# Sicherheitsmodell

## Entwicklungsstand 1.2.3: Journal-Identitäten und Stop-Auswahl

Noch nicht veröffentlicht; der Vorabkanal bleibt auf 1.2.2-beta, der stabile
Kanal auf 1.2.0. Dieser Stand bündelt die nachfolgenden Docker-/Dienstkorrekturen
mit der durchgängigen Prüfung konkreter systemd-Dienstnamen. Unterstützt werden
ASCII-Buchstaben/Ziffern, `:`, `-`, `_`, Punkte und wörtliche Backslashes, auch
`\xHH`-Schreibweisen. Der Präfix vor dem ersten `@` und ein vorhandener Instanzteil
müssen nicht leer sein; weitere `@` im Instanzteil sind zulässig. Einschliesslich
`.service` gilt die Grenze von 255 Zeichen. Zulässige führende Satzzeichen ändern
diese Namensprüfung nicht; ein syntaktisch gültiger Name belegt noch keinen
vorhandenen, geladenen oder sicher stoppbaren Dienst.

Namen bleiben in Auswahl, JSON-Journal und Kommandoargumenten unverändert, ohne
Unescaping oder Shell-Auswertung. `systemctl --` begrenzt die Optionen auch bei
führendem `-`. Leere Templates, Leer-/Steuerzeichen, Globs, `/` und Shell-
Sonderzeichen werden abgewiesen. Der Zeichenumfang und die Instanzbehandlung
orientieren sich an [systemd.unit](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
und den Funktionen `unit_name_is_valid`/`unit_instance_is_valid` in
[systemd v257: unit-name.c](https://github.com/systemd/systemd/blob/v257/src/basic/unit-name.c).
Die Prüfung gespeicherter Stop-Ziele erfolgt vor dem ersten Stopp, sodass eine
ungültige Auswahl nicht erst nach bereits gestoppten Diensten auffällt.
Ungültige Namen und unsichere Journalpfade bleiben abgewiesen; Schutzliste,
Operationssperre und protokollierter Wiederanlauf werden nicht abgeschwächt.
Eine höhere Entwicklungspaketversion schaltet weder einen Download noch einen
öffentlichen Updatekanal frei. Vorhandene Installationen sollen aktualisiert,
nicht zuvor deinstalliert werden; laufende Vorgänge bleiben geschützt.

## Unveröffentlichte Ergänzung: Dienstempfehlungen und Aliase, 19.10.2026

Eine Empfehlung ist keine Stop-Berechtigung. Allgemeine Begriffe wie `db` werden
nicht mehr innerhalb von `dbus` erkannt; die Zuordnung verwendet den tatsächlichen
systemd-Namen. Mehrere Aliase bilden einen Listeneintrag, ohne gespeicherte
Auswahlen zu verlieren. Avahi, ModemManager und D-Bus einschliesslich
`dbus-broker` und bekannter Aliase gehören zu den geschützten Diensten.

Vor einem Stopp löst das Backend den tatsächlichen Namen und die gemeldeten
Aliase erneut auf und prüft den Schutz. Alte gespeicherte Auswahlen geschützter
Dienste werden protokolliert übersprungen, nicht aus der Konfiguration gelöscht;
kein Stopp und kein Wiederanlauf-Journal werden dafür erzeugt. Ungültige oder
nicht sicher auflösbare Identitäten rechtfertigen keinen Stopp. Echte Stop-Fehler
erlaubter Dienste blockieren weiterhin und erscheinen mit Rückgabecode im Log.
Bereits offene Wiederanlauf-Aufträge werden nicht verändert. Dienstdateien
bleiben gemäss bestehender Quellenauswahl gesichert: Stop-Schutz ist kein
Backup-Ausschluss. Keine neuen Einstellungen, Berechtigungen oder Updatekanäle;
diese Ergänzung ist noch nicht veröffentlicht.

## Unveröffentlichte Ergänzung: Docker-Wiederanlauf, 18.10.2026

Der Entwicklungsstand behandelt bestätigte Alt-IDs automatisch, erweitert aber
keine privilegierte Startbefugnis: Eine fehlgeschlagene Docker-Abfrage allein
beweist keine Löschung. Nur eine ausdrückliche Meldung über eine fehlende
Container-ID zusammen mit einer erfolgreichen vollständigen Inventur darf einen
Docker-Eintrag eines inaktiven Vorgangs als `missing` abschliessen. Fehler des
Daemons, der Berechtigungen oder der Abfrage bleiben offen. systemd-Einträge
werden nicht auf diese Weise abgeschlossen.

Neue Journale speichern vollständige IDs und Namen. Die Namen dienen nur der
Dokumentation, nicht dem automatischen Start eines Ersatzcontainers; ältere
kurze IDs bleiben abgleichbar. Während eines aktiven Backups/Restores führt ein
fehlgeschlagener Wiederanlauf weiterhin zuerst zum Fehlerzustand. Automatische
Bereinigung darf keinen erfolgreichen Backup-/Restore-Abschluss vortäuschen.

Davon getrennt ist eine gespeicherte Stop-Auswahl für ein **neues** Backup:
Nach abgeschlossenem Vorgängerbackup wird ein neu erstellter Container über
seine aktuell beobachtete vollständige ID erfasst. Ein inzwischen gelöschter
Name darf nur nach ausdrücklicher Fehlmeldung und einer unabhängigen, gültigen
vollständigen Namensinventur übersprungen werden. Die Auswahl bleibt gespeichert;
Daemon-, Berechtigungs- und Abfragefehler werden nicht als Löschung interpretiert.
Diese Ausnahme berechtigt niemals den Wiederanlauf einer alten ID, einen
gleichnamigen Ersatzcontainer zu starten.

Sobald keine tatsächlich offenen Wiederanläufe verbleiben, wird ein Journal mit
fehlenden Containern atomar in einem eigenen Verzeichnis unter
`ROOT_STATE_DIR/recovery-history/`
archiviert; der Task bleibt als fehlgeschlagen mit eigenem Hinweis sichtbar.
Die root-geschützte Historie behält das gesamte Journal einschliesslich möglicher
Repository-Kontrolldaten. Wiederholte Vorgangsnamen erhalten neue Archivziele;
vorhandene Historie wird nicht überschrieben. Unsichere Pfade und Fehler beim
Sichern der Historie bleiben Fehler; sie rechtfertigen kein Löschen der Belege.
Archivierte Alt-IDs blockieren danach keine neuen Backups oder Deinstallationen.
Tatsächlich offene Wiederanläufe und aktive Vorgänge behalten ihren Schutz.
Die Historie wird erst bei bewusster Deinstallation mit den lokalen Laufzeitdaten
entfernt, nicht durch die normale Wiederanlauf- oder Backup-Aufbewahrung.

Eine im geschützten Journal gespeicherte Fehlersignatur begrenzt nur die
automatische Cron-Ausgabe: erster/geänderter Fehler sowie gleiche Erinnerung
nach frühestens 24 Stunden. Startversuche und Logs bleiben im Fünfminutentakt,
manuelle Aufrufe zeigen immer ihr Ergebnis. Keine neue Benutzeroption, kein
pauschales Abschalten der Wiederherstellung und keine Änderung der Backup-Mails.
Diese Ergänzung gehört noch nicht zum veröffentlichten 1.2.2-beta-Paket.

## Aktuelle Ergänzung: 1.2.2-beta vom 15.10.2026

Die Dienst-/Container-Ermittlung verwendet gebündelte systemd-Abfragen mit
begrenzter Laufzeit. Fehlgeschlagene oder unvollständige Antworten werden nicht
als erfolgreiche leere Auswahl gespeichert. Gespeicherte und noch nicht
gespeicherte Auswahlen bleiben erhalten; geschützte Systemdienste bleiben
ausgeschlossen. Das längere Browser-Zeitlimit erweitert keine Berechtigungen.

Gespeicherte Abschlussprüfungen werden als begrenzter, HTML-geschützter Text
angezeigt und bleiben von Dateiinhaltsprüfung und Restore-Nachweisen getrennt.
Das Schliessen einer Ansicht beendet keinen Hintergrundvorgang und löst weder
einen Stop noch eine Schreibaktion aus. Verspätete Antworten dürfen bewusst
geschlossene Ansichten nicht automatisch wieder öffnen.

Öffentliche Backup-/Restore-Vorprüfungen und die Backup-Vorschau erwerben vor
Ziel- und Repository-Arbeiten eine nicht wartende gemeinsame Vorgangssperre.
Eine aktive exklusive Backup-/Restore-/Wartungssperre führt zum Belegt-Hinweis,
nicht zu parallelen Metadatenproben. Interne Vorprüfungen unter der bereits
gehaltenen exklusiven Worker-Sperre bleiben unverändert. Leichte Anzeigen
werden nicht pauschal gesperrt; vorhandene Einzelbackup-Sperren bleiben wirksam.

Fehlende Inhaltsberichte sind kein Prüfnachweis. Unlesbare, beschädigte,
falsch zugeordnete oder widersprüchliche Berichte werden ohne Überschreiben der
Datei oder Vergleichsbasis als Fehler dargestellt. Ein veralteter Bericht darf
aktuelle Inhalte nicht als geprüft bestätigen. Ziel-, Manifest-, Root-State-
und Historien-Sicherheitsfehler bleiben blockierend; verständliche JSON-Fehler
und HTTP 409 bei Sperrkonflikten umgehen keine Backend-Prüfung.

Freigabeumfang und tatsächliche Testnachweise:
[Release Notes 1.2.2-beta](RELEASE-1.2.2.md). Reale NAS-/USB-Einbindungen,
produktive Dienste und ein bootfähiger System-Restore bleiben eigene Abnahmen.

## Historische Ergänzungen

Ergänzung für **1.2.1-beta vom 07.10.2026**: Eine unbekannte Inode-Kapazität
ist kein Beleg für Erschöpfung. Die gemeinsame Vorprüfung wertet Gesamtzahl
und freie Inodes zusammen aus; bekannte Erschöpfung bleibt fatal. Zielidentität,
Schreibzugriff, Metadaten, Quellenauswahl, Speicherplatz und Repository-Freigaben
werden nicht abgeschwächt. Keine zusätzlichen Rechte oder Sicherungsmodi.
Prüfumfang und Grenzen: [Release Notes 1.2.1-beta](RELEASE-1.2.1.md).

Historischer Stand: reguläres Release 1.2.0 vom 04.10.2026. Das Sicherheitsmodell der
übernommenen Beta-Basis `af2d55d` bleibt unverändert; die stabile Freigabe
erweitert weder Berechtigungen noch Restore-Zusagen. Freigabestatus und
Prüfgrenzen: [Release Notes](RELEASE-1.2.0.md).
Enthalten sind der unprivilegierte Dateiaustausch auch bei Neuinstallation mit
Restdateien und die unveränderte Launcher-/Backend-Trennung.
Die kompakte Übersicht veränderte keine Berechtigungen, Locks oder
Bestätigungsanforderungen. Die damals noch offene HTTP-500-Darstellung bei
gesperrter Laufzeitprüfung war kein Anlass, den Sperrschutz abzuschalten; siehe
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

Vor dem Austausch sichert PREROOT zuerst die Konfiguration dauerhaft in einem
geschützten, installationsübergreifend wiederauffindbaren Verzeichnis unter
`/var/lib/loxberryhostbackup-install-recovery`. Die Sicherung bleibt auch bei
Abbruch, einer neuen Installations-ID oder Neustart erhalten und wird erst nach
erfolgreichem Abschluss entfernt. Die gesicherte alte Konfigurationsdatei und die genau
validierte veraltete Plugin-Programmkopie werden vor dem Plattform-Kopieren
entfernt. So ist kein Upgrade-Purge erforderlich, der bei einer als neu erkannten
Installation ausbleibt. Symlink-Pfadkomponenten und eingebundene Mounts werden
abgewiesen; die Bereinigung verwendet verankerte Verzeichnisdeskriptoren und
folgt keinen Links. Dateibesitzer ausführbarer
Helfer und geschützte Helferstände ausserhalb dieses Baums werden nicht geändert.
Die eigentlichen Backup-Ziele und dauerhaften Laufzeitdaten sind keine
PREROOT-Bereinigungsziele. POSTROOT stellt die gesicherte Konfiguration wieder her
und schützt den neuen Bin-Baum wieder
während der Übernahme. Eine Backend-Kennungsprüfung vor dem Umschalten von
`current` verhindert, dass ein alter Weiterleitungs-Launcher als Backend
veröffentlicht wird. Dieselbe Prüfung im Root-Einstieg verhindert rekursive
Starts auch bei einem bereits falsch gesetzten Programmverweis. Sie ist eine
Strukturprüfung, keine kryptografische Echtheitsprüfung des Installationspakets.
Eine fehlgeschlagene Sicherheitsvorbereitung liefert einen fatalen Hook-Status,
damit LoxBerry nicht mit einem unsicheren Dateiaustausch fortfährt. Bei einer
Deinstallation wird vor der Entfernung privilegierter Helfer auf aktive Vorgänge
und vorhandene Wiederanlaufjournale geprüft. Geschützte Reste der vorgesehenen
Plugin-Bäume werden vor der nachfolgenden Plattformbereinigung entfernt;
externe Symlink-Ziele und ausführbare Datei-Inodes werden nicht umgewidmet.
Die bestehende Operationssperrdatei wird nicht gelöscht, um parallele unabhängige
Sperr-Inodes zu vermeiden. Ein konfiguriertes Backup-Ziel innerhalb eines
Deinstallationsbaums blockiert die Deinstallation.

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

Das Verfahren „Metadaten in Dateiattributen speichern“ (bisher Fake Super)
verwendet für die getrennte Behandlung von Sender und Empfänger
einen festen lokalen rsync-Transport. Der Shellcode ist konstant, führt kein
`eval` aus und stellt keine SSH-/Netzwerkverbindung her; Zielpfade werden nicht
in ausführbaren Shelltext eingesetzt. Geschützte rsync-Argumentübertragung
bewahrt Leerzeichen und Sonderzeichen in Pfaden. Diese Umgehung betrifft den
[bekannten lokalen rsync-Fehler #505](https://github.com/RsyncProject/rsync/issues/505);
Linux-Dateisicherung und Dateisicherung mit reduzierten Metadaten behalten ihren lokalen Kopierweg.

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
Portable Sicherung benötigt `HOSTBACKUP_OFFLINE_RESTORE=1` und ist nicht aus der
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

## Portable Repository-Schlüssel

Die Repository-Einrichtung erfolgt ausdrücklich und getrennt vom normalen
Konfigurationsspeichern. `repository-status` liefert nur freigegebene öffentliche
Statusfelder. `repository-init`, `repository-key-export` und
`repository-confirm-key` verlangen POST, gültiges CSRF und die gespeicherte
Root-Freigabe. Der sudo-Dispatcher erlaubt diesen Aktionen keine zusätzlichen
Argumente und keinen vom Webbenutzer vorgegebenen Engine-Befehl.

Nur der explizite Schlüsseldownload darf geheime Recovery-Daten ausgeben:
als JSON-Attachment mit `Cache-Control: no-store`, nicht als UI-Bericht. Fehler
spiegeln keine teilweise ausgegebene Schlüsseldatei zurück. Eine separate
Bestätigung der sicheren Aufbewahrung ausserhalb des Hosts ist erforderlich;
der Browser liefert keinen beliebigen Bestätigungshash. Backend-seitig muss die
Bestätigung an die zuletzt exportierte Datei und die Repository-Identität gebunden
sein. Die gespeicherte Plugin-Konfiguration und Diagnosepakete enthalten keinen
Repository-Schlüssel.

Portable Sicherungsstände werden nur freigegeben, wenn verfügbare Engine,
Repository-Initialisierung und Schlüsselbestätigung am gespeicherten Ziel
vorliegen. Sowohl CGI als auch Backend prüfen die Voraussetzungen; der Browser
darf nicht allein über die Freigabe entscheiden. Ein automatischer tar.gz-Export
wird als inkompatible gespeicherte Einstellung abgelehnt, nicht still deaktiviert.
Die gemeinsame Datenbasis wird nicht durch Export oder Verschieben eines einzelnen
Standordners transportierbar. Direkter Online-Restore und generischer Einzeldatei-
Restore sind dafür nicht verfügbar. Offline-Recovery benötigt den authentifizierten
Stand und geeigneten leeren Linux-Zwischenspeicher mit vollständigem Platzbedarf
plus Reserve. Fremde Metadaten oder ein richtiger Schlüssel allein belegen keine
passende Architektur, Bootfähigkeit oder Anwendungskonsistenz.

Quellenauswahl, Ausschlüsse, Validierung und Manifest bleiben bis zur
authentifizierten Veröffentlichung in privaten Root-Kontrolldateien. Der
Commit übernimmt keine vom beschreibbaren NAS zurückgelesenen Kontrollen.
Erst nach erfolgreichem Commit werden dessen genaue Kontrollbytes als Cache
auf das NAS übertragen; das abgeschlossene Manifest folgt zuletzt. Spätere
Abweichungen zwischen Cache und authentifiziertem Beleg blockieren Verwaltung
und Wiederherstellung. Bei Abbruch der Cache-Veröffentlichung kann ein gültiger
Commit vorhanden sein: nicht manuell löschen, sondern die authentifizierte
Repository-Liste und den Offline-Recovery-Weg verwenden.

## Sicherheitsmeldungen

Bitte Schwachstellen nicht mit produktiven Backup-Daten in einem öffentlichen
Issue dokumentieren. Melde reproduzierbare Details zunächst vertraulich an die
im Repository angegebene Kontaktadresse und nenne Version, Ziel-Dateisystem,
relevante Logzeilen und ein minimales Reproduktionsszenario.
