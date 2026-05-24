# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Dieses Projekt befindet sich noch in einem frühen Entwicklungsstand. Es gibt
noch keine freigegebene produktive Version.

## [Unreleased]

### Dokumentation

- README vollständig auf den aktuellen Funktionsstand gebracht.
- Installations-, Ersttest- und Bedienablauf so ergänzt, dass eine fremde Person
  das Plugin installieren, konfigurieren und testen kann.
- Status klarer beschrieben: Installation, Konfiguration und echte Backups sind
  getestet; ein produktiver Ende-zu-Ende-Restore ist noch offen.
- USB-Beispiel für Backup-Ziel und Ausschlüsse ergänzt.
- Vollbackup, inkrementeller Snapshot, erster Snapshot als Basiskopie und
  Hardlink-Voraussetzungen dokumentiert.
- Live-Status, Backup-Liste, Explorer, Export, Löschen, Import externer
  Archive und Restore-Auswahl beschrieben.
- Verhalten laufender oder unvollständiger Backups dokumentiert.
- Einstellungen-Export/-Import und Grenzen von Export-Archiven beschrieben.
- Deinstallation und verbleibende externe Backup-Daten dokumentiert.

### LoxBerry-Kompatibilität

- Sudoers-Regel in den LoxBerry-Standardordner `sudoers/sudoers` verschoben,
  damit LoxBerry sie während der Plugin-Installation selbst installiert.
- `postinstall.sh` schreibt nicht mehr direkt nach `/etc/sudoers.d`, da das
  Postinstall-Skript auf LoxBerry ohne Root-Rechte laufen kann.
- `uninstall.sh` entfernt den Cron-Eintrag defensiv; die sudoers-Datei wird von
  LoxBerry verwaltet.
- `postinstall.sh` in den ZIP-Root verschoben, damit LoxBerry das Skript korrekt
  ausführt.
- Restore-Helper von `sbin/` nach `bin/` verschoben, da LoxBerry `sbin/` beim
  Test nicht installiert hat.
- Plugin-Icons ergänzt, damit LoxBerry keine Default-Icon-Warnung ausgeben muss.
- Offizielle LoxBerry-Plugin-Pfadvariablen berücksichtigt.
- Skriptpfad-basierte Erkennung des tatsächlichen Pluginordners ergänzt.
- Default-Konfiguration in das Plugin-Verzeichnis `config/` verschoben.
- `postinstall.sh` nutzt LoxBerry-Installationsargumente für Pluginordner und
  Basisverzeichnis.
- Web-Backend-Aufrufe verwenden `sudo -n`, damit fehlende sudoers-Regeln nicht
  hängen bleiben.

### Planung Und Aufbewahrung

- Zeitgesteuerte Backups per `/etc/cron.d/loxberryhostbackup` ergänzt.
- Auswahl für tägliche, wöchentliche und monatliche Backups ergänzt.
- Wöchentlicher Zeitplan kann mehrere Wochentage speichern und als Cron-Liste
  ausgeben.
- Monatlicher Zeitplan kann mehrere Monatstage sowie einzelne Monate speichern
  und als Cron-Liste ausgeben.
- Monatliche Backups erhalten einen Fallback auf den letzten Tag des Monats,
  wenn ein gewählter Monatstag wie 29, 30 oder 31 im jeweiligen Monat nicht
  existiert.
- Der Cron-Aufruf bleibt beim Monatsende-Fallback auf die relevanten
  Monatsend-Tage begrenzt.
- Info-Texte zum Zeitplan erklären detailliert, welche Felder bei täglich,
  wöchentlich und monatlich relevant sind.
- Zeitplan-Oberfläche klarer strukturiert.
- Aufbewahrung auf 1 bis 10 Backups begrenzt.
- Retention-Regel ergänzt: Bei gesetztem Limit werden nach erfolgreichem Backup
  alte Backups entfernt.
- Retention berücksichtigt nur vollständig abgeschlossene Backups mit
  `manifest.json`-Status `complete`, damit laufende oder unvollständige
  Backups nicht versehentlich in die normale Rotation fallen.
- Cron-Eintrag wird bei Deinstallation entfernt.

### Weboberfläche

- Dateisystem-Prüfung für das Backup-Verzeichnis ergänzt. Die Oberfläche zeigt
  den erkannten Dateisystemtyp, Mount und freien Speicher an und warnt bei
  NTFS/FUSE bzw. nicht typischen Linux-Dateisystemen, besonders für
  inkrementelle Snapshots. Der Hinweis nennt zusätzlich, dass `ext4` in der
  Praxis deutlich schneller als NTFS/FUSE sein kann.
- Kopfbereich mit Plugin-Icon, kompakter Titelgestaltung und Link zurück zur
  LoxBerry-Administration überarbeitet.
- Sichtbare deutsche Texte in der Weboberfläche auf echte Umlaute vereinheitlicht.
- Einstellungen-Seite ergänzt.
- Backup-Verzeichnis, Backup-Modus, Ausschlüsse, Docker-Verhalten, automatische
  Exporte, Retention, Zeitplan und Hooks konfigurierbar gemacht.
- Backup-Modus kann zwischen Vollbackup und inkrementellem Snapshot gewählt
  werden.
- Einstellungen können als JSON-Datei exportiert und nach einer Neuinstallation
  wieder importiert werden.
