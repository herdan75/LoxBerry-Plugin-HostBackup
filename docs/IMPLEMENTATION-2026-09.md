# Umsetzung der Analyse vom 13.09.2026

Entwicklungsbasis: develop, da9aa80. Reihenfolge: Sicherheit, Betrieb, Bedienung,
Erweiterungen. Stabiler Hauptstand: **1.0.0 auf main**. Aktueller Vorabstand:
**1.1.0-beta auf develop**, interne Plugin-Version **1.1.0**.
Die bisher zurückgestellte AP-14 zur Mail-/Benachrichtigungssemantik ist ausgenommen.
Am 19.09.2026 wird der vollständige develop-Stand `4da7cf6` auf `main` übernommen.
Nur Version, Tests der Versions-/Kanaltrennung und aktuelle Dokumentation ändern
sich gegenüber diesem Programmstand. Nach der gesonderten Freigabe wird 1.0.0
als reguläres Release veröffentlicht; beide Update-Kanäle erhalten erst nach
Prüfung des öffentlichen Downloads diesen Stand. Die
[Release Notes](RELEASE-1.0.0.md) beschreiben Update, Freigabeschritte und Prüfgrenzen.
Die ursprüngliche Analyse wurde mit 0.7.0-beta veröffentlicht; historische
Prüfläufe darunter behalten ihre damaligen Versions- und Commitangaben.

## Vorabversion 1.1.0-beta am 20.09.2026

- Datenquellenauswahl, NAS-Metadaten-Diagnosen, kompakte Darstellung, Infobuttons
  und erweiterte Kurzanleitung aus dem bisherigen develop-Teststand aufgenommen.
- Nach dem gemeldeten Deinstallations-/Neuinstallationsfehler den Austausch
  geschützter Restdateien auch ohne Upgrade-Purge abgesichert. Konfiguration wird
  zuvor gesichert, alte Programmkopien gezielt vorbereitet und die Aktivierung
  eines Weiterleitungs-Launchers weiterhin abgewiesen.
- Fehlerpfad der Dateisystem-Prüfung normal formatiert; Wiederholung nur als
  lesende Prüfung ohne Speichern oder Verlust offener Eingaben.
- Neue Linux-Installations- und Browserregressionen sind Freigabekriterien.
  Tatsächliche Hardware-/VM-/NAS-Abnahme bleibt separat; die Nachricht von Klaus
  allein bestätigt keine bereits gelungene Reparatur auf seinem System.
- Version 1.1.0 im Paket, Tag v1.1.0-beta auf `bfeb897`; Vorabkanal nach geprüftem
  öffentlichen Download aktiviert. main, Stable-Kanal und 1.0.0-ZIP unverändert.
- Release-Lauf [35500522353](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/35500522353):
  276 Python-Tests ohne Skips, echter Samba/CIFS-Mount, Browserprüfungen und
  privilegierte Einstiegspunkte erfolgreich. Öffentliches ZIP ohne Anmeldung
  mit HTTP 200, 733697 Bytes, korrekter Paketstruktur und SHA-256 geprüft;
  vollständige Prüfsumme in [RELEASE-1.1.0-beta.md](RELEASE-1.1.0-beta.md).

## Historie: Ergänzungen für 0.7.1-beta am 13.09.2026

- Nachbesserung am 13.09.2026 ohne Versionssprung: automatisches `recover-services
  --scheduled` setzt bei belegter Sperre still aus; echte Fehler bleiben sichtbar.
  Die abschliessende Aufbewahrung erhält die Phase `retention`. Keine Änderung
  der Aufbewahrungsregeln, des Löschschutzes oder der Backup-Mail-Einstellungen.
- [Linux-Lauf 34764161868](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34764161868)
  prüfte den Korrekturstand `416e8ffd18c97b198ccaf4b272e197cffc849d01`: 203 Tests
  ohne Skips und 15 Browser-Prüfblöcke erfolgreich. Der aktualisierte Tag-Stand
  wird einschliesslich Veröffentlichungsdokumentation erneut geprüft.
- Die Erstveröffentlichung übernahm `39254c6` des manuellen Testpakets unverändert;
  Versionsdaten, Updateverweis und Dokumentation werden auf 0.7.1 angepasst.
- Repariert den unprivilegierten Dateiaustausch bei Updates und erkennt einen
  zurückgebliebenen Launcher vor Aktivierung beziehungsweise Ausführung.
  Der Abschlussaufruf für die Zeitplaninstallation ist zeitlich begrenzt.
