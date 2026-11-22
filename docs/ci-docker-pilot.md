# Hosted Docker module suite

Both CI providers execute **the same ordered list of Docker-backed Vigilia
modules**, defined in [`ci/docker-suite.modules`](../ci/docker-suite.modules).
All five previously configured modules have passed on both GitHub Actions and
GitLab CI/CD:

- `20_vigilia/30_docker.t` (3 command tests);
- `20_vigilia/12_error_checking/summary.yml` (5 command tests);
- `40_workflow-automator/15_error-pages/summary.yml` (5 enabled command
  tests; one additional assertion is disabled);
- `40_workflow-automator/29_config-loader-errors/summary.yml` (2 tests);
- `40_workflow-automator/31_specific-features-export-variables/summary.yml`
  (3 tests).

The next three candidates extend Workflow feature coverage using the same
`Dockerfile.workflow-feature-testing` image:

- `40_workflow-automator/28_command_array_concatenation/summary.yml`
  (2 enabled command tests; the tmux-concatenation assertion remains disabled):
  checks per-role command-array scheduling;
- `40_workflow-automator/36_specific-features-timestamps/summary.yml`
  (4 tests): checks generated command timestamp files;
- `40_workflow-automator/37_specific-features-background/summary.yml`
  (2 tests): checks background-command scheduling and suppressed output.

These eight modules specify **26 enabled command tests** in total: 18 verified
on both providers, plus 8 awaiting hosted validation. Two assertions are
explicitly disabled. The existing five modules and their specifications are
unchanged. All eight modules execute in independent Docker containers.

`ci/docker-suite.sh` executes modules **serially** and without a tag filter,
using the existing `ci/test.sh` quality gate for every module. The first
invocation builds and installs the checkout; later invocations use
`ci/test.sh --test-only`. Each module is selected using an exact pathname
suffix, so similarly named modules cannot accidentally be executed.
If a module fails, the suite records the failure, continues with the next
module and eventually returns a nonzero exit status. This is intentional:
CI artifacts must show independent results for all attempted modules.

Change the committed list to expand coverage, one pathname per line relative
to `vigilia/specifications/`. Blank lines and comments are ignored; entries
must name actual `.t`, `.module.yml` or `summary.yml` files. For a local
experiment, set `VIGILIA_DOCKER_MODULES_FILE` to a different list. Do not run
these specifications on a shared Docker daemon: they reuse names such as
`vigilia_test_container` and can execute privileged operations in containers.

The suite is **not** the unfiltered `full` profile. Both jobs remain restricted
to the trusted `ci/regression-integration` branch, not untrusted merge requests.
The standard `smoke` and `regression` jobs are unchanged.

## Evidence layout and local execution

Each invocation creates a new directory beneath `ci-results/docker-suite/`:

```text
ci-results/docker-suite/run.XXXXXX/
  docker-preflight.log
  summary.tsv
  01-20_vigilia_30_docker.t/
    module.txt
    selector.txt
    console.log
    docker-*.log
    run.XXXXXX/report/report.yml
    run.XXXXXX/make-check.log
    ...
  02-20_vigilia_12_error_checking_summary.yml/
    ...
  03-40_workflow-automator_15_error-pages_summary.yml/
    ...
  04-40_workflow-automator_29_config-loader-errors_summary.yml/
    ...
  05-40_workflow-automator_31_specific-features-export-variables_summary.yml/
    ...
  06-40_workflow-automator_28_command_array_concatenation_summary.yml/
    ...
  07-40_workflow-automator_36_specific-features-timestamps_summary.yml/
    ...
  08-40_workflow-automator_37_specific-features-background_summary.yml/
    ...
```

The shared CI gate checks positive executed-test counts, error-free reports
and successful `make check` separately for **each** selected module. The
`summary.tsv` file records each module's success or failure and evidence
folder. Module diagnostics are captured before the next module can replace
its container. All files appear in the existing `docker` job artifact.
The old `vigilia-docker-pilot` job/artifact names remain unchanged so
`automation-workflow ci artifacts_download docker` continues working.

After building and installing the checkout, a local rerun can skip the
installation phase with:

```sh
ci/docker-suite.sh --test-only
```

Without `--test-only`, the suite builds once. Running it locally requires a
working Docker daemon and isolated environment. The harness's historical
fixed subnet remains the default locally; the GitLab job sets
`VIGILIA_DOCKER_NETWORK_SUBNET=auto`.

## GitHub Actions

The `docker-pilot` job runs on an ephemeral `ubuntu-24.04` VM. Docker is
preinstalled. It checks Docker client/daemon access, installs project
dependencies, then invokes `ci/docker-suite.sh` and always uploads the
`vigilia-docker-pilot-<run>-<attempt>` artifact. Separate per-module
`run.*/` directories contain native reports, `make check` diagnostics and
Docker logs.

