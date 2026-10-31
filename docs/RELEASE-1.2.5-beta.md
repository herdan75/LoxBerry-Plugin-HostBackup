# LoxBerry Host Backup 1.2.5-beta

**Vorabfreigabe vorbereitet am 31.10.2026.** Interne Programm- und Paketversion:
`1.2.5`, Release-Tag: `v1.2.5-beta`, Plugin-ZIP: `LoxBerryHostBackup_1.2.5.zip`.
Das stabile Release, `main` und der reguläre Updatekanal bleiben **1.2.4**.

**Freigabereihenfolge:** Zuerst prüft die Tag-Pipeline das Paket. Nach Prüfung
des öffentlichen Downloads wird `develop/prerelease.cfg` auf 1.2.5 umgestellt
und der live geladene Feed kontrolliert. Dieser Vorbereitungsstand behauptet
weder eine bereits abgeschlossene Veröffentlichung noch einen aktiven Kanal.
Die abschliessenden Paket-/Kanalnachweise werden beim
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

Nach der Kanalaktivierung in der LoxBerry-Pluginverwaltung **Vorabversionen
zulassen** und nach Updates suchen. Alternativ das öffentliche
[LoxBerryHostBackup_1.2.5.zip](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.5-beta/LoxBerryHostBackup_1.2.5.zip)
direkt installieren, **nicht entpacken**. Der Link funktioniert erst nach der
öffentlichen Paketfreigabe; danach benötigt der Download kein GitHub-Konto.

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
  des Commits abgeglichen. Der Release-Tag wird erneut separat geprüft.

Die Korrekturen bleiben durch Tests für NAS-Inodes, Metadaten, Quellenauswahl,
Dienst-/Container-Wiederanlauf, Watchdogs, Installation über einen bestehenden
Stand, Oberflächenaktionen und Downloadschutz abgesichert. Details:
[Prüfumfang und Grenzen](DEVELOP-1.2.5-VALIDATION.md).

## Prüfgrenzen

Für den letzten Teststand liegt eine positive Anwender-Rückmeldung vor.
Automatisierte Tests und diese Rückmeldung garantieren weder jedes reale
NAS-/Container-System noch die Konsistenz weiterlaufender Anwendungen oder einen
bootfähigen vollständigen Hardware-Restore. Docker-Fehler werden mit kontrollierten
Client-/Dienst-Doubles geprüft, cgroup-Sonderkennungen anhand dokumentierter
Kernel-Ausgaben; echte Linux-Mount- und CIFS-Tests laufen in isolierten Umgebungen.
Vorhandene bewährte Backups und den externen Repository-Schlüssel weiter aufbewahren.
