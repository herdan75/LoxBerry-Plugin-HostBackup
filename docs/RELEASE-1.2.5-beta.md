# LoxBerry Host Backup 1.2.5-beta

**Vorabversion veröffentlicht am 31.10.2026.** Interne Programm- und Paketversion:
`1.2.5`, Release-Tag: `v1.2.5-beta`, Plugin-ZIP: `LoxBerryHostBackup_1.2.5.zip`.
Das stabile Release, `main` und der reguläre Updatekanal bleiben **1.2.4**.

**Freigabereihenfolge:** Die Tag-Pipeline und die Prüfung des öffentlichen
Downloads sind erfolgreich abgeschlossen. Die anschliessende Kanalaktivierung
verwendet genau dieses Paket in `develop/prerelease.cfg`. Die Live-Kontrolle des
Feeds und die separate Aktivierungs-CI werden nach dem Push geprüft; deren
abschliessende Nachweise stehen beim
[GitHub-Pre-Release](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.5-beta)
festgehalten.

## Korrekturen

- **Container-Mounts:** Von systemd-nspawn verwendete interne Mount-Roots mit
  terminalem `//deleted` werden nicht mehr als ungültige Benutzerpfade behandelt.
  cgroup-/cgroup2-Kennungen mit führenden Elternsegmenten bleiben ebenfalls als
  interne Identitäten erhalten. Die strenge Prüfung echter Quellpfade und der
  Schutz gegen den Austausch ausgewählter Quellen bleiben aktiv.
- **Sonderzeichen:** Unicode-Leerzeichen und -Zeilentrenner in Mount-Namen
  werden nicht mehr als zusätzliche Felder oder Zeilen der Mount-Tabelle gelesen.
  Auswahl, Ausschlüsse und Vergleich verwenden die unveränderten Namen.
- **Docker:** Fehlender Client, unerreichbare Engine und eine erreichbare Engine
  ohne laufende Container werden unterschieden. Optionale Vorprüfungs- und
  Inventarabfragen sind zeitlich begrenzt und dürfen ohne erforderliche
  Docker-Stopps die Sicherung nicht blockieren. Unbekannte Ergebnisse werden
  nicht als gesicherte Anzahl null ausgegeben. `docker.json` wird vollständig
  und atomar geschrieben; echte Datei-/Kopierfehler und nicht ausführbare
  erforderliche Stopps bleiben Fehler.

Keine neuen Sicherungsmodi und keine Änderung gespeicherter Ziele, Quellen oder
Stop-Auswahlen. Ein LoxBerry in einem Container sichert nur dort sichtbare,
ausgewählte Quellen. Docker auf dem äusseren Host wird nicht automatisch erkannt,
gesteuert oder mitgesichert; es werden keine zusätzlichen Sockets freigegeben.

## Installation und Update

In der LoxBerry-Pluginverwaltung **Vorabversionen
zulassen** und nach Updates suchen. Alternativ das öffentliche
[LoxBerryHostBackup_1.2.5.zip](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.5-beta/LoxBerryHostBackup_1.2.5.zip)
direkt installieren, **nicht entpacken**. Der öffentliche Download benötigt
kein GitHub-Konto.

Aktive Vorgänge beenden lassen, Einstellungen exportieren und bewährte Backups
aufbewahren. Direkt über die bestehende Installation aktualisieren,
**nicht vorher deinstallieren**. Einstellungen und Wiederanlauf-Nachweise bleiben
erhalten. Bei Neuinstallation Ziel, Verfahren, Quellen und Stop-Auswahl einrichten.
Danach Einstellungen kontrollieren, **Nächstes Backup prüfen** ausführen und ein
manuelles Backup einschliesslich Dienst-Wiederanlauf vollständig prüfen.

Wer schon ein manuelles Testpaket mit interner Version **1.2.5** installiert hat,
bekommt keinen numerischen Versionssprung. Die Programmlogik des geprüften
Teststands `da034bd` wird bytegleich übernommen; nur Veröffentlichungsdokumentation,
Tests zur Kanalzuordnung und Kanalmetadaten werden nachgezogen. Das gesamte ZIP
kann sich dadurch unterscheiden. Bei einem älteren oder unbekannten 1.2.5-Teststand
das öffentliche Beta-ZIP manuell darüber installieren.

