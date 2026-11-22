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
            if path.endswith('/runs'):
                data = {'workflow_runs': [
                    {'id': 111, 'head_sha': SHA, 'conclusion': 'failed' if state['failed_run'] else 'success',
                     'status': 'completed', 'run_attempt': 1, 'created_at': '2026-11-22T10:00:00Z'},
                ]}
            elif path.endswith('/artifacts'):
                data = {'artifacts': [
                    {'id': 101, 'name': 'vigilia-results-smoke-111-1', 'expired': False},
                    {'id': 102, 'name': 'vigilia-results-regression-111-1',
                     'expired': state['expire_regression']},
                ]}
            elif '/artifacts/' in path and path.endswith('/zip'):
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
            if path.endswith('/pipelines'):
                data = [{'id': 222, 'sha': OLD_SHA if state['different_revision'] else SHA,
                         'status': 'failed' if state['failed_run'] else 'success',
                         'created_at': '2026-11-22T10:00:00Z'}]
            elif path.endswith('/jobs'):
                data = [
                    {'id': 201, 'name': 'vigilia-regression: [smoke]',
                     'status': 'success', 'artifacts_file': {'size': 300}},
                    {'id': 202, 'name': 'vigilia-regression: [regression]',
                     'status': 'failed' if state['failed_job'] else 'success', 'artifacts_file': {'size': 300}},
                ]
                if state['missing_job']:
                    data.pop()
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
        self.server.state.update(storage_headers=[], bad_sha=False, bad_zip=False,
                                 expire_regression=False, different_revision=False,
                                 missing_job=False, failed_job=False, failed_run=False, no_environment=False)
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

    def test_no_credentials_in_manifest(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.invoke('download')
        data = (self.output / SHA / 'manifest.json').read_text()
        self.assertNotIn('github-test-token', data)
        self.assertNotIn('gitlab-test-token', data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
