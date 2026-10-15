# Disaster-Recovery-Testplan

Dieser Plan ist vor einer neuen stabilen Veröffentlichung und danach mindestens
bei Änderungen an rsync-/tar-Optionen, Mount-Prüfung, Import, Restore oder
Retention auszuführen. Produktive Daten werden durch synthetische Marker und
Testdienste ersetzt.

## Ergänzende Bedienungsabnahme für den unveröffentlichten develop-Stand

Diese Szenarien prüfen die schliessbaren Ansichten und die lesbare
Backup-Abschlussprüfung. Sie ändern weder Paketversion noch Updatekanäle und
sind ein Prüfplan, kein Nachweis eines Hardware-Restores.

1. Backup mit `complete_with_warnings` anzeigen: ursprüngliche Hinweise und
   einzelne Prüfpunkte aus `backup-validation.json` am richtigen Backup öffnen.
   Nicht mit dem Bericht der optionalen Inhaltsprüfung verwechseln; es darf
   kein neuer Prüflauf ausgelöst werden. Fehlenden, fehlerhaften und nicht
   lesbaren Bericht verständlich als nicht verfügbar anzeigen.
2. Berichtsdaten mit HTML-/Skriptzeichen als Text anzeigen. Zugriff auf fremde
   Pfade, Pfadtraversierung und Symlink-Ausbruch müssen serverseitig abgewiesen
   werden. Keine Schreib- oder Startaktion allein durch Öffnen oder Schliessen.
3. Vorprüfung, Restore-Vorschau, Aktionsmeldung und Live-Status jeweils öffnen,
   vollständig schliessen und erneut öffnen. Keine leeren Restflächen zwischen
   Übersicht, Prüfergebnis und Fortschritt; bestehende Formularwerte und noch
   nicht gespeicherte Eingaben müssen erhalten bleiben.
4. Während eine Abfrage läuft den Ergebnisbereich schliessen; die verspätete
   Antwort darf ihn nicht wieder öffnen. Ebenso laufenden Live-Status schliessen
   und mehrere Statusabfragen abwarten: geschlossen lassen, Hintergrundvorgang
   nicht abbrechen. Erneutes Öffnen zeigt den aktuellen Stand.
5. Nach erfolgreichem explizitem Backup-, Export-, Import- oder Restorestart
   den alten Prüfbereich schliessen und einmalig zum Live-Status führen. Kein
   wiederholter Scrollsprung bei Folgeabfragen; bei fehlgeschlagenem Start den
   Prüfbericht erhalten. Bei automatisch erkannten Zeitplanaufträgen keine
   ungespeicherten Eingaben verlieren und die Ansicht nicht ungefragt verschieben.
6. Desktop und schmale Mobilansicht sowie Tastaturbedienung prüfen: erreichbare
   Schliessen-/Wiederöffnen-Schaltflächen, eindeutige Beschriftungen, kein Fokus
   in versteckten Bereichen und keine horizontale Überbreite. **Ansicht
   schliessen** klar von **Backup stoppen** unterscheiden.
7. Mit einem separaten Testprozess die exklusive Vorgangssperre halten und
   Backup-/Restore-Vorprüfung sowie aufwendige Prüf-/Speicheraktionen aufrufen.
   Sie müssen unverzüglich mit verständlichem Belegt-Hinweis abbrechen, bevor
   neue Metadatenproben oder vollständige Dateiscans beginnen. Gespeicherte
   Prüfhinweise, Dateiansicht und Wiederherstellungsblatt eines älteren Backups
   sowie Live-Log bleiben lesbar; kein Stoppsignal an den Testprozess.
8. Während eines laufenden synthetischen Backups in ein älteres Backup wechseln
   und die Ansicht wieder schliessen. Der aktive Vorgang muss erhalten bleiben.
   Auch eine verspätete Listenantwort darf keine veraltete Vorgangs-ID in die
   Navigation zurückbringen. Log-Leseposition und **Zum Ende des Logs** prüfen;
   eine alte Logzeit nicht als gemessenen Stillstand ausgeben.
   Mit den echten Präfixen `backup-`, `restore-`, `export-`, `import-` und
   `verify-` wiederholen, insbesondere nach Seitenwechsel oder erneutem Laden.

### Aktionsmatrix: jeder sichtbare Button hat einen Prüfauftrag

Inventur aus `webfrontend/htmlauth/index.cgi` und `assets/hostbackup.js`,
einschliesslich dynamischer Buttons. Die Tabelle ordnet vorhandene Teststellen
und notwendige Abnahmefälle zu; sie ist **keine pauschale Erfolgsmeldung**.
Bestanden zählt nur mit dem Ergebnis des jeweiligen Laufs für den genauen Commit.

**B** bezeichnet `tests/browser/browser-regression.cjs`: echte CGI-Oberfläche,
echtes JavaScript/CSS, aber simulierte Backend-Antworten. **U** sind die genannten
Python-/Shell-Tests mit isolierten Daten oder kontrollierten Prozess-Fixtures.
**L** sind nur unter den vorgesehenen Linux-/CIFS-/Repository-Voraussetzungen
ausgeführte Integrationstests. Ein Skip ist kein bestandener Funktionstest.

