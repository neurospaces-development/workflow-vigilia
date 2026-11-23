#!/usr/bin/env bash
# Hosted integration regression for the exact-path Vigilia selector.
# This is deliberately non-executing inspection: a developer can run it on a
# machine with the required Perl modules without provisioning test containers.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
output=$(mktemp)
errors=$(mktemp)
trap 'rm -f -- "$output" "$errors"' EXIT

bin/vigilia --show-command-descriptions \
    --module 20_vigilia/10_help/summary.yml > "$output"
grep -Fq '20_vigilia/10_help/summary.yml' "$output"
if grep -Fq '40_workflow-automator/' "$output"; then
    echo 'Exact module selection included a non-requested module' >&2
    exit 1
fi

if bin/vigilia --show-command-descriptions \
    --module 20_vigilia/__no_such_module__/summary.yml > "$output" 2> "$errors"; then
    echo 'Unknown module should have been rejected' >&2
    exit 1
fi
grep -Fq -- '--module does not exist' "$errors"

if bin/vigilia --show-command-descriptions \
    --module 20_vigilia/10_help/summary.yml \
    --regex-selector '^40_workflow' > "$output" 2> "$errors"; then
    echo 'Conflicting exact and regex selectors were accepted' >&2
    exit 1
fi
grep -Fq -- '--module cannot be combined' "$errors"
printf 'Exact Vigilia module selection regression tests passed.\n'
