# Shared CI entry point and reusable test tags

## Execution profiles

`vigilia` tags are **generic selection metadata**, not an exclusive CI feature.
The `ci:` namespace identifies runner suitability; existing `manual` tags
remain valid, and `tutorial` (or other topical tags) may later select source
material for documentation conversion.

| Profile | Tag filter | Environment |
| --- | --- | --- |
| `smoke` | `ci:smoke` | No Docker; fast hosted jobs |
| `regression` | `ci:regression` | No Docker; includes smoke plus broader checks |
| `full` | No tag filter | Dedicated disposable runner and Docker daemon |

The full profile is never enabled implicitly. It requires
`VIGILIA_TEST_PROFILE=full VIGILIA_ALLOW_FULL=1` and a genuinely isolated
execution environment. **Do not enable it on shared workstations or ordinary
hosted jobs.** The current suite contains fixed container names and Docker
cleanup operations.

After configuring and installing dependencies, run:

```sh
VIGILIA_TEST_PROFILE=smoke ci/test.sh --test-only
VIGILIA_TEST_PROFILE=regression ci/test.sh --test-only
```

For a fresh disposable CI runner, omit `--test-only`:

```sh
ci/install-dependencies.sh
VIGILIA_TEST_PROFILE=smoke ci/test.sh
```

`--test-only` skips Autotools generation, configure, build and installation.
Its correctness depends on using installed software that corresponds to the
checked-out revision.

The old explicit-regex interface remains supported for targeted reruns:

```sh
VIGILIA_REGEX_SELECTOR='20_vigilia/13_inspection_exit_code\\.t$' \
    ci/test.sh --test-only
```

When a profile is selected, `VIGILIA_REGEX_SELECTOR` is optional and defaults
to `.*`. If explicitly provided, the regex and the profile tag are combined
using logical AND; this is useful for narrowing a failing profile run.

The profile names are mappings maintained by `run_harness.sh`, not built-in
constraints on the specification format. `--tags` can also be used for
`manual`, `tutorial`, `security`, subsystem names, or other classifications.

## Tag hierarchy and documentation

Use the YAML array spelling `tags`, including for individual command tests:

```yaml
name: example.t
tags: [ci:smoke, ci:regression, manual]
command_definitions:
  - description: Fast example included in the manual
    command: /bin/true
    command_tests:
      - description: Exit successfully
        exit_code: 0
  - description: Extra regression command
    tags: [ci:regression]
    command: /bin/true
    command_tests:
      - description: Regression-only assertion
        exit_code: 0
```

The module must explicitly match a requested tag. Untagged children inherit
their selected parent's tags. Explicit child tags restrict selection at that
level; they do **not** automatically union with parent tags. Multiple `--tags`
options are alternatives (OR). Duplicate requested tags are harmless. Only
`tags` is valid, and its value must be a YAML array. The removed singular `tag`
key is rejected with an error, even without a tag filter.

Inspection and documentation output also honor these tags; for example:

```sh
bin/vigilia --tags manual --show-command-tests
bin/vigilia --tags tutorial --show-modules
```

These commands perform selection without executing tested commands. Tags
select the source material; conversion into a complete manual or tutorial
with ordering, narrative and cross-references is a separate concern.
Selecting a tag does not itself guarantee that its module contains
publication-ready content.

## Build and installation

The full CI entry point runs autogen, configure, make, `sudo make install`,
and make check. It explicitly sets `CPAN_INSTALL_STRICT_TESTS=1` **inside**
the elevated installation environment. Bundled CPAN `make test` failures
therefore stop installation rather than being logged as warnings. Outside
CI, ordinary installations retain their permissive behaviour. Modules
already installed at the required version are skipped and not retested.

Never run untrusted project code with elevated access on a shared host.
Run only one job at a time per checkout and system installation.

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