| Buttons/Aktionen | Pflichtfälle | Teststellen / Nachweisgrenze |
| --- | --- | --- |
| **Hinweise ansehen / Prüfdetails**, „Prüfung mit Hinweis“ | Originale Abschlussprüfung, Datum, alle Prüfpunkte, optionale Hinweise; UTF-8, HTML-Zeichen, fehlende/defekte Daten; Tastatur, Schliessen, kein neuer Prüflauf | B Ergebnisansichten; U `test_validation_display.py`. Kein Nachweis eines Restore-Tests. |
| **Nächstes Backup prüfen** (`backup-preview`), Vorschlag **Portable Sicherung und Vollbackup auswählen** | Gespeicherter Stand, Dirty-Sperre, Metadatenfehler; Vorschlag ändert nur Entwurf; Belegt-Hinweis statt paralleler Probe | B Vorschau/Metadatenhilfe; U `test_runtime_safety.py`, `test_preflight_concurrency.py`; L `test_preflight_cifs.py`. NAS des Anwenders separat prüfen. |
| **Speicherbelegung berechnen**, **Laufzeitdateien prüfen** | Lesende Ergebnisanzeige, geteilte Hardlinks, spätere Antwort nach Schliessen, Sperrkonflikt, keine Löschung | B Ergebnisansichten; U `test_maintenance.py`, `test_validation_display.py`. |
| **Backup-Struktur prüfen**, **Dateiinhalte prüfen**, **Prüfbericht** und **Prüfbericht herunterladen** | Strukturprüfung, Prüfjob und gespeicherten Inhaltsbericht unterscheiden; fehlender/nicht lesbarer/veralteter Bericht, noch keine Prüfbasis, Fehler/Belegt, JSON-Vertrag bis zur CGI-Antwort; Download nur für verfügbare Nachweise | B Bericht/Download/Jobstart; U `test_verification_report.py`, `test_maintenance.py`, `test_maintenance_api.py`, `test_validation_display.py`. Ein simuliertes HTTP-200-JSON allein belegt den realen Backend-Endpunkt nicht. |
| **Ergebnis/Meldung schliessen**, **Letztes Ergebnis/Letzte Meldung anzeigen** | Gesamten Bereich verbergen, unverändert wieder öffnen; kein leerer Ergebnisöffner; späte Antworten und Fehler respektieren Schliessen; Fokus und Entwürfe erhalten | B Ergebnisansichten auf Desktop/Mobil; U `test_validation_display.py`. |
| **Live-Status ausblenden/anzeigen**, Vorgangsauswahl, **Zum Ende des Logs**, **Vollständiges Log herunterladen** | Polling bei geschlossener Ansicht, aktive Task-ID bei Navigation, beide Scrollachsen, Original-Logdownload; Schliessen sendet keinen Stop | B Live-Status/Navigation; U `test_overview.py`, `test_download_behavior.py`. Logzeit ist kein Fortschrittsmesser. |
| **Backup starten**, **Backup stoppen**, **Offene Dienste wieder starten** | Start nach erfolgreicher gespeicherter Vorprüfung; Warnbestätigung, Abbruch der Bestätigungsfrage ohne POST; einmalige Live-Anzeige; Stop nur für richtigen Task, Wiederanlaufjournal erhalten | B Aktionsrouting; U `test_runtime_safety.py`, `test_portable_worker.py`, `test_preflight_concurrency.py`. Tatsächlichen Dienst-/Containerzustand nur auf Testhost beurteilen. |
| Zielauswahl/Drag-and-drop, **Erneut prüfen** am Backup-Ziel | Klick und Tastatur übernehmen nur Zielentwurf; verlorene Verbindung/Timeout, erneute lesende Prüfung; kein automatisches Speichern | B Zielprüfung/Bedienelemente; U `test_web_security.py`. Eingebundene reale Datenträger sind zusätzliche Hardwareabnahme. |
| Datenquellen **Liste aktualisieren**, **Grundregel verwenden** | Ausnahmen und ungespeicherte Auswahl bei Nachladen/Fehler erhalten; Grundregel bewusst zurücksetzen; kein POST | B Datenquellen; U `test_source_selection.py`, `test_settings_workflow.py`, `test_web_behavior.cjs`. |
| Dienste **Liste aktualisieren/Erneut laden**, **Empfohlene Auswahl setzen**, **Auswahl leeren** | Verzögerung/Fehler/fehlendes Ziel, gemeinsame Zeitlimits; Änderungen nur im Entwurf; Wiederholen ohne doppelten Request | B Diensteliste; U `test_stop_targets.py`, `test_stop_targets_web.py`. Reale systemd-Abfrage nur bei passender Linux-Testumgebung. |
| **Änderungen speichern**, **Plugineinstellungen speichern**, **Wartungseinstellungen speichern**, Änderungsdetails | Genaue Formularzuordnung, CSRF, Fehler und Änderungen während des Speicherns; Haupt-/Wartungsformular getrennt, Entwürfe nicht fälschlich als gespeichert markieren | B Speicher-/Wartungsabläufe; U `test_settings_workflow.py`, `test_web_security.py`. |
| **Einstellungen exportieren/importieren** | Download und Dateiauswahl; Importbestätigung bei Entwürfen, Abbrechen ohne Request, ungültige Datei/Serverfehler; Navigation nur nach ausdrücklichem erfolgreichem Import | B Aktionsrouting ergänzend ausführen; U Upload-/CSRF-Prüfungen in `test_web_security.py`. Formular-/Stichtests sind kein vollständiger Import-Ende-zu-Ende-Nachweis. |
| Repository **Status prüfen**, **einrichten**, **Wiederherstellungsdatei herunterladen**, **Aufbewahrung bestätigen** | Nur gespeichertes Ziel, getrennte Formulare, bewusste Bestätigung, Download bleibt aus DOM/Logs; Fehler ändern keine Konfiguration | B Repository-Einrichtung; U/L `test_repository.py`, U `test_web_security.py`. Externe Schlüsselaufbewahrung muss der Anwender selbst sicherstellen. |
| **Dateien**, Ordner **Öffnen/Eine Ebene höher**, **Ansicht schliessen/wieder anzeigen**, **Getrennte Wiederherstellung starten** | Richtige Backup-ID/Pfade, aktueller Task bleibt erhalten; Zielentwurf beim Schliessen behalten; Wiederherstellung nur explizit in neues getrenntes Ziel | B Datei-/Restoreansicht und Aktionsrouting; U/L `test_recovery_workflow.py`, U `test_preflight_concurrency.py`. Keine produktiven Dateien im Browser-Test verändern. |
| **Restore**, **Restore-Vorschau erstellen**, **Restore starten**, **Restore-Auswahl schliessen/wieder anzeigen** | Ziel/Volume-Zuordnung erhalten, Vorschau lesend, Sicherheitsbestätigung, Offline-/Metadaten-Grenzen, Fehler; Start einmalig zum Live-Status | B Restoreansicht/Aktionsrouting; U/L `test_restore_behavior.py`, `test_recovery_workflow.py`. Bootfähiger Hardware-Restore bleibt separate Abnahme. |
| **Export erstellen/neu erstellen**, **Export-Archiv herunterladen/löschen** | Richtige ID, expliziter Start; Download mit Prüfsumme, Fehler vor Erfolgsheader; Löschbestätigung und Abbrechen; Repository-Stände bieten diese Aktionen nicht an | B Aktionsrouting; U `test_download_behavior.py`, `test_runtime_safety.py`, `test_archive_validator.py`. Dateirechte/Stream zusätzlich unter Linux prüfen. |
| **Externes Backup importieren** (`import`) | Multipart mit echter Dateiauswahl, Uploadfehler; erfolgreicher Start zeigt einmalig Live-Status; Archive vor Verwendung prüfen, Fehler in Quarantäne | B Aktionsrouting; U `test_archive_validator.py`, `test_runtime_safety.py`, `test_web_security.py`. Browser-Fixture darf keinen echten Restore/Import durchführen. |
| **Vor Löschung schützen / Schutz aufheben**, **Löschen / Unvollständiges Backup löschen** | Richtige ID/Schutzrichtung, Bestätigung/Abbrechen; Schutz und letzte geeignete Sicherung backendseitig respektieren; Fehler sichtbar lassen | B Aktionsrouting; U `test_maintenance.py`, `test_repository.py`. Reale Löschungen nur an synthetischen Testdaten. |
| **Löschvorschau anzeigen**, **Genau diese Löschvorschau ausführen** (Backups oder Laufzeitdateien) | Nur gespeicherte Regeln; richtiger `preview_digest`, veraltete Vorschau abweisen; Abbrechen ohne POST; keine übergreifenden Löschungen | B Wartung/Aktionsrouting; U `test_maintenance.py`, `test_maintenance_api.py`. Vorschau ist ausdrücklich noch keine Löschung. |
| **Persönlichen Testeintrag speichern**, **Wiederherstellungsblatt**, **Diagnosepaket herunterladen** | Datum/Notiz/Backup-ID, UTC, fehlende Berichte; korrekte Downloadheader, sensible Inhalte begrenzen; eigener Testeintrag bleibt persönliche Angabe | B Restore-Test/Downloads; U `test_maintenance.py`, `test_maintenance_api.py`, `test_download_behavior.py`. Kein automatischer Hardware-Restorenachweis. |
| Alle **Infobuttons**, native Aufklappbereiche, Sicherungsverfahren/-art, Zeitplanauswahl | Enter/Leertaste, mobile Grenzen, keine ungewollten POSTs oder Formularänderungen durch Hilfe; Sichtbarkeit/Entwürfe bei Polling erhalten | B Hilfe/Formular- und Tastaturtests; U `test_web_security.py`, `test_quick_guide.py`, `test_web_behavior.cjs`. |

