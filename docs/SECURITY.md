# Sicherheitsmodell

Stand: 1.0.0 auf `main`, Veröffentlichung noch nicht freigegeben. Enthalten ist die Absicherung des
unprivilegierten Update-Dateiaustauschs und die Launcher-/Backend-Trennung.
Die kompakte Übersicht verändert keine Berechtigungen, Locks oder
Bestätigungsanforderungen. Die noch offene HTTP-500-Darstellung bei gesperrter
Laufzeitprüfung ist kein Anlass, den Sperrschutz abzuschalten; siehe
[bekannte Grenzen](RELEASE-1.0.0.md#bekannte-offene-punkte).

Version 1.0.0 übernimmt die Korrektur aus dem letzten Vorabpaket und behandelt nur beim automatischen
`recover-services --scheduled` eine belegte Vorgangssperre als stilles Aussetzen.
Die Sperre wird nicht umgangen und Journale werden dabei nicht verändert.
Technische Sperrfehler und fehlgeschlagene Dienststarts bleiben Fehler. Der
Web-Dispatcher erlaubt weiterhin nur den manuellen Aufruf ohne diesen Zusatz.

## Privilegierte Grenze

Die Weboberfläche ruft nicht mehr direkt ein per Wildcard freigegebenes
Plugin-Skript als Root auf. `sudoers/sudoers` erlaubt nur den installierten
Dispatcher `/usr/local/sbin/loxberryhostbackup-sudo`. Der Dispatcher:

- ist Root-eigen und nicht durch Gruppe oder andere Benutzer beschreibbar,
- akzeptiert nur eine feste Aktions- und Argumentanzahl,
- prüft Eigentümer und Modus des fest verdrahteten Root-Einstiegs,
- startet das Backend mit einer leeren, definierten Umgebung.

Backend, Dispatcher, Restore-Helper und Konfiguration werden bei der
Installation Root zugeordnet. Die Konfigurationsdatei wird unter Lock in eine
neue Datei geschrieben, synchronisiert und atomar umbenannt. Eine ungültige
bestehende Konfiguration wird nicht automatisch überschrieben.

Der Einstieg `/usr/local/sbin/loxberryhostbackup` bindet jeden Aufruf an eine
kanonische, root-eigene Version unter `/usr/libexec/loxberryhostbackup/releases/`.
Alle ausführbaren Helfer einschliesslich Python-Importvalidator und ihrer
Elternverzeichnisse müssen gegen Schreibzugriff anderer Benutzer geschützt sein.
`current` wird nach vollständig kopiertem Helferstand atomar umgestellt.
Laufende Aufgaben behalten ihre bisherige Version; fremd beschreibbare
Pluginverzeichnisse werden nicht als privilegierte Hilfsprogramme verwendet.
Alte Helferstände bleiben erhalten. Das ist jedoch kein automatisches Rollback
der gesamten Installation, Konfiguration oder Cron-Regeln. Diese Schutzprüfung
gilt für die Plugin-Helfer; gemeinsam genutzte LoxBerry-/Systembibliotheken und
deren Updates bleiben Verantwortung der Plattform.

Vor einem Update sichert PREROOT zuerst die Konfiguration und übergibt dann
nur die Verzeichnisse des alten Plugin-Bin-Baums an den Plattformbenutzer.
LoxBerry löscht/kopiert dort als unprivilegierter Benutzer; Root-eigene
Verzeichnisse würden den Austausch verhindern. Symlink-Verzeichnisse werden
nicht verfolgt, Dateibesitzer und die geschützten Helferstände ausserhalb
dieses Baums werden nicht geändert. POSTROOT schützt den neuen Bin-Baum wieder
während der Übernahme. Eine Backend-Kennungsprüfung vor dem Umschalten von
`current` verhindert, dass ein alter Weiterleitungs-Launcher als Backend
veröffentlicht wird. Dieselbe Prüfung im Root-Einstieg verhindert rekursive
Starts auch bei einem bereits falsch gesetzten Programmverweis. Sie ist eine
Strukturprüfung, keine kryptografische Echtheitsprüfung des Installationspakets.
Die abschliessende Zeitplan-Einrichtung ist auf 30 Sekunden plus höchstens
5 Sekunden zum Beenden begrenzt.

Die Cron-Integration berücksichtigt LoxBerrys systemseitige Verknüpfung
`/etc/cron.d` nach `$LBHOMEDIR/system/cron/cron.d`. Nur dieser erwartete,
existierende Zielpfad wird als Ausnahme zugelassen; der Symlink und das
Cron-Zielverzeichnis müssen Root gehören. Am Ziel ist Gruppenschreibrecht
ausschliesslich für die Gruppe `root` (GID 0) zulässig, wie beim tatsächlich
gemeldeten Zustand `root:root 775`. Weltschreibrecht und Schreibrecht für andere
Gruppen werden abgelehnt. Diese Ausnahme behandelt die Gruppe `root` als Teil
der administrativen Plattformgrenze, nicht als unprivilegierten Webbenutzer.
Die erzeugten Cron-Dateien bleiben Root-eigen und haben Modus `644`.
Die von LoxBerry verwalteten
Elternverzeichnisse werden nicht umgewidmet. Diese Plattformgrenze gilt nur für
Cron-Konfigurationen, nicht für ausführbare Root-Helfer oder deren Elternpfade.

Fake Super verwendet für die getrennte Behandlung von Sender und Empfänger
einen festen lokalen rsync-Transport. Der Shellcode ist konstant, führt kein
`eval` aus und stellt keine SSH-/Netzwerkverbindung her; Zielpfade werden nicht
in ausführbaren Shelltext eingesetzt. Geschützte rsync-Argumentübertragung
bewahrt Leerzeichen und Sonderzeichen in Pfaden. Diese Umgehung betrifft den
[bekannten lokalen rsync-Fehler #505](https://github.com/RsyncProject/rsync/issues/505);
Native Strict und Network Compatible behalten ihren lokalen Kopierweg.

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
Manuelles Löschen erfolgt erst nach diesen Prüfungen und einer atomaren Umbenennung
in einen Trash-Namen innerhalb des registrierten Ziels. Die neue Wartungsbereinigung
bindet ihre Vorschau an Inventar, Manifestzustände, Schutzmarkierungen, Exporte und
aktive Aufgaben; sie prüft die Kandidaten erneut vor dem Entfernen und überschreitet
keine Mountgrenzen. Die jüngste brauchbare und geschützte Sicherungen bleiben erhalten.
Diese Entfernung ist endgültig, kein Papierkorb mit Wiederherstellungsfunktion.

## Parallelität und Prozessidentität

Mutierende Aktionen verwenden einen globalen Lock; backupbezogene Aktionen
zusätzlich einen Lock pro Backup-ID. Hintergrundprozesse schreiben atomare
Task-State-Dateien mit PID und `/proc`-Startzeit. Stoppen signalisiert nur den
zu dieser Identität gehörenden Prozess beziehungsweise seine Prozessgruppe.
Der Wiederanlauf tatsächlich gestoppter Dienste und Container wird protokolliert
und bei Fehler oder Abbruch erneut geprüft.

Das lokale Root-Journal wird **vor** dem Stoppen eines ausgewählten, zuvor laufenden
Dienstes synchronisiert. Eine fehlende Backup-Festplatte kann es nicht entfernen.
Offene Einträge bleiben bei Neustartfehlern erhalten; Boot- und periodische Retries
beachten aktuelle Prozessidentität und Operationslock. Ein verspäteter Stop verändert
einen bereits finalisierten Backup-/Taskzustand nicht nachträglich in `stopped`.

## Import- und Webschutz

Alle POST-Formulare verwenden einen stündlich rotierenden HMAC-CSRF-Token und
prüfen, falls vorhanden, den `Origin`-Header. Konfigurations- und Backup-Uploads
werden gestreamt und begrenzt; Teildateien werden entfernt.
Der neue Parser-Vorlauf prüft Anfragegrösse und Platz vor `CGI->new`. Die Oberfläche
erneuert ihre Tokens vor Aktionen; ein fehlgeschlagener Speichervorgang darf den
bearbeiteten Entwurf nicht löschen. Webserver-Requestlimits und ausreichend freier
Upload-Tempplatz sind zusätzlich auf dem tatsächlichen LoxBerry zu prüfen.

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
Importierte Erfolgsmeldungen allein gelten nicht als Nachweis: Profil/Format,
Manifest-Schema, tatsächlich vorhandene Systemdaten, Dateizahl und Archivlesbarkeit
werden lokal erneut geprüft. Kleine oder alte unvollständig beschriebene Datenbestände
erhalten einen eingeschränkten Status. Die generierte Prüfsummen-Sidecar wird
atomar ersetzt und darf kein Symlink oder Hardlink auf eine andere Datei sein.
Ein lokal plausibles Importarchiv beweist noch keine vollständige Originaltreue.

Export- und Logdownloads lesen root-eigene Dateien über die begrenzte Backendaktion.
Die Dateirechte werden dafür nicht aufgeweicht. Bei Exporten werden Inhalt und
Manifest-Bezug vor den Download-Headern geprüft und derselbe offene Dateideskriptor
für die Ausgabe verwendet. Lang laufende Exportdownloads halten den passenden
Leselock. Logdownloads lesen den geöffneten Protokolldeskriptor, ohne das laufende
Backup zu sperren.

## Restore-Grenzen

Restore setzt Root-Freigabe, registriertes Ziel, Marker, exakte Manifest-ID und
eine gültige Kombination aus Abschluss- und Validierungsstatus voraus.
Degradierte Backups benötigen eine zusätzliche ausdrückliche Bestätigung.
Portable Archive benötigt `HOSTBACKUP_OFFLINE_RESTORE=1` und ist nicht aus der
Weboberfläche startbar. Die Weboberfläche verlangt zusätzlich die vollständige
Backup-ID als Challenge.

Die im Backup gespeicherten Ausschlüsse bleiben bei rsync `--delete` und bei der
tar-Auswahl wirksam. Fehlende/unsichere Ausschlussinformationen blockieren den Restore.
Unbekannte Mount-Zuordnungen werden nicht automatisch überschrieben. Der Anwender
muss separate aufgezeichnete Volumes ausdrücklich sicheren Zielen zuordnen und
die Auslassungen in der echten Vorschau kontrollieren. Vor erfolgreicher Vorschau
werden keine Dienste angehalten. Portable Restore benötigt ein Offline-Ziel ungleich `/`.

Einzeldatei-Restore schreibt ausschliesslich in einen neuen, geschützten Unterordner
eines geprüften Alternativziels. Vorhandene Benutzerdateien werden nicht überschrieben.
Prüfsummenbasen und Berichte gehören in lokalen Root-Status; eine neu aufgezeichnete
Basis ist keine rückwirkende Inhaltsprüfung und kein Beleg eines bootfähigen Restores.
Manuell dokumentierte Restoretests sind persönliche Benutzerangaben, separat an
Ziel-/Backupidentität und Manifest-Prüfsumme gebunden. Sie ändern keine
Restore-Freigabe und werden nicht aus importierten Archiven als vertrauenswürdige
Bestätigung übernommen. Ihre Notizen erscheinen im bewusst exportierten Prüfbericht,
aber nicht automatisch im Diagnosepaket.

Ein Dateibackup ersetzt kein Blockdevice-Image. Bootloader, Partitionstabellen,
Kernel-/Firmware-Kompatibilität und applikationskonsistente Datenbank-Backups
bleiben ausserhalb dieser Sicherheitsgarantie.

## Sicherheitsmeldungen

Bitte Schwachstellen nicht mit produktiven Backup-Daten in einem öffentlichen
Issue dokumentieren. Melde reproduzierbare Details zunächst vertraulich an die
im Repository angegebene Kontaktadresse und nenne Version, Ziel-Dateisystem,
relevante Logzeilen und ein minimales Reproduktionsszenario.
