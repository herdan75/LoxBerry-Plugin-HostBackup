# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Dieses Projekt ist in einer ersten vorsichtig freigegebenen Version verfügbar.
Restore-Funktionen sollten weiterhin zuerst in einer Test- oder Rescue-Umgebung
validiert werden.

## [Unreleased]

## [0.5.0-beta] - 2026-06-20

### Import und Export

- Export vorhandener Backups läuft nun als Hintergrundjob mit Live-Status,
  damit grosse `.tar.gz`-Archive keinen Browser- oder Webserver-Timeout mehr
  auslösen.
- Export-Archive werden zuerst als temporäre Datei erstellt, per `tar -tzf`
  geprüft und danach atomar auf den finalen Archivnamen verschoben.
- Die Backup-Liste zeigt Exportstatus, Archivgrösse und Archivpfad an.
- Import externer Backup-Archive läuft nun ebenfalls als Hintergrundjob mit
  Live-Status. Hochgeladene Importdateien werden nach erfolgreichem Import oder
  bei Fehlern automatisch bereinigt.

### Weboberflaeche

- Datei-Explorer und Restore-Auswahl können direkt wieder geschlossen werden.
- Eine kompakte Kurzanleitung erklärt die wichtigsten Schritte für Backup-Ziel,
  Ausschlüsse, Backup-Modus, Stop-Ziele, Erstkontrolle und Restore-Konzept.

## [0.4.3] - 2026-06-02

### Benachrichtigung

- Mailbenachrichtigungen ueber die zentrale LoxBerry-Benachrichtigung ergaenzt.
- Optionale Empfaengeradresse im Plugin: Wenn leer, verwendet LoxBerry die globale Standardadresse.
- Erfolgreiche Backups senden nun nur noch eine Mail und erzeugen keinen zusaetzlichen Eintrag in der LoxBerry-Notification-Uebersicht.
- Fehler, Abbruch und Restore-Ereignisse bleiben als LoxBerry-Notifications sichtbar.

## [0.4.2] - 2026-05-31

### Weboberflaeche

- Backup-Zielauswahl ueberarbeitet und optisch an die restliche LoxBerry-Oberflaeche angepasst.
- Aufklappbare Bereiche für Backup-Ziele, Zeitplan, Stop-Ziele und Backup-Verwaltung weiter vereinheitlicht.
- Manuelle Korrekturen aus `develop` uebernommen und README sowie Update-Metadaten auf Version 0.4.2 nachgezogen.

## [0.4.1] - 2026-05-25

### Weboberfläche

- Der Datei-Explorer erklärt nun kurz, warum inkrementelle Snapshots trotz
  vollständiger Ansicht nur wenig zusätzlichen Speicher belegen können.

## [0.4.0] - 2026-05-25

### Backup-Konsistenz

- Neue Auswahl für Stop-Ziele ergänzt: Docker-Container und systemd-Dienste
  werden erkannt, in Gruppen angezeigt und können einzeln für das Backup
  ausgewählt werden.
- Das Plugin stoppt nur ausgewählte Ziele, die vor dem Backup wirklich liefen,
  und startet genau diese Ziele nach erfolgreichem Backup, Fehler oder manuellem
  Abbruch wieder.
- Gestoppte Docker-Container und systemd-Dienste werden im Backup-Manifest und
  im Log protokolliert, damit nachvollziehbar bleibt, welche Ziele wieder
  gestartet werden mussten.
- Bei manuellem Abbruch wird das Backup als `stopped` markiert. Die
  Weboberfläche fragt anschliessend, ob das unvollständige Backup direkt
  gelöscht werden soll.
- LoxBerry-nahe Dienste werden separat gruppiert; kritische Systemdienste wie
  Netzwerk, Webserver, SSH, Docker-Daemon und systemd-Basisdienste werden nicht
  zur Auswahl angeboten.

### Weboberfläche

- Die Dienst-/Container-Auswahl wird per AJAX nachgeladen, damit die
  Einstellungsseite weiterhin schnell sichtbar bleibt.
- Die Dienst-/Container-Auswahl ist kompakter, pro Rubrik einklappbar und
  blendet kritische LoxBerry-, Web-, SSH- und Backup-Dienste aus.
- Die erweiterten Zeitplanfelder `Tage im Monat`, `Monate` und die Stop-Ziele
  sind standardmässig eingeklappt, damit die Einstellungsseite übersichtlich
  bleibt.
