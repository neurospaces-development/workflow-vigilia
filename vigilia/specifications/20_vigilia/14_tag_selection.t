---
tags:
  - ci:regression
name: 20_vigilia/14_tag_selection.t
description: Hierarchical tag selection for execution, inspection, manuals and tutorials
documentation:
  purpose: Verify generic tags across test execution and documentation inspection.
  explanation: |
    Module tags select collections of tests. Untagged descendants inherit
    their parent's selection. Explicit command and assertion tags restrict
    the selection. Tags such as manual and tutorial are independent of the
    CI-specific ci:smoke and ci:regression classifications.
command_definitions:
  - description: Verify tag selection using an isolated suite
    command: bash vigilia/specifications/20_vigilia/14_tag_selection.bash
    command_tests:
      - description: Do hierarchical tags select tests without unintended commands?
        exit_code: 0
        timeout: 120
