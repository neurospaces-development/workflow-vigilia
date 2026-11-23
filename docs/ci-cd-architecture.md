# CI/CD architecture and operation

This document describes the **implemented CI and verification infrastructure**
for `workflow` and `vigilia` as configured in this repository after the
introduction of the hosted `full` jobs and the subsequent removal of
redundant automatic subset jobs. Both hosted full jobs passed at revision
`43bb8aa85c76` (36 modules, 256 enabled assertions each).
The current pipeline builds, installs, tests, validates and publishes evidence;
it does **not** deploy software or define repository branch-protection rules.

## Goals and invariants

1. The version-controlled `vigilia` specifications are the **single source of
   product knowledge** for tests and future manuals/tutorials. Publication tags
   never exempt an executable specification from unfiltered verification.
2. The `full` profile discovers the same unfiltered knowledge base as local
   `bin/vigilia`: there is no second `full` module list. Execution results can
   differ when local and hosted environments differ.
3. The `smoke` and `regression` tag selections are fast, deliberately smaller
   feedback loops. Focused Docker testing is explicitly requested, not
   automatically repeated when the full suite already runs.
4. The same `ci/test.sh`, Automake harness, `vigilia` assertions and native
   reporting contract apply on both CI providers. Runner provisioning differs.
5. Failed runs must retain diagnostic evidence. An artifact's integrity or
   correct Git revision does **not** mean its tests passed.

## Component and evidence flow

```text
               one version-controlled Git revision (one source tree)
                                  |
                 +----------------+------------------+
                 |                |                  |
         Local developer     GitHub Actions      GitLab CI/CD
          bin/vigilia       ubuntu-24.04 VM    ubuntu:24.04 job
                 |          local daemon         TLS DinD
                 |                |                  |
                 |         ci/install-dependencies.sh
                 |                |                  |
                 |         +------+-----------+------+
                 |         |                  |
                 |     ci/test.sh        ci/docker-suite.sh
                 |         |           (serial subset; calls
                 |         |            ci/test.sh per module)
                 |         +------------------+
                 |                |
                 |          make check / Automake
                 |                |
                 |          run_harness.sh
                 |                |
                 +----------> bin/vigilia
                                  |
                        vigilia/specifications/
                                  |
                     native report.yml + stage logs
                                  |
                     hosted job artifact upload
                                  |
                         provider REST APIs
                                  |
                      ci/download-artifacts.py
                                  ^
                                  |
             configured-workflows/automation-commands-ci.py
                     (`automation-workflow ci ...`)
                                  |
                  manifests + checksums + combined ZIP
```

The diagram is a logical flow: plain local `bin/vigilia` bypasses the
CI wrapper, whereas hosted jobs use the common `ci/test.sh` quality gate.
On GitLab, the **full** job inherits the Docker pilot's bootstrap and changes
the final command to `ci/test.sh`; it does **not** call `ci/docker-suite.sh`.

| Layer | Source of truth / responsibility |
| --- | --- |
| Provider trigger and runner | [`.github/workflows/regression-tests.yml`](../.github/workflows/regression-tests.yml) and [`.gitlab-ci.yml`](../.gitlab-ci.yml): event/branch policy, runner, isolation, dependencies, upload. |
| Installation | [`ci/install-dependencies.sh`](../ci/install-dependencies.sh): Ubuntu/Debian prerequisites; GitLab additionally bootstraps its job container. |
| Common quality gate | [`ci/test.sh`](../ci/test.sh): one run, stage logs/statuses, build/install, `make check`, native report validation. |
| Test selection / execution | [`run_harness.sh`](../run_harness.sh), [`bin/vigilia`](../bin/vigilia) and [`vigilia/specifications/`](../vigilia/specifications/): tag/regex selection, preparation, assertions and reporting. |
| Incremental Docker isolation | [`ci/docker-suite.sh`](../ci/docker-suite.sh), [`ci/docker-suite.modules`](../ci/docker-suite.modules): serial, independent selected-module runs and evidence. |
| Report acceptance | [`ci/validate-report.pl`](../ci/validate-report.pl): finished native report, positive executed-test count, zero errors. |
| Artifact API and integrity | [`ci/download-artifacts.py`](../ci/download-artifacts.py): discovery, waiting, download, revision/checksum checks, manifests and bundles. |
| Orchestration entry point | [`configured-workflows/automation-commands-ci.py`](../configured-workflows/automation-commands-ci.py) and [`ci_artifacts.yml`](../configured-workflows/automation-configuration-data/ci_artifacts.yml): `automation-workflow ci artifacts_*` commands and provider/profile naming. |

