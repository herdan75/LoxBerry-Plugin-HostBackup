#!/usr/bin/perl
use strict;
use warnings;
use CGI qw(:standard escapeHTML);
use File::Temp qw(tempfile);
use File::Copy qw(copy);
use File::Basename qw(basename);
use JSON::PP;

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

sub info_button {
  my ($text) = @_;
  my $safe = escapeHTML($text || '');
  return qq{<span class="info-help"><button type="button" class="info-button">i</button><span class="info-bubble">$safe</span></span>};
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
  my ($status, $out) = run_shell(backend_cmd('task-status', $task, '180'));
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

  if ($action eq 'save-config') {

    my $backup_root = $q->param('backup_root') || '';
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
        $root_permission_ack
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

my ($list_status, $list_json) = run_shell(backend_cmd('list'));

my $backups = [];

if ($list_status == 0) {
  $backups = eval { decode_json($list_json) } || [];
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
my $cfg_keep = escapeHTML($config->{keep_backups} || '10');
my $cfg_pre_hook = escapeHTML($config->{pre_backup_hook} || '');
my $cfg_post_hook = escapeHTML($config->{post_backup_hook} || '');
my $cfg_excludes = escapeHTML(join "\n", @{$config->{rsync_extra_excludes} || []});

my $cfg_stop_docker = checked_attr($config->{stop_docker_before_backup});
my $cfg_create_export = checked_attr($config->{create_export_after_backup});
my $cfg_schedule_enabled = checked_attr($config->{schedule_enabled});
my $cfg_root_permission_ack = checked_attr($config->{root_permission_ack});

my $cfg_schedule_time = escapeHTML($config->{schedule_time} || '02:00');
my $active_task_attr = escapeHTML($active_task);

my $cfg_mode = $config->{schedule_mode} || 'daily';

my $daily_checked = $cfg_mode eq 'daily' ? ' checked' : '';
my $weekly_checked = $cfg_mode eq 'weekly' ? ' checked' : '';
my $monthly_checked = $cfg_mode eq 'monthly' ? ' checked' : '';
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

my $info_backup_root = info_button('Hier legst du fest, wohin die Backups geschrieben werden. Für ein echtes Host-Backup sollte das ein externer Datenträger, ein separates Mount oder ein großer zweiter Datenspeicher sein. Wenn die Systemkarte selbst ausfällt, hilft ein Backup auf derselben Karte nicht.');
my $info_retention = info_button('Legt fest, wie viele fertige Backups behalten werden. Erlaubt sind 1 bis 10. Sobald nach einem erfolgreichen Backup mehr Backups vorhanden sind als erlaubt, entfernt das Plugin automatisch das älteste Backup und das passende Export-Archiv.');
my $info_schedule = info_button('Der Zeitplan erstellt Backups automatisch per Cron. Täglich bedeutet jeden Tag zur Startzeit. Wöchentlich bedeutet an den gewählten Wochentagen zur Startzeit. Monatlich bedeutet an den gewählten Tagen in den gewählten Monaten zur Startzeit.');
my $info_time = info_button('Diese Uhrzeit gilt für alle Zeitplanarten. Bei täglich ist sie die einzige zeitliche Einstellung. Bei wöchentlich und monatlich wird sie mit den gewählten Tagen kombiniert.');
my $info_weekdays = info_button('Nur bei wöchentlichen Backups relevant. Du kannst einen oder mehrere Wochentage auswählen, zum Beispiel Montag und Freitag. An jedem gewählten Tag startet ein Backup zur angegebenen Startzeit.');
my $info_monthdays = info_button('Nur bei monatlichen Backups relevant. Du kannst einen oder mehrere Kalendertage auswählen, zum Beispiel 1 und 15. Gibt es diesen Tag in einem Monat nicht, etwa den 31. im Februar, startet dort kein Backup.');
my $info_months = info_button('Nur bei monatlichen Backups relevant. Mit Alle Monate läuft der Monatsplan jeden Monat. Alternativ kannst du einzelne Monate wählen, zum Beispiel Jan, Apr, Jul und Okt für Quartalsbackups.');
my $info_pre_hook = info_button('Optionales Skript, das direkt vor dem Backup ausgeführt wird. Sinnvoll für Datenbank-Dumps oder das Vorbereiten von Diensten. Das Skript muss absolut angegeben werden und wird aus Sicherheitsgründen nur ausgeführt, wenn es Root gehört und nicht durch andere Benutzer beschreibbar ist.');
my $info_post_hook = info_button('Optionales Skript, das nach dem Backup ausgeführt wird. Sinnvoll zum Aufräumen, Dienste wieder in einen gewünschten Zustand zu bringen oder Benachrichtigungen auszuführen. Es gelten dieselben Sicherheitsregeln wie beim Skript vor dem Backup.');
my $info_excludes = info_button('Hier kannst du Pfade vom rsync-Backup ausschließen, je ein Pfad pro Zeile. Das ist sinnvoll für große Medienarchive, Netzwerkshares oder Daten, die separat gesichert werden. Zu viele Ausschlüsse können aber die Wiederherstellung unvollständig machen.');
my $info_docker = info_button('Wenn aktiv, stoppt das Plugin laufende Docker-Container vor dem Backup und startet sie danach wieder. Das verbessert die Konsistenz von Datenbanken und Volumes, verursacht aber eine Unterbrechung der Container-Dienste während des Backups.');
my $info_export = info_button('Erstellt nach jedem Backup zusätzlich ein komprimiertes tar.gz-Archiv. Das ist praktisch zum Download, Kopieren oder Archivieren, benötigt aber zusätzlichen Speicherplatz und Zeit.');
my $info_root = info_button('Diese Bestätigung ist nötig, weil Vollbackup und Restore Systemdateien, Berechtigungen, Docker-Daten und Cronjobs betreffen. Es werden keine Passwörter gespeichert; erlaubt wird nur der Start des Backend-Skripts dieses Plugins.');
my $info_table = info_button('Diese Liste zeigt vorhandene Backups mit Status, Host, Größe und Fertigstellungszeit. Ein vollständiges Backup sollte den Status complete haben, bevor du es für Restore-Tests verwendest.');
my $info_import = info_button('Importiert ein extern gespeichertes Backup-Archiv im Format tar.gz, zum Beispiel von deinem PC, NAS oder einem anderen Datenträger. Für Restore eines bereits unten gelisteten Backups brauchst du diese Datei-Auswahl nicht.');
my $info_delete = info_button('Löscht den Backup-Ordner und ein eventuell vorhandenes Export-Archiv dieses Backups. Das kann nicht rückgängig gemacht werden.');
my $info_restore = info_button('Wählt dieses Backup für eine Wiederherstellung aus. Danach zeigt der Restore-Bereich die Prüfungen und den Startbutton für genau dieses Backup.');
my $info_browse = info_button('Öffnet den Datei-Explorer für dieses Backup. Damit kannst du prüfen, welche Dateien im Backup enthalten sind.');
my $info_download = info_button('Erstellt bei Bedarf ein Export-Archiv und lädt dieses Backup als tar.gz-Datei auf deinen Rechner herunter. Das kann bei großen Backups einige Zeit dauern.');
my $info_backup_start = info_button('Startet den Backup-Vorgang. Vor dem eigentlichen Backup prüft das Plugin wichtige Voraussetzungen wie rsync, Schreibzugriff, freien Speicher und Docker-Hinweise.');

print header(-type => 'text/html', -charset => 'utf-8');

print <<HTML;
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LoxBerry Host Backup</title>
<link rel="stylesheet" href="assets/style.css">
</head>

<body>

<main class="page">

<header class="topbar">
<div class="brand">
<img class="brand-icon" src="/system/images/icons/loxberryhostbackup/icon_64.png" alt="">
<div>
<h1>LoxBerry Host Backup</h1>
<p>Vollbackup für LoxBerry, Docker, DietPi und native Dienste.</p>
</div>
</div>

<form method="post">
<input type="hidden" name="action" value="backup">
<button class="primary" type="submit">Backup starten</button>$info_backup_start
</form>
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
<form method="post" class="stop-task-form" id="stop-task-form">
<input type="hidden" name="action" value="stop-backup">
<input type="hidden" name="task" value="$active_task_attr">
<button class="danger" type="submit">Backup stoppen</button>
</form>
</div>
<pre class="terminal" id="task-log">Noch keine Live-Ausgabe vorhanden.</pre>
</section>

<section class="panel settings-panel">

<h2>Einstellungen</h2>

<form method="post" class="settings-form">

<input type="hidden" name="action" value="save-config">

<label>
<span>Backup-Verzeichnis $info_backup_root</span>
<input name="backup_root" value="$cfg_backup_root">
</label>

<label>
<span>Backups behalten $info_retention</span>
<input name="keep_backups" type="number" min="1" max="10" value="$cfg_keep">
</label>

<fieldset class="schedule-card wide">

<legend>Automatische Backups $info_schedule</legend>

<label class="checkline schedule-enable">
<input type="checkbox" name="schedule_enabled" value="1"$cfg_schedule_enabled>
<span>Zeitplan aktivieren</span>
</label>

<div class="schedule-modes">
<label><input type="radio" name="schedule_mode" value="daily"$daily_checked> Täglich</label>
<label><input type="radio" name="schedule_mode" value="weekly"$weekly_checked> Wöchentlich</label>
<label><input type="radio" name="schedule_mode" value="monthly"$monthly_checked> Monatlich</label>
</div>

<label>
<span>Startzeit $info_time</span>
<input name="schedule_time" type="time" value="$cfg_schedule_time">
</label>

<details class="schedule-detail" data-schedule-panel="weekly" open>
<summary>Wochentage $info_weekdays</summary>
<div class="choice-grid">
<label><input type="checkbox" name="schedule_weekdays" value="1"$weekday_checked[1]> Montag</label>
<label><input type="checkbox" name="schedule_weekdays" value="2"$weekday_checked[2]> Dienstag</label>
<label><input type="checkbox" name="schedule_weekdays" value="3"$weekday_checked[3]> Mittwoch</label>
<label><input type="checkbox" name="schedule_weekdays" value="4"$weekday_checked[4]> Donnerstag</label>
<label><input type="checkbox" name="schedule_weekdays" value="5"$weekday_checked[5]> Freitag</label>
<label><input type="checkbox" name="schedule_weekdays" value="6"$weekday_checked[6]> Samstag</label>
<label><input type="checkbox" name="schedule_weekdays" value="0"$weekday_checked[0]> Sonntag</label>
</div>
</details>

<details class="schedule-detail" data-schedule-panel="monthly" open>
<summary>Tage im Monat $info_monthdays</summary>
<div class="day-grid">
<label><input type="checkbox" name="schedule_monthdays" value="1"$monthday_checked[1]> 1</label>
<label><input type="checkbox" name="schedule_monthdays" value="2"$monthday_checked[2]> 2</label>
<label><input type="checkbox" name="schedule_monthdays" value="3"$monthday_checked[3]> 3</label>
<label><input type="checkbox" name="schedule_monthdays" value="4"$monthday_checked[4]> 4</label>
<label><input type="checkbox" name="schedule_monthdays" value="5"$monthday_checked[5]> 5</label>
<label><input type="checkbox" name="schedule_monthdays" value="6"$monthday_checked[6]> 6</label>
<label><input type="checkbox" name="schedule_monthdays" value="7"$monthday_checked[7]> 7</label>
<label><input type="checkbox" name="schedule_monthdays" value="8"$monthday_checked[8]> 8</label>
<label><input type="checkbox" name="schedule_monthdays" value="9"$monthday_checked[9]> 9</label>
<label><input type="checkbox" name="schedule_monthdays" value="10"$monthday_checked[10]> 10</label>
<label><input type="checkbox" name="schedule_monthdays" value="11"$monthday_checked[11]> 11</label>
<label><input type="checkbox" name="schedule_monthdays" value="12"$monthday_checked[12]> 12</label>
<label><input type="checkbox" name="schedule_monthdays" value="13"$monthday_checked[13]> 13</label>
<label><input type="checkbox" name="schedule_monthdays" value="14"$monthday_checked[14]> 14</label>
<label><input type="checkbox" name="schedule_monthdays" value="15"$monthday_checked[15]> 15</label>
<label><input type="checkbox" name="schedule_monthdays" value="16"$monthday_checked[16]> 16</label>
<label><input type="checkbox" name="schedule_monthdays" value="17"$monthday_checked[17]> 17</label>
<label><input type="checkbox" name="schedule_monthdays" value="18"$monthday_checked[18]> 18</label>
<label><input type="checkbox" name="schedule_monthdays" value="19"$monthday_checked[19]> 19</label>
<label><input type="checkbox" name="schedule_monthdays" value="20"$monthday_checked[20]> 20</label>
<label><input type="checkbox" name="schedule_monthdays" value="21"$monthday_checked[21]> 21</label>
<label><input type="checkbox" name="schedule_monthdays" value="22"$monthday_checked[22]> 22</label>
<label><input type="checkbox" name="schedule_monthdays" value="23"$monthday_checked[23]> 23</label>
<label><input type="checkbox" name="schedule_monthdays" value="24"$monthday_checked[24]> 24</label>
<label><input type="checkbox" name="schedule_monthdays" value="25"$monthday_checked[25]> 25</label>
<label><input type="checkbox" name="schedule_monthdays" value="26"$monthday_checked[26]> 26</label>
<label><input type="checkbox" name="schedule_monthdays" value="27"$monthday_checked[27]> 27</label>
<label><input type="checkbox" name="schedule_monthdays" value="28"$monthday_checked[28]> 28</label>
<label><input type="checkbox" name="schedule_monthdays" value="29"$monthday_checked[29]> 29</label>
<label><input type="checkbox" name="schedule_monthdays" value="30"$monthday_checked[30]> 30</label>
<label><input type="checkbox" name="schedule_monthdays" value="31"$monthday_checked[31]> 31</label>
</div>
</details>

<details class="schedule-detail" data-schedule-panel="monthly" open>
<summary>Monate $info_months</summary>
<div class="choice-grid month-grid">
<label><input type="checkbox" name="schedule_months" value="*"$all_months_checked> Alle Monate</label>
<label><input type="checkbox" name="schedule_months" value="1"$month_checked[1]> Jan</label>
<label><input type="checkbox" name="schedule_months" value="2"$month_checked[2]> Feb</label>
<label><input type="checkbox" name="schedule_months" value="3"$month_checked[3]> März</label>
<label><input type="checkbox" name="schedule_months" value="4"$month_checked[4]> Apr</label>
<label><input type="checkbox" name="schedule_months" value="5"$month_checked[5]> Mai</label>
<label><input type="checkbox" name="schedule_months" value="6"$month_checked[6]> Jun</label>
<label><input type="checkbox" name="schedule_months" value="7"$month_checked[7]> Jul</label>
<label><input type="checkbox" name="schedule_months" value="8"$month_checked[8]> Aug</label>
<label><input type="checkbox" name="schedule_months" value="9"$month_checked[9]> Sep</label>
<label><input type="checkbox" name="schedule_months" value="10"$month_checked[10]> Okt</label>
<label><input type="checkbox" name="schedule_months" value="11"$month_checked[11]> Nov</label>
<label><input type="checkbox" name="schedule_months" value="12"$month_checked[12]> Dez</label>
</div>
</details>

</fieldset>

<label>
<span>Skript vor dem Backup $info_pre_hook</span>
<input name="pre_backup_hook" value="$cfg_pre_hook">
</label>

<label>
<span>Skript nach dem Backup $info_post_hook</span>
<input name="post_backup_hook" value="$cfg_post_hook">
</label>

<label class="wide">
<span>Vom Backup ausschließen $info_excludes</span>
<textarea name="rsync_extra_excludes" rows="5">$cfg_excludes</textarea>
</label>

<label class="checkline">
<input type="checkbox" name="stop_docker_before_backup" value="1"$cfg_stop_docker>
<span>Docker-Container während des Backups anhalten $info_docker</span>
</label>

<label class="checkline">
<input type="checkbox" name="create_export_after_backup" value="1"$cfg_create_export>
<span>Nach jedem Backup ein Export-Archiv erstellen $info_export</span>
</label>

<label class="checkline root-confirm">
<input type="checkbox" name="root_permission_ack" value="1"$cfg_root_permission_ack required>
<span>Root-Freigabe bestätigen $info_root</span>
</label>

<div class="form-actions">
<button type="submit">Einstellungen speichern</button>
</div>

</form>

</section>

<section class="panel">

<h2>Backups $info_table</h2>

<form class="import" method="post" enctype="multipart/form-data">

<input type="hidden" name="action" value="import">

<input type="file" name="backup_archive">

<button type="submit">Externes Backup importieren</button>$info_import

</form>

<table>

<thead>
<tr>
<th>ID</th>
<th>Status</th>
<th>Host</th>
<th>Größe</th>
<th>Dateien</th>
<th>Fertiggestellt</th>
<th>Export</th>
<th>Aktionen</th>
</tr>
</thead>

<tbody>
HTML

if (!@$backups) {

  print '<tr><td colspan="8" class="empty">Noch keine Backups vorhanden.</td></tr>';

} else {

  for my $backup (@$backups) {

    my $raw_id = $backup->{backup_id} || '';
    my $id = escapeHTML($raw_id);
    my $status = escapeHTML($backup->{status} || 'unbekannt');
    my $host = escapeHTML(($backup->{host} || {})->{hostname} || '');
    my $finished = escapeHTML($backup->{finished_at} || '');

    my $size = int(($backup->{size_bytes} || 0) / 1024 / 1024);
    my $files = escapeHTML($backup->{files_count} || '0');
    my $export = $backup->{export_file} ? 'vorhanden' : '-';

    print qq{
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
<form method="get" class="inline-form">
<input type="hidden" name="browse_id" value="$id">
<button type="submit">Dateien</button>$info_browse
</form>
<form method="get" class="inline-form">
<input type="hidden" name="restore_id" value="$id">
<button type="submit">Restore</button>$info_restore
</form>
<form method="get" class="inline-form">
<input type="hidden" name="action" value="download-export">
<input type="hidden" name="backup_id" value="$id">
<button type="submit">Export</button>$info_download
</form>
<form method="post" class="inline-form delete-backup-form">
<input type="hidden" name="action" value="delete-backup">
<input type="hidden" name="backup_id" value="$id">
<button class="danger" type="submit">Löschen</button>$info_delete
</form>
</div>
</td>
</tr>
};
  }
}

print <<HTML;
</tbody>
</table>
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
      my $parent_url = '?browse_id=' . url_escape($browse_id) . '&path=' . url_escape($parent);
      print qq{<p><a href="$parent_url">Eine Ebene höher</a></p>};
    }

    print qq{
<table>
<thead>
<tr>
<th>Name</th>
<th>Typ</th>
<th>Größe</th>
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
        my $url = '?browse_id=' . url_escape($browse_id) . '&path=' . url_escape($path);
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

print <<HTML;
</section>

<section class="panel">
<h2>Restore</h2>
<p>Restore nur in Rescue-/Testumgebung verwenden. Wähle ein Backup über die Aktion <strong>Restore</strong> in der Backup-Liste aus.</p>
HTML

if ($restore_id) {
  my $safe_restore_id = escapeHTML($restore_id);

  print qq{
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
<form method="post" class="restore-start-form">
<input type="hidden" name="action" value="restore-backup">
<input type="hidden" name="backup_id" value="$safe_restore_id">
<label class="checkline root-confirm">
<input type="checkbox" name="confirm_restore" value="1" required>
<span>Ich bestätige, dass dieses Backup auf das System zurückgeschrieben werden soll.</span>
</label>
<button class="danger" type="submit">Restore starten</button>
</form>
</div>
};
}

print <<HTML;
</section>

</main>

<script>
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
      if (!window.confirm('Backup wirklich stoppen? Docker-Container, die dieses Backup gestoppt hat, werden anschließend wieder gestartet.')) {
        event.preventDefault();
      }
    });
  }

  document.querySelectorAll('.delete-backup-form').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var idInput = form.querySelector('input[name="backup_id"]');
      var backupId = idInput ? idInput.value : 'dieses Backup';
      if (!window.confirm('Backup ' + backupId + ' wirklich dauerhaft löschen?')) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll('.restore-start-form').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var idInput = form.querySelector('input[name="backup_id"]');
      var backupId = idInput ? idInput.value : 'dieses Backup';
      if (!window.confirm('Restore von Backup ' + backupId + ' wirklich starten? Das schreibt Systemdateien zurück.')) {
        event.preventDefault();
      }
    });
  });

  function poll() {
    fetch('?action=task-status&task=' + encodeURIComponent(task), { cache: 'no-store' })
      .then(function (response) { return response.json(); })
      .then(renderStatus)
      .catch(function () {
        setState('error', 'Status nicht verfügbar');
        heartbeatEl.textContent = 'Der Live-Status konnte gerade nicht gelesen werden. Es wird erneut versucht.';
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
  timer = window.setInterval(poll, 3000);
}());
</script>

</body>
</html>
HTML