- Vier kompakte Statuswerte bleiben sichtbar. Vollständige IDs, Zielpfad und
  Prüfaktionen sind aufklappbar; Fehler, offene Dienst-Wiederanläufe und geladene
  Ergebnisse bleiben ausserhalb. Der Aufklappzustand überlebt Aktualisierungen.
- [Linux-Lauf 34759728463](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34759728463)
  prüfte den zugrunde liegenden Commit `39254c6fef422bad251ec75f043ce966bf9ce37a`:
  191 Tests ohne Skips, 14 Browser-Prüfblöcke, Rechte-/Syntaxprüfungen und ZIP-Build
  erfolgreich. Der neue Release-Tag wird vor Veröffentlichung erneut geprüft;
  die Release-Seite erhält dessen CI-Nachweis und Paketprüfsumme.
- Offen bleiben Speicherberechnung ohne Zwischenfortschritt und die generische
  HTTP-500-Anzeige bei einer gesperrten Laufzeitdateien-Prüfung. Die synchrone
  Speicherberechnung hält eine gemeinsame Operationssperre; die Laufzeitvorschau
  verlangt eine exklusive Sperre. Die resultierende Belegtmeldung geht derzeit
  bei der CGI-/Browser-Fehlerdarstellung verloren. Isoliert nachgestellt,
  keine bestätigte Live-Diagnose der Laufdauer auf dem betroffenen Gerät.
- AP-14, vollständiger Offline-Restore und die reale NAS-/Hardwareabnahme
  bleiben wie bisher gesondert offen.

## Nachverfolgung

| Pakete | Status |
|---|---|
| HB-01 Speicher, HB-02 Scheduler | Vergleich der Basiskopien-Schätzung und Inodes korrigiert; alle Zeitpläne verwenden denselben Startweg mit sichtbaren Ablehnungsgründen. |
| HB-04 Wiederanlauf, HB-10 Stop | Lokales dauerhaftes Journal vor Dienstestopp; Retry unabhängig vom Backup-Medium; abgeschlossene Aufgaben werden nicht nachträglich gestoppt. Fehlerfallen und verspätete Hintergrund-PID-Registrierung korrigiert. |
| HB-05/HB-06/HB-07 Import und privilegierte Helfer | Sichere Kontrolldateien, lokale Inhalts-/Schemaprüfung und atomar aktivierte root-kontrollierte Helferverzeichnisse umgesetzt. |
| HB-03/HB-08 Restore | Gespeicherte Ausschlüsse, explizite Ziele/Volume-Zuordnungen und echte Vorschau vor Dienstestopp/Schreiben; Portable-Regeln und Hardlinkgrenzen abgesichert. |
| HB-09 Download | Root-Dateien werden geprüft über das Backend gestreamt; Hashprüfung und Ausgabe verwenden denselben Dateideskriptor. |
| HB-11 bis HB-16 Bedienung | Eingaben bei Fehlern erhalten; Start mit offenen Änderungen abgesichert; Aufgaben auffindbar; Profil-/Zeitplanvalidierung; Token-Erneuerung; lesbare Logs; mobile Hilfen und Tabellen. |
| HB-17 Importressourcen | Frühe Parser-/Uploadgrenzen, Platzreserve und skalierende Archiv-Präfixprüfung. |
| HB-18 Validierung | Metadaten-Rückkopie mit Eigenschaftsvergleich; tatsächliche Snapshot-Wiederverwendung getrennt von Quell-Hardlinks. |
| HB-19 Verhaltenstests | Isolierte Backend-/Archiv-/Restore-/Wartungstests und echte Browserinteraktionen ergänzt. Linux-Integration und Browserlauf in CI verpflichtend; Hardware-Abnahme noch offen. |
| E-01 Startübersicht, E-02 Sicherungsvorschau | Letzter Erfolg/Fehler, Task, nächster Termin, Ziel/Platz; gespeicherte Profile, Referenz, Volumes und Ausschlüsse. |
| E-03 Speicherübersicht | Logische Grösse, tatsächlich belegte Blöcke, geteilte Dateien, Exporte, fehlgeschlagene Stände und lokaler Status getrennt. Exakter Zusatzbedarf des nächsten Laufes ist nicht vorhersagbar; Basiskopien-Schätzung separat. |
| E-04 Wiederherstellungsassistent | Ziel-/Volume-Auswahl, Vorschau, Teilrestore in neuen Unterordner und herunterladbares Recovery-Blatt je Backup. |
| E-05 Inhaltsprüfung | Optionale Basiserfassung, geplanter Vergleich, Datum und herunterladbarer Prüfbericht. Separate lokale Historie selbst dokumentierter Restoretests; kein automatisch bewiesener Systemstart und keine Änderung der Restore-Freigabe. |
| E-06 Aufbewahrung | Anzahl oder tägliche/wöchentliche/monatliche Aufbewahrung, Pins, Schutz des letzten brauchbaren Backups und bestätigte Bereinigung mit gebundener Vorschau. |
| E-07 Diagnose | Diagnosepaket mit Version, Status, anonymisierten Einstellungen und optionalem vollständigem Originalprotokoll samt Datenschutzhinweis. |

