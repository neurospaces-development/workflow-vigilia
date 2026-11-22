# Common CI entry point

## First profile

The initial profile selects `20_vigilia/13_inspection_exit_code\.t$`.
It runs the real `vigilia` CLI via Automake and does not need Docker.
The selector is mandatory; there is no implicit full-suite run.

From a configured source checkout with the existing dependencies installed:

```sh
VIGILIA_REGEX_SELECTOR='20_vigilia/13_inspection_exit_code\.t$' \
    ci/test.sh --test-only
```

`--test-only` skips bootstrap, configure, build and system installation.
The caller must ensure that any installed binaries needed by selected tests
match the checkout. This is intended for local validation of the CI interface,
not a substitute for a clean-runner build.

On a fresh, disposable Ubuntu runner, as a non-root user with noninteractive sudo:

```sh
ci/install-dependencies.sh
VIGILIA_REGEX_SELECTOR='20_vigilia/13_inspection_exit_code\.t$' ci/test.sh
```

The provisioning list is a candidate until tested on a clean Ubuntu 24.04 runner.
The full entry point runs autogen, configure, make, sudo make install and make
check. The full installation explicitly sets `CPAN_INSTALL_STRICT_TESTS=1`
**inside** the elevated environment, so bundled CPAN `make test` failures stop
installation instead of being logged as warnings. The opt-in setting does not
change ordinary `make install` behaviour outside CI. Modules already installed
at the required version are skipped and are not retested. Never run untrusted
project code with elevated access on a shared host.
Run one job at a time per checkout and per system installation.

## Strict CPAN test regression

`ci/test.sh` always runs `ci/tests/test-cpan-install-strict.sh` before build
or installation. It uses a temporary fixture tarball and mocked `make` and
`sudo` commands; it does not install packages, access the network, or modify
the host. It covers default warning behavior, explicit strict/permissive
settings, a successful test run, and failing build, test, and install steps.
The `cpan-regression.log` and `.exit-code.txt` files are retained in the
run evidence. This smoke test also runs with `--test-only`.

## Evidence and exit status

Each invocation creates a fresh `ci-results/run.XXXXXX/` directory, or one
under `CI_RESULTS_DIR` if supplied. Use an absolute external results directory
or the default excluded directory; do not put evidence into other paths in
Docker build contexts. Keep the whole run directory as a CI artifact even
on failure. Review reports and logs before sharing them; they may contain
command output or sensitive data. The script does not upload artifacts.

- `environment.txt`: revision, OS, selector and build mode.
- `<stage>.log` and `<stage>.exit-code.txt`: complete output and status per stage.
- `report/report.yml` and any native assertion diagnostics.
- Automake's `run_harness.sh.log`, `.trs` and `test-suite.log` (when produced).
- `exit-code.txt`: overall exit status for normally terminated invocations.

Success requires both a successful `make check` and a valid native report
with `global.status: Finished`, a positive executed command-test count and
zero errors. A failed `make check` retains its original status; a missing or
invalid report also prevents success. Hard kills or runner loss may prevent
final evidence collection. CI platform artifact upload is configured separately.

## Other profiles

Docker-based and full-suite testing is not enabled by default. Some existing
specifications use fixed container names and global Docker cleanup; execute
those only on a disposable runner with a dedicated Docker daemon. Do not
select `.*` on a shared workstation. Full-suite dependencies, clean checkout
builds, distribution packaging, and Docker context validation remain separate
validation tasks.
