#!/usr/bin/env bash
# Shared entry point for GitHub Actions, GitLab CI and local validation.
set -euo pipefail

usage() {
    printf 'Usage: VIGILIA_TEST_PROFILE=smoke|regression|full %s [--test-only] [--focused]\n' "$0" >&2
    printf '   or: VIGILIA_REGEX_SELECTOR=REGEX %s [--test-only]\n' "$0" >&2
}

build=1
focused=0
while (( $# )); do
    case $1 in
        --test-only) build=0 ;;
        --focused) focused=1 ;;
        *) usage; exit 2 ;;
    esac
    shift
done
if (( focused )) && [[ -n ${VIGILIA_TEST_PROFILE:-} ]]; then
    echo '--focused requires explicit selection, not a CI profile' >&2
    exit 2
fi
# Profile selection is opt-in for the shared CI interface. The previous
# explicit-regex invocation remains supported for focused reruns and probes.
case "${VIGILIA_TEST_PROFILE:-}" in
    smoke|regression)
        VIGILIA_REGEX_SELECTOR=${VIGILIA_REGEX_SELECTOR:-'.*'}
        ;;
    full)
        if [[ -n ${VIGILIA_EXACT_MODULE:-} ]]; then
            echo 'Full suite must not be narrowed by VIGILIA_EXACT_MODULE' >&2
            exit 2
        fi
        if [[ "${VIGILIA_ALLOW_FULL:-0}" != 1 ]]; then
            echo 'Full suite requires VIGILIA_ALLOW_FULL=1 on an isolated Docker runner' >&2
            exit 2
        fi
        VIGILIA_REGEX_SELECTOR=${VIGILIA_REGEX_SELECTOR:-'.*'}
        ;;
    '')
        if [[ -z ${VIGILIA_EXACT_MODULE:-} ]]; then
            : "${VIGILIA_REGEX_SELECTOR:?Set VIGILIA_TEST_PROFILE or an explicit regex selector}"
        elif [[ -n ${VIGILIA_REGEX_SELECTOR:-} ]]; then
            echo 'Choose either VIGILIA_EXACT_MODULE or VIGILIA_REGEX_SELECTOR' >&2
            exit 2
        else
            VIGILIA_REGEX_SELECTOR='.*'  # retained for CI environment metadata
        fi
        ;;
    *)
        echo "Unsupported VIGILIA_TEST_PROFILE: $VIGILIA_TEST_PROFILE" >&2
        exit 2
        ;;
esac
if (( EUID == 0 )); then
    echo 'Run the test harness as a non-root user.' >&2
    exit 2
fi

cd -- "$(dirname -- "$0")/.."
export LC_ALL=C.UTF-8 TERM=dumb VIGILIA_CI=1 VIGILIA_REGEX_SELECTOR
export VIGILIA_EXACT_MODULE="${VIGILIA_EXACT_MODULE:-}"
export VIGILIA_TEST_PROFILE="${VIGILIA_TEST_PROFILE:-}"
export NEUROSPACES_HARNESS_OPTION_EMAIL=0

# Separate evidence from every invocation; never reuse an older report.
results_root=${CI_RESULTS_DIR:-"$PWD/ci-results"}
mkdir -p -- "$results_root"
results_root=$(cd -- "$results_root" && pwd -P)
run_dir=$(mktemp -d "$results_root/run.XXXXXX")
export VIGILIA_REPORT_DIR="$run_dir/report"
mkdir -- "$VIGILIA_REPORT_DIR"
check_started=0

collect() {
    local rc=$? f
    trap - EXIT
    set +e
    if (( check_started )); then
        for f in run_harness.sh.log run_harness.sh.trs test-suite.log; do
            if [[ -f "$f" ]]; then
                cp -- "$f" "$run_dir/" || { (( rc != 0 )) || rc=1; }
            elif (( rc == 0 )); then
                printf 'Missing Automake evidence: %s\n' "$f" >&2
                rc=1
            fi
        done
    fi
    printf '%s\n' "$rc" > "$run_dir/exit-code.txt" || { (( rc != 0 )) || rc=1; }
    printf 'CI result: %s; evidence: %s\n' "$rc" "$run_dir"
    exit "$rc"
}
trap collect EXIT

printf 'CI evidence: %s\n' "$run_dir"
{
    git rev-parse HEAD
    uname -a
    cat /etc/os-release
    printf 'Profile: %s\nSelector: %s\nBuild and install: %s\n' \
        "${VIGILIA_TEST_PROFILE:-<explicit regex>}" "$VIGILIA_REGEX_SELECTOR" "$build"
} > "$run_dir/environment.txt"

run_step() {
    local stage=$1 rc=0
    shift
    printf 'CI stage: %s\n' "$stage"
    "$@" > "$run_dir/$stage.log" 2>&1 || rc=$?
    if ! printf '%s\n' "$rc" > "$run_dir/$stage.exit-code.txt"; then
        (( rc != 0 )) || rc=1
        printf 'Cannot record status for stage: %s\n' "$stage" >&2
    fi
    if (( rc != 0 )); then
        printf 'CI stage failed: %s (exit %s); see %s/%s.log\n' \
            "$stage" "$rc" "$run_dir" "$stage" >&2
    fi
    return "$rc"
}

# The full CI quality gate runs these regression stages once. Focused module
# investigations are intentionally narrower: each still builds (unless
# --test-only), executes make check and validates its own native report.
if (( ! focused )); then
    run_step cpan-regression bash ci/tests/test-cpan-install-strict.sh
    run_step artifact-regression python3 ci/tests/test-download-artifacts.py
    run_step artifact-workflow python3 ci/tests/test-workflow-artifacts.py
    run_step docker-network-regression python3 ci/tests/test-docker-network.py
    run_step docker-suite-regression python3 ci/tests/test-docker-suite.py
fi

if (( build )); then
    run_step sudo-check sudo -n true
    run_step autogen ./autogen.sh
    run_step configure ./configure
    run_step build make
    # Put the strict mode inside the sudo environment: sudo commonly
    # discards caller environment variables.
    run_step install sudo -n env CPAN_INSTALL_STRICT_TESTS=1 make install
fi

# The native report and exact-module selector tests require installed modules.
if (( ! focused )); then
    run_step module-selection-regression bash ci/tests/test-exact-module-selection.sh
    run_step report-counters bash ci/tests/test-report-counters.sh
fi

# These are generated Automake outputs. Clear them only immediately before
# this run so that early build failures cannot collect stale evidence.
rm -f -- run_harness.sh.log run_harness.sh.trs test-suite.log
check_started=1
check_rc=0
report_rc=0
run_step make-check make check || check_rc=$?
run_step validate-report perl ci/validate-report.pl "$VIGILIA_REPORT_DIR/report.yml" || report_rc=$?

# Keep make's original nonzero status even if report validation also fails.
if (( check_rc != 0 )); then
    exit "$check_rc"
fi
exit "$report_rc"