**Pflicht für die Freigabe:** Die Browser-Aktionsmatrix muss gezielt Aktionen,
IDs, Formulardaten und CSRF prüfen. Ein allgemeines „jeder POST ist erfolgreich“
im Fixture reicht nicht. Fehlende, unerwartete und doppelte Requests müssen
auffallen. Besonders neue Jobstarts, Multipart-Importe, Downloads und
Abbruch-/Bestätigungswege sind zusätzlich zu blossen Sichtbarkeitstests zu
prüfen. Ein gemeldeter HTTP-500-Fehler beim Prüfbericht benötigt einen Test des
realen CGI-/Backend-Vertrags; der erfolgreiche Download eines Fixture-JSONs
allein ist dafür kein Beleg.

Nicht in dieser Matrix bewiesen sind der konkrete laufende Backup-Prozess eines
Anwenders, dessen NAS-/USB-Einbindung, Zustände seiner produktiven Dienste und
ein bootfähiger Komplett-Restore. Diese Grenzen bleiben auch bei grüner CI
bestehen. Entwicklungspush, getestetes ZIP und veröffentlichter Updatekanal
weiterhin getrennt ausweisen.

## Ergänzende Freigabeabnahme für 1.2.1-beta

Diese Szenarien gelten für die Vorabversion vom 07.10.2026. Prüfplan und
tatsächlich abgeschlossene Nachweise getrennt behandeln; siehe
[Release Notes 1.2.1-beta](RELEASE-1.2.1.md).

