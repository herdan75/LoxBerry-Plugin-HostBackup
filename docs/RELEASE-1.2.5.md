# LoxBerry Host Backup 1.2.5

**Stabile Freigabe vorbereitet am 14.11.2026.** Programm- und Paketversion:
`1.2.5`, Release-Tag: `v1.2.5`, Plugin-ZIP: `LoxBerryHostBackup_1.2.5.zip`.
Die veröffentlichte Vorabversion **1.2.5-beta** vom 31.10.2026 wird ohne neue
Runtime-Änderungen als reguläres Release übernommen.

**Veröffentlichungsstatus:** Diese Vorbereitung bestätigt noch kein öffentliches
stabiles Paket und keine aktivierten Kanäle. Zuerst muss die Tag-Pipeline
erfolgreich abschliessen; danach wird das öffentliche ZIP ohne Anmeldung geladen
und mit dem geprüften Artefakt abgeglichen. Erst dann werden `main/release.cfg`
und `develop/prerelease.cfg` auf dasselbe stabile Paket 1.2.5 umgestellt und
beide Feeds live kontrolliert. Bis dahin bleiben die Feeds auf 1.2.4 und 1.2.5-beta.
Die endgültigen Nachweise stehen beim
[GitHub-Release 1.2.5](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.5).

## Übernommene Korrekturen

- **Container-Mounts:** Interne systemd-nspawn-Mount-Roots mit terminalem
  `//deleted` sowie cgroup-/cgroup2-Kennungen mit führenden Elternsegmenten werden
  als interne Identitäten behandelt. Echte Quellpfade und Mount-Ziele bleiben
  streng geprüft; verschwundene, ersetzte oder überdeckte ausgewählte Quellen
  werden weiterhin als Fehler erkannt.
- **Unicode-Mount-Namen:** Unicode-Leerzeichen und -Zeilentrenner werden nicht
  mehr als zusätzliche Felder oder Zeilen der Mount-Tabelle interpretiert.
  Auswahl, Ausschlüsse und Identitätsvergleich verwenden die unveränderten Namen.
- **Docker-Vorprüfung:** Fehlender Client, unerreichbare Engine und eine
  erreichbare Engine ohne laufende Container werden unterschieden. Optionale
  Abfragen sind zeitlich begrenzt und blockieren ohne erforderliche Docker-Stopps
  die Sicherung nicht. Unbekannte Ergebnisse werden nicht als bekannte Anzahl
  null ausgegeben.
- **Docker-Inventarisierung:** Auch die zusätzliche Inventarabfrage während des
  Backups hat ein Zeitlimit. `docker.json` wird vollständig und atomar geschrieben;
  fehlende optionale Informationen dürfen den Worker nicht abbrechen. Echte
  Schreibfehler und nicht ausführbare erforderliche Stopps bleiben Fehler.

Alle bisherigen NAS-, Dienstelisten-, Wiederanlauf-, Watchdog- und
Oberflächenkorrekturen bleiben enthalten. Keine neuen Sicherungsmodi, keine
Umwandlung vorhandener Backups und keine automatische Änderung gespeicherter
Ziele, Quellen, Ausschlüsse oder Stop-Auswahlen.

## Installation und Update

Nach Kanalaktivierung in der LoxBerry-Pluginverwaltung nach Updates suchen.
**Vorabversionen müssen für das stabile Release nicht zugelassen sein.** Beide
Kanäle bieten dann dasselbe Paket an. Alternativ das öffentliche
[LoxBerryHostBackup_1.2.5.zip](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.5/LoxBerryHostBackup_1.2.5.zip)
direkt installieren, **nicht entpacken**. Der neue Download ist erst nach
öffentlicher Paketfreigabe erreichbar und benötigt dann kein GitHub-Konto.

Aktive Vorgänge beenden lassen, Einstellungen exportieren und bewährte Backups
aufbewahren. Direkt über die bestehende Installation aktualisieren,
**nicht vorher deinstallieren**. Einstellungen und Wiederanlauf-Nachweise bleiben
erhalten. Danach Einstellungen kontrollieren, **Nächstes Backup prüfen** ausführen
und ein manuelles Backup samt Dienst-Wiederanlauf vollständig prüfen.

Die veröffentlichte **1.2.5-beta** und manuelle 1.2.5-Testpakete haben bereits
die interne Version **1.2.5**. Der Wechsel zum stabilen Tag erzeugt daher keinen
numerischen Versionssprung. Die veröffentlichte Beta und der geprüfte Teststand
`da034bd` verwenden dieselbe Programmlogik; ein erneutes Funktionsupdate ist für
diese Stände nicht nötig. Freigabedokumentation, Kanalmetadaten und zugehörige
Tests werden nachgezogen, weshalb das gesamte ZIP nicht bytegleich sein muss.
Bei einem älteren oder unbekannten 1.2.5-Teststand nach Freigabe das stabile ZIP
manuell darüber installieren.

## Unveränderte Betriebs- und Restore-Grenzen

- Ein LoxBerry in einem Container sichert nur dort sichtbare, ausgewählte Quellen.
  Docker auf dem äusseren Host wird nicht automatisch erkannt, gesteuert oder
  mitgesichert. Keine zusätzliche Socket-Freigabe und kein automatischer Zugriff
  auf eine andere Engine.
