# LoxBerry Host Backup 1.0.0

Vorbereitet am 19.09.2026 auf `main`. **Noch nicht veröffentlicht.**
Plugin- und Paketversion: `1.0.0`, ohne Beta-Zusatz.

## Umfang und Herkunft

Die erste Hauptversion übernimmt den vollständigen develop-Stand
`4da7cf6fc47bd6ac9f0dd27c9f7f9a2b41b59e37` einschliesslich aller Korrekturen
des aktualisierten Vorabpakets. Alle 23 Commits seit dem bisherigen main-Stand
0.5.8 sind enthalten. Gegenüber diesem develop-Stand werden keine Backup-,
Restore-, Aufbewahrungs- oder Benachrichtigungsabläufe verändert.

Die Versionsnummer kennzeichnet die erste Hauptversion, ersetzt aber weder
Hardware-Abnahme noch einen nachgewiesenen vollständigen Restore.

## Funktionen und Verbesserungen gegenüber main 0.5.8

- Dateibasiertes Systembackup für LoxBerry, Docker, DietPi und native Dienste;
  Vollbackup und inkrementelle Hardlink-Snapshots mit geprüfter Referenz.
- Vier Metadaten-Profile: **Native Strict** als Standard für geeignete lokale
  Linux-Ziele, **Network Compatible** für geeignete CIFS-/NFS-/NAS-Ziele,
  **Fake Super** für zuverlässige user-xattrs und **Portable Archive** als
  Archivcontainer ohne Snapshot-Modus und mit Offline-Restore.
- Network Compatible lässt xattrs und File Capabilities bewusst aus. Dieser
  neutrale Hinweis blockiert weder manuelle noch geplante Backups; echte
  Dateifehler und nicht unterstützte erforderliche Metadaten bleiben Fehler.
- Sicherere Backup-Zielidentität, Platz-/Inodeprüfungen, kontrollierter Import,
  Export und Download, Restore-Vorschau und explizite Volume-Zuordnungen.
- Root-eigene Helferstände, eingeschränkter Web-Dispatcher, CSRF-Schutz und
  dauerhafte lokale Journale für den Wiederanlauf zuvor gestoppter Dienste.
- Konfigurationserhalt bei Updates und neustartfeste Root-Laufzeitverzeichnisse;
  reparierter unprivilegierter Dateiaustausch, Cron-Symlink-Unterstützung,
  Launcher-Prüfung und zeitlich begrenzte Zeitplaneinrichtung.
- Automatischer Dienst-Wiederanlauf setzt bei belegter Vorgangssperre still aus
  und versucht es später erneut. Manuelle Sperrkonflikte und echte Fehler
  bleiben sichtbar. Die Aufbewahrung erhält eine eigene Live-Status-Phase.
- Kompakte Übersicht mit aufklappbaren Details, lesbare Logs, Aufgabenhistorie,
  sichtbarer Speicherhinweis bei Änderungen, geschützte Aufbewahrung,
  Inhaltsprüfungen, Diagnosepaket und dokumentierbare externe Restoretests.

## Paket und Update vorbereiten

Das CI-Testpaket beziehungsweise der lokale Build heisst
`LoxBerryHostBackup_1.0.0.zip`. Ein Branch-Push erstellt nur ein Workflow-Artefakt.
Es gibt noch keinen veröffentlichten Download unter einem `v1.0.0`-Tag.

- `release.cfg` bleibt auf dem öffentlichen Stable-Paket 0.5.8.
- `prerelease.cfg` und der vorhandene Vorabkanal 0.7.1-beta bleiben unverändert.
- Die LoxBerry-Pluginseite und öffentliche GitHub-Releases werden nicht geändert.
- Ein 1.0.0-Testpaket nur bewusst manuell installieren; nicht vorher deinstallieren.

Vor einer Testinstallation laufende Vorgänge beenden lassen und Einstellungen
exportieren. Nachher Ziel, Ausschlüsse, Profil, Dienste und Zeitplan kontrollieren.
**Geänderte Einstellungen immer zuerst speichern.** Das gilt auch für
Optionsfelder, Dienste und Container. Automatische Backups verwenden nur
den gespeicherten Stand.