1. Unbekannte oder nicht auswertbare Inode-Statistik (insbesondere Gesamt=0,
   Frei=0) darf allein keinen Startabbruch auslösen. Eine bekannte positive
   Gesamtzahl und Frei=0 muss vor dem Stoppen von Diensten blockieren.
2. Alle vier Metadatenverfahren und beide Sicherungsarten durchlaufen die
   gemeinsame Vorprüfung. Ziel-, Schreib-, Metadaten-, Speicher- und
   Repository-Fehler müssen unabhängig von unbekannten Inodes blockieren.
3. Portable Vollbackup- und Repository-Vorprüfung auf einem echten eingeschränkten
   CIFS-Mount mit realer 0/0-Statistik prüfen. Reduzierte Dateisicherung muss bei
   nicht erhaltenen Eigentümern, Rechten oder Links weiter scheitern.
4. Gesamte Linux-, Repository-/Recovery-, Browser-, Installer-, Sicherheits- und
   Paketprüfungen für den exakten Tag-Commit ausführen. Öffentliches Beta-ZIP
   ohne Anmeldung herunterladen; Version, Dateiinhalte, Unix-Rechte, Engines
   und SHA-256 prüfen. Erst danach `develop` und Vorabfeed freischalten.
5. `main`, stabilen Feed und bisherige Release-Dateien unverändert lassen.
   Vorabfeed muss 1.2.1 und das ZIP unter v1.2.1-beta anbieten. Bei schon
   installiertem numerischem Teststand 1.2.1 kein höheres Angebot erwarten.
6. Direkte NAS-/NFS-Praxisabnahme und bootfähigen Restore auf eigener Hardware
   weiterhin separat durchführen. Die CI ist kein Test von Franks Produktivsystem.

## Historische ergänzende Freigabeabnahme für 1.2.0

Diese Ergänzung gilt für das reguläre Release vom 04.10.2026. Sie ist ein
Prüfplan, kein Nachweis bereits bestandener Paket- oder Hardwaretests. Die
Programmlogik wird aus der Beta-Basis `af2d55d` unverändert übernommen;
vorhandene Beta-Belege und die erneute stabile Paket-/Downloadprüfung in den
[Release Notes für 1.2.0](RELEASE-1.2.0.md) getrennt festhalten.

1. Update von Stable 1.0.0 und älteren Vorabpaketen auf das stabile Paket 1.2.0
   ohne vorherige Deinstallation prüfen. Gespeicherte Einstellungen, Backups,
   Repository-Zuordnung und Schlüssel bleiben erhalten; keine automatische
   Änderung von Sicherungsverfahren oder Datenquellen.
2. Den Übergang von 1.2.0-beta auf das stabile ZIP prüfen. Beide verwenden die
   interne Version `1.2.0`: keinen höheren Versionshinweis erwarten oder
   erzwingen. Die bei Bedarf manuelle Installation derselben Version muss ohne
   Deinstallation möglich bleiben. Repository und externe Wiederherstellungsdatei
   weiterverwenden, nicht für den Versionswechsel neu initialisieren.
3. Paketversion `1.2.0`, Tag `v1.2.0`, Paketinhalt und Engine-Prüfsummen prüfen;
   ausführbare Programmdateien gegen `af2d55d` vergleichen. Kein Beta-Opt-in für
   das reguläre Update verlangen. Erst nach Prüfung des öffentlichen stabilen
   ZIPs `main` und `develop` nachführen und beide Update-Kanäle auf dieses ZIP
   umstellen. Historische Tags und Release-Dateien dürfen nicht ersetzt werden.
4. Die nachfolgenden Funktions-, NAS- und Restore-Szenarien gelten weiterhin.
   Die stabile Kennzeichnung ersetzt weder echte NAS-/Hardwaretests noch einen
   kontrollierten Starttest des wiederhergestellten Systems. Offene Prüfungen
   als offen dokumentieren; keine neue Hardware-Abnahme aus der unveränderten
   Codeübernahme ableiten.

## Historische ergänzende Abnahme für 1.2.0-beta

