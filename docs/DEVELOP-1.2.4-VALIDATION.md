# Entwicklungsstand 1.2.4 – Umfang und Prüfnachweise

Stand: 20.10.2026. Nur `develop`, noch kein veröffentlichtes Release.
Stabiles Paket 1.2.0 und Vorabkanal 1.2.3-beta bleiben unverändert.

## Korrektur und Grenzen

Die Liste der tatsächlich zu kopierenden Quellen wird für alle Verfahren nach
dem vorgesehenen Dienstestopp erstellt. Nur reguläre flüchtige Diagnoseinhalte
unter folgenden bekannten Bereichen werden standardmässig ausgelassen:

- `$LBHOMEDIR/log/plugins`
- `$LBHOMEDIR/log/system_tmpfs`
- `$LBHOMEDIR/log/ramlog/log/plugins`
- `$LBHOMEDIR/log/ramlog/log/system_tmpfs`

Verzeichnisse und ihre Metadaten, Symlinks, Sonderdateien sowie dauerhafte
Installationsnachweise unter `log/system` bleiben normale Quellen. Es gibt keine
allgemeine Ausnahme für `.log`-Dateien, Docker-Volumes oder Datenbankdateien.
Ungewöhnliche Mounts und ausdrücklich eingeschlossene Teilquellen werden nicht
als entbehrlicher Inhalt klassifiziert. Die erweiterte Einstellung
`include_runtime_logs=true` schaltet die Auslassung aus. Ein alter Speicheraufruf
ohne diesen Parameter erhält die bestehende Einstellung.

Der neue Standard gilt auch bei Updates. Oberfläche, Kurzanleitung und
Vorprüfung erklären ihn; `source-selection.json` hält Version, Umfang, Anzahl
und begrenzte Beispiele der Auslassungen fest. Alte Backups werden nicht neu
bewertet. Die ältere, dateinamensabhängige rsync-Ausnahme wird im neuen
Kopierablauf nicht mehr verwendet.

Die Mount-Prüfung verwendet unveränderliche lokale Quellengrenzen. Sie ignoriert
nur Änderungen ausserhalb des gesicherten Umfangs. Verlust, Ersatz oder
Überdeckung einer ausgewählten Quelle und ihrer notwendigen Zugriffswege
bleiben Fehler. `source-verification.json` und `copy-result.json` trennen
Kopierergebnis und Mount-Prüfung. Der letzte vollständig geprüfte Stand je
Host-/Formatlinie bleibt vor automatischer Verdrängung durch neuere Stände
mit Hinweisen geschützt.

Das behebt die Klasse rotierender Diagnoseinhalte und irrelevanter
Mount-Änderungen, nicht jede mögliche Änderung an aktiven Nutzdaten.
Insbesondere kann ein Anwendungs-Watchdog einen absichtlich gestoppten
Container neu erstellen. Dafür bleibt ein abgestimmter Anwendungsstopp oder
Vor-/Nach-Skript nötig. Ein Dateibackup einer schreibenden Datenbank ist
nicht automatisch anwendungskonsistent.

Abgleich mit Primärquellen: LoxBerrys
[RAM-Log-Einrichtung](https://github.com/mschlenstedt/Loxberry/blob/master/sbin/createtmpfsfoldersinit.sh)
verwendet RAM-Speicher und Bind-Mounts für diese Bereiche. Die Auswahl behandelt
nur nachweislich passende Einbindungen als verwaltet. Die
[Borg-Fehlerbehandlung](https://borgbackup.readthedocs.io/en/stable/usage/create.html#error-handling)
und [Restic-Rückgabecodes](https://restic.readthedocs.io/en/stable/040_backup.html#exit-status-codes)
sind Vergleichspunkte, keine Zusicherung identischer Semantik. Wichtige
Lesefehler werden nicht durch ein globales „ignore failed read“ verdeckt.

## Prüfplan

- Bestehende Python-, Shell-, Perl-/CGI-, JavaScript- und Browserprüfungen.
- Neue Policy- und Quellenprüfungen: Legacy-Konfiguration, ausdrückliche Auswahl,
  Symlinks, unbekannte Mounts, wichtige Dateien, begrenzte und private Nachweise.
- Reale GNU-TAR-, rsync- und gepinnte Restic-Läufe mit gleichzeitigem Erstellen,
  Ändern, Rotieren und Entfernen von Diagnoseprotokollen.
- Wiederherstellung der Testdaten einschliesslich UID/GID, Modus, ACL, xattr,
  File Capabilities, Links und Sparse-Dateien; inkrementelle Wiederverwendung.
- Wichtige fehlende Dateien bleiben Fehler; keine erfolgreiche Veröffentlichung
  eines unvollständigen Repository-Kandidaten.
- Acht isolierte Linux-Mount-Namensraumfälle für tolerierte ausgeschlossene und
  abgewiesene ausgewählte/ersetzte/überdeckte Quellen.
- Bestehende Linux-Root-Tests für Installation, Upgrade über blockierte ältere
  Installationen, Dienst-/Container-Wiederanlauf, Abbruch und Deinstallation.
- Bestehende echte CIFS-Qualifikation und Plugin-ZIP-Paketprüfung in GitHub CI.

Die zusätzlichen Linux-Tests sind bei ausdrücklicher Aktivierung verpflichtend:
Fehlende Werkzeuge oder Namespace-Rechte sind Fehler, keine stillen Skips.
Windows führt die portablen Tests aus; Linux-/Root-Prüfungen laufen in CI.

## Ergebnisse

Die konkreten lokalen und GitHub-Ergebnisse werden nach Abschluss ergänzt.
Eine erfolgreiche Simulation oder Pipeline ersetzt keinen vollständigen
System-Restore auf einem Raspberry Pi und keinen Praxistest auf einem konkreten
Synology-/QNAP-Gerät. Die Datei behauptet keine solche Hardware-Abnahme.
