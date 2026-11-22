#!/usr/bin/env python3
"""Retrieve and verify revision-matched GitHub/GitLab CI artifacts via REST.

Only trusted configuration supplies API origins. Credentials are read from
GITHUB_TOKEN/GH_TOKEN and GITLAB_TOKEN; never pass secrets on the command line.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
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
PROFILES = ('smoke', 'regression')
HEX = re.compile(r'^[0-9a-f]{7,40}$')


class ArtifactError(RuntimeError):
    pass


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
        headers = {'User-Agent': 'workflow-vigilia-artifact-downloader/1',
                   'Accept': 'application/json' if not download else 'application/zip'}
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
                    # On all redirects remove credentials (even for same host).
                    headers.pop('Authorization', None)
                    headers.pop('PRIVATE-TOKEN', None)
                    continue
                raise ArtifactError(f'{self.provider} API returned HTTP {exc.code} for {path}') from exc
            except urllib.error.URLError as exc:
                raise ArtifactError(f'{self.provider} network error: {exc.reason}') from exc
        raise ArtifactError('Too many redirects')

    def json(self, path, params=None):
        with self.request(path, params) as response:
            raw = response.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ArtifactError('API JSON response exceeds limit')
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ArtifactError('Invalid API JSON response') from exc

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


def validate_zip(path, expected_sha=None):
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
                if len(environment) != 1:
                    raise ArtifactError(f'Expected one primary environment.txt in {path}')
                first = archive.read(environment[0]).split(b'\n', 1)[0].decode('ascii', 'replace')
                if first != expected_sha:
                    raise ArtifactError(f'Embedded revision mismatch in {path}: {first}')
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArtifactError(f'Invalid ZIP archive: {path}') from exc


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
        token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        self.http = RestClient(settings.get('api_base', 'https://api.github.com'), token, 'github')
        self.base = '/repos/' + '/'.join(urllib.parse.quote(x, safe='') for x in self.repo.split('/'))

    def runs(self, branch):
        workflow = urllib.parse.quote(self.workflow, safe='')
        data = self.http.pages(self.base + f'/actions/workflows/{workflow}/runs',
                               {'branch': branch, 'status': 'completed'}, key='workflow_runs')
        return [{'id': int(r['id']), 'sha': r['head_sha'], 'status': r['conclusion'],
                 'attempt': int(r.get('run_attempt', 1)), 'created_at': r.get('created_at', '')}
                for r in data if r.get('status') == 'completed']

    def artifacts(self, run, profiles):
        items = self.http.pages(self.base + f"/actions/runs/{run['id']}/artifacts", key='artifacts')
        found = {}
        for profile in profiles:
            name = f"vigilia-results-{profile}-{run['id']}-{run['attempt']}"
            choices = [a for a in items if a.get('name') == name and not a.get('expired', True)]
            if len(choices) != 1:
                raise ArtifactError(f'GitHub run {run["id"]}: missing or ambiguous artifact {name}')
            found[profile] = {'id': int(choices[0]['id']), 'name': name}
        return found

    def download(self, artifact, dest):
        self.http.zip(self.base + f"/actions/artifacts/{artifact['id']}/zip", dest)


class GitLab:
    def __init__(self, settings):
        self.project = settings['project']
        token = os.environ.get('GITLAB_TOKEN')
        self.http = RestClient(settings.get('api_base', 'https://gitlab.com/api/v4'), token, 'gitlab')
        self.base = '/projects/' + urllib.parse.quote(self.project, safe='')
        self.job_prefix = settings.get('job_prefix', 'vigilia-regression')

    def runs(self, branch):
        data = self.http.pages(self.base + '/pipelines',
                               {'ref': branch, 'order_by': 'id', 'sort': 'desc'})
        return [{'id': int(r['id']), 'sha': r['sha'], 'status': r['status'],
                 'attempt': 1, 'created_at': r.get('created_at', '')}
                for r in data if r.get('status') in ('success', 'failed')]

    def artifacts(self, run, profiles):
        jobs = self.http.pages(self.base + f"/pipelines/{run['id']}/jobs",
                               {'include_retried': 'false'})
        found = {}
        for profile in profiles:
            name = f'{self.job_prefix}: [{profile}]'
            choices = [j for j in jobs if j.get('name') == name and
                       j.get('status') in ('success', 'failed') and
                       isinstance(j.get('artifacts_file'), dict) and
                       j['artifacts_file'].get('size', 0) > 0]
            if len(choices) != 1:
                raise ArtifactError(f'GitLab pipeline {run["id"]}: missing or ambiguous job artifacts {name}')
            found[profile] = {'id': int(choices[0]['id']), 'name': name}
        return found

    def download(self, artifact, dest):
        self.http.zip(self.base + f"/jobs/{artifact['id']}/artifacts", dest)


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
        validate_zip(path, sha)
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
    p.add_argument('command', choices=('list', 'download', 'verify', 'report'))
    p.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    p.add_argument('--provider', action='append', choices=('github', 'gitlab'))
    p.add_argument('--profile', action='append', choices=PROFILES)
    p.add_argument('--mode', choices=('latest', 'latest-successful', 'revision'))
    p.add_argument('--revision', help='Full Git SHA or unambiguous prefix')
    p.add_argument('--branch')
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
        manifest = artifact_verify(directory / rev / 'manifest.json')
        if args.command == 'report':
            for item in manifest['artifacts']:
                print(f"{item['provider']:6} {item['profile']:10} run={item['run_id']} artifact={item['artifact_id']}")
        else:
            print(f'Verified {len(manifest["artifacts"])} archives for {rev}')
        return 0

    providers = list(dict.fromkeys(args.provider or cfg.get('providers', ['github', 'gitlab'])))
    profiles = list(dict.fromkeys(args.profile or cfg.get('profiles', list(PROFILES))))
    if not providers or not profiles:
        raise ArtifactError('At least one provider and profile are required')
    mode = args.mode or cfg.get('selection', {}).get('mode', 'latest-successful')
    revision = args.revision
    if mode == 'revision' and not revision:
        raise ArtifactError('--mode revision requires --revision')
    branch = args.branch or cfg.get('branch', 'ci/regression-integration')
    objects = {provider: (GitHub(cfg['github']) if provider == 'github' else GitLab(cfg['gitlab']))
               for provider in providers}
    candidates = {provider: obj.runs(branch) for provider, obj in objects.items()}
    if args.command == 'list':
        print(json.dumps(candidates, indent=2))
        return 0
    sha, chosen = select(providers, candidates, mode, revision)
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ArtifactError('Unexpected revision from API')
    discovered = {provider: objects[provider].artifacts(chosen[provider], profiles)
                  for provider in providers}

    target = directory / sha
    entries = []
    for provider in providers:
        run = chosen[provider]
        for profile in profiles:
            artifact = discovered[provider][profile]
            relative = f'{provider}/{profile}/artifact-{artifact["id"]}.zip'
            destination = target / relative
            if destination.exists():
                validate_zip(destination, sha)
                print(f'Reusing {destination}')
            else:
                objects[provider].download(artifact, destination)
                validate_zip(destination, sha)
                print(f'Downloaded {destination}')
            entries.append({'provider': provider, 'profile': profile, 'run_id': run['id'],
                            'run_status': run['status'], 'run_attempt': run['attempt'],
                            'artifact_id': artifact['id'], 'artifact_name': artifact['name'],
                            'file': relative, 'sha256': sha256(destination), 'size': destination.stat().st_size})
    manifest = {'schema_version': 1, 'revision': sha, 'branch': branch, 'selection': mode,
                'generated_at': datetime.now(timezone.utc).isoformat(), 'artifacts': entries}
    atomic_json(target / 'manifest.json', manifest)
    bundle = combine(target, manifest, f'workflow-vigilia-ci-{sha[:12]}.zip')
    atomic_json(directory / 'latest.json', {'revision': sha, 'manifest': f'{sha}/manifest.json',
                                            'bundle': f'{sha}/{bundle.name}'})
    print(f'Bundle: {bundle}')
    print(f'Manifest: {target / "manifest.json"}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ArtifactError, KeyError, OSError, ValueError) as exc:
        print(f'Artifact retrieval failed: {exc}', file=sys.stderr)
        sys.exit(1)
