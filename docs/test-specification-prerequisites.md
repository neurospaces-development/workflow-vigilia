# Execution prerequisites and portability of the test specifications

This document classifies the **execution requirements**, rather than the
publication value, of the `vigilia` product knowledge base. Paths below are
relative to `vigilia/specifications/`. The inventory reflects the repository
through the addition of the `full` CI jobs in patch 0048 (36 modules in
all). Both hosted full jobs subsequently passed all 36 modules and 256 enabled
assertions at revision `43bb8aa85c76`; this inventory remains a description
of technical prerequisites, not a guarantee about future changes. The current provider/job architecture is documented in
[CI/CD architecture and operation](ci-cd-architecture.md).

The authoritative test material is the specification itself. A module used
to generate a manual or tutorial must also remain part of the unfiltered test
knowledge base; documentation-specific tags must not remove it from testing.
`ci/docker-suite.modules` is an **empty-by-default focused-testing list**,
not a second source of truth or the definition of `full`.

## Execution model and common prerequisites

- **Local, unfiltered:** `bin/vigilia` (with its normal configuration and no
  selector) discovers the whole knowledge base. This defines the intended
  selection semantics of CI/CD `full`; it does not mean that every dependency
  is already provisioned locally or in CI.
- **Opt-in native smoke/regression:** `ci/test.sh` builds and installs the
  checkout and runs the requested selection. The package needs Perl and its
  required modules, Python for the CI helpers, the build toolchain, and the
  shell utilities installed by `ci/install-dependencies.sh`. Native reports
  distinguish discovered, selected and executed command tests.
- **Focused Docker suite:** `ci/docker-suite.sh` accepts explicit `--module`
  paths, `VIGILIA_DOCKER_MODULES` or an alternate
  [`ci/docker-suite.modules`](../ci/docker-suite.modules) file, runs selected
  modules *one at a time* via `ci/test.sh`, and records reports and logs.
  Each module needs its Dockerfile, a working daemon and permission to build
  images, create networks, start containers, and use `docker exec -it`.
- **Docker platforms differ:** GitHub Actions uses the daemon on its Ubuntu
  runner VM; GitLab uses TLS-enabled Docker-in-Docker (`DOCKER_HOST` and
  client certificates). GitLab sets `VIGILIA_DOCKER_NETWORK_SUBNET=auto` to
  avoid subnet conflicts. A module with a hard-coded container address, host
  bind mount, or shared `/var/run/docker.sock` is **not** automatically
  portable merely because ordinary Docker modules pass.
- **Isolation:** tests create projects, alter user shell configuration,
  install packages, start services and manipulate Docker images. Use
  disposable containers/runners, trusted branches, and no production
  credentials. Some Dockerfiles run package-manager updates and/or CPAN
  installation, so image building requires external repository access.
- **Deterministic time:** `Dockerfile.workflow-feature-testing` preloads
  `libfaketime` and sets `FAKETIME="@2025-10-11 11:38:32"`.
  `33_specific-features-export-times` intentionally verifies fixed output;
  its historical timestamps are *not* an implementation defect.

### Terminology

| Classification | Meaning | Action |
|---|---|---|
| **Verified hosted** | Native reports from the same Git revision show the enabled assertions executed and passing on both providers. | Retain and monitor. |
| **Added, pending hosted** | Source prerequisites appear suitable for the existing runner, but the new job has not yet passed. | Run and inspect per-module evidence. |
| **Environment/configuration prerequisite** | Needs SSH routing, daemon socket sharing, an image dependency, writable host state, distro packages or a specific execution order. | Provision or isolate the environment before classifying assertion failures. |
| **Specification maintenance** | Exact output, filenames, paths, external dependencies or fixture expectations differ from the implementation/environment. | Confirm intended behavior; update the specification *only when justified*. |
| **Implementation defect / incomplete feature** | Intended behavior is demonstrably wrong or explicitly unimplemented, *after* the environment and assertion are validated. | Keep the failing/disabled assertion traceable; fix product or harness behavior. |

An unsuccessful pipeline alone cannot distinguish the last three cases.

## Historical focused Docker baseline: 22 modules (both platforms verified)

At revision `6d00bee29480b91157a1db6a858e818bec7b4613`, **all 22
modules and 149 enabled assertions passed on both GitHub Actions and GitLab
CI/CD**. Three assertions in the 22 modules remain explicitly disabled.
The Docker-role image build uses a 900-second timeout to support cold builds
on hosted runners; the assertion and expected output are unchanged.

