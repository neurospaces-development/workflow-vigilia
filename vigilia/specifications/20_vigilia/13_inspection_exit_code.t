---
name: 20_vigilia/13_inspection_exit_code.t
description: Runtime exit code assertions and non-executing inspection modes
documentation:
  purpose: Prevent runtime assertions from being evaluated during documentation or inspection.
  explanation: |
    An isolated test library contains matching, mismatching and unavailable
    exit code assertions. Inspection must leave the tested commands unexecuted,
    while actual execution must continue to enforce exit code assertions.
command_definitions:
  - description: Exercise inspection and runtime exit code semantics
    command: bash vigilia/specifications/20_vigilia/13_inspection_exit_code.bash
    command_tests:
      - description: Do inspection and execution retain distinct exit code semantics?
        exit_code: 0
        timeout: 180
