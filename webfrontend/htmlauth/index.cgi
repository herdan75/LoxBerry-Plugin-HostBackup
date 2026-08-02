#!/usr/bin/perl
use strict;
use warnings;
use CGI qw(:standard escapeHTML);
use File::Temp qw(tempfile);
use File::Basename qw(basename);
use File::Path qw(make_path);
use JSON::PP;
use Encode qw(encode);
use Digest::SHA qw(hmac_sha256_hex);
use Fcntl qw(:DEFAULT :flock);
use LoxBerry::Web;

my $plugin = 'loxberryhostbackup';
my $lbhome = $ENV{LBHOMEDIR} || '/opt/loxberry';
my $bindir = $ENV{LBPBINDIR} || "$lbhome/bin/plugins/$plugin";
my $datadir = $ENV{LBPDATADIR} || $ENV{LBPDATA} || "$lbhome/data/plugins/$plugin";
my $backend = $ENV{HOSTBACKUP_SUDO_DISPATCHER} || '/usr/local/sbin/loxberryhostbackup-sudo';
my $q = CGI->new;
my $csrf_token = '';
my $MAX_CONFIG_UPLOAD = 1024 * 1024;
my $MAX_BACKUP_UPLOAD = 64 * 1024 * 1024 * 1024;

my $action = $q->param('action') || '';
my $backup_id = $q->param('backup_id') || '';
my $browse_path = $q->param('path') || '';
my $task = $q->param('task') || '';
my $restore_id = $q->param('restore_id') || '';
my $browse_id = $q->param('browse_id') || '';

my $message = '';
my $error = '';
my $preflight_warning = '';
my $active_task = '';

sub url_escape {
  my ($value) = @_;
  $value //= '';
  my $bytes = encode('UTF-8', $value);
  $bytes =~ s/([^A-Za-z0-9_.~-])/sprintf("%%%02X", ord($1))/ge;
  return $bytes;
}

sub secure_random_hex {
  open my $fh, '<:raw', '/dev/urandom' or die "Zufallsquelle nicht verfuegbar: $!";
  my $bytes = '';
  my $read = read($fh, $bytes, 32);
  close $fh;
  die "Zufallsquelle konnte nicht gelesen werden" unless defined $read && $read == 32;
  return unpack('H*', $bytes);
}

sub csrf_secret {
  my $path = "$datadir/csrf-secret";
  die "Unsicheres Plugin-Datenverzeichnis" if -l $datadir;
  make_path($datadir, { mode => 0700 }) unless -d $datadir;
  die "Plugin-Datenverzeichnis fehlt" unless -d $datadir && !-l $datadir;
  die "Unsicherer CSRF-Secret-Pfad" if -l $path;
  if (-e $path && (!-f $path || -l $path)) {
    die "Unsicherer CSRF-Secret-Dateityp";
  }
  if (-f $path && -r $path) {
    open my $fh, '<', $path or die "CSRF-Secret nicht lesbar: $!";
    my $secret = <$fh> // '';
    close $fh;
    chomp $secret;
    return $secret if $secret =~ /^[a-f0-9]{64}$/;
    die "CSRF-Secret ist beschaedigt";
  }
  my $secret = secure_random_hex();
  my $tmp = "$path.$$";
  sysopen(my $fh, $tmp, O_WRONLY | O_CREAT | O_EXCL, 0600) or die "CSRF-Secret kann nicht angelegt werden: $!";
  print {$fh} "$secret\n" or die "CSRF-Secret kann nicht geschrieben werden: $!";
  close $fh or die "CSRF-Secret kann nicht geschlossen werden: $!";
  chmod 0600, $tmp;
  rename $tmp, $path or do { unlink $tmp; die "CSRF-Secret kann nicht aktiviert werden: $!"; };
  return $secret;
}

sub csrf_identity {
  return join('|', $ENV{REMOTE_USER} || '', $ENV{REMOTE_ADDR} || '', $ENV{HTTP_USER_AGENT} || '');
}

sub csrf_for_bucket {
  my ($bucket) = @_;
  return hmac_sha256_hex(csrf_identity() . '|' . $bucket, csrf_secret());
}

sub constant_time_equal {
  my ($left, $right) = @_;
  return 0 unless defined $left && defined $right && length($left) == length($right);
  my $diff = 0;
  for my $index (0 .. length($left) - 1) {
    $diff |= ord(substr($left, $index, 1)) ^ ord(substr($right, $index, 1));
  }
  return $diff == 0;
}

sub same_origin_request {
  my $origin = $ENV{HTTP_ORIGIN} || '';
  return 1 unless length $origin;
  my $scheme = (($ENV{HTTPS} || '') =~ /^(?:on|1)$/i) ? 'https' : 'http';
  my $host = $ENV{HTTP_HOST} || '';
  return constant_time_equal(lc($origin), lc("$scheme://$host"));
}

sub valid_csrf_request {
  my $provided = $q->param('csrf_token') || '';
  return 0 unless same_origin_request();
  my $bucket = int(time() / 3600);
  return constant_time_equal($provided, csrf_for_bucket($bucket))
    || constant_time_equal($provided, csrf_for_bucket($bucket - 1));
}

sub csrf_field {
  my $safe = escapeHTML($csrf_token);
  return qq{<input data-role="none" type="hidden" name="csrf_token" value="$safe">};
}

sub available_bytes {
  my ($path) = @_;
  my $available = 0;
  if (open(my $fh, '-|', 'df', '-PB1', $path)) {
    my @lines = <$fh>;
    close $fh;
    $available = $1 if defined $lines[1] && $lines[1] =~ /^\S+\s+\d+\s+\d+\s+(\d+)/;
  }
  return $available || 0;
}

sub read_upload_limited {
  my ($upload, $limit) = @_;
  my $content = '';
  my $buffer;
  while (1) {
    my $count = read($upload, $buffer, 65536);
    die "Upload konnte nicht gelesen werden" unless defined $count;
    last if $count == 0;
    die "Upload ist groesser als erlaubt" if length($content) + $count > $limit;
    $content .= substr($buffer, 0, $count);
  }
  return $content;
}

$csrf_token = csrf_for_bucket(int(time() / 3600));

sub redirect_with {
  my (%params) = @_;
  my @parts;
  for my $key (sort keys %params) {
    next unless defined $params{$key} && length $params{$key};
    push @parts, url_escape($key) . '=' . url_escape($params{$key});
  }
  my $uri = page_url_without_query();
  $uri .= '?' . join('&', @parts) if @parts;
  print redirect(-uri => $uri);
  exit;
}

sub hidden_active_task {
  return '' unless $active_task;
  my $safe = escapeHTML($active_task);
  return qq{<input data-role="none" type="hidden" name="active_task" value="$safe">};
}

sub url_with_active_task {
  my (%params) = @_;
  $params{active_task} = $active_task if $active_task;
  my @parts;
  for my $key (sort keys %params) {
    next unless defined $params{$key} && length $params{$key};
    push @parts, url_escape($key) . '=' . url_escape($params{$key});
  }
  return '?' . join('&', @parts);
}

sub page_url_without_query {
  my $uri = $ENV{REQUEST_URI} || '';
  $uri =~ s/[?#].*\z//;

  if (!length $uri) {
    $uri = $ENV{SCRIPT_NAME} || $q->url(-relative => 1) || './';
    $uri =~ s/[?#].*\z//;
  }

  return length $uri ? $uri : './';
}

sub base_url_with_active_task {
  my @parts;
  if ($active_task) {
    push @parts, 'active_task=' . url_escape($active_task);
  }
  my $uri = page_url_without_query();
  $uri .= '?' . join('&', @parts) if @parts;
  return $uri;
}

sub shell_quote {
  my ($value) = @_;
  $value =~ s/'/'"'"'/g;
  return "'$value'";
}

sub backend_cmd {
  return 'sudo -n ' . shell_quote($backend) . ' ' . join(' ', map { shell_quote($_) } @_);
}

sub run_shell {
  my ($cmd) = @_;
  my $output = `$cmd 2>&1`;
  my $status = $? >> 8;
  return ($status, $output);
}

sub checked_attr {
  my ($value) = @_;
  return $value ? ' checked' : '';
}

sub bool_arg {
  my ($value) = @_;
  return $value ? 'true' : 'false';
}

sub array_csv {
  my ($value, $default) = @_;
  return $default unless ref($value) eq 'ARRAY' && @$value;
  my @clean = grep { defined $_ && !ref($_) && length $_ } @$value;
  return @clean ? join(',', @clean) : $default;
}

sub stop_targets_csv {
  my ($value) = @_;
  return '' unless ref($value) eq 'ARRAY' && @$value;
  my @clean;
  for my $target (@$value) {
    my ($type, $name);
    if (ref($target) eq 'HASH') {
      $type = $target->{type} || '';
      $name = $target->{name} || '';
    } elsif (!ref($target) && $target =~ /^([^:]+):(.+)$/) {
      ($type, $name) = ($1, $2);
    }
    next unless ($type || '') =~ /^(docker|systemd)$/;
    next unless defined $name && length $name;
    next unless $name =~ /^[A-Za-z0-9_.\@:\-]+(?:\.service)?$/;
    push @clean, "$type:$name";
  }
  return join(',', @clean);
}

sub info_button {
  my ($text) = @_;
  my $safe = escapeHTML($text || '');
  return qq{<span class="info-help"><button data-role="none" type="button" class="info-button" aria-label="Hinweis anzeigen">i</button><span class="info-bubble" role="tooltip">$safe</span></span>};
}

my $notice = $q->param('msg') || '';
if ($notice eq 'saved') {
  $message = 'Einstellungen gespeichert.';
} elsif ($notice eq 'backup_started') {
  $message = 'Backup gestartet. Der Live-Status wird unten automatisch aktualisiert.';
} elsif ($notice eq 'backup_stop_requested') {
  $message = 'Backup-Stopp wurde angefordert. Zuvor gestoppte Docker-Container werden wieder gestartet, falls möglich.';
} elsif ($notice eq 'backup_deleted') {
  $message = 'Backup gelöscht.';
} elsif ($notice eq 'export_deleted') {
  $message = 'Export-Archiv gelöscht. Das Backup selbst bleibt erhalten.';
} elsif ($notice eq 'backup_imported') {
  $message = 'Backup importiert.';
} elsif ($notice eq 'import_started') {
  $message = 'Import gestartet. Der Live-Status wird unten automatisch aktualisiert.';
} elsif ($notice eq 'import_finished') {
  $message = 'Import abgeschlossen. Die Backup-Liste wurde aktualisiert.';
} elsif ($notice eq 'export_started') {
  $message = 'Export gestartet. Der Live-Status wird unten automatisch aktualisiert.';
} elsif ($notice eq 'export_finished') {
  $message = 'Export abgeschlossen. Das Archiv steht in der Backup-Liste zum Download bereit.';
} elsif ($notice eq 'config_imported') {
  $message = 'Einstellungen importiert. Die Root-Freigabe wurde aus Sicherheitsgründen zurückgesetzt und muss erneut bestätigt werden.';
} elsif ($notice eq 'restore_started') {
  $message = 'Restore gestartet. Der Live-Status wird unten automatisch aktualisiert.';
} elsif ($notice eq 'backup_finished') {
  $message = 'Backup abgeschlossen. Die Backup-Liste wurde aktualisiert.';
} elsif ($notice eq 'restore_finished') {
  $message = 'Restore abgeschlossen.';
}

my $requested_active_task = $q->param('active_task') || '';
if ($requested_active_task =~ /^(backup|restore|export|import)-[A-Za-z0-9._-]+\.log$/) {
  $active_task = $requested_active_task;
}

if ($action eq 'task-status') {
  my ($status, $out) = run_shell(backend_cmd('task-status', $task, '90'));
  if ($status != 0 && $task =~ /^backup-([A-Za-z0-9._-]+)\.log$/) {
    ($status, $out) = run_shell(backend_cmd('task-status', "backup-$1.launch.log", '80'));
  } elsif ($status != 0 && $task =~ /^restore-([A-Za-z0-9._-]+)\.log$/) {
    ($status, $out) = run_shell(backend_cmd('task-status', "restore-$1.launch.log", '80'));
  }
  print header(-type => 'application/json', -charset => 'utf-8', -status => ($status == 0 ? '200 OK' : '500 Internal Server Error'));
  if ($status == 0) {
    print $out;
  } else {
    my $safe_error = encode_json({ task => $task, state => 'error', error => $out });
    print $safe_error;
  }
  exit;
}

if ($action eq 'download-config') {
  my ($status, $out) = run_shell(backend_cmd('config'));

  if ($status != 0) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '500 Internal Server Error');
    print $out;
    exit;
  }

  print header(
    -type => 'application/json',
    -attachment => 'loxberryhostbackup-settings.json',
  );
  print $out;
  exit;
}

if ($action eq 'download-export') {
  my $download_id = $q->param('backup_id') || '';

  if ($download_id !~ /^[A-Za-z0-9._-]+$/) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '400 Bad Request');
    print "Ungültige Backup-ID.\n";
    exit;
  }

  my ($status, $out) = run_shell(backend_cmd('export-info', $download_id));

  if ($status != 0) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '500 Internal Server Error');
    print $out;
    exit;
  }

  my $info = eval { decode_json($out) } || {};
  my $archive = $info->{archive} || '';

  if (($info->{status} || '') ne 'available' || !$archive || !-r $archive || !-f $archive || -l $archive) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '404 Not Found');
    print "Export-Archiv ist noch nicht vorhanden oder konnte nicht gelesen werden.\n";
    exit;
  }

  my $filename = basename($archive);
  my $size = -s $archive;

  print header(
    -type => 'application/gzip',
    -attachment => $filename,
    -Content_length => $size,
  );

  open my $fh, '<', $archive or do {
    print "Export-Archiv konnte nicht geöffnet werden.\n";
    exit;
  };
  binmode $fh;
  binmode STDOUT;
  my $buffer;
  while (read($fh, $buffer, 65536)) {
    print $buffer;
  }
  close $fh;
  exit;
}

