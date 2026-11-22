#!/usr/bin/env bash
# Exercise the real vigilia CLI using an isolated, deliberately mixed suite.
set -euo pipefail

vigilia=$(realpath "${1:-bin/vigilia}")
work=$(mktemp -d "${TMPDIR:-/tmp}/vigilia-inspection.XXXXXX")
trap 'rc=$?; if (( rc == 0 )); then rm -rf -- "$work"; else printf "Inspection regression evidence: %s\n" "$work" >&2; fi' EXIT

export VIGILIA_INSPECTION_TEST_WORK="$work"
export VIGILIA_INSPECTION_TEST_MARKER="$work/executed"
export NEUROSPACES_HARNESS_OPTION_EMAIL=0
mkdir "$work/specifications"

cat > "$work/vigilia.config" <<'CONFIG'
return {
    core_directory => './',
    description => 'Isolated exit code inspection regression fixture',
    tests_directory => "$ENV{VIGILIA_INSPECTION_TEST_WORK}/specifications",
    html_output_directory => "$ENV{VIGILIA_INSPECTION_TEST_WORK}/html",
    package => { name => 'inspection-exit-code-fixture', version => 'test' },
};
CONFIG

# A .module.yml file beginning with --- is a YAML module in vigilia.
# Each fixture is separate so runtime results can be checked independently.
cat > "$work/specifications/pass-zero.module.yml" <<'YAML'
---
name: pass-zero.module.yml
description: Matching zero exit code
command_definitions:
  - description: Run a successful command
    command: /bin/sh
    arguments:
      - -c
      - 'touch "$VIGILIA_INSPECTION_TEST_MARKER" && exit 0'
    command_tests:
      - description: Expect exit code zero
        exit_code: 0
        timeout: 5
YAML

cat > "$work/specifications/pass-nonzero.module.yml" <<'YAML'
---
name: pass-nonzero.module.yml
description: Matching nonzero exit code with exact output
command_definitions:
  - description: Run a command that returns seven
    command: /bin/sh
    arguments:
      - -c
      - 'touch "$VIGILIA_INSPECTION_TEST_MARKER" && printf probe && exit 7'
    command_tests:
      - description: Expect exact output and exit code seven
        read:
          exact: probe
        exit_code: 7
        timeout: 5
YAML

cat > "$work/specifications/fail-mismatch.module.yml" <<'YAML'
---
name: fail-mismatch.module.yml
description: Deliberate exit code mismatch
command_definitions:
  - description: Run a command that returns seven instead of zero
    command: /bin/sh
    arguments:
      - -c
      - 'touch "$VIGILIA_INSPECTION_TEST_MARKER" && exit 7'
    command_tests:
      - description: Deliberately expect the wrong exit code
        exit_code: 0
        timeout: 5
YAML

cat > "$work/specifications/fail-unavailable.module.yml" <<'YAML'
---
name: fail-unavailable.module.yml
description: Deliberate assertion after the command has been reaped
command_definitions:
  - description: Run a command and consume its exit status
    command: /bin/sh
    arguments:
      - -c
      - 'touch "$VIGILIA_INSPECTION_TEST_MARKER" && exit 0'
    command_tests:
      - description: First assertion waits for termination
        exit_code: 0
        timeout: 5
      - description: A second assertion has no running command
        exit_code: 0
        timeout: 5
YAML

fail()
{
    printf '%s\n' "$*" >&2
    exit 1
}

