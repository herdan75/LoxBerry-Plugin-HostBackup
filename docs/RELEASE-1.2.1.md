# LoxBerry Host Backup 1.2.1

**Noch nicht veröffentlicht.** Fehlerkorrektur auf `develop`, vorbereitet am
06.10.2026. Programm- und Paketversion: `1.2.1`.
Installationspaket: `LoxBerryHostBackup_1.2.1.zip` aus dem erfolgreichen
GitHub-Actions-Lauf des gewünschten develop-Commits.
`main`, Release-Tags und beide öffentlichen Plugin-Updatekanäle bleiben bei 1.2.0.

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
- Versionsprüfung: internes Testpaket 1.2.1; beide veröffentlichten Updatefeeds
  weiterhin 1.2.0. Ein develop-Push darf kein Release erzeugen.

Der erfolgreiche Workflow liefert das installierbare ZIP als Artefakt.
Ein erfolgreicher Windows-Teiltest ersetzt keine Linux-/CIFS-Integration.
Es werden keine Tests gegen Franks laufendes System und keine Dienste seines
Systems ausgeführt.

## Grenzen und Praxisabnahme

Die direkte Freigabe auf Franks Synology DS925+ mit CIFS/SMB 3.1.1 und sein
NFS-4.1-Ziel müssen nach Installation dieses Teststands erneut geprüft werden.
Ein lokaler Samba-Test ist kein Test dieser konkreten DSM-/NFS-Konfiguration.
Sein erfolgreicher 1.2.0-Lauf über ein ext4-Loop-Image belegt weder den direkten
NAS-Pfad noch einen vollständigen bootfähigen System-Restore.

Empfohlene Praxisabnahme, ohne bestehende Sicherungen zu löschen:

1. Einstellungen exportieren, laufende Aufgaben beenden lassen und das Test-ZIP
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
