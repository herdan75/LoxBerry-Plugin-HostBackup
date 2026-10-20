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
Kopierergebnis und Mount-Prüfung. `tar-result.json` bewahrt zusätzlich den
Originalstatus und die gezielte Verzeichnisbewertung. Für eine Freigabe müssen
Identität und wiederherstellbare Metadaten des betroffenen verwalteten
Diagnoseverzeichnisses vor und nach dem Kopieren sowie sein Archivheader passen.
Nur Zeitstempel beziehungsweise Verzeichnisgrösse dürfen sich durch die Rotation
ändern. Vollständige, eindeutig quotierte TAR-Diagnosen werden privat erfasst;
unbekannte oder gemischte Fehler erlauben keine Freigabe.
Der letzte vollständig geprüfte Stand je
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

## Nachprüfung: Docker-Namespace-Mounts und Fehlerausgabe

Das erste Testpaket enthielt eine Regression in der erweiterten Mount-Prüfung:
Nicht nur Mount-Ziele, sondern auch Mount-Identitäten wurden als absolute Pfade
geprüft. Linux erzeugt für `nsfs` jedoch absichtlich Kennungen wie `net:[123]`
([Kernel-Implementierung](https://raw.githubusercontent.com/torvalds/linux/v6.12/fs/nsfs.c)).
Solche Einbindungen kommen unter anderem bei Docker vor. Der Fehler war mit
einer gültigen Mount-Tabelle reproduzierbar; die bisherigen grünen Läufe hatten
diese Kombination noch nicht abgedeckt.

Eine getrennte Prüfung akzeptiert diese begrenzten Kennungen ausschliesslich
für `nsfs`, sowohl beim Einlesen als auch beim Vergleich gespeicherter Berichte
einschliesslich mehrerer Mount-Schichten. Benutzerpfade und Mount-Ziele bleiben
absolute Pfade. Namespace-Einträge werden nicht versteckt: Eine neue Einbindung,
die gesicherte Dateien überdeckt, muss weiterhin zum Fehler führen.

Zusätzliche Regressionen prüfen gültige und ungültige Namespace-Kennungen,
Berichts-Roundtrips, ausgeschlossene Änderungen und überdeckte Daten. Ein echter
Namespace-Bind-Mount wird zusätzlich in der isolierten Linux-Integration geprüft.
Die Shell-Vorprüfung behandelt fehlgeschlagene, leere oder ungültige
Quellenantworten kontrolliert als Fehler, ohne einen zusätzlichen JSON-Traceback
in Oberfläche oder Log. Alte Logdateien bleiben unverändert als Nachweis erhalten.
Der nachfolgende Commit benötigt seinen eigenen vollständigen CI-Lauf; die
bisherigen älteren Läufe gelten nicht als Nachweis dieser Korrektur.

## Internetrecherche und abgeleitete Sonderfälle

Es wurden Primärquellen mit den tatsächlichen Kopieroptionen und Prüfungen
abgeglichen. Allgemeine Erfahrungsberichte allein dienen nicht als Nachweis.

| Dokumentierter Sonderfall | Umsetzung beziehungsweise Prüfung |
| --- | --- |
| [rsync-Dateilisten](https://download.samba.org/pub/rsync/rsync.1): Führende `#` und `;` können trotz NUL-Trennung Kommentare sein; `--from0` gilt auch für Ausschlussdateien. `--dirs` erweitert den Eintrag `.` um neue Wurzeleinträge. | Explizite relative Namen erhalten `./`; rsync bekommt keinen expliziten `.`-Eintrag. Wurzelmetadaten werden separat im tatsächlichen Kopiertest geprüft. Die eingefrorene Auswahl wird nicht nochmals als anders getrennte Ausschlussliste interpretiert. Tests für Sonderzeichen, Leerzeichen, Zeilenumbrüche und erst nach der Auswahl entstandene Dateien. |
| [GNU TAR: sich ändernde beziehungsweise nicht lesbare Dateien](https://www.gnu.org/software/tar/manual/html_node/Ignore-Failed-Read.html). | Kein pauschales `--ignore-failed-read`. Relevante fehlende oder während des Lesens veränderte Daten bleiben sichtbar. Ein deterministischer Checkpoint-Test ergänzt die Rotationstests. |
| [GNU-TAR-Quellcode 1.35](https://ftp.gnu.org/gnu/tar/tar-1.35.tar.xz), `src/create.c`: `--no-recursion` verhindert nicht die Änderungsprüfung des Verzeichnisses selbst. | Die verschärften Rotationstests haben diesen zusätzlichen Abbruch tatsächlich reproduziert. Eine gezielte Behandlung muss echte Verzeichnisidentität und unveränderte Eigentümer, Rechte und erweiterte Metadaten nachweisen; wichtige Dateiänderungen und gemischte Fehler bleiben strikt. Das blosse Unterdrücken der Warnmeldung genügt nicht. |
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

## Frühere Fehlermeldungen bleiben im Regressionsumfang

Die CI entdeckt weiterhin sämtliche `tests/test_*.py` und führt zusätzlich die
vollständigen Browser- und Linux-/CIFS-Integrationen aus. Der neue Schwerpunkt
ersetzt keine bisherigen Prüfungen.

| Frühere Meldung | Gezielte Regressionen |
| --- | --- |
| NAS meldet `0/0/0` Inodes | `test_runtime_safety.py`, `test_preflight_cifs.py`: unbekannte Werte zulassen; bekannte Erschöpfung und andere echte Vorprüfungsfehler weiterhin blockieren. |
| Ungeeignete SMB-Metadaten / portable Sicherung | `test_metadata_probe.py` und echte portable CIFS-Roundtrips: feste Rechte und fehlende Metadaten nicht als Erfolg ausgeben; portable Wiederherstellung gesondert prüfen. |
| Diensteliste und Zeitüberschreitung | `test_stop_targets.py`, Browser `checkStopTargets`: grosse Listen, gemeinsame Zeitgrenze, verzögerte Antwort, Wiederholung und Erhalt der Eingaben. |
| Squeezelite-Instanzen, Sonderzeichen und falsche Empfehlungen | `test_systemd_stop_safety.py`, `test_stop_targets_web.py`: gültige Namen wörtlich übertragen, Aliase kanonisch behandeln, unsichere Stopps abweisen; tatsächlichen Backup-Worker ausführen. |
| Verschwundene Docker-ID / wiederholte Mails | `test_docker_recovery.py`: bestätigte obsolete IDs archivieren, keine Ersatzcontainer nach Namen starten; echte Startfehler weiter behandeln und unveränderte Meldungen nicht endlos versenden. |
| Blockierte Altinstallation | `test_install_hooks.py`: tatsächliches Update ohne vorherige Deinstallation, erhaltene Einstellungen und Journale, anschliessende Recovery sowie Deinstallation und Neuinstallation. Schutz bei aktiven Aufgaben und ungesicherten Repository-Schlüsseln bleibt bestehen. |
| Prüfbericht mit HTTP 500 | `test_verification_report.py`, `test_validation_display.py`, Browser `checkActionWiring`: fehlende, beschädigte und gültige Berichte sowie Belegung und echte HTTP-Fehler unterscheiden. |
| Nicht schliessbare Bereiche / parallele Bedienung | Browser `checkResultPanels`, `test_preflight_concurrency.py`: schliessen und wieder öffnen, verspätete Antworten, Scrollposition, Polling, aktive Aufgaben und echte Sperren prüfen. |

Ein fremder Anwendungs-Watchdog wird dadurch nicht automatisch mit dem Backup
koordiniert. Der geprüfte Wiederanlauf behandelt verschwundene Container sicher;
für eine anwendungskonsistente Sicherung bleibt ein abgestimmter Stopp nötig.

## Ergebnisse

Bestätigter vollständiger Referenzlauf vor den zusätzlichen Internet-Sonderfällen:
[`b17f903`, GitHub-Lauf 39483556279](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/39483556279)
ist erfolgreich. Er umfasst 626 Tests im allgemeinen Linux-Lauf
(10 planmässige Skips; die separat aktivierten Integrationen folgen danach),
15 Downloads als unprivilegierter Nutzer, echte Repository-/Portable-Roundtrips,
19 neue Live-Quellen-Tests, das isolierte CIFS-Ziel, die vollständigen
Browser-Regressionen sowie acht Paketprüfungen. Syntax-, ShellCheck-,
sudoers- und PHP-Prüfungen sowie der ZIP-Build sind ebenfalls erfolgreich.

Die anschliessende Erweiterung enthält 28 verpflichtende Live-Quellen-Tests
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