Diese Szenarien gelten für den Vorabstand vom 25.09.2026. Sie sind ein Prüfplan,
kein Nachweis eines bereits bestandenen bootfähigen Hardware-Restores. Ergebnisse
der Entwicklungsbasis und der Release-Prüfung in den
[Release Notes](RELEASE-1.2.0-beta.md) getrennt festhalten. Nur isolierte Testdaten
verwenden und die ältere, bewährte Sicherung erhalten:

1. Update von 1.0.0, 1.1.0-beta und einem manuell installierten 1.1.0-develop-Paket
   ohne Deinstallation prüfen. Version `1.2.0`, unveränderte Quellenauswahl,
   Einstellungen und vorhandene Backupdaten kontrollieren; keine automatische
   Umstellung alter TAR-Vollbackups in ein Repository erwarten.
2. Weiterhin vier Verfahren und zwei Sicherungsarten prüfen. Repository-Einrichtung
   nur bei Portable Sicherung, zunächst zugeklappt; separate Einrichtung,
   Schlüsseldownload und externe Aufbewahrungsbestätigung. Ohne bestätigten
   Schlüssel darf keine portable Repository-Sicherung freigegeben werden.
   Profilwechsel und Aufklappen dürfen keine Einstellungen automatisch ändern.
3. Portable Vollbackups und den ersten sowie weitere Repository-Stände auf Linux
   und echtem SMB/CIFS mit festen UID/GID/Rechten prüfen. Datenblock-Wiederverwendung,
   geänderte/gelöschte Dateien, ACLs, xattrs, Capabilities, Hardlinks, Sparse-Dateien,
   FIFOs und Gerätedateien kontrollieren. Nur bestätigte Unix-Sockets dürfen mit
   nachvollziehbarem Bericht ausgelassen werden; Lese-/Mountfehler bleiben Fehler.
4. Schlüsselverlust und Wiederanbindung auf einem frischen Helferhost nachbilden.
   Falsches Repository, verlorener Mount, fehlender Schlüssel und zu wenig
   Linux-Staging-Platz müssen sicher abbrechen. Keine Schlüssel im normalen
   Konfigurationsexport, Log oder Diagnosepaket; ein Konfigurationsexport ist kein
   Schlüssel-Backup.
5. Vollständige Offline-Wiederherstellung mit Linux-Staging und getrenntem Ziel
   zunächst vorschauen und danach explizit ausführen. Architekturprüfung,
   Volume-Zuordnungen, Ausschlüsse und Löschgrenzen prüfen; direktes `/` und
   ungeeignete Metadaten-Ziele müssen abgewiesen werden. Bootloader und passende
   Bootpartitionen separat vorbereiten, Systemstart und Anwendungen gesondert testen.
6. Prüfungen, Löschschutz und Aufbewahrung gegen gemeinsame Repository-Daten
   testen. Stand-Verweise entfernen ist keine automatische Platzbereinigung;
   explizites Prune darf noch referenzierte Daten nicht entfernen. Keine generischen
   Einzelordner-Exporte, Explorer-Aktionen oder Online-Restores für Repository-Stände.
7. Kompakte Einrichtung, Zusatzexport und Aufbewahrung einschliesslich Infobuttons
   auf Desktop/Mobil mit LoxBerry-Schriftregeln und Tastatur prüfen. Separate
   Formulare, Speichern, Löschvorschau und ungespeicherte Eingaben müssen getrennt
   bleiben; eine Hilfe oder Vorschau löst weder Speichern noch Löschen aus.
8. Paketinhalt, Engine-Prüfsummen und `v1.2.0-beta`-Release-Paket prüfen. Erst nach
   erfolgreichem öffentlichem ZIP-Download den Vorabkanal auf 1.2.0 umstellen.
   Stable-Kanal, main-Commit, v1.0.0-Tag und dessen ZIP bleiben unverändert.

## Historische ergänzende Abnahme für 1.1.0-beta

Nur auf einem isolierten Testsystem; vorhandene produktive Backups nicht löschen:

1. Reguläres Update von 1.0.0 auf 1.1.0 ohne vorherige Deinstallation. Einstellungen,
   Referenzbackups und Root-Helferstände vergleichen; kein stiller Wechsel der Quellen.
2. Die alte Fehlerkonstellation gezielt mit geschützten Restdateien nachbilden:
   Konfiguration und Weiterleitungs-Launcher vorhanden, neue Plattforminstallation
   ohne Upgrade-Purge. Kopie als unprivilegierter Plattformbenutzer und danach
   POSTROOT ausführen; korrekter Backend-Marker, Dispatcher und gespeicherte Werte
   müssen stimmen. Kopieren als Root ist kein Ersatz für diesen Test.
3. Korrigierte Deinstallation, anschliessende Plattformbereinigung und Neuinstallation
   getrennt testen. Pfadverwechslung, Symlinks, Mounts und fremde Dateien dürfen
   nicht über die vorgesehenen Pluginpfade hinaus verändert werden.
4. Fehler und Zeitüberschreitung der Dateisystem-Prüfung unter LoxBerry-Schriftregeln
   auslösen: normal formatierte Hinweisbox, erneuter lesender Prüfversuch,
   unveränderte gespeicherte Einstellungen und offene Formulareingaben.
