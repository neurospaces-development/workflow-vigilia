#!/usr/bin/env bash
# Run independently selected Docker-based Vigilia modules in one CI job.
# The regular ci/test.sh entry point remains responsible for build, execution,
# report validation, and the positive-test-count quality gate.
set -euo pipefail

usage() {
    printf 'Usage: %s [--test-only]\n' "$0" >&2
    printf 'Set VIGILIA_DOCKER_MODULES_FILE to override ci/docker-suite.modules.\n' >&2
}

test_only=0
case ${1:-} in
    '') ;;
    --test-only) test_only=1; shift ;;
    *) usage; exit 2 ;;
esac
(( $# == 0 )) || { usage; exit 2; }

cd -- "$(dirname -- "$0")/.."
repository_root=$PWD
modules_file=${VIGILIA_DOCKER_MODULES_FILE:-"$repository_root/ci/docker-suite.modules"}
if [[ ! -f $modules_file ]]; then
    printf 'Missing Docker suite module list: %s\n' "$modules_file" >&2
    exit 2
fi

# Validate the entire configuration before running any module. A plain source
# pathname is less error-prone than asking CI operators to maintain regexes.
declare -a modules=()
declare -A visited=()
line_number=0
while IFS= read -r module || [[ -n $module ]]; do
    (( line_number += 1 ))
    [[ $module =~ ^[[:space:]]*(#|$) ]] && continue
    if [[ ! $module =~ ^[a-zA-Z0-9_./-]+$ ]] ||
       [[ $module == /* ]] || [[ $module == *..* ]] ||
       [[ $module == *'/./'* ]]; then
        printf 'Invalid Docker suite module path at %s:%d: %s\n' \
            "$modules_file" "$line_number" "$module" >&2
        exit 2
    fi
    case $module in
        *.t|*.module.yml|*/summary.yml) ;;
        *) printf 'Unsupported module filename: %s\n' "$module" >&2; exit 2 ;;
    esac
    if [[ ! -f $repository_root/vigilia/specifications/$module ]]; then
        printf 'Docker suite module does not exist: %s\n' "$module" >&2
        exit 2
    fi
    if [[ -n ${visited[$module]:-} ]]; then
        printf 'Duplicate Docker suite module: %s\n' "$module" >&2
        exit 2
    fi
    visited[$module]=1
    modules+=("$module")
done < "$modules_file"
if (( ${#modules[@]} == 0 )); then
    echo 'Docker suite must select at least one module.' >&2
    exit 2
fi

results_root=${CI_RESULTS_DIR:-"$repository_root/ci-results"}
mkdir -p -- "$results_root"
results_root=$(cd -- "$results_root" && pwd -P)
suite_parent="$results_root/docker-suite"
mkdir -p -- "$suite_parent"
suite_root=$(mktemp -d "$suite_parent/run.XXXXXX")
printf 'Docker suite evidence: %s\n' "$suite_root"

# The suite is serial. Existing Docker specifications may reuse container and
# network names; never run two of these modules concurrently in one daemon.
if ! docker info > "$suite_root/docker-preflight.log" 2>&1; then
    cat "$suite_root/docker-preflight.log" >&2
    echo 'Docker daemon is unavailable; no modules executed.' >&2
    exit 2
fi

printf 'module\tstatus\texit_code\tevidence\n' > "$suite_root/summary.tsv"
failed=0
index=0
for module in "${modules[@]}"; do
    (( index += 1 ))
    # Paths were restricted above. Use index plus path to avoid collisions
    # between modules that have the same basename (e.g. summary.yml).
    directory_name=$(printf '%02d-%s' "$index" "${module//\//_}")
    module_root="$suite_root/$directory_name"
    mkdir -p -- "$module_root"
    printf '%s\n' "$module" > "$module_root/module.txt"

    # Vigilia compares a regex against the discovered module pathname, not
    # just the basename. Dots are quoted, and the end anchor disambiguates
    # similarly named modules. Selection is untagged, as in the local suite.
    selector="${module//./[.]}\$"
    printf '%s\n' "$selector" > "$module_root/selector.txt"

    args=()
    if (( test_only || index > 1 )); then
        args+=(--test-only)
    fi

    printf 'Docker suite %d/%d: %s\n' "$index" "${#modules[@]}" "$module"
    # A prior module may have left a running container with this legacy
    # name. Keep the preceding diagnostics, then start from a clean container.
    docker container rm -f vigilia_test_container \
        > "$module_root/docker-cleanup.log" 2>&1 || true

    rc=0
    env VIGILIA_TEST_PROFILE='' \
        VIGILIA_REGEX_SELECTOR="$selector" \
        CI_RESULTS_DIR="$module_root" \
        ./ci/test.sh "${args[@]}" \
        > "$module_root/console.log" 2>&1 || rc=$?

    # Preserve diagnostics for this module before the next module reuses
    # vigilia_test_container. Never let diagnostic collection mask the rc.
    docker ps -a > "$module_root/docker-containers.log" 2>&1 || true
    docker network ls > "$module_root/docker-networks.log" 2>&1 || true
    docker image ls > "$module_root/docker-images.log" 2>&1 || true
    docker logs vigilia_test_container > "$module_root/docker-container.log" 2>&1 || true
    if (( rc == 0 )); then
        status=PASS
    else
        status=FAIL
        failed=1
        tail -n 40 "$module_root/console.log" >&2 || true
    fi
    printf '%s\t%s\t%d\t%s\n' "$module" "$status" "$rc" "$directory_name" \
        >> "$suite_root/summary.tsv"
    printf 'Docker suite %-4s %s (exit %d; %s)\n' \
        "$status" "$module" "$rc" "$module_root"
done

cat "$suite_root/summary.tsv"
exit "$failed"