## Lokale Verifikation des zusammengeführten Arbeitsstands

Die folgenden Angaben dokumentieren den Windows-Prüflauf vor der
Release-Vorbereitung; die anschliessende Linux-Abnahme ist separat unten dokumentiert.

- Gemeinsamer finaler Lauf `bash tests/run.sh`: Exit 0, 176 Tests in 265,457 Sekunden,
  `OK (skipped=13)`, anschliessend Perl-/JavaScript-Syntax, Node-Verhalten und
  lokal ausführbare Backend-Smokes erfolgreich.
- Die 13 ausgewiesenen Skips betreffen Linux-Prozessidentität, POSIX-Datei-/Link-
  und Root/Webuser-Rechte sowie echte rsync-/ACL-/xattr-Metadatenfixtures.
  Der zusätzliche Root-Neustart-Smoketest wurde mangels passwortlosem sudo
  ebenfalls nicht auf diesem Windows-Rechner ausgeführt.
- ShellCheck 0.10.0: sämtliche Shell-Einstiegspunkte mit `--severity=warning`
  ohne Befunde. `git diff --check` erfolgreich.
- Echter Edge-Browser 152.0.4191.66, Playwright 1.58.2: 10 Prüfblöcke erfolgreich,
  mit tatsächlicher CGI-Ausgabe und produktivem JavaScript/CSS, jedoch simulierten
  Backendantworten. Enthalten sind Speicherfehler, Token-/Save-Race, Taskabschluss
  ohne Reload, Logscrollen, mobile Ansicht und heruntergeladener Prüfbericht.
- Der erste, parallel belastete Gesamtlauf hatte zwei Windows-Testzeitüberschreitungen
  bei Wiederanlauffixtures. Ihre Einzelwiederholung war erfolgreich; die begrenzte
  Testfrist beträgt nun 90 Sekunden auf Windows und 60 Sekunden auf Linux.
  Produktions-Zeitlimits wurden dadurch nicht verändert. Der finale Gesamtlauf
  erfolgte ohne konkurrierende Gesamttests und bestand vollständig.

Lokale Browserbelege enthalten JSON-Receipt, Desktop-/Mobilbilder und einen
Beispiel-Prüfbericht mit ausschliesslich künstlichen Testdaten. Sie sind keine
produktiven Backups und werden nicht als Bestandteil des Plugins ausgeliefert.

Nach diesem erfolgreichen Gesamtlauf folgten zunächst Dokumentation,
Testpaketierung und lesende Abschlussprüfungen. Die anschliessende
Release-Vorbereitung ergänzt Versions-/Update-Metadaten, die unten beschriebenen
Linux-Korrekturen und Release-Dokumentation.

## Linux-Abnahme für 0.7.0-beta

[GitHub-Lauf 34753075077](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34753075077)
prüfte am 13.09.2026 den Code-Stand `92f4f643faffaf14e9ae3b470ad74a00e85174b5`:

- 187 Tests in 13,933 Sekunden erfolgreich, keine übersprungenen Tests.
- Root-/Webuser-Installation, Neustart-Rechte, echte rsync-/ACL-/xattr-Rückkopien
  und Fake-Super-Hardlinks, Sonderzeichenpfade, UID/GID und File Capabilities geprüft.
- Alle 10 Browser-Prüfblöcke mit Chromium 145.0.7632.6 erfolgreich.
- ShellCheck, sudoers-Prüfung, PHP-/Perl-/JavaScript-Syntax und Linux-ZIP-Build erfolgreich.

Die Linux-Prüfung fand zuvor den rsync-3.2.7-Fehler bei lokalen Fake-Super-Transfers;
die feste lokale Transportumgehung ist im geprüften Stand enthalten. Künstliche
Tar-Testeinträge erhielten die tatsächlichen Testbenutzer-Rechte und betretbare
Verzeichnismodi; der Produktions-Restore wurde dafür nicht abgeschwächt.
Der abschliessende Release-Tag durchläuft dieselbe Prüfschranke erneut, bevor
ein Paket veröffentlicht wird. Hardware-/NAS-Abnahme bleibt davon getrennt.

