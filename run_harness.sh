#!/bin/sh

set -eu

if [ "${VIGILIA_CI:-0}" = 1 ]; then

    # Require explicit CI execution parameters.

    : "${VIGILIA_REPORT_DIR:?Missing VIGILIA_REPORT_DIR}"
    : "${VIGILIA_REGEX_SELECTOR:?Missing VIGILIA_REGEX_SELECTOR}"

    export NEUROSPACES_HARNESS_OPTION_EMAIL=0

    mkdir -p "$VIGILIA_REPORT_DIR"

    exec bin/vigilia \
        --console-type linear \
        --reporting-directory "$VIGILIA_REPORT_DIR" \
        --regex-selector "$VIGILIA_REGEX_SELECTOR" \
        "$@"
fi

exec bin/vigilia "$@"

