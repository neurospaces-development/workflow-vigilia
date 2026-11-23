#!/usr/bin/env python3
"""Retrieve and verify revision-matched GitHub/GitLab CI artifacts via REST.

Only trusted configuration supplies API origins. Credentials are read from
GITHUB_TOKEN/GH_TOKEN and GITLAB_TOKEN; never pass secrets on the command line.
"""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / 'configured-workflows/automation-configuration-data/ci_artifacts.yml'
MAX_JSON = 8 * 1024 * 1024
MAX_ZIP = 512 * 1024 * 1024
PROFILES = ('smoke', 'regression', 'docker', 'full')
MAX_SELECTED_ARTIFACTS = 50
DEFAULT_WAIT_TIMEOUT = 1800  # seconds
DEFAULT_POLL_INTERVAL = 15  # seconds
# Read-only REST metadata requests may fail transiently while polling.
JSON_RETRY_DELAYS = (1, 2, 4)  # seconds between attempts; four attempts total
TERMINAL_GITHUB = frozenset(('success', 'failure', 'neutral', 'cancelled',
                             'skipped', 'timed_out', 'action_required', 'stale', 'completed'))
TERMINAL_GITLAB = frozenset(('success', 'failed', 'canceled', 'skipped'))
HEX = re.compile(r'^[0-9a-f]{7,40}$')


class ArtifactError(RuntimeError):
    pass


