# LoxBerry Host Backup

**Version 1.0.0 · Reguläres Release · veröffentlicht am 19.09.2026.**
Die erste Hauptversion übernimmt den vollständigen develop-Stand `4da7cf6`
einschliesslich der Installations-, Sicherheits- und Bedienungskorrekturen.
Programm- und Paketversion lauten `1.0.0`, ohne Beta-Zusatz. Gegenüber diesem
develop-Stand werden keine Backup-/Restoreabläufe geändert.
Details stehen in den [Release Notes für 1.0.0](docs/RELEASE-1.0.0.md).

**Noch unveröffentlicht auf `develop`:** Eine explizite Auswahl von Laufwerken
und Netzfreigaben sowie eine schrittweise Metadaten-Diagnose werden im
[NAS-Teststand](docs/DEVELOP-NAS-SOURCES.md) beschrieben. Diese Änderungen sind
nicht im bestehenden öffentlichen Download von 1.0.0 enthalten.
Die Datenquellen-Ansicht trennt auswählbare Laufwerke von aufklappbaren technischen
Einbindungen. Diese Gruppierung verändert keine Auswahl; gespeicherte Ausnahmen
bleiben direkt sichtbar. Hinweistexte sind gegen globale LoxBerry-Schriftregeln
abgegrenzt und ausführliche Erläuterungen lassen sich separat öffnen.

> [!IMPORTANT]
> **Update auf 1.0.0:** Das reguläre Release ist ohne Beta-Zusatz erhältlich.
> Auch Nutzer des bisherigen Vorabkanals erhalten über dessen Kanaldatei dasselbe
> stabile Paket, solange keine neuere Vorabversion angeboten wird.
> Vor einem Update Einstellungen exportieren, aktive Vorgänge beenden lassen
> und nicht vorher deinstallieren.

**Enthaltene Korrekturen:** Der automatische Dienst-Wiederanlauf setzt
bei einer belegten Vorgangssperre still aus, statt dadurch Cron-Mails auszulösen.
Die abschliessende Aufbewahrungsprüfung erhält eine eigene Live-Status-Phase.
Alle übernommenen Änderungen sind im [Changelog](CHANGELOG.md) dokumentiert.

**Installation und Wiederinstallation:** Der alte Plugin-Bin-Baum wird vor dem Update für
LoxBerrys unprivilegierten Dateiaustausch vorbereitet, die Konfiguration vorher
gesichert und das eigentliche Backup-Programm vor seiner Aktivierung geprüft.
Ein zurückgebliebenes Weiterleitungs-Startskript wird nicht mehr als Backend
übernommen. Die Zeitplan-Einrichtung ist auf 30 Sekunden plus höchstens
5 Sekunden zum Beenden begrenzt. Die bereits vorhandene Unterstützung für
LoxBerrys Cron-Symlink und `root:root 775` bleibt erhalten; gemeinsame
Systemrechte werden nicht geändert.

> [!WARNING]
> **Eine noch hängende alte Installation zuerst klären:** Keinen zweiten
> Installationsversuch parallel starten und nicht deinstallieren. Ein neues
> ZIP beendet bereits laufende fehlerhafte Altprozesse nicht automatisch.
> Erst nach Wiederherstellung einer bedienbaren Plugin-Verwaltung aktualisieren.
> Frühere Versionspakete bleiben unverändert; 1.0.0 besitzt einen eigenen Download.

Die geschützten Programmstände unter `/usr/libexec/loxberryhostbackup` bleiben
erhalten. Die Tests bilden Löschen und Kopieren als unprivilegierter
Plattformbenutzer nach; Kopieren als Root allein reicht nicht als Update-Test.

> [!IMPORTANT]
> **Erst Einstellungen speichern, dann sichern.** Auch ausgewählte Optionen,
> Dienste, Container und Zeitpläne gelten erst nach **Änderungen speichern**.
> Automatische Backups verwenden ausschliesslich die zuletzt gespeicherten Werte.

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
- gemountete Datenpfade entsprechend der gespeicherten Datenquellenauswahl und
  den zusätzlichen Ausschlüssen
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

Bisherige veröffentlichte Stände wurden wie folgt geprüft. Diese historischen
Praxistests sind **kein** Hardware-Nachweis für den neuen Entwicklungsstand:

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

