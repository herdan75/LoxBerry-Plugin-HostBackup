package HostBackupFixture;
use strict;
use warnings;
use JSON::PP;
# Renderer only: intercept every process request, never invoke real sudo/backend.
BEGIN {
  # Repair only the generic identity stub, never replace a real CGI module in
  # Linux CI. A browser needs correct escaping, especially JSON in data-*.
  require CGI;
  no warnings 'redefine';
  if (CGI::escapeHTML('"') eq '"') {
    *CGI::escapeHTML = sub {
      my $value = defined $_[0] ? $_[0] : '';
      $value =~ s/&/&amp;/g;
      $value =~ s/</&lt;/g;
      $value =~ s/>/&gt;/g;
      $value =~ s/"/&quot;/g;
      $value =~ s/'/&#39;/g;
      return $value;
    };
  }
  *CORE::GLOBAL::readpipe = sub {
    my ($command) = @_;
    $? = 0;
    if ($command =~ /'config'\s+2>&1$/) {
      my $mode = $ENV{HOSTBACKUP_FIXTURE_METADATA} || 'native-strict';
      die 'Invalid fixture metadata mode' unless $mode =~ /^(?:native-strict|portable-archive|network-compatible|fake-super)$/;
      return JSON::PP::encode_json({backup_root=>'/fixture/backup',keep_backups=>3,backup_mode=>'snapshot',metadata_mode=>$mode,root_permission_ack=>JSON::PP::true,schedule_enabled=>JSON::PP::false,schedule_mode=>'daily',schedule_time=>'02:00',schedule_weekdays=>['1'],schedule_monthdays=>['1'],schedule_months=>['*'],stop_targets=>['systemd:test.service'],rsync_extra_excludes=>['/fixture/backup/***']});
    }
    return '[]' if $command =~ /'(?:targets|backup-targets|list|stop-targets)'\s+2>&1$/;
    die "Fixture refused subprocess: $command";
  };
}
1;
