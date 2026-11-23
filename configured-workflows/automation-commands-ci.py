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
        if selection in ('latest', 'latest-successful', 'latest-wait'):
            arguments = ['--mode', selection] + arguments
        elif selection in ('smoke', 'regression', 'docker', 'full'):
            arguments = ['--profile', selection] + arguments
        elif selection == 'all':
            arguments = ['--all'] + arguments
        elif len(selection) >= 7 and len(selection) <= 40 and all(c in '0123456789abcdef' for c in selection):
            arguments = ['--mode', 'revision', '--revision', selection] + arguments
        else:
            raise ValueError('First argument must be latest, latest-successful, latest-wait, a profile, all, or a Git revision')

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


def ci_artifacts_inventory(argv):
    _ci_artifacts_schedule('inventory', argv)


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
                'latest-wait': 'Wait for current HEAD to finish on all selected providers',
                '--mode': 'Select the run mode (including latest-wait)',
                '--wait-timeout': 'Maximum CI wait time in seconds',
                '--poll-interval': 'Polling interval in seconds',
                '--revision': 'Select a specific Git revision',
                '--provider': 'Select one or more providers',
                '--profile': 'Select smoke, regression, Docker or full-suite archives',
                'docker': 'Docker pilot artifact archive',
                'all': 'All available job artifact archives',
                '--run-id': 'GitHub run / GitLab pipeline ID',
                '--id': 'Exact GitHub artifact / GitLab job ID',
                '--name': 'Glob matching GitHub artifact / GitLab job name',
                '--all': 'Download every available artifact archive',
            }},
        ],
    })


def ci_artifacts_list_completor(command, argv, analysis):
    return _ci_artifacts_completor('list', argv, analysis)


def ci_artifacts_download_completor(command, argv, analysis):
    return _ci_artifacts_completor('download', argv, analysis)


def ci_artifacts_inventory_completor(command, argv, analysis):
    return _ci_artifacts_completor('inventory', argv, analysis)


def ci_artifacts_verify_completor(command, argv, analysis):
    return _ci_artifacts_completor('verify', argv, analysis)


def ci_artifacts_report_completor(command, argv, analysis):
    return _ci_artifacts_completor('report', argv, analysis)


def ci_artifacts_list_help(command, argv):
    return f'{command}: List recent completed GitHub/GitLab pipeline runs from REST APIs.\n'


def ci_artifacts_inventory_help(command, argv):
    return (f'{command}: Discover available artifact IDs and GitLab job IDs.\n'
            '  Options: --provider github|gitlab, --mode latest|latest-successful|latest-wait,\n'
            '  --run-id ID (one provider), --revision SHA. Does not download archives.\n')


def ci_artifacts_download_help(command, argv):
    return (f'{command}: Download selected GitHub and GitLab job artifacts.\n'
            '  First argument: latest, latest-successful, latest-wait, Git SHA, smoke, regression, docker, full, or all.\n'
            '  Selection: --profile smoke|regression|docker|full, --name GLOB, --all, or --id ID.\n'
            '  Targeting: --provider github|gitlab, --run-id ID, --revision SHA,\n'
            '  --mode latest|latest-successful|latest-wait|revision, --output DIR.\n'
            '  latest-wait targets the local HEAD (or --revision FULL_SHA); waits for all providers.\n'
            '  --wait-timeout SECONDS (default 1800), --poll-interval SECONDS (default 15).\n'
            '  --id requires exactly one provider and an explicit --run-id.\n'
            '  Failed Docker pilots: use --mode latest or --run-id; default selects successful runs.\n'
            '  Credentials: GITHUB_TOKEN/GH_TOKEN and GITLAB_TOKEN environment variables.\n')


def ci_artifacts_verify_help(command, argv):
    return f'{command}: Verify ZIP integrity, embedded revisions, and checksums of latest downloads.\n'


def ci_artifacts_report_help(command, argv):
    return f'{command}: Summarize the latest downloaded verification manifest.\n'


# Test knowledge-base operations. Vigilia alone owns the selection rules;
# these thin adapters perform no regex matching and execute no test at load
# time. The standalone focused suite is reserved for explicit isolation.
def _test_options(argv, inspect=False):
    arguments = list(argv or [])
    isolated = False
    all_modules = False
    selected = []
    result = []
    i = 0
    while i < len(arguments):
        token = arguments[i]
        if token in ('--module', '--tag-query', '--tags'):
            if i + 1 >= len(arguments) or not arguments[i + 1]:
                raise ValueError(token + ' requires an argument')
            value = arguments[i + 1]
            result.extend((token, value))
            if token == '--module':
                selected.append(value)
            i += 2
        elif token == '--isolate-modules' and not inspect:
            isolated = True
            i += 1
        elif token == '--all':
            all_modules = True
            i += 1
        else:
            raise ValueError('Unexpected test option: ' + token)
    if isolated and (not selected or len(result) != 2 * len(selected)):
        raise ValueError('--isolate-modules requires only one or more --module PATH selections')
    if all_modules and result:
        raise ValueError('--all cannot be combined with selection options')
    if not (selected or result or all_modules):
        raise ValueError('Select --module, --tags, --tag-query, or explicitly --all')
    return isolated, selected, result