Der neue Arbeitsstand ergänzt Verhaltenstests für Importangriffe, Dienst-Neustart,
Zeitpläne, Ausschlüsse beim Restore, Metadaten-Roundtrips, Downloads, Aufbewahrung,
Inhaltsprüfung und Browserbedienung. Windows-Prüfungen ersetzen die separat
erforderlichen Linux-, NAS- und Offline-Restoretests nicht. Die
[Linux-Abnahme des Teststands 39254c6](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34759728463)
bestand 191 Tests ohne Skips, alle 14 Browser-Prüfblöcke, Rechte-/Metadatenprüfungen
und den ZIP-Build. Der [nachgebesserte Stand 416e8ff](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34764161868)
bestand 203 Linux-Tests ohne Skips sowie 15 Browser-Prüfblöcke, einschliesslich
echter konkurrierender Dateisperren und Root-/Webbenutzerprüfungen. Auch der
[übernommene Stand 4da7cf6](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34764755275)
bestand diese 203 Linux-Tests und 15 Browser-Prüfblöcke. Der
[vorbereitete 1.0.0-Stand c981111](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/35440782063)
bestand 205 Linux-Tests ohne Skips und 15 Browser-Prüfblöcke. Die Release-Pipeline
prüft zusätzlich den tatsächlichen Tag vor dem Veröffentlichen des ZIPs; den
zugehörigen Lauf nennt die [Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.0.0).
Der lokale
Umsetzungs- und Prüfstand wird in [IMPLEMENTATION-2026-09.md](docs/IMPLEMENTATION-2026-09.md)
geführt. Die [GitHub-Prüfläufe](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/workflows/build-plugin.yml?query=branch%3Amain)
zeigen den jeweiligen Commit, die Ergebnisse und das gebaute Testpaket.
Eine echte LoxBerry-/NAS-/Offline-Hardwareabnahme ist damit nicht nachgewiesen
und bleibt für den verlässlichen produktiven Disaster-Recovery-Einsatz separat erforderlich.
Die Veröffentlichung bescheinigt keine bestandene Hardware-Abnahme.

### Bekannte offene Punkte in 1.0.0

- **Speicherbelegung berechnen:** durchsucht alle erkannten Backup-Dateien und
  liefert erst am Ende ein Ergebnis, derzeit ohne Fortschrittsanzeige. Auf
  grossen oder langsamen Zielen kann das lange dauern. Die Browser-Wartefrist
  beträgt eine Stunde; ein Abbruch im Browser beendet den Backend-Aufruf nicht
  zwingend. Ob der gemeldete konkrete Lauf hing oder noch rechnete, ist nicht
  durch eine Live-Diagnose bestätigt.
- **Laufzeitdateien prüfen:** kann während einer Speicherberechnung oder anderen
  gesperrten Operation abgewiesen werden. Die Oberfläche zeigt dann derzeit
  „Unerwartete Serverantwort (HTTP 500)“ statt der eigentlichen Belegtmeldung.
  Dieser Ablauf wurde isoliert reproduziert, nicht auf dem betroffenen Gerät.
  Prüfungen vorerst nacheinander ausführen; bei unklarem Status nicht wiederholt
  starten. Die kompakte Übersicht behebt diese Funktionsprobleme noch nicht.
- Die zurückgestellte AP-14 zur Mail-/Benachrichtigungssemantik bleibt ausgenommen.

## Installation

1. Das Release-ZIP 1.0.0 über den Link unten herunterladen oder das angebotene
   Update in der LoxBerry-Plugin-Verwaltung verwenden.
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

Aktuelles reguläres Release-Paket:

[**LoxBerryHostBackup_1.0.0.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.0.0/LoxBerryHostBackup_1.0.0.zip)

Der Vorabkanal verweist ebenfalls auf dieses reguläre Release, solange keine
neuere Vorabversion existiert. Alte Downloads bleiben in der
[Release-Historie](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases) erhalten.

### Update auf 1.0.0

In der LoxBerry-Plugin-Verwaltung nach Updates suchen oder das ZIP manuell
installieren. Je nach persönlicher Update-Einstellung wird die neue Version
angeboten oder automatisch installiert. Es ist nicht erforderlich, Vorabversionen
zu aktivieren. Programmversion, Release-Tag und Paket lauten `1.0.0`,
`v1.0.0` und `LoxBerryHostBackup_1.0.0.zip`, ohne Beta-Zusatz.

