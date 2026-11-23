# CI verification artifact retrieval

For the full CI/CD component diagram, profiles, provider jobs and evidence
flow, see [CI/CD architecture and operation](../docs/ci-cd-architecture.md).

`python3 ci/download-artifacts.py` uses the GitHub Actions and GitLab REST APIs
rather than guessing the latest archive name. It requires Python 3 and PyYAML
(`sudo apt install python3-yaml` on Ubuntu/Debian). The configuration is in
`configured-workflows/automation-configuration-data/ci_artifacts.yml`.

Commands:

```sh
python3 ci/download-artifacts.py list
python3 ci/download-artifacts.py download
python3 ci/download-artifacts.py download --mode latest
python3 ci/download-artifacts.py download --mode latest-wait --profile docker
python3 ci/download-artifacts.py download --mode latest-wait --profile full --wait-timeout 7200
python3 ci/download-artifacts.py download --mode revision --revision a12a68e575522285dea96bb61a7edff8d315c60d
python3 ci/download-artifacts.py download --provider github --profile smoke
python3 ci/download-artifacts.py verify
python3 ci/download-artifacts.py report
```

`latest-successful` (default) selects the newest *common* completed successful
revision available on both providers. With no profile argument, downloads now
select **`full`**, the authoritative automatic job; older smoke, regression,
and focused Docker artifacts remain available using `--profile`. `latest` considers failed executions too,
provided their artifacts exist. Both select an already completed revision;
they may return an **older** revision if the latest pipelines are still running.

`latest-wait` instead **pins the target revision** to the current source
checkout's `git HEAD` (or to an explicit full 40-character `--revision`), then
polls GitHub and GitLab until the pipelines for that exact revision finish.
It handles pipelines that have not yet started, does not fall back to older
successful runs, and accepts terminal failures so their diagnostic artifacts
can be downloaded. It checks the whole pipeline/workflow, not just the Docker
job. **Push the target revision to the selected CI providers first.** When
using `--run-id`, select exactly one provider; that run's SHA is the target.
Waiting is synchronous and can be interrupted with Ctrl-C; it does not create
a background task. The default timeout is 1800 seconds (30 minutes), with a
15-second polling interval. Override with `--wait-timeout SECONDS` and
`--poll-interval SECONDS` (both only for `latest-wait`). A timeout returns an
error **without downloading archives**. If a completed run has no matching
artifact, selection still fails normally with a diagnostic.

`--revision` in other modes identifies a particular revision; use a full SHA
if possible. `list` prints recent completed runs without downloading anything.
The API listing is limited to the three most recent pages of 100 runs/pipelines
per provider; use `--revision` for older data if it falls within that window.

Successful downloads appear in `ci-artifacts/<full-SHA>/<provider>/<profile>/`,
with an atomic `manifest.json`, `latest.json` pointer, checksums and a combined
`workflow-vigilia-ci-<SHA>.zip`. ZIP validity and the embedded revision in every module `environment.txt`
are checked (a serial Docker suite can produce several). Early failed jobs may contain no `environment.txt`; in that case the
revision is checked only against provider API metadata and the manifest records
`embedded_revision_verified: false`. Already downloaded artifact IDs
are reused. The archives are *not extracted* or executed. `verify` checks
previous downloads without contacting either provider.

## REST authentication

Use a GitHub fine-grained personal access token scoped to the repository with
**Actions: read**; set `GITHUB_TOKEN` (or `GH_TOKEN`). GitLab uses a token with
**read_api** scope; set `GITLAB_TOKEN`. SSH keys do **not** authenticate the
REST APIs. Tokens are read only from the environment, never passed as CLI
arguments or included in the manifest. Tokens must not be committed to Git.

An example using a session-local environment and interactive prompts:

```sh
read -rsp 'GitHub token: ' GITHUB_TOKEN; echo; export GITHUB_TOKEN
read -rsp 'GitLab token: ' GITLAB_TOKEN; echo; export GITLAB_TOKEN
python3 ci/download-artifacts.py list
python3 ci/download-artifacts.py download
unset GITHUB_TOKEN GITLAB_TOKEN
```

