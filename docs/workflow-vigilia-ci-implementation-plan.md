# CI/CD integration for workflow and vigilia

Stepwise implementation and verification plan

Version 0.2  •  18 November 2026  •  Proposed for implementation

## Objective

Run the existing regression tests of both tools on GitHub Actions and GitLab CI/CD, using a common local entry point. Retain native test evidence on success and failure, without migrating test specifications or adding a dependency on an external testing or reporting framework.

## Architecture and ownership

```text
       Local CLI          GitHub Actions          GitLab CI/CD
           |                    |                      |
           +--------------------+----------------------+
                                |
                           ci/test.sh
                +---------------+---------------+
                |                               |
       make check / run_harness.sh      project-workflow command
       (engine regression tests)        (downstream, optional)
                |                               |
                +---------------+---------------+
                                |
                             vigilia
                                |
             Existing test specifications and assertions
                    Local / Docker / SSH / QEMU
                                |
                Exit status + report.yml + logs
```

CI owns triggering, runners and merge policy; workflow owns process knowledge and environment orchestration; vigilia owns product knowledge, test assertions and results. The engine regression suite uses the existing Automake harness directly. Downstream applications may orchestrate vigilia through workflow. Both paths preserve failure status and native evidence; reporting adapters are optional (Phases 7–8).

## Implementation roadmap

| Phase | Deliverable / decision | Priority |
| --- | --- | --- |
| 1 | Inventory, baseline, and runner requirements | P0 |
| 2 | Common scripts and trustworthy exit status | P0 |
| 3 | GitHub Actions pilot | P0 |
| 4 | GitLab CI/CD pilot | P0 |
| 5 | Native evidence and report validation | P0 |
| 6 | Container matrix, merge gates, reuse | P1 |
| 7 | Native Markdown summaries | P2 / optional |
| 8 | JUnit XML interoperability | P3 / optional |

Execution order: 1 → 2 → 3/4 (either order) → 5 → 6. Phases 7–8 are independent optional extensions after the native evidence contract is stable. Do not require merge checks until deliberate failures are detected.

# Phase 1  /  Establish the baseline

Owner: repository maintainer, with runner administrator for infrastructure checks. Output: ci/README.md containing the baseline SHA, runner requirements and results.

## 1.1  Inspect the current checkout

```bash
git switch -c ci/regression-integration
git rev-parse HEAD
git status --short
git ls-files | grep -E "(^vigilia/|^configured-workflows/)"
grep -nE "TESTS|vigilia-html|install-data" Makefile.am
cat run_harness.sh
cat vigilia.config
```

Public master inspection confirms TESTS = run_harness.sh; the harness calls bin/vigilia. The config uses ./vigilia/html. The tester supports linear console output, tags, module discovery and a reporting directory, and writes report.yml on exit. Its HTML formatter is a separate output mode, not proof that tests executed [1–5].

## 1.2  Prepare a disposable Ubuntu 24.04 runner

☐  Use a clean VM or hosted runner; run as a normal user with passwordless sudo only where necessary. Verify git, bash, make, Perl, Python, Docker, tmux and SSH requirements. Compare dependencies against the existing Ubuntu test Dockerfile [6].

☐  Classify existing tests: local, Docker, SSH/tmux, network-dependent and privileged/hardware-dependent. Identify required users, files, services, image tags, paths, credentials and timeouts. Do not assume a hosted runner supports the entire suite.

## 1.3  Run and record the unchanged baseline

```bash
./autogen.sh && ./configure && make && sudo make install
bin/vigilia --help
bin/vigilia --show-modules > /tmp/vigilia-modules.txt
make check; rc=$?; printf "make check rc=%s\n" "$rc"
ls -l report.yml run_harness.log test-suite.log
```

Record the number of selected/executed tests, failures, skips, runtime, dependency versions and artifacts. Investigate existing failures and hard-coded paths before declaring the baseline green. If Docker is required, verify docker info as the actual test user.

EXIT GATE  —  A clean runner can build/install and execute a known nonempty test set; all exceptions and required infrastructure are recorded. Do not hide baseline failures.

# Phase 2  /  Common CI entry point