**Bereits das manuelle 1.0.0-Testpaket installiert?** Bei gleicher Versionsnummer
erscheint kein höheres Update. Für exakt das veröffentlichte Paket das Release-ZIP
erneut installieren, ohne vorher zu deinstallieren. Die Backup-/Restorelogik
entspricht dem vorbereiteten 1.0.0-Stand; ergänzt sind finale Kanalmetadaten und
Veröffentlichungsdokumentation.

Vor dem Update laufende Backup-/Restoreaufgaben beenden lassen und die
Plugin-Einstellungen exportieren. Vorhandene Einstellungen und Backupdaten
werden beim Update nicht absichtlich zurückgesetzt oder gelöscht. Nach dem
Update Ziel, Ausschlüsse, Profil und Zeitplan kontrollieren, geänderte Werte
**speichern** und zunächst ein manuelles Testbackup ausführen. Neue optionale
Inhaltsprüfungen und Aufbewahrungsregeln bewusst konfigurieren; Inhaltsprüfungen
benötigen zusätzlichen Speicher und Zeit.

**Wichtig beim Umstieg von 0.5.8 und älter:** Der erste inkrementelle Lauf
benötigt nochmals eine vollständige Basiskopie, weil diesen alten Backups die
Metadaten-Profilinformation fehlt. Erst ein nachfolgender erfolgreicher Lauf
kann wieder Hardlinks verwenden. Genügend zusätzlichen freien Platz einplanen;
das letzte brauchbare Backup wird nicht vorab zur Platzbeschaffung gelöscht.
Ein Update von 0.6.x oder 0.7.x auf 1.0.0 erzwingt allein durch die Versionsnummer keine
neue Basiskopie: Entscheidend ist weiterhin eine verwendbare Referenz mit
passendem Profil.

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
- Anzahlaufbewahrung für 1 bis 3650 Backups oder tägliche/wöchentliche/monatliche Aufbewahrung mit Schutz einzelner Sicherungen
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
/media/usb/PI_Backup
```

In diesem Beispiel enthält `PI_Backup` ausschliesslich Sicherungen. Das neue
HostBackup wird dort unter `loxberry-hostbackup` gespeichert, ohne diesen
Datenträger einschliesslich alter DietPi-Backups und Images nochmals zu sichern.
Nutzdaten unter `/media/usb/USB_Loxberry` bleiben dagegen eingeschlossen.

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
  Dieses Profil verwendet zwei lokale rsync-Prozesse mit einem fest definierten
  lokalen Transport, um einen bekannten Fehler lokaler `-M`-Aufrufe in rsync
  3.2.7 zu umgehen. Dafür werden weder SSH noch ein Netzwerkdienst benötigt;
  die Sicherung bleibt auf dem eingebundenen lokalen/NAS-Dateisystem.
- `Portable Archive`: für Ziele ohne geeignete Linux-Metadatenfunktionen. Das
  Profil erzeugt einen metadatentreuen `rootfs.tar`-Container, ist nicht mit
  inkrementellen Snapshots kombinierbar und darf nur aus einer Rescue-/Offline-
  Umgebung wiederhergestellt werden.

Vor jedem Backup führt das Backend einen kleinen Metadaten-Roundtrip auf dem
registrierten Ziel aus. Ein Profil wird nicht stillschweigend herabgestuft.
Im unveröffentlichten develop-Teststand zeigt eine fehlgeschlagene Prüfung die
betroffenen Schritte mit Soll-/Ist-Werten, Exit-Code und begrenzter
Werkzeugausgabe. Die letzte Diagnose liegt zusätzlich root-geschützt unter
`/var/lib/loxberryhostbackup/metadata-probe.json`; sie wird bei der nächsten
Metadatenprüfung ersetzt. Bei zeitgesteuerten Startfehlern stehen die Details
auch im Aufgabenlog.

**Network Compatible ist kein allgemeiner Kompatibilitätsmodus für jede
CIFS-Einbindung:** Besitzer, Gruppe, Rechte, ACLs und Links müssen weiterhin
erhalten bleiben. Feste CIFS-Eigentümer oder Dateirechte können diese Prüfung
zu Recht scheitern lassen. Falls das Ziel diese Eigenschaften nicht speichern
kann: **Portable Archive und Vollbackup wählen, Einstellungen speichern und
erneut prüfen.** Dieser Modus sichert die Metadaten innerhalb von `rootfs.tar`,
unterstützt keine inkrementellen Snapshots und verlangt einen Offline-/Rescue-
Restore. Die Zielprüfung muss auch für dieses Profil erfolgreich sein.

File Capabilities können für einzelne Systemprogramme sicherheitsrelevant sein;
deshalb ist das Weglassen von xattrs eine bewusste, sichtbare Entscheidung und
keine pauschale Behandlung von rsync-Code 23 als Erfolg.

### Laufwerke und Netzfreigaben auswählen (develop-Teststand)

Unter **Laufwerke und Netzfreigaben** lassen sich die Grundregel und einzelne
eingebundene Quellen auswählen. Änderungen wirken erst nach dem Speichern,
auch bei zeitgesteuerten Backups.

- **Neue Konfiguration:** Lokale Laufwerke bleiben enthalten, Netzfreigaben und
  Automount-Bereiche dagegen nicht automatisch. Eine gewünschte Netzfreigabe
  zuerst einbinden, aktualisieren und ausdrücklich auswählen.
- **Bestehende Konfiguration ohne neue Auswahl:** Das bisherige Verhalten bleibt
  erhalten, einschliesslich der bisher mitgesicherten Netzfreigaben. Zum Schutz
  vor unbeabsichtigt grossen Backups die Grundregel bewusst auf lokale Laufwerke
  ändern, gewünschte Freigaben auswählen und speichern. Das Update ändert den
  Sicherungsumfang nicht stillschweigend.
- Ein `autofs`-Sammelverzeichnis wird nicht pauschal freigegeben: einzelne
  eingebundene Freigaben auswählen. Eine aktiv ausgewählte, aber nicht mehr
  eingebundene Quelle verhindert den Start, statt unbemerkt im Backup zu fehlen.
- Zusätzliche Ausschlüsse und der Ausschluss des Backup-Ziels haben Vorrang.
  `/media/usb/PI_Backup` kann ausgeschlossen bleiben, während Nutzdaten auf
  `/media/usb/USB_Loxberry` mitgesichert werden. `/media` nicht pauschal ausschliessen,
  wenn dort gewünschte Nutzdaten liegen.
- **Nächstes Backup prüfen** zeigt den gespeicherten Umfang. Beim Backup wird die
  Dateiliste nach dem Dienst-Stopp erfasst und ohne rekursives Nachladen kopiert.
  Dies verhindert, dass ausgeschlossene Netzfreigaben nachträglich betreten
  werden. Änderungen der Mount-Tabelle führen vorsichtshalber zum Fehler.
- Ohne gespeichertes Backup-Ziel startet kein Backup mehr in einem lokalen
  Standardverzeichnis. Ein separates Ziel auswählen und zuerst speichern.

Die Auswahl wird im Backup als `source-selection.json` dokumentiert. Ein darin
nicht eingeschlossenes Volume kann nicht versehentlich für einen Volume-Restore
freigegeben werden. Die Auswahl und Dateilisten-Prüfung ersetzen keinen echten
Restore-Test; die Erfassung benötigt zusätzliche Zeit bei vielen Dateien.

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

Im neuen Entwicklungsstand verwenden alle Zeitplanarten denselben Startweg:
übergehbare Preflight-Warnungen werden für den automatischen Lauf akzeptiert,
echte Fehler blockieren. Auch ein abgewiesener Start bleibt als fehlgeschlagener
Versuch mit Protokoll sichtbar. Ein leeres Wochen-/Monatsraster wird nicht
stillschweigend als Sonntag, Monatserster oder alle Monate gespeichert.

### Backups Behalten

Standard bleibt die Anzahlaufbewahrung mit 10 Backups; im Entwicklungsstand sind
1 bis 3650 auswählbar. Alternativ lässt sich tägliche, wöchentliche und monatliche
Aufbewahrung kombinieren (GFS: standardmässig 7/4/6 Zeitgruppen). Pro Zeitgruppe
bleibt die jüngste passende Sicherung erhalten. Nach einem erfolgreichen Backup
wird diese gespeicherte Regel angewendet.

Einzeln geschützte Sicherungen und die jüngste brauchbare Sicherung bleiben immer
erhalten. Schutz kann die konfigurierte Anzahl überschreiten. Vor einer manuellen
Bereinigung zeigt die Vorschau die betroffenen Sicherungen und Gründe; verändert
sich die Grundlage, muss die Vorschau erneuert werden. Das letzte gute Backup
wird nicht vor einer neuen Basiskopie zur Platzbeschaffung gelöscht.

Bei inkrementellen Snapshots ist das sicher, weil jeder Snapshot als eigener
Backup-Ordner sichtbar bleibt. Unveränderte Dateien sind per Hardlink mehrfach
referenziert. Wird ein alter Snapshot gelöscht, verschwinden nur dessen
Verzeichniseinträge; Datei-Inhalte bleiben erhalten, solange sie noch von einem
jüngeren Snapshot referenziert werden. Erst wenn kein verbleibender Snapshot
mehr auf einen Datei-Inhalt zeigt, wird der Speicher freigegeben.

Logische Dateigrösse, belegte Blöcke und gemeinsam genutzte Hardlinks sind
verschiedene Werte. Die zusätzliche Speicherübersicht misst diese ausdrücklich
auf Anforderung; bei grossen NAS-Zielen kann das dauern. Einzelwerte mehrerer
Snapshots dürfen wegen gemeinsamer Inodes nicht einfach addiert werden.
Eine Belegungsmessung ist keine Prognose für das nächste Backup.

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
/media/usb/PI_Backup
/var/cache/apt
```

