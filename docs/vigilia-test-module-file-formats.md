# Test module file formats

`vigilia` recognizes three module source formats:

- **Perl module:** `*.t`. This suffix identifies executable Perl
  definitions. A YAML document stored under `.t` is reported as a test library
  error, including when the offending module is outside the active regex/tag
  selection. The historical JSON-in-`.t` loader branch is unchanged by this
  migration and should be addressed separately if strict JSON naming is
  desired.
- **Standalone YAML module:** `*.module.yml`. This is a complete YAML mapping
  containing module metadata and an inline `command_definitions` array.
- **File-structured YAML module:** `<module>/summary.yml` plus YAML command
  definitions under `<module>/command_definitions/`.

The standalone YAML suffix is deliberately distinct from the file-structured
module `summary.yml`, so the discovery logic does not accidentally treat YAML
command-definition files as top-level modules.

All three formats participate in the same `--tags` and `--tag-query` selectors
and may be included in CI/CD and documentation generation. A malformed module
must be corrected rather than hidden by a test profile.