- Unterstützte LoxPanel-Sperrschnittstellen werden koordiniert; die automatische
  Variante wurde mit LoxPanel 0.9.9 geprüft. Massgeblich ist das vorhandene
  Sperrprotokoll, nicht allein die Versionsnummer. Ältere manuelle Varianten
  (0.3.0 bis 0.7.0) und AudioServer4Home vor der Vorprüfung in der eigenen Oberfläche
  stoppen und nach dem Backup dort wieder einschalten. Keine manuellen Container-
  Updates oder Starts während der Kopie.
- Flüchtige LoxBerry-Diagnoseprotokolle bleiben standardmässig ausgelassen.
  Eine ausdrücklich aktivierte Mitsicherung bleibt erhalten und kann bei
  Änderungen während der Sicherung Hinweise oder Abbrüche verursachen.
- Portable System-Restores erfolgen offline. Repository-Stände benötigen das
  vollständige gemeinsame Repository, die extern gesicherte Wiederherstellungsdatei
  mit Schlüssel und vollständigen zusätzlichen Linux-Zwischenspeicher plus Reserve.
  Ein Konfigurationsexport ersetzt den Schlüssel nicht.
- Kein bootfähiges Datenträgerabbild und keine Garantie für Hardware- oder
  Architekturwechsel. Weiterlaufende Anwendungen und Datenbanken können trotz
  erfolgreicher Kopie inkonsistent sein; kontrollierte Stopps beziehungsweise
  anwendungsspezifische Sicherungen und echte Restore-Tests bleiben notwendig.

## Bereits vorhandene Nachweise für den Vorabstand

Freigabebasis ist `bab2563deb9a35532566c4c6883034b635609c43` auf `develop`;
der veröffentlichte Beta-Tag zeigt auf
`74db5df8526317e748c3f5140d22c3c7e1a34a95`. Beide enthalten dieselbe Programmlogik.

- [Beta-Tag-Pipeline 41195340829](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/41195340829):
  Build und Veröffentlichung erfolgreich.
- [Beta-Kanalprüfung 41196464065](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/41196464065):
  erfolgreich; Release-Job dieses Branch-Laufs erwartungsgemäss übersprungen.
- Diese Vorabprüfungen umfassten 874 Haupttests mit zehn zunächst ausgelassenen
  opt-in Integrations-/Paketprüfungen, danach eigene verpflichtende Prüfschritte;
  zusätzlich 144 Linux-/CIFS-Testdurchläufe, 15 unprivilegierte Downloadtests,
  67 Browserfälle und acht Paketprüfungen sowie Syntax, ShellCheck, sudoers und PHP.
- Das öffentliche **Beta-ZIP** war bytegleich mit seinem CI-Artefakt und wurde
  gegen 67 versionierte Paketdateien und zwölf ausführbare Dateimodi geprüft.
  Dies ist kein Hash- oder Paketnachweis für das neue stabile ZIP.

Die positive Anwender-Rückmeldung und die laut Maintainer ausgebliebenen weiteren
Community-Fehlermeldungen unterstützen die Übernahme, ersetzen aber weder die
erneute Prüfung des stabilen Pakets noch einen vollständigen System-Restore-Test.

## Noch erforderliche Freigabenachweise

Der erste Versuch [43601804511](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/43601804511)
bestand Hauptsuite, Downloads und Linux-/CIFS-Integration, scheiterte aber vor
den Browsertests an der neuen `ubuntu-latest`-Plattform Ubuntu 26.04, die das
festgelegte Playwright 1.58.2 nicht unterstützt. Es wurde kein Release-Paket
veröffentlicht. Deshalb ist der Buildrunner jetzt auf Ubuntu 24.04 festgelegt;
Programmlogik und Testabhängigkeiten bleiben unverändert. Erst der vollständige
erneute Lauf gilt als Freigabenachweis.

1. Erfolgreiche Tag-Pipeline für `v1.2.5` einschliesslich aller verpflichtenden
   Linux-/CIFS-, Browser-, Sicherheits- und Paketprüfungen.
2. Öffentliches stabiles Release ohne Prerelease-Kennzeichnung; ZIP ohne Anmeldung
   laden und SHA-256, Dateiinhalte, interne Version und Dateimodi gegen das
   geprüfte Tag-Artefakt abgleichen. Beta-Tag und bisherige ZIPs nicht ersetzen.
3. Erst danach beide Kanaldateien aktivieren, regulären und Vorabfeed über die
   unveränderten Adressen aus `plugin.cfg` live abfragen und die finalen Branch-
   Prüfungen kontrollieren. Paketprüfung und Kanalaktivierung bleiben getrennt.
4. Öffentliche Wiki-/Pluginliste separat nachziehen; ein Git-Push allein ändert sie
   nicht. Endgültige Commit-, CI-, Download- und Kanalnachweise beim GitHub-Release
   ergänzen, ohne den geprüften Tag oder dessen Paket nachträglich umzuschreiben.

Weitere Details: [Prüfumfang und Grenzen](DEVELOP-1.2.5-VALIDATION.md),
[Beta-Release-Notes](RELEASE-1.2.5-beta.md), [Changelog](../CHANGELOG.md),
[Restore-Testplan](DR-TESTPLAN.md).