- LoxBerry-Plugins ohne eigenen sicher steuerbaren Dienst werden nicht als
  Stop-Ziel angeboten, um unzuverlässige Stop-/Start-Aktionen zu vermeiden.
- Neuer Button `Empfohlene Auswahl setzen` markiert laufende Docker-Container
  und typische datenintensive Dienste wie Datenbanken, MQTT/Zigbee, Node-RED,
  Stats4Lox, Grafana oder InfluxDB.
- Löschdialoge und Ladehinweise weisen jetzt darauf hin, dass das Entfernen
  grosser Backups auf langsamen Datenträgern mehrere Minuten dauern kann.
- Das Nachladen von Dateisystem-Prüfung, Backup-Liste und Stop-Zielen wurde
  robuster gemacht und nutzt wieder kompatible JavaScript-Techniken ohne
  `fetch`/`NodeList.forEach` im initialen Ladepfad.

## [0.3.2] - 2026-05-25

### Weboberfläche

- Layout der Einstellungsbereiche weiter vereinheitlicht und an die Backup-
  Verwaltung angeglichen.
- Konfigurationsbuttons optisch an die bestehenden Backup-Import-Controls
  angepasst.
- Restore-Bereich in denselben Innenrahmen wie die Backup-Verwaltung gesetzt.
- Texte und Info-Hinweise auf Schweizer Schreibweise ohne scharfes S
  vereinheitlicht.

## [0.3.1] - 2026-05-25

### Weboberfläche

- Weboberfläche auf die LoxBerry-Standard-Einbettung mit
  `LoxBerry::Web::lbheader` und `lbfooter` umgestellt. Dadurch bleiben die
  LoxBerry-Navigation, das Haus-Symbol und die Kopfzeile sichtbar.
- Separaten Button `Zurück zu LoxBerry` entfernt, da die Navigation nun wieder
  über die LoxBerry-Kopfzeile erfolgt.
- Konfigurationsaktionen in eine eigene Rubrik `Konfiguration verwalten`
  verschoben.
- Bereichsflächen und Backup-Tabelle optisch näher an neutrale LoxBerry-
  Grautöne angeglichen.
- Backup-Liste und Dateisystem-Prüfung werden nach dem Seitenaufbau per
  AJAX nachgeladen, damit die Weboberfläche schneller sichtbar ist.
- Info-Buttons, Restore-Bereich, Konfigurationsaktionen und die
  Dateisystem-Hinweise konsistent nachgezogen und alte zu breite
  Eingabe-/Button-Regeln entschärft.

## [0.3.0] - 2026-05-24

### Geändert

- Version auf die erste vorsichtig freigegebene Fassung angehoben.
- Stable- und Pre-Release-Updatekanal zeigen auf das freigegebene Paket.
- Plugin-Metadaten bereinigt und doppelte Auto-Update-Einträge entfernt.
- Lokale Build- und Testaltlasten aus dem Arbeitsstand entfernt.
- Live-Log für schnelle inkrementelle Backups entschärft: rsync sendet weniger
  Dateinamen und die Weboberfläche liest pro Statusabfrage nur einen begrenzten
  Log-Ausschnitt.
- Aufbewahrung bei inkrementellen Snapshots in Oberfläche und README genauer
  erklärt.

## [0.2.0] - 2026-05-24

### Hinweis

- Erste vorsichtige Beta-/Testversion.
- Installation, Konfiguration, Vollbackup und inkrementelle Snapshot-Backups
  wurden auf einem LoxBerry-/DietPi-Testsystem geprüft.
- Inkrementelle Snapshots wurden auf `ext4` mit Hardlinks und deutlicher
  Speicherersparnis erfolgreich geprüft.
- Ein produktiver Ende-zu-Ende-Restore auf ein frisch installiertes Zielsystem
  steht noch aus.

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
- Backup-Liste zeigt Status, Host, Grösse, Dateianzahl, Abschlusszeit,
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
- Backup-Liste kann Status, Abschlusszeit, Grösse und Dateianzahl aus Logdateien
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

- Früher interner Entwicklungsstand vor der Beta-/Testversion 0.2.0.
- Nur für Tests auf nicht-kritischen Systemen vorgesehen.

[Unreleased]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/compare/v0.5.0-beta...develop
[0.5.0-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.0-beta
[0.4.3]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.3
[0.4.2]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.2
[0.4.1]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.1
[0.4.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.0
[0.3.2]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.3.2
[0.3.1]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.3.1
[0.3.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.3.0
[0.2.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.2.0-beta