def _test_schedule(program, arguments):
    # Commands are composed for workflow's scheduled execution. Source root
    # discovery happens at execution, not when loading the configuration.
    command = 'cd "$(git rev-parse --show-toplevel)" && ' + program
    if arguments:
        command += ' ' + ' '.join(shlex.quote(str(arg)) for arg in arguments)
    execute_command_array([command])


def test_modules(argv):
    if argv:
        raise ValueError('test modules takes no arguments')
    _test_schedule('bin/vigilia', ['--show-modules'])


def test_inspect(argv):
    _, _, args = _test_options(argv, inspect=True)
    _test_schedule('bin/vigilia', ['--show-command-descriptions'] + args)


def test_run(argv):
    isolated, modules, args = _test_options(argv)
    if isolated:
        options = [v for m in modules for v in ('--module', m)]
        _test_schedule('./ci/docker-suite.sh', options)
    else:
        _test_schedule('bin/vigilia', args)


def _test_module_candidates():
    # Best-effort local completions; they are not another selection engine.
    # Vigilia validates each requested path at execution time.
    from pathlib import Path
    import subprocess
    try:
        root = Path(subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                                   check=True, capture_output=True, text=True).stdout.strip())
        base = root / 'vigilia/specifications'
        paths = (p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file())
        return {p: 'Vigilia module' for p in paths
                if p.endswith(('.t', '.module.yml')) or p.endswith('/summary.yml')}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _test_completor(operation, argv, analysis):
    return _completor_generic_expander({
        'analysis': analysis,
        'complete_arguments_array': argv,
        'operation_path': ['test', operation],
        'positional_arguments': [
            {'completions': {
                '--module': 'Exact specification path; may be repeated',
                '--tags': 'Select by tag (OR)',
                '--tag-query': 'Select by Boolean tag expression',
                '--all': 'Explicitly select the entire knowledge base',
                **({'--isolate-modules': 'Separate reports per selected module'} if operation == 'run' else {}),
                **_test_module_candidates(),
            }},
        ],
    })


def test_modules_completor(command, argv, analysis):
    return _completor_generic_expander({
        'analysis': analysis, 'complete_arguments_array': argv,
        'operation_path': ['test', 'modules'], 'positional_arguments': [],
    })


def test_inspect_completor(command, argv, analysis):
    return _test_completor('inspect', argv, analysis)


def test_run_completor(command, argv, analysis):
    return _test_completor('run', argv, analysis)


def test_modules_help(command, argv):
    return (f'{command}: List discovered Vigilia test modules and descriptions.\n'
            '  No command tests are executed.\n')


def test_inspect_help(command, argv):
    return (f'{command}: Inspect selected Vigilia specifications without executing commands.\n'
            '  --module PATH (repeatable), --tags TAG, --tag-query EXPR, or --all.\n'
            '  Module paths are relative to vigilia/specifications/.\n')


def test_run_help(command, argv):
    return (f'{command}: Execute selected Vigilia specifications locally.\n'
            '  --module PATH (repeatable), --tags TAG, --tag-query EXPR, or --all.\n'
            '  --isolate-modules: one report per module through ci/docker-suite.sh;\n'
            '  requires explicit --module paths, Docker and installed dependencies.\n'
            '  By default one Vigilia process executes all selected modules together.\n'
            '  Use the -- separator before these options in workflow commands.\n')


# Read-only CI run monitoring. Run status does not retrieve artifacts and
# waiting does not change the remote pipeline state.
def ci_runs(argv):
    _ci_artifacts_schedule('list', argv)


def ci_status(argv):
    _ci_artifacts_schedule('status', argv)


def ci_wait(argv):
    _ci_artifacts_schedule('wait', argv)


def _ci_run_completor(operation, argv, analysis):
    return _completor_generic_expander({
        'analysis': analysis, 'complete_arguments_array': argv,
        'operation_path': ['ci', operation],
        'positional_arguments': [{'completions': {
            '--revision': 'Full Git SHA (defaults to checked-out HEAD)',
            '--provider': 'github or gitlab (repeatable)',
            '--branch': 'CI branch (defaults to configured branch)',
            '--run-id': 'Specific provider run ID',
            **({'--wait-timeout': 'Maximum seconds to wait',
                '--poll-interval': 'Seconds between API polls'} if operation == 'wait' else {}),
        }}],
    })


def ci_runs_completor(command, argv, analysis):
    return _ci_run_completor('runs', argv, analysis)


def ci_status_completor(command, argv, analysis):
    return _ci_run_completor('status', argv, analysis)


def ci_wait_completor(command, argv, analysis):
    return _ci_run_completor('wait', argv, analysis)


def ci_runs_help(command, argv):
    return f'{command}: List recent provider runs; see ci artifacts_list for options.\n'


def ci_status_help(command, argv):
    return (f'{command}: Query both providers for checked-out HEAD (or --revision SHA).\n'
            '  --provider github|gitlab, --branch NAME, --run-id ID.\n'
            '  Exit code 0 only when all selected runs succeeded; does not download artifacts.\n')


def ci_wait_help(command, argv):
    return (f'{command}: Wait for CI runs matching HEAD (or --revision SHA).\n'
            '  --provider github|gitlab, --branch NAME, --run-id ID,\n'
            '  --wait-timeout SECONDS, --poll-interval SECONDS.\n'
            '  Exit nonzero for failed runs and timeouts; no artifacts downloaded.\n')