class TransientArtifactError(ArtifactError):
    """Temporary API/network failure for a safely repeatable GET request."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RestClient:
    def __init__(self, base, token, provider):
        self.base = base.rstrip('/')
        self.token = token
        self.provider = provider
        parsed = urllib.parse.urlsplit(self.base)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and
                parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ArtifactError('API base must use HTTPS (except loopback test servers)')
        self.origin = parsed.netloc
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, params=None, download=False):
        url = self.base + path
        if params:
            url += '?' + urllib.parse.urlencode(params)
        # GitHub's Actions artifact ZIP endpoint is an API endpoint returning
        # a redirect, not a binary endpoint. It rejects Accept: application/zip
        # with HTTP 415. Use GitHub's API media type even for downloads.
        accept = ('application/vnd.github+json' if self.provider == 'github'
                  else ('application/zip' if download else 'application/json'))
        headers = {'User-Agent': 'workflow-vigilia-artifact-downloader/1',
                   'Accept': accept}
        if self.provider == 'github':
            headers['X-GitHub-Api-Version'] = '2022-11-28'
        if self.token:
            if self.provider == 'github':
                headers['Authorization'] = 'Bearer ' + self.token
            else:
                headers['PRIVATE-TOKEN'] = self.token
        # Do not send credentials to redirected artifact-storage domains.
        for hop in range(5):
            req = urllib.request.Request(url, headers=headers)
            try:
                return self.opener.open(req, timeout=40)
            except urllib.error.HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    location = exc.headers.get('Location')
                    if not location:
                        raise ArtifactError('Redirect without Location header') from exc
                    redirected = urllib.parse.urljoin(url, location)
                    parsed = urllib.parse.urlsplit(redirected)
                    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and
                            parsed.hostname in ('localhost', '127.0.0.1', '::1')):
                        raise ArtifactError('Unsafe artifact redirect') from exc
                    url = redirected
                    # Signed storage URLs must never receive API credentials
                    # or API-specific content negotiation headers.
                    headers.pop('Authorization', None)
                    headers.pop('PRIVATE-TOKEN', None)
                    headers.pop('X-GitHub-Api-Version', None)
                    headers['Accept'] = '*/*'
                    continue
                if exc.code in (429, 500, 502, 503, 504):
                    raise TransientArtifactError(
                        f'{self.provider} API returned HTTP {exc.code} for {path}') from exc
                raise ArtifactError(f'{self.provider} API returned HTTP {exc.code} for {path}') from exc
            except urllib.error.URLError as exc:
                raise TransientArtifactError(
                    f'{self.provider} network error: {exc.reason}') from exc
            except (TimeoutError, ConnectionError) as exc:
                raise TransientArtifactError(
                    f'{self.provider} connection error for {path}: {exc}') from exc
        raise ArtifactError('Too many redirects')

    def json(self, path, params=None):
        # All metadata requests are GETs. Retry only transient failures, not
        # authentication errors, invalid configuration or artifact mismatches.
        for attempt in range(len(JSON_RETRY_DELAYS) + 1):
            try:
                with self.request(path, params) as response:
                    content_type = response.headers.get('Content-Type', 'unknown')
                    raw = response.read(MAX_JSON + 1)
                if len(raw) > MAX_JSON:
                    raise ArtifactError('API JSON response exceeds limit')
                try:
                    return json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    # A proxy/gateway can occasionally return HTML or an
                    # incomplete HTTP 200 body. Avoid logging response data,
                    # which could contain private information.
                    raise TransientArtifactError(
                        f'Invalid API JSON response from {self.provider} for {path} '
                        f'(Content-Type: {content_type}, {len(raw)} bytes)') from exc
            except TransientArtifactError as exc:
                if attempt == len(JSON_RETRY_DELAYS):
                    raise ArtifactError(
                        f'{exc}; exhausted {attempt + 1} attempts') from exc
                delay = JSON_RETRY_DELAYS[attempt]
                print(f'Warning: {exc}; retrying in {delay}s '
                      f'(attempt {attempt + 2}/{len(JSON_RETRY_DELAYS) + 1})',
                      file=sys.stderr, flush=True)
                time.sleep(delay)

    def pages(self, path, params=None, key=None, limit=3):
        result = []
        for page in range(1, limit + 1):
            data = self.json(path, {**(params or {}), 'per_page': 100, 'page': page})
            values = data.get(key) if key else data
            if not isinstance(values, list):
                raise ArtifactError(f'Unexpected API pagination response: {path}')
            result.extend(values)
            if len(values) < 100:
                break
        return result

    def zip(self, path, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.artifact-', dir=destination.parent)
        try:
            count = 0
            with os.fdopen(fd, 'wb') as output, self.request(path, download=True) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > MAX_ZIP:
                        raise ArtifactError('Artifact ZIP exceeds size limit')
                    output.write(chunk)
            validate_zip(Path(temporary))
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def validate_zip(path, expected_sha=None, allow_missing_environment=False):
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > 10000 or sum(i.file_size for i in infos) > 2 * MAX_ZIP:
                raise ArtifactError(f'Invalid ZIP inventory: {path}')
            if archive.testzip() is not None:
                raise ArtifactError(f'ZIP checksum failure: {path}')
            if expected_sha:
                environment = [i for i in infos if i.filename.endswith('/environment.txt')
                               and '/negative-probe/' not in '/' + i.filename and i.file_size < 32768]
                if not environment and allow_missing_environment:
                    return False  # Early job failures may only have bootstrap logs.
                # A serial Docker suite produces one independent report and
                # environment.txt per module. Verify *every* embedded revision,
                # not just the first one, to preserve provenance of the bundle.
                if not environment:
                    raise ArtifactError(f'Expected at least one environment.txt in {path}')
                for entry in environment:
                    first = archive.read(entry).split(b'\n', 1)[0].decode('ascii', 'replace')
                    if first != expected_sha:
                        raise ArtifactError(
                            f'Embedded revision mismatch in {path} '
                            f'({entry.filename}): {first}')
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArtifactError(f'Invalid ZIP archive: {path}') from exc
    return bool(expected_sha)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as inp:
        for chunk in iter(lambda: inp.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.manifest-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, indent=2, sort_keys=True)
            out.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class GitHub:
    def __init__(self, settings):
        self.repo = settings['repository']
        self.workflow = settings['workflow']
        self.names = settings.get('artifact_names', {})
        token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        self.http = RestClient(settings.get('api_base', 'https://api.github.com'), token, 'github')
        self.base = '/repos/' + '/'.join(urllib.parse.quote(x, safe='') for x in self.repo.split('/'))

    @staticmethod
    def normalize_run(r):
        return {'id': int(r['id']), 'sha': r['head_sha'],
                'status': (r.get('conclusion') or 'completed') if r.get('status') == 'completed'
                          else r.get('status', 'unknown'),
                'attempt': int(r.get('run_attempt', 1)), 'created_at': r.get('created_at', ''),
                'branch': r.get('head_branch')}

    def runs(self, branch, include_incomplete=False):
        workflow = urllib.parse.quote(self.workflow, safe='')
        params = {'branch': branch}
        if not include_incomplete:
            params['status'] = 'completed'
        data = self.http.pages(self.base + f'/actions/workflows/{workflow}/runs',
                               params, key='workflow_runs')
        return [self.normalize_run(r) for r in data
                if include_incomplete or r.get('status') == 'completed']

    def run(self, run_id, include_incomplete=False):
        r = self.http.json(self.base + f'/actions/runs/{run_id}')
        if not include_incomplete and r.get('status') != 'completed':
            raise ArtifactError(f'GitHub run {run_id} is not completed')
        workflow = r.get('path', '').split('@', 1)[0]
        if workflow and workflow.split('/')[-1] != self.workflow:
            raise ArtifactError(f'GitHub run {run_id} belongs to a different workflow')
        return self.normalize_run(r)

    def expected_name(self, profile, run):
        patterns = {
            'smoke': 'vigilia-results-smoke-{run_id}-{attempt}',
            'regression': 'vigilia-results-regression-{run_id}-{attempt}',
            'docker': 'vigilia-docker-pilot-{run_id}-{attempt}',
            'full': 'vigilia-full-{run_id}-{attempt}',
        }
        pattern = self.names.get(profile, patterns[profile])
        return pattern.format(run_id=run['id'], attempt=run['attempt'])

    def inventory(self, run):
        items = self.http.pages(self.base + f"/actions/runs/{run['id']}/artifacts", key='artifacts')
        result = []
        for a in items:
            profile = next((p for p in PROFILES if a.get('name') == self.expected_name(p, run)), None)
            result.append({'id': int(a['id']), 'name': a['name'], 'profile': profile,
                           'status': 'expired' if a.get('expired', True) else 'available',
                           'available': not a.get('expired', True),
                           'size': int(a.get('size_in_bytes') or 0)})
        return result

    def download(self, artifact, dest):
        self.http.zip(self.base + f"/actions/artifacts/{artifact['id']}/zip", dest)


class GitLab:
    def __init__(self, settings):
        self.project = settings['project']
        token = os.environ.get('GITLAB_TOKEN')
        self.http = RestClient(settings.get('api_base', 'https://gitlab.com/api/v4'), token, 'gitlab')
        self.base = '/projects/' + urllib.parse.quote(self.project, safe='')
        self.job_prefix = settings.get('job_prefix', 'vigilia-regression')
        self.names = settings.get('job_names', {})

    @staticmethod
    def normalize_run(r):
        return {'id': int(r['id']), 'sha': r['sha'], 'status': r['status'],
                'attempt': 1, 'created_at': r.get('created_at', ''),
                'branch': r.get('ref')}

    def runs(self, branch, include_incomplete=False):
        data = self.http.pages(self.base + '/pipelines',
                               {'ref': branch, 'order_by': 'id', 'sort': 'desc'})
        return [self.normalize_run(r) for r in data
                if include_incomplete or r.get('status') in ('success', 'failed', 'canceled')]

    def run(self, run_id, include_incomplete=False):
        r = self.http.json(self.base + f'/pipelines/{run_id}')
        if not include_incomplete and r.get('status') not in ('success', 'failed', 'canceled'):
            raise ArtifactError(f'GitLab pipeline {run_id} is not completed')
        return self.normalize_run(r)

    def expected_name(self, profile, run):
        names = {'smoke': f'{self.job_prefix}: [smoke]',
                 'regression': f'{self.job_prefix}: [regression]',
                 'docker': 'vigilia-docker-pilot',
                 'full': 'vigilia-full'}
        return self.names.get(profile, names[profile])

    def inventory(self, run):
        jobs = self.http.pages(self.base + f"/pipelines/{run['id']}/jobs",
                               {'include_retried': 'false'})
        result = []
        for j in jobs:
            size = (j.get('artifacts_file') or {}).get('size', 0)
            profile = next((p for p in PROFILES if j.get('name') == self.expected_name(p, run)), None)
            result.append({'id': int(j['id']), 'name': j['name'], 'profile': profile,
                           'status': j.get('status', 'unknown'),
                           'available': isinstance(size, int) and size > 0,
                           'size': int(size or 0)})
        return result

    def download(self, artifact, dest):
        self.http.zip(self.base + f"/jobs/{artifact['id']}/artifacts", dest)


def choose_artifacts(provider, client, run, inventory, profiles, names, all_artifacts, ids, require_success):
    """Choose job artifact archives; never infer success from artifact presence."""
    available = [a for a in inventory if a['available'] and
                 (not require_success or a['status'] in ('available', 'success'))]
    if ids:
        wanted = set(ids)
        choices = [a for a in available if a['id'] in wanted]
        if {a['id'] for a in choices} != wanted:
            raise ArtifactError(f'{provider} run {run["id"]}: requested artifact/job ID unavailable')
    elif profiles:
        choices = []
        for profile in profiles:
            matches = [a for a in available if a['name'] == client.expected_name(profile, run)]
            if len(matches) != 1:
                raise ArtifactError(f'{provider} run {run["id"]}: missing or ambiguous {profile} artifact')
            choices += matches
    elif names:
        choices = [a for a in available if any(fnmatch.fnmatchcase(a['name'], g) for g in names)]
    elif all_artifacts:
        choices = available
    else:
        raise ArtifactError('No artifact selector supplied')
    if not choices:
        raise ArtifactError(f'{provider} run {run["id"]}: no matching artifact archives')
    if len(choices) > MAX_SELECTED_ARTIFACTS:
        raise ArtifactError(f'Too many artifact archives selected ({len(choices)} > {MAX_SELECTED_ARTIFACTS})')
    return choices

def select(providers, candidates, mode, revision):
    if revision:
        if not HEX.fullmatch(revision):
            raise ArtifactError('Revision must be 7–40 lowercase hexadecimal characters')
        common = {r['sha'] for runs in candidates.values() for r in runs if r['sha'].startswith(revision)}
        if len(common) != 1:
            raise ArtifactError(f'No unique revision matching {revision}')
        revision = common.pop()

    selected = {}
    for provider in providers:
        runs = candidates[provider]
        if mode == 'latest-successful':
            runs = [r for r in runs if r['status'] == 'success']
        if revision:
            runs = [r for r in runs if r['sha'] == revision]
        if not runs:
            raise ArtifactError(f'No matching completed {provider} runs')
        selected[provider] = runs

    if revision is None:
        common = set(r['sha'] for r in selected[providers[0]])
        for provider in providers[1:]:
            common.intersection_update(r['sha'] for r in selected[provider])
        if not common:
            raise ArtifactError('No common revision across the selected providers')
        # Most recent common revision as observed by the first provider.
        revision = next(r['sha'] for r in selected[providers[0]] if r['sha'] in common)

    return revision, {provider: next(r for r in selected[provider] if r['sha'] == revision)
                      for provider in providers}


def local_git_head():
    """Use the source checkout, not an arbitrary directory under the caller's cwd."""
    try:
        revision = subprocess.check_output(
            ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
            stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ArtifactError('latest-wait requires a Git checkout or --revision FULL_SHA') from exc
    return revision


def wait_for_runs(providers, objects, branch, revision, run_id, timeout, interval):
    """Wait for all selected providers on one fixed SHA, even if CI starts late.

    Never fall back to an earlier completed revision while this SHA is queued.
    No artifact inventory/download requests are issued during polling.
    """
    if run_id is not None:
        # Explicit run identity takes precedence over the local checkout.
        run = objects[providers[0]].run(run_id, include_incomplete=True)
        target = run['sha']
        if revision is not None and target != revision:
            raise ArtifactError(f'Run {run_id} has revision {target}, not {revision}')
    else:
        target = revision or local_git_head()
    if not re.fullmatch(r'[0-9a-f]{40}', target):
        raise ArtifactError('latest-wait needs a full 40-character revision (--revision FULL_SHA)')

    deadline = time.monotonic() + timeout
    previous = None
    while True:
        selected = {}
        display = []
        complete = True
        for provider in providers:
            if run_id is not None:
                runs = [objects[provider].run(run_id, include_incomplete=True)]
            else:
                runs = objects[provider].runs(branch, include_incomplete=True)
            match = next((r for r in runs if r['sha'] == target), None)
            if match is None:
                complete = False
                display.append(f'{provider}=not-started')
                continue
            selected[provider] = match
            terminal = TERMINAL_GITHUB if provider == 'github' else TERMINAL_GITLAB
            if match['status'] not in terminal:
                complete = False
            display.append(f"{provider}={match['status']} (run {match['id']})")

        state = tuple(display)
        if state != previous:
            print(f"CI revision {target[:12]}: {', '.join(display)}", file=sys.stderr, flush=True)
            previous = state
        if complete:
            print(f'All requested CI pipelines finished for {target}', file=sys.stderr, flush=True)
            return target, selected
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ArtifactError(f"Timed out waiting for {target} after {timeout}s: {', '.join(display)}")
        time.sleep(min(interval, remaining))


def config_load(path):
    with path.open(encoding='utf-8') as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict) or not isinstance(result.get('ci_artifacts'), dict):
        raise ArtifactError('Configuration must contain ci_artifacts mapping')
    return result['ci_artifacts']