5. Lokale USB-Quelle, ausgeschlossene Backup-Platte und zehn nicht gewählte
   Netzfreigaben prüfen; danach eine Netzquelle ausdrücklich auswählen.
   CIFS mit festen Rechten muss konkrete Metadatenfehler statt Scheinerfolg zeigen.
6. Erst nach erfolgreichem öffentlichen ZIP-Download den Vorabkanal auf 1.1.0
   aktivieren. Stable-Kanal, main-Commit, v1.0.0-Tag und dessen ZIP unverändert prüfen.

Linux-/Browser-CI prüft isolierte Szenarien. Eine tatsächliche Reparatur von Klaus'
VM, QNAP-Kompatibilität und vollständiger Hardware-Restore sind separat abzunehmen.

## Historische Upgrade- und Bedienungsabnahme für 1.0.0

Diese Szenarien sind ein Prüfplan, kein Nachweis bereits bestandener Hardwaretests:

1. Auf einem isolierten LoxBerry Updates von 0.5.8, 0.6.x und 0.7.x
   einschliesslich manueller Testpakete auf das Release-Paket 1.0.0 prüfen.
   Die Veröffentlichung ist kein Nachweis bestandener Hardwaretests. Vorher Konfiguration exportieren und
   alle aktiven Aufgaben beenden lassen; keinen zweiten Installer parallel starten.
2. Ziel, Aufbewahrung, Profil, Ausschlüsse, ausgewählte Dienste und Zeitplan vor
   und nach dem Update vergleichen. Alte Backups und geschützte Helferstände
   müssen erhalten bleiben; danach UI und gespeicherten Zeitplan prüfen.
3. Dateiaustausch durch den echten unprivilegierten Plattformbenutzer und
   anschliessende POSTROOT-Aktivierung prüfen. Ein übriggebliebener Launcher als
   Backend muss abgewiesen werden; der gültige vorherige Verweis darf bei dieser
   Abweisung nicht ersetzt werden. Keine rekursive Startschleife akzeptieren.
4. Erneute Installation derselben neuen Version und anschliessenden Neustart
   prüfen; die Zeitplaninstallation darf nicht unbegrenzt warten.
5. Kompakte Übersicht bei Desktop-, Tablet- und Mobilbreite prüfen: vier/zwei/eine
   Spalte, vollständige Daten im Detailbereich, Enter/Leertaste zum Aufklappen,
   kein automatischer Prüfstart und unveränderter Aufklappzustand beim Nachladen.
   Fehler, offene Dienst-Wiederanläufe und geladene Ergebnisse bleiben sichtbar.
6. Speicherberechnung und Laufzeitdateien-Prüfung zunächst getrennt beobachten.
   Dauer, Prozessstatus und eventuelle HTTP-Fehler protokollieren. Die fehlende
   Fortschrittsanzeige und der bekannte Sperrkonflikt mit generischer HTTP-500-
   Meldung sind in 1.0.0 noch offen, nicht als behoben zu bewerten.
7. Von 0.5.8 oder älter eine neue vollständige Basiskopie einplanen. Von
   0.6.x/0.7.x eine passende validierte Referenz und deren tatsächliche
   Hardlink-Wiederverwendung prüfen; die neue Versionsnummer allein darf diese
   Referenz nicht ausschliessen. Das letzte brauchbare Backup erhalten.
8. Plugin- und Diagnoseversion müssen 1.0.0 ohne Beta-Zusatz anzeigen. Beide
   Update-Kanaldateien müssen auf das geprüfte öffentliche 1.0.0-Release zeigen.
   Updateerkennung auch aus dem bisherigen Vorabkanal prüfen. Bei bereits
   installierter 1.0.0 darf kein höherer Versionshinweis erfunden werden.

## Ergänzende Cron-/Aufbewahrungsabnahme für 1.0.0

Diese Prüfungen gelten für den übernommenen Korrekturstand vom 13.09.2026
und das darauf aufbauende Paket 1.0.0. Nur auf einem
isolierten Testsystem mit Testdiensten und entbehrlichen Testbackups ausführen:

1. Nach Installation enthalten sowohl die Boot- als auch die Fünfminuten-Regel
   `recover-services --scheduled`. Während ein regulärer Vorgang die globale
   Sperre hält, muss dieser Aufruf ohne Ausgabe mit Status 0 zurückkehren.
   Offene Journale und aktive Aufgaben müssen unverändert bleiben; der manuelle
   Aufruf ohne Zusatz meldet weiterhin eine belegte Sperre mit Status 5.
2. Nach Freigabe der Sperre muss der nächste automatische Versuch ein offenes
   Wiederanlauf-Journal abarbeiten. Einen fehlgeschlagenen Test-Dienststart
   zusätzlich prüfen: Fehlerausgabe und Fehlerstatus müssen erhalten bleiben,
   ebenso das Journal für einen späteren erneuten Versuch. Keine pauschale
   Ausgabeumleitung oder Abschaltung der Cron-Mails verwenden.
