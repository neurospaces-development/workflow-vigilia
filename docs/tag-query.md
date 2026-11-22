# Boolean tag queries

`vigilia --tag-query 'tutorial AND ci:regression'` selects using a Boolean expression.
`--tag-query` cannot be combined with repeatable `--tags` (which retains OR
semantics for existing CI profiles). Tag names are case-sensitive. Operators
`NOT`, `AND`, `OR` are case-insensitive and associate with precedence
`NOT > AND > OR`. Parentheses group expressions. Quote unusual tag names,
including a tag literally named `AND`, inside the expression.

Examples:

```sh
bin/vigilia --tag-query 'tutorial AND ci:regression' --show-command-tests
bin/vigilia --tag-query '(manual OR tutorial) AND NOT deprecated' --show-command-tests
bin/vigilia --tags ci:smoke --show-modules
```

`NOT` is set complement, not an exclusion list: a test without the named tag
also satisfies `NOT tag`. A query using only negation can select a broad set of
tests. Preview selection with inspection flags before execution.

## Hierarchical effective tags

Boolean queries evaluate **effective tags of each command test**, rather
than requiring every parent to match the expression separately:

- Bare tags such as `tutorial`, `manual` and `security` are **additive** along
  `module -> command definition -> command test`. A command can inherit
  `tutorial` while specifying its own `ci:regression` tag.
- Namespaced tags such as `ci:smoke` and `ci:regression` are **overridden as a
  group** when a child explicitly specifies any `ci:` tag. The same rule
  applies to any namespace prefix followed by `:` (for example `level:`).
  No child `ci:` tag means the inherited CI classifications remain in effect.
- A matching leaf selects its containing command and module, even if the
  module's own tags do not independently match the query.
- Only a selected, enabled assertion permits a command to start. If all its
  assertions are excluded, its command and module preparation are not run.
- Disabled/error-marked definitions and their descendants cannot be selected.
- The query mode uses an **AND/OR/NOT expression on effective tags**. The
  existing repeatable `--tags` option is unchanged: OR matching applies to
  each tagged element, and explicitly tagged children narrow the selection.

Example:

```yaml
name: tutorial-example.t
tags: [tutorial, ci:smoke, ci:regression]
command_definitions:
  - description: Basic example
    command: /bin/true
    command_tests:
      - description: Basic assertion
        exit_code: 0
  - description: Extended example
    tags: [ci:regression]
    command: /bin/true
    command_tests:
      - description: Extended assertion
        exit_code: 0
```

`--tag-query 'tutorial AND ci:smoke'` selects only the basic example;
`--tag-query 'tutorial AND ci:regression'` selects both examples.
The regression-only command does **not** inherit `ci:smoke` from its parent.

Bare tags have no built-in subtractive override: a child cannot remove an
inherited `tutorial` tag without a future explicit exclusion mechanism.
`NOT` may include untagged tests, so use inspection (`--show-command-tests`)
for unfamiliar queries before execution. For automated CI, the established
`--tags ci:smoke` and `--tags ci:regression` profiles remain unchanged.

The native report records the expression under `global.selection.tag_query`
and identifies the evaluated hierarchy as `effective-tags-v1`.
