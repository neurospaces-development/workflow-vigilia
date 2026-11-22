---
name: 20_vigilia/15_tag_query.t
description: Boolean tag-query parsing and precedence
tags:
  - ci:regression
documentation:
  purpose: Verify Boolean tag expressions used to select test and documentation knowledge.
command_definitions:
  - description: Exercise tag-query operator precedence and diagnostics
    command: bash vigilia/specifications/20_vigilia/15_tag_query.bash
    command_tests:
      - description: Do Boolean tag expressions select the correct test modules?
        exit_code: 0
        timeout: 150