In diesem Beispiel enthält `PI_Backup` ausschliesslich Backups und wird deshalb
vollständig ausgeschlossen. Ein separater Datenpfad wie
`/media/usb/USB_Loxberry` bleibt eingeschlossen, sofern seine Daten mitgesichert
werden sollen. Nicht pauschal alle USB-Mounts ausschliessen. Die Sicherungsvorschau
zeigt gespeicherte Regeln, erkannte Volumes und eine verwendbare Snapshot-Referenz.

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

Die Wiederanlaufliste liegt dauerhaft im lokalen, root-geschützten Verzeichnis
`/var/lib/loxberryhostbackup/restart-journals/`, unabhängig vom Backup-Medium.
Der Eintrag wird vor dem Stoppen eines zuvor laufenden Ziels synchronisiert.
Auch bei Abbruch oder fehlendem Backup-Medium können offene Wiederanläufe dadurch
nachgeholt werden. Die separate Cron-Regel versucht dies beim Boot und alle fünf
Minuten erneut; noch laufende Aufgaben werden nicht gestört. Diese Wiederanläufe
gelten nur für zuvor vom Plugin ausgewählte Stop-Ziele, nicht für beliebige Dienste.
Das Manifest hält zusätzlich die Stop-Ziele fest. Ein abgebrochenes Backup wird
als `stopped` markiert; schlägt der Wiederanlauf fehl, bleibt ein Fehlerzustand
mit offenem Journal sichtbar. Unvollständige Backups vor einer Löschung prüfen.

