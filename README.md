# LoxBerry Host Backup

**Status:** Frueher Entwicklungsstand, noch nicht freigegeben.

Dieses Plugin ist noch nicht produktiv validiert. Es wurde lokal syntaktisch und
funktional in Teilen geprueft, aber noch nicht vollstaendig auf einem echten
LoxBerry-/DietPi-System installiert, gesichert und wiederhergestellt. Verwende es
derzeit nicht als einziges Backup fuer produktive Systeme.

## Zweck

LoxBerry Host Backup ist ein hostnahes Backup- und Restore-Plugin fuer
LoxBerry-Systeme.

Es soll nicht nur LoxBerry selbst sichern, sondern auch Programme,
Dienste und Daten, die parallel auf demselben Rechner laufen.

Typische Beispiele:

- LoxBerry-Konfiguration und Plugin-Daten
- Docker-Container, Docker-Volumes und Bind-Mounts
- DietPi-/Debian-Dienste und deren Daten
- systemd-Units, Cronjobs, Skripte und native Programme
- Benutzer- und Anwendungsdaten unter `/opt`, `/home`, `/var/lib` usw.

Das Plugin basiert bewusst nicht auf Raspberry-Pi-spezifischen Tools wie
`raspiBackup`.

Der Kern ist ein `rsync`-basiertes Host-Snapshot-Backup mit Fokus auf
eine moeglichst vollstaendige Wiederherstellung von Diensten, Daten,
Konfigurationen und Systemumgebung.

## Plattform-Kompatibilitaet

Ziel ist eine moeglichst breit kompatible Nutzung auf Linux-basierten
LoxBerry-/DietPi-/Debian-Systemen, z. B. Raspberry Pi, ODROID, VM oder x86.

Voraussetzungen:

- Linux mit Bash
- Perl mit `JSON::PP`
- Perl-CGI-Unterstuetzung fuer die Weboberflaeche
- `rsync`
- `tar`, `find`, `awk`, `sed`, `tail`, `base64`, `stat`
- `cron` fuer automatische Backups
- `sudo` fuer privilegierte Aktionen aus der Weboberflaeche

Docker ist optional. Wenn Docker vorhanden ist, kann das Plugin Container
inventarisieren und optional vor dem Backup stoppen sowie danach wieder starten.

Wichtig: Plattformwechsel, z. B. ODROID zu Raspberry Pi oder ARM zu x86, sind
nicht automatisch garantiert. Daten und portable Dienste lassen sich oft
wiederherstellen, hardware- oder architekturspezifische Pakete, Kernelmodule,
Bootloader und Docker-Images koennen aber manuelle Nacharbeit erfordern.

## Wichtiger Hinweis zur Plattformunabhaengigkeit

Dieses Plugin erstellt:

- KEIN sektorbasiertes Blockdevice-/Disk-Image
- KEIN garantiert hardwareunabhaengiges Bare-Metal-Komplettimage

Das Plugin erstellt stattdessen ein hostnahes dateibasiertes Systembackup
auf Basis von `rsync`.

Je nach Plattform, Hardware und Linux-Basis kann ein Restore einem nahezu
vollstaendigen 1:1-System sehr nahe kommen.

Das Plugin sichert unter anderem:

- LoxBerry-Konfigurationen
- Plugin-Daten
- Docker-Daten und Volumes
- Compose-Konfigurationen
- systemnahe Dateien
- Benutzer- und Anwendungsdaten
- ausgewaehlte Linux-Systembereiche

Dazu gehoeren typischerweise auch:

- `/etc`
- `/opt`
- `/home`
- `/var/lib`
- systemd-Units
- Cronjobs
- Docker-Daten
- native Dienste und deren Daten

Ein Restore funktioniert am zuverlässigsten bei:

- gleicher CPU-Architektur
- ähnlicher Linux-/DietPi-/Debian-Version
- vergleichbarer Hardware
- identischer oder ähnlicher Docker-Umgebung

Beispiele:

- Raspberry Pi → Raspberry Pi
- ODROID → ODROID
- ARM64 → ARM64
- Debian → Debian

## Eingeschraenkte oder manuelle Migrationen

Plattformwechsel wie:

- ODROID → Raspberry Pi
- ARM → x86
- grosse Debian-/DietPi-Versionsspruenge
- Wechsel der Linux-Distribution

koennen manuelle Nacharbeiten erfordern.

Dies betrifft insbesondere:

