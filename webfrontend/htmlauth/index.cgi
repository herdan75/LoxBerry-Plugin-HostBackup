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
  return 'sudo ' . shell_quote($backend) . ' ' . join(' ', map { shell_quote($_) } @_);
}

sub run_shell {
  my ($cmd) = @_;
  my $output = `$cmd 2>&1`;
  my $status = $? >> 8;
  return ($status, $output);
}

sub valid_backup_id {
  my ($value) = @_;
  return defined $value && $value =~ /^[A-Za-z0-9._-]+$/;
}

sub valid_rel_path {
  my ($value) = @_;
  return defined $value && $value !~ m{(^/|(^|/)\.\.(/|$))};
}

sub basename_for_download {
  my ($path) = @_;
  my @parts = grep { length } split m{/+}, $path;
  return $parts[-1] || 'backup-file';
}

sub url_value {
  my ($value) = @_;
  return escape($value || '');
}

sub json_response {
  my ($payload) = @_;
  print header(-type => 'application/json', -charset => 'utf-8');
  print $payload;
  exit;
}

if ($q->request_method eq 'POST') {
  if ($action eq 'backup') {
    my ($status, $out) = run_shell(backend_cmd('start'));
    if ($status == 0) {
      chomp $out;
      my $task_link = escapeHTML("backup-$out.log");
      $message = qq{Backup im Hintergrund gestartet: <a href="?action=task&amp;task=$task_link">$task_link</a>};
    }
    else { $error = escapeHTML($out); }
  } elsif ($action eq 'export' && $backup_id =~ /^[A-Za-z0-9._-]+$/) {
    my ($status, $out) = run_shell(backend_cmd('export', $backup_id));
    if ($status == 0) { $message = "Export erstellt: " . escapeHTML($out); }
    else { $error = escapeHTML($out); }
  } elsif ($action eq 'delete' && $backup_id =~ /^[A-Za-z0-9._-]+$/) {
    my ($status, $out) = run_shell(backend_cmd('delete', $backup_id));
    if ($status == 0) { $message = "Backup geloescht."; }
    else { $error = escapeHTML($out); }
  } elsif ($action eq 'restore-plan' && $backup_id =~ /^[A-Za-z0-9._-]+$/) {
    my ($status, $out) = run_shell(backend_cmd('restore-plan', $backup_id));
    if ($status == 0) { $message = "<pre>" . escapeHTML($out) . "</pre>"; }
    else { $error = escapeHTML($out); }
  } elsif ($action eq 'start-restore' && valid_backup_id($backup_id)) {
    my $confirm = $q->param('confirm_restore') || '';
    if ($confirm eq $backup_id) {
      my ($status, $out) = run_shell(backend_cmd('start-restore', $backup_id));
      if ($status == 0) {
        chomp $out;
        my $task_link = escapeHTML("restore-$out.log");
        $message = qq{Restore im Hintergrund gestartet: <a href="?action=task&amp;task=$task_link">$task_link</a>};
      }
      else { $error = escapeHTML($out); }
    } else {
      $error = "Restore nicht gestartet. Bitte Backup-ID zur Bestaetigung exakt eingeben.";
    }
  } elsif ($action eq 'move' && valid_backup_id($backup_id)) {
    my $destination = $q->param('destination') || '';
    if ($destination =~ m{^/}) {
      my ($status, $out) = run_shell(backend_cmd('move', $backup_id, $destination));
      if ($status == 0) { $message = "Backup verschoben nach: " . escapeHTML($out); }
      else { $error = escapeHTML($out); }
    } else {
      $error = "Zielordner muss ein absoluter Pfad sein.";
    }
  } elsif ($action eq 'save-config') {
    my $backup_root = $q->param('backup_root') || '';
    my $excludes = $q->param('rsync_extra_excludes') || '';
    my $stop_docker = $q->param('stop_docker_before_backup') ? 'true' : 'false';
    my $create_export = $q->param('create_export_after_backup') ? 'true' : 'false';
    my $keep_backups = $q->param('keep_backups') || '0';
    my $schedule_enabled = $q->param('schedule_enabled') ? 'true' : 'false';
    my $schedule_mode = $q->param('schedule_mode') || 'daily';
    my $schedule_time = $q->param('schedule_time') || '02:00';
    my $schedule_weekday = $q->param('schedule_weekday') || '0';
    my $schedule_monthday = $q->param('schedule_monthday') || '1';
    my $pre_hook = $q->param('pre_backup_hook') || '';
    my $post_hook = $q->param('post_backup_hook') || '';
    my ($status, $out) = run_shell(backend_cmd('save-config', $backup_root, $excludes, $stop_docker, $create_export, $keep_backups, $schedule_enabled, $schedule_mode, $schedule_time, $schedule_weekday, $schedule_monthday, $pre_hook, $post_hook));
    if ($status == 0) { $message = "Einstellungen gespeichert."; }
    else { $error = escapeHTML($out); }
  } elsif ($action eq 'import') {
    my $upload = $q->upload('backup_archive');
    if ($upload) {
      my ($tmpfh, $tmpfile) = tempfile('loxberryhostbackup-upload-XXXXXX', SUFFIX => '.tar.gz', DIR => '/tmp', UNLINK => 0);
      binmode $tmpfh;
      while (read($upload, my $buffer, 65536)) {
        print {$tmpfh} $buffer;
      }
      close $tmpfh;
      my ($status, $out) = run_shell(backend_cmd('import', $tmpfile));
      unlink $tmpfile;
      if ($status == 0) { $message = "Backup importiert: " . escapeHTML($out); }
      else { $error = escapeHTML($out); }
    } else {
      $error = "Keine Import-Datei erhalten.";
    }
  }
}

