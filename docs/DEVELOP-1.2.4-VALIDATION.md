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
Die Einordnung stützt sich auf den dokumentierten Zweck dieser Logbereiche,
nicht auf eine inhaltliche Analyse jeder Datei. Falls ein fremdes Plugin dort
entgegen dieser Konvention dauerhafte Nutzdaten ablegt, muss die ausdrückliche
Mitsicherung aktiviert bleiben beziehungsweise dieser Teilbereich ausgewählt werden.
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
- Isolierte Linux-Mount-Namensraumfälle für tolerierte ausgeschlossene und
  abgewiesene ausgewählte/ersetzte/überdeckte Quellen.
- Bestehende Linux-Root-Tests für Installation, Upgrade über blockierte ältere
  Installationen, Dienst-/Container-Wiederanlauf, Abbruch und Deinstallation.
- Bestehende echte CIFS-Qualifikation und Plugin-ZIP-Paketprüfung in GitHub CI.

Die zusätzlichen Linux-Tests sind bei ausdrücklicher Aktivierung verpflichtend:
Fehlende Werkzeuge oder Namespace-Rechte sind Fehler, keine stillen Skips.
Windows führt die portablen Tests aus; Linux-/Root-Prüfungen laufen in CI.

## Internetrecherche und abgeleitete Sonderfälle

Es wurden Primärquellen mit den tatsächlichen Kopieroptionen und Prüfungen
abgeglichen. Allgemeine Erfahrungsberichte allein dienen nicht als Nachweis.