- Info-Buttons mit Hover-/Fokus-Hinweisen für Einstellungen und Backup-Aktionen
  ergänzt.
- Sicherheitsbestätigung für Root-Freigaben ergänzt.
- Backup- und Restore-Start prüfen, ob die Root-Freigabe zuvor bestätigt wurde.
- Live-Loganzeige für laufende Backup- und Restore-Jobs ergänzt.
- Live-Status unterscheidet laufende, abgeschlossene, fehlgeschlagene und
  gestoppte Jobs klarer.
- Live-Status stoppt die Aktualisierungsanzeige nach Abschluss und lädt die
  Backup-Liste danach neu.
- Live-Status bleibt erhalten, wenn während eines laufenden Backups ein anderes
  vollständiges Backup im Explorer geöffnet wird.
- Stop-Button im Live-Status ergänzt, um laufende Backups abbrechen zu können.
- Backup-Liste zeigt Status, Host, Größe, Dateianzahl, Abschlusszeit,
  Exportstatus und Aktionen.
- Aktionen für laufende oder unvollständige Backups werden gesperrt, bis das
  Backup vollständig abgeschlossen ist.
- Backup-Liste um Aktionen für Dateien anzeigen, Restore auswählen, Export
  herunterladen und Löschen erweitert.
- Backup-Liste um Lösch-Button pro Backup mit Bestätigungsdialog ergänzt.
- Import-Bereich klarer als Import externer `tar.gz`-Backup-Archive benannt.
- Restore-Bereich wird nur noch angezeigt, wenn ein Backup für Restore
  ausgewählt wurde.
- Restore-Bereich mit Backup-Auswahl, Restore-Check, Restore-Plan und
  Startbestätigung aus der Backup-Liste ergänzt.
- Sichtbare Ladeanzeige für längere Formularaktionen ergänzt.
- Formularaktionen leiten nach erfolgreichem Speichern oder Backup-Start auf
  eine normale Seite weiter, damit der Browser beim Aktualisieren keine erneute
  Formularübermittlung anbietet.

### Backend

- `rsync`-basiertes Host-Backup ergänzt.
- Inkrementeller Snapshot-Modus mit `rsync --link-dest` ergänzt; jeder Snapshot
  bleibt direkt restore-fähig.
- Wenn noch kein vorheriges vollständiges Backup existiert, wird der erste
  Snapshot automatisch als vollständige Basiskopie erstellt.
- Preflight-Check warnt bei Snapshot-Modus, wenn das Backup-Ziel kein typisches
  Linux-Dateisystem für Hardlinks ist.
- Restore-Backend ergänzt.
- Manifest pro Backup ergänzt.
- Paketliste, systemd-Service-Liste, Mount-Liste und Docker-Inventar ergänzt.
- Backup- und Restore-Logs geben mehr Live-Fortschritt aus:
  Phasenmeldungen, rsync-Datei-/Fortschrittsausgabe, Export- und
  Retention-Schritte.
- Abschlussmeldung und `complete`-Manifest werden erst nach Export-Archiv und
  Aufbewahrungsregel geschrieben.
- Backup-Liste kann Status, Abschlusszeit, Größe und Dateianzahl aus Logdateien
  und Backup-Ordnern ableiten, wenn `manifest.json` fehlt oder veraltet ist.
- Docker-Stop/Start protokolliert Container-Namen und IDs, arbeitet
  containerweise und nutzt Timeouts, wenn verfügbar.
- Backend-Kommando zum Stoppen laufender Backups ergänzt; zuvor durch das Backup
  gestoppte Docker-Container werden danach wieder gestartet.
- Task-Log-Suche auf mehrere LoxBerry-Logpfade erweitert.
- Sicherheitsprüfungen für Backup-IDs zentralisiert und auf Export, Import,
  Move, Explorer, Delete und Restore angewendet.
- Importierte Tar-Archive werden enger geprüft: nur ein sicherer
  Top-Level-Backupordner, keine absoluten Pfade und keine `..`-Pfade.
- Tar-Aufrufe für Export/Import gehärtet.
- Pre-/Post-Backup-Hooks werden nur ausgeführt, wenn sie Root gehören,
  ausführbar sind und nicht von Gruppe/anderen beschreibbar sind.

### Paketierung

- Plugin-ZIP-Build per `package.ps1` ergänzt.
- Plugin-ZIP-Build per `package.sh` für Linux/GitHub Actions ergänzt.
- GitHub Actions Workflow für automatischen ZIP-Build und Release-Asset-Upload
  ergänzt.
- `release.cfg` und `prerelease.cfg` für LoxBerry-Updates ergänzt.
- Installierbares ZIP zunächst nur über den GitHub-Pre-Release-Kanal vorgesehen.
- `.gitattributes` für passende Zeilenenden ergänzt.
- `.gitignore` für lokale Test- und Build-Artefakte ergänzt.

## [0.1.0] - Entwicklungsversion

### Hinweis

- Noch nicht produktiv freigegeben.
- Installation, Konfiguration und echte Backups wurden auf Testsystemen geprüft.
- Ein produktiver Ende-zu-Ende-Restore steht noch aus.
- Nur für Tests auf nicht-kritischen Systemen verwenden.

[Unreleased]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/compare/main...develop