if ($q->request_method eq 'GET' && $action eq 'task-data' && $task =~ /^(backup|restore)-[A-Za-z0-9._-]+(\.launch)?\.log$/) {
  my ($status, $out) = run_shell(backend_cmd('task-status', $task, '500'));
  if ($status == 0) {
    json_response($out);
  }
  json_response(encode_json({ task => $task, state => 'error', error => $out }));
}

my $task_log = '';
if ($q->request_method eq 'GET' && $action eq 'task' && $task =~ /^(backup|restore)-[A-Za-z0-9._-]+(\.launch)?\.log$/) {
  my ($status, $out) = run_shell(backend_cmd('task-log', $task, '400'));
  if ($status == 0) {
    $task_log = $out;
  } else {
    $error ||= escapeHTML($out);
  }
}

if ($q->request_method eq 'GET' && $action eq 'download' && $backup_id =~ /^[A-Za-z0-9._-]+$/) {
  my ($fresh_status, $fresh_json) = run_shell(backend_cmd('list'));
  my $fresh_backups = $fresh_status == 0 ? (eval { decode_json($fresh_json) } || []) : [];
  for my $backup (@$fresh_backups) {
    next unless ($backup->{backup_id} || '') eq $backup_id;
    my $file = $backup->{export_file} || '';
    if ($file && -r $file && $file =~ /\Q$backup_id\E\.tar\.gz$/) {
      print header(
        -type => 'application/gzip',
        -attachment => "$backup_id.tar.gz",
        -Content_length => -s $file,
      );
      open my $fh, '<:raw', $file or last;
      my $buffer;
      while (read($fh, $buffer, 65536)) {
        print $buffer;
      }
      close $fh;
      exit;
    }
  }
  $error = "Export-Datei nicht gefunden. Bitte zuerst Export erstellen.";
}

if ($q->request_method eq 'GET' && $action eq 'download-file' && valid_backup_id($backup_id) && valid_rel_path($browse_path)) {
  my $cmd = backend_cmd('cat-file', $backup_id, $browse_path);
  my $filename = basename_for_download($browse_path);
  print header(
    -type => 'application/octet-stream',
    -attachment => $filename,
  );
  open my $fh, "$cmd 2>/dev/null |";
  binmode $fh;
  binmode STDOUT;
  my $buffer;
  while (read($fh, $buffer, 65536)) {
    print $buffer;
  }
  close $fh;
  exit;
}

my ($list_status, $list_json) = run_shell(backend_cmd('list'));
my $backups = [];
if ($list_status == 0) {
  $backups = eval { decode_json($list_json) } || [];
} else {
  $error ||= escapeHTML($list_json);
}

