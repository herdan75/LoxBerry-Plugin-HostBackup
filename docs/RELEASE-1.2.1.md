# LoxBerry Host Backup 1.2.1-beta

**Vorabversion vom 07.10.2026.** Programm- und Paketversion: `1.2.1`.
GitHub-Tag: `v1.2.1-beta`. Der stabile Kanal und `main` bleiben bei 1.2.0.

[**LoxBerryHostBackup_1.2.1.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.1-beta/LoxBerryHostBackup_1.2.1.zip)

Das öffentliche ZIP ohne GitHub-Anmeldung herunterladen und direkt in der
LoxBerry-Pluginverwaltung installieren. Nicht entpacken und nicht vorher
deinstallieren. Für die automatische Updateerkennung Vorabversionen zulassen.
Der Vorabkanal wird erst nach erfolgreicher Tag-Pipeline und Prüfung des
öffentlichen Downloads auf diese Version umgestellt. Eine Wiki-Änderung allein
aktiviert kein Update; die normalen Einstellungen für automatische Installation
gelten weiterhin.

LoxBerry zeigt die numerische Version **1.2.1** an. Von 1.2.0 ist dies ein
Versionssprung. Bereits installierte develop-Testpakete mit interner Version
1.2.1 erhalten durch den Beta-Tag kein höheres automatisches Update-Angebot;
bei Bedarf das öffentliche Beta-ZIP manuell darüber installieren.

## Anlass und Korrektur

Frank meldete auf Raspberry Pi 5, DietPi/Debian 13, LoxBerry 4.0.0.13 und
Host Backup 1.2.0 ein Synology-Ziel mit nicht auswertbarer Inode-Statistik.
Die Quellenauswahl funktionierte. Auf dem eingeschränkten CIFS-Ziel scheiterte
die reduzierte Dateisicherung erwartungsgemäss an Linux-Metadaten; der portable
Vollbackup-Roundtrip bestand. Danach blockierte die gemeinsame Vorprüfung
fälschlich wegen null freien Inodes bei gleichzeitig null Gesamt-Inodes.

Die Korrektur wertet Gesamtzahl und freie Inodes gemeinsam aus:

| Statistik | Behandlung |
| --- | --- |
| Positive bekannte Gesamtzahl, null frei | Weiterhin Startabbruch |
| Positive bekannte Gesamtzahl, freie vorhanden | Kein Inode-Abbruch |
| Gesamtzahl null, unbekannt oder nicht auswertbar | Nicht ermittelbar; kein Abbruch allein deswegen |
| Abfrage fehlgeschlagen oder widersprüchliche Werte | Verständlicher Diagnosehinweis; keine erfundene Kapazität |

Die Regel gilt unabhängig von NAS-Hersteller, Client-Dateisystem und
Sicherungsverfahren. Es gibt keine pauschale CIFS-/NFS-Ausnahme.
Schreibzugriff, Zielidentität, Quellenauswahl, Speicherplatz, Repository-Bereitschaft
und Metadaten bleiben separate Prüfungen. Echte Schreibfehler werden nicht
ignoriert. Eine unbekannte Inodezahl ist keine Garantie für ausreichend Platz,
verfügbare Metadatenkapazität oder eine ausreichende Benutzer-/Freigabequota.

Bei festen CIFS-Eigentümern und Rechten bleibt Portable Sicherung der passende
Ansatz. Die Metadaten-Anforderungen der reduzierten Dateisicherung werden nicht
abgeschwächt. Keine automatische Änderung vorhandener Einstellungen und kein
zusätzlicher Sicherungsmodus.

## Automatisierte Nachweise

Der Status gilt immer für den exakten Commit des jeweiligen CI-Laufs, nicht
pauschal für einen Branch. Folgende Prüfungen sind Bestandteil des Testumfangs:

- Isolierte echte Vorprüfungsfunktionen mit unterschiedlichen Inode-Statistiken,
  einschliesslich unbekannter Angaben und weiterhin blockierender Pflichtfehler.
- Gemeinsame Vorprüfung auf einem tatsächlich eingebundenen, eingeschränkten
  CIFS-Testziel im kurzlebigen Linux-Testsystem, nicht auf einem produktiven NAS.
- Unveränderte Tests für lokale und Netzwerk-Quellenauswahl, Schutz des Backup-Ziels,
  Metadaten-Roundtrip sowie portable Vollbackups und Repository-Folgesicherungen.
- Linux-Tests für Installation, privilegierte Einstiegspunkte, Dienst-Wiederanlauf,
  Export/Import und Wiederherstellung in isolierte Testverzeichnisse.
- Browser-/CGI-Regressionen, Shell-/Python-/Perl-/PHP-Prüfungen und Audit des
  gepackten ZIPs mit den checksum-geprüften portablen Laufzeitdateien.
- Versionsprüfung: Paket 1.2.1, Vorabfeed für v1.2.1-beta, stabiler Feed weiter
  1.2.0 und unveränderte Kanaladressen. Ein develop-Push darf kein Release erzeugen.