**In Version 1.0.0 enthalten:** Die Boot-/Fünfminuten-Regel
ruft `recover-services --scheduled` auf. Hält gerade ein Backup, Restore oder anderer
Vorgang die globale Sperre, endet nur dieser automatische Versuch ohne Ausgabe
und mit Erfolgscode. Der nächste Cron-Termin versucht den Wiederanlauf erneut;
aktive Aufgaben, Dienste und offene Journale werden dabei nicht verändert.
Das verhindert Cron-Mails allein wegen einer erwartbaren belegten Sperre.
Technische Fehler und fehlgeschlagene Dienststarts bleiben sichtbar. Der manuelle
Aufruf `recover-services` meldet eine belegte Sperre weiterhin als Fehler.
Die konfigurierten Backup-Mailbenachrichtigungen werden dadurch nicht geändert.

Nach erfolgreicher Backup-Prüfung kann die Aufbewahrung älterer Sicherungen noch
Zeit benötigen. Der Live-Status zeigt dafür
„Aufbewahrung prüfen und alte Backups bereinigen“ (`retention`) statt weiterhin
`validating`. Die Aufgabe bleibt bis zum Abschluss dieses Schritts als laufend
markiert und hält ihre Sperre; die Aufbewahrungsregeln bleiben unverändert.

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