| Dokumentierter Sonderfall | Umsetzung beziehungsweise Prüfung |
| --- | --- |
| [rsync-Dateilisten](https://download.samba.org/pub/rsync/rsync.1): Führende `#` und `;` können trotz NUL-Trennung Kommentare sein; `--from0` gilt auch für Ausschlussdateien. `--dirs` erweitert den Eintrag `.` um neue Wurzeleinträge. | Explizite relative Namen erhalten `./`; rsync bekommt keinen expliziten `.`-Eintrag. Wurzelmetadaten werden separat im tatsächlichen Kopiertest geprüft. Die eingefrorene Auswahl wird nicht nochmals als anders getrennte Ausschlussliste interpretiert. Tests für Sonderzeichen, Leerzeichen, Zeilenumbrüche und erst nach der Auswahl entstandene Dateien. |
| [GNU TAR: sich ändernde beziehungsweise nicht lesbare Dateien](https://www.gnu.org/software/tar/manual/html_node/Ignore-Failed-Read.html). | Kein pauschales `--ignore-failed-read`. Relevante fehlende oder während des Lesens veränderte Daten bleiben sichtbar. Ein deterministischer Checkpoint-Test ergänzt die Rotationstests. |
| [rsync `--link-dest`](https://download.samba.org/pub/rsync/rsync.1): Wiederverwendung darf frühere Stände nicht verändern. | Zweiter Stand mit geändertem Inhalt, Modus und ACL; der erste Stand bleibt unverändert. Unveränderte Dateien werden weiterhin wiederverwendet. |
| [Restic-Dateilisten und Fehlercodes](https://restic.readthedocs.io/en/stable/040_backup.html): Direkte Pfade umgehen Ausschlüsse; Exit 3 kann einen unvollständigen Snapshot hinterlassen. | NUL-Liste, unterdrückte zusätzliche Rekursion und exakter Inventarvergleich. Kein Freigabebeleg bei Exit 1/3 oder Metadatenwarnungen; vorherige veröffentlichte Stände bleiben erhalten. |
| [Restic auf älteren Linux/CIFS-Kombinationen](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html). | Das schon vorhandene `GODEBUG=asyncpreemptoff=1` bleibt fest gesetzt und gegen Umgebungsüberschreibung getestet. Reales CIFS wird mit einem isolierten Samba-Testziel geprüft. |
| [Mount-Identität und Schichten](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html) sowie [systemd-Automounts](https://www.freedesktop.org/software/systemd/man/latest/systemd.automount.html). | Aktivierter Datenträger über einem Automount am selben Pfad ist von einer mehrdeutigen Überdeckung zu unterscheiden. Mount-ID, Elternbeziehung, Gerät und Wurzel gehören zum Abgleich. |
| [Bind-Mounts und Mount-Weitergabe](https://www.kernel.org/doc/Documentation/filesystems/sharedsubtree.txt). | Ein Mount unter einem ausgeschlossenen Pfad ist nicht automatisch harmlos, wenn er eine ausgewählte Quelle verdeckt oder dorthin weitergegeben wird. Getrennte Tests für Datei-Binds und Mount-Weitergabe. |
| [LoxBerrys konfigurierbarer RAM-Log-Pfad](https://github.com/mschlenstedt/Loxberry/blob/master/sbin/createtmpfsfoldersinit.sh). | Standardlayout mit tmpfs beziehungsweise nachgewiesenem zram wird erkannt. Unbekannte Sonderlayouts bleiben absichtlich streng; es gibt keine pauschale Freigabe beliebiger Bind-Mounts. |

Nicht-UTF-8-Dateinamen werden bei TAR und rsync bytegetreu geprüft. Das portable
Repository verlangt weiterhin UTF-8-Pfadnamen und lehnt andere Namen ausdrücklich
ab, statt sie umzubenennen oder still auszulassen. Netzwerk-, Schreib- und
Platzfehler werden zusätzlich auf Protokollebene simuliert; dies ersetzt keinen
Verbindungsausfalltest jeder NAS-/Kernel-/SMB-Kombination. Eine Strukturprüfung
ist ausserdem nicht mit einer vollständigen Datenprüfung oder einem System-Restore
gleichzusetzen ([Restic-Datenprüfung](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)).

## Ergebnisse

Bestätigter vollständiger Referenzlauf vor den zusätzlichen Internet-Sonderfällen:
[`b17f903`, GitHub-Lauf 39483556279](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/39483556279)
ist erfolgreich. Er umfasst 626 Tests im allgemeinen Linux-Lauf
(10 planmässige Skips; die separat aktivierten Integrationen folgen danach),
15 Downloads als unprivilegierter Nutzer, echte Repository-/Portable-Roundtrips,
19 neue Live-Quellen-Tests, das isolierte CIFS-Ziel, die vollständigen
Browser-Regressionen sowie acht Paketprüfungen. Syntax-, ShellCheck-,
sudoers- und PHP-Prüfungen sowie der ZIP-Build sind ebenfalls erfolgreich.

Die anschliessende Erweiterung enthält 26 verpflichtende Live-Quellen-Tests
und zusätzliche Quellen-/Repository-Regressionen für die oben dokumentierten
Sonderfälle. Lokale Windows-Prüfungen bestätigen die portablen Anteile;
Linux-spezifische Skips werden nicht als lokale Ausführungsnachweise gezählt.
Docker-Wiederanlauf (26 Tests), systemd-Stoppsicherheit (30), Laufzeitsicherheit
(42) und die drei gezielten Worker-Tests nach Anpassung der rsync-Dateiliste
sind lokal erfolgreich; die plattformabhängigen Skips sind in den Ausgaben
ausgewiesen. Auch die tatsächliche CGI-/JavaScript-Bedienung der neuen Option
wurde mit lokalem Edge geprüft.

Für jeden nachfolgenden Commit ist der
[zugehörige develop-Pipelinelauf](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/workflows/build-plugin.yml?query=branch%3Adevelop)
massgebend: Ein älterer grüner Lauf gilt nicht als Nachweis für spätere Änderungen.
Der Workflow prüft alle Linux-/CIFS-/Browser-/Paketstufen vor der Bereitstellung
des Test-ZIPs. Ein `develop`-Push veröffentlicht kein Release und ändert den
LoxBerry-Vorabkanal nicht.

Eine erfolgreiche Simulation oder Pipeline ersetzt keinen vollständigen
System-Restore auf einem Raspberry Pi und keinen Praxistest auf einem konkreten
Synology-/QNAP-Gerät. Die Datei behauptet keine solche Hardware-Abnahme.
