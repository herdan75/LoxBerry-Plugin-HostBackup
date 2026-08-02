# Sicherheitsmodell

## Privilegierte Grenze

Die Weboberfläche ruft nicht mehr direkt ein per Wildcard freigegebenes
Plugin-Skript als Root auf. `sudoers/sudoers` erlaubt nur den installierten
Dispatcher `/usr/local/sbin/loxberryhostbackup-sudo`. Der Dispatcher:

- ist Root-eigen und nicht durch Gruppe oder andere Benutzer beschreibbar,
- akzeptiert nur eine feste Aktions- und Argumentanzahl,
- prüft Eigentümer und Modus des fest verdrahteten Backends,
- startet das Backend mit einer leeren, definierten Umgebung.

Backend, Dispatcher, Restore-Helper und Konfiguration werden bei der
Installation Root zugeordnet. Die Konfigurationsdatei wird unter Lock in eine
neue Datei geschrieben, synchronisiert und atomar umbenannt. Eine ungültige
bestehende Konfiguration wird nicht automatisch überschrieben.

Locks, Task-State und bereits vom Backend angenommene Importdateien liegen unter
`/var/lib/loxberryhostbackup` in Root-eigenen Verzeichnissen. Ein Web-Upload wird
dorthin verschoben und als reguläre Datei mit genau einem Hardlink erneut
geprüft, bevor Besitzrechte oder Archivinhalt ausgewertet werden.

## Ziel- und Löschsicherheit

Ein Backup-Ziel wird kanonisiert und darf weder geschützte Systempfade noch
symbolische Pfadkomponenten verwenden. Benutzerdefinierte Ziele müssen auf
einem separaten Mount liegen. Beim Speichern werden folgende Werte registriert:

- zufälliger Zielmarker,
- Mountpoint,
- Mountquelle,
- Dateisystemtyp,
- Major/Minor-ID bei lokalen Dateisystemen.

Bei Netzwerkdateisystemen wird bewusst keine Major/Minor-ID gebunden, weil sie
sich nach einem legitimen Remount ändern kann. Marker, Quelle, Mountpoint und
Dateisystem bleiben Pflicht. Jeder Backup-Ordner trägt zusätzlich einen Marker,
und seine Manifest-ID muss exakt mit dem Verzeichnisnamen übereinstimmen.
Löschen erfolgt erst nach diesen Prüfungen und einer atomaren Umbenennung in
einen Trash-Namen innerhalb des registrierten Ziels.

## Parallelität und Prozessidentität

Mutierende Aktionen verwenden einen globalen Lock; backupbezogene Aktionen
zusätzlich einen Lock pro Backup-ID. Hintergrundprozesse schreiben atomare
Task-State-Dateien mit PID und `/proc`-Startzeit. Stoppen signalisiert nur den
zu dieser Identität gehörenden Prozess beziehungsweise seine Prozessgruppe.
Der Wiederanlauf tatsächlich gestoppter Dienste und Container wird protokolliert
und bei Fehler oder Abbruch erneut geprüft.

## Import- und Webschutz

Alle POST-Formulare verwenden einen stündlich rotierenden HMAC-CSRF-Token und
prüfen, falls vorhanden, den `Origin`-Header. Konfigurations- und Backup-Uploads
werden gestreamt und begrenzt; Teildateien werden entfernt.

Importe werden vor der Extraktion ohne Entpacken geprüft. Abgelehnt werden
unter anderem:

- absolute Pfade und `..`,
- mehrere Top-Level-Backups,
- doppelte Einträge,
- ausbrechende Hardlinks,
- Schreibvorgänge durch zuvor angelegte Symlinks,
- Devices, FIFOs und unbekannte Tar-Typen,
- zu viele Einträge oder überschrittene Entpackgrenzen.

Ein eingebettetes Portable-`rootfs.tar` wird nach der äusseren Extraktion mit
denselben Pfadregeln separat geprüft. Erst danach werden Marker, Manifest-ID,
Status und Validierung geprüft und das Backup atomar veröffentlicht.

## Restore-Grenzen

Restore setzt Root-Freigabe, registriertes Ziel, Marker, exakte Manifest-ID und
eine gültige Kombination aus Abschluss- und Validierungsstatus voraus.
Degradierte Backups benötigen eine zusätzliche ausdrückliche Bestätigung.
Portable Archive benötigt `HOSTBACKUP_OFFLINE_RESTORE=1` und ist nicht aus der
Weboberfläche startbar. Die Weboberfläche verlangt zusätzlich die vollständige
Backup-ID als Challenge.

Ein Dateibackup ersetzt kein Blockdevice-Image. Bootloader, Partitionstabellen,
Kernel-/Firmware-Kompatibilität und applikationskonsistente Datenbank-Backups
bleiben ausserhalb dieser Sicherheitsgarantie.

## Sicherheitsmeldungen

Bitte Schwachstellen nicht mit produktiven Backup-Daten in einem öffentlichen
Issue dokumentieren. Melde reproduzierbare Details zunächst vertraulich an die
im Repository angegebene Kontaktadresse und nenne Version, Ziel-Dateisystem,
relevante Logzeilen und ein minimales Reproduktionsszenario.
