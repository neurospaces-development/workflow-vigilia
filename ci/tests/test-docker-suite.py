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

import yaml

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
        for key in ('VIGILIA_DOCKER_MODULES_FILE', 'VIGILIA_DOCKER_MODULES', 'FAKE_FAIL_SELECTOR',
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
        self.assertIn('at least one explicitly selected module', proc.stderr)
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

    def test_command_line_modules_and_environment_selection(self):
        proc = self.invoke('--module', MODULES[1], '--module', MODULES[0])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = (self.root / 'test.log').read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('12_error_checking', lines[0])
        self.assertIn('30_docker', lines[1])
        (self.root / 'test.log').unlink()
        proc = self.invoke(VIGILIA_DOCKER_MODULES=','.join(MODULES))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len((self.root / 'test.log').read_text().splitlines()), 2)

    def test_selection_source_conflicts_and_untrusted_input_rejected(self):
        bad = ('../other.t', '20_vigilia/(foo).t',
               '20_vigilia/a.t;touch /tmp/bad', '20_vigilia/not-found.t')
        for module in bad:
            with self.subTest(module=module):
                proc = self.invoke(VIGILIA_DOCKER_MODULES=module)
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertFalse((self.root / 'test.log').exists())
        proc = self.invoke('--module', MODULES[0],
                           VIGILIA_DOCKER_MODULES=MODULES[1])
        self.assertEqual(proc.returncode, 2)
        self.assertIn('only one', proc.stderr)
        self.assertFalse((self.root / 'test.log').exists())

    def test_committed_docker_list_is_empty_and_full_only_on_trusted_push(self):
        root = SOURCE.parents[1]
        module_list = (root / 'ci/docker-suite.modules').read_text().splitlines()
        self.assertTrue(all(not x.strip() or x.lstrip().startswith('#')
                            for x in module_list))
        github = yaml.safe_load((root / '.github/workflows/regression-tests.yml').read_text())
        jobs = github['jobs']
        self.assertIn("github.event_name == 'pull_request'", jobs['regression-tests']['if'])
        self.assertEqual(jobs['regression-tests']['strategy']['matrix']['profile'], ['regression'])
        self.assertIn("github.event_name == 'workflow_dispatch'", jobs['docker-pilot']['if'])
        self.assertIn("inputs.docker_modules != ''", jobs['docker-pilot']['if'])
        self.assertIn("github.event_name == 'push'", jobs['full-tests']['if'])
        self.assertEqual(jobs['docker-pilot']['env']['VIGILIA_DOCKER_MODULES'],
                         '${{ inputs.docker_modules }}')
        gitlab = yaml.safe_load((root / '.gitlab-ci.yml').read_text())
        self.assertEqual(gitlab['vigilia-full']['extends'], 'vigilia-docker-pilot')
        self.assertIn('CI_PIPELINE_SOURCE == "push"',
                      gitlab['vigilia-full']['rules'][0]['if'])
        self.assertEqual(gitlab['vigilia-docker-pilot']['rules'][0]['when'], 'manual')
        self.assertEqual(gitlab['vigilia-regression']['rules'][0]['when'], 'manual')
        cfg = yaml.safe_load((root / 'configured-workflows/automation-configuration-data/ci_artifacts.yml').read_text())
        self.assertEqual(cfg['ci_artifacts']['profiles'], ['full'])

    def test_override_file_is_used(self):
        custom = self.root / 'extra-list'
        custom.write_text('# custom\n' + MODULES[1] + '\n')
        proc = self.invoke(VIGILIA_DOCKER_MODULES_FILE=str(custom))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len((self.root / 'test.log').read_text().splitlines()), 1)
        self.assertIn('12_error_checking', (self.root / 'test.log').read_text())

    def test_full_jobs_use_unfiltered_vigilia_profile(self):
        """Full CI must not become a second curated list of specifications."""
        root = SOURCE.parents[1]
        github = yaml.safe_load((root / '.github/workflows/regression-tests.yml').read_text())
        full = github['jobs']['full-tests']
        self.assertEqual(full['env']['VIGILIA_TEST_PROFILE'], 'full')
        self.assertEqual(full['env']['VIGILIA_ALLOW_FULL'], '1')
        self.assertNotIn('VIGILIA_REGEX_SELECTOR', full['env'])
        self.assertTrue(any(step.get('run') == './ci/test.sh' for step in full['steps']))

        gitlab = yaml.safe_load((root / '.gitlab-ci.yml').read_text())
        self.assertEqual(gitlab['vigilia-full']['extends'], 'vigilia-docker-pilot')
        self.assertEqual(gitlab['vigilia-full']['variables']['VIGILIA_DOCKER_EXECUTION'], 'full')
        self.assertIn('VIGILIA_TEST_PROFILE=full VIGILIA_ALLOW_FULL=1',
                      gitlab['vigilia-docker-pilot']['script'][0])
        self.assertNotIn('VIGILIA_REGEX_SELECTOR', gitlab['vigilia-full']['variables'])

    def test_docker_unavailable_prevents_any_module_execution(self):
        proc = self.invoke(FAKE_DOCKER_UNAVAILABLE='1')
        self.assertEqual(proc.returncode, 2)
        self.assertIn('Docker daemon is unavailable', proc.stderr)
        self.assertFalse((self.root / 'test.log').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