The GitHub API artifact download is a short-lived HTTPS redirect; the
implementation does **not** forward credentials to redirected storage hosts.
All network requests time out. HTTP API endpoints are accepted only for
loopback regression tests.

When both providers are requested, the downloader refuses mismatched revisions
and missing profiles. Artifact availability depends on retention and token
permissions. Read-only REST metadata requests are retried for temporary DNS/connection
failures, HTTP 429/5xx responses, and invalid JSON (for example an unexpected
HTML gateway response). There are at most four attempts with 1-, 2- and
4-second backoffs. Warnings identify the provider and request path but never
print an API response body or credentials. Persistent errors still abort the
operation; failed downloads leave the previous `latest.json` selection intact.
A later invocation can continue without corrective action once connectivity
returns. The `latest-wait` mode polls pipeline status until completion, but
does not retry missing or expired artifact archives after pipeline completion;
investigate the run instead.

The output directory is ignored by Git and Docker. Do not treat artifacts from
untrusted builds as executable programs. `report` lists manifest metadata;
`verify` checks archived files and checksums, not software correctness.

## `workflow` integration

The target is defined under `configured-workflows`. The following are the
intended operations (use the invocation prefix of your installed automation
workflow command):

```sh
automation-workflow ci artifacts_list
automation-workflow ci artifacts_download latest-successful
automation-workflow ci artifacts_download a12a68e57552
# Wait for this checkout's revision to finish on both CI providers:
automation-workflow ci artifacts_download docker -- --mode latest-wait
# Same, using the positional alias:
automation-workflow ci artifacts_download latest-wait -- --profile docker
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

The `automation-workflow` command-line parser reserves option-looking arguments
for itself. Separate the workflow target/operation from the downstream command's
options with `--`:

```text
automation-workflow ci <operation> [positional-selector] -- [downloader options]
```

The separator is consumed by `workflow`; it is **not** passed to
`ci/download-artifacts.py`. It is only needed when forwarding options such as
`--provider`, `--mode`, `--run-id`, `--name`, or `--id`. Bare operations and
positional selectors (for example `artifacts_download docker`) work without it.
When invoking the standalone `python3 ci/download-artifacts.py`, do **not** add
this separator.

The wrapper schedules the standalone Python command using
`execute_command_array`. It does not issue HTTP requests during configuration
loading, and retains dry-run semantics. The current working directory must
be inside the source checkout for `git rev-parse --show-toplevel` to resolve.

## Offline regression tests

The following tests use a loopback HTTP server, mock responses, and disposable
ZIP fixtures. They never contact GitHub/GitLab and do not require API tokens:

```sh
python3 ci/tests/test-download-artifacts.py
python3 ci/tests/test-workflow-artifacts.py
```

The shared `ci/test.sh` executes them before the build and the `vigilia`
regression suite, preserving separate stage logs.

## Flexible job and Docker-pilot selection

The default download profile is `full`, because routine trusted-branch
pipelines no longer repeat the smoke, regression or focused Docker subset.
Use `--profile smoke`, `--profile regression`, or `--profile docker` for
historical or explicitly requested jobs; the provider's latest run may not
contain those artifacts. For failed full pipelines use `--profile full
--mode latest-wait` or an explicit pipeline/run ID to retain diagnostics.

The new `inventory` operation queries the jobs/artifacts available in a
specific completed run. Its output contains the provider-specific IDs,
artifact/job names, status, availability and sizes. It does not download files.

```sh
# Inspect most recent completed runs, including failed Docker pilots.
automation-workflow ci artifacts_inventory -- --provider github --mode latest
automation-workflow ci artifacts_inventory -- --provider gitlab --mode latest

# Download both Docker pilot artifacts at the latest completed common revision,
# whether the jobs passed or failed. This may be an older revision.
automation-workflow ci artifacts_download docker -- --mode latest

# Wait for the current HEAD on both providers (including failed pipelines),
# then retrieve the Docker evidence; never silently choose an older revision.
automation-workflow ci artifacts_download docker -- --mode latest-wait

# Set the wait timeout (seconds) and poll interval (seconds).
automation-workflow ci artifacts_download docker -- --mode latest-wait --wait-timeout 3600 --poll-interval 20

# Explicit revision (full SHA): usable even from another checkout's HEAD.
automation-workflow ci artifacts_download docker -- --mode latest-wait --revision "$(git rev-parse HEAD)"

# Select one provider and one profile.
automation-workflow ci artifacts_download docker -- --provider github --mode latest

# Select a specific GitHub run and artifact ID (from inventory).
automation-workflow ci artifacts_inventory -- --provider github --run-id 123456789
automation-workflow ci artifacts_download -- --provider github --run-id 123456789 --id 987654321

# Select a specific GitLab pipeline and job ID (from inventory).
automation-workflow ci artifacts_inventory -- --provider gitlab --run-id 123456789
automation-workflow ci artifacts_download -- --provider gitlab --run-id 123456789 --id 987654321

# Name patterns are applied to GitHub artifact names / GitLab job names.
automation-workflow ci artifacts_download -- --mode latest --name '*docker-pilot*'

# All available ZIP artifacts in the selected completed run(s).
automation-workflow ci artifacts_download all -- --mode latest

automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

The standalone `python3 ci/download-artifacts.py` supports identical options.
Use only one of `--profile` (repeatable), `--name` (repeatable), `--id`
(repeatable), or `--all`. `--id` requires one `--provider` and `--run-id`;
`--run-id` refers to a **GitHub Actions workflow run** or a **GitLab
pipeline**, not to a GitLab job. For an individual GitLab job use `--id`.
A named profile may be `smoke`, `regression`, `docker` or `full`. The names for these
profiles are customizable under `github.artifact_names` and `gitlab.job_names`
in the YAML configuration. `--all` has a safety limit of 50 archives per run.

Custom selections of the same source revision use separate `manifest-*.json`
and `workflow-vigilia-ci-*-*.zip` filenames, so retrieving one failed Docker
job does not overwrite an existing smoke/regression evidence bundle. The
`latest.json` pointer follows the most recently completed download; `verify`
and `report` operate on that selection.

When a failed job has no `environment.txt`, the archive can still be retained
and verified for ZIP integrity and checksum, but its revision is only
corroborated by the CI provider's authenticated API; the manifest records
this distinction. `inventory` may report `available: false` for jobs that
produced no artifacts. In that case inspect the job log in the provider UI.

Find the most recently produced combined archive for sharing:

```sh
python3 - <<'PY'
import json
from pathlib import Path
root = Path('ci-artifacts')
pointer = json.loads((root / 'latest.json').read_text())
print(root / pointer['bundle'])
PY
```

## Unfiltered full knowledge-base profile

The separate `full` CI jobs run **one unfiltered `vigilia` invocation** with
`VIGILIA_TEST_PROFILE=full` and `VIGILIA_ALLOW_FULL=1`, using the same module
selection as plain `bin/vigilia` on a suitably provisioned machine. Unlike
`ci/docker-suite.modules`, the full profile is **not a maintained test list**:
new specifications are discovered automatically. The full invocation keeps
ordering/side effects between the `20_preparation` and
`25_preparation_checker` modules and image creation dependencies intact.

The 22-module serial Docker suite remains a separate, previously validated
regression. Full CI results may fail on the first attempts if older fixtures
need maintenance; those are real failures and do not cause assertions to be
silently skipped.

To retrieve full-suite artifacts (including failed jobs):

```sh
automation-workflow ci artifacts_download full -- --mode latest-wait --wait-timeout 7200
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

The default download profiles **remain** smoke and regression. A full run can
take longer than the downloader's default 30-minute polling timeout; set
`--wait-timeout` accordingly. Both providers upload full-suite evidence on
failure. Only the trusted integration branch runs the privileged full jobs.
