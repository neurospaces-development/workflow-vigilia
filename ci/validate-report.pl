#!/usr/bin/env perl
use strict;
use warnings;
use YAML::PP ();

@ARGV == 1 or die "Usage: $0 REPORT.yml\n";
my ($filename) = @ARGV;
-f $filename && -s $filename or die "Missing or empty report: $filename\n";

my $report = YAML::PP::LoadFile($filename);
ref($report) eq 'HASH' or die "Invalid report root\n";
my $global = $report->{global};
ref($global) eq 'HASH' or die "Missing global report data\n";
my $counters = $global->{test_counters};
ref($counters) eq 'HASH' or die "Missing test counters\n";
my $current = $counters->{current};
ref($current) eq 'HASH' or die "Missing current test counters\n";

my $status = $global->{status};
my $tests = $current->{command_test};
my $errors = $global->{error_count};

defined($status) && !ref($status) && $status eq 'Finished'
    or die "Report does not describe a finished test run\n";
for my $counter ([$tests, 'command_test'], [$errors, 'error_count']) {
    defined($counter->[0]) && !ref($counter->[0]) && $counter->[0] =~ /\A[0-9]+\z/
        or die "Missing or invalid counter: $counter->[1]\n";
}

printf "Status: %s\nTests:  %s\nErrors: %s\n", $status, $tests, $errors;
$tests > 0 or die "No command tests executed\n";
$errors == 0 or die "Regression tests reported errors\n";
