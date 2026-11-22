#!/usr/bin/env bash
# Boolean tag expressions on an isolated library (no Docker, sudo, network).
set -euo pipefail
vigilia=$(realpath "${1:-bin/vigilia}")
work=$(mktemp -d "${TMPDIR:-/tmp}/vigilia-tag-query.XXXXXX")
trap 'rc=$?; if (( rc == 0 )); then rm -rf -- "$work"; else echo "Tag-query evidence: $work" >&2; fi' EXIT
export VIGILIA_TAG_QUERY_ROOT="$work" NEUROSPACES_HARNESS_OPTION_EMAIL=0
export VIGILIA_TAG_QUERY_MARKER="$work/executed"
mkdir "$work/specifications"
cat > "$work/vigilia.config" <<'CONFIG'
return {
    core_directory => './',
    description => 'Isolated Boolean tag-query fixture',
    tests_directory => "$ENV{VIGILIA_TAG_QUERY_ROOT}/specifications",
    html_output_directory => "$ENV{VIGILIA_TAG_QUERY_ROOT}/html",
    package => { name => 'tag-query-fixture', version => 'test' },
};
CONFIG

# All commands and assertions are intentionally untagged in patch 0022.
# This tests parsing, precedence, NOT and the CLI independently of the
# effective-tag inheritance rules added in patch 0023.
for pair in 'both:tutorial,ci:regression' 'tutorial:tutorial' \
            'regression:ci:regression' 'manual:manual' 'untagged:'; do
    name=${pair%%:*}
    tags=${pair#*:}
    {
        printf '%s\n' '---' "name: $name.t" "description: $name"
        if [[ -n $tags ]]; then
            printf 'tags: [%s]\n' "$tags"
        fi
        cat <<'YAML'
command_definitions:
  - description: Basic assertion
    command: /bin/true
    command_tests:
      - description: Successful command
        exit_code: 0
        timeout: 10
YAML
    } > "$work/specifications/$name.t"
done

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
run_case() {
    local name=$1 tests=$2 modules=$3
    shift 3
    local rc=0
    rm -f -- "$VIGILIA_TAG_QUERY_MARKER"
    "$vigilia" --config-filename "$work/vigilia.config" \
        --console-type linear --reporting-directory "$work/report-$name" \
        "$@" > "$work/$name.log" 2>&1 || rc=$?
    if (( rc != 0 )); then
        tail -40 "$work/$name.log" >&2
        fail "$name: vigilia exited $rc"
    fi
    perl -MYAML::PP -e '
        my ($filename, $expected_tests, $expected_modules) = @ARGV;
        my $g = YAML::PP::LoadFile($filename)->{global};
        die "incomplete report\n" unless $g->{status} eq "Finished";
        die "errors in report\n" if $g->{error_count};
        die "wrong test count\n" unless $g->{test_counters}->{current}->{command_test} == $expected_tests;
        die "wrong module count\n" unless $g->{test_counters}->{current}->{module_definition} == $expected_modules;
    ' "$work/report-$name/report.yml" "$tests" "$modules"
    printf 'PASS %-24s tests=%s modules=%s\n' "$name" "$tests" "$modules"
}

run_case and 1 1 --tag-query 'tutorial AND ci:regression'
run_case or 3 3 --tag-query 'tutorial OR manual'
run_case precedence 2 2 --tag-query 'tutorial OR manual AND ci:regression'
run_case grouped 1 1 --tag-query '(tutorial OR manual) AND ci:regression'
run_case not 2 2 --tag-query 'tutorial AND NOT ci:regression'
run_case pure-not 3 3 --tag-query 'NOT ci:regression'
run_case quoted 2 2 --tag-query '"ci:regression"'
run_case repeated 2 2 --tag-query 'tutorial OR tutorial'
run_case legacy-or 3 3 --tags tutorial --tags manual

for expression in '' 'tutorial AND' 'tutorial XOR manual' \
    '(tutorial OR manual' 'tutorial OR )' 'AND tutorial' 'tutorial NOT manual'; do
    rc=0
    "$vigilia" --config-filename "$work/vigilia.config" \
        --console-type linear --reporting-directory "$work/invalid-report" \
        --tag-query "$expression" > "$work/invalid.log" 2>&1 || rc=$?
    (( rc != 0 )) || fail "invalid expression '$expression' accepted"
    grep -q 'Invalid --tag-query' "$work/invalid.log" || fail 'missing parser diagnostic'
done
rc=0
"$vigilia" --config-filename "$work/vigilia.config" \
    --console-type linear --tag-query tutorial --tags manual \
    > "$work/mixed.log" 2>&1 || rc=$?
(( rc != 0 )) || fail '--tags mixed with --tag-query accepted'
grep -q -- '--tag-query cannot be combined with --tags' "$work/mixed.log" ||
    fail 'missing mixed-filter diagnostic'
# Nested knowledge-base selection: namespaced child tags override the same
# parent namespace, but bare documentation labels accumulate on descendants.
cat > "$work/specifications/effective.t" <<'YAML'
---
name: effective.t
description: Combined documentation and CI metadata
tags: [tutorial, ci:smoke, ci:regression]
command_definitions:
  - description: Inherit every module tag
    command: /bin/sh
    arguments: [-c, 'printf "base\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Inherited test
        exit_code: 0
  - description: Child overrides CI classification for regression
    tags: [ci:regression]
    command: /bin/sh
    arguments: [-c, 'printf "regression-command\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Regression-only command
        exit_code: 0
  - description: Test overrides the inherited CI namespace
    command: /bin/sh
    arguments: [-c, 'printf "regression-test\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Regression-only assertion
        tags: [ci:regression]
        exit_code: 0
  - description: Child overrides CI classification for smoke
    tags: [ci:smoke]
    command: /bin/sh
    arguments: [-c, 'printf "smoke-command\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Smoke-only command
        exit_code: 0
  - description: A manual label supplements inherited tutorial and CI tags
    tags: [manual]
    command: /bin/sh
    arguments: [-c, 'printf "manual-command\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Manual and tutorial with inherited CI tags
        exit_code: 0
YAML

cat > "$work/specifications/descendant.t" <<'YAML'
---
name: descendant.t
description: A module lacking the requested tutorial and CI tags
tags: [manual]
command_definitions:
  - description: Child defines a more specific category
    tags: [tutorial, ci:regression]
    command: /bin/sh
    arguments: [-c, 'printf "descendant\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Reach through a nonmatching parent
        exit_code: 0
YAML

cat > "$work/specifications/assertion.t" <<'YAML'
---
name: assertion.t
description: Never start a command with no matching assertion
tags: [tutorial, ci:smoke, ci:regression]
command_definitions:
  - description: Parent looks eligible for smoke but assertion is regression-only
    command: /bin/sh
    arguments: [-c, 'printf "UNEXPECTED\n" >> "$VIGILIA_TAG_QUERY_MARKER"']
    command_tests:
      - description: Explicitly regression-only assertion
        tags: [ci:regression]
        exit_code: 0
YAML

run_case effective-smoke 3 1 --regex-selector 'effective\.t$' \
    --tag-query 'tutorial AND ci:smoke'
printf '%s\n' base manual-command smoke-command | sort > "$work/expected-smoke"
sort "$VIGILIA_TAG_QUERY_MARKER" > "$work/actual-smoke"
cmp -s "$work/actual-smoke" "$work/expected-smoke" || fail 'Smoke query crossed CI override'

run_case effective-regression 4 1 --regex-selector 'effective\.t$' \
    --tag-query 'tutorial AND ci:regression'
printf '%s\n' base manual-command regression-command regression-test | sort > "$work/expected-regression"
sort "$VIGILIA_TAG_QUERY_MARKER" > "$work/actual-regression"
cmp -s "$work/actual-regression" "$work/expected-regression" || fail 'Regression query did not respect hierarchy'

run_case effective-manual 1 1 --regex-selector 'effective\.t$' \
    --tag-query 'manual AND ci:regression'
[[ $(cat "$VIGILIA_TAG_QUERY_MARKER") == manual-command ]] || fail 'Bare tag accumulation failed'

run_case descendant 1 1 --regex-selector 'descendant\.t$' \
    --tag-query 'tutorial AND ci:regression'
[[ $(cat "$VIGILIA_TAG_QUERY_MARKER") == descendant ]] || fail 'Descendant did not activate module'

run_case assertion-excluded 0 0 --regex-selector 'assertion\.t$' \
    --tag-query 'ci:smoke'
[[ ! -e $VIGILIA_TAG_QUERY_MARKER ]] || fail 'Excluded assertion started command'

run_case assertion-selected 1 1 --regex-selector 'assertion\.t$' \
    --tag-query 'ci:regression'
[[ $(cat "$VIGILIA_TAG_QUERY_MARKER") == UNEXPECTED ]] || fail 'Selected assertion did not run'

run_case inspection-hierarchy 4 1 --regex-selector 'effective\.t$' \
    --tag-query 'tutorial AND ci:regression' --show-command-tests
[[ ! -e $VIGILIA_TAG_QUERY_MARKER ]] || fail 'Documentation inspection executed commands'

# The existing --tags semantics still narrow on each explicitly tagged child
# rather than applying the additive effective-tag expression semantics.
run_case legacy-hierarchy 2 1 --regex-selector 'effective\.t$' --tags ci:smoke
printf '%s\n' base smoke-command | sort > "$work/expected-legacy"
sort "$VIGILIA_TAG_QUERY_MARKER" > "$work/actual-legacy"
cmp -s "$work/actual-legacy" "$work/expected-legacy" || fail 'Legacy --tags selection changed'

printf '%s\n' 'Vigilia Boolean tag query and hierarchical selection tests passed.'