| Specification | Tests enabled | Specific technical prerequisites | Status |
|---|---:|---|---|
| `20_vigilia/30_docker.t` | 3 | `Dockerfile.neurospaces-testing`, container shell | Verified hosted |
| `20_vigilia/12_error_checking/summary.yml` | 5 | Docker harness; expected failure diagnostics | Verified hosted |
| `40_workflow-automator/15_error-pages/summary.yml` | 5 | Docker; CLI error output; one disabled assertion | Verified hosted |
| `40_workflow-automator/29_config-loader-errors/summary.yml` | 2 | Docker; deliberately invalid/missing config files | Verified hosted |
| `40_workflow-automator/31_specific-features-export-variables/summary.yml` | 3 | `Dockerfile.workflow-feature-testing`; installed project configuration | Verified hosted |
| `40_workflow-automator/28_command_array_concatenation/summary.yml` | 2 | Same image; command scheduling; one unimplemented assertion disabled | Verified hosted |
| `40_workflow-automator/36_specific-features-timestamps/summary.yml` | 4 | Same image; timestamp-related output | Verified hosted |
| `40_workflow-automator/37_specific-features-background/summary.yml` | 2 | Same image; background command execution | Verified hosted |
| `40_workflow-automator/32_specific-features-export-sh/summary.yml` | 15 | Same image; shell exports and role commands | Verified hosted |
| `40_workflow-automator/33_specific-features-export-times/summary.yml` | 5 | Same image; **libfaketime** and fixed `FAKETIME` | Verified hosted |
| `40_workflow-automator/27_schedule/summary.yml` | 8 | Same image; scheduling and interaction inspection | Verified hosted |
| `40_workflow-automator/34_specific-features-annotations.t` | 2 | Same image; Perl `.t` specification | Verified hosted |
| `40_workflow-automator/38_rename_project/summary.yml` | 5 | Same image; mutable project files, isolated home | Verified hosted |
| `40_workflow-automator/39_specific_features_ai/summary.yml` | 16 | Same image; synthetic API-token file operations; **no live API calls** | Verified hosted |
| `40_workflow-automator/42_use-dot-local-bin/summary.yml` | 4 | Same image; writable `~/.local/bin` | Verified hosted |
| `40_workflow-automator/46_builtin/summary.yml` | 16 | `Dockerfile.features-workflow-installed-testing`; preinstalled feature configuration; exact source-line/output expectations | Verified hosted |
| `40_workflow-automator/80_install-testing/10_debian/summary.yml` | 2 | `Dockerfile.workflow-install-testing-debian`; Debian Bookworm image, apt repositories and package installation | Verified hosted |
| `40_workflow-automator/80_install-testing/20_ubuntu/summary.yml` | 2 | `Dockerfile.workflow-install-testing-ubuntu`; Ubuntu 24.04 image, apt repositories and package installation | Verified hosted |

The four advanced-harness modules have been executed in CI/CD:

| Specification | Enabled command tests | Additional prerequisite | CI status |
|---|---:|---|---|
| `40_workflow-automator/30_specific-features-cd.t` | 9 (1 disabled) | tmux, sshpass/sshd, container self-SSH, container IP substitution | Verified hosted |
| `40_workflow-automator/40_remote_script_execution/summary.yml` | 4 | `Docker::Remote`; source checkout is provided inside its Docker image; SSH/scp and host-side preparer dispatch | Verified hosted |
| `40_workflow-automator/44_roles/10_docker/summary.yml` | 5 | Shared Docker socket; daemon-side socket group; nested Docker 20.10 client; legacy build output; cold-build timeout | Verified hosted |
| `40_workflow-automator/50_bash_completion/summary.yml` | 30 | `Docker::Remote`; `feature-testing-workflow` and source checkout are provided inside the Docker image | Verified hosted |

**Do not silently skip failures in these modules.** The serial suite records
one report per module and continues after a failure. The same specifications
are used on both platforms, not provider-specific test variants. The source
checkout under `/home/neurospaces/projects/...` is deliberately created by
the Dockerfile **inside the container**; it is not a path expected to exist
in the CI job container or GitHub runner filesystem.