def artifact_verify(manifest_path):
    with manifest_path.open(encoding='utf-8') as stream:
        manifest = json.load(stream)
    sha = manifest['revision']
    for entry in manifest['artifacts']:
        path = manifest_path.parent / entry['file']
        if path.resolve().is_relative_to(manifest_path.parent.resolve()) is False:
            raise ArtifactError('Unsafe path in artifact manifest')
        if not path.is_file() or sha256(path) != entry['sha256']:
            raise ArtifactError(f'Missing or modified artifact: {path}')
        verified = validate_zip(path, sha, allow_missing_environment=not entry.get('embedded_revision_verified', True))
        if verified != entry.get('embedded_revision_verified', True):
            raise ArtifactError(f'Embedded revision verification changed: {path}')
    return manifest


def combine(directory, manifest, name):
    destination = directory / name
    temporary = directory / ('.' + name + '.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as out:
            out.writestr('manifest.json', json.dumps(manifest, indent=2, sort_keys=True) + '\n')
            for entry in manifest['artifacts']:
                out.write(directory / entry['file'], entry['file'])
        validate_zip(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('list', 'inventory', 'download', 'verify', 'report'))
    p.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    p.add_argument('--provider', action='append', choices=('github', 'gitlab'))
    p.add_argument('--profile', action='append', choices=PROFILES)
    p.add_argument('--mode', choices=('latest', 'latest-successful', 'latest-wait', 'revision'))
    p.add_argument('--revision', help='Git SHA (full 40-character SHA required for latest-wait)')
    p.add_argument('--wait-timeout', type=float, help='Maximum seconds to wait (default: 1800)')
    p.add_argument('--poll-interval', type=float, help='Seconds between checks (default: 15)')
    p.add_argument('--branch')
    p.add_argument('--run-id', type=int, help='GitHub workflow-run or GitLab pipeline ID (one provider)')
    p.add_argument('--id', action='append', type=int, help='Exact GitHub artifact or GitLab job ID')
    p.add_argument('--name', action='append', help='Glob matching GitHub artifact or GitLab job name')
    p.add_argument('--all', action='store_true', help='All available artifact archives in selected run')
    p.add_argument('--output', type=Path)
    args = p.parse_args(argv)
    cfg = config_load(args.config)
    directory = (args.output or ROOT / cfg.get('download', {}).get('directory', 'ci-artifacts')).resolve()
    if args.command in ('verify', 'report'):
        latest = directory / 'latest.json'
        if not latest.is_file():
            raise ArtifactError(f'No latest.json at {latest}')
        pointer = json.loads(latest.read_text(encoding='utf-8'))
        rev = pointer['revision']
        if not re.fullmatch('[0-9a-f]{40}', rev):
            raise ArtifactError('Invalid latest revision')
        manifest_rel = pointer.get('manifest', f'{rev}/manifest.json')
        manifest_file = directory / manifest_rel
        if not manifest_file.resolve().is_relative_to((directory / rev).resolve()):
            raise ArtifactError('Unsafe latest manifest pointer')
        manifest = artifact_verify(manifest_file)
        if args.command == 'report':
            for item in manifest['artifacts']:
                print(f"{item['provider']:6} {item['profile']:10} run={item['run_id']} artifact={item['artifact_id']} name={item['artifact_name']}")
        else:
            print(f'Verified {len(manifest["artifacts"])} archives for {rev}')
        return 0

    providers = list(dict.fromkeys(args.provider or cfg.get('providers', ['github', 'gitlab'])))
    if not providers:
        raise ArtifactError('At least one provider required')
    selectors = sum(bool(x) for x in (args.profile, args.name, args.all, args.id))
    if selectors > 1:
        raise ArtifactError('Use only one of --profile, --name, --all, or --id')
    if args.run_id is not None and (args.run_id < 1 or len(providers) != 1):
        raise ArtifactError('--run-id requires one provider and a positive ID')
    if args.id and (len(providers) != 1 or args.run_id is None or any(i < 1 for i in args.id)):
        raise ArtifactError('--id requires one provider and --run-id')
    if args.command == 'inventory' and (args.name or args.profile or args.all or args.id):
        raise ArtifactError('inventory lists all jobs; selection flags are for download')
    if args.mode == 'revision' and not args.revision:
        raise ArtifactError('--mode revision requires --revision')
    mode = args.mode or cfg.get('selection', {}).get('mode', 'latest-successful')
    if mode != 'latest-wait' and (args.wait_timeout is not None or args.poll_interval is not None):
        raise ArtifactError('--wait-timeout and --poll-interval require --mode latest-wait')
    if mode == 'latest-wait' and args.command == 'list':
        raise ArtifactError('--mode latest-wait is supported for inventory and download only')
    if mode == 'latest-wait':
        timeout = DEFAULT_WAIT_TIMEOUT if args.wait_timeout is None else args.wait_timeout
        interval = DEFAULT_POLL_INTERVAL if args.poll_interval is None else args.poll_interval
        if not (0 <= timeout <= 86400 and 0 < interval <= 3600):
            raise ArtifactError('Expected --wait-timeout 0..86400 and --poll-interval >0..3600 seconds')
    revision = args.revision
    branch = args.branch or cfg.get('branch', 'ci/regression-integration')
    objects = {provider: (GitHub(cfg['github']) if provider == 'github' else GitLab(cfg['gitlab']))
               for provider in providers}
    if mode == 'latest-wait':
        sha, chosen = wait_for_runs(providers, objects, branch, revision, args.run_id,
                                    timeout, interval)
    else:
        if args.run_id is not None:
            only = providers[0]
            candidates = {only: [objects[only].run(args.run_id)]}
            if mode == 'latest-successful' and candidates[only][0]['status'] != 'success':
                # Explicit IDs identify the requested run, including failed pilots.
                mode = 'latest'
        else:
            candidates = {provider: obj.runs(branch) for provider, obj in objects.items()}
        if args.command == 'list':
            print(json.dumps(candidates, indent=2))
            return 0
        sha, chosen = select(providers, candidates, mode, revision)
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ArtifactError('Unexpected revision from API')
    if args.command == 'inventory':
        print(json.dumps({'revision': sha, 'runs': chosen,
                          'artifacts': {provider: objects[provider].inventory(chosen[provider])
                                        for provider in providers}}, indent=2))
        return 0

    profiles = list(dict.fromkeys(args.profile or []))
    if not selectors:
        profiles = list(dict.fromkeys(cfg.get('profiles', ['smoke', 'regression'])))
    discovered = {}
    for provider in providers:
        discovered[provider] = choose_artifacts(provider, objects[provider], chosen[provider],
            objects[provider].inventory(chosen[provider]), profiles, args.name or [], args.all,
            args.id or [], mode == 'latest-successful')

    target = directory / sha
    entries = []
    for provider in providers:
        run = chosen[provider]
        for artifact in discovered[provider]:
            profile = artifact['profile'] or 'custom'
            # Preserve the familiar directory structure for named profiles.
            category = profile if profile in PROFILES else 'selected'
            relative = f'{provider}/{category}/artifact-{artifact["id"]}.zip'
            destination = target / relative
            allow_missing = run['status'] != 'success' or artifact['status'] == 'failed'
            if destination.exists():
                verified = validate_zip(destination, sha, allow_missing)
                print(f'Reusing {destination}')
            else:
                objects[provider].download(artifact, destination)
                verified = validate_zip(destination, sha, allow_missing)
                print(f'Downloaded {destination}')
            if not verified:
                print(f'Warning: job without environment.txt; revision verified only by provider API: {destination}', file=sys.stderr)
            entries.append({'provider': provider, 'profile': profile, 'run_id': run['id'],
                            'run_status': run['status'], 'run_attempt': run['attempt'],
                            'job_status': artifact['status'],
                            'artifact_id': artifact['id'], 'artifact_name': artifact['name'],
                            'file': relative, 'sha256': sha256(destination), 'size': destination.stat().st_size,
                            'embedded_revision_verified': verified})
    manifest = {'schema_version': 1, 'revision': sha,
                'branch': chosen[providers[0]].get('branch') or branch, 'selection': mode,
                'generated_at': datetime.now(timezone.utc).isoformat(), 'artifacts': entries}

    # Preserve independent selections of the same revision; a Docker-pilot
    # diagnosis must not overwrite the earlier smoke/regression evidence.
    key = json.dumps([(a['provider'], a['artifact_id'], a['run_id']) for a in entries], sort_keys=True)
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
    default_selection = (not selectors and not args.run_id and not args.revision and
                         len(providers) == len(cfg.get('providers', ['github', 'gitlab'])) and
                         set(providers) == set(cfg.get('providers', ['github', 'gitlab'])))
    manifest_name = 'manifest.json' if default_selection else f'manifest-{digest}.json'
    bundle_name = (f'workflow-vigilia-ci-{sha[:12]}.zip' if default_selection else
                   f'workflow-vigilia-ci-{sha[:12]}-{digest}.zip')
    atomic_json(target / manifest_name, manifest)
    bundle = combine(target, manifest, bundle_name)
    atomic_json(directory / 'latest.json', {'revision': sha, 'manifest': f'{sha}/{manifest_name}',
                                            'bundle': f'{sha}/{bundle.name}'})
    print(f'Bundle: {bundle}')
    print(f'Manifest: {target / manifest_name}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ArtifactError, KeyError, OSError, ValueError) as exc:
        print(f'Artifact retrieval failed: {exc}', file=sys.stderr)
        sys.exit(1)
