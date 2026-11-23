# Focused Docker module testing (opt-in)

The **full** hosted CI job now executes the entire knowledge base on every
trusted branch push. The previous serial Docker suite was used to develop and
validate the infrastructure; it is preserved for **manually selected modules**,
not executed by default. See [CI/CD architecture](ci-cd-architecture.md).

[`ci/docker-suite.modules`](../ci/docker-suite.modules) is now empty apart
from comments. The following list records the earlier **22-module baseline**,
not the default CI selection. The first eighteen modules passed at
revision `a363438a99c451a6089888d594284260b856dace`:

- `20_vigilia/30_docker.t` (3 assertions);
- `20_vigilia/12_error_checking/summary.yml` (5);
- `40_workflow-automator/15_error-pages/summary.yml` (5 enabled, 1 disabled);
- `40_workflow-automator/29_config-loader-errors/summary.yml` (2);
- `40_workflow-automator/31_specific-features-export-variables/summary.yml` (3);
- `40_workflow-automator/28_command_array_concatenation/summary.yml`
  (2 enabled, 1 disabled);
- `40_workflow-automator/36_specific-features-timestamps/summary.yml` (4);
- `40_workflow-automator/37_specific-features-background/summary.yml` (2);
- `40_workflow-automator/32_specific-features-export-sh/summary.yml` (15);
- `40_workflow-automator/33_specific-features-export-times/summary.yml` (5);
- `40_workflow-automator/27_schedule/summary.yml` (8);
- `40_workflow-automator/34_specific-features-annotations.t` (2);
- `40_workflow-automator/38_rename_project/summary.yml` (5);
- `40_workflow-automator/39_specific_features_ai/summary.yml` (16);
- `40_workflow-automator/42_use-dot-local-bin/summary.yml` (4);
- `40_workflow-automator/46_builtin/summary.yml` (16);
- `40_workflow-automator/80_install-testing/10_debian/summary.yml` (2);
- `40_workflow-automator/80_install-testing/20_ubuntu/summary.yml` (2).

The timestamp assertions use a reproducible reference time:
`Dockerfile.workflow-feature-testing` installs `libfaketime` and sets
`LD_PRELOAD=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1` and
`FAKETIME="@2025-10-11 11:38:32"`. The AI-token tests exercise local storage
using synthetic tokens; they do not call the external OpenAI API.

The four **advanced harness modules** have now been verified on both
CI/CD platforms. A cold Docker-role image build originally timed out on
GitHub; increasing the assertion timeout to 900 seconds preserved the
expected output and allowed it to pass:

- `40_workflow-automator/30_specific-features-cd.t` (9 enabled, 1 disabled):
  includes tmux and SSH from the test container to itself;
- `40_workflow-automator/40_remote_script_execution/summary.yml` (4):
  uses `Docker::Remote`, which distinguishes host-side preparer commands
  from commands sent to the container; its Dockerfile provisions the source
  checkout under `/home/neurospaces/projects/...` **inside the image**;
- `40_workflow-automator/44_roles/10_docker/summary.yml` (5):
  asks for shared Docker-daemon access using `/var/run/docker.sock`, which
  is not automatically available with GitLab's TLS Docker-in-Docker;
- `40_workflow-automator/50_bash_completion/summary.yml` (30):
  also uses `Docker::Remote`; its container-internal source checkout and
  SSH execution have now passed on both providers.

The historical subset comprised **22 modules and 149 enabled command tests**.
At revision `6d00bee29480b91157a1db6a858e818bec7b4613`, all passed on
both platforms. The subsequent **unfiltered full job** passed **36 modules
and 256 enabled assertions** on both platforms at revision `43bb8aa85c76`.
Thus, repeating the old subset on every push is unnecessary.

The `/home/neurospaces/projects/...` checkout is intentionally populated
**inside** the Docker image; it is not supposed to be present on the CI job
host. The earlier socket, Docker client and cold-build timeout issues have
been resolved in the verified 22-module suite. The internal source path was
not the cause of those failures.

See [Test specification execution prerequisites](test-specification-prerequisites.md)
for the full module inventory, infrastructure requirements, and modules not
suitable for this low-risk expansion.

`ci/docker-suite.sh` executes modules **serially** and without a tag filter,
using the existing `ci/test.sh` quality gate for every module. The first
invocation builds and installs the checkout; later invocations use
`ci/test.sh --test-only`. Each module is selected using an exact pathname
suffix, so similarly named modules cannot accidentally be executed.
If a module fails, the suite records the failure, continues with the next
module and eventually returns a nonzero exit status. This is intentional:
CI artifacts must show independent results for all attempted modules.

For focused development, select paths relative to `vigilia/specifications/`:

```sh
# Select one or more modules directly; runs in an isolated Docker environment.
ci/docker-suite.sh --module 20_vigilia/30_docker.t \
  --module 40_workflow-automator/27_schedule/summary.yml

# For manual GitHub/GitLab runs, specify comma-separated paths:
VIGILIA_DOCKER_MODULES='20_vigilia/30_docker.t,40_workflow-automator/27_schedule/summary.yml' \
  ci/docker-suite.sh

# Alternatively, maintain an untracked newline-delimited list:
VIGILIA_DOCKER_MODULES_FILE=/tmp/selected-modules.txt ci/docker-suite.sh
```

