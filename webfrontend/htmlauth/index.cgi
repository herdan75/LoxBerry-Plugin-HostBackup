#!/usr/bin/perl
use strict;
use warnings;
use CGI qw(:standard escapeHTML);
use File::Temp qw(tempfile);
use File::Copy qw(copy);
use File::Basename qw(basename);
use JSON::PP;
use LoxBerry::Web;

my $plugin = 'loxberryhostbackup';
my $lbhome = $ENV{LBHOMEDIR} || '/opt/loxberry';
my $bindir = $ENV{LBPBINDIR} || "$lbhome/bin/plugins/$plugin";
my $backend = "$bindir/hostbackup.sh";
my $q = CGI->new;

my $action = $q->param('action') || '';
my $backup_id = $q->param('backup_id') || '';
my $browse_path = $q->param('path') || '';
my $task = $q->param('task') || '';
my $restore_id = $q->param('restore_id') || '';
my $browse_id = $q->param('browse_id') || '';

my $message = '';
my $error = '';
my $active_task = '';

sub url_escape {
  my ($value) = @_;
  $value //= '';
  $value =~ s/([^A-Za-z0-9_.~-])/sprintf("%%%02X", ord($1))/ge;
  return $value;
}

sub redirect_with {
  my (%params) = @_;
  my @parts;
  for my $key (sort keys %params) {
    next unless defined $params{$key} && length $params{$key};
    push @parts, url_escape($key) . '=' . url_escape($params{$key});
  }
  my $uri = $q->url(-relative => 1);
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
  return qq{<span class="info-help"><button data-role="none" type="button" class="info-button">i</button><span class="info-bubble">$safe</span></span>};
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
} elsif ($notice eq 'backup_imported') {
  $message = 'Backup importiert.';
} elsif ($notice eq 'config_imported') {
  $message = 'Einstellungen importiert.';
} elsif ($notice eq 'restore_started') {
  $message = 'Restore gestartet. Der Live-Status wird unten automatisch aktualisiert.';
} elsif ($notice eq 'backup_finished') {
  $message = 'Backup abgeschlossen. Die Backup-Liste wurde aktualisiert.';
} elsif ($notice eq 'restore_finished') {
  $message = 'Restore abgeschlossen.';
}