if ($q->request_method eq 'POST') {
  if (!valid_csrf_request()) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '403 Forbidden');
    print "Ungueltige oder abgelaufene CSRF-Bestaetigung. Seite neu laden.\n";
    exit;
  }

  if ($action eq 'import-config') {

    my $upload = $q->upload('settings_file');

    if (!$upload) {
      $error = 'Keine Einstellungsdatei ausgewählt.';
    } else {
      binmode $upload;
      my $settings_json = eval { read_upload_limited($upload, $MAX_CONFIG_UPLOAD) };
      if ($@) {
        $error = escapeHTML($@);
        $settings_json = '';
      }
      my $imported = eval { decode_json($settings_json) };

      if (!$imported || ref($imported) ne 'HASH') {
        $error ||= 'Einstellungsdatei konnte nicht gelesen werden. Erwartet wird eine JSON-Datei aus diesem Plugin.';
      } else {
        my $backup_root = $imported->{backup_root} || '';
        my $excludes = ref($imported->{rsync_extra_excludes}) eq 'ARRAY' ? join("\n", @{$imported->{rsync_extra_excludes}}) : '';
        my $stop_docker = bool_arg($imported->{stop_docker_before_backup});
        my $create_export = bool_arg($imported->{create_export_after_backup});
        my $keep_backups = $imported->{keep_backups} || '10';
        my $schedule_enabled = bool_arg($imported->{schedule_enabled});
        my $schedule_mode = $imported->{schedule_mode} || 'daily';
        my $schedule_time = $imported->{schedule_time} || '02:00';
        my $schedule_weekdays = array_csv($imported->{schedule_weekdays}, $imported->{schedule_weekday} || '0');
        my $schedule_monthdays = array_csv($imported->{schedule_monthdays}, $imported->{schedule_monthday} || '1');
        my $schedule_months = array_csv($imported->{schedule_months}, '*');
        my @weekdays = split /,/, $schedule_weekdays;
        my @monthdays = split /,/, $schedule_monthdays;
        my $pre_hook = $imported->{pre_backup_hook} || '';
        my $post_hook = $imported->{post_backup_hook} || '';
        my $root_permission_ack = 'false';
        my $backup_mode = $imported->{backup_mode} || 'full';
        my $metadata_mode = $imported->{metadata_mode} || 'native-strict';
        my $stop_targets = stop_targets_csv($imported->{stop_targets});
        my $mail_notify_enabled = bool_arg($imported->{mail_notify_enabled});
        my $mail_notify_to = $imported->{mail_notify_to} || '';
        my $mail_notify_success = exists $imported->{mail_notify_success} ? bool_arg($imported->{mail_notify_success}) : 'true';
        my $mail_notify_failure = exists $imported->{mail_notify_failure} ? bool_arg($imported->{mail_notify_failure}) : 'true';
        my $mail_notify_stopped = exists $imported->{mail_notify_stopped} ? bool_arg($imported->{mail_notify_stopped}) : 'true';
        my $mail_notify_restore = exists $imported->{mail_notify_restore} ? bool_arg($imported->{mail_notify_restore}) : 'true';

        my ($status, $out) = run_shell(
          backend_cmd(
            'save-config',
            $backup_root,
            $excludes,
            $stop_docker,
            $create_export,
            $keep_backups,
            $schedule_enabled,
            $schedule_mode,
            $schedule_time,
            $weekdays[0] || '0',
            $monthdays[0] || '1',
            $schedule_months,
            $schedule_weekdays,
            $schedule_monthdays,
            $pre_hook,
            $post_hook,
            $root_permission_ack,
            $backup_mode,
            $stop_targets,
            $mail_notify_enabled,
            $mail_notify_to,
            $mail_notify_success,
            $mail_notify_failure,
            $mail_notify_stopped,
            $mail_notify_restore,
            $metadata_mode
          )
        );

        if ($status == 0) {
          redirect_with(msg => 'config_imported');
        } else {
          $error = escapeHTML($out);
        }
      }
    }
  }

  elsif ($action eq 'save-config') {

    my $backup_root = $q->param('backup_root') || '';
    my $backup_mode = $q->param('backup_mode') || 'full';
    my $metadata_mode = $q->param('metadata_mode') || 'native-strict';
    my $keep_backups = $q->param('keep_backups') || '10';

    my $schedule_enabled = $q->param('schedule_enabled') ? 'true' : 'false';
    my $schedule_mode = $q->param('schedule_mode') || 'daily';
    my $schedule_time = $q->param('schedule_time') || '02:00';
    my @schedule_weekdays = $q->param('schedule_weekdays');
    @schedule_weekdays = ('0') unless @schedule_weekdays;
    my $schedule_weekdays = join(',', @schedule_weekdays);
    my @schedule_monthdays = $q->param('schedule_monthdays');
    @schedule_monthdays = ('1') unless @schedule_monthdays;
    my $schedule_monthdays = join(',', @schedule_monthdays);
    my @schedule_months = $q->param('schedule_months');
    @schedule_months = ('*') unless @schedule_months;
    my $schedule_months = join(',', @schedule_months);

    my $pre_hook = $q->param('pre_backup_hook') || '';
    my $post_hook = $q->param('post_backup_hook') || '';
    my $excludes = $q->param('rsync_extra_excludes') || '';

    my $stop_docker = $q->param('stop_docker_before_backup') ? 'true' : 'false';
    my $create_export = $q->param('create_export_after_backup') ? 'true' : 'false';
    my $mail_notify_enabled = $q->param('mail_notify_enabled') ? 'true' : 'false';
    my $mail_notify_to = $q->param('mail_notify_to') || '';
    my $mail_notify_success = $q->param('mail_notify_success') ? 'true' : 'false';
    my $mail_notify_failure = $q->param('mail_notify_failure') ? 'true' : 'false';
    my $mail_notify_stopped = $q->param('mail_notify_stopped') ? 'true' : 'false';
    my $mail_notify_restore = $q->param('mail_notify_restore') ? 'true' : 'false';

    my $root_permission_ack = $q->param('root_permission_ack') ? 'true' : 'false';
    my $stop_targets = '';

    if ($q->param('stop_targets_loaded')) {
      my @stop_targets = $q->param('stop_targets');
      $stop_targets = join(',', grep { defined $_ && /^(docker|systemd):[A-Za-z0-9_.\@:\-]+(?:\.service)?$/ } @stop_targets);
    } else {
      my ($current_status, $current_json) = run_shell(backend_cmd('config'));
      if ($current_status == 0) {
        my $current = eval { decode_json($current_json) } || {};
        $stop_targets = stop_targets_csv($current->{stop_targets});
      }
    }

    my ($status, $out) = run_shell(
      backend_cmd(
        'save-config',
        $backup_root,
        $excludes,
        $stop_docker,
        $create_export,
        $keep_backups,
        $schedule_enabled,
        $schedule_mode,
        $schedule_time,
        $schedule_weekdays[0] || '0',
        $schedule_monthdays[0] || '1',
        $schedule_months,
        $schedule_weekdays,
        $schedule_monthdays,
        $pre_hook,
        $post_hook,
        $root_permission_ack,
        $backup_mode,
        $stop_targets,
        $mail_notify_enabled,
        $mail_notify_to,
        $mail_notify_success,
        $mail_notify_failure,
        $mail_notify_stopped,
        $mail_notify_restore,
        $metadata_mode
      )
    );

    if ($status == 0) {
      redirect_with(msg => 'saved');
    } else {
      $error = escapeHTML($out);
    }
  }

  elsif ($action eq 'backup') {
    my $accept_warnings = $q->param('accept_preflight_warnings') ? 'accept-warnings' : '';
    my ($check_status, $check_out) = run_shell(backend_cmd('preflight-backup'));
    my $check = $check_status == 0 ? eval { decode_json($check_out) } : undef;
    if ($check_status != 0 || !$check || (($check->{status} || '') eq 'error')) {
      $error = escapeHTML($check_out || 'Backup-Preflight fehlgeschlagen.');
    } elsif (($check->{status} || '') eq 'warning' && $accept_warnings ne 'accept-warnings') {
      my $warnings = ref($check->{warnings}) eq 'ARRAY' ? join("\n", @{$check->{warnings}}) : 'Preflight meldet Warnungen.';
      $preflight_warning = escapeHTML($warnings);
    } else {
      my ($status, $out) = run_shell(backend_cmd('start', '', $accept_warnings));
      if ($status == 0) {
        my ($started_id) = $out =~ /([A-Za-z0-9._-]+)/;
        if ($started_id) {
          $active_task = "backup-$started_id.log";
          redirect_with(msg => 'backup_started', active_task => $active_task);
        }
        redirect_with(msg => 'backup_started');
      } else {
        $error = escapeHTML($out);
      }
    }
  }

  elsif ($action eq 'stop-backup') {

    my $stop_task = $q->param('task') || '';
    my ($stop_id) = $stop_task =~ /^backup-([A-Za-z0-9._-]+)\.log$/;

    if (!$stop_id) {
      $error = 'Ungültiger Backup-Task.';
    } else {
      my ($status, $out) = run_shell(backend_cmd('stop', $stop_id));

      if ($status == 0) {
        redirect_with(msg => 'backup_stop_requested', active_task => $stop_task);
      } else {
        $error = escapeHTML($out);
      }
    }
  }

  elsif ($action eq 'delete-backup') {

    my $delete_id = $q->param('backup_id') || '';

    if ($delete_id !~ /^[A-Za-z0-9._-]+$/) {
      $error = 'Ungültige Backup-ID.';
    } else {
      my ($status, $out) = run_shell(backend_cmd('delete', $delete_id));

      if ($status == 0) {
        redirect_with(msg => 'backup_deleted');
      } else {
        $error = escapeHTML($out);
      }
    }
  }

  elsif ($action eq 'delete-export') {

    my $delete_export_id = $q->param('backup_id') || '';

    if ($delete_export_id !~ /^[A-Za-z0-9._-]+$/) {
      $error = 'Ungültige Backup-ID.';
    } else {
      my ($status, $out) = run_shell(backend_cmd('delete-export', $delete_export_id));

      if ($status == 0) {
        redirect_with(msg => 'export_deleted');
      } else {
        $error = escapeHTML($out);
      }
    }
  }

  elsif ($action eq 'start-export') {

    my $export_id = $q->param('backup_id') || '';

    if ($export_id !~ /^[A-Za-z0-9._-]+$/) {
      $error = 'Ungültige Backup-ID.';
    } else {
      my ($status, $out) = run_shell(backend_cmd('start-export', $export_id));

      if ($status == 0) {
        my ($task_id) = $out =~ m{^([A-Za-z0-9._-]+\.log)\s*$}m;
        $task_id ||= "export-$export_id.log";
        redirect_with(msg => 'export_started', active_task => $task_id);
      } else {
        $error = escapeHTML($out);
      }
    }
  }

  elsif ($action eq 'import') {

    my $upload = $q->upload('backup_archive');

    if (!$upload) {
      $error = 'Keine Backup-Datei ausgewählt.';
    } else {
      my $import_dir = "$datadir/imports";
      if (-l $import_dir) {
        $error = 'Das Import-Verzeichnis ist unsicher und darf kein symbolischer Link sein.';
      } else {
        make_path($import_dir, { mode => 0700 }) unless -d $import_dir;
        chmod 0700, $import_dir;
        $error = 'Das Import-Verzeichnis konnte nicht sicher angelegt werden.' unless -d $import_dir && !-l $import_dir;
      }
      if (!$error) {
      my $original_name = basename($q->param('backup_archive') || 'backup.tar.gz');
      $original_name =~ s/[^A-Za-z0-9._-]+/_/g;
      $original_name = 'backup.tar.gz' unless length $original_name;
      my ($fh, $tmpfile) = tempfile('hostbackup-import-XXXXXX-', SUFFIX => "-$original_name", DIR => $import_dir, UNLINK => 0);
      binmode $upload;
      binmode $fh;
      chmod 0600, $tmpfile;

      my $declared_length = $ENV{CONTENT_LENGTH} || 0;
      my $available = available_bytes($import_dir);
      my $reserve = 512 * 1024 * 1024;
      if ($declared_length =~ /^\d+$/ && $declared_length > $MAX_BACKUP_UPLOAD) {
        $error = 'Backup-Upload ist größer als das erlaubte Limit.';
      } elsif ($available && $available <= $reserve) {
        $error = 'Für den Backup-Upload ist nicht genügend freier Speicher verfügbar.';
      } else {
        my $total = 0;
        my $buffer;
        while (!$error) {
          my $count = read($upload, $buffer, 1024 * 1024);
          if (!defined $count) {
            $error = 'Backup-Upload konnte nicht gelesen werden.';
            last;
          }
          last if $count == 0;
          $total += $count;
          if ($total > $MAX_BACKUP_UPLOAD || ($available && $total + $reserve > $available)) {
            $error = 'Backup-Upload überschreitet das Größen- oder Speicherlimit.';
            last;
          }
          my $offset = 0;
          while ($offset < $count) {
            my $written = syswrite($fh, $buffer, $count - $offset, $offset);
            if (!defined $written || $written == 0) {
              $error = 'Backup-Upload konnte nicht vollständig gespeichert werden.';
              last;
            }
            $offset += $written;
          }
        }
      }

      if (!close $fh) {
        $error ||= 'Backup-Upload konnte nicht abgeschlossen werden.';
      }

      if ($error) {
        unlink $tmpfile;
      } else {
        my ($status, $out) = run_shell(backend_cmd('start-import', $tmpfile));

        if ($status == 0) {
          my ($task_id) = $out =~ m{^([A-Za-z0-9._-]+\.log)\s*$}m;
          $task_id ||= '';
          redirect_with(msg => 'import_started', active_task => $task_id);
        } else {
          unlink $tmpfile;
          $error = escapeHTML($out);
        }
      }
      }
    }
  }

  elsif ($action eq 'restore-backup') {

    my $restore_backup_id = $q->param('backup_id') || '';
    my $confirm_restore = $q->param('confirm_restore') ? 1 : 0;
    my $restore_challenge = $q->param('restore_challenge') || '';
    my $confirm_degraded = $q->param('confirm_degraded') ? 'confirm-degraded' : '';

    if ($restore_backup_id !~ /^[A-Za-z0-9._-]+$/) {
      $error = 'Ungültige Backup-ID.';
    } elsif (!$confirm_restore) {
      $error = 'Restore muss ausdrücklich bestätigt werden.';
    } elsif ($restore_challenge ne $restore_backup_id) {
      $error = 'Zur Bestätigung muss die vollständige Backup-ID eingegeben werden.';
    } else {
      my ($check_status, $check_out) = run_shell(backend_cmd('preflight-restore', $restore_backup_id));
      my $check = $check_status == 0 ? eval { decode_json($check_out) } : undef;

      if ($check_status != 0 || !$check || (($check->{status} || '') eq 'error')) {
        $error = escapeHTML($check_out || 'Restore-Check fehlgeschlagen.');
      } elsif ($check->{requires_offline_restore}) {
        $error = 'Portable Archive kann nicht aus der Weboberfläche wiederhergestellt werden. Bitte Rescue-/Offline-Helper verwenden.';
      } elsif ($check->{requires_degraded_confirmation} && $confirm_degraded ne 'confirm-degraded') {
        $error = 'Vor dem Restore muss der Hinweis zu den bewusst ausgelassenen Metadaten bestätigt werden.';
      } else {
        my ($status, $out) = run_shell(backend_cmd('start-restore', $restore_backup_id, $confirm_degraded));

        if ($status == 0) {
          redirect_with(msg => 'restore_started', active_task => "restore-$restore_backup_id.log");
        } else {
          $error = escapeHTML($out);
        }
      }
    }
  }
}

my ($config_status, $config_json) = run_shell(backend_cmd('config'));

my $config = {};
my $config_loaded = 0;

if ($config_status == 0) {
  my $decoded = eval { decode_json($config_json) };
  if ($decoded && ref($decoded) eq 'HASH') {
    $config = $decoded;
    $config_loaded = 1;
  } else {
    $error ||= 'Die Plugin-Konfiguration ist beschädigt und wurde nicht mit Standardwerten überschrieben.';
  }
} else {
  $error ||= escapeHTML($config_json || 'Die Plugin-Konfiguration konnte nicht geladen werden.');
}

if ($restore_id !~ /^[A-Za-z0-9._-]+$/) {
  $restore_id = '';
}

if ($browse_id !~ /^[A-Za-z0-9._-]+$/) {
  $browse_id = '';
}

if ($browse_path =~ m{(^/|(^|/)\.\.(/|$))}) {
  $browse_path = '';
}

my $restore_check = undef;
my $restore_plan = '';
my $restore_error = '';

