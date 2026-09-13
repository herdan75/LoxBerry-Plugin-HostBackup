/* Kept outside Perl heredocs: browser syntax and escaping are tested directly. */
(function (root) {
  'use strict';
  function normalizeLogForDisplay(value) {
    return String(value || '').replace(/\r\n?/g, '\n').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');
  }
  function controlState(controls) {
    var items = Array.from(controls || []);
    if (!items.length) return '';
    if (items[0].type === 'radio') return (items.find(function (item) { return item.checked; }) || {}).value || '';
    if (items[0].type === 'checkbox') {
      if (items.length === 1 && !/^(stop_targets|schedule_weekdays|schedule_monthdays|schedule_months)$/.test(items[0].name)) return items[0].checked ? '1' : '0';
      return items.filter(function (item) { return item.checked; }).map(function (item) { return item.value; }).sort().join('\u001f');
    }
    return items[0].value || '';
  }
  function validateSettings(values) {
    if (values.metadata_mode === 'portable-archive' && values.backup_mode === 'snapshot') return 'Portable Archive unterstützt keine inkrementellen Snapshots. Bitte ausdrücklich „Volles Backup“ wählen.';
    if (values.schedule_enabled === '1') {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(values.schedule_time || '')) return 'Bitte eine gültige Startzeit wählen.';
      if (values.schedule_mode === 'weekly' && !values.schedule_weekdays) return 'Für den wöchentlichen Zeitplan mindestens einen Wochentag wählen.';
      if (values.schedule_mode === 'monthly' && (!values.schedule_monthdays || !values.schedule_months)) return 'Für den monatlichen Zeitplan mindestens einen Tag und einen Monat wählen.';
    }
    return '';
  }
  function updateDirty(initial, changed, name, value, now) {
    if (!Object.prototype.hasOwnProperty.call(initial, name)) initial[name] = value;
    if (initial[name] === value) delete changed[name];
    else if (!changed[name] || changed[name].value !== value) changed[name] = { value: value, at: now };
    return changed;
  }
  function logViewport(scrollTop, clientHeight, scrollHeight) { return scrollHeight - scrollTop - clientHeight < 40; }
  var core = { normalizeLogForDisplay: normalizeLogForDisplay, controlState: controlState, validateSettings: validateSettings, updateDirty: updateDirty, logViewport: logViewport };
  if (typeof module !== 'undefined' && module.exports) module.exports = core;
  if (!root.document) return;
  var document = root.document;
  var app = document.getElementById('hostbackup-app');
  if (!app || !root.fetch || !root.FormData) return; // Native forms remain usable.
  var initial = {}, changed = {}, pendingDraft = app.dataset.pendingSettings === '1';
  var currentTask = (document.getElementById('task-monitor') || {}).dataset.activeTask || '';
  var userSelectedTask = false, taskInFlight = false, overviewInFlight = false, followLog = true, finalTask = '';
  var csrfRefresh = null, busyForms = new WeakSet(), busyCount = 0, pendingImport = false, intentionalNavigation = false;
  var reportDownloadUrl = null;
  var labels = {
    backup_root: 'Backup-Verzeichnis', keep_backups: 'Anzahl Backups behalten', metadata_mode: 'Metadaten-Profil', backup_mode: 'Backup-Modus',
    schedule_enabled: 'Automatische Backups', schedule_mode: 'Zeitplan', schedule_time: 'Startzeit', schedule_weekdays: 'Wochentage',
    schedule_monthdays: 'Monatstage', schedule_months: 'Monate', pre_backup_hook: 'Skript vor dem Backup', post_backup_hook: 'Skript nach dem Backup',
    rsync_extra_excludes: 'Zusätzliche Ausschlüsse', root_permission_ack: 'Root-Freigabe', mail_notify_enabled: 'Mailbenachrichtigung',
    mail_notify_to: 'Mailadresse', mail_notify_success: 'Mail bei Erfolg', mail_notify_failure: 'Mail bei Fehler', mail_notify_stopped: 'Mail bei Abbruch',
    mail_notify_restore: 'Mail bei Restore', stop_targets: 'Zu stoppende Dienste/Container', create_export_after_backup: 'Export nach dem Backup',
    retention_mode: 'Aufbewahrungsart', keep_daily: 'Tagesstände', keep_weekly: 'Wochenstände', keep_monthly: 'Monatsstände',
    log_retention_days: 'Log-Aufbewahrung', quarantine_retention_days: 'Quarantäne-Aufbewahrung', integrity_enabled: 'Regelmässige Integritätsprüfung', integrity_interval_days: 'Prüfintervall'
  };
  function byId(id) { return document.getElementById(id); }
  function all(selector, target) { return Array.from((target || app).querySelectorAll(selector)); }
  function el(tag, text, className) { var node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
  function actionOf(form) { return (form.querySelector('[name="action"]') || {}).value || ''; }
  function settingsForm(form) { return form && (form.id === 'settings-save-form' || form.id === 'maintenance-settings-form'); }
  function controls(name) { return all('#settings-save-form [name], #maintenance-settings-form [name]').filter(function (item) { return item.name === name && !/^(hidden|submit|button|file)$/.test(item.type); }); }
  function names() { return Array.from(new Set(all('#settings-save-form [name], #maintenance-settings-form [name]').filter(function (item) { return !/^(hidden|submit|button|file)$/.test(item.type); }).map(function (item) { return item.name; }))); }
  function states() { var result = {}; names().forEach(function (name) { result[name] = controlState(controls(name)); }); return result; }
  function capture(form) { names().forEach(function (name) { if (!form || controls(name).some(function (item) { return item.form === form; })) { initial[name] = controlState(controls(name)); delete changed[name]; } }); }
  function dirty() { return pendingDraft || Object.keys(changed).length > 0; }
  function readable(name, value) {
    if (/hook$/.test(name)) return value ? 'Eingetragen' : 'Leer';
    if (name === 'rsync_extra_excludes') return value.split(/\r?\n/).filter(function (line) { return line.trim(); }).length + ' Einträge';
    if (name === 'stop_targets') return (value ? value.split('\u001f').length : 0) + ' Ziele ausgewählt';
    return value.replace(/\u001f/g, ', ').slice(0, 120) || 'Keine Auswahl / leer';
  }
  function renderDirty() {
    var popup = byId('settings-change-popup'), list = byId('settings-change-list');
    if (!popup || !list) return;
    list.replaceChildren();
    Object.keys(changed).forEach(function (name) {
      var item = el('li'), copy = el('span'), time = el('time', changed[name].at.toLocaleTimeString());
      copy.append(el('strong', labels[name] || name), el('small', readable(name, changed[name].value)));
      time.dateTime = changed[name].at.toISOString(); item.append(copy, time); list.append(item);
    });
    if (pendingDraft) list.append(el('li', 'Nicht gespeicherte Eingaben aus dem vorherigen Versuch. Bitte prüfen und erneut speichern.'));
    popup.classList.toggle('is-visible', dirty()); popup.setAttribute('aria-hidden', dirty() ? 'false' : 'true');
    byId('settings-change-title').textContent = 'Ungespeicherte Änderungen' + (Object.keys(changed).length ? ' (' + Object.keys(changed).length + ')' : '');
  }
  function onSettingChange(event) {
    if (!settingsForm(event.target.form) || !event.target.name || event.target.type === 'hidden') return;
    updateDirty(initial, changed, event.target.name, controlState(controls(event.target.name)), new Date());
    updateSchedule(); renderDirty(); clearPreflight();
  }
  function feedback(text, kind) { var node = byId('action-feedback'); node.textContent = text; node.className = 'notice ' + (kind || ''); node.hidden = false; }
  function requireSaved() {
    if (!dirty()) return true;
    feedback('Zuerst Änderungen speichern: Backup, Vorschau und Wartung verwenden ausschliesslich den gespeicherten Stand. Deine Eingaben bleiben erhalten.', 'warning');
    byId('settings-change-popup').querySelector('button[type="submit"]').focus(); return false;
  }
  function url(action, params) { var value = new URL(root.location.pathname, root.location.href); value.searchParams.set('action', action); Object.keys(params || {}).forEach(function (key) { value.searchParams.set(key, params[key]); }); value.searchParams.set('_', Date.now()); return value.href; }
  async function request(action, params, options) {
    options = Object.assign({ cache: 'no-store', credentials: 'same-origin' }, options || {});
    var controller = new AbortController(), timeout = root.setTimeout(function () { controller.abort(); }, options.timeout || 20000);
    options.signal = controller.signal; delete options.timeout;
    try {
      var response = await root.fetch(url(action, params), options);
      var text = await response.text(), data;
      try { data = JSON.parse(text); } catch (ignore) { data = { ok: false, error: 'Unerwartete Serverantwort (HTTP ' + response.status + ').' }; }
      if (!response.ok || data.ok === false && !data.requires_confirmation) throw new Error(data.error || 'HTTP ' + response.status);
      return data;
    } catch (error) { if (error.name === 'AbortError') throw new Error('Die Antwort dauert zu lange. Der Vorgang kann im Hintergrund weiterlaufen. Bitte Status prüfen, bevor du ihn erneut startest.'); throw error; }
    finally { root.clearTimeout(timeout); }
  }
  async function refreshCSRF() {
    if (!csrfRefresh) csrfRefresh = request('csrf-token').then(function (data) {
      var token = data.csrf_token || data.token;
      if (!token) throw new Error('Sitzungsbestätigung konnte nicht erneuert werden. Eingaben bleiben erhalten.');
      app.dataset.csrfToken = token; all('[name="csrf_token"]').forEach(function (input) { input.value = token; }); return token;
    }).finally(function () { csrfRefresh = null; });
    return csrfRefresh;
  }
  function csrfFields() { var input = el('input'); input.type = 'hidden'; input.name = 'csrf_token'; input.value = app.dataset.csrfToken; return input; }
  function clearPreflight() { all('.preflight-confirm').forEach(function (node) { node.remove(); }); }
  function showPreflight(form, data) {
    clearPreflight(); var label = el('label', undefined, 'checkline preflight-confirm'), checkbox = el('input');
    checkbox.type = 'checkbox'; checkbox.name = 'accept_preflight_warnings'; checkbox.value = '1'; checkbox.required = true; checkbox.dataset.role = 'none';
    label.append(checkbox, el('span', 'Backup trotz dieser Warnhinweise starten')); form.prepend(label);
    feedback('Backup noch nicht gestartet: ' + data.warning + ' Prüfe die Warnung und bestätige sie nur, wenn du fortfahren möchtest.', 'warning');
  }
  async function fragment(action, target) {
    if (!target) return;
    var controller = new AbortController(), timer = root.setTimeout(function () { controller.abort(); }, 20000);
    try {
      var response = await root.fetch(url(action, currentTask ? { active_task: currentTask } : {}), { cache: 'no-store', credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      target.innerHTML = await response.text(); enhanceTables(target);
      if (action === 'stop-targets') {
        if (pendingDraft) { var values = JSON.parse(app.dataset.draftStops || '[]'); all('[name="stop_targets"]', target).forEach(function (input) { input.checked = values.indexOf(input.value) !== -1; }); }
        initial.stop_targets = controlState(controls('stop_targets'));
      }
    } catch (error) {
      // Never replace existing settings or a usable old fragment after a refresh error.
      if (action === 'backup-list' && !target.querySelector('form')) target.innerHTML = '<tr><td colspan="8">Backup-Liste konnte nicht geladen werden. Bitte später erneut versuchen.</td></tr>';
      else if (action === 'stop-targets' && !target.querySelector('input')) target.textContent = 'Dienste konnten nicht geladen werden; ihre gespeicherte Auswahl wird beim Speichern beibehalten.';
      else if (action === 'target-notice') target.textContent = 'Dateisystem-Prüfung momentan nicht erreichbar. Gespeicherte Einstellungen bleiben erhalten.';
    } finally { root.clearTimeout(timer); }
  }
  function updateSchedule() {
    var mode = controlState(controls('schedule_mode'));
    all('[data-schedule-panel]').forEach(function (panel) { panel.classList.toggle('schedule-hidden', panel.dataset.schedulePanel !== mode); });
    var allMonths = app.querySelector('[name="schedule_months"][value="*"]');
    all('[name="schedule_months"]:not([value="*"])').forEach(function (input) { input.disabled = !!(allMonths && allMonths.checked); });
  }
  function enhanceTables(target) {
    all('table', target).forEach(function (table) {
      var headings = all('thead th', table).map(function (th) { return th.textContent.trim(); });
      all('tbody tr', table).forEach(function (row) { Array.from(row.children).forEach(function (cell, index) { if (!cell.dataset.label && headings[index] && !cell.hasAttribute('colspan')) cell.dataset.label = headings[index]; }); });
    });
  }
  function positionInfoBubble(help) {
    var bubble = help.querySelector('.info-bubble'); if (!bubble) return;
    bubble.style.marginLeft = '0px'; bubble.classList.remove('info-bubble-above');
    var rect = bubble.getBoundingClientRect(), shift = Math.min(0, root.innerWidth - 12 - rect.right);
    if (rect.left + shift < 12) shift += 12 - rect.left - shift;
    bubble.style.marginLeft = shift + 'px'; rect = bubble.getBoundingClientRect();
    if (rect.bottom > root.innerHeight - 12 && help.getBoundingClientRect().top > rect.height + 12) bubble.classList.add('info-bubble-above');
  }
  function infoEvent(event) { var help = event.target.closest('.info-help'); if (help) positionInfoBubble(help); }
  document.addEventListener('pointerover', infoEvent);
  document.addEventListener('focusin', infoEvent);
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') { all('.info-help.is-open').forEach(function (help) { help.classList.remove('is-open'); help.querySelector('.info-button').setAttribute('aria-expanded', 'false'); }); if (document.activeElement && document.activeElement.closest('.info-help')) document.activeElement.blur(); } });
  root.addEventListener('resize', function () { all('.info-help').filter(function (help) { return help.matches(':hover') || help.contains(document.activeElement); }).forEach(positionInfoBubble); });
  function byteLabel(bytes) { if (bytes === null || bytes === undefined) return 'unbekannt'; var value = Number(bytes), unit = 0, units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; while (value >= 1024 && unit < 4) { value /= 1024; unit += 1; } return value.toLocaleString('de-CH', { maximumFractionDigits: 2 }) + ' ' + units[unit]; }
  function reportRows(target, headers, rows) {
    var table = el('table', undefined, 'report-table'), head = el('thead'), body = el('tbody'), tr = el('tr');
    headers.forEach(function (header) { tr.append(el('th', header)); }); head.append(tr);
    rows.forEach(function (row) { var line = el('tr'); row.forEach(function (value, index) { var td = el('td', String(value === undefined || value === null ? '' : value)); td.dataset.label = headers[index]; line.append(td); }); body.append(line); }); table.append(head, body); target.append(table);
  }
  function renderReport(action, data) {
    if (reportDownloadUrl) { URL.revokeObjectURL(reportDownloadUrl); reportDownloadUrl = null; }
    var target = byId('operation-result'); target.replaceChildren(); target.hidden = false;
    if (action === 'backup-preview') {
      target.append(el('h3', 'Vorschau des nächsten Backups'), el('p', 'Gespeicherter Stand: ' + data.backup_mode + ' / ' + data.metadata_mode));
      target.append(el('p', data.full_baseline_required ? 'Neue vollständige Basiskopie erforderlich. Der erste Lauf benötigt erneut Platz für alle ausgewählten Daten; erst danach können passende Snapshots Platz teilen.' : 'Inkrementelle Referenz: ' + (data.reference_id || 'keine')));
      target.append(el('p', 'Verfügbar: ' + byteLabel(data.available_mb == null ? null : data.available_mb * 1048576) + ' · geschätzte Basiskopie: ' + byteLabel(data.baseline_estimate_mb == null ? null : data.baseline_estimate_mb * 1048576)));
      reportRows(target, ['Datenquelle', 'Im Backup', 'Grund'], (data.source_volumes || []).map(function (volume) { return [volume.path, volume.included ? 'Ja' : 'Nein', volume.reason]; }));
      var exclusions = el('details'), list = el('ul'); exclusions.append(el('summary', 'Wirksame Ausschlüsse')); (data.excludes || []).forEach(function (rule) { list.append(el('li', rule)); }); exclusions.append(list); target.append(exclusions);
    } else if (action === 'storage-info') {
      target.append(el('h3', 'Speicherbelegung'), el('p', 'Backups ohne doppelt gezählte Hardlinks: ' + byteLabel(data.backups_unique_allocated_bytes) + ' · Exporte: ' + byteLabel(data.exports_bytes) + ' · fehlgeschlagene Backups: ' + byteLabel(data.failed_bytes)));
      target.append(el('p', 'Logische Dateigrösse und belegter Speicher unterscheiden sich. Gemeinsam genutzte Dateien dürfen nicht pro Snapshot aufsummiert werden.'));
      target.append(el('p', 'Zusatzbedarf des nächsten Laufs: noch nicht sicher bestimmbar. Eine Schätzung für eine neue Basiskopie steht in der Sicherungsvorschau.'));
      if (data.root_state) target.append(el('p', 'Auf dem LoxBerry-System: Logs ' + byteLabel(data.root_state.logs_bytes) + ' · Quarantäne ' + byteLabel(data.root_state.quarantine_bytes) + ' · Prüfsummen-Basen ' + byteLabel(data.root_state.integrity_bytes) + ' · freier Systemplatz ' + byteLabel(data.root_state.free_bytes)));
      reportRows(target, ['Backup', 'Status', 'Logische Grösse', 'Belegte Blöcke', 'Geteilte Dateien'], (data.backups || []).map(function (item) { return [item.backup_id, item.status, byteLabel(item.logical_bytes), byteLabel(item.allocated_bytes), item.shared_file_count]; }));
    } else if (/^(maintenance-preview|maintenance-run|runtime-cleanup-preview|runtime-cleanup-run)$/.test(action)) {
      target.append(el('h3', data.applied ? 'Wartung abgeschlossen' : 'Löschvorschau – noch nichts gelöscht'));
      reportRows(target, ['Bleibt erhalten', 'Grund'], (data.keep || []).map(function (item) { return [item.backup_id, (item.reasons || []).join(', ')]; }));
      reportRows(target, ['Zur Löschung vorgesehen', 'Status', 'Belegte Blöcke'], (data.delete || []).map(function (item) { return [item.backup_id, item.status, byteLabel(item.allocated_bytes)]; }));
      if (!data.applied && data.preview_digest && ((data.delete || []).length || (data.artifacts || []).length || (data.files || []).length)) {
        var form = el('form'); form.method = 'post'; form.dataset.ajax = 'false'; form.append(csrfFields());
        [['action', action.indexOf('runtime-') === 0 ? 'runtime-cleanup-run' : 'maintenance-run'], ['preview_digest', data.preview_digest]].forEach(function (item) { var input = el('input'); input.type = 'hidden'; input.name = item[0]; input.value = item[1]; form.append(input); });
        var button = el('button', 'Genau diese Löschvorschau ausführen', 'danger'); button.type = 'submit'; form.append(button); target.append(form);
      }
      if (data.artifacts && data.artifacts.length) reportRows(target, ['Weitere Bereinigung', 'Typ'], data.artifacts.map(function (item) { return [item.path || item.name, item.kind || item.type]; }));
      if (data.files) reportRows(target, ['Laufzeitdatei', 'Bereich', 'Grösse'], data.files.map(function (item) { return [item.name, item.directory, byteLabel(item.size_bytes)]; }));
    } else if (action === 'verification-report' || action === 'inspect-backup' || action === 'record-restore-test') {
      target.append(el('h3', action === 'record-restore-test' ? 'Persönlicher Restore-Test' : action === 'verification-report' ? 'Integritätsbericht' : 'Strukturprüfung'));
      var statusLabels = { baseline_created: 'Prüfsummen-Basis wurde neu erstellt. Das ist noch kein Vergleich mit einem früher bekannten Stand.', verified: 'Dateien stimmen mit der gespeicherten Prüfsummen-Basis überein.', changed: 'Änderungen zur Prüfsummen-Basis gefunden.', error: 'Prüfung konnte nicht vollständig durchgeführt werden.' };
      if (action !== 'record-restore-test') target.append(el('p', statusLabels[data.status] || ('Status: ' + (data.status || 'siehe Prüfergebnis'))));
      if (data.restore_test) {
        var manual = data.restore_test;
        target.append(el('p', 'Persönlich dokumentierter Restore-Test: ' + (manual.result === 'passed' ? 'Erfolgreich' : 'Fehlgeschlagen') + ' am ' + manual.tested_at + '. Vom Plugin nicht überprüft.'));
        if (!manual.applies_to_current_manifest) target.append(el('p', 'Dieser Eintrag bezieht sich auf einen früheren Manifeststand, nicht auf den aktuellen Backup-Stand.'));
      } else target.append(el('p', 'Restore-Test: nicht nachgewiesen. Noch kein persönlicher Testeintrag vorhanden.'));
      target.append(el('p', 'Eine Struktur- oder Prüfsummenprüfung ersetzt keinen erfolgreichen Restore-Test. Persönliche Testeinträge ändern keine Restore-Freigaben.'));
      if (data.restore_test_history && data.restore_test_history.length) reportRows(target, ['Testzeitpunkt (UTC)', 'Persönliches Ergebnis', 'Notiz', 'Aktueller Backup-Stand'], data.restore_test_history.map(function (entry) { return [entry.tested_at, entry.result === 'passed' ? 'Erfolgreich' : 'Fehlgeschlagen', entry.note || '', entry.applies_to_current_manifest ? 'Ja' : 'Nein']; }));
      if (action === 'verification-report') target.append(el('p', 'Geprüft am: ' + (data.checked_at || 'unbekannt') + ' · Vergleichsbasis vom: ' + (data.baseline_at || 'unbekannt')));
      if (data.changes) reportRows(target, ['Datei', 'Änderung'], data.changes.map(function (item) { return [item.path, item.change]; }));
      if (action === 'verification-report') {
        var reportText = JSON.stringify(data, null, 2);
        if (reportText.length <= 16777216) {
          reportDownloadUrl = URL.createObjectURL(new Blob([reportText], { type: 'application/json;charset=utf-8' }));
          var download = el('a', 'Prüfbericht herunterladen', 'button-link'); download.id = 'verification-download'; download.href = reportDownloadUrl;
          download.download = String(data.backup_id || 'backup').replace(/[^A-Za-z0-9._-]/g, '_') + '-verification.json'; download.dataset.ajax = 'false'; target.append(download);
        }
      }
    } else target.append(el('h3', 'Ergebnis'));
    var details = el('details'), raw = el('pre', JSON.stringify(data, null, 2)); details.append(el('summary', 'Technische Details'), raw); target.append(details);
  }
  function taskName(task) { return ({ backup: 'Backup', restore: 'Restore', export: 'Export', import: 'Import', verify: 'Integritätsprüfung' })[(task || '').split('-')[0]] || 'Vorgang'; }
  function selectTask(task, explicit) {
    if (!task) return;
    if (explicit) userSelectedTask = true;
    if (task === currentTask) return;
    currentTask = task; finalTask = ''; followLog = true; byId('task-log').textContent = 'Log wird geladen...';
    var input = byId('stop-task-form').querySelector('[name="task"]'); input.value = task; pollTask();
  }
  async function overview() {
    if (overviewInFlight) return; overviewInFlight = true;
    try {
      var data = await request('task-overview'), target = byId('overview-values'); target.replaceChildren();
      byId('recover-services-form').hidden = !data.pending_service_recovery;
      [['Letztes erfolgreiches Backup', data.last_success ? data.last_success.backup_id + ' · ' + (data.last_success.finished_at || '') : 'Noch keines bekannt'],
        ['Nächster Termin', data.next_run ? data.next_run.local || data.next_run.note || 'Zeitplan deaktiviert' : 'Zeitplan deaktiviert'],
        ['Backup-Ziel', data.target && data.target.configured ? data.target.path : 'Noch nicht konfiguriert'],
        ['Freier Speicher am Ziel', data.target && data.target.readable ? byteLabel(data.target.available_mb * 1048576) : 'Momentan nicht ermittelbar'],
        ['Aktueller Vorgang', data.active_task || 'Keiner'], ['Letzter Fehler', data.last_failure ? data.last_failure.task + ' · ' + data.last_failure.state : 'Keiner bekannt']].forEach(function (item) { var card = el('div'); card.append(el('strong', item[0]), el('span', String(item[1]))); target.append(card); });
      var select = byId('task-history'), tasks = data.tasks || []; select.replaceChildren(el('option', 'Vorgang auswählen'));
      select.firstChild.value = ''; tasks.forEach(function (item) { var option = el('option', item.task + ' · ' + (item.state || '')); option.value = item.task; select.append(option); });
      var active = typeof data.active_task === 'object' ? data.active_task.task : data.active_task;
      if (active && !userSelectedTask && (!currentTask || currentTask === finalTask)) selectTask(active, false);
      if (currentTask && !tasks.some(function (item) { return item.task === currentTask; })) { var extra = el('option', currentTask); extra.value = currentTask; select.append(extra); }
      select.value = currentTask;
    } catch (error) { if (!byId('overview-values').querySelector('strong')) byId('overview-values').textContent = 'Übersicht momentan nicht erreichbar. Sie wird erneut geladen.'; }
    finally { overviewInFlight = false; }
  }
  async function pollTask() {
    if (!currentTask || taskInFlight) return; var task = currentTask; taskInFlight = true;
    try {
      var data = await request('task-status', { task: task }); if (task !== currentTask) return;
      var state = data.state || 'running', terminal = /^(finished|failed|cleanup_failed|stopped|interrupted|error)$/.test(state);
      byId('task-state').className = 'task-state state-' + state;
      byId('task-state').textContent = taskName(task) + ' ' + ({ running: 'läuft', starting: 'startet', queued: 'wartet', finished: 'abgeschlossen', failed: 'fehlgeschlagen', cleanup_failed: 'fehlgeschlagen; Wiederanlauf unvollständig', stopped: 'gestoppt', interrupted: 'unterbrochen', stale: 'ohne neue Ausgabe', error: 'Status nicht verfügbar' }[state] || state);
      byId('task-heartbeat').textContent = (data.phase ? 'Phase: ' + data.phase + '. ' : '') + (terminal ? 'Die Eingaben auf dieser Seite bleiben erhalten.' : 'Letzte Log-Aktualisierung vor ' + Math.max(0, Number(data.now || 0) - Number(data.mtime || 0)) + ' Sekunden.');
      var content = ''; try { content = new TextDecoder().decode(Uint8Array.from(root.atob(data.content_b64 || ''), function (char) { return char.charCodeAt(0); })); } catch (ignore) { content = data.content || ''; }
      var log = byId('task-log'), left = log.scrollLeft, top = log.scrollTop, atEnd = followLog && logViewport(log.scrollTop, log.clientHeight, log.scrollHeight);
      var normalized = normalizeLogForDisplay(content) || data.error || 'Noch keine Logausgabe vorhanden.';
      if (log.textContent !== normalized) log.textContent = normalized;
      log.scrollLeft = left; log.scrollTop = atEnd ? log.scrollHeight : top;
      byId('download-task-log').href = url('download-log', { task: task }); byId('download-task-log').hidden = false;
      byId('stop-task-form').hidden = terminal || task.indexOf('backup-') !== 0;
      byId('stop-task-form').querySelector('[name="task"]').value = task;
      if (terminal && finalTask !== task) { finalTask = task; fragment('backup-list', byId('backup-list-body')); overview(); }
    } catch (error) { byId('task-heartbeat').textContent = 'Status momentan nicht erreichbar; der Vorgang kann weiterlaufen. Automatischer neuer Versuch folgt.'; }
    finally { taskInFlight = false; }
  }
  function setBusy(form, busy) {
    if (busy) { busyForms.add(form); busyCount += 1; } else { busyForms.delete(form); busyCount = Math.max(0, busyCount - 1); }
    form.setAttribute('aria-busy', busy ? 'true' : 'false');
    // Keep controls editable: a failed request must not discard a user's newer draft.
  }
  async function submitForm(form) {
    if (busyForms.has(form)) return false;
    var action = actionOf(form);
    if (action === 'backup' && !requireSaved()) return false;
    if (action === 'maintenance-preview' && !requireSaved()) return false;
    if (action === 'save-config') { var error = validateSettings(states()); if (error) { feedback(error, 'warning'); return false; } }
    if (action === 'import-config' && dirty() && !root.confirm('Die importierten Einstellungen ersetzen den gespeicherten Stand und deine ungespeicherten Eingaben. Trotzdem importieren?')) return false;
    var confirmations = { 'delete-backup': 'Dieses Backup dauerhaft löschen? Geschützte und die letzte geeignete Sicherung bleiben gesperrt.', 'delete-export': 'Nur dieses Exportarchiv löschen? Der Backup-Snapshot bleibt erhalten.', 'restore-backup': 'Restore wirklich starten? Die Ziel-Systemdateien werden überschrieben. Ausschlüsse und Volume-Zuordnung in der Vorschau vorher prüfen.', 'stop-backup': 'Backup stoppen? Bereits gestoppte Dienste und Container werden anhand des Wiederanlauf-Journals neu gestartet.', 'maintenance-run': 'Genau die angezeigte Löschvorschau ausführen? Diese Dateien werden dauerhaft entfernt.' };
    if (action === 'runtime-cleanup-run') confirmations[action] = 'Die angezeigten alten Log- und Quarantänedateien endgültig löschen? Offene Wiederanlauf-Journale bleiben erhalten.';
    if (action === 'recover-services') confirmations[action] = 'Die im offenen Wiederanlauf-Journal vermerkten Dienste jetzt erneut starten?';
    if (confirmations[action] && !root.confirm(confirmations[action])) return false;
    setBusy(form, true); var submitted, importDraft = action === 'import-config' ? states() : null;
    try {
      var token = await refreshCSRF();
      if ((action === 'backup' || action === 'maintenance-preview') && !requireSaved()) return false;
      if (action === 'save-config') { var validationError = validateSettings(states()); if (validationError) { feedback(validationError, 'warning'); return false; } }
      // One synchronous snapshot: inputs may change while the token request is in flight.
      submitted = states();
      var body = new FormData(form); body.set('csrf_token', token);
      if (action === 'record-restore-test') {
        var testDate = new Date(body.get('tested_at'));
        if (!Number.isFinite(testDate.getTime())) throw new Error('Bitte einen gültigen Testzeitpunkt angeben.');
        body.set('tested_at', testDate.toISOString());
      }
      if (action === 'maintenance-config') { var policy = {}; Array.from(form.elements).forEach(function (item) { if (labels[item.name]) policy[item.name] = item.type === 'checkbox' ? item.checked : item.type === 'number' ? Number(item.value) : item.value; }); body.set('policy_json', JSON.stringify(policy)); }
      var multipart = form.enctype === 'multipart/form-data';
      feedback('Aktion wird ausgeführt. Eingaben bleiben bei einem Fehler erhalten.');
      var data = await request(action, {}, { method: 'POST', headers: { 'X-HostBackup-Request': '1', 'X-CSRF-Token': token }, body: multipart ? body : new URLSearchParams(body), timeout: multipart || /maintenance-run|save-config|restore-backup/.test(action) ? 3600000 : 120000 });
      if (data.requires_confirmation) { showPreflight(form, data); return false; }
      if (action === 'save-config' || action === 'maintenance-config') {
        Object.keys(submitted).forEach(function (name) { if (controls(name).some(function (item) { return item.form === form; })) { initial[name] = submitted[name]; updateDirty(initial, changed, name, controlState(controls(name)), new Date()); } });
        if (action === 'save-config') { pendingDraft = false; pendingImport = false; }
        renderDirty(); clearPreflight(); fragment('target-notice', byId('target-notice')); overview();
        feedback(dirty() ? 'Gespeichert. Währenddessen geänderte Eingaben sind noch ungespeichert.' : 'Einstellungen gespeichert. Backups verwenden jetzt diesen Stand.', 'ok');
      } else if (action === 'import-config') {
        // Only this explicitly requested replacement navigates; never task completion.
        if (JSON.stringify(importDraft) !== JSON.stringify(states())) { pendingImport = true; feedback('Import gespeichert. Inzwischen wurden weitere Eingaben geändert; diese bleiben hier erhalten. Zum Anzeigen des importierten Stands die Seite nach dem Sichern deiner Eingaben neu laden.', 'warning'); }
        else { changed = {}; pendingDraft = false; intentionalNavigation = true; root.location.assign(root.location.pathname); }
      } else {
        if (data.redirect) { var redirect = new URL(data.redirect, root.location.href), task = redirect.searchParams.get('active_task'); if (task) { selectTask(task, false); userSelectedTask = false; } }
        if (data.data) renderReport(action, data.data);
        feedback(data.message || 'Aktion abgeschlossen bzw. im Hintergrund gestartet.', 'ok');
        fragment('backup-list', byId('backup-list-body')); overview(); pollTask();
      }
      return true;
    } catch (error) { feedback(error.message + ' Deine Eingaben wurden nicht verworfen.', 'error'); return false; }
    finally { setBusy(form, false); }
  }
  document.addEventListener('submit', async function (event) {
    var form = event.target; if (!app.contains(form)) return;
    if ((form.method || 'get').toLowerCase() !== 'post') {
      if (!form.classList.contains('operation-form')) return;
      event.preventDefault(); var params = Object.fromEntries(new FormData(form));
      try { renderReport(params.action, await request(params.action, params)); } catch (error) { feedback(error.message, 'error'); } return;
    }
    event.preventDefault();
    if (form.id === 'settings-save-form' && byId('maintenance-settings-form')) {
      if (await submitForm(form)) { var advanced = byId('maintenance-settings-form'); if (Object.keys(changed).some(function (name) { return controls(name).some(function (control) { return control.form === advanced; }); })) await submitForm(advanced); }
    } else await submitForm(form);
  });
  document.addEventListener('input', onSettingChange);
  document.addEventListener('change', onSettingChange);
  document.addEventListener('click', async function (event) {
    var info = event.target.closest('.info-button');
    if (info) { event.preventDefault(); var help = info.closest('.info-help'); help.classList.toggle('is-open'); info.setAttribute('aria-expanded', help.classList.contains('is-open') ? 'true' : 'false'); positionInfoBubble(help); return; }
    var picker = event.target.closest('[data-backup-root]');
    if (picker) { event.preventDefault(); setBackupRoot(picker.dataset.backupRoot); return; }
    var preset = event.target.closest('[data-stop-target-preset]');
    if (preset) { event.preventDefault(); all('[name="stop_targets"]').forEach(function (box) { box.checked = preset.dataset.stopTargetPreset === 'recommended' && box.dataset.recommended === '1'; }); updateDirty(initial, changed, 'stop_targets', controlState(controls('stop_targets')), new Date()); renderDirty(); return; }
    var load = event.target.closest('[data-load-action]');
    if (load) { event.preventDefault(); if (load.dataset.loadAction === 'backup-preview' && !requireSaved()) return; load.disabled = true; feedback('Ergebnis wird berechnet...'); try { renderReport(load.dataset.loadAction, await request(load.dataset.loadAction, {}, { timeout: 3600000 })); byId('action-feedback').hidden = true; } catch (error) { feedback(error.message, 'error'); } finally { load.disabled = false; } return; }
    var preview = event.target.closest('[data-restore-preview]');
    if (preview) { var form = preview.closest('form'); preview.disabled = true; try { var data = new FormData(form), result = await request('restore-plan', { backup_id: data.get('backup_id'), destination: data.get('restore_destination'), volume_map: data.get('restore_volume_map') }, { timeout: 3600000 }); byId('restore-plan-output').textContent = result.text; byId('restore-plan-output').hidden = false; } catch (error) { feedback(error.message, 'error'); } finally { preview.disabled = false; } }
  });
  function setBackupRoot(path) { var input = byId('backup-root-input'); if (input && path) { input.value = path; input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true })); input.focus(); } }
  document.addEventListener('dragstart', function (event) { var picker = event.target.closest('[data-backup-root]'); if (picker && event.dataTransfer) event.dataTransfer.setData('text/plain', picker.dataset.backupRoot); });
  byId('backup-root-input').addEventListener('dragover', function (event) { event.preventDefault(); });
  byId('backup-root-input').addEventListener('drop', function (event) { event.preventDefault(); setBackupRoot(event.dataTransfer.getData('text/plain')); });
  byId('settings-change-toggle').addEventListener('click', function () { var list = byId('settings-change-list'); list.hidden = !list.hidden; this.setAttribute('aria-expanded', list.hidden ? 'false' : 'true'); this.textContent = list.hidden ? 'Details anzeigen' : 'Details ausblenden'; });
  byId('task-history').addEventListener('change', function () { selectTask(this.value, true); });
  byId('task-log').addEventListener('scroll', function () { followLog = logViewport(this.scrollTop, this.clientHeight, this.scrollHeight); });
  byId('log-follow').addEventListener('click', function () { followLog = true; byId('task-log').scrollTop = byId('task-log').scrollHeight; });
  root.addEventListener('beforeunload', function (event) { if (!intentionalNavigation && (dirty() || busyCount || pendingImport)) { event.preventDefault(); event.returnValue = ''; } });
  root.addEventListener('pagehide', function () { if (reportDownloadUrl) URL.revokeObjectURL(reportDownloadUrl); });
  root.addEventListener('focus', function () { refreshCSRF().catch(function () {}); overview(); });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { refreshCSRF().catch(function () {}); overview(); pollTask(); } });
  capture(); renderDirty(); updateSchedule(); enhanceTables(app); byId('stop-task-form').hidden = true;
  fragment('target-notice', byId('target-notice')); fragment('backup-list', byId('backup-list-body')); fragment('stop-targets', byId('stop-targets-list'));
  overview(); pollTask(); root.setInterval(function () { if (!document.hidden) { overview(); pollTask(); } }, 5000);
  root.setInterval(function () { if (!document.hidden) refreshCSRF().catch(function () {}); }, 1800000);
}(typeof window === 'undefined' ? globalThis : window));