my $requested_active_task = $q->param('active_task') || '';
if ($requested_active_task =~ /^(backup|restore)-[A-Za-z0-9._-]+\.log$/) {
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

  my ($status, $out) = run_shell(backend_cmd('export', $download_id));

  if ($status != 0) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '500 Internal Server Error');
    print $out;
    exit;
  }

  my ($archive) = $out =~ m{^(/[^\r\n]+\.tar\.gz)\s*$}m;

  if (!$archive || !-r $archive || !-f $archive) {
    print header(-type => 'text/plain', -charset => 'utf-8', -status => '404 Not Found');
    print "Export-Archiv konnte nicht gelesen werden.\n";
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

  if ($action eq 'import-config') {

    my $upload = $q->upload('settings_file');

    if (!$upload) {
      $error = 'Keine Einstellungsdatei ausgewählt.';
    } else {
      binmode $upload;
      local $/;
      my $settings_json = <$upload>;
      my $imported = eval { decode_json($settings_json) };

      if (!$imported || ref($imported) ne 'HASH') {
        $error = 'Einstellungsdatei konnte nicht gelesen werden. Erwartet wird eine JSON-Datei aus diesem Plugin.';
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
        my $root_permission_ack = bool_arg($imported->{root_permission_ack});
        my $backup_mode = $imported->{backup_mode} || 'full';
        my $stop_targets = stop_targets_csv($imported->{stop_targets});

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
            $stop_targets
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
        $stop_targets
      )
    );

    if ($status == 0) {
      redirect_with(msg => 'saved');
    } else {
      $error = escapeHTML($out);
    }
  }

  elsif ($action eq 'backup') {

    my ($status, $out) = run_shell(backend_cmd('start'));

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

  elsif ($action eq 'import') {

    my $upload = $q->upload('backup_archive');

    if (!$upload) {
      $error = 'Keine Backup-Datei ausgewählt.';
    } else {
      my ($fh, $tmpfile) = tempfile('hostbackup-import-XXXXXX', SUFFIX => '.tar.gz', TMPDIR => 1, UNLINK => 1);
      binmode $fh;
      binmode $upload;
      copy($upload, $fh);
      close $fh;

      my ($status, $out) = run_shell(backend_cmd('import', $tmpfile));

      if ($status == 0) {
        redirect_with(msg => 'backup_imported');
      } else {
        $error = escapeHTML($out);
      }
    }
  }

  elsif ($action eq 'restore-backup') {

    my $restore_backup_id = $q->param('backup_id') || '';
    my $confirm_restore = $q->param('confirm_restore') ? 1 : 0;

    if ($restore_backup_id !~ /^[A-Za-z0-9._-]+$/) {
      $error = 'Ungültige Backup-ID.';
    } elsif (!$confirm_restore) {
      $error = 'Restore muss ausdrücklich bestätigt werden.';
    } else {
      my ($check_status, $check_out) = run_shell(backend_cmd('preflight-restore', $restore_backup_id));
      my $check = $check_status == 0 ? eval { decode_json($check_out) } : undef;

      if ($check_status != 0 || !$check || (($check->{status} || '') eq 'error')) {
        $error = escapeHTML($check_out || 'Restore-Check fehlgeschlagen.');
      } else {
        my ($status, $out) = run_shell(backend_cmd('start-restore', $restore_backup_id));

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

if ($config_status == 0) {
  $config = eval { decode_json($config_json) } || {};
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
my $cfg_keep = escapeHTML($config->{keep_backups} || '10');
my $cfg_pre_hook = escapeHTML($config->{pre_backup_hook} || '');
my $cfg_post_hook = escapeHTML($config->{post_backup_hook} || '');
my $cfg_excludes = escapeHTML(join "\n", @{$config->{rsync_extra_excludes} || []});

my $cfg_create_export = checked_attr($config->{create_export_after_backup});
my $cfg_schedule_enabled = checked_attr($config->{schedule_enabled});
my $cfg_root_permission_ack = checked_attr($config->{root_permission_ack});

my $cfg_schedule_time = escapeHTML($config->{schedule_time} || '02:00');
my $active_task_attr = escapeHTML($active_task);

my $cfg_mode = $config->{schedule_mode} || 'daily';

my $daily_checked = $cfg_mode eq 'daily' ? ' checked' : '';
my $weekly_checked = $cfg_mode eq 'weekly' ? ' checked' : '';
my $monthly_checked = $cfg_mode eq 'monthly' ? ' checked' : '';
my $full_mode_checked = $cfg_backup_mode eq 'snapshot' ? '' : ' checked';
my $snapshot_mode_checked = $cfg_backup_mode eq 'snapshot' ? ' checked' : '';
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

my $info_backup_root = info_button('Hier legst du fest, wohin die Backups geschrieben werden. Für ein echtes Host-Backup sollte das ein externer Datenträger, ein separates Mount oder ein grosser zweiter Datenspeicher sein. Wenn die Systemkarte selbst ausfällt, hilft ein Backup auf derselben Karte nicht.');
my $info_backup_mode = info_button('Vollbackup kopiert jeden Stand vollständig. Inkrementeller Snapshot nutzt rsync mit Hardlinks auf das vorherige vollständige Backup: jedes Backup bleibt einzeln wiederherstellbar, unveränderte Dateien benötigen aber kaum zusätzlichen Speicher. Für zuverlässige Speicherersparnis wird ein Linux-Dateisystem wie ext4 empfohlen.');
my $info_retention = info_button('Legt fest, wie viele fertige Backups behalten werden. Erlaubt sind 1 bis 10. Bei inkrementellen Snapshots ist das Löschen alter Backups sicher: unveränderte Dateien sind per Hardlink in jedem Snapshot sichtbar. Wird ein alter Snapshot entfernt, bleiben Dateien erhalten, solange sie noch von einem jüngeren Snapshot referenziert werden. Sobald nach einem erfolgreichen Backup mehr Backups vorhanden sind als erlaubt, entfernt das Plugin automatisch das älteste fertige Backup und das passende Export-Archiv.');
my $info_schedule = info_button('Der Zeitplan erstellt Backups automatisch per Cron. Täglich bedeutet jeden Tag zur Startzeit. Wöchentlich bedeutet an den gewählten Wochentagen zur Startzeit. Monatlich bedeutet an den gewählten Tagen in den gewählten Monaten zur Startzeit.');
my $info_time = info_button('Diese Uhrzeit gilt für alle Zeitplanarten. Bei täglich ist sie die einzige zeitliche Einstellung. Bei wöchentlich und monatlich wird sie mit den gewählten Tagen kombiniert.');
my $info_weekdays = info_button('Nur bei wöchentlichen Backups relevant. Du kannst einen oder mehrere Wochentage auswählen, zum Beispiel Montag und Freitag. An jedem gewählten Tag startet ein Backup zur angegebenen Startzeit.');
my $info_monthdays = info_button('Nur bei monatlichen Backups relevant. Du kannst einen oder mehrere Kalendertage auswählen, zum Beispiel 1, 15 oder 31. Wenn ein gewählter Tag im aktuellen Monat nicht existiert, läuft das Backup automatisch am letzten Tag dieses Monats. Beispiel: 31 wird im Februar am 28. oder 29. und in Monaten mit 30 Tagen am 30. ausgeführt.');
my $info_months = info_button('Nur bei monatlichen Backups relevant. Mit Alle Monate läuft der Monatsplan jeden Monat. Alternativ kannst du einzelne Monate wählen, zum Beispiel Jan, Apr, Jul und Okt für Quartalsbackups.');
my $info_pre_hook = info_button('Optionales Skript, das direkt vor dem Backup ausgeführt wird. Sinnvoll für Datenbank-Dumps oder das Vorbereiten von Diensten. Das Skript muss absolut angegeben werden und wird aus Sicherheitsgründen nur ausgeführt, wenn es Root gehört und nicht durch andere Benutzer beschreibbar ist.');
my $info_post_hook = info_button('Optionales Skript, das nach dem Backup ausgeführt wird. Sinnvoll zum Aufräumen, Dienste wieder in einen gewünschten Zustand zu bringen oder Benachrichtigungen auszuführen. Es gelten dieselben Sicherheitsregeln wie beim Skript vor dem Backup.');
my $info_excludes = info_button('Hier kannst du Pfade vom rsync-Backup ausschliessen, je ein Pfad pro Zeile. Das ist sinnvoll für grosse Medienarchive, Netzwerkshares oder Daten, die separat gesichert werden. Zu viele Ausschlüsse können aber die Wiederherstellung unvollständig machen.');
my $info_stop_targets = info_button('Wähle gezielt Docker-Container oder sicher steuerbare Dienste aus, die vor dem Backup angehalten und danach wieder gestartet werden. Kritische LoxBerry-, Web-, SSH- und Backup-Dienste werden nicht angeboten. LoxBerry-Plugins ohne eigenen Dienst werden hier nicht aufgeführt und nicht hart beendet; dafür sind Pre-/Post-Backup-Hooks der sichere Weg.');
my $info_export = info_button('Erstellt nach jedem Backup zusätzlich ein komprimiertes tar.gz-Archiv. Das ist praktisch zum Download, Kopieren oder Archivieren, benötigt aber zusätzlichen Speicherplatz und Zeit.');
my $info_root = info_button('Diese Bestätigung ist nötig, weil Vollbackup und Restore Systemdateien, Berechtigungen, Docker-Daten und Cronjobs betreffen. Es werden keine Passwörter gespeichert; erlaubt wird nur der Start des Backend-Skripts dieses Plugins.');
my $info_config_export = info_button('Lädt nur die Einstellungen dieses Plugins als kleine JSON-Datei herunter. Enthalten sind zum Beispiel Backup-Verzeichnis, Ausschlüsse, Zeitplan und ausgewählte Stop-Ziele, aber keine Backup-Daten und keine Passwörter.');
my $info_config_import = info_button('Liest eine zuvor exportierte Einstellungsdatei wieder ein. Das ist praktisch nach einer Neuinstallation des Plugins. Danach bitte Pfade und Root-Freigabe kurz prüfen und speichern, falls sich Laufwerke geändert haben.');
my $info_table = info_button('Diese Liste zeigt vorhandene Backups mit Status, Host, Grösse und Fertigstellungszeit. Ein vollständiges Backup sollte den Status complete haben, bevor du es für Restore-Tests verwendest.');
my $info_import = info_button('Importiert ein extern gespeichertes Backup-Archiv im Format tar.gz, zum Beispiel von deinem PC, NAS oder einem anderen Datenträger. Für Restore eines bereits unten gelisteten Backups brauchst du diese Datei-Auswahl nicht.');
my $info_delete = info_button('Löscht den Backup-Ordner und ein eventuell vorhandenes Export-Archiv dieses Backups. Das kann nicht rückgängig gemacht werden.');
my $info_restore = info_button('Wählt dieses Backup für eine Wiederherstellung aus. Danach wird unterhalb der Backup-Liste die Restore-Prüfung mit Bestätigung und Startbutton für genau dieses Backup eingeblendet.');
my $info_browse = info_button('Öffnet den Datei-Explorer für dieses Backup. Damit kannst du prüfen, welche Dateien im Backup enthalten sind.');
my $info_browse_pending = info_button('Dieses Backup ist noch nicht vollständig abgeschlossen. Dateien, Restore und Export werden erst freigegeben, wenn Status, Manifest und rootfs vollständig sind.');
my $info_download = info_button('Erstellt bei Bedarf ein Export-Archiv und lädt dieses Backup als tar.gz-Datei auf deinen Rechner herunter. Das kann bei grossen Backups einige Zeit dauern.');
my $info_backup_start = info_button('Startet den Backup-Vorgang. Vor dem eigentlichen Backup prüft das Plugin wichtige Voraussetzungen wie rsync, Schreibzugriff, freien Speicher und Docker-Hinweise.');

sub render_target_notice {
  my ($target_info) = @_;
  return '<section class="inline-notice loading">Dateisystem-Pr&uuml;fung wird geladen...</section>' unless $target_info && %{$target_info};
  my $target_state = ($target_info->{status} || 'ok') eq 'ok' ? 'ok' : 'warning';
  my $target_message = $target_state eq 'ok'
    ? 'Backup-Ziel verwendet das empfohlene Dateisystem ext4.'
    : 'Empfehlung: Backup-Ziel auf ext4 umstellen. ext4 ist deutlich schneller und f&uuml;r inkrementelle Snapshots mit Hardlinks am zuverl&auml;ssigsten.';
  my $target_fs = escapeHTML($target_info->{fs_type} || 'unbekannt');
  my $target_free = escapeHTML($target_info->{available_mb} || 0);
  return qq{<section class="inline-notice $target_state"><strong>Dateisystem-Pr&uuml;fung:</strong> $target_message<br><span>Erkannt: <code>$target_fs</code>, frei ca. $target_free MB.</span></section>};
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
    my $export = $backup->{export_file} ? 'vorhanden' : '-';
    my $is_complete = (($backup->{status} || '') eq 'complete') && (($backup->{files_count} || 0) > 0);
    my $active_task_hidden = hidden_active_task();
    my $backup_actions;

    if ($is_complete) {
      $backup_actions = qq{
<form data-ajax="false" method="get" class="inline-form">
<input data-role="none" type="hidden" name="browse_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Dateien</button>$info_browse
</form>
<form data-ajax="false" method="get" class="inline-form">
<input data-role="none" type="hidden" name="restore_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Restore</button>$info_restore
</form>
<form data-ajax="false" method="get" class="inline-form">
<input data-role="none" type="hidden" name="action" value="download-export">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" type="submit">Export</button>$info_download
</form>
};
    } else {
      $backup_actions = qq{
<span class="pending-action">Noch nicht vollst&auml;ndig</span>$info_browse_pending
};
    }

    $html .= qq{
<tr>
<td><code>$id</code></td>
<td>$status</td>
<td>$host</td>
<td>${size} MB</td>
<td>$files</td>
<td>$finished</td>
<td>$export</td>
<td>
<div class="row-actions">
$backup_actions
<form data-ajax="false" method="post" class="inline-form delete-backup-form">
<input data-role="none" type="hidden" name="action" value="delete-backup">
<input data-role="none" type="hidden" name="backup_id" value="$id">
$active_task_hidden
<button data-role="none" class="danger" type="submit">L&ouml;schen</button>$info_delete
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
    'Docker-Container' => 'Container mit eigenen Datenbanken oder Konfigurationsdateien. Diese Auswahl ist meistens sinnvoll.',
    'LoxBerry-/Plugin-Dienste' => 'Erkannte Dienste mit Bezug zu LoxBerry oder Plugins. Nur ausw&auml;hlen, wenn der Dienst w&auml;hrend des Backups kurz pausieren darf.',
    'Weitere Systemdienste' => 'Expertenbereich. Nur ausw&auml;hlen, wenn du genau weisst, was dieser Dienst macht.',
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
    my $open = $selected_count ? ' open' : '';
    my $safe_hint = $group_hint{$group} || '';
    my $hint_html = length($safe_hint) ? qq{<p class="stop-target-hint">$safe_hint</p>} : '';
    $html .= qq{<details class="stop-target-group"$open><summary><span>$safe_group</span><small>$count_label</small></summary>$hint_html<div class="stop-target-grid">};

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
      my $disabled = $is_stoppable ? '' : ' disabled';
      my $name_attr = $is_stoppable ? ' name="stop_targets"' : '';

      $html .= qq{<label class="stop-target-item}.($is_stoppable ? '' : ' is-disabled').qq{"><input data-role="none" type="checkbox"$name_attr value="$value"$checked$disabled$recommended><span><strong>$label</strong>$meta_html</span></label>};
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
  print $target_status == 0 ? render_target_notice($target_info) : '<section class="inline-notice warning">Dateisystem-Pr&uuml;fung konnte nicht geladen werden.</section>';
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

<main class="page" id="hostbackup-app" data-enhance="false">

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
<input data-role="none" type="hidden" name="action" value="backup">
<button data-role="none" class="primary" type="submit">Backup starten</button>$info_backup_start
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

print <<HTML;

<section class="panel task-monitor" id="task-monitor" data-active-task="$active_task_attr">
<h2>Live-Status</h2>
<div class="task-actions">
<span class="task-state state-running" id="task-state">Kein laufender Task ausgewählt</span>
<span class="task-heartbeat" id="task-heartbeat">Nach einem gestarteten Backup werden hier Status und Log angezeigt.</span>
<form data-ajax="false" method="post" class="stop-task-form" id="stop-task-form">
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

<input data-role="none" type="hidden" name="action" value="save-config">

<fieldset class="schedule-card wide">
<legend>Grundeinstellungen</legend>

<div class="settings-subtitle">Speicherort und Aufbewahrung</div>

<div class="settings-form nested-settings">

<label>
<span>Backup-Verzeichnis $info_backup_root</span>
<input data-role="none" name="backup_root" value="$cfg_backup_root">
</label>

<div id="target-notice">$target_notice</div>

<label>
<span>Anzahl Backups behalten $info_retention</span>
<input data-role="none" name="keep_backups" type="number" min="1" max="10" value="$cfg_keep">
</label>

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
<span>Nach jedem Backup ein Export-Archiv erstellen $info_export</span>
</label>

<label class="checkline root-confirm">
<input data-role="none" type="checkbox" name="root_permission_ack" value="1"$cfg_root_permission_ack required>
<span>Root-Freigabe bestätigen $info_root</span>
</label>

</fieldset>

</form>

<fieldset class="schedule-card wide settings-group config-card">
<legend>Konfiguration verwalten</legend>

<div class="settings-subtitle">Plugin-Konfiguration</div>

<div class="config-actions">
<button data-role="none" type="submit" form="settings-save-form">Plugineinstellungen speichern</button>
</div>

<div class="settings-subtitle config-subtitle">Einstellungsdatei sichern und wiederherstellen</div>

<div class="config-actions">

<form data-ajax="false" method="get" class="inline-form">
<input data-role="none" type="hidden" name="action" value="download-config">
<button data-role="none" type="submit">Einstellungen exportieren</button>
$info_config_export
</form>

<form data-ajax="false" method="post" enctype="multipart/form-data" class="inline-form">
<input data-role="none" type="hidden" name="action" value="import-config">
<input data-role="none" class="config-file" type="file" name="settings_file" accept="application/json,.json">
<button data-role="none" type="submit">Einstellungen importieren</button>
$info_config_import
</form>
</div>
</fieldset>

</section>

<section class="panel backups-panel">

<h2>Backups $info_table</h2>

<fieldset class="backup-content">
<legend>Verwaltung Backups</legend>

<form data-ajax="false" class="import" method="post" enctype="multipart/form-data">

<input data-role="none" type="hidden" name="action" value="import">

<input data-role="none" class="config-file" type="file" name="backup_archive">

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

  print qq{
<div class="subpanel">
<h3>Dateien in Backup <code>$safe_browse_id</code></h3>
<p>Pfad: <code>$safe_browse_path</code></p>
};

  if ($browse_error) {
    print qq{<section class="notice error"><pre>$browse_error</pre></section>};
  } elsif ($browse_data && ref($browse_data->{items}) eq 'ARRAY') {
    if (length $browse_path) {
      my @parts = split m{/+}, $browse_path;
      pop @parts;
      my $parent = join '/', @parts;
      my $parent_url = url_with_active_task(browse_id => $browse_id, path => $parent);
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
        my $url = url_with_active_task(browse_id => $browse_id, path => $path);
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

  print qq{
<section class="panel restore-panel">
<h2>Restore</h2>
<fieldset class="backup-content">
<legend>Wiederherstellung vorbereiten</legend>
<p>Restore nur in Rescue-/Testumgebung verwenden.</p>
<div class="subpanel">
<h3>Ausgewähltes Backup: <code>$safe_restore_id</code></h3>
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
<form data-ajax="false" method="post" class="restore-start-form">
<input data-role="none" type="hidden" name="action" value="restore-backup">
<input data-role="none" type="hidden" name="backup_id" value="$safe_restore_id">
<label class="checkline root-confirm">
<input data-role="none" type="checkbox" name="confirm_restore" value="1" required>
<span>Ich bestätige, dass dieses Backup auf das System zurückgeschrieben werden soll.</span>
</label>
<button data-role="none" class="danger" type="submit">Restore starten</button>
</form>
</div>
</fieldset>
</section>
};
}

print <<HTML;

</main>

<script>
(function () {
  var overlay = document.getElementById('loading-overlay');
  var loadingText = document.getElementById('loading-text');

  function showLoading(text) {
    if (loadingText) loadingText.textContent = text || 'Aktion wird ausgeführt...';
    if (overlay) overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('is-loading');
  }

  window.hostbackupShowLoading = showLoading;

  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (form.hasAttribute('data-skip-loading')) return;
      if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
      var actionInput = form.querySelector('input[name="action"]');
      var action = actionInput ? actionInput.value : '';
      var messages = {
        'save-config': 'Einstellungen werden gespeichert...',
        'import-config': 'Einstellungen werden importiert...',
        'import': 'Backup wird importiert...',
        'delete-backup': 'Backup wird gelöscht...',
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
  var activeParam = activeTask ? '&active_task=' + encodeURIComponent(activeTask) : '';

  function loadFragment(url, target, fallback) {
    if (!target) return;
    fetch(url + '&_=' + Date.now(), { cache: 'no-store' })
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

  loadFragment('?action=target-notice', targetNotice, '<section class="inline-notice warning">Dateisystem-Pr&uuml;fung konnte nicht geladen werden.</section>');
  loadFragment('?action=stop-targets', stopTargetsList, '<p class="empty">Dienste und Container konnten nicht geladen werden.</p>');
  loadFragment('?action=backup-list' + activeParam, backupListBody, '<tr><td colspan="8" class="empty">Backup-Liste konnte nicht geladen werden.</td></tr>');

  if (stopTargetsList) {
    stopTargetsList.addEventListener('click', function (event) {
      var button = event.target.closest ? event.target.closest('[data-stop-target-preset]') : null;
      if (!button) return;
      var mode = button.getAttribute('data-stop-target-preset');
      var boxes = stopTargetsList.querySelectorAll('input[name="stop_targets"]');
      boxes.forEach(function (box) {
        box.checked = mode === 'recommended' ? box.getAttribute('data-recommended') === '1' : false;
      });
      if (mode === 'recommended') {
        stopTargetsList.querySelectorAll('details.stop-target-group').forEach(function (detail) {
          detail.open = !!detail.querySelector('input[name="stop_targets"]:checked');
        });
      }
    });
  }
}());

(function () {
  document.addEventListener('submit', function (event) {
    var deleteForm = event.target.closest ? event.target.closest('.delete-backup-form') : null;
    if (deleteForm) {
      var idInput = deleteForm.querySelector('input[name="backup_id"]');
      var backupId = idInput ? idInput.value : 'dieses Backup';
      if (!window.confirm('Backup ' + backupId + ' wirklich dauerhaft loeschen?')) {
        event.preventDefault();
      } else if (window.hostbackupShowLoading) {
        window.hostbackupShowLoading('Backup wird geloescht...');
      }
      return;
    }

    var restoreForm = event.target.closest ? event.target.closest('.restore-start-form') : null;
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
    panels.forEach(function (panel) {
      panel.classList.toggle('schedule-hidden', panel.getAttribute('data-schedule-panel') !== mode);
    });
  }

  function updateMonthSelection() {
    if (!allMonths) return;
    monthInputs.forEach(function (input) {
      input.disabled = allMonths.checked;
      if (allMonths.checked) input.checked = false;
    });
  }

  modeInputs.forEach(function (input) {
    input.addEventListener('change', updateSchedulePanels);
  });
  if (allMonths) {
    allMonths.addEventListener('change', updateMonthSelection);
  }
  monthInputs.forEach(function (input) {
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
  var monitor = document.getElementById('task-monitor');
  if (!monitor) return;

  var task = monitor.getAttribute('data-active-task');
  var stateEl = document.getElementById('task-state');
  var heartbeatEl = document.getElementById('task-heartbeat');
  var logEl = document.getElementById('task-log');
  var stopForm = document.getElementById('stop-task-form');
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

  function renderStatus(data) {
    pollFailures = 0;
    inFlight = false;
    var state = data.state || 'running';
    var labels = {
      running: task.indexOf('restore-') === 0 ? 'Restore läuft' : 'Backup läuft',
      finished: 'Backup abgeschlossen',
      failed: 'Backup fehlgeschlagen',
      stopped: 'Backup gestoppt',
      stale: 'Keine neue Logausgabe',
      error: 'Status nicht verfügbar'
    };

    if (task.indexOf('restore-') === 0) {
      labels.finished = 'Restore abgeschlossen';
      labels.failed = 'Restore fehlgeschlagen';
    }

    setState(state, labels[state] || state);

    if (state === 'finished') {
      heartbeatEl.textContent = 'Abgeschlossen. Die Backup-Liste wird aktualisiert.';
    } else if (state === 'failed') {
      heartbeatEl.textContent = 'Fehlgeschlagen. Bitte Logausgabe prüfen.';
    } else if (state === 'stopped') {
      heartbeatEl.textContent = 'Gestoppt. Die Backup-Liste wird aktualisiert.';
    } else if (data.now && data.mtime) {
      var age = Math.max(0, Number(data.now) - Number(data.mtime));
      heartbeatEl.textContent = 'Letzte Log-Aktualisierung vor ' + age + ' Sekunden.';
    } else {
      heartbeatEl.textContent = 'Warte auf Logausgabe des Backups.';
    }

    if (data.error) {
      logEl.textContent = data.error;
    } else {
      logEl.textContent = decodeLog(data.content_b64) || 'Backup wurde gestartet. Die Logdatei wird vorbereitet...';
    }

    logEl.scrollTop = logEl.scrollHeight;

    if (state === 'finished' || state === 'failed' || state === 'stopped') {
      if (stopForm) stopForm.classList.add('task-monitor-idle');
      window.clearInterval(timer);
      if (!refreshScheduled) {
        refreshScheduled = true;
        if (state === 'finished' || state === 'stopped') {
          window.setTimeout(function () {
            var msg = state === 'stopped' ? 'backup_stop_requested' : (task.indexOf('restore-') === 0 ? 'restore_finished' : 'backup_finished');
            window.location.href = window.location.pathname + '?msg=' + encodeURIComponent(msg);
          }, 2500);
        }
      }
    }
  }

  if (stopForm) {
    stopForm.addEventListener('submit', function (event) {
      if (!window.confirm('Backup wirklich stoppen? Docker-Container, die dieses Backup gestoppt hat, werden anschliessend wieder gestartet.')) {
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
        heartbeatEl.textContent = 'Der Live-Status konnte gerade nicht gelesen werden. Das Backup kann trotzdem weiterlaufen; es wird automatisch erneut versucht.';
      });
  }

  if (!task) {
    monitor.classList.add('task-monitor-idle');
    if (stopForm) stopForm.classList.add('task-monitor-idle');
    return;
  }

  monitor.classList.remove('task-monitor-idle');
  setState('running', task.indexOf('restore-') === 0 ? 'Restore läuft' : 'Backup läuft');
  heartbeatEl.textContent = 'Live-Status wird geladen...';
  logEl.textContent = 'Backup wurde gestartet. Warte auf erste Logausgabe...';
  poll();
  timer = window.setInterval(poll, 5000);
}());
</script>

HTML

LoxBerry::Web::lbfooter();