## Testgrenzen

### Nachbesserung der Wiederinstallation: unprivilegierter Dateiaustausch

Nach erfolgreicher Erstinstallation trat beim nächsten Update eine
Startschleife auf. Der geschützte Plugin-Bin-Baum konnte durch den
Plattformbenutzer nicht vollständig entfernt/ersetzt werden. POSTROOT übernahm
anschliessend den alten Weiterleitungs-Launcher als eigentlichen Backend-Code.
Der zuvor getestete Dateiaustausch als Root hatte diesen Fehler verdeckt.

`test_real_unprivileged_platform_upgrade_and_stale_launcher` bildet die
Lösch-/Kopierphase jetzt unter einem tatsächlichen unprivilegierten Linux-Konto
nach. Er reproduziert den alten Berechtigungsfehler und prüft anschliessend
Abweisung der alten Startdatei, Reparatur und Wiederholung derselben Version,
Konfigurationserhalt sowie unveränderte geschützte Helferstände. Link-Ziele
ausserhalb des Plugin-Bin-Baums bleiben geschützt. Der Test läuft nur unter
Linux mit Root-Rechten und wird von der vorhandenen Linux-CI verpflichtend
ausgeführt; ein Windows-Skip gilt nicht als bestandene Plattformprüfung.

Die Änderungen wurden zunächst auf `develop` und in einem separaten manuellen
0.7.0-Testpaket bereitgestellt. Mit 0.7.1-beta erhalten sie einen eigenen
Release-Tag, eine höhere Updateversion und einen neuen Download; das alte
veröffentlichte ZIP bleibt unverändert. Eine erneute Prüfung über den echten
LoxBerry-Pluginmanager bleibt zusätzlich notwendig.

### Historie: Nachbesserung der LoxBerry-Installation unter 0.7.0-beta

Das anschliessende reale Installationsprotokoll meldete
`Unsafe trusted directory: /etc/cron.d`. LoxBerry verknüpft dieses Verzeichnis
absichtlich mit seinem Root-eigenen `system/cron/cron.d`; dessen Eltern gehören
LoxBerry. Der bisherige Installer testete dagegen nur ein gewöhnliches
Root-eigenes Verzeichnis und ersetzte das Backend im Installationstest durch
einen Stub. Diese Abdeckung hat den Plattformfehler nicht erkannt.

Die Korrektur akzeptiert gezielt die vorgesehene Cron-Verknüpfung, ohne
Systemrechte zu verändern oder den Schutz ausführbarer Helfer zu lockern.
Ein zusätzlicher verpflichtender Linux-Test installiert das echte Backend mit
beiden Verzeichnisvarianten, prüft den gespeicherten Zeitplan, das Laden der
Konfiguration und die erneute Installation derselben Version. Unbekannte,
defekte und ungeschützte Symlink-/Zielvarianten müssen weiterhin scheitern.
[Linux-Lauf 34753883131](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34753883131)
prüfte den Korrekturstand `15957d79203d2ff084315b881c6250bb8744f43d` erfolgreich:
188 Tests ohne Skips einschliesslich der reproduzierten alten Cron-Ablehnung
und anschliessend erfolgreicher echter Installation, zehn Browser-Prüfblöcke,
ShellCheck, Rechteprüfungen und ZIP-Build. Der abschliessende Tag-Lauf und die neue
ZIP-Prüfsumme werden beim bestehenden Pre-Release dokumentiert; Version und
Download-URL bleiben unverändert.

### Zweite Nachbesserung anhand der gemessenen Verzeichnisrechte

Die erste Cron-Korrektur war noch unvollständig: Das zweite reale Protokoll
meldete die Ablehnung des Zielverzeichnisses. Die nachgereichte `stat`-Ausgabe
belegte `/etc/cron.d` als Root-eigenen Symlink (Modus `777`, unter Linux normal)
und sein Ziel `/opt/loxberry/system/cron/cron.d` mit `root:root 775`.
Die vorherige Fixture hatte nur ein Ziel mit Modus `755` abgebildet.