LoxPanel-/AudioServer-Regeln bleiben unverändert: unterstützte LoxPanel-
Sperrprotokolle werden koordiniert; ältere manuelle Varianten und AudioServer4Home
weiterhin vor der Vorprüfung in der eigenen Oberfläche stoppen und danach dort
wieder einschalten. Keine Container-Updates oder manuellen Starts während der Kopie.

## Vorhandener Entwicklungsnachweis

Geprüfte Programmbasis: `da034bd2f59905c3aabab862e69f994aaf9e2a8d`,
[GitHub-Lauf 41189024061](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/41189024061),
erfolgreich abgeschlossen. Der Release-Job dieses Branch-Laufs war absichtlich
übersprungen; dieser Nachweis ist noch kein Veröffentlichungsnachweis.

- Hauptsuite: **874 Tests**, zehn zunächst ausgelassene opt-in Integrations-/
  Paketprüfungen beziehungsweise Testklassen; anschliessend in eigenen
  verpflichtenden Schritten ausgeführt.
- **144 zusätzliche Integrationstest-Durchläufe** unter Linux/CIFS
  (32 + 18 + 38 + 6 + 32 + 18), inklusive tatsächlicher Sicherung und
  Wiederherstellung von Testdaten.
- **15** unprivilegierte Downloadtests, **67** Browserfälle und **8** Paketprüfungen.
- Syntax, ShellCheck, sudoers und PHP erfolgreich. Das Actions-ZIP wurde zusätzlich
  gegen alle **66** versionierten Paketdateien und **12** ausführbaren Dateimodi
  des Commits abgeglichen. Der Release-Tag wurde zusätzlich separat geprüft.

Die Korrekturen bleiben durch Tests für NAS-Inodes, Metadaten, Quellenauswahl,
Dienst-/Container-Wiederanlauf, Watchdogs, Installation über einen bestehenden
Stand, Oberflächenaktionen und Downloadschutz abgesichert. Details:
[Prüfumfang und Grenzen](DEVELOP-1.2.5-VALIDATION.md).

## Veröffentlichungsnachweis

- Tag `v1.2.5-beta` zeigt auf `74db5df8526317e748c3f5140d22c3c7e1a34a95`.
- [Tag-Pipeline 41195340829](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/41195340829):
  Build und Veröffentlichung erfolgreich, einschliesslich Hauptsuite,
  verpflichtender Linux-/CIFS-, Browser-, Sicherheits- und Paketprüfungen.
- Öffentliches ZIP ohne Anmeldung mit HTTP 200 geladen: **29 558 286 Bytes**.
  SHA-256: `e35147be8c6e9ffebfb2e3e45a7b672de29bdc6fe1873db846694c51bb0985be`.
  Identisch mit dem Tag-CI-Artefakt und dem veröffentlichten GitHub-Asset-Digest.
- CRC, sichere ZIP-Pfade, alle **67** versionierten Paketdateien, **12**
  ausführbare Dateimodi und interne Version 1.2.5 gegen den Tag abgeglichen.
  Acht zusätzliche Pakettests am öffentlich heruntergeladenen ZIP erfolgreich.
- `main`, `release.cfg` und das stabile Paket 1.2.4 werden nicht geändert.
  Das Tag-Paket enthält noch den damaligen Vorabfeed-Stand; für Updates gilt
  die unveränderte Remote-Adresse aus `plugin.cfg`. Der Tag und sein geprüftes
  ZIP werden nach der Kanalaktivierung nicht nachträglich ersetzt.

## Prüfgrenzen

Für den letzten Teststand liegt eine positive Anwender-Rückmeldung vor.
Automatisierte Tests und diese Rückmeldung garantieren weder jedes reale
NAS-/Container-System noch die Konsistenz weiterlaufender Anwendungen oder einen
bootfähigen vollständigen Hardware-Restore. Docker-Fehler werden mit kontrollierten
Client-/Dienst-Doubles geprüft, cgroup-Sonderkennungen anhand dokumentierter
Kernel-Ausgaben; echte Linux-Mount- und CIFS-Tests laufen in isolierten Umgebungen.
Vorhandene bewährte Backups und den externen Repository-Schlüssel weiter aufbewahren.