The two distribution tests run installation **within the image** and then
check the installed `feature-testing-workflow` configuration. Their need for
package repositories during image construction is a routine prerequisite,
not proof that the tests need changes. The builtin module's exact-output
assertions include source line numbers; source changes may legitimately
require specification review.

## Complete unfiltered CI execution

At revision `6d00bee29480b91157a1db6a858e818bec7b4613`, the Docker
suite passed **22 modules and 149 enabled assertions** on **both** hosted
platforms. GitHub's Docker-role image-build timeout was increased to 900 s
without changing its expected output.

The verified `full` CI jobs execute all **36 discovered modules in one `vigilia`
run**, with the same unfiltered module selection as plain local `bin/vigilia`
when using the same specification configuration. The runtime environment may
differ. There is no separate curated selection list. In particular, `20_preparation.t` and
`25_preparation_checker.t` share state and contain no command assertions,
so independently invoking them through the positive-assertion CI gate is not
equivalent to testing the full knowledge base. `15_docker_creator.t` creates
an image needed by `41_docker_creator_output_formats.t` and `50_merges.t`.

The first full jobs passed at revision `43bb8aa85c76` on both platforms. The 14
previously unselected modules have not all passed on hosted runners; some
may require fixes to legacy expected output, package provisioning or image
setup. Full-suite failures remain failing CI jobs, and logs are preserved.

## Remaining 14 modules: prerequisites and blockers

These modules are *not* selected by the Docker-suite list above. Some are
already exercised by the **separate native smoke/regression jobs**. Others
require environment engineering or review before being promoted to hosted
Docker testing. They remain part of unfiltered `vigilia` discovery.

| Specification | Required prerequisites / reason for deferral | Suggested next action |
|---|---|---|
| `20_vigilia/10_help/summary.yml` | No Docker harness; exact help output. Already in native regression selection. | Keep in native CI, not duplicate in Docker suite. |
| `20_vigilia/13_inspection_exit_code.module.yml` | No Docker; standalone test invokes the dedicated inspection regression script. Native smoke/regression tag. | Keep in native CI. |
| `20_vigilia/14_tag_selection.module.yml` | No Docker; hierarchical-tag regression script. Native regression tag. | Keep in native CI. |
| `20_vigilia/15_tag_query.module.yml` | No Docker; Boolean-query regression script. Native regression tag. | Keep in native CI. |
| `20_vigilia/15_docker_creator.t` | Docker preparation/image snapshot; CPAN installation and historical source path `~/projects/workflow-automation-engine/source/snapshots/master`. | Establish image-creator and `docker-snapshot` prerequisites; validate outputs. |
| `20_vigilia/20_preparation.t` | Preparation/reparation callbacks write fixed `/tmp/preparation.txt` and `/tmp/reparation.txt`; **no command assertions**. | Exercise together with its checker in a stateful harness-level test; do not feed into the positive-assertion per-module gate unchanged. |
| `20_vigilia/25_preparation_checker.t` | Reads state created by the preceding module; **no command assertions**. | Preserve ordering and shared fixture state when validating the pair. |
| `20_vigilia/40_output_formats.t` | Docker plus build/installation steps, `docker-snapshot`, historical CLI/formatter exact outputs; some HTMLTable output explicitly unimplemented. | Review current formatter APIs and image-creation prerequisites. |
| `20_vigilia/41_docker_creator_output_formats.t` | `Docker::Image` harness expects pre-existing image `vigilia-image`, created by another module; formatter exact outputs. | Supply and version the prerequisite image; verify outputs. |
| `20_vigilia/50_merges.t` | Same `Docker::Image` dependency (`vigilia-image`); expects merge fixtures and a config file. | Provision image and merged-module fixture consistently. |
| `40_workflow-automator/12_help-pages/summary.yml` | No Docker; 24 command-line help assertions; exact text may change with product version. | Pilot as native CI module and update intended help expectations if needed. |
| `40_workflow-automator/25_smoke/summary.yml` | `Dockerfile.workflow` (separate image); long **stateful** build/install, `.bashrc`, archive and shell-history sequence; some assertions disabled for harness limitations. | Isolated end-to-end pilot with sufficient timeout and sequence preservation. |
| `40_workflow-automator/80_install-testing/30_fedora/summary.yml` | `Dockerfile.workflow-install-testing-fedora` uses `fedora:40`, DNF repositories, CPAN `TOML`, build/install. | Check base-image/repository availability and distribution package compatibility first. |
| `40_workflow-automator/80_install-testing/40_opensuse/summary.yml` | `Dockerfile.workflow-install-testing-opensuse` uses rolling `opensuse/tumbleweed`, `zypper`, CPAN `TOML`, build/install. | Check current package names, image build reproducibility and repository availability first. |