my ($config_status, $config_json) = run_shell(backend_cmd('config'));
my $config = {};
if ($config_status == 0) {
  $config = eval { decode_json($config_json) } || {};
} else {
  $error ||= escapeHTML($config_json);
}

my $browser = undef;
if ($action eq 'browse' && valid_backup_id($backup_id) && valid_rel_path($browse_path)) {
  my ($status, $out) = run_shell(backend_cmd('browse', $backup_id, $browse_path));
  if ($status == 0) {
    $browser = eval { decode_json($out) };
    $error ||= escapeHTML($@) if $@;
  } else {
    $error ||= escapeHTML($out);
  }
}

my $restore_plan = '';
my $restore_check = undef;
if ($action eq 'prepare-restore' && valid_backup_id($backup_id)) {
  my ($check_status, $check_out) = run_shell(backend_cmd('preflight-restore', $backup_id));
  if ($check_status == 0) {
    $restore_check = eval { decode_json($check_out) };
    $error ||= escapeHTML($@) if $@;
  } else {
    $error ||= escapeHTML($check_out);
  }
  my ($status, $out) = run_shell(backend_cmd('restore-plan', $backup_id));
  if ($status == 0) {
    $restore_plan = $out;
  } else {
    $error ||= escapeHTML($out);
  }
}

my $backup_check = undef;
if ($action eq 'prepare-backup') {
  my ($status, $out) = run_shell(backend_cmd('preflight-backup'));
  if ($status == 0) {
    $backup_check = eval { decode_json($out) };
    $error ||= escapeHTML($@) if $@;
  } else {
    $error ||= escapeHTML($out);
  }
}

sub render_check {
  my ($check) = @_;
  return unless $check;
  my $status = escapeHTML($check->{status} || 'unknown');
  print qq{<div class="check-summary status-$status">Check: $status</div>};
  if ($check->{warnings} && @{$check->{warnings}}) {
    print '<ul class="warnings">';
    for my $warning (@{$check->{warnings}}) {
      print '<li>' . escapeHTML($warning) . '</li>';
    }
    print '</ul>';
  }
  print '<table class="check-table"><thead><tr><th>Check</th><th>Status</th><th>Wert</th></tr></thead><tbody>';
  for my $item (@{$check->{checks} || []}) {
    my $name = escapeHTML($item->{name} || '');
    my $ok = $item->{ok} ? 'OK' : 'Pruefen';
    my $value = escapeHTML($item->{value} || '');
    print qq{<tr><td>$name</td><td>$ok</td><td><code>$value</code></td></tr>};
  }
  print '</tbody></table>';
}

sub checked_attr {
  my ($value) = @_;
  return $value ? ' checked' : '';
}

print header(-type => 'text/html', -charset => 'utf-8');
print <<'HTML';
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
        <button class="primary" type="submit">Backup starten</button>
      </form>
      <form method="get">
        <input type="hidden" name="action" value="prepare-backup">
        <button type="submit">Backup-Check</button>
      </form>
    </header>
HTML

if ($message) {
  print qq{<section class="notice ok">$message</section>};
}
if ($error) {
  print qq{<section class="notice error"><pre>$error</pre></section>};
}

my $cfg_backup_root = escapeHTML($config->{backup_root} || '');
my $cfg_keep = escapeHTML(defined $config->{keep_backups} ? $config->{keep_backups} : 0);
my $cfg_pre_hook = escapeHTML($config->{pre_backup_hook} || '');
my $cfg_post_hook = escapeHTML($config->{post_backup_hook} || '');
my $cfg_excludes = escapeHTML(join "\n", @{$config->{rsync_extra_excludes} || []});
my $cfg_stop_docker = checked_attr($config->{stop_docker_before_backup});
my $cfg_create_export = checked_attr($config->{create_export_after_backup});
my $cfg_schedule_enabled = checked_attr($config->{schedule_enabled});
my $cfg_schedule_time = escapeHTML($config->{schedule_time} || '02:00');
my $cfg_schedule_weekday = escapeHTML(defined $config->{schedule_weekday} ? $config->{schedule_weekday} : '0');
my $cfg_schedule_monthday = escapeHTML(defined $config->{schedule_monthday} ? $config->{schedule_monthday} : '1');
my $cfg_mode = $config->{schedule_mode} || 'daily';
my $daily_selected = $cfg_mode eq 'daily' ? ' selected' : '';
my $weekly_selected = $cfg_mode eq 'weekly' ? ' selected' : '';
my $monthly_selected = $cfg_mode eq 'monthly' ? ' selected' : '';
my @weekday_selected = map { $cfg_schedule_weekday eq "$_" ? ' selected' : '' } 0..6;

