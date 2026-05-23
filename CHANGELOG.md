# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Dieses Projekt befindet sich noch in einem fruehen Entwicklungsstand. Es gibt
noch keine freigegebene produktive Version.

## [Unreleased]

### Dokumentation

- README vollstaendig auf Deutsch neu strukturiert.
- Zweck, Plattform-Kompatibilitaet, Voraussetzungen und bekannte Grenzen ergaenzt.
- Installations- und erster Testablauf fuer LoxBerry beschrieben.
- Restore-Risiken, Docker-/Datenbank-Hinweise und Branch-Modell dokumentiert.

### LoxBerry-Kompatibilitaet

- Sudoers-Regel in den LoxBerry-Standardordner `sudoers/sudoers` verschoben, damit LoxBerry sie waehrend der Plugin-Installation selbst installiert.
- `postinstall.sh` schreibt nicht mehr direkt nach `/etc/sudoers.d`, da das Postinstall-Skript auf LoxBerry ohne Root-Rechte laufen kann.
- `uninstall.sh` entfernt nur noch den Cron-Eintrag defensiv; die sudoers-Datei wird von LoxBerry verwaltet.
- `postinstall.sh` in den ZIP-Root verschoben, damit LoxBerry das Skript korrekt ausfuehrt.
- Restore-Helper von `sbin/` nach `bin/` verschoben, da LoxBerry `sbin/` beim Test nicht installiert hat.
- Plugin-Icons ergaenzt, damit LoxBerry keine Default-Icon-Warnung ausgeben muss.
- Offizielle LoxBerry-Plugin-Pfadvariablen beruecksichtigt.
- Skriptpfad-basierte Erkennung des tatsaechlichen Pluginordners ergaenzt.
- Default-Konfiguration in das Plugin-Verzeichnis `config/` verschoben.
- `postinstall.sh` nutzt LoxBerry-Installationsargumente fuer Pluginordner und Basisverzeichnis.
- Web-Backend-Aufrufe verwenden `sudo -n`, damit fehlende sudoers-Regeln nicht haengen bleiben.

### Planung und Aufbewahrung

- Woechentlicher Zeitplan kann mehrere Wochentage speichern und als Cron-Liste ausgeben.
- Monatlicher Zeitplan kann mehrere Monatstage sowie einzelne Monate speichern und als Cron-Liste ausgeben.
- Info-Texte zum Zeitplan erklaeren detailliert, welche Felder bei taeglich, woechentlich und monatlich relevant sind.
- Zeitplan-Oberflaeche klarer strukturiert: taeglich zeigt nur Uhrzeit, woechentlich Wochentag und Uhrzeit, monatlich Monatstag, Monate und Uhrzeit.
- Monatsauswahl fuer monatliche Backups ergaenzt.
- Aufbewahrung auf 1 bis 10 Backups begrenzt.
- Zeitgesteuerte Backups per `/etc/cron.d/loxberryhostbackup` ergaenzt.
- Auswahl fuer taegliche, woechentliche und monatliche Backups ergaenzt.
- Uhrzeit, Wochentag und Monatstag konfigurierbar gemacht.
- Retention-Regel ergaenzt: Bei gesetztem Limit werden nach erfolgreichem Backup alte Backups entfernt.
- Cron-Eintrag wird bei Deinstallation entfernt.

### Weboberflaeche

- Startbutton von `Backup vorbereiten` auf `Backup starten` umbenannt.
- Stop-Button im Live-Status ergaenzt, um laufende Backups abbrechen zu koennen.
- Formularaktionen leiten nach erfolgreichem Speichern oder Backup-Start auf eine normale Seite weiter, damit der Browser beim Aktualisieren keine erneute Formularuebermittlung anbietet.
- Info-Buttons mit Hover-/Fokus-Hinweisen fuer Einstellungen und Backup-Aktionen ergaenzt.
- Beschriftungen in den Einstellungen klarer benannt, z. B. Backup-Verzeichnis, Backups behalten, Skript vor/nach dem Backup und Vom Backup ausschliessen.
- Sicherheitsbestaetigung fuer Root-Freigaben ergaenzt, inklusive kurzer Erklaerung in den Einstellungen.
- Backup- und Restore-Start pruefen, ob die Root-Freigabe zuvor bestaetigt wurde.
- Einstellungen-Seite ergaenzt.
- Backup-Ziel, Excludes, Docker-Verhalten, automatische Exporte, Retention und Hooks konfigurierbar gemacht.
- Backup-Start fuehrt zuerst zum Preflight-Check.
- Live-Loganzeige fuer laufende Backup- und Restore-Jobs ergaenzt.
- Backup-Explorer mit Download einzelner Dateien ergaenzt.
- Import, Export, Verschieben und Loeschen von Backups ergaenzt.
- Restore-Workflow mit Backup-Auswahl, Restore-Check, Restore-Plan und expliziter Bestaetigung ergaenzt.

### Backend

- Backend-Kommando zum Stoppen laufender Backups ergaenzt; zuvor durch das Backup gestoppte Docker-Container werden danach wieder gestartet.
- Task-Log-Suche auf mehrere LoxBerry-Logpfade erweitert, damit Live-Status auch dann aktualisiert, wenn LoxBerry Logs direkt unter `log/plugins` statt im Plugin-Unterordner ablegt.
- Backup- und Restore-Logs geben mehr Live-Fortschritt aus: Phasenmeldungen, rsync-Datei-/Fortschrittsausgabe, Export- und Retention-Schritte.
- Sicherheitspruefungen fuer Backup-IDs zentralisiert und auf Export, Import, Move, Explorer, Delete und Restore angewendet.
- Importierte Tar-Archive werden enger geprueft: nur ein sicherer Top-Level-Backupordner, keine absoluten Pfade und keine `..`-Pfade.
- Tar-Aufrufe fuer Export/Import gehaertet.
- Pre-/Post-Backup-Hooks werden nur noch ausgefuehrt, wenn sie Root gehoeren, ausfuehrbar sind und nicht von Gruppe/anderen beschreibbar sind.
- `rsync`-basiertes Host-Backup ergaenzt.
- Restore-Backend ergaenzt.
- Manifest pro Backup ergaenzt.
- Paketliste, systemd-Service-Liste, Mount-Liste und Docker-Inventar ergaenzt.
- Preflight-Checks fuer Backup und Restore ergaenzt.
- Task-Status- und Task-Log-Kommandos ergaenzt.
- Backup-Import und -Export ergaenzt.
- Sichere Pfadpruefungen fuer Backup-Explorer, Datei-Download und Task-Logs ergaenzt.
- Pre-/Post-Backup-Hooks ergaenzt.

### Paketierung

- Plugin-ZIP-Build per `package.ps1` ergaenzt.
- Plugin-ZIP-Build per `package.sh` fuer Linux/GitHub Actions ergaenzt.
- GitHub Actions Workflow fuer automatischen ZIP-Build und Release-Asset-Upload ergaenzt.
- `release.cfg` und `prerelease.cfg` fuer LoxBerry-Updates ergaenzt.
- Installierbares ZIP zunaechst nur ueber den GitHub-Pre-Release-Kanal vorgesehen.
- `.gitattributes` fuer passende Zeilenenden ergaenzt.
- `.gitignore` fuer lokale Test- und Build-Artefakte ergaenzt.

## [0.1.0] - Entwicklungsversion

### Hinweis

- Noch nicht produktiv freigegeben.
- Noch nicht vollstaendig auf echter LoxBerry-/DietPi-Hardware validiert.
- Nur fuer Tests auf nicht-kritischen Systemen verwenden.

[Unreleased]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/compare/main...develop