3. Die Phase muss nach der Backup-Validierung auf `retention` wechseln und in der
   Oberfläche als „Aufbewahrung prüfen und alte Backups bereinigen“ erscheinen.
   Die Aufgabe bleibt währenddessen laufend und hält ihre Sperre. Erst nach der
   Aufbewahrung darf der Abschluss erscheinen; Löschregeln und Schutz bleiben gleich.
4. `tests/test_runtime_safety.py` prüft zusätzlich eine echte konkurrierende
   Linux-`flock`-Sperre. Unter Windows wird dieser Test ausdrücklich übersprungen;
   Bash-Funktionstests mit simulierten Sperren und Browserprüfungen ersetzen weder
   diesen Linux-Nachweis noch die Abnahme auf dem Test-LoxBerry.

## Testmatrix

| Ziel | Profil | Sicherungsart | Erwartung |
|---|---|---|---|
| ext4/xfs/btrfs | Linux-Dateisicherung | Full + Snapshot | `complete`, Validierung `ok`, Metadaten vollständig |
| CIFS Synology | Dateisicherung mit reduzierten Metadaten | Full | `complete`, Validierung `ok`, neutraler Hinweis auf bewusst ausgelassene xattrs |
| NFS Synology | Dateisicherung mit reduzierten Metadaten | Full | `complete`, Validierung `ok`, neutraler Hinweis auf bewusst ausgelassene xattrs |
| Ziel mit stabilen user-xattrs | Metadaten in Dateiattributen speichern | Full + Snapshot | `complete`, `user.rsync.*` nachweisbar |
| CIFS/NFS | Portable Sicherung | Full | `complete`, `rootfs.tar`, Restore nur offline |
| CIFS mit festen UID/GID und Rechten, ohne ACL/xattrs | Portable Sicherung | Platzsparende Sicherungsstände | Repository nach Einrichtung/Schlüsselbestätigung, drei Stände mit Wiederverwendung, vollständiger Metadaten-Restore auf Linux-Staging |

Portable Sicherungsstände sind ohne verfügbare Engine, initialisiertes Repository
am gespeicherten Ziel oder bestätigte Schlüsselaufbewahrung abzulehnen. Ebenso
blockiert ein eingeschalteter automatischer tar.gz-Export; kein automatisches
Umstellen auf Vollbackup oder stilles Ausschalten des Exports. Linux-Dateisicherung
muss auf einem Ziel, das die Probe nicht besteht, vor dem eigentlichen Backup
fehlschlagen. Die CIFS-Testzeile simuliert NAS-Mount-Einschränkungen; sie ist kein
Nachweis für jedes NAS-Modell oder für einen bootfähigen Hardware-Restore.

Zusätzliche Repository-Prüfungen: Wiederanbindung nur mit richtiger Recovery-Datei,
falscher Schlüssel/Repository-Identität, verlorener Mount, fremde Standdaten,
abgebrochene Sicherung und gefülltes Ziel dürfen keinen neuen gültigen Stand
erzeugen. Schutz/Aufbewahrung, Inhaltsprüfung, leerer Linux-Staging-Pfad mit
genügend Platz, tatsächlicher Offline-Datei-Restore sowie Architektur-Abweisung
prüfen. In der Oberfläche dürfen Repository-Stände weder normalen Einzelarchiv-
Export noch direkten Online-/Einzeldatei-Restore anbieten. Alte TAR-Vollarchive
müssen weiterhin lesbar bleiben; siehe [Recovery-Ablauf](PORTABLE-REPOSITORY.md).

## Testdaten

Auf einem isolierten LoxBerry-/DietPi-Testhost anlegen:

- normale Datei mit UID/GID ungleich Root und Modus `0640`,
- Verzeichnis mit Default-ACL und Datei mit zusätzlicher ACL,
- `user.*`-xattr,
- Testkopie einer Datei mit `security.capability`,
- Hardlink-Paar und relativer Symlink,
- Sparse-Datei mit mindestens 1 GiB logischer Grösse,
- Test-systemd-Dienst und Testcontainer mit eindeutigem Vorher-Zustand,
- kleine Testdatenbank mit applikationsspezifischem Dump-Hook.

Prüfsummen und Metadaten vorab mit `sha256sum`, `stat`, `getfacl`, `getfattr`,
`getcap`, `du` und `ls -li` erfassen.

## Ablauf je Matrixzeile

1. Ziel einhängen, Einstellungen speichern und Zielmarker dokumentieren.
2. Preflight ausführen und Metadaten-Roundtrip prüfen.
3. Backup starten; Task-Phasen und Dienst-/Container-Stop beobachten.
4. Manifest, Validierungsdatei, Marker, Dateizahl und Status prüfen.
5. Export erzeugen; `sha256sum -c` und Descriptor/Manifest-Hash prüfen.
6. Export löschen, neu erzeugen, extern kopieren und wieder importieren.
7. Import mit Traversal-, Symlink-, Hardlink-, Duplicate- und Grössen-Testarchiven
   wiederholen; jeder negative Fall muss ohne Veröffentlichung im Backup-Ziel
   enden.
8. Restore auf einem frisch installierten, isolierten Zielhost aus Rescue-/
   Offline-Umgebung durchführen.
9. Prüfsummen, UID/GID, Modi, ACLs, xattrs, Capabilities, Hardlinks, Symlinks und
   Sparse-Belegung vergleichen.