if ($restore_id) {
  my ($check_status, $check_json) = run_shell(backend_cmd('preflight-restore', $restore_id));
  if ($check_status == 0) {
    $restore_check = eval { decode_json($check_json) };
  } else {
    $restore_error = escapeHTML($check_json);
  }

  my ($plan_status, $plan_text) = run_shell(backend_cmd('restore-plan', $restore_id));
  if ($plan_status == 0) {
    $restore_plan = escapeHTML($plan_text);
  } elsif (!$restore_error) {
    $restore_error = escapeHTML($plan_text);
  }
}

my $browse_data = undef;
my $browse_error = '';

if ($browse_id) {
  my ($browse_status, $browse_json) = run_shell(backend_cmd('browse', $browse_id, $browse_path));
  if ($browse_status == 0) {
    $browse_data = eval { decode_json($browse_json) };
  } else {
    $browse_error = escapeHTML($browse_json);
  }
}

my $cfg_backup_root = escapeHTML($config->{backup_root} || '');
my $cfg_backup_mode = $config->{backup_mode} || 'full';
my $cfg_metadata_mode = $config->{metadata_mode} || 'native-strict';
$cfg_metadata_mode = 'native-strict' unless $cfg_metadata_mode =~ /^(?:native-strict|network-compatible|fake-super|portable-archive)$/;
my $cfg_keep = escapeHTML($config->{keep_backups} || '10');
my $cfg_pre_hook = escapeHTML($config->{pre_backup_hook} || '');
my $cfg_post_hook = escapeHTML($config->{post_backup_hook} || '');
my $cfg_excludes = escapeHTML(join "\n", @{$config->{rsync_extra_excludes} || []});

my $cfg_create_export = checked_attr($config->{create_export_after_backup});
my $cfg_mail_notify_enabled = checked_attr($config->{mail_notify_enabled});
my $cfg_mail_notify_to = escapeHTML($config->{mail_notify_to} || '');
my $cfg_mail_notify_success = checked_attr(exists $config->{mail_notify_success} ? $config->{mail_notify_success} : 1);
my $cfg_mail_notify_failure = checked_attr(exists $config->{mail_notify_failure} ? $config->{mail_notify_failure} : 1);
my $cfg_mail_notify_stopped = checked_attr(exists $config->{mail_notify_stopped} ? $config->{mail_notify_stopped} : 1);
my $cfg_mail_notify_restore = checked_attr(exists $config->{mail_notify_restore} ? $config->{mail_notify_restore} : 1);
my $cfg_schedule_enabled = checked_attr($config->{schedule_enabled});
my $cfg_root_permission_ack = checked_attr($config->{root_permission_ack});

my $cfg_schedule_time = escapeHTML($config->{schedule_time} || '02:00');
my $active_task_attr = escapeHTML($active_task);
my $config_action_disabled = $config_loaded ? '' : ' disabled aria-disabled="true"';

my $cfg_mode = $config->{schedule_mode} || 'daily';

my $daily_checked = $cfg_mode eq 'daily' ? ' checked' : '';
my $weekly_checked = $cfg_mode eq 'weekly' ? ' checked' : '';
my $monthly_checked = $cfg_mode eq 'monthly' ? ' checked' : '';
my $full_mode_checked = $cfg_backup_mode eq 'snapshot' ? '' : ' checked';
my $snapshot_mode_checked = $cfg_backup_mode eq 'snapshot' ? ' checked' : '';
my $native_strict_checked = $cfg_metadata_mode eq 'native-strict' ? ' checked' : '';
my $network_compatible_checked = $cfg_metadata_mode eq 'network-compatible' ? ' checked' : '';
my $fake_super_checked = $cfg_metadata_mode eq 'fake-super' ? ' checked' : '';
my $portable_archive_checked = $cfg_metadata_mode eq 'portable-archive' ? ' checked' : '';
my @cfg_weekdays = ref($config->{schedule_weekdays}) eq 'ARRAY' ? @{$config->{schedule_weekdays}} : ($config->{schedule_weekday} || '0');
my %cfg_weekdays = map { $_ => 1 } @cfg_weekdays;
my @weekday_checked = map { checked_attr($cfg_weekdays{"$_"}) } 0..6;
my @cfg_monthdays = ref($config->{schedule_monthdays}) eq 'ARRAY' ? @{$config->{schedule_monthdays}} : ($config->{schedule_monthday} || '1');
my %cfg_monthdays = map { $_ => 1 } @cfg_monthdays;
my @monthday_checked = map { checked_attr($cfg_monthdays{"$_"}) } 0..31;
my @cfg_months = ref($config->{schedule_months}) eq 'ARRAY' ? @{$config->{schedule_months}} : ('*');
my %cfg_months = map { $_ => 1 } @cfg_months;
my $all_months_checked = checked_attr($cfg_months{'*'});
my @month_checked = map { checked_attr($cfg_months{'*'} || $cfg_months{"$_"}) } 0..12;

my $info_backup_root = info_button('Hier legst du fest, wohin die Backups geschrieben werden. Für ein echtes Host-Backup sollte das ein externer Datenträger, ein separates Mount oder ein grosser zweiter Datenspeicher sein. Erkannte Ziele können per Klick oder Drag und Drop übernommen werden. Wenn die Systemkarte selbst ausfällt, hilft ein Backup auf derselben Karte nicht.');
my $info_backup_mode = info_button('Vollbackup kopiert jeden Stand vollständig. Inkrementeller Snapshot nutzt rsync mit Hardlinks auf das vorherige vollständige Backup: jedes Backup bleibt einzeln wiederherstellbar, unveränderte Dateien benötigen aber kaum zusätzlichen Speicher. Für zuverlässige Speicherersparnis wird ein Linux-Dateisystem wie ext4 empfohlen.');
my $info_metadata_mode = info_button('Das Metadaten-Profil bestimmt, wie Linux-Dateirechte und Zusatzinformationen auf dem Backup-Ziel abgelegt werden. Standard ist Native Strict. Für CIFS/NFS und viele NAS-Systeme ist meistens Network Compatible passend. Die vier Info-Buttons erklären Umfang, Voraussetzungen und Restore-Einschränkungen jedes Profils.');
my $info_metadata_native = info_button('Standardprofil bei einer Neuinstallation. Native Strict verwendet rsync mit -aHAX, numerischen Benutzer- und Gruppen-IDs sowie Sparse-Dateien. Gesichert werden Dateien, Verzeichnisse, symbolische Links, Besitzer, Gruppen, Rechte, Zeitstempel, ACLs, Hardlinks, xattrs und damit auch File Capabilities. Geeignet für lokale Linux-Dateisysteme wie ext4, xfs und btrfs. Unterstützt das Ziel eine erforderliche Metadatenfunktion nicht, wird das Backup als Fehler beendet.');
my $info_metadata_network = info_button('Für CIFS/NFS und viele NAS-Systeme, die Linux-xattrs nicht vollständig unterstützen. Network Compatible verwendet rsync ohne das X-Flag. Dateien, Verzeichnisse, symbolische Links, Besitzer, Gruppen, Rechte, Zeitstempel, ACLs, Hardlinks und Sparse-Dateien werden weiterhin gesichert; xattrs und File Capabilities werden bewusst ausgelassen. Das erzeugt nur einen neutralen Hinweis und blockiert auch zeitgesteuerte Backups nicht. Vor einem Restore muss die reduzierte Metadatentreue bestätigt werden.');
my $info_metadata_fake_super = info_button('Für Ziele, die user-xattrs zuverlässig unterstützen, aber native Unix-Besitzer oder privilegierte Metadaten nicht direkt speichern können. rsync --fake-super legt diese Angaben in Attributen unter user.rsync.* ab und liest sie beim Restore wieder aus. Das Profil hilft nicht, wenn das Ziel auch user-xattrs ablehnt. Deshalb nur verwenden, wenn die automatische Zielprüfung erfolgreich ist.');
my $info_metadata_portable = info_button('Für Ziele ohne geeignete Linux-Metadatenfunktionen. Portable Archive schreibt statt eines normalen rsync-Dateibaums einen pax-kompatiblen rootfs.tar-Container mit numerischen Besitzern, ACLs, xattrs, SELinux-Informationen und Sparse-Dateien. Dadurch liegen die Metadaten innerhalb des Archivs. Inkrementelle Snapshots sind nicht möglich; die Wiederherstellung erfolgt ausschließlich mit dem Offline-Helper aus einer Rescue- oder Offline-Umgebung.');
my $info_retention = info_button('Legt fest, wie viele fertige Backups behalten werden. Erlaubt sind 1 bis 10. Bei inkrementellen Snapshots ist das Löschen alter Backups sicher: unveränderte Dateien sind per Hardlink in jedem Snapshot sichtbar. Wird ein alter Snapshot entfernt, bleiben Dateien erhalten, solange sie noch von einem jüngeren Snapshot referenziert werden. Sobald nach einem erfolgreichen Backup mehr Backups vorhanden sind als erlaubt, entfernt das Plugin automatisch das älteste fertige Backup und das passende Export-Archiv.');
my $info_schedule = info_button('Der Zeitplan erstellt Backups automatisch per Cron. Täglich bedeutet jeden Tag zur Startzeit. Wöchentlich bedeutet an den gewählten Wochentagen zur Startzeit. Monatlich bedeutet an den gewählten Tagen in den gewählten Monaten zur Startzeit.');
my $info_time = info_button('Diese Uhrzeit gilt für alle Zeitplanarten. Bei täglich ist sie die einzige zeitliche Einstellung. Bei wöchentlich und monatlich wird sie mit den gewählten Tagen kombiniert.');
my $info_weekdays = info_button('Nur bei wöchentlichen Backups relevant. Du kannst einen oder mehrere Wochentage auswählen, zum Beispiel Montag und Freitag. An jedem gewählten Tag startet ein Backup zur angegebenen Startzeit.');
my $info_monthdays = info_button('Nur bei monatlichen Backups relevant. Du kannst einen oder mehrere Kalendertage auswählen, zum Beispiel 1, 15 oder 31. Wenn ein gewählter Tag im aktuellen Monat nicht existiert, läuft das Backup automatisch am letzten Tag dieses Monats. Beispiel: 31 wird im Februar am 28. oder 29. und in Monaten mit 30 Tagen am 30. ausgeführt.');
my $info_months = info_button('Nur bei monatlichen Backups relevant. Mit Alle Monate läuft der Monatsplan jeden Monat. Alternativ kannst du einzelne Monate wählen, zum Beispiel Jan, Apr, Jul und Okt für Quartalsbackups.');
my $info_pre_hook = info_button('Optionales Skript, das direkt vor dem Backup ausgeführt wird. Sinnvoll für Datenbank-Dumps oder das Vorbereiten von Diensten. Das Skript muss absolut angegeben werden und wird aus Sicherheitsgründen nur ausgeführt, wenn es Root gehört und nicht durch andere Benutzer beschreibbar ist.');
my $info_post_hook = info_button('Optionales Skript, das nach dem Backup ausgeführt wird. Sinnvoll zum Aufräumen, Dienste wieder in einen gewünschten Zustand zu bringen oder Benachrichtigungen auszuführen. Es gelten dieselben Sicherheitsregeln wie beim Skript vor dem Backup.');
my $info_excludes = info_button('Hier kannst du Pfade vom rsync-Backup ausschliessen, je ein Pfad pro Zeile. Das ist sinnvoll für grosse Medienarchive, Netzwerkshares oder Daten, die separat gesichert werden. Zu viele Ausschlüsse können aber die Wiederherstellung unvollständig machen.');
my $info_stop_targets = info_button('Wähle gezielt Docker-Container oder sicher steuerbare Dienste aus, die vor dem Backup angehalten und danach wieder gestartet werden. Laufende Dienste werden erkannt; zusätzlich werden LoxBerry-/Plugin-nahe Dienste angezeigt, auch wenn sie gerade inaktiv sind. Kritische LoxBerry-, Web-, SSH- und Backup-Dienste werden nicht angeboten. LoxBerry-Plugins ohne eigenen Dienst werden nicht hart beendet; dafür sind Pre-/Post-Backup-Hooks der sichere Weg.');
my $info_export = info_button('Erstellt nach jedem Backup zusätzlich ein komprimiertes tar.gz-Archiv. Das ist praktisch zum Download, Kopieren oder Archivieren, benötigt aber zusätzlichen Speicherplatz und Zeit.');
my $info_mail = info_button('Sendet Mailbenachrichtigungen über die zentrale LoxBerry-Benachrichtigung. SMTP-Zugangsdaten werden nicht im Plugin gespeichert.');
my $info_mail_to = info_button('Optional. Wenn leer, verwendet LoxBerry Host Backup die in LoxBerry hinterlegte Standardadresse aus der Mail- und Benachrichtigungskonfiguration.');
my $info_mail_events = info_button('Wähle aus, bei welchen Ereignissen eine Mailbenachrichtigung gesendet werden soll.');
my $info_root = info_button('Diese Bestätigung ist nötig, weil Vollbackup und Restore Systemdateien, Berechtigungen, Docker-Daten und Cronjobs betreffen. Es werden keine Passwörter gespeichert; erlaubt wird nur der Start des Backend-Skripts dieses Plugins.');
my $info_config_export = info_button('Lädt nur die Einstellungen dieses Plugins als kleine JSON-Datei herunter. Enthalten sind zum Beispiel Backup-Verzeichnis, Ausschlüsse, Zeitplan und ausgewählte Stop-Ziele, aber keine Backup-Daten und keine Passwörter.');
my $info_config_import = info_button('Liest eine zuvor exportierte Einstellungsdatei wieder ein. Das ist praktisch nach einer Neuinstallation des Plugins. Danach bitte Pfade prüfen und die Root-Freigabe aus Sicherheitsgründen erneut bestätigen.');
my $info_table = info_button('Diese Liste zeigt vorhandene Backups mit Status, Host, Grösse und Fertigstellungszeit. Nach neuen Backups wird zusätzlich eine kurze Plausibilitätsprüfung angezeigt. Ein vollständiges Backup sollte den Status complete und möglichst Prüfung ok haben, bevor du es für Restore-Tests verwendest.');
my $info_import = info_button('Importiert ein extern gespeichertes Backup-Archiv im Format tar.gz, zum Beispiel von deinem PC, NAS oder einem anderen Datenträger. Für Restore eines bereits unten gelisteten Backups brauchst du diese Datei-Auswahl nicht.');
my $info_delete = info_button('Löscht den Backup-Ordner und ein eventuell vorhandenes Export-Archiv dieses Backups. Das kann nicht rückgängig gemacht werden. Bei grossen Backups oder langsamen Datenträgern kann das Löschen mehrere Minuten dauern.');
my $info_delete_export = info_button('Löscht nur das tar.gz-Exportarchiv dieses Backups. Der eigentliche Backup-Snapshot bleibt erhalten und kann später erneut exportiert werden.');
my $info_restore = info_button('Wählt dieses Backup für eine Wiederherstellung aus. Danach wird unterhalb der Backup-Liste die Restore-Prüfung mit Bestätigung und Startbutton für genau dieses Backup eingeblendet.');
my $info_browse = info_button('Öffnet den Datei-Explorer für dieses Backup. Damit kannst du prüfen, welche Dateien im Backup enthalten sind.');
my $info_browse_pending = info_button('Dieses Backup ist noch nicht vollständig abgeschlossen. Dateien, Restore und Export werden erst freigegeben, wenn Status, Manifest und rootfs vollständig sind.');
my $info_download = info_button('Export erstellt ein tar.gz-Archiv im Backup-Verzeichnis. Sobald es fertig ist, kann es separat heruntergeladen werden. Die Erstellung grosser Archive läuft im Hintergrund.');
my $info_download_ready = info_button('Lädt das bereits erstellte tar.gz-Exportarchiv dieses Backups auf deinen Computer herunter. Das ist nicht der Restore; für eine Wiederherstellung bitte den Restore-Button verwenden.');
my $info_export_recreate = info_button('Erstellt das tar.gz-Exportarchiv für dieses Backup neu. Ein vorhandenes Export-Archiv wird ersetzt; der eigentliche Backup-Snapshot bleibt unverändert.');
my $info_backup_start = info_button('Prüft zuerst wichtige Voraussetzungen wie rsync, Schreibzugriff, freien Speicher und laufende Docker-Container. Nur wenn eine übergehbare Warnung erkannt wird, erscheint anschließend eine Bestätigung für einen zweiten Startversuch. Echte Fehler können nicht übergangen werden.');