Owner: repository maintainer. Deliverables: ci/install-dependencies.sh, ci/test.sh, ci/README.md, run_harness.sh update and .gitignore entry for ci-results/.

## 2.1  Create the dependency installer

```bash
#!/usr/bin/env bash
set -euo pipefail
sudo -n apt-get update
sudo -n apt-get install -y --no-install-recommends \
  autoconf automake make gcc git perl python3-dev \
  python3-setuptools python3-wheel python3-yaml jq grc \
  libclone-perl libexpect-perl libfile-chdir-perl \
  libfile-find-rule-perl libinline-perl libipc-system-simple-perl \
  libjson-perl libnet-ip-perl libtoml-perl libyaml-pp-perl \
  libwww-perl screen unzip openssh-server sshpass tmux libfaketime
# Docker: pre-provision on runner; verify if required by the suite.
```

Candidate package list derived from upstream prerequisites and Dockerfile, not a verified complete dependency manifest. Validate on Ubuntu 24.04; add actual missing modules rather than silently ignoring installation errors. Install PDF tooling only for a documentation job.

## 2.2  Adapt the existing harness (not a new harness)

```bash
#!/bin/sh
set -eu
# CI mode is opt-in; preserve the existing local default.
if [ "${VIGILIA_CI:-0}" = 1 ]; then
    exec env NEUROSPACES_HARNESS_OPTION_EMAIL=0 \
        bin/vigilia --console-type linear \
        --reporting-directory "$VIGILIA_REPORT_DIR"
fi
exec bin/vigilia "$@"
```

Check that the reporting-directory option is honored and the linear reporter remains noninteractive without a controlling terminal. Test email suppression, timeout behavior and exact working directory. If full suite needs infrastructure not present, introduce a documented nonempty smoke profile through the existing tag selection, after verifying tags and syntax.

## 2.3  Preserve the existing test semantics

Do not modify assertions to make the CI job pass. Keep installation separate from execution and do not run the test harness as root. Use disposable runners because installation modifies system paths and may build bundled CPAN modules.

EXIT GATE  —  Dependency script succeeds on a fresh runner; the harness remains backward compatible and produces a valid report in CI mode.

# Phase 2 continued  /  Test contract

## 2.4  Implement ci/test.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export LC_ALL=C.UTF-8 TERM=dumb VIGILIA_CI=1
export VIGILIA_REPORT_DIR="$PWD/ci-results"
mkdir -p "$VIGILIA_REPORT_DIR"
# Remove stale evidence from previous invocations.
rm -f ci-results/{report.yml,test-suite.log,run_harness.log,run.log}
rm -f ci-results/{exit-code.txt,environment.txt,summary.md,junit.xml}
rm -f report.yml test-suite.log run_harness.log
collect() {
    local rc=$?
    trap - EXIT
    for f in test-suite.log run_harness.log; do
        if [[ -f "$f" ]]; then cp "$f" ci-results/ || true; fi
    done
    printf '%s\n' "$rc" > ci-results/exit-code.txt
    exit "$rc"
}
trap collect EXIT
{ git rev-parse HEAD; uname -a; cat /etc/os-release; } \
    > ci-results/environment.txt
bash -euo pipefail -c '
    ./autogen.sh
    ./configure
    make
    sudo -n make install
    make check
    test -s ci-results/report.yml
