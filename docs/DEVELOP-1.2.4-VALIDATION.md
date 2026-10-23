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

## Nachbesserung: Watchdogs und Containerzustand

Stand 22.10.2026: **Entwicklungsstand, kein neues Release oder Vorabkanal-Update**.
Nach den lokalen Prüfungen ist der eigene GitHub-Lauf dieses Commits massgebend.
Ein früherer grüner GitHub-Lauf bestätigt diese zusätzlichen Änderungen nicht.

Der gemeldete Lauf vom 21.10. hatte einen erfolgreichen TAR-Kopierstatus, aber
eine neu erschienene Docker-Overlay-Einbindung während der Kopierphase. Der
Quellenfehler darf nicht pauschal als harmlos gelten: Ein gestoppter Container
kann durch eine fremde Überwachung wieder starten und Daten verändern.

LoxPanels [neuere Steuerung](https://github.com/Lenardo1/Loxpanel/blob/61bfd1d82e86f6feb06162e11e41e3fca7944bf6/loxberry-plugin/bin/loxpanel-ctl.sh)
verwendet für `check`, Backup und Restore eine gemeinsame `flock`-Sperre.
Diese Steuerung ist nicht in den veröffentlichten Plugin-ZIPs 0.3.0 bis 0.7.0
enthalten. Die ursprünglichen Sperrtests belegten daher keine Kompatibilität
mit diesen installierbaren Paketen. Die nachfolgende Ergänzung korrigiert diese
Prüflücke ausdrücklich.
Das am 23.10.2026 veröffentlichte Paket **0.9.9** enthält eine solche Sperre,
verlegt deren Prüfung jedoch in eine eigene Hilfsfunktion. Die zusätzliche
Kompatibilitätskorrektur dafür wird unten getrennt dokumentiert.
HostBackup nutzt diese Sperre beim ausgewählten LoxPanel-Container vor dem Stopp
bis nach dem Wiederanlaufversuch. Der Helfer läuft ausserhalb der
`stop_backup_targets | tee`-Pipeline, damit die Sperre nicht bereits mit dem
Ende dieser Subshell freigegeben wird.

- Nur das erkannte Sperrprotokoll wird verwendet; keine Ausführung des fremden
  Controllers als root, keine Änderung der Docker-Restart-Policy, kein
  `compose down`, Image-Pull oder automatischer Ersatz eines Containers.
- Bestehende Sperrdateien werden nicht überschrieben, gelöscht oder umberechtigt.
  Eine neue Sperrdatei ist auch bei root-Umask 077 für den Watchdog lesbar.
  Ein kurzer, unprivilegierter Leseversuch prüft tatsächliche Zugriffsrechte
  einschliesslich Elternverzeichnissen und ACLs.
- Erfolg, Kopierfehler und Cleanup lösen die Sperre nach dem Wiederanlaufversuch.
  EOF oder Ende des zugehörigen Worker-Prozesses beenden den Helfer; es bleibt
  kein dauerhafter Abschaltmarker. Eine belegte oder verlorene Sperre wird nicht
  als erfolgreiche Koordination ausgegeben.
- Der gemeinsame Worker kontrolliert zusätzlich die im lokalen Journal als
  gestoppt vermerkten Docker-IDs vor und nach der Kopie. Unerwartet laufende,
  entfernte oder nicht überprüfbare Container führen zu einem konkreten Fehler.
  Nicht ausgewählte oder schon vorher gestoppte Container werden dadurch nicht
  gestartet. Die bestehenden Quellen- und Dateiprüfungen bleiben aktiv.

### Weitere Programme und bewährte Muster

| Programm / Primärquelle | Befund und Konsequenz |
| --- | --- |
| [AudioServer4Home](https://github.com/mschlenstedt/LoxBerry-Plugin-Audioserver4Home/blob/master/bin/as_watchdog.pl) | Eigene Überwachung und bewusster Stoppmarker; Wiederanlauf kann `compose down`, Pull und Neuerstellung enthalten. Die LoxPanel-Sperre ist nicht übertragbar. Vorerst über die eigene Plugin-Oberfläche abgestimmt stoppen bzw. passende Hooks verwenden; nicht als automatisch behoben ausgeben. |
| [Watchtower](https://github.com/containrrr/watchtower/blob/main/docs/arguments.md) | `include-stopped` und `revive-stopped` können gestoppte Container aktualisieren bzw. starten; beide sind standardmässig aus. Keine pauschale Abschaltung aller Installationen. |
| [Autoheal](https://github.com/willfarrell/docker-autoheal/blob/main/docker-entrypoint) | Reagiert auf `unhealthy`, nicht allgemein auf jeden gestoppten Container. Kein belegter Auslöser dieses konkreten Falls. |
| [Offen docker-volume-backup](https://offen.github.io/docker-volume-backup/how-tos/use-with-docker-swarm.html) | Koordiniert bei Swarm den übergeordneten Dienst, beispielsweise durch vorübergehend null Replikate, statt gegen dessen automatische Wiederherstellung zu arbeiten. |
| [Borgmatic](https://torsion.org/borgmatic/how-to/add-preparation-and-cleanup-steps-to-backups/) / [Duplicati](https://docs.duplicati.com/automation-and-integration/scripts) | Vorbereitungs- und Aufräumschritte koordinieren Anwendungen; Fehlerpfade müssen den Wartungszustand ebenfalls aufheben. Keine allgemeine automatische Unterstützung beliebiger Watchdogs. |

Ein gewöhnlicher manueller Docker-Stopp unterdrückt zunächst Dockers eigene
[Restart-Policy](https://docs.docker.com/engine/containers/start-containers-automatically/).
Zusätzliche Host-Manager sind ein anderer Mechanismus; globale Policy-Änderungen
wären deshalb weder nötig noch ausreichend.

**Grenzen:** Explizite LoxPanel-Bedienaktionen wie Start oder Update benutzen
nicht zwingend die Watchdog-Sperre. Während des Backups keine solchen Aktionen
ausführen. Zwei Zustandsabgleiche sind keine lückenlose Ereignisüberwachung:
Ein zwischenzeitlicher Start mit erneutem Stopp kann zwischen den Abfragen
liegen. Die Lösung bestätigt nicht pauschal die Anwendungskonsistenz laufender
Datenbanken und ist kein vollständiger Restore-Nachweis.

Die neuen Tests umfassen Sperrprotokoll, Namens-/ID-Auswahl, sichere Dateipfade,
Kopier-/Stop-/Wiederanlauffehler, verlorene Helfer und die Reihenfolge von Stopp,
Kopie, Quellenprüfung und Wiederanlauf. Linux-spezifische Tests verwenden echte
Sperren und prüfen zusätzlich Signalbehandlung, Besitzerende und unprivilegierten
Dateizugriff. Am Windows-Arbeitsplatz sind diese Linux-Tests ausdrücklich
ausgelassen; die tatsächliche Linux-Ausführung muss der neue GitHub-Lauf belegen.
Andreas' System und ein vollständiger Restore bleiben gesonderte Praxistests.

Die zusätzliche Bedienkorrektur speichert erkannte Containerprobleme strukturiert
beim Vorgang, nicht nur im begrenzten Logausschnitt. Die aufklappbare Meldung im
Live-Status nennt den ursprünglichen Containernamen und die unveränderliche ID,
trennt Wiederstart, fehlenden Container und nicht prüfbaren Docker-Zustand und
gibt konkrete nächste Schritte. Der Name stammt aus dem lokalen Stoppjournal
und wird niemals zur Auswahl eines Ersatzcontainers verwendet. Fehlt er in
einem alten Journal, bleibt die ID sichtbar. Ein möglicher Watchdog wird nicht
als bewiesener Verursacher bezeichnet. Die Diagnose soll Statuswechsel,
Wiederanlauf und Seitenreload überstehen; Polling darf einen vom Nutzer
zugeklappten Hinweis nicht wieder öffnen. Backend- und Browsertests prüfen diese
Fälle und die getrennte Anzeige verschiedener Vorgänge. Diese Erweiterung
benötigt ihren eigenen vollständigen CI-Nachweis nach dem nächsten Commit.
Die lokalen Diagnoseprüfungen umfassen elf echte Journal-/Task-API-Tests,
zehn Zustandsprüfungen und die Übersichtssuite (13 ausgeführt, ein
Linux-`/proc`-Skip unter Windows). Der fokussierte CGI-/Browsertest wurde auf
Desktop und Mobil erfolgreich ausgeführt: getrennte Ursachen und Selbsthilfe,
vollständige IDs, langes Log, Reload, Aufgabenwechsel, sichere Textdarstellung
und schliessbare Hinweise. Eine Beobachtung verändert weder Docker noch das
Wiederanlauf-Journal; auch dies wird geprüft.

Lokal ausgeführt: 27 Helfer-Testmethoden (19 ausgeführt, acht Linux-Skips),
19 Koordinations-Testmethoden (neun ausgeführt mit zusätzlichen Tabellenfällen,
zehn Linux-/Signal-Skips) sowie zehn Zustands-/Journal-Tests ohne Skips.
ShellCheck 0.11.0 für die geänderten Shell-Dateien, Bash-Syntax, JavaScript-
Verhaltenstest und acht Prüfungen des neu gebauten Installationspakets sind
erfolgreich. Diese Zahlen sind keine Behauptung einer lokalen Linux-Ausführung.
Zusätzlich wurden 22 bestehende portable/TAR-/rsync-Worker-Testmethoden sowie
die beiden vollständigen simulierten Abläufe mit Squeezelite/SONN und einer
zwischen Backups entfernten Docker-Anwendung erfolgreich erneut ausgeführt.
In der verpflichtenden Linux-CI führen fehlendes Bash, flock oder benötigte
Root-Rechte bei den neuen Koordinationstests zu Fehlern, nicht zu stillen Skips.

## Ergebnisse

### Kompatibilität mit LoxPanel 0.9.9 (23.10.2026)

Das tatsächliche [Release-Paket 0.9.9](https://github.com/Lenardo1/Loxpanel/releases/tag/v0.9.9)
enthält weiterhin die gemeinsame Watchdog-Sperre, aber eine ausgelagerte
Prüffunktion. Die bisherige enge Strukturerkennung weist diese Variante zurück,
obwohl das unterstützte Sperrverfahren vorhanden ist. Die Korrektur erweitert
gezielt die Protokollerkennung; sie akzeptiert nicht pauschal jede neuere
Versionsnummer und führt keinen fremden Controller als root aus.

Unverändert gelten:

- 0.3.0 bis 0.7.0: bereits vor der Vorprüfung in der eigenen LoxPanel-Oberfläche
  stoppen; vorhandenen Stoppmarker erhalten und später selbst wieder starten.
- 0.9.9 und die bereits unterstützten Sperrvarianten: den ausgewählten Container
  unter der gemeinsamen Sperre stoppen und wieder starten. Keine Neuerstellung,
  kein Pull und kein neuer Sicherungsmodus.
- Bereits vorher ausgeschaltete Container nicht automatisch starten; unbekannte
  Controller, unbrauchbare Sperren und unerwartete Containeränderungen weiterhin
  verständlich melden. Andere Anwendungen wie AudioServer4Home werden dadurch
  nicht automatisch koordiniert.
- Manuelle Start-/Updateaktionen während des Backups bleiben zu vermeiden.
  Eine gemeinsame, dauerhaft zugesicherte Backup-Schnittstelle mit LoxPanel ist
  nicht implementiert; Änderungen des Sperrprotokolls können neue Prüfung erfordern.

Lokale Nachweise dieser Ergänzung:

- Guard-/Kompatibilitätssuite: 38 Tests, 30 erfolgreich und acht Linux-Skips.
  Enthalten sind 20 zusätzliche positive Varianten und 46 Negativvarianten,
  darunter doppelte Funktionsdefinitionen, mehrdeutige Aufrufzweige, entfernte
  Sperren und vorzeitige Starts. Eine unabhängige Gegenprüfung ist erfolgt.
  Der erste Linux-Lauf deckte eine zu strenge Ablehnung einer bestehenden
  Variante mit `echo busy` auf. Die Erkennung erlaubt nun harmlose, wörtliche
  Ausgaben auch ohne Anführungszeichen; Shell-Ersetzungen bleiben gesperrt.
- Originalcontroller-Suite: 17 Tests, vier erfolgreich und 13 Linux-Skips.
  Herkunft, unveränderte Bytes und SHA-256 des veröffentlichten 0.9.9-Pakets
  sind geprüft; alte veröffentlichte Varianten bleiben in derselben Matrix.
- Python-Kompilierung, Bash-Syntax der neuen Fixture und `git diff --check`
  erfolgreich. Der Controller ist nur Testmaterial und nicht Teil des ZIPs.

Der vollständige GitHub-Workflow **zum Commit dieser Ergänzung** ist der
massgebliche Nachweis für echte Linux-Sperren, Watchdog-/Boot-Aufrufe,
Abbrüche, Wiederanlauf, Installer, NAS und Browser. Vor dessen grünem Abschluss
sind diese Laufzeitprüfungen offen; frühere Läufe ersetzen ihn nicht.
Auch ein erfolgreicher CI-Lauf ist kein Test auf Andreas' Gerät und kein
vollständiger System-Restore. Installations-/Paketversion bleibt 1.2.4 auf
`develop`; öffentlicher Vorabkanal, stabiles Release und `main` bleiben unverändert.

### Korrektur der veröffentlichten LoxPanel-Varianten (22.10.2026)

Andreas' Lauf `backup-20261022-134825-2328655.log` endet bereits vor dem Kopieren:
Die neue Erkennung setzte eine im veröffentlichten LoxPanel-Paket nicht
vorhandene Sperre voraus. Das offizielle ZIP 0.7.0 reproduziert dieselbe
Fehlermeldung. Die acht veröffentlichten ZIPs 0.3.0 bis 0.7.0 enthalten denselben
Controller mit `loxpanel_stopped.cfg`; ihre neue Testsuite verwendet deshalb
ein dedupliziertes Original mit Herkunft, SHA-256 und Lizenznachweis.

- Veröffentlichung ohne Sperre: bewussten Stopp aus eigener LoxPanel-Oberfläche
  anhand des unterstützten Markers und des Docker-Zustands prüfen. Stoppmarker
  weder anlegen noch löschen; manuell gestoppte Anwendungen bleiben gestoppt.
- Neuere Sperrsteuerung: automatisches, zeitlich begrenztes Koordinieren wie
  bisher. Fremder Plugin-Code wird von HostBackup weiterhin nicht ausgeführt.
- Gemeinsame lesende Vorprüfung vor Backup-Anlage und erneute Prüfung im Worker;
  Änderungen nach einer Vorprüfung bleiben erkennbar. Nicht voraussetzen, dass
  ein beliebiges Vorab-Skript einen noch laufenden Legacy-Watchdog sicher stoppt:
  bei dieser Variante muss der bewusste Stopp bereits vor der Vorprüfung erfolgen.
- Kombinationen: Name/ID/alte Gesamtauswahl, fehlender oder nicht ausgewählter
  Container, laufend/gestoppt/entfernt, Marker vorhanden/fehlend/ausgetauscht,
  Docker nicht erreichbar, unbekannte Controller, Symlinks, Rechte, Abbrüche und
  gleichzeitige Watchdog-Aufrufe. Bestehende Quellen-, Recovery-, Installer-,
  NAS- und Oberflächentests bleiben Teil der Regression.

Lokale Nachweise dieser Ergänzung:

- Gesamtlauf `test_watchdog*.py`: 78 Tests, davon 55 erfolgreich und 23 wegen
  fehlender Linux-Funktionen unter Windows übersprungen. Die abschliessend
  erweiterten reinen Guard-/Kompatibilitätstests wurden separat erneut geprüft.
- Vorprüfung: 11 Tests erfolgreich; zusätzlich die vollständige Matrix aus vier
  Metadatenprofilen, zwei Sicherungsarten und `skip`/`lock` (16 Kombinationen).
- Bestehende RuntimeSafety: 42 Tests, davon 40 erfolgreich und zwei erwartete
  Windows-Skips. ShellCheck, Bash-/JavaScript-Syntax und Web-Verhalten erfolgreich.
- Gezielter echter Browsertest für die neue Vorprüfung auf Desktop und Handy
  erfolgreich. Der vollständige lokale Edge-Lauf wurde durch ein unerwartetes
  Schliessen des Browsers unterbrochen und gilt nicht als bestanden.

Massgeblicher Linux-/NAS-/Browsernachweis ist der vollständige GitHub-Workflow
zum Commit dieser Änderung. Vor dessen erfolgreichem Abschluss sind insbesondere
die Linux-Skips und der vollständige Browserlauf offen; frühere grüne Läufe
ersetzen diesen Nachweis nicht. Eine erfolgreiche Linux-Simulation ist weiterhin
kein Praxistest auf Andreas' Installation und kein vollständiger System-Restore.

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
