# LoxBerry Host Backup 0.7.1-beta

Pre-Release vom 13.09.2026 · interne Plugin-Version 0.7.1 · Stable bleibt 0.5.8.

Dieses Update veröffentlicht die Installationskorrektur und die kompakte
Übersicht aus dem manuell bereitgestellten Teststand `39254c6` unter einer neuen
Version. Gegenüber diesem Testpaket ändern sich Versionsdaten und Dokumentation,
nicht die Backup-/Restorelogik. Es ist weiterhin eine Vorabversion für freiwillige
Tests und kein Ersatz für einen nachgewiesenen vollständigen Restore.

## Installation und Update

[LoxBerryHostBackup_0.7.1.zip herunterladen](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.7.1-beta/LoxBerryHostBackup_0.7.1.zip)

In der LoxBerry-Plugin-Verwaltung den Pre-Release-Kanal aktivieren und nach
Updates suchen. `prerelease.cfg` meldet jetzt die höhere interne Version 0.7.1,
auch gegenüber einer installierten 0.7.0-Testfassung. Alternativ das ZIP manuell
über die Plugin-Verwaltung laden, ohne vorherige Deinstallation. Die alten
Release-Tags und ZIPs werden nicht überschrieben; Stable bleibt bei 0.5.8.

1. Laufende Backup-/Restoreaufgaben beenden lassen und Einstellungen exportieren.
2. Nur eine Installation starten. Bei einer noch hängenden alten Installation
   zuerst deren Zustand klären; ein neues ZIP beendet Altprozesse nicht automatisch.
3. Nach dem Update Ziel, Ausschlüsse, Profil, Aufbewahrung und Zeitplan kontrollieren.
4. **Geänderte Einstellungen zuerst mit „Änderungen speichern“ übernehmen.**
   Das gilt auch für Optionsfelder, Dienste und Container. Geplante Backups
   verwenden die zuletzt gespeicherten Einstellungen.
5. Freien Speicher prüfen und zunächst ein manuelles Testbackup durchführen.

> **Inkrementelle Backups:** Der Wechsel von 0.7.0 auf 0.7.1 erzwingt allein
> wegen der Versionsnummer keine neue Basiskopie. Eine gültige passende Referenz
> bleibt erforderlich. Beim Umstieg von 0.5.8 oder älter wird dagegen zuerst
> nochmals vollständig kopiert, weil diesen Backups die Metadaten-Profilinformation
> fehlt. Erst nach einer erfolgreichen neuen Basiskopie sind wieder Hardlinks
> möglich; genügend zusätzlichen Platz einplanen.

## Installation und Wiederinstallation korrigiert

- Vor dem Update wird die Konfiguration gesichert. Anschliessend werden nur
  die alten Plugin-Bin-Verzeichnisse für LoxBerrys unprivilegierten Dateiaustausch
  vorbereitet; geschützte Helferstände, Root-Status und Backups bleiben erhalten.
- Vor der Aktivierung prüft POSTROOT, dass `hostbackup.sh` das eigentliche
  Backend ist. Ein übriggebliebener Weiterleitungs-Launcher darf den bisherigen
  funktionierenden Programmstand nicht ersetzen. Der Root-Einstieg weist einen
  solchen falschen Stand ebenfalls sofort ab, statt rekursiv zu starten.
- Die abschliessende Zeitplaninstallation ist auf 30 Sekunden plus höchstens
  5 Sekunden zum Beenden begrenzt.
- LoxBerrys vorgesehener Cron-Symlink und die gemeldeten Rechte `root:root 775`
  bleiben unterstützt, ohne gemeinsame Systemrechte oder den Schutz der
  ausführbaren Root-Helfer abzuschwächen.
- Linux-Tests bilden den tatsächlichen unprivilegierten Lösch-/Kopiervorgang,
  Reparatur, erneute Installation, Konfigurationserhalt und Symlink-Schutz nach.

## Kompakte Übersicht und Bedienung

- Letztes erfolgreiches Backup, nächster Termin, aktueller Vorgang und freier
  Zielspeicher bleiben direkt sichtbar: vier/zwei/eine Spalte je nach Fensterbreite.
- **Details und Prüfaktionen** ist anfangs geschlossen und enthält vollständige
  IDs, Zielpfad und die Prüf-/Diagnoseschaltflächen. Der Zustand bleibt beim
  automatischen Nachladen erhalten. Enter und Leertaste funktionieren ebenfalls.
- Aufklappen startet keine Berechnung. Letzter protokollierter Fehler, offene
  Dienst-Wiederanläufe und bereits geladene Ergebnisse bleiben auch zugeklappt sichtbar.
- Weisse Inhaltsflächen, getrennte Beschriftungen/Werte und passende Abstände
  vereinheitlichen Übersicht, Live-Status und Einstellungen.
- Inhaltsabhängige CSS-/JavaScript-Adressen verhindern veraltete Oberflächendateien
  aus dem Browser-Cache auch bei späteren Korrekturen ohne Versionssprung.

## Bekannte offene Punkte

- **Speicherbelegung berechnen** liefert weiterhin erst am Ende ein Ergebnis,
  ohne Fortschrittsanzeige. Viele Dateien oder langsame Ziele können lange
  Berechnungen verursachen. Ein Browserabbruch beendet das Backend nicht zwingend.
  Die konkrete Laufdauer beziehungsweise ein Hängen auf dem gemeldeten Gerät
  wurde noch nicht durch eine Live-Diagnose bestätigt.
- **Laufzeitdateien prüfen** kann bei laufender Speicherberechnung oder anderen
  gesperrten Operationen abgewiesen werden. Der Browser zeigt derzeit die
  generische Meldung „Unerwartete Serverantwort (HTTP 500)“ statt des eigentlichen
  Sperrgrunds. Diese Fehlerkette wurde isoliert reproduziert und ist in diesem
  Release **noch nicht behoben**. Prüfungen vorerst nacheinander ausführen;
  bei unklarem Zustand nicht wiederholt starten.
- AP-14 zur Mail-/Benachrichtigungssemantik bleibt ausgenommen.
- Echte NAS-/Neustarttests und ein vollständiger Offline-Restore mit anschliessendem
  Systemstart bleiben gesonderte Hardwareprüfungen. Kein garantiert bootfähiges
  Disk-Image und keine automatische Partitionierungs-/Bootloader-Wiederherstellung.

## Prüfnachweise

Der zugrunde liegende [Teststand 39254c6](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34759728463)
bestand 191 Linux-Tests ohne Skips und 14 Browser-Prüfblöcke sowie Syntax-, Rechte-
und Paketprüfungen. Der getaggte 0.7.1-Stand durchläuft die Prüfungen vor
Veröffentlichung erneut. Den tatsächlichen abschliessenden Lauf und die
SHA-256-Prüfsumme nennt die
[GitHub-Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.1-beta).
Isolierte Fixtures sind kein Nachweis eines produktiven End-to-End-Restores.

Details: [README](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/README.md),
[Changelog](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/CHANGELOG.md),
[Prüfbericht](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/docs/IMPLEMENTATION-2026-09.md),
[Sicherheitsmodell](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/docs/SECURITY.md),
[Disaster-Recovery-Testplan](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/docs/DR-TESTPLAN.md).
