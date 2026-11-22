#!/usr/bin/env bash
# Exercise hierarchical tags through vigilia's public CLI, using only /bin/sh.
set -euo pipefail

vigilia=$(realpath "${1:-bin/vigilia}")
work=$(mktemp -d "${TMPDIR:-/tmp}/vigilia-tags.XXXXXX")
trap 'rc=$?; if (( rc == 0 )); then rm -rf -- "$work"; else printf "Tag regression evidence: %s\n" "$work" >&2; fi' EXIT

export VIGILIA_TAG_TEST_ROOT="$work"
export VIGILIA_TAG_TEST_MARKER="$work/executed"
export NEUROSPACES_HARNESS_OPTION_EMAIL=0
mkdir "$work/specifications"

cat > "$work/vigilia.config" <<'CONFIG'
return {
    core_directory => './',
    description => 'Isolated hierarchical tag regression fixture',
    tests_directory => "$ENV{VIGILIA_TAG_TEST_ROOT}/specifications",
    html_output_directory => "$ENV{VIGILIA_TAG_TEST_ROOT}/html",
    package => { name => 'tags-fixture', version => 'test' },
};
CONFIG

cat > "$work/specifications/primary.t" <<'YAML'
---
name: primary.t
description: Hierarchically tagged execution and documentation
tags:
  - ci:smoke
  - ci:regression
  - manual
  - tutorial