sub render_target_notice {
  my ($target_info) = @_;
  return '<section class="inline-notice loading">Dateisystem-Pr&uuml;fung wird geladen...</section>' unless $target_info && %{$target_info};
  if (exists $target_info->{configured} && !$target_info->{configured}) {
    my $target_message = escapeHTML($target_info->{message} || 'Noch kein Backup-Verzeichnis festgelegt.');
    return qq{<section class="inline-notice info"><strong>Backup-Ziel:</strong> $target_message Die Dateisystem-Pr&uuml;fung startet nach dem Speichern automatisch.</section>};
  }
  my $target_state = $target_info->{status} || 'error';
  $target_state = 'error' unless $target_state =~ /^(?:ok|info|warning|error)$/;
  my $target_message = escapeHTML($target_info->{message} || 'Dateisystem- und Mount-Prüfung lieferte keine Detailmeldung.');
  my $target_fs = escapeHTML($target_info->{fs_type} || 'unbekannt');
  my $target_free = escapeHTML($target_info->{available_mb} || 0);
  return qq{<section class="inline-notice $target_state"><strong>Dateisystem-Pr&uuml;fung:</strong> $target_message<br><span>Erkannt: <code>$target_fs</code>, frei ca. $target_free MB.</span></section>};
}

sub classify_target_path {
  my ($path) = @_;
  my $probe = $path;
  while (defined $probe && !-e $probe && $probe ne '/') {
    $probe =~ s{/+[^/]+$}{};
    $probe = '/' unless length $probe;
  }
  $probe = '/' unless defined $probe && length $probe && -e $probe;
  my $fs = '';
  if (open(my $fh, '-|', 'findmnt', '-no', 'FSTYPE', '-T', $probe)) {
    $fs = <$fh> // '';
    close $fh;
  }
  chomp $fs;
  $fs ||= 'unbekannt';
  my $free = 0;
  if (open(my $fh, '-|', 'df', '-Pm', $probe)) {
    my @lines = <$fh>;
    close $fh;
    if (defined $lines[1] && $lines[1] =~ /^\S+\s+\S+\s+\S+\s+(\d+)/) {
      $free = $1;
    }
  }
  $free ||= 0;
  my $recommended = $fs =~ /^(ext2|ext3|ext4|xfs|btrfs)$/ ? 1 : 0;
  return ($recommended, $fs, $free);
}

