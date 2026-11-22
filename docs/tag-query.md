# Boolean tag queries

`vigilia --tag-query '"'"'tutorial AND ci:regression'"'"'` selects using a Boolean expression.
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

Patch 0022 introduces the parser and local Boolean evaluation. Patch 0023
provides effective-tag inheritance across nested specifications and defines
namespace overrides for safe CI filtering. See the hierarchical section added
by that patch.
