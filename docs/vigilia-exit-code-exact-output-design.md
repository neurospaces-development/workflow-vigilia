# Vigilia exit-code and exact-output patch proposal

## Outcome

The accompanying patch adds two independent assertions that can also be used together:

```yaml
command_tests:
  - description: command emits exactly two lines and succeeds
    read:
      exact: |
        first line
        second line
    exit_code: 0
```

`read.exact` compares the complete remaining pseudo-terminal stream. Because `Expect` uses a PTY, that stream contains both STDOUT and STDERR. `exit_code` accepts an integer from 0 through 255 and waits for the tested process to terminate.

## Changes in the patch

- Adds a shared `wait_for_command_completion()` helper. It reads until EOF (or timeout), returns the remaining PTY output, captures the status stored by `Expect`, and clears the global process state.
- Adds `check_exit_code()` after the command-test-specific output assertion. This permits `read` and `exit_code` in the same command test.
- Adds an `ExitCode` command-test class so a test containing only `exit_code` still performs write/wait processing and returns a valid result object.
- Adds an `Exact` command-test class selected by `read: { exact: ... }`. It waits for EOF and uses Perl string equality instead of asking `Expect` to find a substring.
- Marks the exact comparison as final so the existing numerical/approximate comparator cannot turn an exact mismatch into a pass.
- Prefixes exit-code-only difference values with `Wrong exit_code: `. The existing reporter then automatically propagates the prefix into `010_expected.txt.raw`, `020_seen.txt.raw`, their normalized counterparts, and `030_expected-minus-seen.diff`.
- Clears `$global_exp` and `$global_running_command_definition` whenever the process is closed, preventing a reaped `Expect` object from being reused.

For a command expected to return 0 but actually returning 1, the raw report files contain:

```text
010_expected.txt.raw: Wrong exit_code: 0
020_seen.txt.raw:     Wrong exit_code: 1
```

Signal termination is reported as, for example, `Wrong exit_code: signal 9`; an unavailable status is reported as `Wrong exit_code: exit status unavailable`.

## Design rationale

The ordinary scalar `read` assertion retains its current semantics: it succeeds when `Expect` finds the literal somewhere in the stream. Changing it to whole-stream equality would silently break existing specifications. Whole-stream comparison therefore has explicit syntax.

The EOF helper is shared because both assertions need the same terminal operation: drain the PTY, reap the process, and retain the status. An exact-output assertion stores the raw status in its result; a simultaneous `exit_code` assertion reuses it rather than waiting a second time.

The status is decoded as a Perl/POSIX wait status (`signal = status & 127`, core flag `status & 128`, exit code `status >> 8`). This matches the `Expect` implementation, which stores Perl's raw `$?` value in `exp_Exit`. The `Expect` documentation also explicitly supports calling `expect($timeout)` without patterns to read until EOF or timeout:

- https://metacpan.org/pod/Expect#I-just-want-to-read-the-output-of-a-process-without-expect()ing-anything.-How-can-I-do-this?
- https://github.com/jacoby/expect.pm/blob/master/lib/Expect.pm

Exact output is necessarily terminating: equality cannot be established while more output may still arrive. It should therefore be the first and final output assertion for a process, and normally the final command test. Interactive prompt-by-prompt checks should continue to use the existing literal or regular-expression forms.

## Suggested acceptance tests

| Case | Expected result |
| --- | --- |
| Expected and actual exit code are 0 | Pass |
| Expected and actual nonzero code are equal | Pass |
| Expected 0, actual 1 | One failure; prefixed expected/seen/diff artifacts |
| Process is terminated by a signal | Failure naming the signal |
| Exact output is equal, including final newline | Pass |
| Actual output has an extra byte or line | Exact-output failure |
| Exact output matches but exit code differs | Exit-code failure with prefixed artifacts |
| Both exact output and exit code differ | One combined error; output remains the primary diff |
| Process does not terminate before timeout | Failure and forced cleanup |
| `exit_code` is outside 0..255 or not an integer | Specification failure |

## Remaining implementation questions

1. **Specification syntax.** The proposal uses `read: { exact: ... }` to preserve scalar `read` compatibility. This should be accepted as the stable public syntax before many specifications adopt it.

2. **Meaning of “complete.”** The patch compares the complete *remaining* PTY stream. If exact matching must work after earlier prompt matches, Vigilia needs a separate transcript buffer that is never consumed by `Expect` matches.

3. **STDOUT versus PTY output.** `Expect` combines STDOUT and STDERR on its pseudo-terminal. A true STDOUT-only assertion would require separate pipes or another execution backend.

4. **Whitespace policy.** Existing `white_space: ignore` behavior is marked as non-working in the script. The proposal does not redefine it. A decision is needed whether `read.exact` must reject all whitespace normalization or mean equality after an explicitly requested normalization.

5. **Two failures in one command test.** When output and exit code both differ, the patch appends both explanations to the error but keeps the output comparison in the single expected/seen artifact pair. Producing two independently indexed failures would require the result/reporting interface to support multiple assertions per command test.

6. **Expected signals.** The proposal treats every signal termination as failure. If signal termination is a legitimate outcome, add a separate assertion such as `signal: TERM` instead of overloading `exit_code`.

7. **Platform scope.** The status decoding is appropriate for the current Unix/Linux PTY model. Supporting non-POSIX platforms should use a platform-specific status abstraction.

## Verification status

The consolidated patch applies cleanly to the supplied `vigilia` source. Its control flow and report propagation were reviewed against the supplied reporter implementation and the upstream `Expect` documentation/source. A full `perl -c` and runtime test could not be executed in the isolated workspace because the application dependency `Data::Transformator` (and the complete project environment) is not present. The acceptance cases above should be added to the project's normal Vigilia test suite before merging.