### Examples: environment configuration versus actual defects

**Environment / execution infrastructure (not product defects):**

- GitLab's former fixed `172.18.0.0/16` Docker subnet conflicted with another
  network. Patch 0035 introduced `VIGILIA_DOCKER_NETWORK_SUBNET=auto` and
  preparation error handling; this was an infrastructure-compatibility issue.
- GitLab Docker-in-Docker exposes the client connection at `tcp://docker:2376`,
  but the daemon's Unix socket exists in the **DinD service container**, not
  the CI job container. Socket group inspection must run on the daemon side;
  Docker Engine 28 is used to support the old Docker 20.10 CLI installed in
  the nested test image. The Docker-role fixture also relies on legacy
  `docker build` output; `DOCKER_BUILDKIT=0` makes that behavior deterministic.
- `41_docker_creator_output_formats.t` and `50_merges.t` depend on an existing
  `vigilia-image`; running them in isolation without the image is an
  *unsatisfied prerequisite*, not an assertion about product correctness.
- `20_preparation.t` and `25_preparation_checker.t` have zero command tests
  and share `/tmp` state. The existing Docker-suite positive-test-count gate
  is therefore not an appropriate standalone acceptance criterion for them.

**Specification/harness issues or known incomplete functionality:**

- `40_workflow-automator/28_command_array_concatenation` explicitly disables
  a tmux-role assertion with **"This is not implemented yet."** That is a
  documented feature gap, not a passing test.
- `20_vigilia/40_output_formats.t` and
  `20_vigilia/41_docker_creator_output_formats.t` disable their HTMLTable
  assertions because the formatter is **"not fully implemented."** This is
  explicit evidence of incomplete implementation; it does *not* establish
  whether the other formatter assertions currently pass.
- `40_workflow-automator/30_specific-features-cd.t` disables the `tmux ls`
  assertion with **"the regex does not work"**. This is an assertion/fixture
  issue until evidence isolates a runtime bug.
- `40_workflow-automator/25_smoke` documents inability to read an output file
  in one disabled test and a Bash-history visibility issue in another.
  These should first be investigated as harness/fixture constraints.

**Genuine implementation defect:** classify a new failure this way *only if*
its prerequisites were satisfied, the expected behavior is still correct,
and repeatable native `vigilia` evidence shows that the product (or harness)
does not implement it. **The presently validated hosted modules show no such
failing assertions**; do not conflate disabled placeholders with confirmed
runtime regressions.

## CI failure triage and evidence

1. Examine `ci-results/docker-suite/run.*/summary.tsv` to identify the exact
   module. Read its `console.log`, `docker-*.log`, `make-check.log`, and native
   `run.*/report/report.yml` before changing any specification.
2. If the Dockerfile failed to build or a network, SSH, path, package or
   image prerequisite is missing, classify it as **environment provisioning**.
3. If the product executed but an exact-output assertion differs, compare
   the intended behavior with the current implementation. Classify stale
   expectations as **specification maintenance**; a reproducible behavioral
   mismatch with a valid expectation is a **product/harness defect**.
4. Preserve the failed report and repair the appropriate layer. Do not
   disable an assertion solely to obtain a green CI pipeline.
5. Keep documentation and tutorial source bound to the *same committed*
   specification and tested revision. A verified CI report is evidence for
   a particular run, not a blanket assertion that later commits still pass.

For a single-module local investigation, create an alternate module list:

```sh
printf '%s\n' '40_workflow-automator/46_builtin/summary.yml' \
  > /tmp/vigilia-docker-one-module.txt
VIGILIA_DOCKER_MODULES_FILE=/tmp/vigilia-docker-one-module.txt \
  ci/docker-suite.sh --test-only
```

For the hosted Docker jobs, gather the latest revision's evidence with:

```sh
automation-workflow ci artifacts_download docker -- --mode latest-wait
automation-workflow ci artifacts_verify
automation-workflow ci artifacts_report
```

The `--` is required by the `automation-workflow` command-line parser; it
separates workflow options from operation-specific arguments.
