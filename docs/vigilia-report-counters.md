# `vigilia` native report counters

The report at `global.test_counters` distinguishes **discovery**, **static
selection**, **processing**, and **actual runtime execution**. The previous
`expected_totals` field remains available for existing report consumers.

| Field | Meaning |
|---|---|
| `discovered_totals` | All module/command/test definitions loaded after the module filename/regex filter, before tags and disabled/error flags. |
| `expected_totals` | **Legacy alias of `discovered_totals`**; deprecated for interpreting profile coverage. Its values are unchanged. |
| `selected_totals` | Statically eligible elements after module/command/test tag selection, disabled/error flags and the no-selected-assertions command gate. |
| `current` | Live count of definitions **processed** by the engine; includes inspection formatters and is not necessarily an executed count. |
| `processed_totals` | Snapshot of `current` at completion, including inspections. |
| `executed_totals` | Snapshot of runtime executor processing; zero for `--show-modules`, other inspection formatters, and documentation output. |

`global.selection` records `regex_selector` and `requested_tags`.
`global.counter_semantics` is included in the report for machine-readable
interpretation. `global.status` remains `Finished` only for completed runs.

The distinction matters for tagged CI profiles. For example, `--tags ci:smoke`
may statically select one test although the library contains many more. A
non-executing `--show-modules` report can have `current.command_test: 1` but
`executed_totals.command_test: 0`. The CI quality gate should inspect
`executed_totals.command_test`, in addition to status and error count.

`selected_totals` is a prediction, not a guarantee of execution: runtime
preparation, context restrictions or failures can prevent a selected test from
running. Do not require the final `current` to equal `selected_totals` in all
modes. No count should be inferred as a success count: use `error_count` and
individual reports for outcomes.

Because `expected_totals` is retained as an alias, existing consumers can
continue reading it, but new clients should use `discovered_totals` and
`selected_totals` explicitly.
