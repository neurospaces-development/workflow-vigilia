#!/bin/sh

set -eu

if [ "${VIGILIA_CI:-0}" = 1 ]; then

    # Require explicit CI execution parameters.

    : "${VIGILIA_REPORT_DIR:?Missing VIGILIA_REPORT_DIR}"
    : "${VIGILIA_REGEX_SELECTOR:?Missing VIGILIA_REGEX_SELECTOR}"

    # Tags are generic specification metadata: these CI profile mappings do
    # not prevent manual/tutorial selection using --tags outside CI.
    case "${VIGILIA_TEST_PROFILE:-}" in
        smoke)
            set -- --tags ci:smoke "$@"
            ;;
        regression)
            set -- --tags ci:regression "$@"
            ;;
        full)
            if [ "${VIGILIA_ALLOW_FULL:-0}" != 1 ]; then
                echo "Full suite requires VIGILIA_ALLOW_FULL=1 and an isolated Docker runner" >&2
                exit 2
            fi
            ;;
        '')
            # Backward compatibility: a regex selector without a profile.
            ;;
        *)
            echo "Unknown VIGILIA_TEST_PROFILE: $VIGILIA_TEST_PROFILE" >&2
            exit 2
            ;;
    esac

    export NEUROSPACES_HARNESS_OPTION_EMAIL=0

    mkdir -p "$VIGILIA_REPORT_DIR"

    if [ -n "${VIGILIA_EXACT_MODULE:-}" ]; then
        set -- --module "$VIGILIA_EXACT_MODULE" "$@"
    else
        set -- --regex-selector "$VIGILIA_REGEX_SELECTOR" "$@"
    fi
    exec bin/vigilia \
        --console-type linear \
        --reporting-directory "$VIGILIA_REPORT_DIR" \
        "$@"
fi

exec bin/vigilia "$@"