' 2>&1 | tee ci-results/run.log
```

Commit scripts as executable: chmod +x ci/*.sh run_harness.sh. Add ci-results/ to .gitignore. A separate Bash process preserves fail-fast behavior inside the logging pipeline; the script fails if a successful make check has no report. Automake may map the original vigilia exit code to its own nonzero value; preserve that distinction in the report and logs.

## 2.5  Verify the control path experimentally

| Experiment | Expected outcome |
| --- | --- |
| Clean baseline | Exit 0; nonempty report; selected test count > 0. |
| Temporary wrong expected output / exit code | Nonzero exit; failing assertion in report and logs. |
| Malformed fixture / missing dependency | Nonzero exit; diagnostic retained even without report. |
| No selected tests; timeout / interruption | Reject zero tests; investigate timeout and canceled-run cleanup. |

Implement the zero-test guard in Phase 2 using parsed native report counters once their schema is confirmed, and require it before starting the CI pilots. Phase 5 expands validation. The script above is a starting point, not the completed guard. If report writing fails or exit status is wrong, fix the relevant vigilia/harness behavior before merge gating. Never use grep on colored output to determine pass/fail.

EXIT GATE  —  Positive and negative controls agree at vigilia, make check and ci/test.sh layers. Run from a clean checkout, with no manual prompts.

# Phase 3  /  GitHub Actions

Owner: repository maintainer. Deliverable: .github/workflows/regression-tests.yml. Use a GitHub-hosted Ubuntu VM initially, or an isolated self-hosted VM only if necessary.

## 3.1  Add the pipeline definition

```yaml
name: Regression tests
on:
  push:
    branches: [master]
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  regression-tests:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Install dependencies
        run: |
          mkdir -p ci-results
          set -o pipefail
          ./ci/install-dependencies.sh 2>&1 | tee ci-results/deps.log
      - name: Run regression tests
        run: ./ci/test.sh
      - name: Upload evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: vigilia-results
          path: ci-results/
          retention-days: 30
          if-no-files-found: warn
```

## 3.2  Execute the pilot

☐  Push the feature branch and open a pull request against master. Verify Actions are enabled; start a manual run where the workflow is available on the default branch.

☐  Inspect logs and download artifacts. Introduce the controlled failure on the feature branch, confirm red status and retained diagnostics, then revert the fixture change.

☐  Confirm the expected runner can access Docker if required; use no production secrets for pull requests. Before merge gating, pin action references to reviewed full commit SHAs.

EXIT GATE  —  A real PR produces reproducible green/red results and downloadable evidence. Keep the status check advisory until Phase 6.

# Phase 4  /  GitLab CI/CD

Owner: repository maintainer and GitLab runner administrator. Deliverable: .gitlab-ci.yml. Start with an isolated Ubuntu 24.04 VM using the shell executor, with the same installed tools and noninteractive sudo as the pilot.

## 4.1  Register and configure a runner

☐  Register an ephemeral or dedicated disposable runner for this project, use the proposed tag ubuntu-ci, and verify sudo -n true and docker info (if required) as gitlab-runner. Use one job per VM to prevent global installation collisions; do not expose sensitive hosts to untrusted branches.

## 4.2  Add the pipeline definition

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS &&
           $CI_PIPELINE_SOURCE == "push"'
      when: never
    - if: '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH'
    - if: '$CI_PIPELINE_SOURCE == "web"'
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
stages: [test]
regression-tests:
  stage: test
  tags: [ubuntu-ci]
  timeout: 1h
  script:
    - mkdir -p ci-results
    - set -o pipefail
    - ./ci/install-dependencies.sh 2>&1 | tee ci-results/deps.log
    - ./ci/test.sh
  artifacts:
    when: always
    expire_in: 30 days
    paths:
      - ci-results/
```

The GitLab workflow rules control event selection, not engineering workflows. Branch pushes with open merge requests are suppressed to avoid duplicate pipelines. The shell executor uses the host OS, not an image: field. A Docker executor is a later explicit design choice [8].

## 4.3  Execute the pilot

☐  Validate YAML in CI Lint; push the same commit to the GitLab project or mirror. Open a merge request and compare counts and failures with GitHub and the local baseline.

☐  Repeat the deliberate failing test, inspect retained artifacts, and revert the change. Confirm manual and scheduled runs work when configured.

EXIT GATE  —  Same selected suite and expected pass/fail outcome on both services; artifacts accessible after ordinary failure. No required merge gate yet.

# Phase 5  /  Native test evidence

Owner: vigilia maintainer. Deliverables: documented native report contract, validator and fixtures. No external reporting framework or JUnit XML is required.

## 5.1  Inspect the existing report.yml

☐  Capture representative reports for pass, assertion failure, disabled test and harness failure. Identify the schema and stable test IDs, execution context, counters, error details and duration. Verify that report.yml is a results report, rather than the specification dumps produced by --dump-json / --dump-yaml [5].

