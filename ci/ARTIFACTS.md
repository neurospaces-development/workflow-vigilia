# CI verification artifact retrieval

`python3 ci/download-artifacts.py` uses the GitHub Actions and GitLab REST APIs
rather than guessing the latest archive name. It requires Python 3 and PyYAML
(`sudo apt install python3-yaml` on Ubuntu/Debian). The configuration is in
`configured-workflows/automation-configuration-data/ci_artifacts.yml`.

Commands:

```sh
python3 ci/download-artifacts.py list
python3 ci/download-artifacts.py download
python3 ci/download-artifacts.py download --mode latest
python3 ci/download-artifacts.py download --mode revision --revision a12a68e575522285dea96bb61a7edff8d315c60d
python3 ci/download-artifacts.py download --provider github --profile smoke
python3 ci/download-artifacts.py verify
python3 ci/download-artifacts.py report
```

`latest-successful` (default) selects the newest *common* completed successful
revision available on both providers. `latest` considers failed executions too,
provided their artifacts exist. In either mode the revision must match across
providers. `--revision` identifies a particular revision; use a full SHA if
possible. `list` prints recent completed runs without downloading anything.
The API listing is limited to the three most recent pages of 100 runs/pipelines
per provider; use `--revision` for older data if it falls within that window.

Successful downloads appear in `ci-artifacts/<full-SHA>/<provider>/<profile>/`,
with an atomic `manifest.json`, `latest.json` pointer, checksums and a combined
`workflow-vigilia-ci-<SHA>.zip`. Both ZIP validity and the embedded revision
in the primary `environment.txt` are checked. Already downloaded artifact IDs
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
permissions. No automatic retries are performed for missing or expired
artifacts; investigate the relevant CI run instead.

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
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

The wrapper schedules the standalone Python command using
`execute_command_array`. It does not issue HTTP requests during configuration
loading, and retains dry-run semantics. The current working directory must
be inside the source checkout for `git rev-parse --show-toplevel` to resolve.
