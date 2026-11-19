#!/usr/bin/env bash
# Ubuntu/Debian runner provisioning; execute only on a disposable runner.
set -euo pipefail

if (( EUID == 0 )); then
    elevate=()
else
    elevate=(sudo -n)
    "${elevate[@]}" true
fi

export DEBIAN_FRONTEND=noninteractive
"${elevate[@]}" env DEBIAN_FRONTEND=noninteractive apt-get update
"${elevate[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    autoconf automake build-essential git perl sudo \
    python3-dev python3-setuptools python3-wheel python3-yaml python-is-python3 \
    jq grc \
    libclone-perl libexpect-perl libfile-chdir-perl libfile-find-rule-perl \
    libinline-perl libinline-c-perl libipc-system-simple-perl libjson-perl \
    libnet-ip-perl libterm-readkey-perl libtoml-perl libyaml-pp-perl \
    libwww-perl libxml-parser-perl \
    screen unzip openssh-server sshpass tmux libfaketime

# Bundled CPAN modules are installed by make install. Docker, when needed,
# must be provisioned separately on the isolated runner.