- Bootloader
- Kernelmodule
- hardwareabhaengige Pakete
- Netzwerkinterfaces
- UUIDs und Mountpoints
- Device Trees
- Docker-Images anderer Architektur

Portable Daten und viele Dienste lassen sich jedoch meist problemlos uebernehmen.

## Empfohlenes Vorgehen fuer Restore/Migration

Empfohlen wird:

1. Zielsystem frisch installieren
2. LoxBerry installieren
3. Plugin installieren
4. Backup importieren
5. Restore vorbereiten und pruefen
6. Restore gezielt durchfuehren

Dadurch lassen sich Probleme durch Hardware-, Kernel- oder Plattformunterschiede deutlich reduzieren.

## Aktueller Validierungsstand

Lokal geprueft:

- Bash-Syntax fuer Backend, Postinstall, Restore-Helper und Uninstall
- Perl/CGI-Syntax mit lokalem `CGI.pm`-Stub
- Backend-Kommando `list` mit isolierten Testverzeichnissen
- Backend-Kommando `preflight-backup` mit isolierten Testverzeichnissen
- Backend-Kommando `config` mit isolierten Testverzeichnissen
- Backend-Kommando `task-status` mit synthetischem Logfile
- Plugin-ZIP-Paketierung
- Installation und Update ueber den LoxBerry Plugin Manager
- Weboberflaeche auf einem LoxBerry-Testsystem
- Speichern der Einstellungen ueber die LoxBerry-sudoers-Regel
- Echtes Backup auf LoxBerry-/DietPi-Hardware inklusive Live-Log
- Stoppen und Wiederanlauf von Docker-Containern im Backup-Ablauf

Noch nicht validiert:

- Echter Restore auf ein frisch installiertes Zielsystem
- Docker-/Datenbank-Konsistenz in allen produktiven Anwendungsszenarien
- Migration zwischen unterschiedlichen CPU-Architekturen

## Installation

1. ZIP-Paket aus dem GitHub-Pre-Release herunterladen oder lokal bauen.
2. In LoxBerry unter **Plugins > Plugin installieren** hochladen.
3. Nach der Installation die Plugin-Oberflaeche oeffnen.
4. Root-Freigabe in den Einstellungen bewusst bestaetigen und Einstellungen speichern.
5. Zuerst nur ein kleines Testbackup auf einem externen oder separaten Pfad ausfuehren.