Übersicht und Live-Status haben wie die Einstellungen weisse Inhaltsflächen.
In der Übersicht stehen Beschriftung und Wert mit Abstand untereinander;
direkt sichtbar bleiben letztes erfolgreiches Backup, nächster Termin, aktueller
Vorgang und freier Zielspeicher. Je nach Fensterbreite stehen diese Angaben in
vier, zwei oder einer Spalte. **Details und Prüfaktionen** klappt die vollständige
Backup-ID, den Zielpfad, die Vorgangsdatei und die Prüf-/Diagnoseschaltflächen auf.
Der Bereich ist anfangs geschlossen; automatische Aktualisierungen verändern
seinen Zustand nicht. Das Aufklappen startet keine Prüfung. Der letzte
protokollierte Fehler, offene Dienst-Wiederanläufe und bereits geladene
Prüfergebnisse bleiben auch bei geschlossenem Detailbereich sichtbar.

CSS und JavaScript werden über ihren Inhaltsstand geladen, sodass auch
Korrekturen ohne Versionssprung nach erneutem Öffnen der Plugin-Seite sichtbar
werden.

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
Meldungen des angezeigten Ausschnitts bleiben getrennt lesbar. Lange Einzelzeilen
werden nicht mitten im Text umgebrochen, sondern können horizontal gescrollt
werden. Die Liveanzeige ist bewusst begrenzt; das **vollständige Originalprotokoll**
kann separat heruntergeladen werden und bleibt unverändert. Wer nach oben
scrollt, wird durch Aktualisierungen nicht wieder ans Ende versetzt.

Nach Abschluss stoppt die Anzeige der letzten Log-Aktualisierung. Die
Backup-Liste wird anschliessend aktualisiert.
Ungespeicherte Einstellungen werden dabei nicht durch eine automatische
Seitennavigation verworfen. Auch ohne Start-Link erkennt die Übersicht laufende
Zeitplanaufträge und bietet die Auftragshistorie an.

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

Zusätzlich liegen Dienst-Neustartjournale unter
`/var/lib/loxberryhostbackup/restart-journals/`. Vor einem Dienst-Stopp wird dort
dauerhaft festgehalten, was gegebenenfalls neu gestartet werden muss. Das
funktioniert auch bei verschwundenem Backup-Medium. Offene Neustarts werden
beim Booten, danach alle fünf Minuten und vor einem neuen Backup erneut versucht.
Laufende Aufträge bleiben unberührt; nur im Journal festgehaltene Dienste oder
Container werden behandelt. Misslingt ein Neustart, bleibt das Journal erhalten.

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

Ein vollständiger Restore schreibt entweder nach `/` (laufender Host, riskant)
oder in ein ausdrücklich gewähltes Offline-Zielverzeichnis. Bestehende Dateien
im freigegebenen Zielbereich können ersetzt und beim rsync-Restore gelöscht werden.
Die zum Backup gespeicherten Ausschlüsse bleiben beim Restore geschützt;
fehlende oder unsichere Ausschlussdateien blockieren den Vorgang.

Der Restore ist deshalb absichtlich mehrstufig:

1. In der Backup-Liste beim gewünschten Backup `Restore` wählen.
2. Ziel und gegebenenfalls Volume-Zuordnungen angeben; Restore-Check und echte
   Datei-/Löschvorschau im Restore-Bereich prüfen.
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

Separate Quell-Volumes werden nicht stillschweigend auf das Root-Dateisystem
zurückkopiert. Sie benötigen eine ausdrückliche Zuordnung zu vorhandenen,
sicheren Zielverzeichnissen; die Vorschau benennt ausgelassene Volumes. Portable
Archive erfordert zusätzlich ein Offline-Ziel ungleich `/`, respektiert dieselben
Ausschlüsse und löscht keine am Ziel zusätzlich vorhandenen Dateien.