print <<HTML;
    <section class="panel settings-panel">
      <h2>Einstellungen</h2>
      <form method="post" class="settings-form">
        <input type="hidden" name="action" value="save-config">
        <label>
          <span>Backup-Ziel</span>
          <input name="backup_root" value="$cfg_backup_root" placeholder="/mnt/backupdisk/loxberry-hostbackup">
        </label>
        <label>
          <span>Aufbewahrung</span>
          <input name="keep_backups" type="number" min="0" step="1" value="$cfg_keep">
        </label>
        <label>
          <span>Zeitplan</span>
          <select name="schedule_mode">
            <option value="daily"$daily_selected>Taeglich</option>
            <option value="weekly"$weekly_selected>Woechentlich</option>
            <option value="monthly"$monthly_selected>Monatlich</option>
          </select>
        </label>
        <label>
          <span>Uhrzeit</span>
          <input name="schedule_time" type="time" value="$cfg_schedule_time">
        </label>
        <label>
          <span>Wochentag</span>
          <select name="schedule_weekday">
            <option value="1"$weekday_selected[1]>Montag</option>
            <option value="2"$weekday_selected[2]>Dienstag</option>
            <option value="3"$weekday_selected[3]>Mittwoch</option>
            <option value="4"$weekday_selected[4]>Donnerstag</option>
            <option value="5"$weekday_selected[5]>Freitag</option>
            <option value="6"$weekday_selected[6]>Samstag</option>
            <option value="0"$weekday_selected[0]>Sonntag</option>
          </select>
        </label>
        <label>
          <span>Monatstag</span>
          <input name="schedule_monthday" type="number" min="1" max="31" step="1" value="$cfg_schedule_monthday">
        </label>
        <label>
          <span>Pre-Backup-Hook</span>
          <input name="pre_backup_hook" value="$cfg_pre_hook" placeholder="/opt/scripts/before-backup.sh">
        </label>
        <label>
          <span>Post-Backup-Hook</span>
          <input name="post_backup_hook" value="$cfg_post_hook" placeholder="/opt/scripts/after-backup.sh">
        </label>
        <label class="wide">
          <span>Zusaetzliche rsync-Excludes</span>
          <textarea name="rsync_extra_excludes" rows="5" placeholder="/mnt/nas&#10;/media/bigdata">$cfg_excludes</textarea>
        </label>
        <label class="checkline">
          <input type="checkbox" name="stop_docker_before_backup" value="1"$cfg_stop_docker>
          <span>Docker-Container vor dem Backup stoppen und danach wieder starten</span>
        </label>
        <label class="checkline">
          <input type="checkbox" name="create_export_after_backup" value="1"$cfg_create_export>
          <span>Nach jedem Backup automatisch ein Export-Archiv erstellen</span>
        </label>
        <label class="checkline">
          <input type="checkbox" name="schedule_enabled" value="1"$cfg_schedule_enabled>
          <span>Automatische Backups per Cron aktivieren</span>
        </label>
        <div class="form-actions">
          <button type="submit">Einstellungen speichern</button>
        </div>
      </form>
    </section>
HTML

print <<'HTML';
    <section class="panel">
      <h2>Backup-Dateien</h2>
      <form class="import" method="post" enctype="multipart/form-data">
        <input type="hidden" name="action" value="import">
        <input type="file" name="backup_archive" accept=".gz,.tgz,application/gzip">
        <button type="submit">Backup laden</button>
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
            <th>Aktionen</th>
          </tr>
        </thead>
        <tbody>
HTML

if (!@$backups) {
  print '<tr><td colspan="7" class="empty">Noch keine Backups vorhanden.</td></tr>';
}