## GitLab CI/CD

The `vigilia-docker-pilot` job runs on a GitLab.com **privileged, ephemeral**
`saas-linux-small-amd64` runner. It uses `docker:29.1.3-dind` with TLS on
`tcp://docker:2376` and a root-owned Ubuntu 24.04 job container. The job
installs Ubuntu's `docker.io` CLI and checks that it is version 29.1.3,
matching the pinned daemon release. If Ubuntu upgrades the CLI, the pilot
fails with an explicit version-mismatch diagnostic instead of silently using
an incompatible Docker API. Update the client and daemon together in that
case.

The job creates an unprivileged account for the test harness. The client TLS
credentials are copied to that account's private home directory, **outside
the collected artifacts**. The DinD TLS service must
supply `/certs/client/{ca,cert,key}.pem` on the runner; missing files or
unreachable daemons are reported as explicit bootstrap failures. Artifacts
are named `vigilia-docker-pilot-<job>-<sha>` and retained on failure.

The Docker harness historically requests `172.18.0.0/16` for its
`harness_network`, which can overlap the DinD daemon's existing address pools.
The GitLab pilot sets `VIGILIA_DOCKER_NETWORK_SUBNET=auto` so the Docker
Engine selects an available subnet; the default remains `172.18.0.0/16`
locally for compatibility with specifications that assume fixed IP addresses.
The harness checks network creation and container startup, reporting these as
preparation errors rather than letting missing containers produce misleading
assertion failures. Note that other specifications with hard-coded container
addresses are **not** made portable to DinD by this pilot override.

The GitLab DinD daemon has a different filesystem and network namespace from
the job container. Basic `docker build`, `docker run` and `docker exec` calls
can work, but tests using host bind mounts, Docker socket sharing, or direct
container IP access may need changes. Do not expose the DinD TLS key to tested
containers or untrusted code. The module suite does not modify Vigilia
harness semantics or existing Dockerfiles; diagnose new module failures
using the per-module logs.

## Validation and evidence

After applying the patch, push `ci/regression-integration` to both remotes.
If a module fails, download the **Docker job artifact** even if the other
profiles pass, and inspect the module-specific logs and `summary.tsv`. The
REST artifact downloader supports the `docker` profile, including artifacts
from failed pipelines, when invoked with `--mode latest` or a specific
run/pipeline ID. The default selection still targets smoke and regression
results from successful pipelines.

The Docker jobs intentionally fail when any selected module fails. Do not infer
successful Docker coverage from a green `smoke` or `regression` job. The
subsequent full-profile work should use the same unfiltered selection as
running `bin/vigilia` locally, but additional remote/privileged dependencies
will have to be provisioned and validated first.

References:
- GitHub hosted runners: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- GitLab Docker-in-Docker: https://docs.gitlab.com/ci/docker/docker_in_docker/
- GitLab hosted runner capabilities: https://docs.gitlab.com/ci/runners/hosted_runners/linux/

## Retrieve pilot diagnostics through workflow

With the flexible REST artifact downloader installed, query the latest
completed runs **including failures** and inspect the Docker jobs. Pass
`--` after the workflow operation (and any positional selector) to forward
options to the downloader; without the separator, `workflow` tries to parse
`--provider`, `--mode`, and similar options itself:

```sh
automation-workflow ci artifacts_inventory -- --provider github --mode latest
automation-workflow ci artifacts_inventory -- --provider gitlab --mode latest
```

Download both Docker suite artifacts for the latest **completed** common
revision (which can be older than the one you just pushed):

```sh
automation-workflow ci artifacts_download docker -- --mode latest
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

Alternatively, after pushing both remotes, **wait for the current local Git
HEAD** to complete on both providers before downloading anything:

```sh
automation-workflow ci artifacts_download docker -- --mode latest-wait
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

`latest-wait` includes failed pipelines, does not silently fall back to older
revisions, and has a 30-minute default timeout. You can append
`--wait-timeout 3600 --poll-interval 20` after the `--` separator. To pin an
explicit revision use `--revision "$(git rev-parse HEAD)"` (40 characters).
The command blocks locally until all selected pipelines are terminal or it
times out; it cannot repair a missing artifact or a failed Docker job.

If only one platform completed the pilot, select its provider, pipeline/run
ID and (if desired) the specific job/artifact ID using `--run-id` and `--id`.
For example:

```sh
automation-workflow ci artifacts_inventory -- --provider github --run-id 45051720283
automation-workflow ci artifacts_inventory -- --provider gitlab --run-id 3100079440
```

These are illustrative IDs from the initial pilot; inspect the current
run/pipeline inventory before selecting an archive. The downloader produces a combined ZIP bundle containing the original provider
archives and a manifest with revision and checksum evidence. These commands do
not require changes to the tests or access to the runner's Docker daemon.
