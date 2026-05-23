#!/usr/bin/perl
use strict;
use warnings;
use CGI qw(:standard escapeHTML);
use File::Temp qw(tempfile);
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

my $message = '';
my $error = '';

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

if ($q->request_method eq 'POST') {

  if ($action eq 'save-config') {

    my $backup_root = $q->param('backup_root') || '';
    my $keep_backups = $q->param('keep_backups') || '10';

    my $schedule_enabled = $q->param('schedule_enabled') ? 'true' : 'false';
    my $schedule_mode = $q->param('schedule_mode') || 'daily';
    my $schedule_time = $q->param('schedule_time') || '02:00';

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
        '0',
        '1',
        '*',
        $pre_hook,
        $post_hook,
        $root_permission_ack
      )
    );

    if ($status == 0) {
      $message = 'Einstellungen gespeichert.';
    } else {
      $error = escapeHTML($out);
    }
  }

  elsif ($action eq 'backup') {

    my ($status, $out) = run_shell(backend_cmd('start'));

    if ($status == 0) {
      $message = 'Backup gestartet.';
    } else {
      $error = escapeHTML($out);
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

my $cfg_mode = $config->{schedule_mode} || 'daily';

my $daily_checked = $cfg_mode eq 'daily' ? ' checked' : '';
my $weekly_checked = $cfg_mode eq 'weekly' ? ' checked' : '';
my $monthly_checked = $cfg_mode eq 'monthly' ? ' checked' : '';

my $info_backup_root = info_button('Ablageort fuer die Backups.');
my $info_retention = info_button('1 bis 10 Backups.');
my $info_schedule = info_button('Automatische Backups.');
my $info_time = info_button('Startzeit.');
my $info_pre_hook = info_button('Skript vor dem Backup.');
my $info_post_hook = info_button('Skript nach dem Backup.');
my $info_excludes = info_button('Pfade ausschliessen.');
my $info_docker = info_button('Docker stoppen.');
my $info_export = info_button('Export erstellen.');
my $info_root = info_button('Root-Freigabe.');
my $info_table = info_button('Backupliste.');
my $info_import = info_button('Backup importieren.');
my $info_backup_start = info_button('Backup vorbereiten.');

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
<div>
<h1>LoxBerry Host Backup</h1>
<p>Vollbackup fuer LoxBerry, Docker, DietPi und native Dienste.</p>
</div>

<form method="post">
<input type="hidden" name="action" value="backup">
<button class="primary" type="submit">Backup vorbereiten</button>$info_backup_start
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
<label><input type="radio" name="schedule_mode" value="daily"$daily_checked> Taeglich</label>
<label><input type="radio" name="schedule_mode" value="weekly"$weekly_checked> Woechentlich</label>
<label><input type="radio" name="schedule_mode" value="monthly"$monthly_checked> Monatlich</label>
</div>

<label>
<span>Startzeit $info_time</span>
<input name="schedule_time" type="time" value="$cfg_schedule_time">
</label>

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
<span>Vom Backup ausschliessen $info_excludes</span>
<textarea name="rsync_extra_excludes" rows="5">$cfg_excludes</textarea>
</label>

<label class="checkline">
<input type="checkbox" name="stop_docker_before_backup" value="1"$cfg_stop_docker>
<span>Docker-Container waehrend des Backups anhalten $info_docker</span>
</label>

<label class="checkline">
<input type="checkbox" name="create_export_after_backup" value="1"$cfg_create_export>
<span>Nach jedem Backup ein Export-Archiv erstellen $info_export</span>
</label>

<label class="checkline root-confirm">
<input type="checkbox" name="root_permission_ack" value="1"$cfg_root_permission_ack required>
<span>Root-Freigabe bestaetigen $info_root</span>
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

<button type="submit">Backup importieren</button>$info_import

</form>

<table>

<thead>
<tr>
<th>ID</th>
<th>Status</th>
<th>Host</th>
<th>Groesse</th>
<th>Fertiggestellt</th>
<th>Export</th>
</tr>
</thead>

<tbody>
HTML

if (!@$backups) {

  print '<tr><td colspan="6" class="empty">Noch keine Backups vorhanden.</td></tr>';

} else {

  for my $backup (@$backups) {

    my $id = escapeHTML($backup->{backup_id} || '');
    my $status = escapeHTML($backup->{status} || '');
    my $host = escapeHTML(($backup->{host} || {})->{hostname} || '');
    my $finished = escapeHTML($backup->{finished_at} || '');

    my $size = int(($backup->{size_bytes} || 0) / 1024 / 1024);

    print qq{
<tr>
<td><code>$id</code></td>
<td>$status</td>
<td>$host</td>
<td>${size} MB</td>
<td>$finished</td>
<td>-</td>
</tr>
};
  }
}

print <<HTML;
</tbody>
</table>
</section>

<section class="panel">
<h2>Restore</h2>
<p>Restore nur in Rescue-/Testumgebung verwenden.</p>
</section>

</main>

</body>
</html>
HTML
