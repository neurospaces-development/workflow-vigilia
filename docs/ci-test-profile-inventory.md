# CI profile inventory and documentation tags

This classification is deliberately conservative. Tags describe the intended
selection of a test; they **do not** establish that its dependencies or expected
output have been validated on every CI runner. The CI pipelines must execute
these profiles before treating them as required merge checks.

## Initial classifications

| Specification | Tags | Evidence and rationale |
| --- | --- | --- |
| `20_vigilia/13_inspection_exit_code.module.yml` | `ci:smoke`, `ci:regression` | Runs a disposable local fixture without Docker; previously validated in both hosted CI pilots. |
| `20_vigilia/14_tag_selection.module.yml` | `ci:regression` | Runs a temporary local fixture; performs CLI selection, no Docker or installation. Introduced by patch 0012; hosted validation pending. |
| `20_vigilia/10_help/summary.yml` | `ci:regression`, `manual` | Uses `bin/vigilia` help commands, no Docker harnessing in the module. Exact-output comparisons need hosted validation. Helpful reference material for a manual. |

The smoke profile currently selects **one** top-level `vigilia` command test.
The regression profile selects those tests plus the new tag tests and the
existing help-message tests (approximately twelve top-level command tests,
subject to actual test selection and verification on the runners).

`ci:smoke` is not inferred from the legacy directory
`40_workflow-automator/25_smoke`: that module has a Docker harness and the
pre-existing `manual` tag. **Do not add `ci:smoke` or `ci:regression` to it** on
shared runners.

## Unclassified modules

- `20_vigilia/12_error_checking/summary.yml` has Docker-based harnessing.
- `20_vigilia/15_docker_creator.t`, `30_docker.t`,
  `41_docker_creator_output_formats.t`, and several workflow modules operate
  on Docker images or containers. They require a disposable runner with a
  dedicated Docker daemon.
- `40_workflow-automator/12_help-pages/summary.yml` invokes `bin/workflow`
  help commands. It is a candidate for future non-Docker regression coverage
  **after** a pilot proves dependencies and expected outputs match.
- Workflow installation, configuration, remote access, AI and other
  environment-dependent modules remain unclassified pending explicit audit.

Untouched modules remain part of an unfiltered `vigilia` invocation, i.e. the
**full** profile. The CI entry point requires `VIGILIA_ALLOW_FULL=1` before it
will attempt that profile. No full-suite CI job is enabled by these patches.

## Reusing tags for manuals and tutorials

Tags are generic YAML metadata and may be combined across different concerns:

```yaml
name: example.t
tags: [ci:smoke, ci:regression, manual]
documentation:
  purpose: Explain a feature.
  explanation: The tested command illustrates the feature.
```

The existing `manual` tag is preserved for compatibility. A `tutorial` tag may
later select a curated subset of commands intended for step-by-step teaching.
Subsections can use explicit tags to restrict selection: untagged children
inherit the selected parent; tagged children must themselves match at least
one requested tag.

Examples of nonexecuting source selection:

```sh
bin/vigilia --show-modules --tags manual
bin/vigilia --show-command-tests --tags tutorial
```

Documentation generators already use the execution-independent formatters.
Publication workflows will also need ordering, narrative structure, output
redaction and suitability review. Selecting tags alone does not guarantee
that expected command output is publication-ready.

**Warning:** `--tags manual` without `--show-*` or another output formatter
is an *execution* selection and may run the legacy Docker-backed manual tests.
Do not run it on a shared machine.

## Promotion checklist

Before adding more modules to `ci:smoke` or `ci:regression`, verify that
their commands do not modify host state, require Docker, use fixed container
names, require network secrets, or consume unbounded time. Test them on a
disposable runner, inspect native reports, and promote them only after a clean
positive run. Once a stable profile exists, make the corresponding pipeline
a required merge check.
