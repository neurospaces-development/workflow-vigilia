#!/usr/bin/python3
"""Thin workflow adapter; all API logic lives in ci/download-artifacts.py.

No API call occurs while parsing workflow configuration or while composing
commands for --dry-run. The engine executes the scheduled command later.
"""
import shlex


def _ci_artifacts_schedule(subcommand, argv):
    arguments = list(argv or [])
    if subcommand == 'download' and arguments and not arguments[0].startswith('--'):
        selection = arguments.pop(0)
        if selection in ('latest', 'latest-successful'):
            arguments = ['--mode', selection] + arguments
        elif len(selection) >= 7 and len(selection) <= 40 and all(c in '0123456789abcdef' for c in selection):
            arguments = ['--mode', 'revision', '--revision', selection] + arguments
        else:
            raise ValueError('First argument must be latest, latest-successful, or a Git revision')

    # Determine the source root when the command is executed, not while the
    # workflow configuration is loaded. This works from any subdirectory of
    # the source checkout and preserves --dry-run behaviour.
    program = '"$(git rev-parse --show-toplevel)/ci/download-artifacts.py"'
    command = 'python3 ' + program + ' ' + shlex.quote(subcommand)
    if arguments:
        command += ' ' + ' '.join(shlex.quote(str(a)) for a in arguments)
    execute_command_array([command])


def ci_artifacts_list(argv):
    _ci_artifacts_schedule('list', argv)


def ci_artifacts_download(argv):
    _ci_artifacts_schedule('download', argv)


def ci_artifacts_verify(argv):
    _ci_artifacts_schedule('verify', argv)


def ci_artifacts_report(argv):
    _ci_artifacts_schedule('report', argv)


def _ci_artifacts_completor(operation, argv, analysis):
    return _completor_generic_expander({
        'analysis': analysis,
        'complete_arguments_array': argv,
        'operation_path': ['ci', 'artifacts_' + operation],
        'positional_arguments': [
            {'completions': {
                'latest': 'Most recent completed run (including failures)',
                'latest-successful': 'Most recent common successful revision',
                '--mode': 'Select the run mode',
                '--revision': 'Select a specific Git revision',
                '--provider': 'Select one or more providers',
                '--profile': 'Select one or more test profiles',
            }},
        ],
    })


def ci_artifacts_list_completor(command, argv, analysis):
    return _ci_artifacts_completor('list', argv, analysis)


def ci_artifacts_download_completor(command, argv, analysis):
    return _ci_artifacts_completor('download', argv, analysis)


def ci_artifacts_verify_completor(command, argv, analysis):
    return _ci_artifacts_completor('verify', argv, analysis)


def ci_artifacts_report_completor(command, argv, analysis):
    return _ci_artifacts_completor('report', argv, analysis)


def ci_artifacts_list_help(command, argv):
    return f'{command}: List recent completed GitHub/GitLab pipeline runs from REST APIs.\n'


def ci_artifacts_download_help(command, argv):
    return (f'{command}: Download both providers and profiles at a common Git revision.\n'
            '  First argument: latest (including failures), latest-successful, or SHA.\n'
            '  Additional options: --provider github|gitlab, --profile smoke|regression,\n'
            '  --revision SHA, --mode latest|latest-successful|revision, --output DIR.\n'
            '  Credentials: GITHUB_TOKEN/GH_TOKEN and GITLAB_TOKEN environment variables.\n')


def ci_artifacts_verify_help(command, argv):
    return f'{command}: Verify ZIP integrity, embedded revisions, and checksums of latest downloads.\n'


def ci_artifacts_report_help(command, argv):
    return f'{command}: Summarize the latest downloaded verification manifest.\n'
