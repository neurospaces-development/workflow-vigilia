#!/usr/bin/env bash
# Boolean tag expressions on an isolated library (no Docker, sudo, network).
set -euo pipefail
vigilia=$(realpath "${1:-bin/vigilia}")
work=$(mktemp -d "${TMPDIR:-/tmp}/vigilia-tag-query.XXXXXX")
trap 'rc=$?; if (( rc == 0 )); then rm -rf -- "$work"; else echo "Tag-query evidence: $work" >&2; fi' EXIT
export VIGILIA_TAG_QUERY_ROOT="$work" NEUROSPACES_HARNESS_OPTION_EMAIL=0
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
printf '%s\n' 'Vigilia Boolean tag query parser regression tests passed.'