## Pipeline topology and trigger policy

These are the **currently configured** jobs, not an abstract future design:

| Profile / job | GitHub Actions | GitLab CI/CD | Selection | Runtime |
| --- | --- | --- | --- | --- |
| `smoke` | Local (`ci/test.sh`) | `vigilia-regression` (manual) | `--tags ci:smoke` | Fast subset, not scheduled on pushes |
| `regression` | `regression-tests` (PRs) | Same manual matrix | `--tags ci:regression` | Non-Docker; native `ci/test.sh` |
| Focused Docker (manual) | `docker-pilot` | `vigilia-docker-pilot` | Explicit paths from job input or `--module` | Docker-enabled `ci/docker-suite.sh` |
| `full` | `full-tests` | `vigilia-full` | No tag exclusions; module regex defaults to `.*` | One unfiltered `ci/test.sh` run |

Smoke/regression jobs have 60-minute timeouts, and focused Docker and full
jobs have 90-minute timeouts. Artifacts are retained for 30 days when the
runner can upload them.

**GitHub:** Trusted pushes to `master` and `ci/regression-integration` execute
**only `full`**, not a duplicate Docker subset or profile matrix. Pull
requests to `master` execute one non-Docker regression job, without
privileged Docker tests. A manual `workflow_dispatch` with a nonempty
`docker_modules` input runs the focused Docker job, without the full job.
The workflow requests `contents: read` and checks out without persisted
credentials.

**GitLab:** Trusted pushes to the default branch and
`ci/regression-integration` execute **only `vigilia-full`**. A developer may
start a manual (web) pipeline on a development branch and run the optional
`vigilia-docker-pilot` job with `VIGILIA_DOCKER_MODULES` set to selected paths.
Smoke/regression remain manually available, but are not automatic duplicates.
The full job **extends** the Docker bootstrap and overrides its manual rule,
using `VIGILIA_DOCKER_EXECUTION=full`. There is only a `test` stage.

Branch protection / required-check policies are administered at the provider
and are **not** established merely by these YAML definitions. An experimental
full failure is still a failing CI job; it is not silently tolerated.

## Selection semantics and knowledge-base integrity

- `ci/test.sh` requires either `VIGILIA_TEST_PROFILE=smoke|regression|full`
  or an explicit `VIGILIA_REGEX_SELECTOR`; it refuses execution as root.
- In CI mode, `run_harness.sh` maps `smoke` and `regression` to the respective
  `--tags` arguments and invokes `bin/vigilia` with linear console output, an
  explicit reporting directory and `--regex-selector`.
- `full` is guarded by `VIGILIA_ALLOW_FULL=1` and adds **no** `--tags`
  selection. Its default regex is `.*`. For equivalence with local unfiltered
  discovery, do **not** set `VIGILIA_REGEX_SELECTOR` to a narrower expression
  in the full job.
- The two CI subset tags are independent selectors; the directory named
  `25_smoke` is **not** automatically assigned to `ci:smoke`.
- The focused Docker suite is path-selected and serial, but its committed
  module file is intentionally empty. Selection must be explicit through
  `--module PATH`, comma-separated `VIGILIA_DOCKER_MODULES`, or an alternate
  `VIGILIA_DOCKER_MODULES_FILE`; no empty runs are accepted. One `ci/test.sh`
  execution/report is generated per selected module, with build/install once.
- The full run is a **single** `vigilia` invocation; this matters for module
  preparation/reparation state and images created by earlier modules. Some
  modules intentionally have no individual command assertions, so the serial
  suite's positive-test-count gate is not valid for running them alone.

At revision `43bb8aa85c76e45c6c035008eab2fafcbfa6f6c3`, the **full
profile passed all 36 modules and 256 enabled assertions on both providers**.
The previous Docker subset (22 modules, 149 enabled assertions) passed at
`6d00bee29480` but is no longer an automatic redundant CI job.
For exact module prerequisites and disabled tests, see
[test-specification-prerequisites.md](test-specification-prerequisites.md).

## Environment provisioning and security boundaries

