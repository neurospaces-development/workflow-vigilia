#!/usr/bin/env python3
"""Offline REST API regression tests with local GitHub/GitLab emulators."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.parse
import zipfile

import yaml

SHA = 'a12a68e575522285dea96bb61a7edff8d315c60d'
OLD_SHA = 'b' * 40
SCRIPT = Path(__file__).resolve().parent.parent / 'download-artifacts.py'
spec = importlib.util.spec_from_file_location('vigilia_artifacts', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def archive(sha, gitlab):
    out = io.BytesIO()
    name = 'ci-results/run.fixture/environment.txt' if gitlab else 'run.fixture/environment.txt'
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr(name, sha + '\nUbuntu test fixture\n')
        z.writestr('README.txt', 'test evidence\n')
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        state = self.server.state
        path = urllib.parse.urlsplit(self.path).path
        auth = self.headers.get('Authorization')
        private = self.headers.get('PRIVATE-TOKEN')
        if path.startswith('/storage/'):
            state['storage_headers'].append((auth, private))
            state['storage_accepts'].append(self.headers.get('Accept'))
            if auth or private:
                return self.send_error(400)
            identity = int(path.rsplit('/', 1)[1])
            body = archive(OLD_SHA if state['bad_sha'] else SHA, identity >= 200)
            if state['no_environment']:
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as z:
                    z.writestr('bootstrap.log', 'Simulated provisioning failure\n')
                body = stream.getvalue()
            if state['bad_zip']:
                body = b'not-a-zip'
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith('/gh/'):
            if auth != 'Bearer github-test-token' or private:
                return self.send_error(401)
            if path.endswith('/runs/111') or path.endswith('/runs'):
                state['gh_run_reads'] += 1
                pending = state['gh_pending_polls'] > 0
                if pending:
                    state['gh_pending_polls'] -= 1
                item = {'id': 111, 'head_sha': SHA,
                        'conclusion': None if pending else ('failure' if state['failed_run'] else 'success'),
                        'status': 'in_progress' if pending else 'completed',
                        'run_attempt': 1, 'created_at': '2026-11-22T10:00:00Z',
                        'path': '.github/workflows/regression-tests.yml@refs/heads/ci/regression-integration'}
                if path.endswith('/runs/111'):
                    data = item
                else:
                    entries = [] if state['gh_missing_polls'] > 0 else [item]
                    if state['gh_missing_polls'] > 0:
                        state['gh_missing_polls'] -= 1
                    if state['include_old_run']:
                        entries.append({'id': 99, 'head_sha': OLD_SHA, 'conclusion': 'success',
                                        'status': 'completed', 'run_attempt': 1})
                    data = {'workflow_runs': entries}
            elif path.endswith('/artifacts'):
                state['gh_inventory_reads'] += 1
                data = {'artifacts': [
                    {'id': 101, 'name': 'vigilia-results-smoke-111-1', 'expired': False},
                    {'id': 102, 'name': 'vigilia-results-regression-111-1',
                     'expired': state['expire_regression']},
                    {'id': 103, 'name': 'vigilia-docker-pilot-111-1', 'expired': state['expire_docker']},
                ]}
            elif '/artifacts/' in path and path.endswith('/zip'):
                # Match the real GitHub API: incorrect binary Accept values
                # are rejected before the signed artifact-storage redirect.
                state['github_zip_accepts'].append(self.headers.get('Accept'))
                if self.headers.get('Accept') != 'application/vnd.github+json':
                    return self.send_error(415)
                identity = int(path.split('/artifacts/')[1].split('/')[0])
                self.send_response(302)
                self.send_header('Location', f'/storage/{identity}')
                self.end_headers()
                return
            else:
                return self.send_error(404)
        elif path.startswith('/gl/'):
            if private != 'gitlab-test-token' or auth:
                return self.send_error(401)
            if path.endswith('/pipelines/222') or path.endswith('/pipelines'):
                state['gl_run_reads'] += 1
                pending = state['gl_pending_polls'] > 0
                if pending:
                    state['gl_pending_polls'] -= 1
                item = {'id': 222, 'sha': OLD_SHA if state['different_revision'] else SHA,
                        'status': 'running' if pending else ('failed' if state['failed_run'] else 'success'),
                        'created_at': '2026-11-22T10:00:00Z'}
                if path.endswith('/pipelines/222'):
                    data = item
                else:
                    entries = [] if state['gl_missing_polls'] > 0 else [item]
                    if state['gl_missing_polls'] > 0:
                        state['gl_missing_polls'] -= 1
                    if state['include_old_run']:
                        entries.append({'id': 200, 'sha': OLD_SHA, 'status': 'success'})
                    data = entries
            elif path.endswith('/jobs'):
                state['gl_inventory_reads'] += 1
                data = [
                    {'id': 201, 'name': 'vigilia-regression: [smoke]',
                     'status': 'success', 'artifacts_file': {'size': 300}},
                    {'id': 202, 'name': 'vigilia-regression: [regression]',
                     'status': 'failed' if state['failed_job'] else 'success', 'artifacts_file': {'size': 300}},
                    {'id': 203, 'name': 'vigilia-docker-pilot',
                     'status': 'failed' if state['failed_job'] else 'success',
                     'artifacts_file': {'size': 0 if state['missing_docker_artifact'] else 300}},
                ]
                if state['missing_job']:
                    data = [job for job in data if job['id'] != 202]
            elif path.endswith('/artifacts'):
                identity = int(path.split('/jobs/')[1].split('/')[0])
                self.send_response(302)
                self.send_header('Location', f'/storage/{identity}')
                self.end_headers()
                return
            else:
                return self.send_error(404)
        else:
            return self.send_error(404)
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)


class ArtifactDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.state = {}
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vigilia-artifact-test-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.server.state.clear()
        self.server.state.update(storage_headers=[], storage_accepts=[], github_zip_accepts=[],
                                 bad_sha=False, bad_zip=False,
                                 expire_regression=False, expire_docker=False, different_revision=False,
                                 missing_job=False, failed_job=False, failed_run=False,
                                 no_environment=False, missing_docker_artifact=False,
                                 gh_pending_polls=0, gl_pending_polls=0,
                                 gh_missing_polls=0, gl_missing_polls=0, include_old_run=False,
                                 gh_run_reads=0, gl_run_reads=0,
                                 gh_inventory_reads=0, gl_inventory_reads=0)
        port = self.server.server_port
        settings = {'ci_artifacts': {
            'branch': 'ci/regression-integration',
            'providers': ['github', 'gitlab'],
            'profiles': ['smoke', 'regression'],
            'github': {'repository': 'neurospaces-development/workflow-vigilia',
                       'workflow': 'regression-tests.yml', 'api_base': f'http://127.0.0.1:{port}/gh'},
            'gitlab': {'project': 'neurospaces-development/workflow-vigilia',
                       'job_prefix': 'vigilia-regression', 'api_base': f'http://127.0.0.1:{port}/gl'},
            'selection': {'mode': 'latest-successful'},
        }}
        self.cfg = self.folder / 'config.yml'
        self.cfg.write_text(yaml.safe_dump(settings))
        self.output = self.folder / 'results'
        self.env = patch.dict(os.environ, {'GITHUB_TOKEN': 'github-test-token',
                                           'GITLAB_TOKEN': 'gitlab-test-token'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def invoke(self, cmd, *args):
        return mod.main([cmd, '--config', str(self.cfg), '--output', str(self.output), *args])

    def test_download_verify_report_idempotence(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.invoke('list'), 0)
            self.assertEqual(self.invoke('download'), 0)
            self.assertEqual(self.invoke('verify'), 0)
            self.assertEqual(self.invoke('report'), 0)
            self.assertEqual(self.invoke('download'), 0)
        manifest = json.loads((self.output / SHA / 'manifest.json').read_text())
        self.assertEqual(manifest['revision'], SHA)
        self.assertEqual({(a['provider'], a['profile']) for a in manifest['artifacts']},
                         {('github', 'smoke'), ('github', 'regression'),
                          ('gitlab', 'smoke'), ('gitlab', 'regression')})
        bundle = self.output / SHA / f'workflow-vigilia-ci-{SHA[:12]}.zip'
        with zipfile.ZipFile(bundle) as z:
            self.assertIn('manifest.json', z.namelist())
            self.assertEqual(len(z.namelist()), 5)
        self.assertEqual(len(self.server.state['storage_headers']), 4)
        self.assertTrue(all(a is None and b is None for a, b in self.server.state['storage_headers']))
        self.assertEqual(self.server.state['github_zip_accepts'],
                         ['application/vnd.github+json', 'application/vnd.github+json'])
        self.assertEqual(self.server.state['storage_accepts'], ['*/*'] * 4)

    def test_early_failure_artifacts_without_environment(self):
        self.server.state['failed_run'] = True
        self.server.state['failed_job'] = True
        self.server.state['no_environment'] = True
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke('download', '--mode', 'latest'), 0)
            self.assertEqual(self.invoke('verify'), 0)
        manifest = json.loads((self.output / SHA / 'manifest.json').read_text())
        self.assertTrue(all(e['embedded_revision_verified'] is False
                            for e in manifest['artifacts']))

    def test_mismatched_revision_rejected(self):
        self.server.state['different_revision'] = True
        with self.assertRaisesRegex(mod.ArtifactError, 'No common revision'):
            self.invoke('download')

    def test_missing_profile_rejected(self):
        self.server.state['missing_job'] = True
        with self.assertRaisesRegex(mod.ArtifactError, 'missing or ambiguous'):
            self.invoke('download')

    def test_successful_pipeline_with_failed_profile_is_rejected(self):
        self.server.state['failed_job'] = True
        with self.assertRaisesRegex(mod.ArtifactError, 'missing or ambiguous'):
            self.invoke('download')

    def test_expired_github_artifact_rejected(self):
        self.server.state['expire_regression'] = True
        with self.assertRaisesRegex(mod.ArtifactError, 'missing or ambiguous'):
            self.invoke('download')

    def test_bad_zip_rejected(self):
        self.server.state['bad_zip'] = True
        with self.assertRaisesRegex(mod.ArtifactError, 'ZIP'):
            self.invoke('download')

    def test_bad_embedded_sha_rejected(self):
        self.server.state['bad_sha'] = True
        with self.assertRaisesRegex(mod.ArtifactError, 'revision mismatch'):
            self.invoke('download')

    def test_explicit_revision(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.invoke('download', '--mode', 'revision', '--revision', SHA[:12]), 0)
        with self.assertRaisesRegex(mod.ArtifactError, 'No unique revision'):
            self.invoke('download', '--mode', 'revision', '--revision', 'deadbee')

    def test_manifest_integrity(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.invoke('download')
        manifest = self.output / SHA / 'manifest.json'
        item = json.loads(manifest.read_text())['artifacts'][0]
        with (manifest.parent / item['file']).open('ab') as out:
            out.write(b'tamper')
        with self.assertRaisesRegex(mod.ArtifactError, 'modified'):
            self.invoke('verify')

    def test_multiple_module_environments_all_verified(self):
        archive_path = self.folder / 'docker-suite.zip'
        with zipfile.ZipFile(archive_path, 'w') as z:
            z.writestr('ci-results/docker-suite/run.fixture/01-a/run.x/environment.txt',
                       SHA + '\nfirst module\n')
            z.writestr('ci-results/docker-suite/run.fixture/02-b/run.y/environment.txt',
                       SHA + '\nsecond module\n')
        self.assertTrue(mod.validate_zip(archive_path, SHA))
        with zipfile.ZipFile(archive_path, 'w') as z:
            z.writestr('ci-results/docker-suite/run.fixture/01-a/run.x/environment.txt',
                       SHA + '\nfirst module\n')
            z.writestr('ci-results/docker-suite/run.fixture/02-b/run.y/environment.txt',
                       OLD_SHA + '\nsecond module\n')
        with self.assertRaisesRegex(mod.ArtifactError, 'Embedded revision mismatch'):
            mod.validate_zip(archive_path, SHA)

    def test_no_credentials_in_manifest(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.invoke('download')
        data = (self.output / SHA / 'manifest.json').read_text()
        self.assertNotIn('github-test-token', data)
        self.assertNotIn('gitlab-test-token', data)


    def test_inventory_lists_docker_and_ids(self):
        self.server.state['failed_run'] = True
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(self.invoke('inventory', '--mode', 'latest'), 0)
        info = json.loads(captured.getvalue())
        self.assertEqual(info['runs']['github']['id'], 111)
        self.assertEqual(info['runs']['gitlab']['id'], 222)
        self.assertIn(('docker', 103), [(a['profile'], a['id']) for a in info['artifacts']['github']])
        self.assertIn(('docker', 203), [(a['profile'], a['id']) for a in info['artifacts']['gitlab']])

    def test_latest_wait_waits_for_both_providers_before_download(self):
        self.server.state.update(gh_pending_polls=2, gl_pending_polls=3,
                                 gh_missing_polls=1, include_old_run=True)
        observed = []

        def inspect_before_sleep(_):
            observed.append((self.server.state['gh_inventory_reads'],
                             self.server.state['gl_inventory_reads']))

        with patch.object(mod, 'local_git_head', return_value=SHA), \
             patch.object(mod.time, 'sleep', side_effect=inspect_before_sleep), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke('download', '--mode', 'latest-wait',
                                         '--profile', 'docker', '--wait-timeout', '10',
                                         '--poll-interval', '0.01'), 0)
        self.assertGreaterEqual(len(observed), 3)
        self.assertTrue(all(g == 0 and l == 0 for g, l in observed))
        self.assertEqual(self.server.state['gh_inventory_reads'], 1)
        self.assertEqual(self.server.state['gl_inventory_reads'], 1)
        pointer = json.loads((self.output / 'latest.json').read_text())
        manifest = json.loads((self.output / pointer['manifest']).read_text())
        self.assertEqual(manifest['revision'], SHA)
        self.assertEqual(manifest['selection'], 'latest-wait')
        self.assertEqual({a['profile'] for a in manifest['artifacts']}, {'docker'})

    def test_latest_wait_keeps_failed_pipelines(self):
        self.server.state.update(gh_pending_polls=1, gl_pending_polls=1,
                                 failed_run=True, failed_job=True)
        with patch.object(mod, 'local_git_head', return_value=SHA), \
             patch.object(mod.time, 'sleep', return_value=None), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke('download', '--mode', 'latest-wait',
                                         '--profile', 'docker'), 0)
        pointer = json.loads((self.output / 'latest.json').read_text())
        manifest = json.loads((self.output / pointer['manifest']).read_text())
        self.assertEqual({a['run_status'] for a in manifest['artifacts']},
                         {'failure', 'failed'})

    def test_latest_wait_explicit_revision_and_run_id(self):
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.invoke('inventory', '--mode', 'latest-wait',
                                         '--revision', SHA, '--wait-timeout', '0'), 0)
            self.assertEqual(self.invoke('download', '--provider', 'github',
                                         '--run-id', '111', '--profile', 'docker',
                                         '--mode', 'latest-wait', '--wait-timeout', '0'), 0)
        pointer = json.loads((self.output / 'latest.json').read_text())
        self.assertEqual(pointer['revision'], SHA)

    def test_latest_wait_rejects_previous_revision_and_times_out(self):
        self.server.state.update(gh_missing_polls=1000, include_old_run=True)
        with patch.object(mod, 'local_git_head', return_value=SHA), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(mod.ArtifactError, 'Timed out waiting'):
                self.invoke('download', '--mode', 'latest-wait',
                            '--wait-timeout', '0', '--profile', 'docker')
        self.assertEqual(self.server.state['gh_inventory_reads'], 0)
        self.assertFalse((self.output / 'latest.json').exists())

    def test_latest_wait_argument_validation(self):
        with self.assertRaisesRegex(mod.ArtifactError, 'require --mode latest-wait'):
            self.invoke('download', '--wait-timeout', '2')
        with self.assertRaisesRegex(mod.ArtifactError, 'inventory and download only'):
            self.invoke('list', '--mode', 'latest-wait')
        with self.assertRaisesRegex(mod.ArtifactError, 'Expected --wait-timeout'):
            self.invoke('download', '--mode', 'latest-wait', '--poll-interval', '0')
        with self.assertRaisesRegex(mod.ArtifactError, '40-character'):
            self.invoke('download', '--mode', 'latest-wait', '--revision', SHA[:12])
        with self.assertRaisesRegex(mod.ArtifactError, 'not ' + 'f' * 40):
            self.invoke('download', '--provider', 'github', '--mode', 'latest-wait',
                        '--run-id', '111', '--revision', 'f' * 40)

    def test_docker_from_failed_pipelines(self):
        self.server.state['failed_run'] = True
        self.server.state['failed_job'] = True
        self.server.state['no_environment'] = True
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.invoke('download', '--mode', 'latest', '--profile', 'docker'), 0)
            self.assertEqual(self.invoke('verify'), 0)
        pointer = json.loads((self.output / 'latest.json').read_text())
        manifest = json.loads((self.output / pointer['manifest']).read_text())
        self.assertEqual({(a['provider'], a['artifact_id']) for a in manifest['artifacts']},
                         {('github', 103), ('gitlab', 203)})
        self.assertTrue(all(not a['embedded_revision_verified'] for a in manifest['artifacts']))

    def test_explicit_run_artifact_id_and_gitlab_job_id(self):
        for provider, run_id, artifact_id in [('github', 111, 103), ('gitlab', 222, 203)]:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.invoke('download', '--provider', provider,
                                             '--run-id', str(run_id), '--id', str(artifact_id)), 0)
                self.assertEqual(self.invoke('verify'), 0)
            pointer = json.loads((self.output / 'latest.json').read_text())
            manifest = json.loads((self.output / pointer['manifest']).read_text())
            self.assertEqual([e['artifact_id'] for e in manifest['artifacts']], [artifact_id])
            self.assertEqual(manifest['artifacts'][0]['profile'], 'docker')

    def test_glob_and_all_artifacts(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.invoke('download', '--name', '*docker-pilot*'), 0)
        pointer = json.loads((self.output / 'latest.json').read_text())
        manifest = json.loads((self.output / pointer['manifest']).read_text())
        self.assertEqual(len(manifest['artifacts']), 2)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.invoke('download', '--all'), 0)
            self.assertEqual(self.invoke('verify'), 0)
        pointer = json.loads((self.output / 'latest.json').read_text())
        manifest = json.loads((self.output / pointer['manifest']).read_text())
        self.assertEqual(len(manifest['artifacts']), 6)

    def test_custom_selection_preserves_previous_bundle(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.invoke('download')
        legacy = self.output / SHA / 'manifest.json'
        original = legacy.read_bytes()
        normal_bundle = self.output / SHA / f'workflow-vigilia-ci-{SHA[:12]}.zip'
        self.assertTrue(normal_bundle.is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            self.invoke('download', '--provider', 'github', '--profile', 'docker')
            self.invoke('verify')
        pointer = json.loads((self.output / 'latest.json').read_text())
        self.assertNotEqual(pointer['manifest'], f'{SHA}/manifest.json')
        self.assertEqual(legacy.read_bytes(), original)
        self.assertTrue(normal_bundle.is_file())
        self.assertTrue((self.output / pointer['bundle']).is_file())

    def test_selector_errors(self):
        with self.assertRaisesRegex(mod.ArtifactError, 'only one'):
            self.invoke('download', '--all', '--profile', 'docker')
        with self.assertRaisesRegex(mod.ArtifactError, 'one provider'):
            self.invoke('download', '--run-id', '111')
        with self.assertRaisesRegex(mod.ArtifactError, 'requires one provider'):
            self.invoke('download', '--provider', 'github', '--id', '103')
        with self.assertRaisesRegex(mod.ArtifactError, 'unavailable'):
            self.invoke('download', '--provider', 'github', '--run-id', '111', '--id', '999')

    def test_inventory_shows_missing_artifacts(self):
        self.server.state['missing_docker_artifact'] = True
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.invoke('inventory', '--provider', 'gitlab')
        jobs = json.loads(captured.getvalue())['artifacts']['gitlab']
        self.assertFalse(next(j for j in jobs if j['id'] == 203)['available'])
        with self.assertRaisesRegex(mod.ArtifactError, 'missing or ambiguous'):
            self.invoke('download', '--provider', 'gitlab', '--profile', 'docker')


if __name__ == '__main__':
    unittest.main(verbosity=2)