☐  Establish a safe YAML parser/validator (using existing dependencies) and verify the zero-test guard introduced in Phase 2. Check counters against individual cases; distinguish no tests, incomplete execution and complete suites. Never fabricate passed tests when a report is missing.

## 5.2  Reporting architecture

```text
                          vigilia
                             |
                        report.yml
                     (native results)
                             |
           +-----------------+------------------+
           |                 |                  |
     Native evidence     Markdown summary     JUnit XML
       (required)          (optional)          (optional)
           |                 |                  |
     CI artifacts       GitHub job summary    GitLab test UI
     logs / metadata    + generic artifact   + external tools
```

The exit status is the authoritative pipeline control signal. A missing, invalid, incomplete or empty native report must cause an otherwise successful job to fail. Preserve any original nonzero status and retain diagnostic evidence. Markdown and JUnit XML are derived views, never independent test executions or gate prerequisites.

## 5.3  Validate and publish native evidence

☐  Archive report.yml, test-suite.log, run_harness.log, run.log, exit-code.txt and environment.txt on both platforms. Confirm the recorded outcome and test identity are consistent with the actual executed commit and profile. Test pass, failure, invalid YAML, missing report and zero tests with checked-in fixtures.

☐  Keep HTML/PDF output available as native human-readable documentation or reports. Use a separate make vigilia-html / documented generation job where appropriate; do not present generated specification documentation as evidence of actual test execution.

EXIT GATE  —  Native evidence is validated and available for both pipelines. A known failing test and an invalid or missing report produce nonzero status. No optional export is necessary to proceed.

# Phase 6  /  Harden and extend

Owner: repository maintainer and CI administrators. Deliverables: runner policy, merge requirements, documentation and reusable process interfaces.

## 6.1  Expand coverage safely

☐  Define smoke, full regression, integration and documentation profiles with explicit tags or module selectors. Validate nonempty selection for every profile. Smoke runs on PR/MR; full regression runs on protected branches and scheduled pipelines.

☐  Reuse existing Debian, Ubuntu, Fedora and OpenSUSE test Dockerfiles; first extract common dependency-only images if suitable, pin base image digests and invalidate caches on dependency changes. Run tested source from the checked-out commit, not a stale preinstalled build.

☐  Separate Docker-in-Docker, socket access, QEMU/KVM and hardware/SSH suites onto isolated runners. Treat Docker socket access as privileged; use protected runners for trusted code only. Use per-job resource names and cleanup on exit/cancellation; enforce timeouts.

## 6.2  Activate production merge gates

☐  Require GitHub regression-tests and enable GitLab successful-pipeline merge checks only after repeated clean runs and confirmed red controls. Protect the default branch and CI definitions; document rollback and runner ownership.

☐  Publish commit SHA, profile, runner OS/architecture, dependency and tool versions, outcome and logs. Apply a proposed 30-day operational retention, with separate approved retention for release evidence. Audit secrets and redact sensitive test output.

## 6.3  Make integration reusable in downstream projects

Keep ci/test.sh as a stable adapter. For downstream projects, optionally move project-specific build, provisioning and test orchestration into an existing <project>-workflow command (for example, ci test, to be implemented). It must propagate vigilia status and write the same artifact contract. Local command, GitHub and GitLab all invoke that interface.

## Definition of done

| Check | Evidence |
| --- | --- |
| Same tests, same commit | Local/GitHub/GitLab reports agree on logical results. |
| Failure detection | Deliberate assertion and infrastructure failures block merge. |
| Reproducibility | Fresh runner succeeds; profiles, versions and setup documented. |
| Maintainability | No duplicated tests; one common entry point; ownership assigned. |

EXIT GATE  —  Maintainers approve the merge gate, runner security and evidence policy. Future extensions use the same test contract.

# Phases 7–8  /  Optional reporting adapters

Owner: vigilia maintainer. Start only after the native evidence contract is stable. Both adapters consume report.yml without altering the test engine or requiring a rerun.

## 7.1  Native Markdown summary (P2)