**GitHub:** hosted `ubuntu-24.04` jobs run on disposable VMs with a local Docker
daemon. Docker jobs verify daemon availability, then install project
prerequisites. Tests may build images, create networks, use SSH/tmux inside
containers and perform package installations.

**GitLab:** Ubuntu 24.04 runs as a job container on the hosted
`saas-linux-small-amd64` runner. The Docker pilot/full jobs use a privileged
`docker:28.5.2-dind` service, accessed via TLS at `tcp://docker:2376`.
The job bootstraps as root, creates a passwordless-sudo `vigilia-ci` account
and runs `vigilia` as that user. TLS client credentials are copied to a
private user-owned directory; they must never be collected as CI artifacts.
The job checks for Docker CLI 29.1.3; Engine 28 is retained for compatibility
with the older Docker CLI installed in the Docker-role test image.
`VIGILIA_DOCKER_NETWORK_SUBNET=auto` avoids the historical fixed-subnet
collision. Shared socket permissions are probed on the **daemon side**, not
by `stat` on the GitLab job container's filesystem.

Both Docker control and passwordless `sudo` provide high-impact privileges.
Only trusted integration-branch code should use them; never expose this runner
configuration or secrets to untrusted pull/merge-request code. Docker-related
specifications can reuse fixed network/container names and require disposable,
nonshared daemons. Paths such as `/home/neurospaces/projects/...` may be
created deliberately **inside test images** and need not exist on the CI host.

REST retrieval credentials (`GITHUB_TOKEN`/`GH_TOKEN` with Actions-read access
and `GITLAB_TOKEN` with read-API access) are separate from runner credentials.
Do not commit tokens, copy DinD private keys into archives, or share unredacted
test output containing secrets. Refer to
[ci/ARTIFACTS.md](../ci/ARTIFACTS.md) for authentication details.

## Quality gates, failure propagation, and evidence

Each `ci/test.sh` invocation creates a fresh `ci-results/run.XXXXXX/`
(or a directory under `CI_RESULTS_DIR`) and records:

- `environment.txt` with the Git revision, operating system, profile,
  selector, and build mode;
- `<stage>.log` and `<stage>.exit-code.txt` for the offline CPAN, artifact,
  Docker-network, Docker-suite and report-counter checks, optional
  Autotools/build/install, `make-check`, and `validate-report`;
- `report/report.yml`, assertion evidence, Automake's `run_harness.sh.log`,
  `.trs`, and `test-suite.log` when produced;
- `exit-code.txt` on normally terminated runs.

The quality gate requires successful `make check` **and**
`ci/validate-report.pl` acceptance of `global.status: Finished`, a positive
executed command-test count and `global.error_count: 0`. When present, the
validator also checks that `executed_totals.command_test` agrees with the
processed/current report counter. A failed `make check` is not overwritten by
a later report-validation error. Unsuccessful preparation can prevent a native
report from being written; its stage logs and exit codes remain evidence.

For the serial Docker subset, inspect
`ci-results/docker-suite/run.*/summary.tsv` and each module's `console.log`,
`docker-*.log` and nested `run.*/report/report.yml`. The full profile creates
**one** run/report rather than a per-module directory. Provider-level Docker
preflight, daemon diagnostics, and dependency logs are also retained. Upload
is `always` / `if: always()` but cannot recover artifacts after hard runner
termination or an upload failure.

The native report distinguishes discovered, selected, processed and executed
test counts. **Discovered does not mean executed**, and counters alone do not
indicate success. See [vigilia-report-counters.md](vigilia-report-counters.md).

## Artifact retrieval and revision provenance

GitHub and GitLab independently upload ZIP artifacts. The downloader reads
provider REST metadata rather than constructing download URLs from guessed
IDs. The provider/job/profile mapping lives in
[`ci_artifacts.yml`](../configured-workflows/automation-configuration-data/ci_artifacts.yml).
The default download profile is now **`full`**, at the newest common
successful revision. Focused `docker` and historical `smoke`/`regression`
artifacts require explicit `--profile` selection.

From a checkout at the revision pushed to both providers:

```sh
# Wait for that exact Git HEAD, including failed pipelines, then download.
automation-workflow ci artifacts_download full -- --mode latest-wait --wait-timeout 7200

# For the independently executed Docker subset:
automation-workflow ci artifacts_download docker -- --mode latest-wait

automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

`latest-wait` waits synchronously until **both pipelines/workflow runs** reach
terminal status; its default is a 15-second sleep after API requests, with a
30-minute timeout unless overridden. It does **not** require success. A failed
run may still have downloadable diagnostics. A temporary network error aborts
the command; a later retry can succeed without changing the source. If a
download fails, `verify`/`report` may still refer to an **earlier** successful
selection via `ci-artifacts/latest.json`.

Options passed through `automation-workflow` require `--` after the operation
and any positional selector; the standalone Python tool does not use that
separator. `artifacts_inventory` shows available IDs; `--provider`,
`--run-id`, `--id`, `--name` and `--all` provide more precise selections.
GitHub `--run-id` means a workflow run and GitLab `--run-id` means a pipeline;
GitLab `--id` selects a job.

Downloads are grouped by **full Git SHA** in `ci-artifacts/<SHA>/`, with
provider/profile ZIPs, manifests, checksums, and a combined ZIP. Different
selections for the same commit get distinct manifest and bundle names.
`verify` checks ZIP readability, checksums, and embedded revisions from every
available `environment.txt`. If an early failure produced no such file,
revision matching relies on authenticated provider metadata and is recorded
as weaker evidence. It does **not** validate assertions; that is the job of
`vigilia` and the CI quality gate.

See [ci/ARTIFACTS.md](../ci/ARTIFACTS.md) for configuration, token handling,
mode semantics, timeouts, CLI examples, and manifest details.

## Operations and extension procedure

For a **trusted local** run, after provisioning dependencies and ensuring the
installed binaries match the checkout:

```sh
VIGILIA_TEST_PROFILE=smoke ci/test.sh --test-only
VIGILIA_TEST_PROFILE=regression ci/test.sh --test-only

# Focused Docker subset (dedicated Docker daemon required):
ci/docker-suite.sh --test-only --module 20_vigilia/30_docker.t

# Complete unfiltered knowledge base (isolated, disposable environment only):
VIGILIA_TEST_PROFILE=full VIGILIA_ALLOW_FULL=1 ci/test.sh --test-only
```

Omit `--test-only` to perform the build/install first. The full run may alter
host/container state. Do not run it against a shared laptop Docker daemon.
For inspection without execution, use `bin/vigilia --show-modules` or other
nonexecuting selection modes.

When adding a test or updating infrastructure:

1. Keep the **specification** as the only authoritative assertion definition;
   documentation/tutorial material must derive from that same committed
   source and revision.
2. For focused investigation, pass a selected module path to the manual
   Docker job. Do **not** edit `full` selection rules: it discovers new modules
   automatically.
3. Declare and provision needed Dockerfiles, SSH/tmux facilities, permissions,
   time freezing, network access, images and other prerequisites. Preserve
   existing assertions unless evidence justifies a change.
4. Run local/offline CI checks, push the same Git revision to both providers,
   and obtain job artifacts even if a job fails.
5. Diagnose failures using the native report and infrastructure logs; separate
   environment failures, stale expectations and implementation defects.
   Avoid disabling tests simply to obtain green pipelines.
6. Confirm both providers independently before claiming cross-platform
   verification. The full profile is authoritative only **after** its hosted
   runs actually pass.

## Documentation map and maintenance

- [ci/README.md](../ci/README.md): shared CI entry-point usage and tag mapping.
- [ci/ARTIFACTS.md](../ci/ARTIFACTS.md): downloader API and `workflow` CLI.
- [ci-docker-pilot.md](ci-docker-pilot.md): Docker module suite, runner
  differences and module-specific evidence.
- [test-specification-prerequisites.md](test-specification-prerequisites.md):
  complete specification inventory, dependencies and failure taxonomy.
- [ci-test-profile-inventory.md](ci-test-profile-inventory.md): original
  classification rationale (historical; not an up-to-date suite inventory).
- [vigilia-report-counters.md](vigilia-report-counters.md): precise report
  counter semantics.
- [workflow-vigilia-ci-implementation-plan.md](workflow-vigilia-ci-implementation-plan.md):
  original implementation roadmap; historical planning reference, not current
  pipeline topology.

**Maintenance rule:** treat workflow YAML and scripts as executable truth.
Update this architecture document when trigger rules, test selection, runner
capabilities, gates, artifact naming/provenance, or security boundaries change.
Record new verified revision(s) in the operational documents only after
checking native reports from *both* providers.
