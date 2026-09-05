# LoxBerry Host Backup

**Status:** Vorabversion 0.6.1-beta aus `develop`. Dieser Stand enthält
zusätzliche Sicherheits-, Metadaten- und Restore-Härtungen und wird über den
Pre-Release-Kanal für Tests bereitgestellt. Der stabile Release-Kanal bleibt
weiterhin auf Version 0.5.8.

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
- `rsync` für verzeichnisbasierte Backups und Restores
- Python 3 für die sichere Prüfung importierter Archive
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

Standardmässig ausgeschlossen:

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

## Mailbenachrichtigung

Das Plugin kann nach Backup-, Abbruch- und Restore-Ereignissen eine
Mailbenachrichtigung senden. SMTP-Zugangsdaten werden nicht im Plugin
gespeichert. Wenn im Plugin keine Mailadresse eingetragen ist, verwendet
LoxBerry Host Backup die globale Standardadresse aus der
LoxBerry-Mail-/Benachrichtigungskonfiguration.

Erfolgreiche Backups werden nur per Mail gemeldet und erzeugen keinen
zusaetzlichen Eintrag in der LoxBerry-Notification-Uebersicht. Fehler, Abbruch
und Restore-Ereignisse bleiben bewusst LoxBerry-Notifications, damit kritische
Ereignisse auch im System sichtbar sind.

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

Plattformwechsel wie ODROID zu Raspberry Pi, ARM zu x86 oder grosse
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
- Stoppen und Wiederanlauf ausgewählter Docker-Container und Dienste im Backup-Ablauf
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

Aktuelles stabiles Release-Paket:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.5.8/LoxBerryHostBackup_0.5.8.zip
```

Aktuelles Pre-Release-Paket:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.6.1-beta/LoxBerryHostBackup_0.6.1.zip
```

Lokales Paket nach dem Build:

```text
LoxBerryHostBackup_0.6.1.zip
```

## Erste Tests Auf LoxBerry

Empfohlene Reihenfolge:

1. Plugin installieren.
2. Weboberfläche öffnen.
3. Backup-Ziel auf einen externen oder separaten Pfad setzen.
4. Alte Backup-, Image- oder Archivordner auf demselben Host ausschliessen.
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
- vier explizite Metadatenprofile für native Linux-, CIFS-/NFS- und portable Ziele
- Restore eines ausgewählten Backups
- Restore-Check und Restore-Plan vor dem Start
- Live-Status für laufende Backup-, Restore-, Export- und Import-Jobs
- Stop-Button für laufende Backups
- Backup-Liste mit Status, Grösse, Dateianzahl, Abschlusszeit und Exportstatus
- Backup-Explorer in der Weboberfläche
- Import externer `.tar.gz`-Backup-Archive im Hintergrund
- Export vorhandener Backups als `.tar.gz` mit SHA-256- und Manifest-Bezug
- Löschen vorhandener Backups
- Export und Import der Plugin-Einstellungen als JSON-Datei
- Docker- und Dienst-Inventarisierung
- auswählbares Stoppen/Starten einzelner Docker-Container und systemd-Dienste
- Kurzanleitung für die wichtigsten Einstellungen und Kontrollen
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

> [!IMPORTANT]
> **Geänderte Einstellungen müssen immer zuerst gespeichert werden.**
> Eine Auswahl oder Eingabe in der Weboberfläche ist zunächst nur eine
> ungespeicherte Änderung. Erst mit **Änderungen speichern** werden die Werte in
> die Plugin-Konfiguration übernommen. Das gilt insbesondere für
> Backup-Verzeichnis, Ausschlüsse, Aufbewahrung, Metadaten-Profil, Backup-Modus,
> ausgewählte Dienste und Container sowie den Zeitplan. Speichere die Änderungen
> deshalb **vor dem Start eines manuellen Backups und bevor du dich auf ein
> automatisches Backup verlässt**. Ohne Speichern verwendet das Plugin weiterhin
> die zuletzt gespeicherten Werte; bei einer Neuinstallation ist gegebenenfalls
> noch kein gültiges Backup-Ziel oder kein aktiver Zeitplan vorhanden. Der
> eingeblendete Speicherhinweis erinnert daran, speichert die Änderung aber nicht
> automatisch.