Der ergänzte Fix lässt deshalb ausschliesslich am erwarteten Plattform-Cronziel
Gruppenschreibrecht für GID 0 zu. Die neue Installationsmatrix umfasst
`755`, `775`, `2755` und `2775`, reproduziert beide bisherigen Ablehnungen
und prüft den vollständigen anschliessenden Ablauf mit echtem Backend,
Zeitplan, gespeicherten Einstellungen und Neuinstallation derselben Version.
Negative Tests prüfen weiterhin falsche Ziele/Eigentümer/Gruppen,
Weltschreibrecht sowie unverändert verbotene gruppenschreibbare Root-Helfer.
Es werden keine gemeinsamen Verzeichnisrechte korrigiert oder umgewidmet.
Der abschliessende CI-Lauf und die neue ZIP-Prüfsumme stehen beim bestehenden
Pre-Release; sie sind von den oben dokumentierten älteren Läufen zu unterscheiden.

### Verbleibende Praxisabnahme

Keine produktiven Backups, Restores oder Serviceaktionen. Linux-Integrationstests
verwenden ausschliesslich isolierte temporäre Verzeichnisse. Echte Offline-
Wiederherstellung auf LoxBerry und NAS-Matrix bleiben gesonderte Praxistests.

Dieser Windows-Arbeitsplatz hat kein Linux-Root-/rsync-/ACL-/xattr-Testsystem.
Die auf Windows übersprungenen Bereiche sind durch die obige Linux-CI abgedeckt.
Die Veröffentlichung des Pre-Release-Pakets ist an erfolgreiche Linux-CI
einschliesslich Integrations- und Browserprüfungen gebunden. Der zugehörige Lauf
und seine tatsächlichen Ergebnisse werden auf der
[Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.1-beta)
nachgeführt.
Vor einer stabilen Freigabe sind zusätzlich
die Szenarien in `DR-TESTPLAN.md` einschliesslich realem Neustart, Zielverlust,
NAS-Profilen und vollständigem Offline-Systemstart abzuarbeiten.

## Historie: Hauptstand 1.0.0 vor der Veröffentlichungsfreigabe

- Plugin-Version `1.0.0`, Paket `LoxBerryHostBackup_1.0.0.zip`, kein Beta-Zusatz.
- `main` übernimmt alle 23 bisherigen develop-Commits seit `47f75ef`; Ausgangsstand
  ist `4da7cf6fc47bd6ac9f0dd27c9f7f9a2b41b59e37`. Die Programmdateien bleiben
  gegenüber diesem Stand unverändert. `develop` und `pre-develop` werden nicht verschoben.
- Ein `main`-Push prüft den neuen Stand und erzeugt nur ein CI-Artefakt.
  Noch keinen `v1.0.0`-Tag, GitHub-Release oder Pluginseiten-Eintrag anlegen.
- `release.cfg` bleibt bei 0.5.8; `prerelease.cfg` und die vorhandenen öffentlichen
  Pakete bleiben unverändert. Die Version des vorbereiteten Pakets ist bewusst
  von den noch nicht umgestellten öffentlichen Update-Kanälen getrennt.
- README, Changelog, Release Notes, Sicherheits-/Testdokumentation und lokale
  Pluginseiten-/Forum-Entwürfe werden auf `main` committet und geprüft.
  Fremde unversionierte Arbeitsdateien sind kein Teil des Releases und werden
  weder übernommen noch bereinigt.

## Veröffentlichung 1.0.0 am 19.09.2026

- Gesonderter Auftrag zur Veröffentlichung als reguläres Release ohne Beta-Zusatz.
- Finale Kanalmetadaten und Dokumentation werden zuerst auf einem Release-Zweig
  geprüft. Live-Kanäle bleiben bis zur Prüfung des veröffentlichten Downloads unverändert.
- `v1.0.0` bezeichnet den unveränderten, geprüften Release-Commit. Die Tag-Pipeline
  prüft diesen erneut unter Linux und erzeugt das öffentliche ZIP.
- Danach werden `main` und `develop` auf denselben Commit vorgezogen:
  Stable- und Vorabkanal melden Version 1.0.0 mit identischer Downloadadresse.
- Der vorbereitete Stand `c981111` bestand 205 Linux-Tests ohne Skips und 15
  Browser-Prüfblöcke. Der endgültige Taglauf und die Paketprüfsumme werden auf
  der [Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.0.0) dokumentiert.
- Kein neuer Hardware-/NAS-/Offline-Restore-Nachweis durch die Veröffentlichung.
  Bekannte Grenzen und AP-14 bleiben ausdrücklich offen.
- Fremde unversionierte Dateien, frühere Releases und `pre-develop` bleiben unverändert.
  Externe Plugin-/Wiki-Seiten werden nicht automatisch bearbeitet.
