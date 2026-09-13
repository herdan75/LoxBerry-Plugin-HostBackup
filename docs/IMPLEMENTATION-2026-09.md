# Umsetzung der Analyse vom 13.09.2026

Entwicklungsbasis: develop, da9aa80. Reihenfolge: Sicherheit, Betrieb, Bedienung,
Erweiterungen. Zielstand: **0.7.0-beta**, interne Plugin-Version **0.7.0**.
Die bisher zurückgestellte AP-14 zur Mail-/Benachrichtigungssemantik ist ausgenommen.
Der Stand wird als neues Pre-Release mit eigenem ZIP und Updateeintrag
bereitgestellt; der stabile Kanal bleibt auf 0.5.8. Die
[Release Notes](RELEASE-0.7.0-beta.md) beschreiben Update und Prüfgrenzen.

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
Release-Vorbereitung; sie sind kein Nachweis für bereits erfolgreiche Linux-CI.

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

Lokale Browserbelege (JSON-Receipt, Desktop/Mobilbilder und Beispiel-Prüfbericht):
`C:\Users\Daniel Hermann\AppData\Local\Temp\hostbackup-final-validation-ee2a7d11c5e94d19a7d51c2aa2d0fe58\browser\`.
Es handelt sich ausschliesslich um künstliche Testdaten, nicht um produktive Backups.

Nach diesem erfolgreichen Gesamtlauf folgten zunächst Dokumentation,
Testpaketierung und lesende Abschlussprüfungen. Die anschliessende
Release-Vorbereitung ergänzt Versions-/Update-Metadaten und Release-Dokumentation.

## Testgrenzen

Keine produktiven Backups, Restores oder Serviceaktionen. Linux-Integrationstests
verwenden ausschliesslich isolierte temporäre Verzeichnisse. Echte Offline-
Wiederherstellung auf LoxBerry und NAS-Matrix bleiben gesonderte Praxistests.

Dieser Windows-Arbeitsplatz hat kein Linux-Root-/rsync-/ACL-/xattr-Testsystem.
Die entsprechend markierten Tests müssen auf Linux ausgeführt werden.
Die Veröffentlichung des Pre-Release-Pakets ist an erfolgreiche Linux-CI
einschliesslich Integrations- und Browserprüfungen gebunden. Der zugehörige Lauf
und seine tatsächlichen Ergebnisse werden auf der
[Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.0-beta)
nachgeführt; diese lokale Prüfung behauptet kein noch ausstehendes CI-Ergebnis.
Vor einer stabilen Freigabe sind zusätzlich
die Szenarien in `DR-TESTPLAN.md` einschliesslich realem Neustart, Zielverlust,
NAS-Profilen und vollständigem Offline-Systemstart abzuarbeiten.

## Veröffentlichung

- Pre-Release: `v0.7.0-beta`, Plugin-Version `0.7.0`.
- Paket: `LoxBerryHostBackup_0.7.0.zip` im zugehörigen GitHub-Pre-Release.
- `prerelease.cfg` wird für die LoxBerry-Updateerkennung auf dieses Paket
  umgestellt, nachdem es verfügbar ist; `release.cfg` bleibt bei 0.5.8.
- Produktänderungen und zugehörige Dokumentation werden auf `develop` versioniert.
  Fremde unversionierte Arbeitsdateien sind kein Teil des Releases und werden
  weder übernommen noch bereinigt.