sub target_label_from_path {
  my ($path) = @_;
  return 'Backup-Ziel' unless defined $path && length $path;
  $path =~ s{/loxberry-hostbackup/?$}{};
  $path =~ s{//+}{/}g;
  my ($label) = $path =~ m{/([^/]+)$};
  return $label || $path;
}

sub is_real_network_mount {
  my ($path) = @_;
  return 0 unless defined $path && length $path;

  my $probe = $path;
  while (defined $probe && !-e $probe && $probe ne '/') {
    $probe =~ s{/+[^/]+$}{};
    $probe = '/' unless length $probe;
  }

  return 0 unless defined $probe && length $probe && -e $probe;

  my $target = '';
  my $fs = '';

  if (open(my $fh, '-|', 'findmnt', '-rn', '-T', $probe, '-o', 'TARGET,FSTYPE')) {
    my $line = <$fh> // '';
    close $fh;
    chomp $line;

    if ($line =~ /^(\S+)\s+(\S+)/) {
      ($target, $fs) = ($1, $2);
    }
  }

  return 0 unless length $target && length $fs;
  return 0 if $target eq '/';

  return 1 if $fs =~ /^(cifs|smb3?|nfs|nfs4|fuse\.sshfs|sshfs|curlftpfs|fuse|fuseblk)$/i;

  return 0;
}

sub render_backup_target_picker {
  my ($current_root) = @_;
  my @groups = (
    { id => 'current', title => 'Aktueller Pfad', description => 'Der derzeit gespeicherte Zielpfad.', targets => [] },
    { id => 'usb', title => 'USB-Speicher', description => 'Erkannte USB-Datenträger und LoxBerry-USB-Pfade.', targets => [] },
    { id => 'network', title => 'Netzwerkspeicher', description => 'Typische LoxBerry-Mountpoints für Samba, NFS oder FTP.', targets => [] },
    { id => 'local', title => 'Weitere lokale Pfade', description => 'Weitere sinnvolle lokale Speicherorte.', targets => [] },
  );
  my %group_by_id = map { $_->{id} => $_ } @groups;
  my %seen;

  my $add_target = sub {
    my ($path, $group_id, $label) = @_;
    return unless defined $path && length $path;
    $path =~ s{//+}{/}g;
    return if $path eq '/' || $path =~ m{^/(proc|sys|dev|run|tmp)(/|$)};
    return if $seen{$path}++;
    $group_id ||= 'local';
    $group_id = 'local' unless $group_by_id{$group_id};
    my ($recommended, $fs, $free) = classify_target_path($path);
    push @{$group_by_id{$group_id}->{targets}}, {
      path => $path,
      label => $label || target_label_from_path($path),
      recommended => $recommended,
      fs => $fs,
      free => $free,
    };
  };

  my $storage_value = sub {
    my ($item, @keys) = @_;
    return '' unless ref($item) eq 'HASH';
    for my $key (@keys) {
      return $item->{$key} if defined $item->{$key} && length $item->{$key};
    }
    return '';
  };

  eval {
    require LoxBerry::Storage;

    my @usb = eval { LoxBerry::Storage::get_usbstorage() };
    for my $item (@usb) {
      my $path = $storage_value->($item, qw(path mountpoint mount dir directory devicepath USBSTORAGE_DEVICEPATH));
      my $label = $storage_value->($item, qw(name label device USBSTORAGE_DEVICE USBSTORAGE_NAME));
      next unless length $path;
      $add_target->("$path/loxberry-hostbackup", 'usb', $label);
    }

    my @netshares = eval { LoxBerry::Storage::get_netshares() };
    for my $item (@netshares) {
      my $path = $storage_value->($item, qw(path mountpoint mount dir directory sharepath NETSHARE_SHAREPATH));
      my $label = $storage_value->($item, qw(name label sharename NETSHARE_SHARENAME));
      next unless length $path;

      # Netzwerkspeicher nur anzeigen, wenn wirklich ein Netzwerk-Dateisystem gemountet ist.
      next unless is_real_network_mount($path);

      $add_target->("$path/loxberry-hostbackup", 'network', $label);
    }

    1;
  };

  $add_target->($current_root, 'current', 'Aktueller Zielpfad') if defined $current_root && length $current_root;

  my @base_dirs = (
    [ '/media/usb', 'usb' ],
    [ '/opt/loxberry/system/storage/usb', 'usb' ],
    [ '/mnt/ftp_client', 'network' ],
    [ '/mnt/nfs_client', 'network' ],
    [ '/mnt/samba', 'network' ],
    [ '/mnt', 'local' ],
  );
  for my $base (@base_dirs) {
    my ($base_path, $group_id) = @$base;
    next unless -d $base_path;

    opendir(my $dh, $base_path) or next;
    my @entries = sort grep { $_ !~ /^\./ } readdir($dh);
    closedir($dh);

    for my $entry (@entries) {
      next if $entry =~ /^(lost\+found|System Volume Information)$/i;
      next if $base_path eq '/mnt' && $entry =~ /^(ftp_client|nfs_client|samba)$/;

      my $path = "$base_path/$entry";
      next unless -d $path;

      # Netzwerk-Basisordner wie /mnt/samba, /mnt/nfs_client oder /mnt/ftp_client
      # nur anzeigen, wenn darunter wirklich ein Netzwerk-Dateisystem gemountet ist.
      if ($group_id eq 'network') {
        next unless is_real_network_mount($path);
      }

      $add_target->("$path/loxberry-hostbackup", $group_id, $entry);
    }
  }

  my $has_targets = 0;
  for my $group (@groups) {
    $has_targets ||= @{$group->{targets}};
  }
  return '' unless $has_targets;

  my $groups_html = '';
  for my $group (@groups) {
    my @targets = @{$group->{targets}};
    next unless @targets;
    @targets = @targets[0..5] if @targets > 6;
    my $buttons = '';
    for my $target (@targets) {
      my $safe_path = escapeHTML($target->{path});
      my $safe_label = escapeHTML($target->{label});
      my $class = $target->{recommended} ? ' is-recommended' : ' is-warning';
      my $state = $target->{recommended} ? 'empfohlen' : 'pr&uuml;fen';
      my $safe_fs = escapeHTML($target->{fs});
      my $safe_free = escapeHTML($target->{free});
      $buttons .= qq{<span role="button" tabindex="0" class="path-choice$class" draggable="true" data-backup-root="$safe_path"><span class="path-choice-head"><strong>$safe_label</strong> <em>$state</em></span><span class="path-choice-path">$safe_path</span><span class="path-choice-meta">$safe_fs &middot; frei ca. $safe_free MB</span></span>};
    }
    my $safe_title = escapeHTML($group->{title});
    my $count = scalar @targets;
    $groups_html .= qq{<details class="target-picker-group"><summary><span>$safe_title</span><small>$count verf&uuml;gbar</small></summary><div class="target-picker-actions">$buttons</div></details>};
  }

  my $info_targets = info_button('Klick übernimmt den Pfad ins Backup-Verzeichnis. Linux-Dateisysteme wie ext4, xfs oder btrfs sind für Geschwindigkeit, Rechte und inkrementelle Snapshots empfohlen.');

  return qq{
<details class="schedule-detail target-picker">
<summary>Backup-Ziel auswählen $info_targets</summary>
<div class="target-picker-groups">$groups_html</div>
</details>
};
}

sub render_backup_rows {
  my ($backups) = @_;

  if (!$backups || ref($backups) ne 'ARRAY' || !@$backups) {
    return '<tr><td colspan="8" class="empty">Noch keine Backups vorhanden.</td></tr>';
  }

  my $html = '';

  for my $backup (@$backups) {
    my $raw_id = $backup->{backup_id} || '';
    my $id = escapeHTML($raw_id);
    my $status = escapeHTML($backup->{status} || 'unbekannt');
    my $host = escapeHTML(($backup->{host} || {})->{hostname} || '');
    my $finished = escapeHTML($backup->{finished_at} || '');

    my $size = int(($backup->{size_bytes} || 0) / 1024 / 1024);
    my $files = escapeHTML($backup->{files_count} || '0');
    my $export_status = $backup->{export_status} || ($backup->{export_file} ? 'available' : 'missing');
    my $export_message = escapeHTML($backup->{export_message} || '');
    my $export_path = escapeHTML($backup->{export_file} || '');
    my $export_size = int(($backup->{export_size_bytes} || 0) / 1024 / 1024);
    my $export = '-';
    if ($export_status eq 'available') {
      $export = qq{<span class="export-state ok">vorhanden</span><small class="export-size">${export_size} MB</small>};
      $export .= qq{<small class="muted">Pfad: <code>$export_path</code></small>} if length $export_path;
    } elsif ($export_status eq 'running') {
      $export = qq{<span class="export-state running">Export läuft</span>};
    } elsif ($export_status eq 'failed') {
      $export = qq{<span class="export-state failed">fehlgeschlagen</span>};
      $export .= qq{<small class="muted">$export_message</small>} if length $export_message;
    }
    my $validation = $backup->{validation} || {};
    my $backup_status = $backup->{status} || '';
    my $validation_status = $validation->{status} || '';
    my $is_complete = ($backup_status eq 'complete' && $validation_status eq 'ok')
      || ($backup_status eq 'complete_with_warnings' && $validation_status eq 'warning');
    my $storage_format = (($backup->{backup} || {})->{storage_format}) || $backup->{storage_format} || 'directory';
    my $is_portable = $storage_format eq 'portable-tar';
    my $csrf = csrf_field();
    my $validation_label = '';
    my $delete_label = $is_complete ? 'L&ouml;schen' : 'Unvollst&auml;ndiges Backup l&ouml;schen';
    if ($backup_status =~ /^complete(?:_with_warnings)?$/) {
      if (($validation->{status} || '') eq 'ok') {
        $validation_label = '<small class="backup-health ok">Pr&uuml;fung ok</small>';
      } elsif (($validation->{status} || '') eq 'warning') {
        $validation_label = '<small class="backup-health warning">Pr&uuml;fung mit Hinweis</small>';
      } elsif (($validation->{status} || '') eq 'error') {
        $validation_label = '<small class="backup-health error">Pr&uuml;fung fehlerhaft</small>';
      } else {
        $validation_label = '<small class="backup-health muted">Pr&uuml;fung nicht vorhanden</small>';
      }
    } elsif (($backup->{status} || '') =~ /^(stopped|failed|running|unbekannt)$/) {
      $validation_label = '<small class="backup-health warning">Unvollst&auml;ndig: bei Bedarf l&ouml;schen</small>';
    }
    my $active_task_hidden = hidden_active_task();
    my $backup_actions;
    my $export_action = '';

    if ($is_complete) {
      if ($export_status eq 'available') {
        $export_action = qq{
<form data-ajax="false" method="get" class="inline-form">
<input data-role="none" type="hidden" name="action" value="download-export">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Export-Archiv herunterladen</button>$info_download_ready
</form>
<form data-ajax="false" method="post" class="inline-form loading-form">
$csrf
<input data-role="none" type="hidden" name="action" value="start-export">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Export neu erstellen</button>$info_export_recreate
</form>
<form data-ajax="false" method="post" class="inline-form delete-export-form">
$csrf
<input data-role="none" type="hidden" name="action" value="delete-export">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" class="danger" type="submit">Export-Archiv löschen</button>$info_delete_export
</form>
};
      } elsif ($export_status eq 'running') {
        $export_action = qq{<span class="pending-action">Export läuft</span>$info_download};
      } else {
        $export_action = qq{
<form data-ajax="false" method="post" class="inline-form loading-form">
$csrf
<input data-role="none" type="hidden" name="action" value="start-export">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Export erstellen</button>$info_download
</form>
};
      }

      my $browse_action = $is_portable
        ? qq{<span class="pending-action">Dateiansicht bei Portable Archive nicht verf&uuml;gbar</span>$info_browse}
        : qq{
<form data-ajax="false" method="get" class="inline-form" data-return-anchor="backup-browser">
<input data-role="none" type="hidden" name="browse_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Dateien</button>$info_browse
</form>
};
      $backup_actions = qq{
$browse_action
<form data-ajax="false" method="get" class="inline-form" data-return-anchor="restore-panel">
<input data-role="none" type="hidden" name="restore_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Restore</button>$info_restore
</form>
$export_action
};
    } else {
      $backup_actions = qq{
<span class="pending-action">Noch nicht vollst&auml;ndig</span>$info_browse_pending
};
    }

    $html .= qq{
<tr>
<td><code>$id</code></td>
<td>$status$validation_label</td>
<td>$host</td>
<td>${size} MB</td>
<td>$files</td>
<td>$finished</td>
<td>$export</td>
<td>
<div class="row-actions">
$backup_actions
<form data-ajax="false" method="post" class="inline-form delete-backup-form">
$csrf
<input data-role="none" type="hidden" name="action" value="delete-backup">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" class="danger" type="submit">$delete_label</button>$info_delete
</form>
</div>
</td>
</tr>
};
  }

  return $html;
}

sub render_stop_targets {
  my ($targets) = @_;
  my $hidden = '<input data-role="none" type="hidden" name="stop_targets_loaded" value="1">';

  if (!$targets || ref($targets) ne 'ARRAY' || !@$targets) {
    return $hidden . '<p class="empty">Keine ausw&auml;hlbaren Dienste oder Container gefunden.</p>';
  }

  my @group_order = ('Docker-Container', 'LoxBerry-/Plugin-Dienste', 'Weitere Systemdienste', 'Weitere Dienste');
  my %order = map { $group_order[$_] => $_ } 0..$#group_order;
  my %group_hint = (
    'Docker-Container' => 'Empfohlen bei Containern mit Datenbanken, Konfigurationen oder vielen Schreibzugriffen. Gestoppt wird nur, was vor dem Backup wirklich l&auml;uft; danach wird genau das wieder gestartet.',
    'LoxBerry-/Plugin-Dienste' => 'Dienste mit Bezug zu LoxBerry oder Plugins. Sinnvoll bei Diensten mit Datenbanken, Logs oder h&auml;ufig ge&auml;nderten Dateien. Plugins ohne eigenen Dienst werden nicht angeboten; daf&uuml;r sind Hooks der sichere Weg.',
    'Weitere Systemdienste' => 'Expertenbereich. Nur ausw&auml;hlen, wenn du den Dienst kennst und ein kurzer Stopp w&auml;hrend des Backups unkritisch ist.',
    'Weitere Dienste' => 'Sonstige erkannte Dienste.',
  );
  my %groups;
  my $recommended_total = 0;

  for my $target (@$targets) {
    next unless ref($target) eq 'HASH';
    my $type = $target->{type} || '';
    my $name = $target->{name} || '';
    next unless $type =~ /^(docker|systemd|plugin)$/ && length $name;
    $recommended_total++ if $target->{recommended} && $type =~ /^(docker|systemd)$/;
    my $group = $target->{group} || 'Weitere Dienste';
    push @{$groups{$group}}, $target;
  }

  my $html = $hidden;
  $html .= '<div class="stop-target-row">';
  if ($recommended_total) {
    $html .= qq{<div class="stop-target-toolbar"><button data-role="none" type="button" data-stop-target-preset="recommended">Empfohlene Auswahl setzen</button><button data-role="none" type="button" data-stop-target-preset="clear">Auswahl leeren</button><span>$recommended_total Stop-Ziele empfohlen</span></div>};
  }

  for my $group (sort { ($order{$a} // 99) <=> ($order{$b} // 99) || $a cmp $b } keys %groups) {
    my $safe_group = escapeHTML($group);
    my $total_count = scalar @{$groups{$group}};
    my $selected_count = 0;
    for my $target (@{$groups{$group}}) {
      $selected_count++ if $target->{selected};
    }
    my $count_label = $selected_count ? "$selected_count von $total_count ausgew&auml;hlt" : "$total_count verf&uuml;gbar";
    my $safe_hint = $group_hint{$group} || '';
    my $hint_html = length($safe_hint) ? qq{<p class="stop-target-hint">$safe_hint</p>} : '';
    $html .= qq{<details class="stop-target-group"><summary><span>$safe_group</span><small>$count_label</small></summary>$hint_html<div class="stop-target-grid">};

    for my $target (sort { ($a->{label} || $a->{name} || '') cmp ($b->{label} || $b->{name} || '') } @{$groups{$group}}) {
      my $type = $target->{type} || '';
      my $name = $target->{name} || '';
      my $value = escapeHTML("$type:$name");
      my $label = escapeHTML($target->{label} || $name);
      my $status = $target->{status} || '';
      my $details = $target->{details} || '';
      my $is_stoppable = $type =~ /^(docker|systemd)$/;
      my $checked = $is_stoppable ? checked_attr($target->{selected}) : '';
      my $recommended = ($is_stoppable && $target->{recommended}) ? ' data-recommended="1"' : '';
      my $meta = join(' - ', grep { length $_ } ($status, $details));
      my $meta_html = length($meta) ? '<small>' . escapeHTML($meta) . '</small>' : '';
      my $reason_html = ($is_stoppable && $target->{recommended})
        ? '<small class="stop-target-reason">Empfohlen: laufender Dienst mit wahrscheinlichen Daten&auml;nderungen</small>'
        : '';
      my $disabled = $is_stoppable ? '' : ' disabled';
      my $name_attr = $is_stoppable ? ' name="stop_targets"' : '';

      $html .= qq{<label class="stop-target-item}.($is_stoppable ? '' : ' is-disabled').qq{"><input data-role="none" type="checkbox"$name_attr value="$value"$checked$disabled$recommended><span><strong>$label</strong>$meta_html$reason_html</span></label>};
    }

    $html .= '</div></details>';
  }

  $html .= '</div>';

  return $html;
}

if ($action eq 'target-notice') {
  my ($target_status, $target_json) = run_shell(backend_cmd('target-info'));
  my $target_info = {};
  if ($target_status == 0) {
    $target_info = eval { decode_json($target_json) } || {};
  }
  print header(-type => 'text/html', -charset => 'utf-8', -status => ($target_status == 0 ? '200 OK' : '500 Internal Server Error'));
  print $target_status == 0 ? render_target_notice($target_info) : '<section class="inline-notice error"><strong>Technischer Fehler:</strong> Dateisystem-Pr&uuml;fung konnte nicht geladen werden.</section>';
  exit;
}

if ($action eq 'backup-list') {
  my ($list_status, $list_json) = run_shell(backend_cmd('list'));
  my $backups = [];
  if ($list_status == 0) {
    $backups = eval { decode_json($list_json) } || [];
  }
  print header(-type => 'text/html', -charset => 'utf-8', -status => ($list_status == 0 ? '200 OK' : '500 Internal Server Error'));
  print $list_status == 0 ? render_backup_rows($backups) : '<tr><td colspan="8" class="empty">Backup-Liste konnte nicht geladen werden.</td></tr>';
  exit;
}

if ($action eq 'stop-targets') {
  my ($target_status, $target_json) = run_shell(backend_cmd('stop-targets'));
  my $targets = [];
  if ($target_status == 0) {
    $targets = eval { decode_json($target_json) } || [];
  }
  print header(-type => 'text/html', -charset => 'utf-8', -status => ($target_status == 0 ? '200 OK' : '500 Internal Server Error'));
  print $target_status == 0 ? render_stop_targets($targets) : '<p class="empty">Dienste und Container konnten nicht geladen werden.</p>';
  exit;
}

my $target_notice = render_target_notice(undef);
my $backup_target_picker = render_backup_target_picker($config->{backup_root} || '');
my $csrf_html = csrf_field();
my $csrf_attr = escapeHTML($csrf_token);
my $preflight_accept_control = '';
if (length $preflight_warning) {
  $preflight_accept_control = '<label class="checkline preflight-confirm"><input data-role="none" type="checkbox" name="accept_preflight_warnings" value="1" required><span>Backup trotz dieser Warnhinweise starten</span></label>';
}

our $htmlhead = qq{
<link rel="stylesheet" href="assets/style.css">
};

LoxBerry::Web::lbheader(
  "LoxBerry Host Backup",
  undef,
  undef
);

print <<HTML;

<div class="loading-overlay" id="loading-overlay" aria-live="polite" aria-hidden="true">
<div class="loading-box">
<span class="loading-spinner" aria-hidden="true"></span>
<span id="loading-text">Aktion wird ausgeführt...</span>
</div>
</div>

<main class="page" id="hostbackup-app" data-enhance="false" data-csrf-token="$csrf_attr">

<header class="topbar">
<div class="brand">
<img class="brand-icon" src="/system/images/icons/loxberryhostbackup/icon_64.png" alt="">
<div>
<h1>LoxBerry Host Backup</h1>
<p>Vollbackup für LoxBerry, Docker, DietPi und native Dienste.</p>
</div>
</div>

<div class="topbar-actions">
<form data-ajax="false" method="post">
$csrf_html
<input data-role="none" type="hidden" name="action" value="backup">
$preflight_accept_control
<button data-role="none" class="primary" type="submit"$config_action_disabled>Backup starten</button>$info_backup_start
</form>
</div>
</header>
HTML

if ($message) {
  print qq{<section class="notice ok">$message</section>};
}

if ($error) {
  print qq{<section class="notice error"><pre>$error</pre></section>};
}

if (!$config_loaded) {
  print qq{<section class="notice warning"><strong>Gespeicherte Einstellungen wurden nicht geladen.</strong> Die unten sichtbaren Ersatzwerte sind nicht der gespeicherte Stand. Speichern und Backup-Start bleiben gesperrt, damit eine vorhandene Konfiguration nicht versehentlich ersetzt wird.</section>};
}

if ($preflight_warning) {
  print qq{<section class="notice warning"><strong>Backup noch nicht gestartet:</strong><pre>$preflight_warning</pre><span>Prüfe den Hinweis. Wenn du trotzdem fortfahren möchtest, aktiviere oben die Bestätigung und starte das Backup erneut.</span></section>};
}

print <<HTML;

<section class="panel wizard-panel">
<details>
<summary>Kurzanleitung</summary>
<ol>
<li><strong>Backup-Ziel wählen und speichern:</strong> Übernimm ein erkanntes Ziel oder trage das Backup-Verzeichnis ein. Bestätige die Root-Freigabe und speichere die Einstellungen; erst danach kann das Plugin Dateisystem, Mount und freien Speicher prüfen.</li>
<li><strong>Metadaten-Profil passend zum Ziel wählen:</strong> Standard ist <em>Native Strict</em> für lokale Linux-Dateisysteme wie ext4, xfs oder btrfs. Für CIFS/NFS und viele NAS-Systeme ist <em>Network Compatible</em> vorgesehen; der dort angezeigte Hinweis blockiert weder manuelle noch zeitgesteuerte Backups.</li>
<li><strong>Ausschlüsse prüfen:</strong> Schliesse das Backup-Ziel selbst, weitere Backup-Datenträger, alte Images und grosse Archivordner aus. So vermeidest du doppelte Sicherungen und unnötig grosse Backups.</li>
<li><strong>Backup-Modus festlegen:</strong> Für regelmässige Sicherungen ist der inkrementelle Snapshot empfohlen. Unveränderte Dateien werden per Hardlink geteilt; deshalb belegen Folgebackups deutlich weniger zusätzlichen Speicher.</li>
<li><strong>Dienste und Container auswählen:</strong> Stoppe gezielt Dienste und Container, die während des Backups viele Daten schreiben oder eigene Datenbanken verwenden. Das verbessert die Konsistenz der gesicherten Daten.</li>
<li><strong>Zeitplan aktivieren:</strong> Lege täglich, wöchentlich oder monatlich sowie die gewünschte Startzeit fest und speichere erneut. Zeitgesteuerte Backups laufen danach selbständig; neutrale Hinweise erfordern keine Bestätigung.</li>
<li><strong>Erstes Backup kontrollieren:</strong> Prüfe nach dem ersten Lauf Status, Live-Log, Manifest, Dateizahl, Grösse und die Backup-Liste. Öffne bei Bedarf den Datei-Explorer, um den Inhalt des Backups zu kontrollieren.</li>
<li><strong>Restore-Konzept festlegen:</strong> Lege vor dem Ernstfall fest, wie und wo du ein Backup wiederherstellst. Für produktive Systeme ist ein Restore aus einer Rescue- oder Offline-Umgebung am zuverlässigsten; ein geplanter Restore-Test wird empfohlen.</li>
</ol>
</details>
</section>

<section class="panel task-monitor" id="task-monitor" data-active-task="$active_task_attr">
<h2>Live-Status</h2>
<div class="task-actions">
<span class="task-state state-running" id="task-state">Kein laufender Task ausgewählt</span>
<span class="task-heartbeat" id="task-heartbeat">Nach einem gestarteten Backup werden hier Status und Log angezeigt.</span>
<form data-ajax="false" method="post" class="stop-task-form" id="stop-task-form">
$csrf_html
<input data-role="none" type="hidden" name="action" value="stop-backup">
<input data-role="none" type="hidden" name="task" value="$active_task_attr">
<button data-role="none" class="danger" type="submit">Backup stoppen</button>
</form>
</div>
<pre class="terminal" id="task-log">Noch keine Live-Ausgabe vorhanden.</pre>
</section>

<section class="panel settings-panel">

<h2>Einstellungen</h2>

<form data-ajax="false" method="post" class="settings-form" id="settings-save-form">

$csrf_html
<input data-role="none" type="hidden" name="action" value="save-config">

<fieldset class="settings-load-guard"$config_action_disabled>

<fieldset class="schedule-card wide">
<legend>Grundeinstellungen</legend>

<div class="settings-subtitle">Speicherort und Aufbewahrung</div>

<div class="settings-form nested-settings">

<div class="target-input-stack">
$backup_target_picker
<label>
<span>Backup-Verzeichnis $info_backup_root</span>
<input data-role="none" id="backup-root-input" name="backup_root" value="$cfg_backup_root">
</label>
</div>

<div id="target-notice">$target_notice</div>

<label>
<span>Anzahl Backups behalten $info_retention</span>
<input data-role="none" name="keep_backups" type="number" min="1" max="10" value="$cfg_keep">
</label>

</div>

</fieldset>

<fieldset class="schedule-card wide">
<legend>Metadaten-Profil $info_metadata_mode</legend>
<div class="settings-subtitle">Passendes Sicherungsverfahren für das verwendete Backup-Ziel</div>
<div class="metadata-default-note"><strong>Standardeinstellung:</strong> Native Strict. Für CIFS/NFS oder ein NAS bitte das zum Ziel passende Profil wählen.</div>
<div class="schedule-modes metadata-modes">
<label><input data-role="none" type="radio" name="metadata_mode" value="native-strict"$native_strict_checked><span class="metadata-profile-copy"><span class="metadata-profile-title"><strong>Native Strict</strong><span class="metadata-default-badge">Standard</span>$info_metadata_native</span><span class="metadata-profile-summary">Lokale Linux-Dateisysteme wie ext4, xfs und btrfs; vollständige Linux-Metadaten.</span></span></label>
<label><input data-role="none" type="radio" name="metadata_mode" value="network-compatible"$network_compatible_checked><span class="metadata-profile-copy"><span class="metadata-profile-title"><strong>Network Compatible</strong>$info_metadata_network</span><span class="metadata-profile-summary">CIFS/NFS und viele NAS-Systeme; ohne xattrs und File Capabilities.</span></span></label>
<label><input data-role="none" type="radio" name="metadata_mode" value="fake-super"$fake_super_checked><span class="metadata-profile-copy"><span class="metadata-profile-title"><strong>Fake Super</strong>$info_metadata_fake_super</span><span class="metadata-profile-summary">Ziele mit zuverlässigen user-xattrs, aber ohne native Unix-Metadaten.</span></span></label>
<label><input data-role="none" type="radio" name="metadata_mode" value="portable-archive"$portable_archive_checked><span class="metadata-profile-copy"><span class="metadata-profile-title"><strong>Portable Archive</strong>$info_metadata_portable</span><span class="metadata-profile-summary">Metadatentreuer Archivcontainer; keine Snapshots und Restore nur offline.</span></span></label>
</div>
</fieldset>

<fieldset class="schedule-card wide">
<legend>Backup-Modus $info_backup_mode</legend>
<div class="settings-subtitle">Auswahl Backup-Modus</div>
<div class="schedule-modes">
<label><input data-role="none" type="radio" name="backup_mode" value="full"$full_mode_checked> Volles Backup</label>
<label><input data-role="none" type="radio" name="backup_mode" value="snapshot"$snapshot_mode_checked> Inkrementeller Snapshot</label>
</div>
</fieldset>

<fieldset class="schedule-card wide">

<legend>Automatische Backups $info_schedule</legend>

<div class="settings-subtitle">Definition automatische Backups</div>

<label class="checkline schedule-enable">
<input data-role="none" type="checkbox" name="schedule_enabled" value="1"$cfg_schedule_enabled>
<span>Zeitplan aktivieren</span>
</label>

<div class="schedule-modes">
<label><input data-role="none" type="radio" name="schedule_mode" value="daily"$daily_checked> Täglich</label>
<label><input data-role="none" type="radio" name="schedule_mode" value="weekly"$weekly_checked> Wöchentlich</label>
<label><input data-role="none" type="radio" name="schedule_mode" value="monthly"$monthly_checked> Monatlich</label>
</div>

<label>
<span>Startzeit $info_time</span>
<input data-role="none" class="schedule-time-input" name="schedule_time" type="time" value="$cfg_schedule_time">
</label>

<details class="schedule-detail" data-schedule-panel="weekly">
<summary>Wochentage $info_weekdays</summary>
<div class="choice-grid">
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="1"$weekday_checked[1]> Montag</label>
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="2"$weekday_checked[2]> Dienstag</label>
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="3"$weekday_checked[3]> Mittwoch</label>
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="4"$weekday_checked[4]> Donnerstag</label>
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="5"$weekday_checked[5]> Freitag</label>
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="6"$weekday_checked[6]> Samstag</label>
<label><input data-role="none" type="checkbox" name="schedule_weekdays" value="0"$weekday_checked[0]> Sonntag</label>
</div>
</details>

<details class="schedule-detail" data-schedule-panel="monthly">
<summary>Tage im Monat $info_monthdays</summary>
<div class="day-grid">
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="1"$monthday_checked[1]> 1</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="2"$monthday_checked[2]> 2</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="3"$monthday_checked[3]> 3</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="4"$monthday_checked[4]> 4</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="5"$monthday_checked[5]> 5</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="6"$monthday_checked[6]> 6</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="7"$monthday_checked[7]> 7</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="8"$monthday_checked[8]> 8</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="9"$monthday_checked[9]> 9</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="10"$monthday_checked[10]> 10</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="11"$monthday_checked[11]> 11</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="12"$monthday_checked[12]> 12</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="13"$monthday_checked[13]> 13</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="14"$monthday_checked[14]> 14</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="15"$monthday_checked[15]> 15</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="16"$monthday_checked[16]> 16</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="17"$monthday_checked[17]> 17</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="18"$monthday_checked[18]> 18</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="19"$monthday_checked[19]> 19</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="20"$monthday_checked[20]> 20</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="21"$monthday_checked[21]> 21</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="22"$monthday_checked[22]> 22</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="23"$monthday_checked[23]> 23</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="24"$monthday_checked[24]> 24</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="25"$monthday_checked[25]> 25</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="26"$monthday_checked[26]> 26</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="27"$monthday_checked[27]> 27</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="28"$monthday_checked[28]> 28</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="29"$monthday_checked[29]> 29</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="30"$monthday_checked[30]> 30</label>
<label><input data-role="none" type="checkbox" name="schedule_monthdays" value="31"$monthday_checked[31]> 31</label>
</div>
</details>

<details class="schedule-detail" data-schedule-panel="monthly">
<summary>Monate $info_months</summary>
<div class="choice-grid month-grid">
<label><input data-role="none" type="checkbox" name="schedule_months" value="*"$all_months_checked> Alle Monate</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="1"$month_checked[1]> Jan</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="2"$month_checked[2]> Feb</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="3"$month_checked[3]> März</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="4"$month_checked[4]> Apr</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="5"$month_checked[5]> Mai</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="6"$month_checked[6]> Jun</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="7"$month_checked[7]> Jul</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="8"$month_checked[8]> Aug</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="9"$month_checked[9]> Sep</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="10"$month_checked[10]> Okt</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="11"$month_checked[11]> Nov</label>
<label><input data-role="none" type="checkbox" name="schedule_months" value="12"$month_checked[12]> Dez</label>
</div>
</details>

</fieldset>

<fieldset class="schedule-card wide settings-group">
<legend>Skripte und Ausschlüsse</legend>

<div class="settings-subtitle">Vor- und Nachbearbeitung</div>

<div class="settings-form nested-settings">

<label>
<span>Skript vor dem Backup $info_pre_hook</span>
<input data-role="none" class="hook-input" name="pre_backup_hook" value="$cfg_pre_hook">
</label>

<label>
<span>Skript nach dem Backup $info_post_hook</span>
<input data-role="none" class="hook-input" name="post_backup_hook" value="$cfg_post_hook">
</label>

<label class="wide">
<span>Vom Backup ausschliessen $info_excludes</span>
<textarea data-role="none" name="rsync_extra_excludes" rows="5">$cfg_excludes</textarea>
</label>

</div>

</fieldset>

<fieldset class="schedule-card wide settings-group">
<legend>Optionen und Freigaben</legend>

<label class="checkline root-confirm">
<input data-role="none" type="checkbox" name="root_permission_ack" value="1"$cfg_root_permission_ack required>
<span>Root-Freigabe bestätigen $info_root</span>
</label>

<details class="schedule-detail mail-detail">
<summary>Mailbenachrichtigung $info_mail</summary>

<label class="checkline">
<input data-role="none" type="checkbox" name="mail_notify_enabled" value="1"$cfg_mail_notify_enabled>
<span>Mailbenachrichtigung aktivieren</span>
</label>

<div class="settings-form nested-settings mail-settings">
<label class="wide">
<span>Mailadresse $info_mail_to</span>
<input data-role="none" type="email" name="mail_notify_to" value="$cfg_mail_notify_to" placeholder="leer = LoxBerry-Standardadresse">
</label>

<label class="wide">
<span>Ereignisse $info_mail_events</span>
<div class="choice-grid mail-event-grid">
<label><input data-role="none" type="checkbox" name="mail_notify_success" value="1"$cfg_mail_notify_success> Backup erfolgreich</label>
<label><input data-role="none" type="checkbox" name="mail_notify_failure" value="1"$cfg_mail_notify_failure> Fehler</label>
<label><input data-role="none" type="checkbox" name="mail_notify_stopped" value="1"$cfg_mail_notify_stopped> Abbruch</label>
<label><input data-role="none" type="checkbox" name="mail_notify_restore" value="1"$cfg_mail_notify_restore> Restore</label>
</div>
</label>
</div>
</details>

<input data-role="none" type="hidden" name="stop_docker_before_backup" value="">

<details class="stop-target-panel">
<summary>Zu stoppende Dienste vor dem Backup $info_stop_targets</summary>
<div id="stop-targets-list" class="stop-targets-list loading">
<span class="mini-spinner" aria-hidden="true"></span>
<span>Dienste und Container werden geladen...</span>
</div>
</details>

<label class="checkline">
<input data-role="none" type="checkbox" name="create_export_after_backup" value="1"$cfg_create_export>
<span>Nach jedem Backup ein tar.gz-Archiv erstellen $info_export</span>
</label>

</fieldset>

</fieldset>

</form>

<aside class="settings-change-popup" id="settings-change-popup" role="dialog" aria-modal="false" aria-hidden="true" aria-labelledby="settings-change-title">
<div class="settings-change-popup-header">
<div>
<strong id="settings-change-title">Ungespeicherte Änderungen</strong>
<span>Diese Einstellungen wurden noch nicht übernommen.</span>
</div>
</div>
<ul id="settings-change-list" class="settings-change-list"></ul>
<button data-role="none" class="primary settings-change-save" type="submit" form="settings-save-form"$config_action_disabled>Änderungen speichern</button>
</aside>

<fieldset class="schedule-card wide settings-group config-card">
<legend>Konfiguration verwalten</legend>

<div class="settings-subtitle">Plugin-Konfiguration</div>

<div class="config-actions">
<button data-role="none" type="submit" form="settings-save-form"$config_action_disabled>Plugineinstellungen speichern</button>
</div>

<div class="settings-subtitle config-subtitle">Einstellungsdatei sichern und wiederherstellen</div>

<div class="config-actions">

<form data-ajax="false" method="get" class="inline-form">
<input data-role="none" type="hidden" name="action" value="download-config">
<button data-role="none" type="submit"$config_action_disabled>Einstellungen exportieren</button>
$info_config_export
</form>

<form data-ajax="false" method="post" enctype="multipart/form-data" class="inline-form">
$csrf_html
<input data-role="none" type="hidden" name="action" value="import-config">
<input data-role="none" class="config-file" type="file" name="settings_file" accept="application/json,.json">
<button data-role="none" type="submit">Einstellungen importieren</button>
$info_config_import
</form>
</div>
</fieldset>

</section>

<section class="panel backups-panel" id="backups">

<h2>Backups $info_table</h2>

<fieldset class="backup-content">
<legend>Verwaltung Backups</legend>

<form data-ajax="false" class="import" method="post" enctype="multipart/form-data">

$csrf_html
<input data-role="none" type="hidden" name="action" value="import">

<input data-role="none" class="config-file" type="file" name="backup_archive" accept="application/gzip,application/x-gzip,.tar.gz,.tgz">

<button data-role="none" type="submit">Externes Backup importieren</button>$info_import

</form>

<table>

<thead>
<tr>
<th>ID</th>
<th>Status</th>
<th>Host</th>
<th>Grösse</th>
<th>Dateien</th>
<th>Fertiggestellt</th>
<th>Export</th>
<th>Aktionen</th>
</tr>
</thead>

<tbody id="backup-list-body">
<tr><td colspan="8" class="empty"><span class="mini-spinner"></span> Backup-Liste wird geladen...</td></tr>
HTML


print <<HTML;
</tbody>
</table>
</fieldset>
HTML

if ($browse_id) {
  my $safe_browse_id = escapeHTML($browse_id);
  my $safe_browse_path = escapeHTML($browse_path || '/');
  my $close_browse_url = base_url_with_active_task() . '#backups';

  print qq{
<div class="subpanel" id="backup-browser">
<div class="detail-header">
<h3>Dateien in Backup <code>$safe_browse_id</code></h3>
<a data-ajax="false" data-skip-scroll-save="1" class="button-link" href="$close_browse_url">Ansicht schliessen</a>
</div>
<p>Pfad: <code>$safe_browse_path</code></p>
<section class="inline-notice warning">Der Datei-Explorer dient nur zur Ansicht des Backup-Inhalts. F&uuml;r eine vollst&auml;ndige Wiederherstellung bitte den Restore-Button des gew&uuml;nschten Backups verwenden. Bei inkrementellen Snapshots sind kleine Gr&ouml;ssen normal: Unver&auml;nderte Dateien werden per Hardlink geteilt und belegen nicht mehrfach Speicher.</section>
};

  if ($browse_error) {
    print qq{<section class="notice error"><pre>$browse_error</pre></section>};
  } elsif ($browse_data && ref($browse_data->{items}) eq 'ARRAY') {
    if (length $browse_path) {
      my @parts = split m{/+}, $browse_path;
      pop @parts;
      my $parent = join '/', @parts;
      my $parent_url = url_with_active_task(browse_id => $browse_id, path => $parent) . '#backup-browser';
      print qq{<p><a href="$parent_url">Eine Ebene höher</a></p>};
    }

    print qq{
<table>
<thead>
<tr>
<th>Name</th>
<th>Typ</th>
<th>Grösse</th>
<th>Aktion</th>
</tr>
</thead>
<tbody>
};

    for my $item (@{$browse_data->{items}}) {
      my $name = escapeHTML($item->{name} || '');
      my $type = escapeHTML($item->{type} || '');
      my $path = $item->{path} || '';
      my $size = int(($item->{size} || 0) / 1024);
      my $open = '-';

      if (($item->{type} || '') eq 'directory') {
        my $url = url_with_active_task(browse_id => $browse_id, path => $path) . '#backup-browser';
        $open = qq{<a href="$url">Öffnen</a>};
      }

      print qq{
<tr>
<td>$name</td>
<td>$type</td>
<td>${size} KB</td>
<td>$open</td>
</tr>
};
    }

    print qq{
</tbody>
</table>
};
  }

  print qq{</div>};
}

print qq{</section>};

if ($restore_id) {
  my $safe_restore_id = escapeHTML($restore_id);
  my $close_restore_url = base_url_with_active_task() . '#backups';
  my $degraded_confirmation = '';
  my $offline_notice = '';
  my $restore_submit_disabled = '';
  if ($restore_check && $restore_check->{requires_degraded_confirmation}) {
    $degraded_confirmation = qq{
<label class="checkline root-confirm">
<input data-role="none" type="checkbox" name="confirm_degraded" value="1" required>
<span>Ich habe den Hinweis verstanden: xattrs und File Capabilities sind in diesem Backup bewusst nicht enthalten.</span>
</label>};
  }
  if ($restore_check && $restore_check->{requires_offline_restore}) {
    $offline_notice = '<section class="inline-notice warning">Dieses Portable Archive kann nicht aus der Weboberfl&auml;che zur&uuml;ckgespielt werden. Starte den Restore in einer Rescue-/Offline-Umgebung mit <code>HOSTBACKUP_OFFLINE_RESTORE=1</code>.</section>';
    $restore_submit_disabled = ' disabled';
  }

  print qq{
<section class="panel restore-panel" id="restore-panel">
<h2>Restore</h2>
<fieldset class="backup-content">
<legend>Wiederherstellung vorbereiten</legend>
<p>Restore nur in Rescue-/Testumgebung verwenden.</p>
<div class="subpanel">
<div class="detail-header">
<h3>Ausgewähltes Backup: <code>$safe_restore_id</code></h3>
<a data-ajax="false" data-skip-scroll-save="1" class="button-link" href="$close_restore_url">Restore-Auswahl schliessen</a>
</div>
};

  if ($restore_error) {
    print qq{<section class="notice error"><pre>$restore_error</pre></section>};
  }

  if ($restore_check) {
    my $check_status = escapeHTML($restore_check->{status} || 'unbekannt');
    print qq{<p><strong>Restore-Check:</strong> $check_status</p>};

    if (ref($restore_check->{warnings}) eq 'ARRAY' && @{$restore_check->{warnings}}) {
      print '<ul class="warnings">';
      for my $warning (@{$restore_check->{warnings}}) {
        print '<li>' . escapeHTML($warning) . '</li>';
      }
      print '</ul>';
    }

    if (ref($restore_check->{notices}) eq 'ARRAY' && @{$restore_check->{notices}}) {
      print '<section class="inline-notice info"><strong>Hinweis:</strong><ul>';
      for my $notice (@{$restore_check->{notices}}) {
        print '<li>' . escapeHTML($notice) . '</li>';
      }
      print '</ul></section>';
    }

    if (ref($restore_check->{checks}) eq 'ARRAY') {
      print '<table class="check-table"><thead><tr><th>Prüfung</th><th>Status</th><th>Wert</th></tr></thead><tbody>';
      for my $check (@{$restore_check->{checks}}) {
        my $name = escapeHTML($check->{name} || '');
        my $ok = $check->{ok} ? 'ok' : 'nicht ok';
        my $value = escapeHTML($check->{value} || '');
        print qq{<tr><td>$name</td><td>$ok</td><td>$value</td></tr>};
      }
      print '</tbody></table>';
    }
  }

  if ($restore_plan) {
    print qq{<pre>$restore_plan</pre>};
  }

  print qq{
<section class="inline-notice warning">Achtung: Ein Restore kann das aktuelle System &uuml;berschreiben und sollte nur mit einem gepr&uuml;ften Backup durchgef&uuml;hrt werden.</section>
<form data-ajax="false" method="post" class="restore-start-form">
$csrf_html
<input data-role="none" type="hidden" name="action" value="restore-backup">
<input data-role="none" type="hidden" name="backup_id" value="$safe_restore_id">
$offline_notice
$degraded_confirmation
<label>
<span>Backup-ID zur Sicherheitsbestätigung eingeben</span>
<input data-role="none" type="text" name="restore_challenge" value="" autocomplete="off" required pattern="[A-Za-z0-9._-]+" placeholder="$safe_restore_id">
</label>
<label class="checkline root-confirm">
<input data-role="none" type="checkbox" name="confirm_restore" value="1" required>
<span>Ich bestätige, dass dieses Backup auf das System zurückgeschrieben werden soll.</span>
</label>
<button data-role="none" class="danger" type="submit"$restore_submit_disabled>Restore starten</button>
</form>
</div>
</fieldset>
</section>
};
}

print <<HTML;

</main>

<script>
function hostbackupEach(nodes, callback) {
  if (!nodes) return;
  for (var i = 0; i < nodes.length; i += 1) {
    callback(nodes[i], i);
  }
}

function hostbackupClosest(node, selector) {
  while (node && node.nodeType !== 1) {
    node = node.parentElement || node.parentNode;
  }
  while (node && node.nodeType === 1) {
    if (node.matches && node.matches(selector)) return node;
    node = node.parentElement;
  }
  return null;
}

(function () {
  var edgePadding = 12;
  var helpers = document.querySelectorAll('.info-help');

  function positionInfoBubble(help) {
    var bubble = help ? help.querySelector('.info-bubble') : null;
    if (!bubble) return;

    bubble.style.marginLeft = '0px';
    bubble.classList.remove('info-bubble-above');

    var rect = bubble.getBoundingClientRect();
    var shift = 0;
    if (rect.right > window.innerWidth - edgePadding) {
      shift -= rect.right - (window.innerWidth - edgePadding);
    }
    if (rect.left + shift < edgePadding) {
      shift += edgePadding - (rect.left + shift);
    }
    bubble.style.marginLeft = shift + 'px';

    rect = bubble.getBoundingClientRect();
    var helpRect = help.getBoundingClientRect();
    if (rect.bottom > window.innerHeight - edgePadding && helpRect.top > rect.height + edgePadding) {
      bubble.classList.add('info-bubble-above');
    }
  }

  hostbackupEach(helpers, function (help) {
    help.addEventListener('mouseenter', function () { positionInfoBubble(help); });
    help.addEventListener('focusin', function () { positionInfoBubble(help); });
    help.addEventListener('click', function (event) {
      var button = help.querySelector('.info-button');
      event.preventDefault();
      event.stopPropagation();
      if (button) button.focus();
      positionInfoBubble(help);
    });
  });

  window.addEventListener('resize', function () {
    hostbackupEach(helpers, function (help) {
      if (help.matches && (help.matches(':hover') || help.contains(document.activeElement))) {
        positionInfoBubble(help);
      }
    });
  });
}());

(function () {
  var input = document.getElementById('backup-root-input');
  if (!input) return;

  function setBackupRoot(path) {
    if (!path) return;
    input.value = path;
    try {
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e) {}
    input.focus();
  }

  document.addEventListener('click', function (event) {
    var button = hostbackupClosest(event.target, '[data-backup-root]');
    if (!button) return;
    event.preventDefault();
    setBackupRoot(button.getAttribute('data-backup-root') || '');
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    var button = hostbackupClosest(event.target, '[data-backup-root]');
    if (!button) return;
    event.preventDefault();
    setBackupRoot(button.getAttribute('data-backup-root') || '');
  });

  document.addEventListener('dragstart', function (event) {
    var button = hostbackupClosest(event.target, '[data-backup-root]');
    if (!button || !event.dataTransfer) return;
    event.dataTransfer.setData('text/plain', button.getAttribute('data-backup-root') || '');
  });

  input.addEventListener('dragover', function (event) {
    event.preventDefault();
  });

  input.addEventListener('drop', function (event) {
    event.preventDefault();
    var path = event.dataTransfer ? event.dataTransfer.getData('text/plain') : '';
    setBackupRoot(path);
  });
}());

(function () {
  var key = 'loxberryhostbackup-scroll';

  function saveScroll(targetId) {
    try {
      sessionStorage.setItem(key, JSON.stringify({
        y: window.pageYOffset || document.documentElement.scrollTop || 0,
        target: targetId || ''
      }));
    } catch (e) {}
  }

  function restoreScroll() {
    var data = null;
    try {
      data = JSON.parse(sessionStorage.getItem(key) || 'null');
      sessionStorage.removeItem(key);
    } catch (e) {
      data = null;
    }

    var hashTarget = window.location.hash ? window.location.hash.replace(/^#/, '') : '';
    var targetId = hashTarget || (data && data.target ? data.target : '');
    var y = data && typeof data.y === 'number' ? data.y : null;

    window.setTimeout(function () {
      var target = targetId ? document.getElementById(targetId) : null;
      if (target) {
        target.scrollIntoView({ block: 'start' });
      } else if (y !== null) {
        window.scrollTo(0, y);
      }
    }, 80);

    window.setTimeout(function () {
      if (!targetId && y !== null) {
        window.scrollTo(0, y);
      }
    }, 450);
  }

  document.addEventListener('submit', function (event) {
    var form = hostbackupClosest(event.target, 'form');
    if (!form) return;
    saveScroll(form.getAttribute('data-return-anchor') || '');
  }, true);

  document.addEventListener('click', function (event) {
    var link = hostbackupClosest(event.target, 'a');
    if (!link) return;
    if (link.getAttribute('data-skip-scroll-save') === '1') return;
    var href = link.getAttribute('href') || '';
    if (!href || href.indexOf('javascript:') === 0 || href.indexOf('#') === 0) return;
    if (link.hostname && link.hostname !== window.location.hostname) return;
    saveScroll('');
  }, true);

  restoreScroll();
}());

(function () {
  var overlay = document.getElementById('loading-overlay');
  var loadingText = document.getElementById('loading-text');

  function showLoading(text) {
    if (loadingText) loadingText.textContent = text || 'Aktion wird ausgeführt...';
    if (overlay) overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('is-loading');
  }

  window.hostbackupShowLoading = showLoading;

  hostbackupEach(document.querySelectorAll('form'), function (form) {
    form.addEventListener('submit', function (event) {
      if (form.hasAttribute('data-skip-loading')) return;
      if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
      var actionInput = form.querySelector('input[name="action"]');
      var action = actionInput ? actionInput.value : '';
      var messages = {
        'save-config': 'Einstellungen werden gespeichert...',
        'import-config': 'Einstellungen werden importiert...',
        'import': 'Backup-Import wird gestartet...',
        'start-export': 'Export wird im Hintergrund gestartet...',
        'delete-export': 'Export-Archiv wird gelöscht...',
        'delete-backup': 'Backup wird gelöscht. Bei grossen Backups kann das einige Minuten dauern...',
        'download-export': 'Export wird vorbereitet...',
        'restore-backup': 'Restore wird vorbereitet...',
        'stop-backup': 'Backup wird gestoppt...',
        'download-config': 'Einstellungen werden exportiert...'
      };
      if (action === 'backup') return;
      window.setTimeout(function () {
        if (!event.defaultPrevented) {
          showLoading(messages[action] || 'Aktion wird ausgeführt...');
        }
      }, 0);
    });
  });
}());

(function () {
  var targetNotice = document.getElementById('target-notice');
  var backupListBody = document.getElementById('backup-list-body');
  var stopTargetsList = document.getElementById('stop-targets-list');
  var monitor = document.getElementById('task-monitor');
  var activeTask = monitor ? monitor.getAttribute('data-active-task') : '';
  var fragmentBaseUrl = window.location.pathname;

  function fragmentUrl(action, extra) {
    return fragmentBaseUrl + '?action=' + encodeURIComponent(action) + (extra || '') + '&_=' + Date.now();
  }

  function loadFragment(url, target, fallback) {
    if (!target) return;

    fetch(url, { cache: 'no-store' })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.text();
      })
      .then(function (html) {
        target.innerHTML = html;
      })
      .catch(function () {
        target.innerHTML = fallback;
      });
  }

  loadFragment(
    fragmentUrl('target-notice', ''),
    targetNotice,
    '<section class="inline-notice error"><strong>Technischer Fehler:</strong> Dateisystem-Pr&uuml;fung konnte nicht geladen werden.</section>'
  );

  loadFragment(
    fragmentUrl('backup-list', activeTask ? '&active_task=' + encodeURIComponent(activeTask) : ''),
    backupListBody,
    '<tr><td colspan="8" class="empty">Backup-Liste konnte nicht geladen werden.</td></tr>'
  );

  loadFragment(
    fragmentUrl('stop-targets', ''),
    stopTargetsList,
    '<p class="empty">Dienste und Container konnten nicht geladen werden.</p>'
  );
}());

(function () {
  var stopTargetsList = document.getElementById('stop-targets-list');
  if (!stopTargetsList) return;

  stopTargetsList.addEventListener('click', function (event) {
    var node = event.target;

    while (node && node !== stopTargetsList) {
      if (node.getAttribute && node.getAttribute('data-stop-target-preset')) {
        var mode = node.getAttribute('data-stop-target-preset');
        var boxes = stopTargetsList.querySelectorAll('input[name="stop_targets"]');

        hostbackupEach(boxes, function (box) {
          box.checked = mode === 'recommended'
            ? box.getAttribute('data-recommended') === '1'
            : false;
        });

        if (mode === 'recommended') {
          hostbackupEach(stopTargetsList.querySelectorAll('details.stop-target-group'), function (detail) {
            detail.open = !!detail.querySelector('input[name="stop_targets"]:checked');
          });
        }

        return;
      }

      node = node.parentNode;
    }
  });
}());

(function () {
  document.addEventListener('submit', function (event) {
    var deleteForm = hostbackupClosest(event.target, '.delete-backup-form');
    if (deleteForm) {
      var idInput = deleteForm.querySelector('input[name="backup_id"]');
      var backupId = idInput ? idInput.value : 'dieses Backup';
      if (!window.confirm('Backup ' + backupId + ' wirklich dauerhaft löschen?\\n\\nBei grossen Backups oder langsamen Datenträgern kann das Löschen mehrere Minuten dauern. Bitte danach warten, bis die Aktion abgeschlossen ist.')) {
        event.preventDefault();
      } else if (window.hostbackupShowLoading) {
        window.hostbackupShowLoading('Backup wird gelöscht. Bei grossen Backups kann das einige Minuten dauern...');
      }
      return;
    }

    var deleteExportForm = hostbackupClosest(event.target, '.delete-export-form');
    if (deleteExportForm) {
      var exportIdInput = deleteExportForm.querySelector('input[name="backup_id"]');
      var exportBackupId = exportIdInput ? exportIdInput.value : 'dieses Backup';
      if (!window.confirm('Nur das tar.gz-Exportarchiv von Backup ' + exportBackupId + ' löschen?\\n\\nDer eigentliche Backup-Snapshot bleibt erhalten und kann später erneut exportiert werden.')) {
        event.preventDefault();
      } else if (window.hostbackupShowLoading) {
        window.hostbackupShowLoading('Export-Archiv wird gelöscht...');
      }
      return;
    }

    var restoreForm = hostbackupClosest(event.target, '.restore-start-form');
    if (restoreForm) {
      var restoreInput = restoreForm.querySelector('input[name="backup_id"]');
      var restoreId = restoreInput ? restoreInput.value : 'dieses Backup';
      if (!window.confirm('Restore von Backup ' + restoreId + ' wirklich starten? Das schreibt Systemdateien zurueck.')) {
        event.preventDefault();
      } else if (window.hostbackupShowLoading) {
        window.hostbackupShowLoading('Restore wird vorbereitet...');
      }
    }
  });
}());

(function () {
  var modeInputs = document.querySelectorAll('input[name="schedule_mode"]');
  var panels = document.querySelectorAll('[data-schedule-panel]');
  var allMonths = document.querySelector('input[name="schedule_months"][value="*"]');
  var monthInputs = document.querySelectorAll('input[name="schedule_months"]:not([value="*"])');

  function selectedMode() {
    var checked = document.querySelector('input[name="schedule_mode"]:checked');
    return checked ? checked.value : 'daily';
  }

  function updateSchedulePanels() {
    var mode = selectedMode();
    hostbackupEach(panels, function (panel) {
      panel.classList.toggle('schedule-hidden', panel.getAttribute('data-schedule-panel') !== mode);
    });
  }

  function updateMonthSelection() {
    if (!allMonths) return;
    hostbackupEach(monthInputs, function (input) {
      input.disabled = allMonths.checked;
      if (allMonths.checked) input.checked = false;
    });
  }

  hostbackupEach(modeInputs, function (input) {
    input.addEventListener('change', updateSchedulePanels);
  });
  if (allMonths) {
    allMonths.addEventListener('change', updateMonthSelection);
  }
  hostbackupEach(monthInputs, function (input) {
    input.addEventListener('change', function () {
      if (input.checked && allMonths) {
        allMonths.checked = false;
        updateMonthSelection();
      }
    });
  });

  updateSchedulePanels();
  updateMonthSelection();
}());

(function () {
  var form = document.getElementById('settings-save-form');
  var popup = document.getElementById('settings-change-popup');
  var changeList = document.getElementById('settings-change-list');
  var stopTargetsList = document.getElementById('stop-targets-list');
  if (!form || !popup || !changeList) return;

  var ignoredNames = {
    action: true,
    csrf_token: true,
    stop_docker_before_backup: true,
    stop_targets_loaded: true
  };
  var initialStates = {};
  var changedAt = {};
  var valueSeparator = String.fromCharCode(31);
  var fieldLabels = {
    backup_root: 'Backup-Verzeichnis',
    keep_backups: 'Anzahl Backups behalten',
    metadata_mode: 'Metadaten-Profil',
    backup_mode: 'Backup-Modus',
    schedule_enabled: 'Automatische Backups',
    schedule_mode: 'Zeitplan',
    schedule_time: 'Startzeit',
    schedule_weekdays: 'Wochentage',
    schedule_monthdays: 'Monatstage',
    schedule_months: 'Monate',
    pre_backup_hook: 'Skript vor dem Backup',
    post_backup_hook: 'Skript nach dem Backup',
    rsync_extra_excludes: 'Zusätzliche Ausschlüsse',
    root_permission_ack: 'Root-Freigabe',
    mail_notify_enabled: 'Mailbenachrichtigung',
    mail_notify_to: 'Mailadresse',
    mail_notify_success: 'Mail bei Erfolg',
    mail_notify_failure: 'Mail bei Fehler',
    mail_notify_stopped: 'Mail bei Abbruch',
    mail_notify_restore: 'Mail bei Restore',
    stop_targets: 'Zu stoppende Dienste/Container',
    create_export_after_backup: 'Export nach dem Backup'
  };
  var valueLabels = {
    metadata_mode: {
      'native-strict': 'Native Strict',
      'network-compatible': 'Network Compatible',
      'fake-super': 'Fake Super',
      'portable-archive': 'Portable Archive'
    },
    backup_mode: {
      full: 'Volles Backup',
      snapshot: 'Inkrementeller Snapshot'
    },
    schedule_mode: {
      daily: 'Täglich',
      weekly: 'Wöchentlich',
      monthly: 'Monatlich'
    }
  };
  var booleanNames = {
    schedule_enabled: true,
    root_permission_ack: true,
    mail_notify_enabled: true,
    mail_notify_success: true,
    mail_notify_failure: true,
    mail_notify_stopped: true,
    mail_notify_restore: true,
    create_export_after_backup: true
  };
  var weekdayLabels = {
    '0': 'So', '1': 'Mo', '2': 'Di', '3': 'Mi', '4': 'Do', '5': 'Fr', '6': 'Sa'
  };
  var monthLabels = {
    '1': 'Jan', '2': 'Feb', '3': 'Mär', '4': 'Apr', '5': 'Mai', '6': 'Jun',
    '7': 'Jul', '8': 'Aug', '9': 'Sep', '10': 'Okt', '11': 'Nov', '12': 'Dez'
  };

  function namedControls(name) {
    var controls = form.querySelectorAll('[name]');
    var matches = [];
    hostbackupEach(controls, function (control) {
      if (control.name === name) matches.push(control);
    });
    return matches;
  }

  function relevantName(control) {
    if (!control || !control.name || ignoredNames[control.name]) return '';
    if (control.type === 'hidden' || control.type === 'submit' || control.type === 'button' || control.type === 'file') return '';
    return control.name;
  }

  function stateFor(name) {
    var controls = namedControls(name);
    if (!controls.length) return '';
    var type = (controls[0].type || '').toLowerCase();
    if (type === 'radio') {
      var selected = '';
      hostbackupEach(controls, function (control) {
        if (control.checked) selected = control.value;
      });
      return selected;
    }
    if (type === 'checkbox') {
      if (controls.length === 1) return controls[0].checked ? '1' : '0';
      var selectedValues = [];
      hostbackupEach(controls, function (control) {
        if (control.checked) selectedValues.push(control.value);
      });
      selectedValues.sort();
      return selectedValues.join(valueSeparator);
    }
    return controls[0].value || '';
  }

  function captureInitialState(name) {
    if (!name || Object.prototype.hasOwnProperty.call(initialStates, name)) return;
    initialStates[name] = stateFor(name);
  }

  function captureCurrentControls() {
    hostbackupEach(form.querySelectorAll('[name]'), function (control) {
      captureInitialState(relevantName(control));
    });
  }

  function selectedValues(state) {
    return state ? state.split(valueSeparator) : [];
  }

  function displayValue(name, state) {
    if (valueLabels[name] && valueLabels[name][state]) return valueLabels[name][state];
    if (booleanNames[name]) return state === '1' ? 'Aktiviert' : 'Deaktiviert';
    if (name === 'schedule_weekdays') {
      return selectedValues(state).map(function (value) { return weekdayLabels[value] || value; }).join(', ') || 'Keine Auswahl';
    }
    if (name === 'schedule_monthdays') {
      return selectedValues(state).join(', ') || 'Keine Auswahl';
    }
    if (name === 'schedule_months') {
      if (state === '*') return 'Alle Monate';
      return selectedValues(state).map(function (value) { return monthLabels[value] || value; }).join(', ') || 'Keine Auswahl';
    }
    if (name === 'stop_targets') {
      var targetCount = selectedValues(state).length;
      return targetCount === 1 ? '1 Ziel ausgewählt' : targetCount + ' Ziele ausgewählt';
    }
    if (name === 'rsync_extra_excludes') {
      var excludeCount = state.split(/\\r?\\n/).filter(function (line) { return line.trim() !== ''; }).length;
      return excludeCount === 1 ? '1 Eintrag' : excludeCount + ' Einträge';
    }
    if (name === 'pre_backup_hook' || name === 'post_backup_hook') return state ? 'Eingetragen' : 'Leer';
    if (!state) return 'Leer';
    return state.length > 80 ? state.substring(0, 77) + '...' : state;
  }

  function formatTime(date) {
    function pad(number) { return number < 10 ? '0' + number : String(number); }
    return pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
  }

  function renderPopup() {
    var names = Object.keys(changedAt).sort(function (left, right) {
      return changedAt[left].getTime() - changedAt[right].getTime();
    });
    changeList.innerHTML = '';

    hostbackupEach(names, function (name) {
      var item = document.createElement('li');
      var copy = document.createElement('span');
      var label = document.createElement('strong');
      var value = document.createElement('small');
      var time = document.createElement('time');
      label.textContent = fieldLabels[name] || name;
      value.textContent = displayValue(name, stateFor(name));
      time.textContent = 'geändert ' + formatTime(changedAt[name]);
      time.setAttribute('datetime', changedAt[name].toISOString());
      copy.appendChild(label);
      copy.appendChild(value);
      item.appendChild(copy);
      item.appendChild(time);
      changeList.appendChild(item);
    });

    var visible = names.length > 0;
    popup.classList.toggle('is-visible', visible);
    popup.setAttribute('aria-hidden', visible ? 'false' : 'true');
  }

  function refreshName(name) {
    if (!name) return;
    captureInitialState(name);
    if (stateFor(name) === initialStates[name]) {
      delete changedAt[name];
    } else {
      changedAt[name] = new Date();
    }
    renderPopup();
  }

  captureCurrentControls();

  form.addEventListener('input', function (event) {
    refreshName(relevantName(event.target));
  });
  form.addEventListener('change', function (event) {
    refreshName(relevantName(event.target));
  });

  if (stopTargetsList && window.MutationObserver) {
    new MutationObserver(function () {
      captureInitialState('stop_targets');
    }).observe(stopTargetsList, { childList: true, subtree: true });
  }

  document.addEventListener('click', function (event) {
    if (!hostbackupClosest(event.target, '[data-stop-target-preset]')) return;
    window.setTimeout(function () { refreshName('stop_targets'); }, 0);
  });
}());

(function () {
  var monitor = document.getElementById('task-monitor');
  if (!monitor) return;

  var task = monitor.getAttribute('data-active-task');
  var stateEl = document.getElementById('task-state');
  var heartbeatEl = document.getElementById('task-heartbeat');
  var logEl = document.getElementById('task-log');
  var stopForm = document.getElementById('stop-task-form');
  var page = document.getElementById('hostbackup-app');
  var csrfToken = page ? (page.getAttribute('data-csrf-token') || '') : '';
  var timer = null;
  var refreshScheduled = false;
  var inFlight = false;
  var pollFailures = 0;

  function setState(state, text) {
    stateEl.className = 'task-state state-' + state;
    stateEl.textContent = text;
  }

  function decodeLog(value) {
    if (!value) return '';
    try {
      return decodeURIComponent(escape(window.atob(value)));
    } catch (e) {
      try {
        return window.atob(value);
      } catch (ignored) {
        return '';
      }
    }
  }

  function normalizeLogForDisplay(value) {
    var text = String(value || '');
    var newline = String.fromCharCode(10);
    text = text.split(String.fromCharCode(13, 10)).join(newline);
    text = text.split(String.fromCharCode(13)).join(newline);
    return text.replace(new RegExp(String.fromCharCode(27) + '\\\\[[0-?]*[ -/]*[@-~]', 'g'), '');
  }

 function backupIdFromTask() {
   var value = task || '';
   if (value.indexOf('backup-') !== 0) return '';
   if (value.slice(-4) !== '.log') return '';
   return value.slice(7, -4);
 }

  function taskKind() {
    if ((task || '').indexOf('restore-') === 0) return 'restore';
    if ((task || '').indexOf('export-') === 0) return 'export';
    if ((task || '').indexOf('import-') === 0) return 'import';
    return 'backup';
  }

  function taskName() {
    var kind = taskKind();
    if (kind === 'restore') return 'Restore';
    if (kind === 'export') return 'Export';
    if (kind === 'import') return 'Import';
    return 'Backup';
  }

  function redirectWithMessage(message) {
    window.location.href = window.location.pathname + '?msg=' + encodeURIComponent(message);
  }

  function deleteStoppedBackup(backupId) {
    var form = document.createElement('form');
    var action = document.createElement('input');
    var id = document.createElement('input');
    var csrf = document.createElement('input');
    form.method = 'post';
    form.action = window.location.pathname;
    action.type = 'hidden';
    action.name = 'action';
    action.value = 'delete-backup';
    id.type = 'hidden';
    id.name = 'backup_id';
    id.value = backupId;
    csrf.type = 'hidden';
    csrf.name = 'csrf_token';
    csrf.value = csrfToken;
    form.appendChild(action);
    form.appendChild(id);
    form.appendChild(csrf);
    document.body.appendChild(form);
    if (window.hostbackupShowLoading) {
      window.hostbackupShowLoading('Unfertiges Backup wird gelöscht. Bei grossen Backups kann das einige Minuten dauern...');
    }
    form.submit();
  }

  function renderStatus(data) {
    pollFailures = 0;
    inFlight = false;
    var state = data.state || 'running';
    var labels = {
      running: task.indexOf('restore-') === 0 ? 'Restore läuft' : 'Backup läuft',
      finished: 'Backup abgeschlossen',
      failed: 'Backup fehlgeschlagen',
      cleanup_failed: 'Backup fehlgeschlagen; Wiederanlauf unvollständig',
      stopped: 'Backup gestoppt',
      stale: 'Keine neue Logausgabe',
      error: 'Status nicht verfügbar'
    };

    if (task.indexOf('restore-') === 0) {
      labels.finished = 'Restore abgeschlossen';
      labels.failed = 'Restore fehlgeschlagen';
    }

    labels.running = taskName() + ' läuft';
    labels.finished = taskName() + ' abgeschlossen';
    labels.failed = taskName() + ' fehlgeschlagen';
    labels.cleanup_failed = taskName() + ' fehlgeschlagen; Wiederanlauf unvollständig';
    labels.stopped = taskName() + ' gestoppt';
    setState(state, labels[state] || state);

    if (state === 'finished') {
      heartbeatEl.textContent = taskName() + ' abgeschlossen. Die Ansicht wird aktualisiert.';
    } else if (state === 'failed' || state === 'cleanup_failed') {
      heartbeatEl.textContent = taskName() + ' fehlgeschlagen. Bitte Logausgabe und Cleanup-Status prüfen.';
    } else if (state === 'stopped') {
      heartbeatEl.textContent = taskName() + ' gestoppt. Der Wiederanlauf wurde geprüft; Details stehen im Log.';
    } else if (data.now && data.mtime) {
      var age = Math.max(0, Number(data.now) - Number(data.mtime));
      heartbeatEl.textContent = (data.phase ? 'Phase: ' + data.phase + '. ' : '') + 'Letzte Log-Aktualisierung vor ' + age + ' Sekunden.';
    } else {
      heartbeatEl.textContent = 'Warte auf Logausgabe für ' + taskName() + '.';
    }

    if (data.error) {
      logEl.textContent = data.error;
    } else {
      logEl.textContent = normalizeLogForDisplay(decodeLog(data.content_b64)) || taskName() + ' wurde gestartet. Die Logdatei wird vorbereitet...';
    }

    logEl.scrollTop = logEl.scrollHeight;

    if (state === 'finished' || state === 'failed' || state === 'cleanup_failed' || state === 'stopped') {
      if (stopForm) stopForm.classList.add('task-monitor-idle');
      window.clearInterval(timer);
      if (!refreshScheduled) {
        refreshScheduled = true;
        if (state === 'finished' || state === 'stopped') {
          window.setTimeout(function () {
            var backupId = backupIdFromTask();
            if (state === 'stopped' && backupId) {
              if (window.confirm('Das Backup wurde gestoppt und ist unvollständig. Soll dieses unfertige Backup jetzt gelöscht werden?\\n\\nBei grossen Backups oder langsamen Datenträgern kann das Löschen mehrere Minuten dauern.')) {
                deleteStoppedBackup(backupId);
              } else {
                redirectWithMessage('backup_stop_requested');
              }
              return;
            }
            var kind = taskKind();
            redirectWithMessage(kind === 'restore' ? 'restore_finished' : kind === 'export' ? 'export_finished' : kind === 'import' ? 'import_finished' : 'backup_finished');
          }, 2500);
        }
      }
    }
  }

  if (stopForm) {
    stopForm.addEventListener('submit', function (event) {
      if (!window.confirm('Backup wirklich stoppen? Dienste und Docker-Container, die dieses Backup bereits gestoppt hat, werden anschliessend anhand der Restart-Liste wieder gestartet.')) {
        event.preventDefault();
      }
    });
  }

  function poll() {
    if (inFlight) return;
    inFlight = true;
    fetch('?action=task-status&task=' + encodeURIComponent(task) + '&_=' + Date.now(), { cache: 'no-store' })
      .then(function (response) { return response.text(); })
      .then(function (text) {
        renderStatus(JSON.parse(text));
      })
      .catch(function () {
        inFlight = false;
        pollFailures += 1;
        setState(pollFailures >= 3 ? 'error' : 'stale', pollFailures >= 3 ? 'Status nicht verfügbar' : 'Status wird erneut gelesen');
        heartbeatEl.textContent = 'Der Live-Status für ' + taskName() + ' konnte gerade nicht gelesen werden. Der Task kann trotzdem weiterlaufen; es wird automatisch erneut versucht.';
      });
  }

  if (!task) {
    monitor.classList.add('task-monitor-idle');
    if (stopForm) stopForm.classList.add('task-monitor-idle');
    return;
  }

  monitor.classList.remove('task-monitor-idle');
  if (stopForm && taskKind() !== 'backup') stopForm.classList.add('task-monitor-idle');
  heartbeatEl.textContent = 'Live-Status wird geladen...';
  setState('running', taskName() + ' läuft');
  logEl.textContent = taskName() + ' wurde gestartet. Warte auf erste Logausgabe...';
  poll();
  timer = window.setInterval(poll, 5000);
}());
</script>

HTML

LoxBerry::Web::lbfooter();
