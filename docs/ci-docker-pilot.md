# Hosted Docker-harness CI pilots

The two pilot jobs deliberately select **only** the existing Perl module
`20_vigilia/30_docker.t` using the same `VIGILIA_REGEX_SELECTOR` interface
and `ci/test.sh` used by the other hosted jobs. They are not the `full` profile.
Both pilots run only on `ci/regression-integration`, not untrusted merge
requests. The normal `smoke` and `regression` jobs remain unchanged.

## GitHub Actions

The `docker-pilot` job runs on an ephemeral `ubuntu-24.04` VM. Docker is
preinstalled. The pilot tests Docker client/daemon access before building and
installing the project, runs `ci/test.sh`, and always uploads the
`vigilia-docker-pilot-<run>-<attempt>` artifact. Look in `ci-results/run.*/`
for build, `make check`, and Vigilia logs; `docker-*.log` files describe the
state of the daemon/container when the job ended.

## GitLab CI/CD

The `vigilia-docker-pilot` job runs on a GitLab.com **privileged, ephemeral**
`saas-linux-small-amd64` runner. It uses `docker:24.0.5-dind` with TLS on
`tcp://docker:2376` and a root-owned Ubuntu 24.04 job container. The job
installs the Docker CLI and creates an unprivileged account for the test
harness. The client TLS credentials are copied to that account's private home
directory, **outside the collected artifacts**. The DinD TLS service must
supply `/certs/client/{ca,cert,key}.pem` on the runner; missing files or
unreachable daemons are reported as explicit bootstrap failures. Artifacts
are named `vigilia-docker-pilot-<job>-<sha>` and retained on failure.

The GitLab DinD daemon has a different filesystem and network namespace from
the job container. Basic `docker build`, `docker run` and `docker exec` calls
can work, but tests using host bind mounts, Docker socket sharing, or direct
container IP access may need changes. Do not expose the DinD TLS key to tested
containers or untrusted code. This pilot does not modify Vigilia harness
semantics or the existing Dockerfiles; any problems in those specifications
should be diagnosed using the uploaded job logs.

## Validation and evidence

After applying both patches, push `ci/regression-integration` to both remotes.
If either pilot fails, download its **Docker pilot job artifact** even if the
other profiles pass, and inspect the per-stage logs. The REST artifact
downloader supports the `docker` profile, including artifacts from failed
pipelines, when invoked with `--mode latest` or a specific run/pipeline ID. The default selection still targets smoke and
regression results from successful pipelines.

The pilot jobs intentionally fail when the Docker test fails. Do not infer
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

Download both Docker pilot artifacts for the latest common revision:

```sh
automation-workflow ci artifacts_download docker -- --mode latest
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

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
