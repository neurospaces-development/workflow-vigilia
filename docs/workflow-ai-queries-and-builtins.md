# Useful AI Queries and `builtin_ai_*` Commands for the `workflow` Engine

The most valuable use of AI in `workflow` is not “ask anything”; it is turning the generated manual, dry-run output, lint output, stack traces, and source snippets into actionable workflow knowledge.

The current primitive is essentially:

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Can you summarize the purpose of this project?"
```

That is useful, but it should be treated as the low-level transport. Higher-level `builtin_ai_*` commands can wrap it with stronger prompts and more deterministic output.

OpenAI’s current file-input flow supports this pattern: upload a file, then reference the resulting `file_id` as an `input_file` in the Responses API. For commands that need parseable output, Structured Outputs are worth considering because they constrain model responses to a supplied JSON schema instead of relying on free-form text.

## Useful Queries for the Current `builtin_ai_query`

### 1. Orientation Queries

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Explain the workflow engine in terms of targets, operations, builtins, roles, scheduling, and interactions. Assume I know Perl but not this codebase."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Give me a conceptual map of the workflow engine. List the main command groups and explain when I would use each one."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "What are the safest first five commands for a new user to run, and why?"
```

### 2. Command Discovery

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "I want to find where a workflow command is implemented. Which workflow command should I use, and what is the exact command line?"
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "I want to inspect available workflow commands related to Docker. Which commands are relevant? Give examples."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "I want to generate project documentation. Which builtin commands are involved and in what order should I run them?"
```

### 3. Operational Runbooks

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Write a runbook for adding a new workflow command, including help text, bash completions, lint checks, and manual regeneration."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Write a runbook for debugging why a workflow command does not appear in bash completion."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Write a runbook for renaming a workflow project while preserving references and avoiding destructive changes."
```

### 4. Safety and Dry-Run Interpretation

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Which commands may change files, Git history, Docker state, remote hosts, or project configuration? Classify them by risk."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Explain how --dry-run, --interactions, and command scheduling interact. Give examples of how to preview changes safely."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Before running project_rename, what should I inspect, back up, or dry-run?"
```

### 5. Developer-Maintenance Queries

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "How should a new builtin command be structured? Include the main sub, _completions sub, and _help sub."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "What conventions does this project use for command names, target names, operation names, and help generation?"
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Find likely inconsistencies, missing documentation, or confusing command names in the manual."
```

### 6. Test-Generation Queries

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Propose command-line tests for builtin ai_query. Include success cases, missing argument cases, nonexistent PDF, missing query, and --dry-run behavior."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Generate a YAML command_tests block for verifying that builtin lint reports missing help and completion functions."
```

### 7. Documentation-Improvement Queries

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Rewrite the builtin ai_query help page so it explains API key setup, PDF upload, model selection, and expected YAML output."
```

```bash
workflow builtin ai_query workflow-engine-manual-builtin.pdf \
  "Identify commands whose help text is too terse. Suggest improved help text."
```

## Useful `builtin_ai_*` Commands

The following commands would provide a practical AI layer on top of the existing `workflow` command model.

| Perl sub | CLI shape | Purpose |
|---|---|---|
| `builtin_ai_command` | `workflow builtin ai_command "<intent>"` | Convert natural-language intent into candidate `workflow` commands. |
| `builtin_ai_explain` | `workflow builtin ai_explain <command-or-topic>` | Explain a command, target, or concept from the manual. |
| `builtin_ai_error` | `workflow builtin ai_error <log-file>` | Explain stack traces, command failures, and likely fixes. |
| `builtin_ai_dry_run_review` | `workflow builtin ai_dry_run_review <file>` | Explain `--dry-run` or `--interactions` output. |
| `builtin_ai_manual_review` | `workflow builtin ai_manual_review <pdf>` | Review generated manual quality and detect missing or confusing docs. |
| `builtin_ai_patch_review` | `workflow builtin ai_patch_review <patch-file>` | Review a patch for risk, style, missing help, completions, and tests. |
| `builtin_ai_tests` | `workflow builtin ai_tests <command-name>` | Generate command tests for one builtin or workflow command. |
| `builtin_ai_completion_draft` | `workflow builtin ai_completion_draft <command-name>` | Draft a bash completion sub for an existing command. |
| `builtin_ai_help_draft` | `workflow builtin ai_help_draft <command-name>` | Draft or improve the `_help` sub. |
| `builtin_ai_architecture` | `workflow builtin ai_architecture <pdf-or-source>` | Produce architecture notes from manual or source context. |
| `builtin_ai_security_review` | `workflow builtin ai_security_review <file-or-command>` | Review shell quoting, API key handling, remote execution, and destructive commands. |
| `builtin_ai_cache_file` | `workflow builtin ai_cache_file <file>` | Upload once, store file ID and checksum metadata, and reuse for later queries. |

## First Command to Implement: `builtin_ai_command`

This is probably the most useful user-facing command because it turns the manual into a command recommender.

Example:

```bash
workflow builtin ai_command workflow-engine-manual-builtin.pdf \
  "I want to find the Perl file and line number that implements builtin ai_query"
```

Expected output should be structured, not prose:

```yaml
intent: "Find implementation location for builtin ai_query"
recommended_commands:
  - command: "workflow builtin workflow_locate builtin_ai_query"
    confidence: 0.72
    reason: "The workflow_locate builtin is intended to locate workflow implementations."
  - command: "workflow builtin grep_code '^sub builtin_ai_query$'"
    confidence: 0.91
    reason: "Direct source grep for the Perl sub definition."
safety:
  mutates_state: false
  recommended_first_step: "Run the grep_code command."
```

This command should not execute the suggested command automatically. It should recommend commands and mark whether they mutate state.

## Second Command to Implement: `builtin_ai_error`

This would consume stderr, stack traces, or log files.

Example:

```bash
workflow builtin ai_error workflow-engine-manual-builtin.pdf error.log
```

or:

```bash
workflow builtin ai_error workflow-engine-manual-builtin.pdf -- \
  'OpenAI API error: Unknown error while validating file ownership...'
```

Useful prompt behind it:

```text
You are debugging the workflow engine. Explain the likely cause of this error.
Separate:
1. immediate cause,
2. likely code path,
3. whether this is user configuration, API behavior, or workflow bug,
4. commands to run next,
5. patch recommendation if any.
```

This would have helped directly with the `file ownership` error.

## Third Command to Implement: `builtin_ai_patch_review`

This fits the current workflow well because patches are a regular development artifact.

Example:

```bash
workflow builtin ai_patch_review workflow-engine-manual-builtin.pdf workflow-ai-query-retry.patch
```

Output:

```yaml
summary: "Adds retry logic around Responses API file ownership failures."
risk_level: medium
possible_regressions:
  - "May retry non-transient errors if error matching is too broad."
missing_tests:
  - "Test that 400 invalid_request_error is not retried."
  - "Test that 500 ownership validation error is retried."
style_comments:
  - "Keep retry policy inside AI::OpenAI rather than builtin_ai_query."
recommendation: "Accept after adding status-code-aware retry tests."
```

## Fourth Command to Implement: `builtin_ai_tests`

This should generate test cases from a command help page and implementation conventions.

Example:

```bash
workflow builtin ai_tests workflow-engine-manual-builtin.pdf "builtin ai_query"
```

Useful output:

```yaml
command_tests:
  - description: "ai_query rejects missing PDF filename"
    command: "workflow builtin ai_query"
    expected_stderr_regex: "expects the PDF filename"
    expected_exit_code: 1

  - description: "ai_query rejects nonexistent PDF"
    command: "workflow builtin ai_query does-not-exist.pdf 'question'"
    expected_stderr_regex: "PDF file does not exist"
    expected_exit_code: 1

  - description: "ai_query does not upload during dry-run"
    command: "workflow --dry-run builtin ai_query manual.pdf 'question'"
    expected_stdout_regex: ""
    expected_stderr_not_regex: "uploading"
```

## Fifth Command to Implement: `builtin_ai_manual_review`

The `builtin_manual` command generates documentation from help subs. AI can review the resulting manual as a quality gate.

Example:

```bash
workflow builtin ai_manual_review workflow-engine-manual-builtin.pdf
```

It should answer:

```yaml
missing_concepts:
  - "How target/operation names map to Perl sub names."
  - "How --dry-run affects API-calling builtins."
confusing_sections:
  - command: "builtin grep_commands"
    issue: "Synopsis says <grep-regex> but arguments describe target regex and command regex."
suggested_improvements:
  - command: "builtin ai_query"
    change: "Document OPENAI_API_KEY, --model, --base-url, --purpose, and YAML output."
```

## Implementation Notes

For `builtin_ai_*`, avoid hard-coding every command as a separate OpenAI call pattern. Instead, introduce two or three reusable methods in `AI::OpenAI`:

```perl
$client->ask_file(...);         # already present
$client->ask_text(...);         # for logs, patches, dry-run output
$client->ask_file_and_text(...); # manual PDF + stack trace / patch / command output
```

Then each builtin only differs by the prompts:

```perl
my $system_prompt = "... role-specific instruction ...";
my $user_prompt   = "... task-specific prompt ...";
```

For commands that another part of `workflow` will parse, use JSON/YAML-shaped output and ideally API-level structured output. Structured Outputs are intended for schema-conforming JSON responses, which is a better fit than asking the model to “please return valid YAML” and hoping it complies.

## Recommended First Tranche

Add these in this order:

```text
builtin_ai_command
builtin_ai_error
builtin_ai_patch_review
builtin_ai_tests
builtin_ai_manual_review
builtin_ai_cache_file
```

That gives a practical loop:

```text
manual/source → ask for command → run dry-run → review output → patch → review patch → generate tests → regenerate manual → review manual
```

This is a stronger integration than a generic PDF question-answer command.
