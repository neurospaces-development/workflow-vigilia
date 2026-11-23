#!/usr/bin/env python3
"""Offline test of the configured workflow command adapter."""
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'configured-workflows/automation-commands-ci.py'


class WorkflowAdapterTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        namespace = {'execute_command_array': self.commands.append}
        exec(compile(SCRIPT.read_text(), str(SCRIPT), 'exec'), namespace)
        self.ns = namespace

    def test_schedules_without_invoking_api(self):
        self.ns['ci_artifacts_download'](['latest-successful', '--provider', 'github'])
        self.assertEqual(len(self.commands), 1)
        self.assertIn('download --mode latest-successful --provider github', self.commands[0][0])

    def test_revision_quoting(self):
        self.ns['ci_artifacts_download'](['a12a68e57552'])
        self.assertIn('--mode revision --revision a12a68e57552', self.commands[0][0])

    def test_no_shell_injection(self):
        self.ns['ci_artifacts_list'](['--branch', 'master; echo UNSAFE'])
        self.assertIn("'master; echo UNSAFE'", self.commands[0][0])

    def test_completion_uses_registered_operation_path(self):
        self.ns['_completor_generic_expander'] = lambda obj: obj
        actual = self.ns['ci_artifacts_download_completor']('ci artifacts_download', [], {})
        self.assertEqual(actual['operation_path'], ['ci', 'artifacts_download'])

    def test_unknown_selector_rejected(self):
        with self.assertRaises(ValueError):
            self.ns['ci_artifacts_download'](['random-selector'])

    def test_other_commands(self):
        for command in ['list', 'inventory', 'verify', 'report']:
            self.ns['ci_artifacts_' + command]([])
        self.assertEqual(len(self.commands), 4)

    def test_latest_wait_positional_selector(self):
        self.ns['ci_artifacts_download'](['latest-wait', '--profile', 'docker',
                                          '--wait-timeout', '900'])
        self.assertIn('download --mode latest-wait --profile docker --wait-timeout 900',
                      self.commands[0][0])

    def test_latest_wait_with_docker_positional_selector(self):
        self.ns['ci_artifacts_download'](['docker', '--mode', 'latest-wait',
                                          '--poll-interval', '5'])
        self.assertIn('download --profile docker --mode latest-wait --poll-interval 5',
                      self.commands[0][0])

    def test_download_full_profile(self):
        self.ns['ci_artifacts_download'](['full', '--mode', 'latest-wait',
                                          '--wait-timeout', '5400'])
        self.assertIn('download --profile full --mode latest-wait --wait-timeout 5400',
                      self.commands[0][0])

    def test_download_docker_pilot(self):
        self.ns['ci_artifacts_download'](['docker', '--provider', 'github',
                                          '--mode', 'latest'])
        self.assertIn('download --profile docker --provider github --mode latest',
                      self.commands[0][0])

    def test_download_explicit_job_id(self):
        self.ns['ci_artifacts_download'](['--provider', 'gitlab', '--run-id',
                                          '12345', '--id', '56789'])
        self.assertIn('download --provider gitlab --run-id 12345 --id 56789',
                      self.commands[0][0])

    def test_download_all(self):
        self.ns['ci_artifacts_download'](['all', '--provider', 'gitlab'])
        self.assertIn('download --all --provider gitlab', self.commands[0][0])

    def test_knowledge_base_direct_and_isolated_execution(self):
        self.ns['test_run'](['--module', '20_vigilia/30_docker.t',
                             '--module', '40_workflow-automator/27_schedule/summary.yml'])
        command = self.commands.pop()[0]
        self.assertIn('bin/vigilia --module 20_vigilia/30_docker.t --module', command)
        self.ns['test_run'](['--isolate-modules', '--module', '20_vigilia/30_docker.t'])
        self.assertIn('./ci/docker-suite.sh --module 20_vigilia/30_docker.t',
                      self.commands.pop()[0])

    def test_knowledge_base_prevents_accidental_full_execution(self):
        for operation in ('run', 'inspect'):
            with self.assertRaises(ValueError):
                self.ns['test_' + operation]([])
        with self.assertRaises(ValueError):
            self.ns['test_run'](['--isolate-modules', '--all'])
        with self.assertRaises(ValueError):
            self.ns['test_run'](['--module', 'a.t; touch /tmp/unsafe', '--other'])
        self.ns['test_run'](['--all'])
        self.assertIn('bin/vigilia', self.commands.pop()[0])

    def test_knowledge_base_inspection_and_completion(self):
        self.ns['test_modules']([])
        self.assertIn('--show-modules', self.commands.pop()[0])
        self.ns['test_inspect'](['--module', '20_vigilia/30_docker.t'])
        self.assertIn('--show-command-descriptions --module', self.commands.pop()[0])
        self.ns['_completor_generic_expander'] = lambda obj: obj
        comp = self.ns['test_run_completor']('test run', [], {})
        self.assertEqual(comp['operation_path'], ['test', 'run'])
        self.assertIn('--isolate-modules', comp['positional_arguments'][0]['completions'])
        self.assertIn('--module', self.ns['test_inspect_help']('test inspect', []))

    def test_ci_status_wait_runs_and_help(self):
        for name, operation in [('runs', 'list'), ('status', 'status'), ('wait', 'wait')]:
            self.ns['ci_' + name](['--revision', 'a' * 40])
            self.assertIn(' ' + operation + ' --revision', self.commands.pop()[0])
            self.ns['_completor_generic_expander'] = lambda obj: obj
            result = self.ns['ci_' + name + '_completor']('ci ' + name, [], {})
            self.assertEqual(result['operation_path'], ['ci', name])
            self.assertIn('ci ' + name, self.ns['ci_' + name + '_help']('ci ' + name, []))

    def test_native_report_operations_and_completion(self):
        for name in ('results', 'failures', 'compare', 'timings'):
            self.ns['ci_' + name](['--provider', 'github'])
            command = self.commands.pop()[0]
            self.assertIn('report-analysis.py', command)
            self.assertIn(' ' + name + ' --provider github', command)
            self.ns['_completor_generic_expander'] = lambda obj: obj
            result = self.ns['ci_' + name + '_completor']('ci ' + name, [], {})
            self.assertEqual(result['operation_path'], ['ci', name])
            self.assertIn('ci ' + name, self.ns['ci_' + name + '_help']('ci ' + name, []))

    def test_inventory_path_completion(self):
        self.ns['_completor_generic_expander'] = lambda obj: obj
        result = self.ns['ci_artifacts_inventory_completor']('ci artifacts_inventory', [], {})
        self.assertEqual(result['operation_path'], ['ci', 'artifacts_inventory'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