for my $backup (@$backups) {
  my $id = escapeHTML($backup->{backup_id} || '');
  my $status = escapeHTML($backup->{status} || 'unknown');
  my $host = escapeHTML(($backup->{host} || {})->{hostname} || '');
  my $finished = escapeHTML($backup->{finished_at} || '');
  my $size = int(($backup->{size_bytes} || 0) / 1024 / 1024);
  my $export_file = $backup->{export_file} ? escapeHTML($backup->{export_file}) : '';
  my $export = $export_file ? "<code>$export_file</code><br><a href=\"?action=download&amp;backup_id=$id\">Download</a>" : '-';
  print "<tr>";
  print "<td><code>$id</code></td>";
  print "<td>$status</td>";
  print "<td>$host</td>";
  print "<td>${size} MB</td>";
  print "<td>$finished</td>";
  print "<td>$export</td>";
  print '<td class="actions">';
  print qq{<form method="post"><input type="hidden" name="backup_id" value="$id"><input type="hidden" name="action" value="export"><button type="submit">Export</button></form>};
  print qq{<form method="get"><input type="hidden" name="backup_id" value="$id"><input type="hidden" name="action" value="browse"><button type="submit">Explorer</button></form>};
  print qq{<form method="get"><input type="hidden" name="backup_id" value="$id"><input type="hidden" name="action" value="prepare-restore"><button type="submit">Restore</button></form>};
  print qq{<form class="move-form" method="post"><input type="hidden" name="backup_id" value="$id"><input type="hidden" name="action" value="move"><input name="destination" placeholder="/mnt/backupziel"><button type="submit">Verschieben</button></form>};
  print qq{<form method="post" onsubmit="return confirm('Backup wirklich loeschen?');"><input type="hidden" name="backup_id" value="$id"><input type="hidden" name="action" value="delete"><button class="danger" type="submit">Loeschen</button></form>};
  print '</td>';
  print "</tr>";
}