Without any selected modules, the focused runner fails before running Docker;
it does not claim an empty run passed. Paths are checked for existence and
invalid characters. Do not run these tests on a shared Docker daemon: they
reuse names such as `vigilia_test_container`.

**GitHub:** Choose **Run workflow** and enter comma-separated paths in
`docker_modules`; only the focused Docker job runs. **GitLab:** Start a
pipeline manually using the variable `VIGILIA_DOCKER_MODULES` and run the
optional `vigilia-docker-pilot` job. These manual invocations can target a
trusted development branch. On ordinary pushes to trusted branches, only
the full job runs. GitHub additionally runs one non-Docker regression job for
pull requests.

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
  09-40_workflow-automator_32_specific-features-export-sh_summary.yml/
    ...
  10-40_workflow-automator_33_specific-features-export-times_summary.yml/
    ...
  11-40_workflow-automator_27_schedule_summary.yml/
    ...
  12-40_workflow-automator_34_specific-features-annotations.t/
    ...
  13-40_workflow-automator_38_rename_project_summary.yml/
    ...
  14-40_workflow-automator_39_specific_features_ai_summary.yml/
    ...
  15-40_workflow-automator_42_use-dot-local-bin_summary.yml/
    ...
  16-40_workflow-automator_46_builtin_summary.yml/
    ...
  17-40_workflow-automator_80_install-testing_10_debian_summary.yml/
    ...
  18-40_workflow-automator_80_install-testing_20_ubuntu_summary.yml/
    ...
  19-40_workflow-automator_30_specific-features-cd.t/
    ...
  20-40_workflow-automator_40_remote_script_execution_summary.yml/
    ...
  21-40_workflow-automator_44_roles_10_docker_summary.yml/
    ...
  22-40_workflow-automator_50_bash_completion_summary.yml/
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

The optional `docker-pilot` job runs on an ephemeral `ubuntu-24.04` VM. Docker is
preinstalled. It checks Docker client/daemon access, installs project
dependencies, then invokes `ci/docker-suite.sh` and always uploads the
`vigilia-docker-pilot-<run>-<attempt>` artifact. Separate per-module
`run.*/` directories contain native reports, `make check` diagnostics and
Docker logs.

## GitLab CI/CD

The `vigilia-docker-pilot` job runs on a GitLab.com **privileged, ephemeral**
`saas-linux-small-amd64` runner. It uses `docker:28.5.2-dind` with TLS on
`tcp://docker:2376` and a root-owned Ubuntu 24.04 job container. The job
installs Ubuntu's `docker.io` CLI and checks that it is version 29.1.3.
Docker Engine 28.5.2 supports both this job-container CLI and the **Docker
20.10 CLI inside the Docker-role test image**. Docker Engine 29 rejects the
older nested client (its minimum supported API is 1.44). If Ubuntu upgrades
the job-container CLI, the pilot fails with an explicit diagnostic until the
version compatibility is reassessed.

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
work. Socket-sharing is implemented by inspecting the socket group **on the
Docker daemon**, using a short-lived helper container based on the test image;
it no longer runs `stat /var/run/docker.sock` in the CI job container, where
that socket does not exist. The Docker-role image sets `DOCKER_BUILDKIT=0` to
preserve the exact legacy build output currently asserted by its test
specification. These are harness/environment compatibility accommodations, not
changes to the test assertions. Sharing the daemon socket confers powerful
access and must remain limited to the disposable trusted-branch CI runner.
The DinD TLS client key is not mounted into tested containers.

## Validation and evidence

After starting a manual focused run, download the **Docker job artifact**
if any selected module fails, and inspect the module-specific logs and `summary.tsv`. The
REST artifact downloader supports the `docker` profile, including artifacts
from failed pipelines, when invoked with `--mode latest` or a specific
run/pipeline ID. The default selection now targets full
results from successful pipelines.

Focused Docker jobs intentionally fail when any selected module fails. Do not infer
successful Docker coverage from a green `smoke` or `regression` job. The `full` jobs use the same unfiltered selection as local `bin/vigilia`
and passed at revision `43bb8aa85c76`.

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

## Full knowledge-base CI (all 36 modules)

The separate GitHub `full-tests` and GitLab `vigilia-full` jobs run the
**unfiltered** `VIGILIA_TEST_PROFILE=full` selection through `ci/test.sh`,
inside the existing disposable Docker-capable hosted runner environments.
Both jobs have a 90-minute cap and retain artifacts on failure. In GitLab,
`vigilia-full` inherits the DinD bootstrap, TLS and unprivileged account
setup from `vigilia-docker-pilot`, but invokes `ci/test.sh` directly.

Unlike the serial `ci/docker-suite.modules` job, full does not have a module
allowlist or an individual per-module CI report. It runs all discovered
modules together, retaining dependencies such as preparation/reparation
between modules and the `vigilia-image` created by a preceding module.
This is essential for matching the semantics of local `bin/vigilia`.

The historical 22-module Docker suite remains available as an **opt-in**
diagnostic tool, but its committed selection list is empty and it is not
scheduled on normal pushes. Both hosted full jobs passed all 36 modules and
256 enabled assertions at revision `43bb8aa85c76`.

```sh
automation-workflow ci artifacts_download full -- --mode latest-wait --wait-timeout 7200
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```
