#!/usr/bin/env python3
"""Exercise Vigilia's actual Docker preparer with a fake Docker executable.

No Docker daemon or Perl dependencies beyond the standard interpreter are
required. This catches network-pool conflicts and preparer error propagation.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'bin/vigilia'
source = SOURCE.read_text()
package_start = source.index('\npackage Heterarch::Test::ExecutionContext::Harness::Docker;')
start = source.index('\nsub _docker_preparer\n', package_start)
end = source.index('\nsub _docker_reparer\n', start)
SOCKET_HELPER_START = source.index('\nsub _docker_shared_socket_options\n', package_start)
SOCKET_HELPER = source[SOCKET_HELPER_START:start]
PREPARER = source[start:end]

PERL_DRIVER = r'''
use strict;
use warnings;
package Heterarch::Test::ExecutionContext::Harness::Docker;
our $docker_command_no_redirect = 'docker';
our $docker_command_selected = 'docker';
''' + SOCKET_HELPER + PREPARER + r'''
my $harness = bless {
    class => { docker => {
        dockerfile => 'Dockerfile.mock',
        name_image => 'vigilia_mock_image',
        name_container => 'vigilia_mock_container',
        shared_volumes => [],
        docker_in_docker => {shared => ($ENV{FAKE_SHARED_DOCKER_SOCKET} // 0)},
    } },
}, __PACKAGE__;
my $result = $harness->_docker_preparer(undef);
if (ref($result) eq 'SCALAR') {
    print STDERR "PREPARATION_ERROR: $$result\n";
    exit 3;
}
print "PREPARATION_OK: $result->{variable_actions}->{__DOCKER_HOST_IP_ADDRESS__}\n";
'''

FAKE_DOCKER = r'''#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1 $2" in
    'network inspect')
        if [ -z "${FAKE_EXISTING_SUBNET:-}" ]; then exit 1; fi
        printf '%s\n' "$FAKE_EXISTING_SUBNET"
        ;;
    'network create')
        if [ -n "${FAKE_CREATE_FAIL:-}" ]; then
            echo 'invalid pool request: Pool overlaps' >&2
            exit 9
        fi
        echo mock-network-id
        ;;
    'run --rm')
        if [ -n "${FAKE_SOCKET_FAIL:-}" ]; then
            echo 'invalid mount config: bind source path does not exist: /var/run/docker.sock' >&2
            exit 7
        fi
        printf '%s\n' "${FAKE_SOCKET_GID:-105}"
        ;;
    'run '*|'run ')
        if [ -n "${FAKE_RUN_FAIL:-}" ]; then
            echo 'network harness_network not found' >&2
            exit 5
        fi
        echo mock-container-id
        ;;
    'inspect '*|'inspect ')
        echo '[{"NetworkSettings":{"Networks":{"harness_network":{"IPAddress":"172.19.0.12"}}}}]'
        ;;
esac
'''


class DockerNetworkPreparerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vigilia-network-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        docker = self.root / 'docker'
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
        self.log = self.root / 'docker.log'
        self.env = os.environ.copy()
        self.env['FAKE_DOCKER_LOG'] = str(self.log)
        self.env['PATH'] = f'{self.root}:{self.env["PATH"]}'
        for name in ('VIGILIA_DOCKER_NETWORK_SUBNET', 'FAKE_EXISTING_SUBNET',
                     'FAKE_CREATE_FAIL', 'FAKE_RUN_FAIL',
                     'FAKE_SHARED_DOCKER_SOCKET', 'FAKE_SOCKET_FAIL', 'FAKE_SOCKET_GID'):
            self.env.pop(name, None)

    def execute(self, **overrides):
        env = dict(self.env, **overrides)
        run = subprocess.run(['perl', '-e', PERL_DRIVER], env=env,
                             capture_output=True, text=True, timeout=15)
        calls = [line.split() for line in self.log.read_text().splitlines()]
        return run, calls

    def test_existing_default_subnet_is_preserved(self):
        run, calls = self.execute()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(['network', 'create', '--subnet=172.18.0.0/16', 'harness_network'], calls)
        self.assertIn('PREPARATION_OK: 172.19.0.12', run.stdout)

    def test_auto_allocation_omits_subnet(self):
        run, calls = self.execute(VIGILIA_DOCKER_NETWORK_SUBNET='auto')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(['network', 'create', 'harness_network'], calls)
        self.assertFalse(any('--subnet=' in a for cmd in calls for a in cmd))

    def test_auto_allocation_can_reuse_existing_network(self):
        run, calls = self.execute(VIGILIA_DOCKER_NETWORK_SUBNET='auto',
                                  FAKE_EXISTING_SUBNET='172.19.0.0/16')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(any(cmd[:2] == ['network', 'create'] for cmd in calls))
        self.assertTrue(any(cmd[0] == 'run' for cmd in calls))

    def test_existing_incompatible_network_is_rejected(self):
        run, calls = self.execute(FAKE_EXISTING_SUBNET='172.19.0.0/16')
        self.assertEqual(run.returncode, 3)
        self.assertIn("existing Docker network", run.stderr)
        self.assertFalse(any(cmd[0] == 'run' for cmd in calls))

    def test_create_failure_is_reported_without_running_container(self):
        run, calls = self.execute(FAKE_CREATE_FAIL='1')
        self.assertEqual(run.returncode, 3)
        self.assertIn('Docker network creation failed', run.stderr)
        self.assertIn('Pool overlaps', run.stderr)
        self.assertFalse(any(cmd[0] == 'run' for cmd in calls))

    def test_run_failure_is_reported(self):
        run, _ = self.execute(FAKE_RUN_FAIL='1')
        self.assertEqual(run.returncode, 3)
        self.assertIn('Docker container start failed', run.stderr)
        self.assertIn('network harness_network not found', run.stderr)

    def test_invalid_env_value_is_rejected_before_network_operations(self):
        run, calls = self.execute(VIGILIA_DOCKER_NETWORK_SUBNET='auto; echo unsafe')
        self.assertEqual(run.returncode, 3)
        self.assertIn('invalid VIGILIA_DOCKER_NETWORK_SUBNET', run.stderr)
        self.assertFalse(any(cmd[:1] == ['network'] for cmd in calls))

    def test_shared_socket_group_is_inspected_in_daemon_not_job(self):
        run, calls = self.execute(FAKE_SHARED_DOCKER_SOCKET='1',
                                  FAKE_SOCKET_GID='2375')
        self.assertEqual(run.returncode, 0, run.stderr)
        probe = [cmd for cmd in calls if cmd[:2] == ['run', '--rm']]
        self.assertEqual(len(probe), 1)
        self.assertIn('type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock,readonly',
                      probe[0])
        self.assertEqual(probe[0][-3:], ['-c', '%g', '/var/run/docker.sock'])
        run_command = next(cmd for cmd in calls if cmd[:2] == ['run', '--net'])
        self.assertIn('--group-add', run_command)
        self.assertEqual(run_command[run_command.index('--group-add') + 1], '2375')
        self.assertIn('/var/run/docker.sock:/var/run/docker.sock', run_command)

    def test_missing_daemon_socket_fails_before_container_start(self):
        run, calls = self.execute(FAKE_SHARED_DOCKER_SOCKET='1',
                                  FAKE_SOCKET_FAIL='1')
        self.assertEqual(run.returncode, 3)
        self.assertIn('cannot inspect the daemon-side Docker socket', run.stderr)
        self.assertIn('bind source path does not exist', run.stderr)
        self.assertFalse(any(cmd[:2] == ['run', '--net'] for cmd in calls))

    def test_non_numeric_socket_group_is_rejected(self):
        run, calls = self.execute(FAKE_SHARED_DOCKER_SOCKET='1',
                                  FAKE_SOCKET_GID='not-a-group-id')
        self.assertEqual(run.returncode, 3)
        self.assertIn('cannot inspect the daemon-side Docker socket', run.stderr)
        self.assertFalse(any(cmd[:2] == ['run', '--net'] for cmd in calls))


if __name__ == '__main__':
    unittest.main(verbosity=2)