if ($backup_check) {
  print <<'HTML';
        </tbody>
      </table>
    </section>

    <section class="panel restore-panel">
      <h2>Backup-Check</h2>
HTML
  render_check($backup_check);
  print <<'HTML';
      <form method="post">
        <input type="hidden" name="action" value="backup">
        <button class="primary" type="submit">Backup jetzt starten</button>
      </form>
    </section>
HTML
} elsif ($task_log) {
  my $task_html = escapeHTML($task);
  my $task_url = url_value($task);
  my $log_html = escapeHTML($task_log);
  print <<HTML;
        </tbody>
      </table>
    </section>

    <section class="panel task-panel" data-task="$task_url">
      <h2>Task: <code>$task_html</code></h2>
      <div class="task-actions">
        <span id="task-state" class="task-state">verbinde...</span>
        <span id="task-heartbeat" class="task-heartbeat">warte auf Logdaten</span>
        <a href="?action=task&amp;task=$task_url">Neu laden</a>
      </div>
      <pre id="task-terminal" class="terminal">$log_html</pre>
    </section>
    <script>
      (function () {
        var panel = document.querySelector('.task-panel');
        var terminal = document.getElementById('task-terminal');
        var state = document.getElementById('task-state');
        var heartbeat = document.getElementById('task-heartbeat');
        if (!panel || !terminal || !state || !heartbeat) return;
        var task = panel.getAttribute('data-task');
        var lastSize = null;
        function decodeBase64(value) {
          try {
            return decodeURIComponent(Array.prototype.map.call(atob(value || ''), function (char) {
              return '%' + ('00' + char.charCodeAt(0).toString(16)).slice(-2);
            }).join(''));
          } catch (error) {
            return atob(value || '');
          }
        }
        function tick() {
          fetch('?action=task-data&task=' + task, { cache: 'no-store' })
            .then(function (response) { return response.json(); })
            .then(function (data) {
              var text = decodeBase64(data.content_b64 || '');
              terminal.textContent = text || 'Noch keine Logausgabe vorhanden...';
              terminal.scrollTop = terminal.scrollHeight;
              state.textContent = data.state || 'unknown';
              state.className = 'task-state state-' + (data.state || 'unknown');
              var changed = lastSize === null || lastSize !== data.size;
              lastSize = data.size;
              var age = Math.max(0, (data.now || 0) - (data.mtime || 0));
              heartbeat.textContent = changed ? 'Log aktualisiert, letzte Aenderung vor ' + age + 's' : 'warte weiter, letzte Aenderung vor ' + age + 's';
              if (data.state === 'finished' || data.state === 'failed') {
                return;
              }
              window.setTimeout(tick, 2000);
            })
            .catch(function () {
              heartbeat.textContent = 'Live-Verbindung unterbrochen, neuer Versuch laeuft...';
              window.setTimeout(tick, 4000);
            });
        }
        terminal.scrollTop = terminal.scrollHeight;
        tick();
      }());
    </script>
HTML
} elsif ($restore_plan) {
  my $restore_id = escapeHTML($backup_id);
  my $plan_html = escapeHTML($restore_plan);
  print <<HTML;
        </tbody>
      </table>
    </section>

    <section class="panel restore-panel">
      <h2>Restore vorbereiten: <code>$restore_id</code></h2>
HTML
  render_check($restore_check);
  print <<HTML;
      <pre>$plan_html</pre>
      <form method="post" onsubmit="return confirm('Restore jetzt starten? Das Zielsystem wird ueberschrieben.');">
        <input type="hidden" name="backup_id" value="$restore_id">
        <input type="hidden" name="action" value="start-restore">
        <label>Backup-ID zur Bestaetigung eingeben</label>
        <input name="confirm_restore" autocomplete="off" placeholder="$restore_id">
        <button class="danger" type="submit">Restore starten</button>
      </form>
    </section>
HTML
} elsif ($browser) {
  my $current = escapeHTML($browser->{path} || '');
  my $browser_id = escapeHTML($backup_id);
  my $browser_id_url = url_value($backup_id);
  print <<HTML;
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Explorer: <code>$browser_id</code></h2>
      <p><code>/$current</code></p>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Typ</th>
            <th>Groesse</th>
            <th>Geaendert</th>
            <th>Aktion</th>
          </tr>
        </thead>
        <tbody>
HTML
  if ($browse_path) {
    my @parts = grep { length } split m{/+}, $browse_path;
    pop @parts;
    my $parent = escapeHTML(join '/', @parts);
    my $parent_url = url_value(join '/', @parts);
    print qq{<tr><td><a href="?action=browse&amp;backup_id=$browser_id_url&amp;path=$parent_url">..</a></td><td>directory</td><td></td><td></td><td></td></tr>};
  }
  for my $item (@{$browser->{items} || []}) {
    my $name = escapeHTML($item->{name} || '');
    my $path = escapeHTML($item->{path} || '');
    my $path_url = url_value($item->{path} || '');
    my $type = escapeHTML($item->{type} || '');
    my $size = int(($item->{size} || 0) / 1024);
    my $mtime = $item->{mtime} ? scalar localtime($item->{mtime}) : '';
    my $action_html = '';
    if (($item->{type} || '') eq 'directory') {
      $action_html = qq{<a href="?action=browse&amp;backup_id=$browser_id_url&amp;path=$path_url">Oeffnen</a>};
      print "<tr><td><a href=\"?action=browse&amp;backup_id=$browser_id_url&amp;path=$path_url\">$name</a></td>";
    } elsif (($item->{type} || '') eq 'file') {
      $action_html = qq{<a href="?action=download-file&amp;backup_id=$browser_id_url&amp;path=$path_url">Download</a>};
      print "<tr><td>$name</td>";
    } else {
      print "<tr><td>$name</td>";
    }
    print "<td>$type</td><td>${size} KB</td><td>" . escapeHTML($mtime) . "</td><td>$action_html</td></tr>";
  }
  print <<'HTML';
        </tbody>
      </table>
    </section>
HTML
} else {
print <<'HTML';
        </tbody>
      </table>
    </section>
HTML
}

print <<'HTML';
    <section class="panel">
      <h2>Restore</h2>
      <p>Ein Restore sollte bevorzugt auf einem frisch installierten Zielsystem oder aus einer Rescue-Umgebung erfolgen. Der Restore-Befehl ist absichtlich gesperrt und benoetigt <code>ALLOW_RESTORE=1</code>.</p>
    </section>
  </main>
</body>
</html>
HTML