Einzelne Dateien oder Ordner lassen sich in einen **neu angelegten**
`recovered-…`-Unterordner an einem alternativen Ort zurückholen. Dieser Weg
überschreibt keine dort vorhandenen Benutzerdateien und stoppt keine Dienste.
Ein unvollständiger Wiederherstellungsordner bleibt bei Fehlern zur Prüfung
erhalten. Symbolische Links werden als Links wiederhergestellt, nicht verfolgt.
Das je Backup herunterladbare Recovery-Blatt enthält die dazu passenden
Offline-Schritte; Bootpartition, Bootloader und Systemtest bleiben eigene Schritte.

## Inhaltsprüfung, Wartung und Diagnose

Die optionale Inhaltsprüfung ist standardmässig ausgeschaltet. Bei Aktivierung
wird nach einem erfolgreichen neuen Backup eine Prüfbasis aufgezeichnet. Ein
späterer Vergleich erkennt Änderungen und fehlende Dateien. Für vorhandene
Sicherungen bedeutet der erste Lauf nur **Prüfbasis erstellt**, nicht nachträglich
bewiesene Originaltreue. Die automatische Prüfung kontrolliert stündlich, ob nach
dem gespeicherten Intervall (Standard: 7 Tage) eine Sicherung fällig ist, und prüft
höchstens eine fällige Sicherung pro Aufruf. Ein Prüfbericht kann heruntergeladen werden.

`Kopie abgeschlossen`, `Struktur geprüft`, `Inhalt mit Prüfbasis verglichen` und
`vollständiger Restore getestet` sind ausdrücklich unterschiedliche Nachweise.
Eine Inhaltsprüfung ersetzt keinen Teststart des wiederhergestellten Systems.
Einen selbst durchgeführten Praxistest kannst du je Backup über
**Externen Restoretest dokumentieren** mit Datum, Ergebnis und kurzer Notiz
festhalten. Diese lokale Historie ist ausdrücklich eine persönliche Angabe,
keine vom Plugin überprüfte Boot-/Funktionsbestätigung. Sie ändert weder den
Backupstatus noch die Sicherheitsfreigabe für einen Restore. Geänderte Manifeste
entwerten die Zuordnung eines früheren Testnachweises zum aktuellen Stand.
Ohne dokumentierten Praxistest bleibt die Wiederherstellung nicht nachgewiesen.
Notizen können sensible Angaben enthalten und gehören nicht ungeprüft in
einen öffentlich geteilten Prüfbericht. Bis zu 20 Testeinträge bleiben erhalten.
Prüfbasis und Schutzmarkierungen liegen im lokalen root-geschützten Pluginstatus;
sie werden nicht als unabhängig vertrauenswürdiger Nachweis aus einem fremden
Import übernommen. Umfangreiche Inhaltsprüfungen lesen alle betreffenden Daten
und können auf einem NAS lange dauern.

Die Prüfbasis benötigt zusätzlich lokalen Speicher unter
`/var/lib/loxberryhostbackup/integrity/`, auch wenn das Backup auf einem NAS liegt.
Der Platzbedarf wächst mit Dateizahl, Pfadlängen und Metadaten je Sicherung;
ein Vergleich benötigt vorübergehend einen zweiten Index. Je Prüflauf gelten
maximal 2 GiB Indexplatz und mindestens 256 MiB freie Reserve für lokalen Status.
Reicht der Platz nicht, schlägt die optionale Prüfung mit einem Fehler fehl;
eine vorhandene Prüfbasis wird nicht stillschweigend ersetzt. Die Speicherübersicht
weist lokalen Platz für Prüfindizes, Logs und Quarantäne getrennt aus. Beim
bestätigten Löschen einer Sicherung entfernt das Plugin auch deren zugehörige
lokale Prüfbasis und Bericht. Schlägt nur diese Nachbereinigung fehl, wird das
gemeldet; die bereits gelöschte Sicherung wird dadurch nicht wiederhergestellt.

Fehlgeschlagene Backups bleiben zur bewussten Sichtung und Löschung erhalten.
Alte Aufgabenprotokolle und quarantänisierte Importe lassen sich separat mit
Vorschau bereinigen (Standardalter 30 beziehungsweise 7 Tage). Offene Neustartjournale
werden dabei niemals entfernt. Bereinigung ist endgültig und nicht rückgängig zu machen.

