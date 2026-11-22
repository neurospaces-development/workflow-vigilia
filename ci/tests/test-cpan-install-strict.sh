#!/usr/bin/env bash
# Verify the opt-in CPAN test gate without installing modules or using sudo.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
installer="$repo_root/cpan/cpan_install"
work_root=$(mktemp -d "${TMPDIR:-/tmp}/vigilia-cpan-strict.XXXXXX")
trap 'rm -rf -- "$work_root"' EXIT

module=VigiliaCIInstallProbe-0.01
archive=01-${module}.tar.gz
mkdir -p "$work_root/source/$module" "$work_root/bin"
cat > "$work_root/source/$module/Makefile.PL" <<'PL'
print "Mock CPAN fixture configured\n";
PL
tar -czf "$work_root/$archive" -C "$work_root/source" "$module"

# These mock executables ensure the test does not invoke real make install or
# sudo. A real tarball and the actual cpan_install Perl script are exercised.
cat > "$work_root/bin/make" <<'MOCK_MAKE'
#!/bin/sh
set -eu
printf '%s\n' "${1:-build}" >> "$CI_CPAN_MAKE_CALLS"
case "${1:-build}" in
    test)    exit "${CI_CPAN_MAKE_TEST_RC:-0}" ;;
    install) : > "$CI_CPAN_INSTALL_MARKER"
             exit "${CI_CPAN_MAKE_INSTALL_RC:-0}" ;;
    *)       exit "${CI_CPAN_MAKE_BUILD_RC:-0}" ;;
esac
MOCK_MAKE
cat > "$work_root/bin/sudo" <<'MOCK_SUDO'
#!/bin/sh
set -eu
exec "$@"
MOCK_SUDO
chmod +x "$work_root/bin/make" "$work_root/bin/sudo"

assert_case() {
    local name=$1 mode=$2 test_rc=$3 build_rc=$4 install_rc=$5
    local outcome=$6 installed=$7 expected_log=$8
    local dir="$work_root/$name" rc=0
    mkdir -p "$dir"
    cp -- "$work_root/$archive" "$dir/"

    (
        cd -- "$dir"
        export PATH="$work_root/bin:$PATH"
        export CI_CPAN_MAKE_CALLS="$dir/make-calls.txt"
        export CI_CPAN_INSTALL_MARKER="$dir/installed"
        export CI_CPAN_MAKE_TEST_RC="$test_rc"
        export CI_CPAN_MAKE_BUILD_RC="$build_rc"
        export CI_CPAN_MAKE_INSTALL_RC="$install_rc"
        if [[ $mode == unset ]]; then
            unset CPAN_INSTALL_STRICT_TESTS
        else
            export CPAN_INSTALL_STRICT_TESTS="$mode"
        fi
        "$installer" "$archive"
    ) > "$dir/output.log" 2>&1 || rc=$?

    case "$outcome" in
        success)
            if (( rc != 0 )); then
                printf 'FAIL %s: expected success, got exit %d\n' "$name" "$rc" >&2
                cat "$dir/output.log" >&2
                exit 1
            fi
            ;;
        failure)
            if (( rc == 0 )); then
                printf 'FAIL %s: expected nonzero exit\n' "$name" >&2
                cat "$dir/output.log" >&2
                exit 1
            fi
            ;;
    esac
    if [[ -e $dir/installed ]] && [[ $installed == no ]]; then
        printf 'FAIL %s: installation occurred unexpectedly\n' "$name" >&2
        exit 1
    fi
    if [[ ! -e $dir/installed ]] && [[ $installed == yes ]]; then
        printf 'FAIL %s: installation was not attempted\n' "$name" >&2
        cat "$dir/output.log" >&2
        exit 1
    fi
    if ! grep -Fq -- "$expected_log" "$dir/output.log"; then
        printf 'FAIL %s: missing diagnostic: %s\n' "$name" "$expected_log" >&2
        cat "$dir/output.log" >&2
        exit 1
    fi
    printf 'PASS %-22s exit=%s install=%s\n' "$name" "$rc" "$installed"
}

assert_case default-warn       unset 7 0 0 success yes 'WARNING while testing'
assert_case explicit-permissive 0     7 0 0 success yes 'WARNING while testing'
assert_case strict-fail        1     7 0 0 failure no  'ERROR while testing'
assert_case strict-pass        1     0 0 0 success yes 'Installing VigiliaCIInstallProbe'
assert_case strict-build-fail  1     0 6 0 failure no  'ERROR while building'
assert_case strict-install-fail 1    0 0 9 failure yes 'ERROR while installing'
assert_case invalid-mode       true  0 0 0 failure no  'CPAN_INSTALL_STRICT_TESTS must be 0 or 1'

# The rejecting cases must never run the installation step. For an invalid
# setting, fail even before any mock make invocation.
for case_name in strict-fail strict-build-fail invalid-mode; do
    if [[ -f "$work_root/$case_name/make-calls.txt" ]] &&
       grep -qx install "$work_root/$case_name/make-calls.txt"; then
        printf 'FAIL %s: mock make install was invoked\n' "$case_name" >&2
        exit 1
    fi
done
if [[ -e "$work_root/invalid-mode/make-calls.txt" ]]; then
    printf 'FAIL invalid-mode: make invoked despite invalid configuration\n' >&2
    exit 1
fi

printf 'CPAN strict installation regression tests passed.\n'
