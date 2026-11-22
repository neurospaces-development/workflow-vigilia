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
        for command in ['list', 'verify', 'report']:
            self.ns['ci_artifacts_' + command]([])
        self.assertEqual(len(self.commands), 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