☐  Optionally implement ci/report-to-markdown.py using the existing YAML parser. Show selected/executed counts, pass/fail/error/skip totals, failed test IDs and bounded diagnostic text. If evidence is missing, say so explicitly; redact secrets. Publish the Markdown file as a portable artifact and append it to GitHub's $GITHUB_STEP_SUMMARY in an always() step [10]. No JUnit or third-party reporting action is needed.

EXIT GATE  —  If enabled, the summary agrees with report.yml for positive and negative controls; absence of the optional summary does not change the regression-test status.

## 8.1  JUnit XML interoperability (P3)

JUnit XML is an interchange format, not a dependency on the Java JUnit framework. It enables GitLab's native test-result UI and comparisons in merge requests [9]. It does not determine a pipeline's pass/fail status. Implement only when native CI visualization or external tool interoperability is requested.

☐  If justified, implement ci/report-to-junit.py using the existing YAML parser and Python's standard XML library. Use stable unique test IDs, distinct failure/error/skipped elements, consistent totals and durations where available, and proper XML escaping. Test fixtures against the native report; do not invent results for incomplete runs. No Java, JUnit runtime or third-party reporting framework is required.

```yaml
# Optional: under the GitLab job's existing artifacts: block
reports:
  junit: ci-results/junit.xml
```

☐  Run enabled exporters after an ordinary failed test as well as a pass; publish diagnostics on export failures and preserve the test status. Remove stale export files before each run. Any reporting-specific quality gate must be separate and explicitly requested. Never upload untrusted output or secrets to external tools.

EXIT GATE  —  If enabled, JUnit totals and identities agree with report.yml and GitLab displays the expected positive/negative controls. If deferred, record the decision; Phase 6 remains complete without either adapter.

# Implementation register and references

## Suggested commit sequence

| Commit | Change | Verify |
| --- | --- | --- |
| 01 | docs(ci): record baseline and runner prerequisites | Phase 1 baseline |
| 02 | ci: add dependency installer and common runner | Local green/red |
| 03 | test: enable noninteractive vigilia reporting | Status and YAML |
| 04 | ci: add GitHub Actions | PR pilot |
| 05 | ci: add GitLab pipeline | MR pilot |
| 06 | test: validate native report contract | Report fixtures |
| 07 | ci: add profiles, policy and maintainer guide | Merge gate review |
| 08 | ci: add Markdown summary adapter (optional) | Summary fixtures |
| 09 | ci: add JUnit XML adapter (optional) | XML fixtures / GitLab UI |

## Decisions and open issues

Proposed choices: Ubuntu 24.04, Automake as initial entry point, linear console reporting, 60-minute job timeout, 30-day artifacts, and GitLab shell VM. These are defaults to confirm in Phase 1. Public master was inspected, but no exact private/local SHA was supplied and no full build or live CI run was performed. Dependency completeness, test coverage, runner prerequisites and report schema remain verification items. JUnit XML and Markdown summaries are optional; native YAML evidence and exit status are the required interface. Do not infer successful execution from HTML generation or report upload.

## Source references

[1] Repository / README — https://github.com/neurospaces-development/workflow-vigilia

[2] Automake entry point — https://github.com/neurospaces-development/workflow-vigilia/blob/master/Makefile.am

[3] Existing harness — https://github.com/neurospaces-development/workflow-vigilia/blob/master/run_harness.sh

[4] Tester configuration — https://github.com/neurospaces-development/workflow-vigilia/blob/master/vigilia.config

[5] Vigilia CLI and report_exit / report_file_dump — https://github.com/neurospaces-development/workflow-vigilia/blob/master/bin/vigilia

[6] Ubuntu installation test Dockerfile — https://github.com/neurospaces-development/workflow-vigilia/blob/master/vigilia/specifications/dockerfiles/Dockerfile.workflow-install-testing-ubuntu

[7] GitHub Actions artifacts — https://docs.github.com/en/actions/tutorials/store-and-share-data

[8] GitLab workflow rules and YAML — https://docs.gitlab.com/ci/yaml/workflow/

[9] GitLab JUnit reports — https://docs.gitlab.com/ci/testing/unit_test_reports/

[10] GitHub job summaries — https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary
