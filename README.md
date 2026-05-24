# LoxBerry Host Backup

**Status:** Version 0.3.0, erste vorsichtig freigegebene Version.

Dieses Plugin wurde bereits auf einem LoxBerry-/DietPi-Testsystem installiert,
konfiguriert und für echte Vollbackups sowie inkrementelle Snapshot-Backups
genutzt. Ein vollständiger Ende-zu-Ende-Restore auf ein frisch installiertes
Zielsystem ist noch nicht produktiv validiert. Verwende es deshalb aktuell
weiterhin mit zusätzlicher Absicherung und nicht als einziges Backup für ein
kritisches System.

## Zweck

LoxBerry Host Backup ist ein hostnahes Backup- und Restore-Plugin für
LoxBerry-Systeme.

Es soll nicht nur LoxBerry selbst sichern, sondern auch Programme, Dienste und
Daten, die parallel auf demselben Rechner laufen.

Typische Beispiele:

- LoxBerry-Konfiguration und Plugin-Daten
- Docker-Container, Docker-Volumes und Bind-Mounts
- DietPi-/Debian-Dienste und deren Daten
- systemd-Units, Cronjobs, Skripte und native Programme
- Benutzer- und Anwendungsdaten unter `/opt`, `/home`, `/var/lib` usw.

Das Plugin basiert bewusst nicht auf Raspberry-Pi-spezifischen Tools. Der Kern
ist ein `rsync`-basiertes Host-Backup mit Fokus auf eine möglichst vollständige
Wiederherstellung von Diensten, Daten, Konfigurationen und Systemumgebung.

## Plattform-Kompatibilität

Ziel ist eine möglichst breit kompatible Nutzung auf Linux-basierten
LoxBerry-/DietPi-/Debian-Systemen, z. B. Raspberry Pi, ODROID, VM oder x86.

Voraussetzungen:

- Linux mit Bash
- Perl mit `JSON::PP`
- Perl-CGI-Unterstützung für die Weboberfläche
- `rsync`
- `tar`, `find`, `awk`, `sed`, `tail`, `base64`, `stat`
- `cron` für automatische Backups
- `sudo` für privilegierte Aktionen aus der Weboberfläche

Docker ist optional. Wenn Docker vorhanden ist, kann das Plugin Container
inventarisieren und optional vor dem Backup stoppen sowie danach wieder starten.

Wichtig: Plattformwechsel, z. B. ODROID zu Raspberry Pi oder ARM zu x86, sind
nicht automatisch garantiert. Daten und portable Dienste lassen sich oft
wiederherstellen, hardware- oder architekturspezifische Pakete, Kernelmodule,
Bootloader und Docker-Images können aber manuelle Nacharbeit erfordern.

## Was Gesichert Wird

Das Plugin erstellt:

- kein sektorbasiertes Blockdevice-/Disk-Image
- kein garantiert hardwareunabhängiges Bare-Metal-Komplettimage
- ein dateibasiertes Systembackup auf Basis von `rsync`

Standardquelle ist `/`.

Standardmäßig ausgeschlossen:

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
- gemountete Datenpfade, sofern sie nicht ausgeschlossen werden
- Docker-Daten, sofern sie im gesicherten Dateisystem liegen
- systemd-Units
- Cronjobs
- LoxBerry-Konfiguration
- Plugin-Daten
- native Anwendungsdaten

## Restore Und Migration

Ein Restore kann einem nahezu vollständigen 1:1-System sehr nahe kommen, wenn
das Zielsystem ähnlich ist.

Am zuverlässigsten ist ein Restore bei:

- gleicher CPU-Architektur
- ähnlicher Linux-/DietPi-/Debian-Version
- vergleichbarer Hardware
- identischer oder ähnlicher Docker-Umgebung

Beispiele:

- Raspberry Pi zu Raspberry Pi
- ODROID zu ODROID
- ARM64 zu ARM64
- Debian zu Debian

Plattformwechsel wie ODROID zu Raspberry Pi, ARM zu x86 oder große
Distributionssprünge können manuelle Nacharbeiten erfordern. Das betrifft vor
allem Bootloader, Kernelmodule, Netzwerkinterfaces, UUIDs, Mountpoints,
Device Trees und Docker-Images anderer Architektur.

Empfohlenes Restore-Vorgehen:

1. Zielsystem frisch installieren.
2. LoxBerry installieren.
3. Plugin installieren.
4. Backup importieren oder vorhandenen Backup-Pfad eintragen.
5. Restore in einer Rescue-/Testumgebung vorbereiten und prüfen.
6. Restore gezielt durchführen.

Ein Online-Restore auf einem laufenden System ist riskanter, weil Dienste und
Dateien parallel aktiv sein können.

## Aktueller Validierungsstand

Geprüft:

- Bash-Syntax für Backend, Postinstall, Restore-Helper und Uninstall
- Perl/CGI-Syntax mit lokalem `CGI.pm`-Stub
- Backend-Kommandos `list`, `config`, `preflight-backup`, `task-status`
- Plugin-ZIP-Paketierung
- Installation und Update über den LoxBerry Plugin Manager
- Weboberfläche auf einem LoxBerry-Testsystem
- Speichern der Einstellungen über die LoxBerry-sudoers-Regel
- Echtes Backup auf LoxBerry-/DietPi-Hardware inklusive Live-Log
- Stoppen und Wiederanlauf von Docker-Containern im Backup-Ablauf
- Export-Archiv nach einem Backup

Noch nicht produktiv validiert:

- echter Restore auf ein frisch installiertes Zielsystem
- Docker-/Datenbank-Konsistenz in allen produktiven Anwendungsszenarien
- Migration zwischen unterschiedlichen CPU-Architekturen

## Installation

1. ZIP-Paket aus dem GitHub-Release herunterladen oder lokal bauen.
2. In LoxBerry unter **Plugins > Plugin installieren** hochladen.
3. Nach der Installation die Plugin-Oberfläche öffnen.
4. Root-Freigabe in den Einstellungen bewusst bestätigen.
5. Backup-Verzeichnis und Ausschlüsse prüfen.
6. Einstellungen speichern.
7. Zuerst ein manuelles Testbackup auf einem externen oder separaten Datenträger
   ausführen.

Die Weboberfläche ist in die normale LoxBerry-Oberfläche eingebettet. Die
LoxBerry-Kopfzeile mit Haus-Symbol und Menü bleibt sichtbar, sodass jederzeit
zur LoxBerry-Administration gewechselt werden kann.

Release-Paket:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.3.0/LoxBerryHostBackup_0.3.0.zip
```

Lokales Paket nach dem Build:

```text
LoxBerryHostBackup_0.3.0.zip
```

## Erste Tests Auf LoxBerry

Empfohlene Reihenfolge:

1. Plugin installieren.
2. Weboberfläche öffnen.
3. Backup-Ziel auf einen externen oder separaten Pfad setzen.
4. Alte Backup-, Image- oder Archivordner auf demselben Host ausschließen.
5. Root-Freigabe bestätigen und Einstellungen speichern.
6. Manuelles Backup starten.
7. Live-Status beobachten.
8. Nach Abschluss Backup-Liste prüfen.
9. Dateien über den Backup-Explorer prüfen.
10. Export herunterladen, falls ein transportierbares Archiv benötigt wird.
11. Restore nur auf einem Testsystem oder in einer Rescue-Umgebung prüfen.

## Funktionen

- vollständiges Host-Backup per `rsync`
- inkrementelle Snapshot-Backups per `rsync --link-dest`
- Restore eines ausgewählten Backups
- Restore-Check und Restore-Plan vor dem Start
- Live-Status für laufende Backup-/Restore-Jobs
- Stop-Button für laufende Backups
- Backup-Liste mit Status, Größe, Dateianzahl, Abschlusszeit und Exportstatus
- Backup-Explorer in der Weboberfläche
- Import externer `.tar.gz`-Backup-Archive
- Export vorhandener Backups als `.tar.gz`
- Löschen vorhandener Backups
- Export und Import der Plugin-Einstellungen als JSON-Datei
- Docker-Inventarisierung
- optionales Stoppen/Starten laufender Docker-Container
- zeitgesteuerte Backups per Cron
- tägliche, wöchentliche und monatliche Zeitpläne
- Monatsende-Fallback bei monatlichen Backups am 29., 30. oder 31.
- Aufbewahrungsregel für 1 bis 10 Backups
- Pre-/Post-Backup-Hooks
- Manifest pro Backup mit Host-, LoxBerry- und Inventardaten
- sichtbare Ladeanzeige bei längeren Formularaktionen
- Link zurück zur LoxBerry-Administration

Laufende oder unvollständige Backups können nicht geöffnet, exportiert oder für
Restore ausgewählt werden. Diese Aktionen werden erst freigegeben, wenn das
Backup vollständig abgeschlossen ist.

## Einstellungen

Die Weboberfläche enthält Info-Buttons neben wichtigen Feldern und Aktionen. Die
Hinweise erklären, wofür ein Feld gedacht ist und verschwinden wieder, sobald
der Info-Button verlassen wird.

### Root-Freigabe

Das Plugin benötigt kontrollierte Root-Rechte, weil ein vollständiges Host-
Backup und ein Restore Systemdateien, Berechtigungen, Docker-Daten, Cronjobs und
Dienste betreffen.

In der Weboberfläche muss diese Freigabe bewusst bestätigt werden. Ohne diese
Bestätigung starten Backup- und Restore-Aktionen nicht.

Es werden keine Passwörter gespeichert. Die LoxBerry-sudoers-Regel erlaubt dem
LoxBerry-Webuser ausschließlich den Start des Backend-Skripts dieses Plugins
ohne Passwort.

### Backup-Verzeichnis

Leer bedeutet: Das Plugin verwendet das eigene Datenverzeichnis. Für echte
Backups sollte ein absoluter Pfad auf einem externen oder separaten Datenträger
verwendet werden.

Beispiel:

```text
/media/usb/PI_Backup/loxberry-hostbackup
```

Das konfigurierte Backup-Verzeichnis wird automatisch vom Backup ausgeschlossen,
damit das Backup sich nicht selbst wieder mitsichert.

Das Plugin prüft den eingestellten Speicherort und zeigt in der Oberfläche den
erkannten Dateisystemtyp an. Für inkrementelle Snapshots wird ein Linux-
Dateisystem wie `ext4`, `xfs` oder `btrfs` empfohlen. Unabhängig vom
Backup-Modus ist `ext4` für dieses Plugin in der Praxis meist deutlich
schneller als NTFS/FUSE, besonders bei sehr vielen kleinen Dateien. NTFS/FUSE
kann zusätzlich Hardlinks, Besitzer, Rechte oder Linux-Metadaten nur
eingeschränkt abbilden.

Wenn der Backup-Datenträger noch andere alte Backups, Images oder Archivdaten
enthält, sollten diese zusätzlich ausgeschlossen werden.

Beispiel für ein System mit zwei USB-Mounts:

```text
Backup-Verzeichnis:
/media/usb/PI_Backup/loxberry-hostbackup

Vom Backup ausschließen:
/media/usb/PI_Backup/dietpi-backup
/media/usb/PI_Backup/dietpi-sync
/media/usb/PI_Backup/Bookworm
/media/usb/USB_Loxberry
```

Damit wird das neue HostBackup auf `/media/usb/PI_Backup/loxberry-hostbackup`
gespeichert, während alte DietPi-Backups, Images und der zweite USB-Stick nicht
mitgesichert werden.

### Backup-Modus

Das Plugin kann Backups in zwei Modi erstellen:

- `Vollbackup`: Jeder Backup-Ordner enthält eine vollständige Kopie.
- `Inkrementeller Snapshot`: Das Backup nutzt `rsync --link-dest` und Hardlinks
  auf das vorherige vollständige Backup. Jeder Snapshot sieht weiterhin wie ein
  vollständiges Backup aus und kann direkt für Restore gewählt werden.

Beim ersten inkrementellen Snapshot existiert noch kein vorheriges vollständiges
Backup. Das Plugin erstellt dann automatisch eine vollständige Basiskopie. Ab
dem zweiten erfolgreichen Snapshot werden unveränderte Dateien per Hardlink auf
das vorherige Backup referenziert.

Für zuverlässige Hardlinks, Rechte und Linux-Metadaten wird ein Linux-
Dateisystem wie `ext4`, `xfs` oder `btrfs` als Backup-Ziel empfohlen. Auf
NTFS/FUSE-Zielen kann die Speicherersparnis oder Metadatenunterstützung
eingeschränkt sein.

### Automatische Backups

Automatische Backups können täglich, wöchentlich oder monatlich laufen.

- Täglich: Nur die Uhrzeit ist relevant.
- Wöchentlich: Ein oder mehrere Wochentage und die Uhrzeit sind relevant.
- Monatlich: Ein oder mehrere Monatstage, ein oder mehrere Monate und die
  Uhrzeit sind relevant.

Bei monatlichen Backups gilt ein Monatsende-Fallback: Wenn z. B. der 31.
gewählt ist und ein Monat nur 30, 29 oder 28 Tage hat, startet das Backup am
letzten Tag dieses Monats.

Der Zeitplan wird installiert als:

```text
/etc/cron.d/loxberryhostbackup
```

Der Cron-Eintrag wird bei der Deinstallation wieder entfernt.

### Backups Behalten

Die Anzahl zu behaltender Backups ist auf 1 bis 10 begrenzt. Sobald das Limit
überschritten wird, entfernt das Plugin nach einem erfolgreichen Backup das
älteste vollständig abgeschlossene Backup.

Laufende, fehlgeschlagene oder unvollständige Backup-Verzeichnisse werden dabei
nicht als reguläre Backups gezählt. Sie müssen bei Bedarf manuell geprüft und
gelöscht werden.

### Vom Backup Ausschließen

Ein Eintrag pro Zeile.

Sinnvoll für sehr große Datenpfade, alte Backupordner, Netzwerkshares,
temporäre Daten oder Verzeichnisse, die nicht Teil des Disaster-Recovery-
Backups sein sollen.

Beispiel:

```text
/media/usb/PI_Backup/dietpi-backup
/media/usb/PI_Backup/dietpi-sync
/media/usb/USB_Loxberry
/var/cache/apt
```

### Docker-Container Anhalten

Wenn aktiviert, werden laufende Docker-Container vor dem Backup gestoppt und
danach wieder gestartet.

Das verbessert die Konsistenz von Container-Daten, kann aber Dienste während
des Backups unterbrechen. Das Plugin startet nur Container wieder, die es zuvor
selbst gestoppt hat.

Für Datenbanken oder Anwendungen mit eigenen Backup-Mechanismen können
zusätzliche Pre-/Post-Backup-Hooks sinnvoll sein.

### Export-Archiv Erstellen

Wenn aktiviert, wird nach jedem Backup zusätzlich ein `.tar.gz`-Archiv erstellt.

Das ist praktisch zum Herunterladen, Kopieren oder Archivieren. Es benötigt aber
zusätzlichen Speicherplatz und Zeit. Bei inkrementellen Snapshots kann ein
Export-Archiv deutlich größer sein als der zusätzliche Speicherverbrauch des
Snapshot-Ordners, weil das Archiv einen transportierbaren Stand enthält.

### Einstellungen Exportieren Und Importieren

Die Plugin-Einstellungen können als kleine JSON-Datei exportiert und nach einer
Neuinstallation wieder importiert werden.

Enthalten sind zum Beispiel:

- Backup-Verzeichnis
- Backup-Modus
- Ausschlüsse
- Docker-Option
- Export-Option
- Zeitplan
- Aufbewahrung
- Pre-/Post-Backup-Hooks
- Root-Freigabe-Bestätigung

Nicht enthalten sind Backup-Daten oder Passwörter.

Nach einem Import sollten die Pfade trotzdem kurz geprüft werden, weil sich
USB-Mounts oder Laufwerksnamen nach einer Neuinstallation ändern können.

### Hooks

Pre- und Post-Backup-Hooks sind optionale ausführbare Skripte mit absolutem
Pfad.

Sie müssen Root gehören und dürfen nicht durch Gruppe oder andere Benutzer
beschreibbar sein.

Sie können genutzt werden, um Datenbanken zu dumpen, Dienste vorzubereiten oder
nach dem Backup aufzuräumen.

## Live-Status

Nach dem Start eines Backups erscheint ein Live-Status. Er zeigt fortlaufend,
was das Backend gerade macht, z. B. Docker-Stop, `rsync`-Fortschritt, Export und
Aufbewahrung.

Während ein Backup läuft:

- bleibt der Live-Status beim Navigieren im Plugin erhalten
- kann ein laufendes Backup über `Backup stoppen` abgebrochen werden
- sind Datei-Explorer, Restore und Export für dieses laufende Backup gesperrt

Nach Abschluss stoppt die Anzeige der letzten Log-Aktualisierung. Die
Backup-Liste wird anschließend aktualisiert.

## Backup-Liste Und Aktionen

Die Backup-Liste zeigt pro Backup:

- ID
- Status
- Host
- Größe
- Dateianzahl
- Abschlusszeit
- Exportstatus
- verfügbare Aktionen

Mögliche Aktionen:

- `Dateien`: Backup-Explorer für ein vollständiges Backup öffnen.
- `Restore`: Restore-Bereich für genau dieses Backup vorbereiten.
- `Export`: vorhandenes Export-Archiv herunterladen oder Export anstoßen.
- `Löschen`: Backup und zugehöriges Export-Archiv entfernen.

`Datei auswählen` und `Externes Backup importieren` sind für bereits extern
gespeicherte `.tar.gz`-Backup-Archive gedacht, z. B. wenn ein Backup vom PC oder
einem anderen Speicherort wieder in das Plugin geholt werden soll.

## Restore

Ein Restore schreibt das Backup zurück nach `/` und kann das Zielsystem
überschreiben.

Der Restore ist deshalb absichtlich mehrstufig:

1. In der Backup-Liste beim gewünschten Backup `Restore` wählen.
2. Restore-Check und Restore-Plan im eingeblendeten Restore-Bereich prüfen.
3. Restore per Checkbox ausdrücklich bestätigen.
4. Restore starten.

Der Restore-Bereich wird nur angezeigt, wenn vorher ein Backup aus der Liste
ausgewählt wurde.

Für einen vollständigen Restore ist ein frisch installiertes Zielsystem oder
eine Rescue-/Offline-Umgebung vorzuziehen.

## Docker Und Datenbanken

Laufende Container und Datenbanken können während eines Live-Backups
inkonsistente Dateien erzeugen.

Für wichtige Dienste sollten daher entweder:

- Docker-Container vor dem Backup gestoppt werden
- Pre-/Post-Hooks für Datenbank-Dumps verwendet werden
- oder applikationsspezifische Backup-Mechanismen genutzt werden

## Kommandozeile

Nach der Installation liegt das Backend typischerweise hier:

```sh
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh
```

Wichtige Backend-Kommandos:

```sh
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh list
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh preflight-backup
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh start
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh task-status backup-YYYYMMDD-HHMMSS.log
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh browse BACKUP_ID
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh export BACKUP_ID
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh delete BACKUP_ID
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh preflight-restore BACKUP_ID
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh restore-plan BACKUP_ID
```

Weitere Backend-Kommandos wie `cat-file` oder `move` sind vorhanden, werden in
der Weboberfläche aber nicht als Standardworkflow geführt.

## Dateien Und Verzeichnisse

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

## Deinstallation

Bei der Deinstallation entfernt das Plugin seine LoxBerry-Plugin-Dateien und den
Cron-Eintrag `/etc/cron.d/loxberryhostbackup`.

Backup-Daten auf externen Datenträgern werden nicht automatisch gelöscht. Sie
sollen bewusst erhalten bleiben, damit ein Restore oder eine spätere manuelle
Prüfung möglich bleibt.

## Bekannte Grenzen

- erste vorsichtig freigegebene Version, produktive Nutzung weiterhin mit eigener Prüfung
- noch kein echter Ende-zu-Ende-Restore auf LoxBerry/DietPi produktiv validiert
- kein Ersatz für applikationsspezifische Datenbank-Backups
- Plattformmigration kann manuelle Nacharbeit erfordern
- Bootloader-, Kernel- und Partitionslayout-Themen werden nicht gelöst
- sehr große Backups und Exporte müssen auf Speicherplatz und Laufzeit getestet werden
- inkrementelle Snapshots setzen für optimale Speicherersparnis ein Dateisystem
  mit zuverlässiger Hardlink-Unterstützung voraus, z. B. `ext4`
- kein sektorbasiertes Raw-Disk-/Blockdevice-Image wie z. B. `dd` oder Clonezilla

## Entwicklung

Repository:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup
```

Branches:

- `main`: aktueller freigegebener Stand 0.3.0
- `develop`: laufende Weiterentwicklung

Update-Dateien:

- `release.cfg`: Stable-Kanal mit ZIP-Download aus dem GitHub-Release
- `prerelease.cfg`: Pre-Release-Kanal, derzeit identisch mit dem freigegebenen Paket

Das installierbare ZIP wird über den Release-Kanal bereitgestellt. Der Pre-Release-Kanal zeigt aktuell auf dasselbe Paket.

GitHub Actions erzeugt das Plugin-ZIP automatisch und hängt es bei
GitHub-Releases als Asset an.

Paket lokal bauen:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1
```

Alternativ unter Linux/GitHub Actions:

```sh
./package.sh
```