10. Dienste, Container, LoxBerry-Weboberfläche, Netzwerk und Testdatenbank prüfen.

Bei Dateisicherung mit reduzierten Metadaten sind fehlende xattrs/Capabilities der erwartete und zu
dokumentierende Unterschied. Alle regulären Dateiinhalte, UID/GID, Modi, ACLs,
Hardlinks und Symlinks müssen trotzdem übereinstimmen.

## Fehler- und Abbruchtests

- Offline-Ziel mit nicht gesicherten Benutzerdaten unter einem gespeicherten
  Ausschlusspfad vorbereiten: rsync `--delete` und Portable Restore müssen sie
  unverändert lassen; fehlende Ausschlussdatei muss vor Dienst-Stopp blockieren.
- Zwei aufgezeichnete Daten-Volumes und einen Backup-Datenträger verwenden:
  ohne Zuordnung bleibt ein Daten-Volume ausgelassen und wird so angezeigt;
  mit Zuordnung wird nur das beabsichtigte Ziel beschrieben. Backup-Medium,
  fremd beschreibbare Pfadkomponenten und überlappende Zuordnungen sind gesperrt.
- Teilrestore einer Datei, eines Verzeichnisses, Hardlinks und Symlinks in einen
  neuen Unterordner prüfen; gleichnamige vorhandene Daten bleiben unverändert.
- Root/Webuser-Rollen prüfen: Webuser kann weder Helfer noch Helfer-Elternpfade
  ersetzen, aber einen geprüften Export und das vollständige Log herunterladen.
  Nach zwei Helferaufrufen und einem Update dürfen keine Python-Caches den Start stören.
- Backup nach Dienst-Stopp unterbrechen, Backup-Medium entfernen und Host neu
  starten: lokale Journale müssen übrigbleiben, früh gestartetes Cron darf beim
  ersten noch nicht bereiten Docker fehlschlagen und später erfolgreich nachholen.
- Alle Zeitplanarten mit ok/warning/error sowie konkurrierendem Auftrag prüfen:
  Warnung läuft autonom, Fehler blockiert, jeder echte Startversuch bleibt sichtbar.
- Pin, GFS, letzte gute Sicherung und veraltete Bereinigungsvorschau testen.
  Änderung zwischen Vorschau und Bestätigung darf keine unerwartete Datei entfernen.
- Inhaltsprüfbasis erfassen, danach Inhalt mit gleicher Dateigrösse verändern:
  Vergleich muss den Schaden erkennen. Erster Lauf bleibt `baseline_created`,
  niemals `restore_tested`. Bericht muss nach Manifeständerung als veraltet gelten.
- Einen externen Restoretest persönlich dokumentieren: Datum, Ergebnis und Notiz
  müssen als Benutzerangabe erscheinen, ohne Backupstatus oder Restore-Freigabe
  zu verändern. Ein späterer fehlgeschlagener Test und eine Manifeständerung
  dürfen nicht als aktueller erfolgreicher Nachweis erscheinen.
- Browser mit schmalem Fenster/Zoom und Tastatur prüfen: Profil-, Checkbox-, Text-,
  Dienst-/Containeränderung aktiviert Speicherhinweis; Save-Fehler, Tokenablauf und
  Taskabschluss verwerfen keine Änderungen. Lange Logzeilen umbrechen nicht,
  nach oben gescrolltes Log bleibt dort, dynamisch geladene Hilfen bleiben lesbar.
- Multipart-Upload über Grössen-/Platzgrenze vor dem CGI-Parser abweisen;
  temporären Verbrauch und Reste auf dem echten LoxBerry kontrollieren.

- NAS während der Kopie aushängen: Task muss fehlschlagen; lokaler Fallback darf
  nicht verwendet werden.
- Backup während Dienst-Stopp, Kopie, Validierung und Export mit `TERM` stoppen:
  nur zuvor laufende Ziele werden neu gestartet; Task zeigt Fehler/Stopped oder
  `cleanup_failed` mit Logdetails.
- Parallel Backup, Restore, Import, Export, Löschen und Retention anstossen:
  konfliktbehaftete Aktionen müssen am globalen oder Backup-Lock scheitern.
- PID wiederverwenden simulieren: abweichende `/proc`-Startzeit darf keinen
  fremden Prozess stoppen.
- Manifest, Marker, Validierung und Export-Prüfsumme einzeln manipulieren: Browse,
  Export, Löschen oder Restore müssen entsprechend blockieren.
- Pre-/Post-Hook fehlschlagen lassen: Backup muss fehlschlagen und der
  Wiederanlauf muss trotzdem geprüft werden.

## Freigabekriterium

Eine stabile Veröffentlichung ist erst freigabefähig, wenn alle automatisierten
Tests grün sind und jede relevante Matrixzeile einen datierten Testnachweis mit
Host-/OS-Version, Dateisystem, Profil, Backup-ID, Restore-Ziel und Ergebnis hat.
Ein fehlender echter Offline-Restore bleibt ein Release-Blocker und darf nicht
durch einen erfolgreichen Backup- oder Exporttest ersetzt werden.
