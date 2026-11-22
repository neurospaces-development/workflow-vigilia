#!/usr/bin/env python3
"""Offline regressions for serial, independently evidenced Docker CI modules.

A fake repository, test entry point, and docker CLI avoid requiring a daemon,
Perl dependencies or GitHub/GitLab access on the developer's workstation.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'docker-suite.sh'
MODULES = ('20_vigilia/30_docker.t',
           '20_vigilia/12_error_checking/summary.yml')
FAKE_TEST = '''#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s|%s|%s\\n' "$VIGILIA_REGEX_SELECTOR" "${1:-<build>}" \
    "$CI_RESULTS_DIR" "${VIGILIA_TEST_PROFILE:-<unset>}" >> "$FAKE_TEST_LOG"
mkdir -p "$CI_RESULTS_DIR/run.fixture/report"
printf 'tested\\n' > "$CI_RESULTS_DIR/run.fixture/report/report.yml"
if [[ -n "${FAKE_FAIL_SELECTOR:-}" && "$VIGILIA_REGEX_SELECTOR" == *"$FAKE_FAIL_SELECTOR"* ]]; then
    exit 7
fi
'''
FAKE_DOCKER = '''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
if [[ "${1:-}" == info && "${FAKE_DOCKER_UNAVAILABLE:-0}" == 1 ]]; then
    exit 3
fi
'''


class DockerSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vigilia-docker-suite-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'ci').mkdir()
        (self.root / 'bin').mkdir()
        shutil.copyfile(SOURCE, self.root / 'ci/docker-suite.sh')
        self.test_file = self.root / 'ci/test.sh'
        self.test_file.write_text(FAKE_TEST)
        self.test_file.chmod(0o755)
        self.docker_file = self.root / 'bin/docker'
        self.docker_file.write_text(FAKE_DOCKER)
        self.docker_file.chmod(0o755)
        self.modules_file = self.root / 'ci/docker-suite.modules'
        self.modules_file.write_text('\n'.join(MODULES) + '\n')
        for module in MODULES:
            path = self.root / 'vigilia/specifications' / module
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('dummy specification\n')
        self.results = self.root / 'results'
        self.env = os.environ.copy()
        self.env.update({
            'PATH': f'{self.root / "bin"}:{self.env["PATH"]}',
            'CI_RESULTS_DIR': str(self.results),
            'FAKE_TEST_LOG': str(self.root / 'test.log'),
            'FAKE_DOCKER_LOG': str(self.root / 'docker.log'),
            'VIGILIA_TEST_PROFILE': 'regression',  # ensure no inherited tags
        })
        for key in ('VIGILIA_DOCKER_MODULES_FILE', 'FAKE_FAIL_SELECTOR',
                    'FAKE_DOCKER_UNAVAILABLE'):
            self.env.pop(key, None)

    def suite_run(self):
        runs = list((self.results / 'docker-suite').glob('run.*'))
        self.assertEqual(len(runs), 1)
        return runs[0]

    def invoke(self, *args, **env_changes):
        return subprocess.run(['bash', 'ci/docker-suite.sh', *args],
                              cwd=self.root, env=dict(self.env, **env_changes),
                              capture_output=True, text=True, timeout=20)

    def test_two_modules_run_independently_and_build_once(self):
        proc = self.invoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = (self.root / 'test.log').read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('20_vigilia/30_docker[.]t$|<build>|', lines[0])
        self.assertIn('20_vigilia/12_error_checking/summary[.]yml$|--test-only|', lines[1])
        self.assertTrue(all(line.endswith('|<unset>') for line in lines))
        summary = (self.suite_run() / 'summary.tsv').read_text()
        self.assertEqual(summary.count('\tPASS\t0\t'), 2)
        subdirs = sorted(x for x in self.suite_run().iterdir()
                         if x.is_dir())
        self.assertEqual(len(subdirs), 2)
        for directory in subdirs:
            self.assertTrue((directory / 'console.log').exists())
            self.assertTrue((directory / 'docker-containers.log').exists())
            self.assertTrue((directory / 'run.fixture/report/report.yml').exists())

    def test_failure_does_not_skip_later_module(self):
        proc = self.invoke(FAKE_FAIL_SELECTOR='30_docker')
        self.assertEqual(proc.returncode, 1)
        lines = (self.root / 'test.log').read_text().splitlines()
        self.assertEqual(len(lines), 2)
        summary = (self.suite_run() / 'summary.tsv').read_text()
        self.assertIn('\tFAIL\t7\t', summary)
        self.assertIn('\tPASS\t0\t', summary)

    def test_test_only_option_disables_build_for_every_module(self):
        proc = self.invoke('--test-only')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(all('|--test-only|' in line for line in
                            (self.root / 'test.log').read_text().splitlines()))

    def test_empty_list_rejected_before_test_execution(self):
        self.modules_file.write_text('  # nothing\n\n')
        proc = self.invoke()
        self.assertEqual(proc.returncode, 2)
        self.assertIn('at least one module', proc.stderr)
        self.assertFalse((self.root / 'test.log').exists())

    def test_invalid_and_missing_modules_are_rejected_up_front(self):
        for invalid in ('../other.t', '20_vigilia/(foo).t',
                        '20_vigilia/nonexistent.t', MODULES[0] + ' ',
                        MODULES[0] + '\n' + MODULES[0]):
            with self.subTest(invalid=invalid):
                self.modules_file.write_text(invalid + '\n')
                proc = self.invoke()
                self.assertEqual(proc.returncode, 2)
                self.assertFalse((self.root / 'test.log').exists())

    def test_override_file_is_used(self):
        custom = self.root / 'extra-list'
        custom.write_text('# custom\n' + MODULES[1] + '\n')
        proc = self.invoke(VIGILIA_DOCKER_MODULES_FILE=str(custom))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len((self.root / 'test.log').read_text().splitlines()), 1)
        self.assertIn('12_error_checking', (self.root / 'test.log').read_text())

    def test_docker_unavailable_prevents_any_module_execution(self):
        proc = self.invoke(FAKE_DOCKER_UNAVAILABLE='1')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('Docker daemon is unavailable', proc.stderr)
        self.assertFalse((self.root / 'test.log').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
