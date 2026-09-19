# Disaster-Recovery-Testplan

Dieser Plan ist vor einer neuen stabilen Veröffentlichung und danach mindestens
bei Änderungen an rsync-/tar-Optionen, Mount-Prüfung, Import, Restore oder
Retention auszuführen. Produktive Daten werden durch synthetische Marker und
Testdienste ersetzt.

## Ergänzende Upgrade- und Bedienungsabnahme für 1.0.0

Diese Szenarien sind ein Prüfplan, kein Nachweis bereits bestandener Hardwaretests:

1. Auf einem isolierten LoxBerry Updates von 0.5.8, 0.6.x und 0.7.x
   einschliesslich manueller Testpakete auf das CI-Testpaket 1.0.0 prüfen.
   Keine öffentliche Freigabe daraus ableiten. Vorher Konfiguration exportieren und
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
8. Plugin- und Diagnoseversion müssen 1.0.0 ohne Beta-Zusatz anzeigen. Die
   Update-Kanaldateien bleiben bis zur separaten Veröffentlichung auf ihren
   bisherigen Versionen; weder Pluginseite noch öffentliche Releases ändern.

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

| Ziel | Profil | Backup-Modus | Erwartung |
|---|---|---|---|
| ext4/xfs/btrfs | Native Strict | Full + Snapshot | `complete`, Validierung `ok`, Metadaten vollständig |
| CIFS Synology | Network Compatible | Full | `complete`, Validierung `ok`, neutraler Hinweis auf bewusst ausgelassene xattrs |
| NFS Synology | Network Compatible | Full | `complete`, Validierung `ok`, neutraler Hinweis auf bewusst ausgelassene xattrs |
| Ziel mit stabilen user-xattrs | Fake Super | Full + Snapshot | `complete`, `user.rsync.*` nachweisbar |
| CIFS/NFS | Portable Archive | Full | `complete`, `rootfs.tar`, Restore nur offline |

Snapshot ist mit Portable Archive abzulehnen. Native Strict muss auf einem Ziel,
das die Probe nicht besteht, vor dem eigentlichen Backup fehlschlagen.

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

Bei Network Compatible sind fehlende xattrs/Capabilities der erwartete und zu
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