Die Weboberfläche enthält Info-Buttons neben wichtigen Feldern und Aktionen. Die
Hinweise erklären, wofür ein Feld gedacht ist. Ihre Position wird an den
sichtbaren Browserbereich angepasst, damit auch Info-Buttons am rechten oder
unteren Fensterrand vollständig lesbar bleiben.

Sobald eine Einstellung geändert wird, erscheint unten rechts ein nicht
blockierender Speicherhinweis. Er nennt den geänderten Bereich, den neuen Wert
und die Uhrzeit der Änderung und bietet direkt **Änderungen speichern** an. Das
gilt auch für Optionsfelder wie Metadaten-Profil, Backup-Modus und Zeitplan. Wird
ein Feld auf seinen zuletzt gespeicherten Wert zurückgestellt, verschwindet sein
Eintrag wieder; ohne Änderungen bleibt der Hinweis vollständig ausgeblendet.

### Root-Freigabe

Das Plugin benötigt kontrollierte Root-Rechte, weil ein vollständiges Host-
Backup und ein Restore Systemdateien, Berechtigungen, Docker-Daten, Cronjobs und
Dienste betreffen.

In der Weboberfläche muss diese Freigabe bewusst bestätigt werden. Ohne diese
Bestätigung starten Backup- und Restore-Aktionen nicht.

Es werden keine Passwörter gespeichert. Die LoxBerry-sudoers-Regel erlaubt dem
LoxBerry-Webuser ausschliesslich einen root-eigenen Dispatcher. Dieser akzeptiert
nur die für die Weboberfläche benötigten Aktionen, startet ein fest verdrahtetes,
root-eigenes Backend und verwirft die aufrufende Umgebung. Der Dispatcher und
der geschützte Laufzeitbereich werden während der Installation über den von
LoxBerry als Root ausgeführten Hook `postroot.sh` eingerichtet. Bei einem
Upgrade sichert `preroot.sh` zuvor die bestehende `config.json`. `postroot.sh`
stellt sie unmittelbar zu Beginn der privilegierten Nacharbeiten wieder her,
bevor weitere Installationsprüfungen laufen. Damit bleiben Backup-Ziel,
Metadaten-Profil, Ausschlüsse, Zeitplan, Stop-Ziele und die übrigen
Plugin-Einstellungen bei künftigen Updates erhalten.

### Backup-Verzeichnis

Ohne gespeicherten Pfad zeigt die Oberfläche einen neutralen Hinweis; eine
Dateisystem-Prüfung ist dann noch nicht möglich. Für echte Backups muss ein
absoluter Pfad auf einem externen oder separaten Datenträger verwendet und über
**Einstellungen speichern** übernommen werden.

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

Beim Speichern wird das Ziel mit einer zufälligen Markerdatei und seiner
Mount-Identität registriert. Vor Backup, Restore, Import, Export und Löschen
werden Marker, Mountpoint, Quelle und Dateisystem erneut geprüft. Dadurch wird
ein nicht eingehängtes NAS nicht unbemerkt durch das gleichnamige lokale
Verzeichnis ersetzt. Benutzerdefinierte Ziele auf dem Root-Dateisystem sind
standardmässig gesperrt.

Wenn der Backup-Datenträger noch andere alte Backups, Images oder Archivdaten
enthält, sollten diese zusätzlich ausgeschlossen werden.

Beispiel für ein System mit zwei USB-Mounts:

```text
Backup-Verzeichnis:
/media/usb/PI_Backup/loxberry-hostbackup

Vom Backup ausschliessen:
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

Als Referenz wird nur ein erfolgreich validierter Snapshot mit demselben
Metadaten-Profil verwendet. Backups aus Version 0.5.8 und älter enthalten diese
Profilinformation noch nicht und können daher nicht als `--link-dest` dienen.
Nach einem Update von einem solchen Altbestand wird der erste inkrementelle Lauf
nochmals als vollständige Basiskopie erstellt. Der nächste erfolgreiche Lauf
mit unverändertem Metadaten-Profil kann diese neue Basiskopie wieder
inkrementell verwenden. Im Live-Log zeigt `Snapshot reference: .../rootfs` die
verwendete Referenz; `No complete previous backup found. Creating first snapshot
as full copy.` kennzeichnet eine neue vollständige Basiskopie.

Die Vorprüfung erkennt diesen Basiskopiefall vor dem Start. Ist ein älteres
abgeschlossenes Backup mit Größenangabe vorhanden, verwendet das Plugin dessen
Belegung als Schätzwert und verlangt zusätzlich 20 Prozent beziehungsweise
mindestens 1 GiB Reserve. Reicht der freie Speicher dafür erkennbar nicht aus,
wird der Lauf noch vor dem Stoppen ausgewählter Dienste und Container beendet.
Ein normaler inkrementeller Lauf mit passender Hardlink-Referenz bleibt davon
unverändert.

Für zuverlässige Hardlinks, Rechte und Linux-Metadaten wird ein Linux-
Dateisystem wie `ext4`, `xfs` oder `btrfs` als Backup-Ziel empfohlen. Auf
NTFS/FUSE-Zielen kann die Speicherersparnis oder Metadatenunterstützung
eingeschränkt sein.

### Metadaten-Profil

Das Metadaten-Profil muss zum Ziel passen. Die Standardeinstellung bei einer
Neuinstallation ist `Native Strict`. Sie ist für lokale Linux-Dateisysteme
gedacht; bei CIFS/NFS oder einem NAS muss bewusst das passende Profil gewählt
werden. In der Weboberfläche besitzt jedes Profil einen eigenen Info-Button mit
seinen gesicherten Metadaten, Voraussetzungen und Restore-Einschränkungen:

- `Native Strict`: für lokale Linux-Ziele mit ext4, xfs oder btrfs. `rsync`
  sichert Besitzer, Rechte, ACLs, xattrs, File Capabilities und Hardlinks
  vollständig. Fehlt eine benötigte Funktion, wird das Backup als Fehler
  beendet.
- `Network Compatible`: `rsync -aHA` ohne xattrs. Dieses Profil ist für CIFS-
  oder NFS-Ziele gedacht, die einzelne Linux-xattrs mit `Operation not
  supported` ablehnen. Das bewusste Auslassen wird als neutraler Hinweis im
  Manifest und in der Oberfläche dokumentiert. Ein ansonsten erfolgreiches
  Backup erhält `complete`/`ok` und läuft auch per Zeitplan ohne Bestätigung;
  ein Restore benötigt wegen der reduzierten Metadaten weiterhin eine
  zusätzliche Bestätigung.
- `Fake Super`: für Ziele mit user-xattrs, aber ohne native Unix-Metadaten.
  rsync speichert privilegierte Angaben in `user.rsync.*`; das Profil darf nur
  verwendet werden, wenn das Ziel user-xattrs zuverlässig unterstützt.
- `Portable Archive`: für Ziele ohne geeignete Linux-Metadatenfunktionen. Das
  Profil erzeugt einen metadatentreuen `rootfs.tar`-Container, ist nicht mit
  inkrementellen Snapshots kombinierbar und darf nur aus einer Rescue-/Offline-
  Umgebung wiederhergestellt werden.

Vor jedem Backup führt das Backend einen kleinen Metadaten-Roundtrip auf dem
registrierten Ziel aus. Ein Profil wird nicht stillschweigend herabgestuft.
File Capabilities können für einzelne Systemprogramme sicherheitsrelevant sein;
deshalb ist das Weglassen von xattrs eine bewusste, sichtbare Entscheidung und
keine pauschale Behandlung von rsync-Code 23 als Erfolg.

### Automatische Backups

Automatische Backups können täglich, wöchentlich oder monatlich laufen.

Bei einem manuellen Start prüft das Plugin zuerst die Voraussetzungen. Eine
Bestätigung zum Fortfahren wird nur eingeblendet, wenn dabei eine übergehbare
Warnung erkannt wurde, beispielsweise sehr wenig freier Speicher oder laufende
Docker-Container ohne Stop-Auswahl. Echte Fehler können nicht bestätigt und
übergangen werden. Ein neutraler Hinweis des Profils `Network Compatible` löst
diese Bestätigung nicht aus.

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

Bei inkrementellen Snapshots ist das sicher, weil jeder Snapshot als eigener
Backup-Ordner sichtbar bleibt. Unveränderte Dateien sind per Hardlink mehrfach
referenziert. Wird ein alter Snapshot gelöscht, verschwinden nur dessen
Verzeichniseinträge; Datei-Inhalte bleiben erhalten, solange sie noch von einem
jüngeren Snapshot referenziert werden. Erst wenn kein verbleibender Snapshot
mehr auf einen Datei-Inhalt zeigt, wird der Speicher freigegeben.

Hinweis zur angezeigten Grösse: Bei inkrementellen Snapshots kann ein neuer
Snapshot sehr klein wirken. Das ist normal. Unveränderte Dateien werden per
Hardlink geteilt und belegen auf dem Datenträger nicht nochmals denselben
Speicherplatz.

Laufende, fehlgeschlagene oder unvollständige Backup-Verzeichnisse werden dabei
nicht als reguläre Backups gezählt. Sie müssen bei Bedarf manuell geprüft und
gelöscht werden.

### Vom Backup Ausschliessen

Ein Eintrag pro Zeile.

Sinnvoll für sehr grosse Datenpfade, alte Backupordner, Netzwerkshares,
temporäre Daten oder Verzeichnisse, die nicht Teil des Disaster-Recovery-
Backups sein sollen.

Beispiel:

```text
/media/usb/PI_Backup/dietpi-backup
/media/usb/PI_Backup/dietpi-sync
/media/usb/USB_Loxberry
/var/cache/apt
```

### Dienste Und Container Anhalten

In den Einstellungen kann gezielt ausgewählt werden, welche Docker-Container
oder systemd-Dienste vor dem Backup gestoppt und danach wieder gestartet werden.
Das Plugin liest dazu die vorhandenen Container und sicher steuerbare Dienste
aus, gruppiert sie kompakt und merkt sich die Auswahl.
Installierte LoxBerry-Plugins ohne eigenen sicher steuerbaren Dienst werden
nicht als Stop-Ziel angeboten, weil sie nicht zuverlässig automatisch wieder
gestartet werden können.
Mit `Empfohlene Auswahl setzen` markiert das Plugin automatisch laufende
Container und typische datenintensive Dienste, z. B. Datenbanken, MQTT/Zigbee,
Node-RED, Stats4Lox, Grafana oder InfluxDB. Die Empfehlung kann danach manuell
angepasst werden.

Das verbessert die Konsistenz von Container-, Datenbank- und Dienst-Daten, kann
aber diese Dienste während des Backups unterbrechen. Das Plugin startet nur
Ziele wieder, die vor dem Backup wirklich liefen und durch dieses Backup
gestoppt wurden. Kritische LoxBerry-, Web-, SSH-, Docker- und Backup-Dienste
werden in der Auswahl nicht angeboten. LoxBerry-Plugins ohne eigenen
systemd-Dienst werden nicht hart beendet; dafür sind Pre-/Post-Backup-Hooks
der sicherere Weg.

Die tatsächlich gestoppten Container und Dienste werden im Backup-Verzeichnis
protokolliert und zusätzlich im `manifest.json` festgehalten. Auch bei einem
manuellen Abbruch wird diese Restart-Liste verwendet, damit bereits gestoppte
Ziele wieder gestartet werden. Ein abgebrochenes Backup wird als `stopped`
markiert; die Weboberfläche fragt danach, ob das unvollständige Backup gelöscht
werden soll.

Für Datenbanken oder Anwendungen mit eigenen Backup-Mechanismen können
zusätzliche Pre-/Post-Backup-Hooks sinnvoll sein.

### Export-Archiv Erstellen

Wenn aktiviert, wird nach jedem Backup zusätzlich ein `.tar.gz`-Archiv erstellt.

Das ist praktisch zum Herunterladen, Kopieren oder Archivieren. Es benötigt aber
zusätzlichen Speicherplatz und Zeit. Bei inkrementellen Snapshots kann ein
Export-Archiv deutlich grösser sein als der zusätzliche Speicherverbrauch des
Snapshot-Ordners, weil das Archiv einen transportierbaren Stand enthält.
Das Archiv wird erst aus einem finalisierten und validierten Backup erstellt.
Eine SHA-256-Datei und ein Descriptor binden es an die finale `manifest.json`;
Download und Statusprüfung lehnen fehlende oder widersprüchliche
Integritätsdaten ab.

### Einstellungen Exportieren Und Importieren

Die Plugin-Einstellungen können als kleine JSON-Datei exportiert und nach einer
Neuinstallation wieder importiert werden.

Enthalten sind zum Beispiel:

- Backup-Verzeichnis
- Backup-Modus
- Ausschlüsse
- ausgewählte Stop-Ziele für Container und Dienste
- Export-Option
- Zeitplan
- Aufbewahrung
- Pre-/Post-Backup-Hooks

Nicht enthalten sind Backup-Daten oder Passwörter.

Nach einem Import sollten die Pfade trotzdem kurz geprüft werden, weil sich
USB-Mounts oder Laufwerksnamen nach einer Neuinstallation ändern können.
Die Root-Freigabe wird aus Sicherheitsgründen nicht aus der Einstellungsdatei
übernommen und muss nach dem Import erneut bestätigt werden.

### Hooks

Pre- und Post-Backup-Hooks sind optionale ausführbare Skripte mit absolutem
Pfad.

Sie müssen Root gehören und dürfen nicht durch Gruppe oder andere Benutzer
beschreibbar sein.

Sie können genutzt werden, um Datenbanken zu dumpen, Dienste vorzubereiten oder
nach dem Backup aufzuräumen.

## Live-Status

Nach dem Start eines Backups erscheint ein Live-Status. Er zeigt fortlaufend,
was das Backend gerade macht, z. B. Dienst-/Container-Stop, `rsync`-Fortschritt,
Export und Aufbewahrung.

Während ein Backup läuft:

- bleibt der Live-Status beim Navigieren im Plugin erhalten
- kann ein laufendes Backup über `Backup stoppen` abgebrochen werden
- sind Datei-Explorer, Restore und Export für dieses laufende Backup gesperrt

Export und Import grosser `.tar.gz`-Archive laufen ebenfalls als Hintergrundjob
mit Live-Status. Dadurch bleibt die Weboberfläche erreichbar, während das Archiv
erstellt, geprüft oder importiert wird.

Die Webanzeige stellt die von `rsync` verwendeten Wagenrückläufe als echte
Zeilenenden dar und entfernt reine Terminal-Steuerzeichen. Alle
Fortschrittsmeldungen bleiben sichtbar. Lange Einzelzeilen werden nicht mitten
im Text umgebrochen, sondern können horizontal gescrollt werden. Die
gespeicherte Original-Logdatei bleibt unverändert.

Nach Abschluss stoppt die Anzeige der letzten Log-Aktualisierung. Die
Backup-Liste wird anschliessend aktualisiert.

### Verhalten Nach Einem LoxBerry-Neustart

LoxBerry kann das normale Plugin-Logverzeichnis beim Start neu anlegen und dem
Benutzer `loxberry` zuweisen. Host Backup verwendet dieses plattformverwaltete
Verzeichnis deshalb nicht für privilegierte Task-Dateien. Backup-, Restore-,
Import- und Export-Logs liegen dauerhaft und root-geschützt unter:

```text
/var/lib/loxberryhostbackup/logs/
```

Die Oberfläche liest diese Logs ausschliesslich über den begrenzten
Root-Dispatcher. Die gespeicherte Konfiguration bleibt unabhängig davon unter
`/opt/loxberry/config/plugins/loxberryhostbackup/config.json` erhalten. Kann die
Konfiguration aus einem anderen technischen Grund nicht geladen werden, werden
Speichern und Backup-Start gesperrt. Sichtbare Ersatzwerte können dadurch nicht
versehentlich über die vorhandenen Einstellungen geschrieben werden.

## Backup-Liste Und Aktionen

Die Backup-Liste zeigt pro Backup:

- ID
- Status
- Host
- Grösse
- Dateianzahl
- Abschlusszeit
- Exportstatus
- verfügbare Aktionen

Mögliche Aktionen:

- `Dateien`: Backup-Explorer für ein vollständiges Backup öffnen.
- `Restore`: Restore-Bereich für genau dieses Backup vorbereiten.
- `Export`: vorhandenes Export-Archiv herunterladen oder Export anstossen.
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
3. Die vollständige Backup-ID als Sicherheits-Challenge eingeben.
4. Restore per Checkbox ausdrücklich bestätigen.
5. Bei einem degradierten Backup den Metadatenverlust separat akzeptieren.
6. Restore starten.

Der Restore-Bereich wird nur angezeigt, wenn vorher ein Backup aus der Liste
ausgewählt wurde.

Für einen vollständigen Restore ist ein frisch installiertes Zielsystem oder
eine Rescue-/Offline-Umgebung vorzuziehen.

Nur finalisierte Backups mit passender Validierung sind restorefähig. Die
Quelle wird durch Marker und Manifest-ID gebunden, laufende Operationen sind
global und pro Backup gesperrt, und ein Restore wertet nur Exit-Code 0 als
Erfolg. Portable Archive ist in der Weboberfläche absichtlich nicht startbar;
hierfür ist der Offline-Helper vorgesehen.

## Docker Und Datenbanken

Laufende Container und Datenbanken können während eines Live-Backups
inkonsistente Dateien erzeugen.

Für wichtige Dienste sollten daher entweder:

- betroffene Container oder Dienste vor dem Backup gestoppt werden
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

Offline-Restore eines Portable Archive:

```sh
HOSTBACKUP_OFFLINE_RESTORE=1 /opt/loxberry/bin/plugins/loxberryhostbackup/restore-hostbackup.sh BACKUP_ID
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
/var/lib/loxberryhostbackup/
/var/lib/loxberryhostbackup/logs/
```

Das Verzeichnis unter `/opt/loxberry/log/plugins/` wird von LoxBerry verwaltet
und darf nach einem Neustart `loxberry:loxberry` gehören. Sicherheitskritische
Task-Zustände und Task-Logs liegen unter `/var/lib/loxberryhostbackup/` und
bleiben `root:root` mit eingeschränkten Rechten.

Systemdateien:

```text
/opt/loxberry/system/sudoers/LoxBerryHostBackup
/etc/cron.d/loxberryhostbackup
/usr/local/sbin/loxberryhostbackup-sudo
/var/lib/loxberryhostbackup
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
- sehr grosse Backups und Exporte müssen auf Speicherplatz und Laufzeit getestet werden
- inkrementelle Snapshots setzen für optimale Speicherersparnis ein Dateisystem
  mit zuverlässiger Hardlink-Unterstützung voraus, z. B. `ext4`
- kein sektorbasiertes Raw-Disk-/Blockdevice-Image wie z. B. `dd` oder Clonezilla

Der verbindliche Restore-Testplan steht in
[`docs/DR-TESTPLAN.md`](docs/DR-TESTPLAN.md); Sicherheitsgrenzen und
Bedrohungsmodell stehen in [`docs/SECURITY.md`](docs/SECURITY.md).

## Entwicklung

Repository:

```text
https://github.com/herdan75/LoxBerry-Plugin-HostBackup
```

Branches:

- `main`: aktuell veröffentlichter stabiler Stand
- `develop`: laufende Weiterentwicklung

Update-Dateien:

- `release.cfg`: Stable-Kanal mit ZIP-Download aus dem GitHub-Release
- `prerelease.cfg`: Pre-Release-Kanal mit neuer Vorabversion

Das stabile installierbare ZIP wird über den Release-Kanal bereitgestellt. Der
Pre-Release-Kanal zeigt für freiwillige Tests auf Version 0.6.1-beta. LoxBerry
erkennt die Vorabversion über `prerelease.cfg`; das Paket liegt im zugehörigen
GitHub-Pre-Release unter dem Tag `v0.6.1-beta`.

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