Die Tag-Pipeline muss vollständig bestehen, bevor ihr Release-Schritt das
installierbare ZIP veröffentlicht. Danach werden der öffentliche Download und
seine Zuordnung zum getaggten Commit separat geprüft. Erst anschliessend wird
`develop` auf den geprüften Stand nachgeführt und damit der Vorabfeed aktiviert.
Ein erfolgreicher Windows-Teiltest ersetzt keine Linux-/CIFS-Integration.
Es werden keine Tests gegen Franks laufendes System und keine Dienste seines
Systems ausgeführt.

### Bereits geprüfte Entwicklungsbasis

Der erfolgreiche [CI-Lauf 37524709004](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/37524709004)
belegt exakt Commit `faac7055451d80cc33924b0b42332abc2d52a2e2` vom 06.10.2026:

- 381 Tests der Linux-Hauptsuite ohne Fehler; sieben bedingt ausgelassene Tests
  wurden in den anschliessenden Pflicht-Spezialschritten tatsächlich ausgeführt.
- 15 zusätzliche Downloadtests als unprivilegierter Benutzer.
- Je 29 Repository- und 18 Portable-Recovery-Tests lokal und erneut auf CIFS.
- Sechs zusätzliche CIFS-Vorprüfungstests, darunter vier echte Integrationsfälle.
- 35 Browserprüfungen, ShellCheck, visudo, PHP sowie ZIP-Bau und acht Paketaudits.
- 68 gezielte Inode-Regressionsfälle innerhalb von sechs Testmethoden; diese
  Unterfälle sind nicht als weitere unabhängige Gesamtsuite zu addieren.

Der echte Netzwerk-Test verwendet einen kurzlebigen Samba-/CIFS-Mount mit
SMB 3.0, forceuid/forcegid und festen Rechten. Portable Vollsicherung und
Repository-Stände bestehen dort mit realer 0/0-Statistik die Vorprüfung;
unpassende reduzierte Metadaten und bekannte Inode-Erschöpfung blockieren weiter.
Dienst-Ablauftests verwenden kontrollierte Stellvertreter, keine produktiven Dienste.

Die Veröffentlichungsvorbereitung ändert gegenüber `faac705` keine
Backup-/Restore-Programmlogik. Der neue Tag-Lauf und die Prüfung des öffentlichen
ZIPs sind dennoch eigene Nachweise. Deren konkrete Laufadresse, Paketgrösse und
SHA-256 werden nach Abschluss in den
[öffentlichen Release Notes](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.1-beta)
ergänzt. Die Prüfsumme des älteren develop-Artefakts gilt nicht für dieses Release-ZIP.

## Grenzen und Praxisabnahme

Die direkte Freigabe auf Franks Synology DS925+ mit CIFS/SMB 3.1.1 und sein
NFS-4.1-Ziel müssen nach Installation dieses Teststands erneut geprüft werden.
Ein lokaler Samba-Test ist kein Test dieser konkreten DSM-/NFS-Konfiguration.
Sein erfolgreicher 1.2.0-Lauf über ein ext4-Loop-Image belegt weder den direkten
NAS-Pfad noch einen vollständigen bootfähigen System-Restore.

Empfohlene Praxisabnahme, ohne bestehende Sicherungen zu löschen:

1. Einstellungen exportieren, laufende Aufgaben beenden lassen und das Beta-ZIP
   ohne vorherige Deinstallation installieren. Angezeigte Version 1.2.1 prüfen.
2. Das direkt eingebundene NAS-Ziel und die gewünschte Quellenauswahl speichern.
   Das ext4-Loop-Image für diesen direkten NAS-Test nicht als Ziel verwenden.
3. Bei Portable Sicherung mit Vollbackup die Vorprüfung ausführen. Unbekannte
   Inode-Kapazität muss als solche erscheinen, andere Pflichtprüfungen müssen
   bestehen. Keine Metadatenfehler umgehen.
4. Ein manuelles Backup abschliessen lassen; Status, Prüfbericht und Wiederanlauf
   der zuvor gestoppten Dienste/Container kontrollieren. Bei gewünschtem Export
   auch dessen erfolgreichen Abschluss und Lesbarkeit prüfen.
5. Für portable Sicherungsstände das Repository und den extern aufbewahrten
   Wiederherstellungsschlüssel einrichten, Zusatzexport deaktivieren, speichern
   und einen zweiten Lauf mit kleinen Änderungen prüfen. Ein TAR-Vollbackup wird
   nicht automatisch zu einem inkrementellen Repository konvertiert.
6. Dateiinhalte und Metadaten in eine getrennte Linux-Testumgebung wiederherstellen.
   Einen vollständigen System-Restore nur in einer geeigneten Rescue-/Testumgebung
   gemäss [DR-Testplan](DR-TESTPLAN.md) durchführen.

## Technische Grundlagen

- [Btrfs: dynamisch angelegte Inodes](https://btrfs.readthedocs.io/en/latest/ch-fs-limits.html)
- [Linux statfs: undefinierte Felder können null sein](https://man7.org/linux/man-pages/man2/statfs.2.html)
- [Linux CIFS: Initialisierung der Inode-Statistik](https://github.com/torvalds/linux/blob/master/fs/smb/client/cifsfs.c)
