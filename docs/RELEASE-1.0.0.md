# LoxBerry Host Backup 1.0.0

Reguläres Release vom 19.09.2026 auf `main`, Tag **v1.0.0**.
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

## Download und Update

[**LoxBerryHostBackup_1.0.0.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.0.0/LoxBerryHostBackup_1.0.0.zip)

- Reguläres GitHub-Release, **kein Pre-Release**.
- `main/release.cfg` meldet Version 1.0.0. Auch `develop/prerelease.cfg` verweist
  auf dasselbe stabile Paket, solange keine neuere Vorabversion existiert.
- Die bestehenden Kanaladressen in `plugin.cfg` bleiben unverändert.
- In LoxBerry nach Updates suchen oder das ZIP manuell installieren.
  **Nicht vorher deinstallieren.** Automatische Installation hängt von der
  persönlichen Einstellung in der Plugin-Verwaltung ab.
- Bereits manuell installierte 1.0.0-Testpakete erhalten keinen höheren
  Versionshinweis. Das Release-ZIP bei Bedarf erneut installieren, um auch
  die finalen Kanalmetadaten und Dokumente zu übernehmen.
- Ältere Releases und Downloads bleiben unverändert. Die Plugin-/Wiki-Seite
  und Forumbeiträge werden separat gepflegt.

Vor einem Update laufende Vorgänge beenden lassen und Einstellungen
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

Der [vorbereitete 1.0.0-Stand c981111](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/35440782063)
bestand 205 Linux-Tests ohne Skips, 15 Browser-Prüfblöcke, Syntax- und
Rechteprüfungen sowie den ZIP-Bau. Darunter sind echte Dateisperren,
Metadaten-Roundtrips und Installationen mit Root-/Webbenutzerrechten.

Der endgültige Release-Commit wird vor dem Tag und nochmals über den Tag unter
Linux geprüft. Die [Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.0.0)
nennt den dazugehörigen Lauf und die Prüfsumme des veröffentlichten Pakets.

Die Freigabe erfolgt mit den oben dokumentierten Grenzen. Ein vollständiger
Offline-Restore mit Systemstart und die NAS-/Hardwarematrix sind weiterhin
nicht nachgewiesen. Vor produktivem Disaster-Recovery-Einsatz den
[DR-Testplan](DR-TESTPLAN.md) auf geeigneter eigener Testhardware abarbeiten.

## Veröffentlichungsverfahren

1. Release-Commit mit finalen Dokumenten und Kanalmetadaten unter Linux prüfen,
   während die live abgefragten Branches noch den vorherigen Kanalstand liefern.
2. Unveränderten geprüften Commit als `v1.0.0` taggen. Die Tag-Pipeline veröffentlicht
   das ZIP erst nach erfolgreichen Linux-, Browser- und Paketprüfungen.
3. Öffentlichen Download, ZIP-Inhalt, Laufzeitversion und SHA-256 kontrollieren.
4. Erst danach `main` und `develop` auf den Release-Commit vorziehen, damit
   beide Update-Kanäle auf das tatsächlich verfügbare Paket zeigen.
5. Raw-Kanaladressen und Updatewerte nochmals von aussen prüfen. Die
   LoxBerry-Pluginseite und Forumbeiträge separat pflegen.

Vorbereitete Veröffentlichungstexte: [Pluginseite](PLUGINSEITE-1.0.0.txt)
und [Forum-Update](FORUM-UPDATE-1.0.0.md).
