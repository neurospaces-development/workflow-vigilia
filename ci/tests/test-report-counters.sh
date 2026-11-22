#!/usr/bin/env bash
# Validate report semantics against real execution and non-executing inspection.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
root=$(mktemp -d "${TMPDIR:-/tmp}/vigilia-report-counters.XXXXXX")
trap 'rm -rf -- "$root"' EXIT
export NEUROSPACES_HARNESS_OPTION_EMAIL=0

bin/vigilia --console-type linear --tags ci:smoke \
  --regex-selector '20_vigilia/13_inspection_exit_code\.module\.yml$' \
  --reporting-directory "$root/execution" > "$root/execution.log" 2>&1

bin/vigilia --console-type linear --tags ci:regression \
  --show-modules \
  --reporting-directory "$root/inspection" > "$root/inspection.log" 2>&1

perl -MYAML::PP -e '
    for my $mode (qw(execution inspection)) {
        my $report = YAML::PP::LoadFile("$ARGV[0]/$mode/report.yml");
        my $global = $report->{global};
        die "incomplete report\n" unless $global->{status} eq "Finished";
        my $c = $global->{test_counters};
        for my $k (qw(module_definition command_definition command_test)) {
            die "legacy counter changed\n" unless
                $c->{expected_totals}->{$k} == $c->{discovered_totals}->{$k};
            die "processed counter changed\n" unless
                $c->{processed_totals}->{$k} == $c->{current}->{$k};
        }
        my $tests = $mode eq "execution" ? 1 : 13;
        die "incorrect selected test count\n" unless
            $c->{selected_totals}->{command_test} == $tests;
        die "incorrect processed test count\n" unless
            $c->{current}->{command_test} == $tests;
        die "incorrect executed test count\n" unless
            $c->{executed_totals}->{command_test} == ($mode eq "execution" ? $tests : 0);
        die "incorrect requested tags\n" unless
            $global->{selection}->{requested_tags}->[0] eq
                ($mode eq "execution" ? "ci:smoke" : "ci:regression");
        print "PASS $mode: discovered=$c->{discovered_totals}->{command_test} "
            . "selected=$c->{selected_totals}->{command_test} "
            . "processed=$c->{current}->{command_test} "
            . "executed=$c->{executed_totals}->{command_test}\n";
    }
' "$root"
echo 'Native report counter regression tests passed.'
