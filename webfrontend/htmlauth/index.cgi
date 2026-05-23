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
my $active_task = '';

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

if ($action eq 'task-status') {
  my ($status, $out) = run_shell(backend_cmd('task-status', $task, '180'));
  if ($status != 0 && $task =~ /^backup-([A-Za-z0-9._-]+)\.log$/) {
    ($status, $out) = run_shell(backend_cmd('task-status', "backup-$1.launch.log", '80'));
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
      $message = 'Einstellungen gespeichert.';
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
      }
      $message = 'Backup gestartet. Der Live-Status wird unten automatisch aktualisiert.';
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

my $info_backup_root = info_button('Hier legst du fest, wohin die Backups geschrieben werden. Fuer ein echtes Host-Backup sollte das ein externer Datentraeger, ein separates Mount oder ein grosser zweiter Datenspeicher sein. Wenn die Systemkarte selbst ausfaellt, hilft ein Backup auf derselben Karte nicht.');
my $info_retention = info_button('Legt fest, wie viele fertige Backups behalten werden. Erlaubt sind 1 bis 10. Sobald nach einem erfolgreichen Backup mehr Backups vorhanden sind als erlaubt, entfernt das Plugin automatisch das aelteste Backup und das passende Export-Archiv.');
my $info_schedule = info_button('Der Zeitplan erstellt Backups automatisch per Cron. Taeglich bedeutet jeden Tag zur Startzeit. Woechentlich bedeutet an den gewaehlen Wochentagen zur Startzeit. Monatlich bedeutet an den gewaehlen Tagen in den gewaehlen Monaten zur Startzeit.');
my $info_time = info_button('Diese Uhrzeit gilt fuer alle Zeitplanarten. Bei taeglich ist sie die einzige zeitliche Einstellung. Bei woechentlich und monatlich wird sie mit den gewaehlen Tagen kombiniert.');
my $info_weekdays = info_button('Nur bei woechentlichen Backups relevant. Du kannst einen oder mehrere Wochentage auswaehlen, zum Beispiel Montag und Freitag. An jedem gewaehlten Tag startet ein Backup zur angegebenen Startzeit.');
my $info_monthdays = info_button('Nur bei monatlichen Backups relevant. Du kannst einen oder mehrere Kalendertage auswaehlen, zum Beispiel 1 und 15. Gibt es diesen Tag in einem Monat nicht, etwa den 31. im Februar, startet dort kein Backup.');
my $info_months = info_button('Nur bei monatlichen Backups relevant. Mit Alle Monate laeuft der Monatsplan jeden Monat. Alternativ kannst du einzelne Monate waehlen, zum Beispiel Jan, Apr, Jul und Okt fuer Quartalsbackups.');
my $info_pre_hook = info_button('Optionales Skript, das direkt vor dem Backup ausgefuehrt wird. Sinnvoll fuer Datenbank-Dumps oder das Vorbereiten von Diensten. Das Skript muss absolut angegeben werden und wird aus Sicherheitsgruenden nur ausgefuehrt, wenn es Root gehoert und nicht durch andere Benutzer beschreibbar ist.');
my $info_post_hook = info_button('Optionales Skript, das nach dem Backup ausgefuehrt wird. Sinnvoll zum Aufraeumen, Dienste wieder in einen gewuenschten Zustand zu bringen oder Benachrichtigungen auszufuehren. Es gelten dieselben Sicherheitsregeln wie beim Skript vor dem Backup.');
my $info_excludes = info_button('Hier kannst du Pfade vom rsync-Backup ausschliessen, je ein Pfad pro Zeile. Das ist sinnvoll fuer grosse Medienarchive, Netzwerkshares oder Daten, die separat gesichert werden. Zu viele Ausschluesse koennen aber die Wiederherstellung unvollstaendig machen.');
my $info_docker = info_button('Wenn aktiv, stoppt das Plugin laufende Docker-Container vor dem Backup und startet sie danach wieder. Das verbessert die Konsistenz von Datenbanken und Volumes, verursacht aber eine Unterbrechung der Container-Dienste waehrend des Backups.');
my $info_export = info_button('Erstellt nach jedem Backup zusaetzlich ein komprimiertes tar.gz-Archiv. Das ist praktisch zum Download, Kopieren oder Archivieren, benoetigt aber zusaetzlichen Speicherplatz und Zeit.');
my $info_root = info_button('Diese Bestaetigung ist noetig, weil Vollbackup und Restore Systemdateien, Berechtigungen, Docker-Daten und Cronjobs betreffen. Es werden keine Passwoerter gespeichert; erlaubt wird nur der Start des Backend-Skripts dieses Plugins.');
my $info_table = info_button('Diese Liste zeigt vorhandene Backups mit Status, Host, Groesse und Fertigstellungszeit. Ein vollstaendiges Backup sollte den Status complete haben, bevor du es fuer Restore-Tests verwendest.');
my $info_import = info_button('Importiert ein zuvor exportiertes Backup-Archiv zurueck in die lokale Backup-Liste. Das Archiv wird vor dem Entpacken auf sichere Pfade und die erwartete Backup-Struktur geprueft.');
my $info_backup_start = info_button('Startet den Backup-Vorgang. Vor dem eigentlichen Backup prueft das Plugin wichtige Voraussetzungen wie rsync, Schreibzugriff, freien Speicher und Docker-Hinweise.');

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

<section class="panel task-monitor" id="task-monitor" data-active-task="$active_task_attr">
<h2>Live-Status</h2>
<div class="task-actions">
<span class="task-state state-running" id="task-state">Kein laufender Task ausgewaehlt</span>
<span class="task-heartbeat" id="task-heartbeat">Nach einem gestarteten Backup werden hier Status und Log angezeigt.</span>
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
<label><input type="radio" name="schedule_mode" value="daily"$daily_checked> Taeglich</label>
<label><input type="radio" name="schedule_mode" value="weekly"$weekly_checked> Woechentlich</label>
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
<label><input type="checkbox" name="schedule_months" value="3"$month_checked[3]> Maerz</label>
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
  var timer = null;

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
      running: 'Backup laeuft',
      finished: 'Backup abgeschlossen',
      failed: 'Backup fehlgeschlagen',
      stale: 'Keine neue Logausgabe',
      error: 'Status nicht verfuegbar'
    };

    setState(state, labels[state] || state);

    if (data.now && data.mtime) {
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

    if (state === 'finished' || state === 'failed') {
      window.clearInterval(timer);
    }
  }

  function poll() {
    fetch('?action=task-status&task=' + encodeURIComponent(task), { cache: 'no-store' })
      .then(function (response) { return response.json(); })
      .then(renderStatus)
      .catch(function () {
        setState('error', 'Status nicht verfuegbar');
        heartbeatEl.textContent = 'Der Live-Status konnte gerade nicht gelesen werden. Es wird erneut versucht.';
      });
  }

  if (!task) {
    monitor.classList.add('task-monitor-idle');
    return;
  }

  monitor.classList.remove('task-monitor-idle');
  setState('running', 'Backup laeuft');
  heartbeatEl.textContent = 'Live-Status wird geladen...';
  logEl.textContent = 'Backup wurde gestartet. Warte auf erste Logausgabe...';
  poll();
  timer = window.setInterval(poll, 3000);
}());
</script>

</body>
</html>
HTML