run_case()
{
    local name=$1 expected_rc=$2 expected_tests=$3 expected_errors=$4 diagnostic=$5
    shift 5
    local rc=0

    rm -f -- "$VIGILIA_INSPECTION_TEST_MARKER"

    "$vigilia" --config-filename "$work/vigilia.config" \
        --console-type linear --reporting-directory "$work/report-$name" \
        "$@" > "$work/$name.log" 2>&1 || rc=$?

    if (( rc != expected_rc )); then
        tail -n 35 "$work/$name.log" >&2
        fail "$name: expected vigilia status $expected_rc, got $rc"
    fi

    # Do not accept a zero exit from an empty selection, a missing report,
    # or an unrelated failure in one of the two deliberately failing cases.
    perl -MYAML::PP -e '
        my ($file, $tests, $errors, $diagnostic) = @ARGV;
        my $report = YAML::PP::LoadFile($file);
        my $global = $report->{global};
        die "Unexpected report status\n" unless $global->{status} eq "Finished";
        die "Unexpected test count\n"
            unless $global->{test_counters}->{current}->{command_test} == $tests;
        die "Unexpected error count\n" unless $global->{error_count} == $errors;
        if (length $diagnostic) {
            my @reports = values %{ $report->{errors}->{error_reports} || {} };
            die "Expected diagnostic not present\n"
                unless grep { index($_->{error} // "", $diagnostic) >= 0 } @reports;
        }
    ' "$work/report-$name/report.yml" "$expected_tests" "$expected_errors" "$diagnostic"
}

# All five assertions are processed, including the intentionally invalid
# runtime cases, but no tested command may execute in inspection mode.
for mode in show-modules show-command-tests show-command-descriptions show-images; do
    run_case "$mode" 0 5 0 '' "--$mode"
    [[ ! -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail "$mode executed a tested command"
done

run_case output-html 0 5 0 '' --output-html
[[ ! -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail 'HTML generation executed a tested command'
[[ -s "$work/html/index.html" ]] || fail 'HTML index missing'

# LaTeX generation requires the project logo.  This test runs from source.
# Use the source logo rather than depend on a system-wide installation.
logo=images/ns-main-logo-dark2.jpg
if [[ -r "$logo" ]]; then
    run_case output-latex 0 5 0 '' --output-latex --output-logo "$(realpath "$logo")"
    [[ ! -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail 'LaTeX generation executed a tested command'
    find "$work/report-output-latex" -name '*.tex' -size +0c -print -quit | grep -q . || fail 'LaTeX output missing'
else
    printf 'Skipping LaTeX generation: source logo not available\n'
fi

run_case pass-zero 0 1 0 '' --regex-selector '/pass-zero\.module\.yml$'
[[ -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail 'pass-zero did not execute'
run_case pass-nonzero 0 1 0 '' --regex-selector '/pass-nonzero\.module\.yml$'
[[ -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail 'pass-nonzero did not execute'
run_case fail-mismatch 1 1 1 'tested command exited with code 7; expected exit code 0' \
    --regex-selector '/fail-mismatch\.module\.yml$'
[[ -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail 'fail-mismatch did not execute'
run_case fail-unavailable 1 2 1 'no tested command is currently running' \
    --regex-selector '/fail-unavailable\.module\.yml$'
[[ -e "$VIGILIA_INSPECTION_TEST_MARKER" ]] || fail 'fail-unavailable did not execute'

# A misnamed YAML module is a specification error, even when the selected
# profile excludes it. Its discovery must increase the native error count.
cat > "$work/specifications/wrong-format.t" <<'YAML'
---
name: wrong-format.t
description: Deliberately misnamed YAML module
command_definitions:
  - command: /bin/true
    command_tests:
      - description: This command must never run
        exit_code: 0
YAML

rc=0
"$vigilia" --config-filename "$work/vigilia.config" \
    --console-type linear --reporting-directory "$work/report-wrong-format" \
    --regex-selector '/pass-zero\.module\.yml$' \
    > "$work/wrong-format.log" 2>&1 || rc=$?
(( rc != 0 )) || fail 'Misnamed YAML module did not fail the vigilia run'
grep -Fq 'YAML module has a .t filename' "$work/wrong-format.log" ||
    fail 'Misnamed YAML module was not reported'

# The optional YAML document marker is not required for the format check.
cat > "$work/specifications/wrong-format-no-marker.t" <<'YAML'
name: wrong-format-no-marker.t
description: YAML mapping without an explicit document marker
command_definitions: []
YAML
rc=0
"$vigilia" --config-filename "$work/vigilia.config" \
    --console-type linear --reporting-directory "$work/report-wrong-format-no-marker" \
    --regex-selector '/pass-zero\.module\.yml$' \
    > "$work/wrong-format-no-marker.log" 2>&1 || rc=$?
(( rc != 0 )) || fail 'Misnamed YAML module without document marker passed'
grep -Fq 'YAML module has a .t filename' "$work/wrong-format-no-marker.log" ||
    fail 'Misnamed YAML without document marker was not reported'

printf 'Inspection exit code regression tests passed.\n'
