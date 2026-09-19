# LoxBerry Host Backup 0.7.1-beta

Historisches Dokument zum veröffentlichten Vorabpaket. Der vorbereitete
Hauptstand auf `main` ist [Version 1.0.0](RELEASE-1.0.0.md), ohne neue Veröffentlichung.

Pre-Release vom 13.09.2026 · interne Plugin-Version 0.7.1 · Stable bleibt 0.5.8.

Die Erstveröffentlichung übernahm die Installationskorrektur und die kompakte
Übersicht aus dem Teststand `39254c6`. Das am selben Tag aktualisierte Paket
ergänzt die Korrekturen aus `416e8ff`: keine Cron-Mail allein wegen einer belegten
Vorgangssperre und eine eigene Live-Status-Phase für die Aufbewahrung.
Version und Download-Adresse bleiben unverändert. Es ist weiterhin eine
Vorabversion für freiwillige Tests und kein Nachweis eines vollständigen Restores.

## Installation und Update

[LoxBerryHostBackup_0.7.1.zip herunterladen](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.7.1-beta/LoxBerryHostBackup_0.7.1.zip)

In der LoxBerry-Plugin-Verwaltung den Pre-Release-Kanal aktivieren und nach
Updates suchen. `prerelease.cfg` meldet jetzt die höhere interne Version 0.7.1,
auch gegenüber einer installierten 0.7.0-Testfassung. Alternativ das ZIP manuell
über die Plugin-Verwaltung laden, ohne vorherige Deinstallation. Dieses
0.7.1-beta-ZIP und sein Tag werden auf den korrigierten Stand aktualisiert;
ältere Releases und Stable 0.5.8 bleiben unverändert.

**Bereits 0.7.1 installiert:** Die gleiche Versionsnummer löst keinen höheren
Versionshinweis aus. Das aktualisierte ZIP erneut herunterladen und über die
Plugin-Verwaltung installieren, ohne vorher zu deinstallieren. Ein bereits lokal
vorhandenes altes ZIP wird nicht automatisch aktualisiert.

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

## Nachbesserung ohne Versionssprung

- Der automatische Wiederanlauf beim Boot und alle fünf Minuten verwendet
  `recover-services --scheduled`. Bei belegter globaler Sperre setzt dieser
  Versuch ohne Ausgabe mit Status 0 aus; der nächste Cron-Termin versucht es
  erneut. Aktive Vorgänge und offene Journale bleiben dabei unberührt.
- Nur erwartbare Sperrkonflikte werden still behandelt. Technische Sperrfehler
  und fehlgeschlagene Dienststarts bleiben sichtbar; manuelle Wiederanläufe
  melden eine belegte Sperre weiterhin als Fehler. AP-14 und die konfigurierten
  Backup-Mailbenachrichtigungen werden nicht verändert.
- Nach der Validierung erscheint „Aufbewahrung prüfen und alte Backups bereinigen“
  (`retention`) statt eines stehengebliebenen `validating`. Die Aufgabe bleibt
  bis zum Abschluss laufend; Aufbewahrungsregeln und Löschschutz bleiben gleich.

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

Der [Korrekturstand 416e8ff](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34764161868)
bestand 203 Linux-Tests ohne Skips und 15 Browser-Prüfblöcke sowie Syntax-, Rechte-
und Paketprüfungen. Darunter sind echte konkurrierende Dateisperren,
Metadaten-Roundtrips und Installationen mit Root-/Webbenutzerrechten.
Der aktualisierte Tag-Stand durchläuft die Prüfungen vor Veröffentlichung erneut.
Den tatsächlichen abschliessenden Lauf und die
SHA-256-Prüfsumme nennt die
[GitHub-Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.1-beta).
Isolierte Fixtures sind kein Nachweis eines produktiven End-to-End-Restores.

Details: [README](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/README.md),
[Changelog](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/CHANGELOG.md),
[Prüfbericht](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/docs/IMPLEMENTATION-2026-09.md),
[Sicherheitsmodell](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/docs/SECURITY.md),
[Disaster-Recovery-Testplan](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.1-beta/docs/DR-TESTPLAN.md).