Pre-Release-Paket:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.1.0-dev/LoxBerryHostBackup_0.1.0.zip
```

Lokales Paket nach dem Build:

```text
LoxBerryHostBackup_0.1.0.zip
```

## Erste Tests auf LoxBerry

Empfohlene Reihenfolge:

1. Plugin installieren.
2. Weboberflaeche oeffnen.
3. Backup-Ziel auf einen externen oder separaten Pfad setzen, z. B. `/mnt/backupdisk/loxberry-hostbackup`.
4. Backup-Check ausfuehren.
5. Kleines manuelles Backup starten.
6. Live-Log beobachten.
7. Backup im Explorer oeffnen.
8. Einzelne Datei herunterladen.
9. Export erstellen und herunterladen.
10. Restore nur auf einem Testsystem pruefen.

## Funktionen

- Vollstaendiges Host-Backup per `rsync`
- Inkrementelle Snapshot-Backups per `rsync --link-dest`
- Restore eines ausgewaehlten Backups
- Backup- und Restore-Preflight-Checks
- Live-Loganzeige fuer laufende Backup-/Restore-Jobs
- Backup-Explorer in der Weboberflaeche
- Download einzelner Dateien aus einem Backup
- Import und Export von Backup-Archiven
- Export und Import der Plugin-Einstellungen als JSON-Datei
- Verschieben kompletter Backup-Saetze
- Docker-Inventarisierung
- Optionales Stoppen/Starten laufender Docker-Container
- Zeitgesteuerte Backups per Cron
- Aufbewahrungsregel fuer die Anzahl zu behaltender Backups
- Pre-/Post-Backup-Hooks
- Manifest pro Backup mit Host-, LoxBerry- und Inventardaten

## Einstellungen

Die Weboberflaeche enthaelt eine Einstellungen-Sektion.

Neben wichtigen Feldern und Aktionen zeigt ein Info-Button eine kurze
Erklaerung. Die Information erscheint beim Ueberfahren oder Fokussieren des
Buttons und verschwindet wieder, sobald der Button verlassen wird.

### Root-Freigabe

Das Plugin benoetigt kontrollierte Root-Rechte, weil ein vollstaendiges
Host-Backup und ein Restore Systemdateien, Berechtigungen, Docker-Daten,
Cronjobs und Dienste betreffen.

In der Weboberflaeche muss diese Freigabe bewusst bestaetigt werden.
Ohne diese Bestaetigung starten Backup- und Restore-Aktionen nicht.

Es werden keine Passwoerter gespeichert.

Die LoxBerry-sudoers-Regel erlaubt dem LoxBerry-Webuser ausschliesslich
den Start des Backend-Skripts dieses Plugins ohne Passwort.

### Backup-Ziel

Leer bedeutet: Das Plugin verwendet das eigene Datenverzeichnis.

Fuer echte Backups sollte ein absoluter Pfad auf einem externen oder
separaten Datentraeger verwendet werden.

Beispiel:

```text
/mnt/backupdisk/loxberry-hostbackup
```

### Backup-Modus

Das Plugin kann Backups in zwei Modi erstellen:

- `Vollbackup`: Jeder Backup-Ordner enthaelt eine vollstaendige Kopie.
- `Inkrementeller Snapshot`: Das Backup nutzt `rsync --link-dest` und Hardlinks
  auf das vorherige vollstaendige Backup. Jeder Snapshot sieht weiterhin wie ein
  vollstaendiges Backup aus und kann direkt fuer Restore gewaehlt werden.

Der inkrementelle Snapshot spart Speicherplatz, wenn sich viele Dateien nicht
geaendert haben. Fuer zuverlaessige Hardlinks, Rechte und Linux-Metadaten wird
ein Linux-Dateisystem wie `ext4`, `xfs` oder `btrfs` als Backup-Ziel empfohlen.
Auf NTFS/FUSE-Zielen kann die Speicherersparnis oder Metadatenunterstuetzung
eingeschraenkt sein.

### Zusaetzliche rsync-Excludes

Ein Eintrag pro Zeile.

Sinnvoll fuer sehr grosse Datenpfade, Netzwerkshares oder Verzeichnisse,
die nicht Teil des Disaster-Recovery-Backups sein sollen.

Beispiel:

```text
/mnt/nas
/media/archive
/var/cache/apt
```

### Docker behandeln

Wenn aktiviert, werden laufende Docker-Container vor dem Backup gestoppt
und danach wieder gestartet.

Das verbessert die Konsistenz von Container-Daten, kann aber Dienste
waehrend des Backups kurz unterbrechen.

### Automatischer Export

Wenn aktiviert, wird nach jedem Backup automatisch ein `.tar.gz`-Export erstellt.

Dieser Export ist praktisch zum Herunterladen oder Archivieren, ist aber ein
komprimiertes Archiv des ausgewaehlten Backup-Stands. Er spart nicht automatisch
denselben Speicherplatz wie ein inkrementeller Snapshot-Ordner mit Hardlinks.

### Einstellungen exportieren und importieren

Die Plugin-Einstellungen koennen als kleine JSON-Datei exportiert und nach einer
Neuinstallation wieder importiert werden.

Enthalten sind zum Beispiel:

- Backup-Verzeichnis
- Backup-Modus
- Ausschluesse
- Docker-Option
- Export-Option
- Zeitplan
- Aufbewahrung
- Pre-/Post-Backup-Hooks
- Root-Freigabe-Bestaetigung

Nicht enthalten sind Backup-Daten oder Passwoerter.

Nach einem Import sollten die Pfade trotzdem kurz geprueft werden, weil sich
USB-Mounts oder Laufwerksnamen nach einer Neuinstallation aendern koennen.

### Zeitplan

Automatische Backups koennen taeglich, woechentlich oder monatlich laufen.

- Taeglich: Nur die Uhrzeit ist relevant.
- Woechentlich: Ein oder mehrere Wochentage und die Uhrzeit sind relevant.
- Monatlich: Ein oder mehrere Monatstage, ein oder mehrere Monate und die Uhrzeit sind relevant.

### Aufbewahrung

Die Anzahl zu behaltender Backups ist auf 1 bis 10 begrenzt.

Sobald das Limit ueberschritten wird, entfernt das Plugin nach einem
erfolgreichen Backup das aelteste Backup.

Der Zeitplan wird installiert als:

```text
/etc/cron.d/loxberryhostbackup
```

### Hooks

Pre- und Post-Backup-Hooks sind optionale ausfuehrbare Skripte mit absolutem Pfad.

Sie muessen Root gehoeren und duerfen nicht durch Gruppe oder andere
Benutzer beschreibbar sein.

Sie koennen genutzt werden, um Datenbanken zu dumpen, Dienste vorzubereiten
oder nach dem Backup aufzuraeumen.

## Backup-Inhalt

Standardquelle ist `/`.

Standardmaessig ausgeschlossen:

- `/proc`
- `/sys`
- `/dev`
- `/run`
- `/tmp`
- `/lost+found`
- `/var/cache`
- das konfigurierte Backup-Ziel selbst

Enthalten sind unter anderem:

- `/etc`
- `/opt`
- `/home`
- `/var/lib`
- gemountete Datenpfade, sofern nicht ausgeschlossen
- Docker-Daten, sofern sie im gesicherten Dateisystem liegen
- systemd-Units
- Cronjobs
- LoxBerry-Konfiguration
- Plugin-Daten
- native Anwendungsdaten

## Restore

Ein Restore schreibt das Backup zurueck nach `/`
und kann das Zielsystem ueberschreiben.

Deshalb ist der Restore absichtlich mit mehreren Schritten abgesichert:

1. In der Backup-Liste die Aktion `Restore` beim gewuenschten Backup waehlen
2. Restore-Check und Restore-Plan im eingeblendeten Restore-Bereich pruefen
3. Restore per Checkbox ausdruecklich bestaetigen
4. Restore starten

Fuer einen vollstaendigen Restore ist ein frisch installiertes Zielsystem
oder eine Rescue-/Offline-Umgebung vorzuziehen.

Ein Online-Restore auf einem laufenden System kann funktionieren,
ist aber riskanter, weil Dienste und Dateien parallel aktiv sein koennen.

## Docker und Datenbanken

Laufende Container und Datenbanken koennen waehrend eines Live-Backups
inkonsistente Dateien erzeugen.

Fuer wichtige Dienste sollten daher entweder:

- Docker-Container vor dem Backup gestoppt werden
- Pre-/Post-Hooks fuer Datenbank-Dumps verwendet werden
- oder applikationsspezifische Backup-Mechanismen genutzt werden

## Kommandozeile

Nach der Installation liegt das Backend typischerweise hier:

```sh
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh
```

## Dateien und Verzeichnisse

Typische LoxBerry-Zielpfade:

```text
/opt/loxberry/webfrontend/htmlauth/plugins/loxberryhostbackup/
/opt/loxberry/bin/plugins/loxberryhostbackup/
/opt/loxberry/config/plugins/loxberryhostbackup/
/opt/loxberry/data/plugins/loxberryhostbackup/
/opt/loxberry/log/plugins/loxberryhostbackup/
```

Systemdateien:

```text
/opt/loxberry/system/sudoers/LoxBerryHostBackup
/etc/cron.d/loxberryhostbackup
```

## Bekannte Grenzen

- Noch nicht produktiv freigegeben
- Noch kein echter Ende-zu-Ende-Restore auf LoxBerry/DietPi validiert
- Kein Ersatz fuer applikationsspezifische Datenbank-Backups
- Plattformmigration kann manuelle Nacharbeit erfordern
- Bootloader-, Kernel- und Partitionslayout-Themen werden nicht geloest
- Sehr grosse Backups und Exporte muessen auf Speicherplatz und Laufzeit getestet werden
- Inkrementelle Snapshots setzen fuer optimale Speicherersparnis ein Dateisystem
  mit zuverlaessiger Hardlink-Unterstuetzung voraus, z. B. `ext4`
- Kein sektorbasiertes Raw-Disk-/Blockdevice-Image wie z. B. `dd` oder Clonezilla
- Bootloader-, Partitions- und Dateisystembesonderheiten koennen manuelle Nacharbeit erfordern

## Entwicklung

Repository:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup
```

Branches:

- `main`: stabilerer Stand
- `develop`: laufende Weiterentwicklung

Update-Dateien:

- `release.cfg`: Stable-Kanal, derzeit ohne freigegebenes ZIP
- `prerelease.cfg`: Pre-Release-Kanal mit ZIP-Download aus dem GitHub-Pre-Release

Das installierbare ZIP soll bis zur Freigabe nur ueber den Pre-Release-Kanal
bereitgestellt werden.

GitHub Actions erzeugt das Plugin-ZIP automatisch und haengt es
bei GitHub-Releases als Asset an.

Paket lokal bauen:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1
```

Alternativ unter Linux/GitHub Actions:

```sh
./package.sh
```