Ein Diagnose-ZIP enthält Version, ausgewählten Taskstatus, anonymisierte
Konfiguration und Mountinformationen. Das optional ausgewählte Originalprotokoll
ist vollständig und kann weiterhin private Pfade oder Adressen enthalten:
**vor dem Weitergeben prüfen**. Pro Diagnosepaket sind maximal 100 MiB Logdaten
vorgesehen; grössere Originalprotokolle separat herunterladen.

## Docker Und Datenbanken

Laufende Container und Datenbanken können während eines Live-Backups
inkonsistente Dateien erzeugen.

Für wichtige Dienste sollten daher entweder:

- betroffene Container oder Dienste vor dem Backup gestoppt werden
- Pre-/Post-Hooks für Datenbank-Dumps verwendet werden
- oder applikationsspezifische Backup-Mechanismen genutzt werden

## Kommandozeile

Als root den vertrauenswürdigen Einstieg verwenden:

```sh
/usr/local/sbin/loxberryhostbackup
```

Wichtige Backend-Kommandos:

```sh
/usr/local/sbin/loxberryhostbackup task-overview
/usr/local/sbin/loxberryhostbackup backup-preview
/usr/local/sbin/loxberryhostbackup start
/usr/local/sbin/loxberryhostbackup task-status backup-YYYYMMDD-HHMMSS.log
/usr/local/sbin/loxberryhostbackup browse BACKUP_ID
/usr/local/sbin/loxberryhostbackup export BACKUP_ID
/usr/local/sbin/loxberryhostbackup inspect-backup BACKUP_ID
/usr/local/sbin/loxberryhostbackup verify-backup BACKUP_ID
/usr/local/sbin/loxberryhostbackup storage-info
/usr/local/sbin/loxberryhostbackup maintenance-preview
/usr/local/sbin/loxberryhostbackup restore-plan BACKUP_ID /mnt/recovery-root
```

Offline-Restore eines Portable Archive:

```sh
ALLOW_RESTORE=1 HOSTBACKUP_OFFLINE_RESTORE=1 /usr/local/sbin/loxberryhostbackup restore BACKUP_ID confirm-degraded /mnt/recovery-root
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
/usr/local/sbin/loxberryhostbackup
/usr/libexec/loxberryhostbackup/releases/
/usr/libexec/loxberryhostbackup/current
/etc/cron.d/loxberryhostbackup-recovery
/var/lib/loxberryhostbackup
```

Der Root-Einstieg bindet jeden Aufruf an eine unveränderliche, root-eigene
Helferversion. Ein Update schaltet den Verweis `current` atomar um; bereits
laufende Aufgaben verwenden weiterhin ihre bisherige Helferversion. Python-Caches
werden dort nicht angelegt. Alte Helferversionen werden nicht während laufender
Aufgaben entfernt.

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

- `main`: veröffentlichter Hauptstand 1.0.0
- `develop`: auf die Release-Basis nachgeführt; Ausgangspunkt weiterer Entwicklung
- `pre-develop`: älterer Referenzstand; unverändert

Update-Dateien:

- `main/release.cfg`: Stable 1.0.0 mit dem geprüften Release-ZIP
- `develop/prerelease.cfg`: vorerst dasselbe reguläre 1.0.0-Paket für Vorabkanal-Nutzer

Die in `plugin.cfg` hinterlegten Kanaladressen bleiben unverändert, damit
bestehende Installationen die neuen Metadaten finden. Sobald eine neuere
Vorabversion vorhanden ist, kann deren Kanal gezielt weitergeführt werden.

Ein Branch-Push erzeugt nur ein geprüftes Workflow-Artefakt. Ein Tag-/Release-
Ereignis veröffentlicht das ZIP erst nach Linux-/Browserprüfungen. Für die
Freigabe werden die live abgefragten Branch-Kanaldateien erst nach erfolgreicher
Prüfung des öffentlichen Downloads umgestellt. Die Wiki-/Pluginseite wird
separat gepflegt; ein Git-Push bearbeitet sie nicht. AP-14 bleibt ausgenommen.

Paket lokal bauen:

```powershell
powershell -ExecutionPolicy Bypass -File .\package.ps1
```

Alternativ unter Linux/GitHub Actions:

```sh
./package.sh
```
