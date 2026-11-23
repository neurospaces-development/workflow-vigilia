#!/usr/bin/env python3
"""Offline report analysis tests using two synthetic provider artifact archives."""
import contextlib
from datetime import datetime
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import yaml

SCRIPT = Path(__file__).resolve().parents[1] / 'report-analysis.py'
spec = importlib.util.spec_from_file_location('vigilia_report_analysis', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA = 'a12a68e575522285dea96bb61a7edff8d315c60d'


class ReportAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vigilia-report-analysis-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        base = self.root / SHA
        manifest = {'revision': SHA, 'artifacts': []}
        for provider, failed in [('github', False), ('gitlab', True)]:
            report = {
                'global': {'status': 'Finished', 'error_count': int(failed),
                           'time_start': datetime(2026, 11, 23, 12, 0, 0),
                           'time_end': datetime(2026, 11, 23, 12, 3, 5),
                           'test_counters': {'executed_totals': {'command_test': 2},
                                             'discovered_totals': {'command_test': 3}}},
                'timings': {'module/a.t': {'first': 1.2, 'second': 2.3}},
            }
            if failed:
                report['errors'] = {'error_reports': {'1': {
                    'module_name': 'module/a.t', 'description': 'expected value',
                    'error': '1:TIMEOUT', 'executed_command': 'sleep 300'}}}
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as z:
                z.writestr('run.fixture/environment.txt', SHA + '\n')
                z.writestr('run.fixture/report/report.yml', yaml.safe_dump(report))
            location = f'{provider}/full/artifact-100.zip'
            filename = base / location
            filename.parent.mkdir(parents=True, exist_ok=True)
            filename.write_bytes(data.getvalue())
            manifest['artifacts'].append({
                'provider': provider, 'profile': 'full', 'run_status': 'failed' if failed else 'success',
                'job_status': 'failed' if failed else 'available', 'file': location,
                'sha256': hashlib.sha256(data.getvalue()).hexdigest(),
                'embedded_revision_verified': True,
            })
        (base / 'manifest.json').write_text(json.dumps(manifest))
        (self.root / 'latest.json').write_text(json.dumps({
            'revision': SHA, 'manifest': f'{SHA}/manifest.json'}))

    def invoke(self, command, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(mod.main([command, '--directory', str(self.root), *argv]), 0)
        return json.loads(output.getvalue())

    def test_results_are_revision_matched_and_verified(self):
        result = self.invoke('results')
        self.assertEqual(result['revision'], SHA)
        self.assertEqual([r['executed'] for r in result['records']], [2, 2])
        self.assertEqual([r['duration_seconds'] for r in result['records']], [185.0, 185.0])

    def test_failure_details_do_not_include_successful_provider(self):
        failure = self.invoke('failures')
        self.assertEqual(len(failure['failures']), 1)
        self.assertEqual(failure['failures'][0]['provider'], 'gitlab')
        self.assertEqual(failure['failures'][0]['errors'][0]['module'], 'module/a.t')

    def test_compare_and_native_timings(self):
        comparison = self.invoke('compare')
        self.assertEqual(comparison['providers']['github']['errors'], 0)
        self.assertEqual(comparison['providers']['gitlab']['errors'], 1)
        times = self.invoke('timings', '--last', '2', '--top', '1')
        self.assertEqual(times['runs'][0]['providers'][0]['slowest_modules'][0]['assertion_seconds'], 3.5)

    def test_modified_archive_is_rejected(self):
        path = self.root / SHA / 'github/full/artifact-100.zip'
        path.write_bytes(path.read_bytes() + b'corrupt')
        with self.assertRaises(mod.artifacts.ArtifactError):
            self.invoke('results')


if __name__ == '__main__':
    unittest.main(verbosity=2)
