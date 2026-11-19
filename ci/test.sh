#!/usr/bin/env bash
# Shared entry point for GitHub Actions, GitLab CI and local validation.
set -euo pipefail

usage() {
    printf 'Usage: VIGILIA_REGEX_SELECTOR=REGEX %s [--test-only]\n' "$0" >&2
}

build=1
case ${1:-} in
    '') ;;
    --test-only) build=0; shift ;;
    *) usage; exit 2 ;;
esac
(( $# == 0 )) || { usage; exit 2; }
: "${VIGILIA_REGEX_SELECTOR:?Select a nonempty regex explicitly}"
if (( EUID == 0 )); then
    echo 'Run the test harness as a non-root user.' >&2
    exit 2
fi

cd -- "$(dirname -- "$0")/.."
export LC_ALL=C.UTF-8 TERM=dumb VIGILIA_CI=1 VIGILIA_REGEX_SELECTOR
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
    printf 'Selector: %s\nBuild and install: %s\n' "$VIGILIA_REGEX_SELECTOR" "$build"
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

if (( build )); then
    run_step sudo-check sudo -n true
    run_step autogen ./autogen.sh
    run_step configure ./configure
    run_step build make
    run_step install sudo -n make install
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