### Wichtig bei inkrementellen Backups

Backups aus 0.5.8 oder älter haben keine Metadaten-Profilinformation und sind
deshalb keine Hardlink-Referenz für den neuen Stand. Der erste inkrementelle
Lauf erstellt eine neue vollständige Basiskopie: genügend Platz und Zeit einplanen.
Nach einer erfolgreichen passenden Basiskopie können folgende Läufe wieder
inkrementell arbeiten. Auch ein Profilwechsel kann eine neue Basiskopie erfordern.

Beim Wechsel von 0.6.x/0.7.x auf 1.0.0 erzwingt die Versionsnummer allein keine
neue Basiskopie; entscheidend bleibt eine geeignete validierte Referenz mit
demselben Profil. Alte Backups werden nicht pauschal vorab zur Platzbeschaffung gelöscht.

## Bekannte offene Punkte

- **Speicherbelegung berechnen** zeigt erst am Ende ein Ergebnis. Viele Dateien
  oder langsame Ziele benötigen Zeit; ein Browserabbruch beendet den Backendlauf
  nicht zwingend. Zwischenfortschritt und die konkrete Laufdauer auf dem
  betroffenen Gerät sind nicht abschliessend geklärt.
- **Laufzeitdateien prüfen** kann bei belegter Sperre noch eine generische
  HTTP-500-Meldung zeigen. Prüfungen nacheinander ausführen; nicht wiederholt starten.
- AP-14 zur Mail-/Benachrichtigungssemantik bleibt ausdrücklich ausgenommen.
- Vollständiger Offline-Restore mit anschliessendem Systemstart, NAS-Matrix und
  reale Neustart-/Zielverlust-Szenarien bleiben gesonderte Hardwareprüfungen.
  Nicht als einziges Backup kritischer Systeme verwenden. Kein Disk-Image,
  keine garantierte Partitionierungs-/Bootloader- oder Architektur-Migration.

## Prüfnachweise

Der übernommene Programmstand bestand am 13.09.2026
[203 Linux-Tests ohne Skips und 15 Browserprüfungen](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34764755275),
einschliesslich echter Sperren, Metadaten-Roundtrips, Root-/Webbenutzerrechten,
Installations-/Neustartschutz, Syntaxprüfungen und ZIP-Build.

Die [main-Prüfläufe](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/workflows/build-plugin.yml?query=branch%3Amain)
prüfen den tatsächlichen 1.0.0-Commit erneut. Eine historische oder simulierte
Prüfung wird nicht als Hardware-Abnahme für 1.0.0 ausgegeben.

## Spätere Veröffentlichung – nur nach separater Freigabe

1. Offene Hardware-/Restoreabnahme nach [DR-TESTPLAN.md](DR-TESTPLAN.md) klären
   und die tatsächlich bestandenen Prüfungen dokumentieren.
2. Den vorgesehenen main-Commit vollständig unter Linux und im Browser prüfen.
3. Erst dann `v1.0.0` ohne Beta-Zusatz taggen und ein reguläres GitHub-Release
   mit dem geprüften `LoxBerryHostBackup_1.0.0.zip` bereitstellen.
4. Öffentlichen Download, Paketinhalt, Version und SHA-256 prüfen.
5. Erst danach `release.cfg` auf Version 1.0.0 und den vorhandenen Download
   umstellen. Auch das Paket muss dann die freigegebenen Kanalmetadaten enthalten.
6. Erst nach ausdrücklichem Auftrag die LoxBerry-Pluginseite und Forumtexte
   veröffentlichen. Vorbereitete Texte: [Pluginseite](PLUGINSEITE-1.0.0.txt)
   und [Forum-Update](FORUM-UPDATE-1.0.0.md).

Bis dahin keine Tags, Releases, Download-Ersetzungen oder Kanalumschaltung auslösen.