command_definitions:
  - description: Inherited default assertion
    command: /bin/sh
    arguments: [-c, 'printf "base\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Untagged assertion inherits its module
        exit_code: 0
        timeout: 10
  - description: Explicit regression command
    tags: [ci:regression]
    command: /bin/sh
    arguments: [-c, 'printf "regression-command\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Untagged assertion inherits command selection
        exit_code: 0
        timeout: 10
  - description: Explicit regression assertion
    command: /bin/sh
    arguments: [-c, 'printf "regression-assertion\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Assertion narrows selection to regression
        tags: [ci:regression]
        exit_code: 0
        timeout: 10
  - description: Manual-only command
    tags: [manual]
    command: /bin/sh
    arguments: [-c, 'printf "manual\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Canonical tags array on a command
        exit_code: 0
        timeout: 10
  - description: Tutorial-only assertion
    command: /bin/sh
    arguments: [-c, 'printf "tutorial\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Tutorial assertion
        tags: [tutorial]
        exit_code: 0
        timeout: 10
YAML

cat > "$work/specifications/regression.t" <<'YAML'
---
name: regression.t
description: Regression-only module
tags: [ci:regression]
command_definitions:
  - description: Separate regression command
    command: /bin/sh
    arguments: [-c, 'printf "regression-module\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Regression-only module assertion
        exit_code: 0
        timeout: 10
YAML

cat > "$work/specifications/untagged.t" <<'YAML'
---
name: untagged.t
description: Module without explicit tags
command_definitions:
  - description: Must not run with a tag filter
    command: /bin/sh
    arguments: [-c, 'printf "untagged-module\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Untagged module assertion
        exit_code: 0
        timeout: 10
YAML

cat > "$work/specifications/secondary.t" <<'YAML'
---
name: secondary.t
description: Canonical tutorial tags on a second module
tags: [tutorial]
command_definitions:
  - description: Inherited tutorial command
    command: /bin/sh
    arguments: [-c, 'printf "secondary-tutorial\n" >> "$VIGILIA_TAG_TEST_MARKER"']
    command_tests:
      - description: Tutorial module assertion
        exit_code: 0
        timeout: 10
YAML

fail()
{
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

run_case()
{
    local name=$1 tests=$2 modules=$3
    shift 3
    local rc=0
    rm -f -- "$VIGILIA_TAG_TEST_MARKER"

    "$vigilia" --config-filename "$work/vigilia.config" \
        --console-type linear --reporting-directory "$work/report-$name" \
        "$@" > "$work/$name.log" 2>&1 || rc=$?
    if (( rc != 0 )); then
        tail -50 "$work/$name.log" >&2
        fail "$name: vigilia returned $rc"
    fi

    perl -MYAML::PP -e '
        my ($filename, $expected_tests, $expected_modules) = @ARGV;
        my $r = YAML::PP::LoadFile($filename);
        my $g = $r->{global};
        die "Report not finished\n" unless $g->{status} eq "Finished";
        die "Unexpected errors\n" unless $g->{error_count} == 0;
        die "Unexpected selected assertions\n"
            unless $g->{test_counters}->{current}->{command_test} == $expected_tests;
        die "Unexpected selected modules\n"
            unless $g->{test_counters}->{current}->{module_definition} == $expected_modules;
    ' "$work/report-$name/report.yml" "$tests" "$modules"

    printf 'PASS %-22s tests=%s modules=%s\n' "$name" "$tests" "$modules"
}

# With the smoke tag, only the inherited assertion may run. In particular
# *commands* with only explicitly excluded tests must not even be started.
run_case smoke 1 1 --tags ci:smoke
[[ $(cat "$VIGILIA_TAG_TEST_MARKER") == base ]] || fail 'Smoke execution crossed a tag boundary'

run_case smoke-duplicated 1 1 --tags ci:smoke --tags ci:smoke
[[ $(cat "$VIGILIA_TAG_TEST_MARKER") == base ]] || fail 'Duplicate tags altered the selection'

run_case regression 4 2 --tags ci:regression
sort "$VIGILIA_TAG_TEST_MARKER" > "$work/regression-actual"
printf '%s\n' base regression-assertion regression-command regression-module | sort > "$work/regression-expected"
cmp -s "$work/regression-actual" "$work/regression-expected" || fail 'Regression executed the wrong commands'

run_case union 4 2 --tags ci:smoke --tags ci:regression
cmp -s "$work/regression-actual" <(sort "$VIGILIA_TAG_TEST_MARKER") || fail 'Tag OR semantics changed execution'

# Selection works for documentation as well as CI, without executing commands.
run_case manual 2 1 --tags manual --show-command-tests
[[ ! -e "$VIGILIA_TAG_TEST_MARKER" ]] || fail 'Manual inspection executed commands'
run_case tutorial 3 2 --tags tutorial --show-command-tests
[[ ! -e "$VIGILIA_TAG_TEST_MARKER" ]] || fail 'Tutorial inspection executed commands'
run_case modules 1 1 --tags ci:smoke --show-modules
[[ ! -e "$VIGILIA_TAG_TEST_MARKER" ]] || fail 'Module inspection executed commands'

# Unfiltered execution still includes existing untagged modules and all tests.
run_case unfiltered 8 4 --regex-selector '.*'
[[ $(wc -l < "$VIGILIA_TAG_TEST_MARKER") -eq 8 ]] || fail 'Unfiltered run excluded a command'

cat > "$work/specifications/invalid.t" <<'YAML'
---
name: invalid.t
description: Invalid tag structure
tags: not-an-array
command_definitions:
  - description: Invalid tags may not silently pass
    command: /bin/true
    command_tests:
      - description: Must be rejected before runtime
        exit_code: 0
YAML

rc=0
"$vigilia" --config-filename "$work/vigilia.config" \
    --console-type linear --reporting-directory "$work/report-invalid" \
    --regex-selector 'invalid\.t$' --tags ci:smoke \
    > "$work/invalid.log" 2>&1 || rc=$?
(( rc != 0 )) || fail 'Malformed tags unexpectedly accepted'
grep -q 'Invalid tags for invalid.t' "$work/invalid.log" ||
    fail 'Malformed tags did not produce a useful diagnostic'

# The removed singular `tag` key must fail closed at every level, even for
# unfiltered inspection. Otherwise stale metadata could widen test execution.
for level in module command test; do
    case "$level" in
        module)
            cat > "$work/specifications/deprecated.t" <<'YAML'
---
name: deprecated.t
description: Unsupported singular module tag
tag: tutorial
command_definitions:
  - description: Command must never execute
    command: /bin/true
    command_tests:
      - description: Assertion must never execute
        exit_code: 0
YAML
            ;;
        command)
            cat > "$work/specifications/deprecated.t" <<'YAML'
---
name: deprecated.t
description: Unsupported singular command tag
tags: [tutorial]
command_definitions:
  - description: Command must never execute
    tag: tutorial
    command: /bin/true
    command_tests:
      - description: Assertion must never execute
        exit_code: 0
YAML
            ;;
        test)
            cat > "$work/specifications/deprecated.t" <<'YAML'
---
name: deprecated.t
description: Unsupported singular assertion tag
tags: [tutorial]
command_definitions:
  - description: Command must never execute
    command: /bin/true
    command_tests:
      - description: Assertion must never execute
        tag: tutorial
        exit_code: 0
YAML
            ;;
    esac
    rc=0
    "$vigilia" --config-filename "$work/vigilia.config" \
        --console-type linear --reporting-directory "$work/report-removed-$level" \
        --regex-selector 'deprecated\.t$' --show-modules \
        > "$work/removed-$level.log" 2>&1 || rc=$?
    (( rc != 0 )) || fail "Singular $level tag unexpectedly accepted"
    grep -Fq "'tag' is unsupported; use 'tags' (YAML array)" \
        "$work/removed-$level.log" ||
        fail "Singular $level tag did not produce a migration diagnostic"
done
printf 'PASS removed singular tag spelling rejected at all hierarchy levels.\n'

printf 'Vigilia hierarchical tag regression tests passed.\n'
