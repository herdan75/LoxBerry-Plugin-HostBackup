# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert.

Version 1.0.0 bleibt das reguläre Release; 1.1.0-beta ist der neue Vorabstand.
Die LoxBerry-Pluginseite wird separat gepflegt.
Restore-Funktionen sollten weiterhin zuerst in einer Test- oder Rescue-Umgebung
validiert werden.

## Noch nicht veröffentlicht – develop

- Verständliche Namen für weiterhin vier Sicherungsverfahren: Linux-Dateisicherung,
  Portable Sicherung sowie zwei ausdrücklich erweiterte Metadatenverfahren.
  Bestehende Konfigurationen werden nicht automatisch umgestellt.
- Portable Sicherung um platzsparende, verschlüsselte Repository-Stände ergänzt.
  Folgesicherungen verwenden unveränderte Datenblöcke erneut; das bestehende
  eigenständige TAR-Vollbackup bleibt unverändert verfügbar.
- Zielgebundene Einrichtung mit separatem Wiederherstellungsschlüssel,
  verpflichtender externer Schlüsselbestätigung und echter Metadaten-Vorprüfung.
- Authentifizierte Veröffentlichung erst nach erfolgreicher Kopier-/Quellprüfung;
  gemeinsame Repository-Daten werden nicht als einzelne Backup-Ordner gelöscht.
- Offline-Wiederherstellung mit zusätzlichem Linux-Zwischenspeicher und expliziten
  Volume-Zuordnungen. Keine automatische Hardware- oder Architekturmigration.
- Linux-/SMB-Tests für eingeschränkte Zielrechte, inkrementelle Wiederverwendung,
  Schlüsselverlust-Szenario, Metadaten und sichere Aufbewahrung ergänzt.

## [1.1.0-beta] - 2026-09-20

### Installation und Fehleranzeige

- Neuinstallation nach einer unvollständigen früheren Deinstallation abgesichert:
  gespeicherte Konfiguration vor dem Austausch sichern und geschützte alte
  Programmkopien gezielt vorbereiten, auch ohne die Upgrade-Bereinigung der Plattform.
  Der echte unprivilegierte Kopierweg wird unter Linux geprüft. Eine dauerhafte
  geschützte Konfigurationssicherung übersteht abgebrochene Installationen,
  neue Installations-IDs und Neustarts bis zum erfolgreichen Abschluss.
- Schutz vor der Aktivierung eines zurückgebliebenen Weiterleitungs-Launchers
  bleibt erhalten. Backup-Ziele werden nicht bereinigt oder in ihren Rechten geändert.
- Eine nicht erreichbare Dateisystem-Prüfung erscheint als normale Hinweisbox
  mit erneutem Prüfversuch statt als übergrosser unformatierter Text. Gespeicherte
  Einstellungen und offene Eingaben bleiben erhalten.

### Datenquellen, NAS-Diagnose und Bedienung

- Neue Konfigurationen sichern lokale Laufwerke und nur ausdrücklich gewählte
  Netzfreigaben; autofs-Sammelbereiche werden nicht ungewollt rekursiv kopiert.
  Bestehende Konfigurationen behalten ihren Umfang mit sichtbarem Umstellungshinweis.
- Kompakte Laufwerksauswahl mit gespeicherten Ausnahmen, Vorschau und dem
  bestehenden Speicherhinweis; lokale USB-Nutzdaten bleiben auswählbar.
- Layoutkorrektur der Datenquellen: Texte und Aufklapptitel gegen globale
  LoxBerry-Schriftregeln isoliert, Hinweise gekürzt und technische System-/Docker-
  Einbindungen in aufklappbare Details gruppiert. Die Sicherungsauswahl bleibt
  unverändert; bewusst gesetzte Ausnahmen bleiben in der Hauptliste sichtbar.
- Grundregel „Bisheriges Verhalten“ verständlich in „Alle eingebundenen Laufwerke
  und Netzfreigaben“ umbenannt, lokale Regel als Empfehlung/Standard bei
  Neuinstallation beschrieben und Infobutton neben Datenquellen ergänzt.
  Ausführliche Hilfe erklärt Quellen, Ziele, Profile, Ausschlüsse, Automount
  und Speichern; lange Infofenster bleiben scrollbar innerhalb des Sichtbereichs.
  Gespeicherte Werte und Auswahlregeln bleiben unverändert.
- Kontextbezogene Infobuttons für Struktur-/Inhaltsprüfung, Prüfbericht,
  Wiederherstellungsblatt, Löschschutz und persönliche Restore-Testeinträge
  ergänzt. Weitere Hilfen erklären Übersicht-Prüfaktionen, Diagnose-Download,
  Dienst-Wiederanlauf, Backup-Stopp, erweiterte Aufbewahrung, Prüfsummenintervalle,
  Löschvorschau sowie getrennten Restore, Restore-Ziel und Volume-Zuordnungen.
  Hilfen nennen Voraussetzungen, Dauer und Grenzen und lösen selbst keine
  Aktion aus. Keine Änderung an Sicherungsumfang oder Backend-Abläufen.
- Kurzanleitung zu einer vollständigen Einrichtungs- und Prüfreihenfolge ergänzt:
  Root-Unterordner und technische Einbindungen, Neuinstallations-/Updateverhalten,
  automatischer Zielordner-Ausschluss gegenüber weiteren Backup-Datenträgern,
  zunächst leere Stop-Dienstauswahl und konsistente Docker-/Datenbankdaten,
  Speichern vor der Vorschau, Basiskopie/Speicherbedarf und manueller Test vor
  dem Zeitplan. Restore-Grenzen, Volume-Zuordnung und separater Testdatenträger
  ausdrücklich erklärt. Nur Anleitungstexte, keine neuen Standardwerte.
- Kein Backup-Start ohne gespeichertes Ziel, kein stilles Übergehen einer
  ausgewählten, nicht eingebundenen Freigabe. Explizite Dateilisten und
  Mount-Prüfung begrenzen Vollbackups, Snapshots und Portable Archives.
- Metadatenprüfung protokolliert jeden Schritt, Soll-/Ist-Werte und begrenzte
  Werkzeugfehler; letzter Bericht unter `/var/lib/loxberryhostbackup/metadata-probe.json`.
  Konkrete Hinweise zu festen CIFS-Rechten und Portable Archive/Vollbackup.
- Fehlende Unix-Metadaten werden weiterhin nicht als Erfolg behandelt;
  Network Compatible überspringt ausschliesslich xattrs und File Capabilities.
- Zusätzliche Regressionstests und isolierter echter Linux-Samba/CIFS-Test für
  feste Eigentümer/Rechte, Archiv-Roundtrip und ausgewählte Datenquellen.
- Plugin- und ZIP-Version `1.1.0`, GitHub-Tag `v1.1.0-beta`. Der Vorabkanal wurde
  nach Prüfung des öffentlichen ZIP-Downloads auf 1.1.0 umgestellt. Das reguläre
  Release 1.0.0 und sein Download bleiben unverändert.

## [1.0.0] - 2026-09-19

### Übernahme auf main und erste Hauptversion

- Vollständigen develop-Stand `4da7cf6` per Fast-forward auf `main` übernommen,
  einschliesslich sämtlicher Korrekturen bis zum aktualisierten 0.7.1-Vorabpaket.
- Plugin-Version auf `1.0.0` ohne Beta-Zusatz gesetzt; der Paketbau erzeugt
  `LoxBerryHostBackup_1.0.0.zip` und die dazu passende Laufzeit-Version.
- Gegenüber dem übernommenen Stand keine Änderung der Backup-/Restorelogik.
  README, aktuelle Release Notes, Sicherheitsmodell, Testplan, Umsetzungsbericht
  und Beschreibungsentwürfe auf den Hauptstand nachgeführt. Historische
  Versionsverläufe und Prüfnachweise behalten ihre damaligen Bezeichnungen.
- Reguläres GitHub-Release `v1.0.0` ohne Pre-Release-Kennzeichnung mit geprüftem ZIP.
  `main/release.cfg` und `develop/prerelease.cfg` zeigen auf dasselbe Paket.
  Die Kanaldateien werden erst nach erfolgreicher Prüfung des öffentlichen
  Downloads aktiviert. Auch bisherige Vorabkanal-Nutzer können auf 1.0.0 wechseln.
- `develop` auf die veröffentlichte Release-Basis nachgeführt. Bisherige
  Release-Tags, Downloads und `pre-develop` bleiben unverändert.
- Bei bereits installiertem 1.0.0-Testpaket kein höherer Versionshinweis:
  für finale Kanalmetadaten und Dokumentation das Release-ZIP manuell installieren.
- Wiki-/Pluginseiten- und Forumtexte bereitgestellt; externe Seiten werden
  dadurch nicht automatisch bearbeitet.

### Enthalten gegenüber dem bisherigen main-Stand 0.5.8

- Vier Metadaten-Profile einschliesslich Network Compatible für geeignete
  CIFS-/NFS-/NAS-Ziele; keine blockierende Warnung allein durch dieses Profil.
- Sicherere Ziele, Importe, Exporte, Downloads, Restore-Vorschauen, geschützte
  Root-Helfer und Neustart-Journale. Einstellungen bleiben bei Updates erhalten;
  Root-Laufzeitdaten liegen ausserhalb der von LoxBerry neu angelegten Logordner.
- Reparierte Installation mit Cron-Symlink-Unterstützung und begrenzter
  Zeitplaneinrichtung; keine rekursive Launcher-/Backend-Startschleife.
- Kompakte Übersicht, Speicherhinweis für ungespeicherte Änderungen, lesbare Logs,
  Aufgabenhistorie, Wartungs- und Integritätsprüfungen sowie Diagnosepaket.
- Automatischer Dienst-Wiederanlauf setzt bei belegter Sperre still aus;
  echte Fehler bleiben sichtbar. Eigene Live-Phase für die Aufbewahrung.
- Ausführliche Einzeländerungen stehen in den historischen Abschnitten darunter.

### Updatehinweise und Prüfgrenzen

- Von 0.5.8 oder älter erstellt der erste inkrementelle Lauf wegen fehlender
  Profilinformationen eine neue vollständige Basiskopie. Genügend Platz und Zeit
  einplanen. Von 0.6.x/0.7.x erzwingt die Versionsänderung allein keine Basiskopie.
- Geänderte Einstellungen vor Backup oder Vorschau ausdrücklich speichern.
- Der vorbereitete 1.0.0-Stand bestand 205 Linux-Tests ohne Skips und 15
  Browser-Prüfblöcke; vor dem Upload wird auch der Release-Tag vollständig geprüft.
- Vollständiger Offline-Restore mit Systemstart und NAS-/Hardwarematrix bleiben
  offen. Ebenso Speicherberechnung ohne Zwischenfortschritt und generische
  HTTP-500-Anzeige bei einer gesperrten Laufzeitprüfung. AP-14 bleibt ausgenommen.

## [0.7.1-beta] - 2026-09-13

### Aktualisiertes Pre-Release-Paket ohne Versionssprung

- Das bestehende ZIP `LoxBerryHostBackup_0.7.1.zip` und der Pre-Release-Tag
  `v0.7.1-beta` werden auf den korrigierten develop-Stand aktualisiert. Interne
  Version `0.7.1`, Download-Adresse und Stable 0.5.8 bleiben gleich. Bereits
  installierte 0.7.1-Versionen erhalten deshalb keinen höheren Versionshinweis;
  für die Korrektur das aktualisierte ZIP erneut installieren, ohne Deinstallation.

- Der automatische Dienst-Wiederanlauf beim Boot und alle fünf Minuten verwendet
  `recover-services --scheduled`. Ist die globale Vorgangssperre belegt, setzt
  dieser Aufruf ohne Ausgabe und mit Erfolgscode aus; die nächste Cron-Ausführung
  versucht es erneut. Dadurch entstehen keine Cron-Mails allein wegen eines noch
  laufenden Backups, Restores oder anderen gesperrten Vorgangs. Journale und aktive
  Aufgaben bleiben unangetastet. Manuelle Aufrufe melden eine belegte Sperre weiter;
  technische Sperrfehler und fehlgeschlagene Dienststarts werden nicht unterdrückt.
- Während der abschliessenden Aufbewahrungsprüfung wechselt die laufende Aufgabe
  jetzt auf `retention`, statt bei `validating` stehenzubleiben. Der Live-Status zeigt
  „Aufbewahrung prüfen und alte Backups bereinigen“. Erst nach diesem Schritt wird
  die Aufgabe abgeschlossen; Aufbewahrungsregeln und Löschschutz bleiben unverändert.
- Regressionstests für stille Cron-Sperrkonflikte, unveränderte Journale und spätere
  Wiederanläufe, sichtbare echte Fehler sowie die Phasenfolge ergänzt; zusätzlich
  Linux-Test mit echter `flock`-Sperre und Browserprüfung der Phasenanzeige.
- [Linux-Prüfung des Korrekturstands 416e8ff](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34764161868):
  203 Tests ohne Skips, darunter echte Sperr-, Metadaten- und Root-/Webbenutzertests,
  sowie 15 Browser-Prüfblöcke erfolgreich. Der Dokumentations-/Release-Stand wird
  vor Ersetzen des Downloads erneut geprüft; Nachweis und Prüfsumme beim Release.
- Backup-Mail-Einstellungen, Daten, Aufbewahrungsregeln und Löschschutz bleiben
  unverändert. Die Korrektur gilt erst nach Installation des aktualisierten Pakets.

### Versionierung und Update

- Interne Plugin-Version `0.7.1`, Pre-Release `v0.7.1-beta` und neues ZIP
  `LoxBerryHostBackup_0.7.1.zip`. LoxBerry erkennt damit ein Update gegenüber
  0.7.0 einschliesslich der manuellen Testpakete. Stable bleibt 0.5.8;
  ältere Release-Tags und Downloads werden nicht ersetzt. Ausnahme ist die oben
  dokumentierte Aktualisierung dieses 0.7.1-beta-Pakets unter derselben Adresse.
- Veröffentlicht den Programmstand `39254c6` mit angepassten Versionsdaten,
  README, Release Notes, Prüfbericht, Sicherheits- und Testdokumentation.
- Keine neue Basiskopie allein wegen des Updates von 0.7.0 auf 0.7.1;
  die vorhandenen Referenz-/Profilprüfungen bleiben unverändert. Beim Umstieg
  von 0.5.8 oder älter wird weiterhin zuerst eine vollständige Basiskopie benötigt.

### Installation und Bedienung

- Übersicht kompakter gestaltet: vier wichtige Statuswerte bleiben sichtbar;
  vollständige IDs, Zielpfad und Prüf-/Diagnoseaktionen liegen im standardmässig
  geschlossenen Bereich „Details und Prüfaktionen“. Auf-/Zuklappen ist auch per
  Tastatur möglich und bleibt bei automatischer Aktualisierung erhalten.
  Fehlerhinweis, offene Dienst-Wiederanläufe und geladene Prüfergebnisse bleiben
  ausserhalb des aufklappbaren Bereichs sichtbar. Responsive Browserprüfungen
  decken vier/zwei/eine Spalte und lange Zielpfade ab.
- Update-/Wiederinstallationsfehler korrigiert: PREROOT gibt nach Sicherung der
  Konfiguration ausschliesslich die alten Plugin-Bin-Verzeichnisse für
  LoxBerrys unprivilegierten Dateiaustausch frei. Geschützte Helferstände,
  Root-Status und Backups bleiben unberührt.
- POSTROOT prüft vor Aktivierung, dass `hostbackup.sh` das eigentliche
  Backup-Programm ist. Ein bei fehlgeschlagenem Dateiaustausch zurückgebliebenes
  Startskript darf den bisherigen funktionierenden Programmstand nicht ersetzen.
  Der Root-Einstieg weist solche falschen Programmstände ebenfalls sofort ab.
- Die Zeitplan-Einrichtung wartet höchstens 30 Sekunden (plus maximal 5 Sekunden
  zum Beenden), damit ein Fehler nicht unbegrenzt die Plugin-Installation sperrt.
- Linux-Regression ergänzt: tatsächliches Löschen/Kopieren als unprivilegierter
  Plattformbenutzer, Nachstellung des alten Kopierfehlers, Reparatur und erneute
  Installation derselben Version, unveränderte Einstellungen und alte Helferstände,
  Abweisung eines Startskripts als Backend und Schutz vor Symlink-Zielen.
- Die zuvor separat unter interner Version `0.7.0` bereitgestellten
  Testkorrekturen werden mit 0.7.1-beta als neues Pre-Release angeboten.
- Übersicht und Live-Status verwenden weisse Inhaltsflächen passend zu den
  Einstellungen. Beschriftungen und Werte in der Übersicht sind getrennt und
  bleiben auch ohne CSS durch Doppelpunkt und Leerzeichen lesbar.
- CSS und JavaScript erhalten inhaltsabhängige Ladeadressen. Damit werden
  aktualisierte Oberflächendateien auch bei unveränderter Plugin-Version neu
  geladen; alte Browser-Caches müssen nicht manuell geleert werden.
- Browserprüfung ergänzt um die tatsächlich vom CGI erzeugten Asset-Adressen,
  alte zwischengespeicherte Styles, weisse Flächen sowie Desktop-/Mobilabstände.

### Prüfung und offene Punkte

- Der zugrunde liegende Teststand `39254c6` bestand 191 Linux-Tests ohne Skips
  und 14 Browser-Prüfblöcke. Der Release-Tag durchläuft die Linux-Prüfungen vor
  Veröffentlichung erneut; Ergebnisse und Paketprüfsumme stehen beim Release.
- Speicherberechnung ohne Zwischenfortschritt und die unverständliche
  HTTP-500-Anzeige bei gesperrter Laufzeitdateien-Prüfung bleiben offen.
  Die Fehlerkette wurde isoliert nachgestellt, nicht live auf dem Nutzergerät.
- AP-14 bleibt ausgenommen. Vollständige Offline-Restore-/NAS-Hardwareabnahme
  bleibt separat erforderlich; ein erfolgreicher CI-Lauf ersetzt sie nicht.

## [0.7.0-beta] - 2026-09-13

### Versionierung und Update

- Neuer Pre-Release-Kanalstand mit interner Plugin-Version `0.7.0`, Tag
  `v0.7.0-beta` und Paket `LoxBerryHostBackup_0.7.0.zip`. LoxBerry kann ihn
  über `prerelease.cfg` als neues Update erkennen; Stable bleibt auf 0.5.8.
- Paketveröffentlichung nach erfolgreicher Linux-CI. Das ZIP von 0.7.0-beta
  wird für die unten dokumentierte Installationskorrektur unter demselben Namen
  ersetzt; ältere Releases bleiben unverändert. Ausführliche Updatehinweise in
  `docs/RELEASE-0.7.0-beta.md`.
- Einstellungen vor dem Update exportieren und danach kontrollieren.
  Änderungen stets vor manuellen und automatischen Backups speichern.
- Beim Umstieg von 0.5.8 und älter bleibt eine neue vollständige Basiskopie
  erforderlich; erst danach ist wieder inkrementelle Hardlink-Nutzung möglich.
  Eine vorhandene passende 0.6.x-Referenz wird nicht allein wegen der neuen
  Versionsnummer ausgeschlossen.

### Installationskorrektur ohne Versionswechsel - 2026-09-13

- POSTROOT-Abbruch `Unsafe trusted directory: /etc/cron.d` auf LoxBerry behoben.
  Der vorgesehene Root-eigene Symlink auf `system/cron/cron.d` wird akzeptiert;
  Ziel, Eigentümer und Schreibrechte bleiben geprüft. Unbekannte, defekte oder
  ungeschützte Verknüpfungen werden weiterhin abgelehnt.
- Nach dem zweiten Installationsprotokoll und der tatsächlichen Rechteausgabe
  ergänzt: Das vorgesehene Cron-Ziel mit `root:root 775` beziehungsweise `2775`
  wird unterstützt. Gruppenschreibrecht ist nur für GID 0 zulässig; fremde
  Eigentümer, andere schreibberechtigte Gruppen und Weltschreibrecht bleiben
  verboten. Die erste Symlink-Korrektur allein hatte diesen Fall nicht abgedeckt.
- Die Linux-Installationsmatrix bildet nun die Rechte `755`, `775`, `2755` und
  `2775` ab, reproduziert beide bisherigen Ablehnungen und prüft danach die
  vollständige Installation mit echtem Backend sowie die Neuinstallation
  derselben Version. Ausführbare Helfer bleiben auch bei Gruppenschreibrecht
  für `root` gesperrt; Cron-Dateien bleiben Root-eigen und `644`.
- Keine Änderung gemeinsamer LoxBerry-/Systemverzeichnisrechte und keine
  Lockerung des Schutzes ausführbarer Root-Helfer. Der Recovery-Cron-Eintrag
  wird über eine zufällige temporäre Datei atomar installiert.
- Linux-Installationstest mit echtem Backend ergänzt: normales Cron-Verzeichnis,
  LoxBerry-Symlink mit LoxBerry-eigenen Elternverzeichnissen, Zeitplaninstallation,
  erneute Installation derselben Version und Erhalt gespeicherter Einstellungen.
  Linux-Abnahme: alle 188 Tests ohne Skips und zehn Browser-Prüfblöcke bestanden.
- Plugin-Version `0.7.0`, Pre-Release `v0.7.0-beta` und ZIP-URL bleiben gleich.
  Nach einem Fehlversuch das frisch heruntergeladene ZIP erneut installieren;
  bei bereits eingetragener Version 0.7.0 gibt es keine höhere Updateversion.

### Daten- und Wiederherstellungssicherheit

- Restore übernimmt die beim Backup gespeicherten Ausschlüsse; rsync-Löschungen
  können ausgeschlossene Nutzdaten nicht mehr unabsichtlich entfernen.
- Echte Restore-Vorschau, ausdrückliches Offline-Ziel und Volume-Zuordnungen;
  Portable-Archive-Restore berücksichtigt Ausschlüsse und meldet Auslassungen.
- Dauerhafte lokale Dienst-Neustartjournale mit Eintrag vor dem Stoppen,
  Wiederanlauf bei fehlendem Backup-Medium, Boot-/Fünfminuten-Retry und Schutz
  vor verspäteten Stopps bereits abgeschlossener Backups.
- Privilegierte Helfer in atomar aktivierte, root-eigene Versionsverzeichnisse
  verschoben; Webaktionen bleiben über eine begrenzte Befehlsliste zugänglich.
- Import-Sidecars gegen Linkangriffe geschützt, Archivpfade effizient geprüft
  und importierte Strukturen/Manifestangaben lokal erneut plausibilisiert.
- Speichervergleich für eine neue Snapshot-Basiskopie und volle Inodes korrigiert;
  tägliche, wöchentliche und monatliche Starts verwenden denselben Prüfweg.
- Export-/Logdownloads werden aus root-geschützten Dateien über das Backend
  gestreamt. Exportprüfung und Ausgabe verwenden denselben geöffneten Dateideskriptor.
- Metadatenprobe führt eine echte Rückkopie durch; Snapshot-Wiederverwendung wird
  über identische Pfade mit übereinstimmendem Gerät/Inode gemessen.
- Fake-Super-Transfers umgehen den in der Linux-Abnahme erkannten rsync-3.2.7-
  Fehler lokaler `-M`-Optionen über einen fest definierten lokalen Transport
  ohne SSH oder Netzwerkdienst. Zwischenkopie und Zielinhalt werden geprüft.

### Bedienung und Erweiterungen

- Speicherhinweis, Absicherung ungespeicherter Änderungen, erneuerbare CSRF-Tokens,
  Prüfung widersprüchlicher Profil-/Zeitplaneinstellungen und frühe Uploadgrenzen.
- Startübersicht, Auftragshistorie und Sicherungsvorschau der gespeicherten
  Einstellungen mit Volumes, Ausschlüssen und Snapshot-Referenz.
- Lesbare, nicht umbrechende Live-Logzeilen, kontrolliertes Scrollen und vollständiger
  Logdownload; Hilfen und Bedienelemente funktionieren auch in nachgeladenen Ansichten.
- Speicherübersicht unterscheidet logische Grösse, Belegung, Hardlinks und Exporte.
- Einzeldatei-/Ordner-Restore in einen neuen Unterordner und Recovery-Blatt je Backup.
- Optionale Inhaltsprüfbasis, zeitgesteuerte Vergleichsprüfung und exportierbarer
  Prüfbericht; Prüfbasis, Inhaltsvergleich und echter Restoretest bleiben getrennt.
- Eigene externe Restoretests mit Datum, Ergebnis und Notiz lokal dokumentieren;
  eindeutig als persönliche Angabe gekennzeichnet, ohne Änderung der Restore-Freigabe.
- Anzahlaufbewahrung bis 3650 oder tägliche/wöchentliche/monatliche Aufbewahrung,
  Schutz einzelner Sicherungen und bestätigte Bereinigung mit Vorschau.
- Gesonderte Bereinigung alter Logs/Quarantäne und Diagnosepaket mit anonymisierter
  Konfiguration; ausgewählte Originalprotokolle müssen vor Weitergabe geprüft werden.

### Qualität und Abgrenzung

- Linux-Abnahme für 0.7.0-beta: 187 Tests ohne Skips, zehn Browser-Prüfblöcke,
  privilegierte Installation/Neustart-Rechte, Metadaten-Roundtrips und ZIP-Build
  erfolgreich; datierter Lauf im Umsetzungsbericht verlinkt.
- Verhaltenstests für Sicherheitsgrenzen, Abbrüche, Restore, Metadaten, Downloads,
  Wartung und Browserinteraktionen ergänzt; Linux-Integration in CI verpflichtend.
- README, Release Notes, Umsetzungsbericht und Disaster-Recovery-Testplan
  aktualisiert. Lokaler Gesamtlauf: 176 Tests mit 13 Windows-bedingten Skips;
  zehn echte Browser-Prüfblöcke und ShellCheck erfolgreich.
- Echte NAS- und vollständige Offline-Hardwaretests bleiben vor stabiler
  Freigabe erforderlich. Die Linux-CI-Ergebnisse stehen beim jeweiligen Release;
  automatisierte Fixtures ersetzen keinen realen System-Restore.
- `Network Compatible` bleibt ein bewusstes Profil ohne xattrs und File
  Capabilities: Der Hinweis blockiert weder manuelle noch zeitgesteuerte
  Backups und erfordert keine zusätzliche Startbestätigung.
- Die zurückgestellte AP-14 zur Mail-/Benachrichtigungssemantik bleibt unverändert.

## [0.6.1-beta] - 2026-08-02

### Versionierung

- Pre-Release-Version auf 0.6.1 angehoben, damit LoxBerry den korrigierten Stand
  als neues Plugin-Update erkennt und automatisch zur Installation anbietet.
- `prerelease.cfg` verweist auf den neuen Tag `v0.6.1-beta` und das Paket
  `LoxBerryHostBackup_0.6.1.zip`; der stabile Kanal bleibt auf Version 0.5.8.

### Neustart und Einstellungen

- Privilegierte Task-Logs liegen dauerhaft unter
  `/var/lib/loxberryhostbackup/logs`. Das von LoxBerry beim Boot gegebenenfalls
  neu erzeugte Plugin-Logverzeichnis darf plattformkonform
  `loxberry:loxberry` gehören und blockiert Konfiguration, Weboberfläche sowie
  automatische Backups nach einem Neustart nicht mehr.
- Schlägt das Laden der gespeicherten Konfiguration fehl, kennzeichnet die
  Oberfläche sichtbare Werte ausdrücklich als Ersatzwerte und sperrt Speichern,
  Export sowie Backup-Start. Eine vorhandene Konfiguration kann dadurch nicht
  versehentlich mit Standardwerten überschrieben werden.

### Backup und Live-Status

- Die Backup-Vorprüfung erkennt, wenn ein inkrementell konfigurierter Lauf ohne
  kompatible Hardlink-Referenz eine vollständige Basiskopie erstellen muss. Sie
  schätzt den Platzbedarf anhand des letzten abgeschlossenen Backups zuzüglich
  Reserve und blockiert bei eindeutig zu wenig Speicher, bevor Dienste oder
  Container gestoppt werden.
- Die Live-Loganzeige stellt `rsync`-Wagenrückläufe als echte Zeilenenden dar,
  entfernt reine Terminal-Steuerzeichen und verhindert automatische
  Zeilenumbrüche. Alle Fortschrittsmeldungen bleiben erhalten; lange Zeilen sind
  horizontal scrollbar.

### Qualität

- Ein Root-Rechte-Test simuliert das von LoxBerry nach einem Neustart mit
  `loxberry`-Besitz angelegte Plugin-Logverzeichnis und prüft, dass die
  gespeicherte Konfiguration sowie die Task-Abfragen weiterhin funktionieren.

## [0.6.0-beta] - 2026-08-02

### Versionierung

- Entwicklungsstand auf Version 0.6.0 angehoben und als `0.6.0-beta` für den
  Pre-Release-Kanal vorbereitet.
- `prerelease.cfg` verweist auf den Tag `v0.6.0-beta` und das Paket
  `LoxBerryHostBackup_0.6.0.zip`; der stabile Kanal in `release.cfg` bleibt auf
  Version 0.5.8.

### Sicherheit

- Privilegierte Installationsschritte in den von LoxBerry als Root gestarteten
  Hook `postroot.sh` verschoben; `postinstall.sh` benötigt keine Root-Rechte
  mehr.
- Bestehende `config.json` wird beim Upgrade im Root-Hook gesichert und nach der
  Installation mit geschützten Besitzrechten wiederhergestellt.
- Die Wiederherstellung der gesicherten Einstellungen erfolgt nun bereits zu
  Beginn von `postroot.sh`, damit nachfolgende Installationsprüfungen keinen
  sichtbaren Rückfall auf die mitgelieferten Standardwerte verursachen.
- Das gesicherte Konfigurationsverzeichnis wird für die eigentliche
  LoxBerry-Aktualisierung kontrolliert an den Benutzer `loxberry` übergeben und
  die systemweiten Basisvariablen `LBPCONFIG`, `LBPDATA` und `LBPLOG` werden
  korrekt um den Plugin-Unterordner ergänzt.
- Privilegierte Webaktionen auf einen root-eigenen Dispatcher mit fester
  Aktionsliste und bereinigter Umgebung begrenzt; direkte sudoers-Freigabe des
  Plugin-Backends entfernt.
- Backup-Ziele an Marker und Mount-Identität gebunden; kanonische Pfad- und
  Symlink-Prüfungen vor Schreiben, Import, Export, Restore und Löschen ergänzt.
- Globale und Backup-spezifische Locks sowie atomare Task-State-Dateien mit
  PID-Startzeit eingeführt.
- CSRF-Schutz für alle POST-Aktionen, begrenzte Streaming-Uploads und gehärtete
  Tar-Importprüfung gegen Traversal, Link-Angriffe, Duplikate und Archive-Bombs
  ergänzt.
- Konfiguration root-eigen, atomar und fail-closed gespeichert; unsichere
  Helper-Include-Pfade entfernt.

### Backup und Restore

- Metadatenprofile `Native Strict`, `Network Compatible`, `Fake Super` und
  `Portable Archive` mit Ziel-Roundtrip und sichtbarer Fidelitätsangabe ergänzt.
- Als Hardlink-Referenz für inkrementelle Snapshots werden nur erfolgreich
  validierte Backups mit demselben Metadaten-Profil verwendet. Backups aus
  Version 0.5.8 und älter enthalten diese Profilinformation noch nicht und
  werden deshalb nicht als `--link-dest` ausgewählt. Der erste inkrementelle
  Lauf nach dem Update erstellt in diesem Fall nochmals eine vollständige
  Basiskopie; der darauffolgende erfolgreiche Lauf kann den neuen Stand wieder
  inkrementell verwenden.
- CIFS-/NFS-kompatibler Modus lässt xattrs und File Capabilities bewusst aus,
  zeigt dies beim erfolgreichen Backup nur als neutralen Hinweis und blockiert
  weder manuelle noch zeitgesteuerte Starts; beim Restore bleibt die separate
  Bestätigung erhalten.
- Backup erst nach erfolgreicher Validierung finalisiert; Exit-Code 24 wird als
  sichtbarer Hinweis behandelt, andere rsync-Fehler bleiben Fehler.
- Restore auf finalisierte, validierte Backups begrenzt, Restore-ID-Challenge,
  Quellschutz, Dry-Run, strikte Exit-Auswertung und Offline-Gate für Portable
  Archive ergänzt.
- Stop-/Restart- und Hook-Ablauf fail-closed und mit überprüfbarem Cleanup-Status
  umgesetzt.

### Import, Export und Qualität

- Exporte enthalten Metadaten, SHA-256-Prüfsumme und einen Descriptor mit Hash
  des finalen Manifests.
- Importe werden in root-eigenem Staging geprüft und erst nach Manifest-,
  Validierungs- und Markerprüfung atomar veröffentlicht.
- UI-Status für Backup, Restore, Import, Export und `cleanup_failed` präzisiert.
- Automatisierte Archiv-/Web-Sicherheitstests, Shell-/Perl-/PHP-/sudoers-Checks,
  least-privilege CI und ein verbindlicher Disaster-Recovery-Testplan ergänzt.
- Installationspakete schließen generierte Python-Cachedateien zuverlässig aus.
- Kurzanleitung um Ziel-Speichern, Metadaten-Profil und automatische Zeitpläne
  ergänzt; die vier Profilkarten beschreiben Ziel, Umfang und Einschränkungen
  nun entscheidungsorientiert.
- Info-Beschreibungen werden an den sichtbaren Browserbereich angepasst und
  nicht mehr am rechten oder unteren Fensterrand abgeschnitten.
- Ein noch nicht konfiguriertes Backup-Verzeichnis wird als neutraler Hinweis
  statt als fehlgeschlagene Dateisystem-Prüfung dargestellt; echte technische
  Ladefehler bleiben davon klar unterscheidbar.
- Die Bestätigung zum Start trotz Preflight-Warnhinweisen ist standardmäßig
  ausgeblendet und erscheint erst, nachdem tatsächlich eine übergehbare Warnung
  erkannt wurde; die Warnung wird dabei getrennt von echten Fehlern angezeigt.
- Das Metadaten-Profil kennzeichnet `Native Strict` sichtbar als
  Standardeinstellung. Jede der vier Auswahlmöglichkeiten besitzt nun einen
  eigenen, ausführlichen Info-Button; die Karten selbst bleiben kompakt und
  nennen den vorgesehenen Zieltyp.
- Nach jeder noch nicht gespeicherten Einstellungsänderung erscheint ein
  nicht blockierender Speicherhinweis mit geändertem Bereich, neuem Wert,
  Uhrzeit und direkter Speicheraktion. Auch Radio-Auswahlen wie das
  Metadaten-Profil sowie dynamisch geladene Dienst-/Container-Ziele werden
  erfasst; beim Zurückstellen auf den Ausgangswert verschwindet der Eintrag.
- Die JavaScript-Ausgabe des Speicherhinweises berücksichtigt die Escape-
  Verarbeitung des Perl-CGI-Heredocs. Dadurch starten Dateisystemprüfung,
  Backup-Liste und Dienst-/Container-Auswahl wieder zuverlässig; ein Test prüft
  nun zusätzlich die Syntax des tatsächlich an den Browser ausgegebenen Codes.

Die bestehende Benachrichtigungs- und Mailsemantik ist in diesem Stand bewusst
nicht überarbeitet worden.

## [0.5.8] - 2026-06-22

### Release

- Version 0.5.8 als Release-Kanal bereitgestellt.
- `release.cfg` auf das stabile Release-ZIP `v0.5.8` aktualisiert.
- Enthält die Korrekturen aus `0.5.8-beta` für den robusteren Export-Live-Status.

## [0.5.8-beta] - 2026-06-22

### Stabilität

- Export-Live-Status robuster gemacht: Export-Logs werden vor dem Hintergrundjob sicher angelegt, fehlende Export-Logs werden über `export-info` abgefangen und laufende Export-Neuerstellungen werden zuverlässig als `running` erkannt.

## [0.5.7] - 2026-06-22

### Release

- Version 0.5.7 als Release-Kanal bereitgestellt.
- `release.cfg` auf das stabile Release-ZIP `v0.5.7` aktualisiert.
- Enthält die Korrekturen aus `0.5.7-beta` für Detailansichten, Export/Import und Konfigurationsimport.

## [0.5.7-beta] - 2026-06-22

### Stabilität

- Detailansichten für Datei-Explorer und Restore schliessen nun über eine robuste Basis-URL ohne alte Query-Parameter.
- Export-Neuerstellungen werden in der Backup-Liste und in `export-info` korrekt als laufend angezeigt, auch wenn noch ein altes Export-Archiv vorhanden ist.
- Export-Archiv-Löschung ist gegen gleichzeitig laufende Export-Jobs gesperrt.
- Lange Export- und Import-Jobs schreiben Heartbeat-Einträge ins Log, damit der Live-Status nicht fälschlich als veraltet erscheint.
- Hintergrund-Importe akzeptieren nur noch zuvor im Plugin-Staging abgelegte `.tar.gz`-Archive.
- Importierte Plugin-Einstellungen übernehmen die Root-Freigabe nicht mehr automatisch; sie muss nach dem Import erneut bestätigt werden.

## [0.5.6-beta] - 2026-06-21

### Weboberfläche

- Aktion `Ansicht schliessen` und `Restore-Auswahl schliessen` korrigiert, damit Datei-Explorer und Restore-Auswahl eine saubere URL ohne `browse_id` oder `restore_id` verwenden und wirklich ausgeblendet werden.

## [0.5.5-beta] - 2026-06-21

### Paketierung

- Pre-Release-Paket neu erstellt, damit die ZIP-Einträge Unix-Pfade mit `/` verwenden und von LoxBerry sauber entpackt werden können.
- Windows-Paketierungsskript korrigiert, damit künftige Builds keine Backslash-Pfade im ZIP erzeugen.

## [0.5.4-beta] - 2026-06-21

### Weboberfläche

- Aktion `Ansicht schliessen` und `Restore-Auswahl schliessen` korrigiert, damit Datei-Explorer und Restore-Auswahl wieder vollständig ausgeblendet werden.
- Infotext für `Export neu erstellen` ergänzt, damit klar ist, dass nur das tar.gz-Exportarchiv neu erzeugt wird und der Backup-Snapshot unverändert bleibt.

## [0.5.3-beta] - 2026-06-21

### Weboberfläche

- Aktion `Ansicht schliessen` und `Restore-Auswahl schliessen` robuster gemacht, damit Detailansichten wieder korrekt geschlossen werden.
- Export-Aktionen eindeutiger beschriftet: Download, Neuerstellung und Löschung des Export-Archivs sind klar getrennt.
- Separates Löschen eines vorhandenen `.tar.gz`-Exportarchivs ergänzt, ohne den eigentlichen Backup-Snapshot zu entfernen.
- Export-Status in der Backup-Liste lesbarer dargestellt.

## [0.5.2] - 2026-06-20

### Release

- Version 0.5.2 als stabilen Release-Kanal bereitgestellt.
- `release.cfg` auf das stabile Release-ZIP `v0.5.2` aktualisiert.

## [0.5.2-beta] - 2026-06-20

### Update-Kanal

- Pre-Release-CFG-URL im Plugin auf die präzisere `refs/heads/develop`-Adresse umgestellt.
- Pre-Release-Metadaten auf ein neues ZIP-Paket aktualisiert, damit LoxBerry die aktuelle Version eindeutig erkennt.

## [0.5.1-beta] - 2026-06-20

### Weboberfläche

- Einrichtungs-Wizard in Kurzanleitung umbenannt.
- Kurzanleitung produktiver formuliert und um Restore-Konzept ergänzt.
- Sichtbare Texte im betroffenen UI-Bereich auf echte Umlaute vereinheitlicht.

## [0.5.0-beta] - 2026-06-20

### Import und Export

- Export vorhandener Backups läuft nun als Hintergrundjob mit Live-Status,
  damit grosse `.tar.gz`-Archive keinen Browser- oder Webserver-Timeout mehr
  auslösen.
- Export-Archive werden zuerst als temporäre Datei erstellt, per `tar -tzf`
  geprüft und danach atomar auf den finalen Archivnamen verschoben.
- Die Backup-Liste zeigt Exportstatus, Archivgrösse und Archivpfad an.
- Import externer Backup-Archive läuft nun ebenfalls als Hintergrundjob mit
  Live-Status. Hochgeladene Importdateien werden nach erfolgreichem Import oder
  bei Fehlern automatisch bereinigt.

### Weboberflaeche

- Datei-Explorer und Restore-Auswahl können direkt wieder geschlossen werden.
- Eine kompakte Kurzanleitung erklärt die wichtigsten Schritte für Backup-Ziel,
  Ausschlüsse, Backup-Modus, Stop-Ziele, Erstkontrolle und Restore-Konzept.

## [0.4.3] - 2026-06-02

### Benachrichtigung

- Mailbenachrichtigungen ueber die zentrale LoxBerry-Benachrichtigung ergaenzt.
- Optionale Empfaengeradresse im Plugin: Wenn leer, verwendet LoxBerry die globale Standardadresse.
- Erfolgreiche Backups senden nun nur noch eine Mail und erzeugen keinen zusaetzlichen Eintrag in der LoxBerry-Notification-Uebersicht.
- Fehler, Abbruch und Restore-Ereignisse bleiben als LoxBerry-Notifications sichtbar.

## [0.4.2] - 2026-05-31

### Weboberflaeche

- Backup-Zielauswahl ueberarbeitet und optisch an die restliche LoxBerry-Oberflaeche angepasst.
- Aufklappbare Bereiche für Backup-Ziele, Zeitplan, Stop-Ziele und Backup-Verwaltung weiter vereinheitlicht.
- Manuelle Korrekturen aus `develop` uebernommen und README sowie Update-Metadaten auf Version 0.4.2 nachgezogen.

## [0.4.1] - 2026-05-25

### Weboberfläche

- Der Datei-Explorer erklärt nun kurz, warum inkrementelle Snapshots trotz
  vollständiger Ansicht nur wenig zusätzlichen Speicher belegen können.

## [0.4.0] - 2026-05-25

### Backup-Konsistenz

- Neue Auswahl für Stop-Ziele ergänzt: Docker-Container und systemd-Dienste
  werden erkannt, in Gruppen angezeigt und können einzeln für das Backup
  ausgewählt werden.
- Das Plugin stoppt nur ausgewählte Ziele, die vor dem Backup wirklich liefen,
  und startet genau diese Ziele nach erfolgreichem Backup, Fehler oder manuellem
  Abbruch wieder.
- Gestoppte Docker-Container und systemd-Dienste werden im Backup-Manifest und
  im Log protokolliert, damit nachvollziehbar bleibt, welche Ziele wieder
  gestartet werden mussten.
- Bei manuellem Abbruch wird das Backup als `stopped` markiert. Die
  Weboberfläche fragt anschliessend, ob das unvollständige Backup direkt
  gelöscht werden soll.
- LoxBerry-nahe Dienste werden separat gruppiert; kritische Systemdienste wie
  Netzwerk, Webserver, SSH, Docker-Daemon und systemd-Basisdienste werden nicht
  zur Auswahl angeboten.

### Weboberfläche

- Die Dienst-/Container-Auswahl wird per AJAX nachgeladen, damit die
  Einstellungsseite weiterhin schnell sichtbar bleibt.
- Die Dienst-/Container-Auswahl ist kompakter, pro Rubrik einklappbar und
  blendet kritische LoxBerry-, Web-, SSH- und Backup-Dienste aus.
- Die erweiterten Zeitplanfelder `Tage im Monat`, `Monate` und die Stop-Ziele
  sind standardmässig eingeklappt, damit die Einstellungsseite übersichtlich
  bleibt.
- LoxBerry-Plugins ohne eigenen sicher steuerbaren Dienst werden nicht als
  Stop-Ziel angeboten, um unzuverlässige Stop-/Start-Aktionen zu vermeiden.
- Neuer Button `Empfohlene Auswahl setzen` markiert laufende Docker-Container
  und typische datenintensive Dienste wie Datenbanken, MQTT/Zigbee, Node-RED,
  Stats4Lox, Grafana oder InfluxDB.
- Löschdialoge und Ladehinweise weisen jetzt darauf hin, dass das Entfernen
  grosser Backups auf langsamen Datenträgern mehrere Minuten dauern kann.
- Das Nachladen von Dateisystem-Prüfung, Backup-Liste und Stop-Zielen wurde
  robuster gemacht und nutzt wieder kompatible JavaScript-Techniken ohne
  `fetch`/`NodeList.forEach` im initialen Ladepfad.

## [0.3.2] - 2026-05-25

### Weboberfläche

- Layout der Einstellungsbereiche weiter vereinheitlicht und an die Backup-
  Verwaltung angeglichen.
- Konfigurationsbuttons optisch an die bestehenden Backup-Import-Controls
  angepasst.
- Restore-Bereich in denselben Innenrahmen wie die Backup-Verwaltung gesetzt.
- Texte und Info-Hinweise auf Schweizer Schreibweise ohne scharfes S
  vereinheitlicht.

## [0.3.1] - 2026-05-25

### Weboberfläche

- Weboberfläche auf die LoxBerry-Standard-Einbettung mit
  `LoxBerry::Web::lbheader` und `lbfooter` umgestellt. Dadurch bleiben die
  LoxBerry-Navigation, das Haus-Symbol und die Kopfzeile sichtbar.
- Separaten Button `Zurück zu LoxBerry` entfernt, da die Navigation nun wieder
  über die LoxBerry-Kopfzeile erfolgt.
- Konfigurationsaktionen in eine eigene Rubrik `Konfiguration verwalten`
  verschoben.
- Bereichsflächen und Backup-Tabelle optisch näher an neutrale LoxBerry-
  Grautöne angeglichen.
- Backup-Liste und Dateisystem-Prüfung werden nach dem Seitenaufbau per
  AJAX nachgeladen, damit die Weboberfläche schneller sichtbar ist.
- Info-Buttons, Restore-Bereich, Konfigurationsaktionen und die
  Dateisystem-Hinweise konsistent nachgezogen und alte zu breite
  Eingabe-/Button-Regeln entschärft.

## [0.3.0] - 2026-05-24

### Geändert

- Version auf die erste vorsichtig freigegebene Fassung angehoben.
- Stable- und Pre-Release-Updatekanal zeigen auf das freigegebene Paket.
- Plugin-Metadaten bereinigt und doppelte Auto-Update-Einträge entfernt.
- Lokale Build- und Testaltlasten aus dem Arbeitsstand entfernt.
- Live-Log für schnelle inkrementelle Backups entschärft: rsync sendet weniger
  Dateinamen und die Weboberfläche liest pro Statusabfrage nur einen begrenzten
  Log-Ausschnitt.
- Aufbewahrung bei inkrementellen Snapshots in Oberfläche und README genauer
  erklärt.

## [0.2.0] - 2026-05-24

### Hinweis

- Erste vorsichtige Beta-/Testversion.
- Installation, Konfiguration, Vollbackup und inkrementelle Snapshot-Backups
  wurden auf einem LoxBerry-/DietPi-Testsystem geprüft.
- Inkrementelle Snapshots wurden auf `ext4` mit Hardlinks und deutlicher
  Speicherersparnis erfolgreich geprüft.
- Ein produktiver Ende-zu-Ende-Restore auf ein frisch installiertes Zielsystem
  steht noch aus.

### Dokumentation

- README vollständig auf den aktuellen Funktionsstand gebracht.
- Installations-, Ersttest- und Bedienablauf so ergänzt, dass eine fremde Person
  das Plugin installieren, konfigurieren und testen kann.
- Status klarer beschrieben: Installation, Konfiguration und echte Backups sind
  getestet; ein produktiver Ende-zu-Ende-Restore ist noch offen.
- USB-Beispiel für Backup-Ziel und Ausschlüsse ergänzt.
- Vollbackup, inkrementeller Snapshot, erster Snapshot als Basiskopie und
  Hardlink-Voraussetzungen dokumentiert.
- Live-Status, Backup-Liste, Explorer, Export, Löschen, Import externer
  Archive und Restore-Auswahl beschrieben.
- Verhalten laufender oder unvollständiger Backups dokumentiert.
- Einstellungen-Export/-Import und Grenzen von Export-Archiven beschrieben.
- Deinstallation und verbleibende externe Backup-Daten dokumentiert.

### LoxBerry-Kompatibilität

- Sudoers-Regel in den LoxBerry-Standardordner `sudoers/sudoers` verschoben,
  damit LoxBerry sie während der Plugin-Installation selbst installiert.
- `postinstall.sh` schreibt nicht mehr direkt nach `/etc/sudoers.d`, da das
  Postinstall-Skript auf LoxBerry ohne Root-Rechte laufen kann.
- `uninstall.sh` entfernt den Cron-Eintrag defensiv; die sudoers-Datei wird von
  LoxBerry verwaltet.
- `postinstall.sh` in den ZIP-Root verschoben, damit LoxBerry das Skript korrekt
  ausführt.
- Restore-Helper von `sbin/` nach `bin/` verschoben, da LoxBerry `sbin/` beim
  Test nicht installiert hat.
- Plugin-Icons ergänzt, damit LoxBerry keine Default-Icon-Warnung ausgeben muss.
- Offizielle LoxBerry-Plugin-Pfadvariablen berücksichtigt.
- Skriptpfad-basierte Erkennung des tatsächlichen Pluginordners ergänzt.
- Default-Konfiguration in das Plugin-Verzeichnis `config/` verschoben.
- `postinstall.sh` nutzt LoxBerry-Installationsargumente für Pluginordner und
  Basisverzeichnis.
- Web-Backend-Aufrufe verwenden `sudo -n`, damit fehlende sudoers-Regeln nicht
  hängen bleiben.

### Planung Und Aufbewahrung

- Zeitgesteuerte Backups per `/etc/cron.d/loxberryhostbackup` ergänzt.
- Auswahl für tägliche, wöchentliche und monatliche Backups ergänzt.
- Wöchentlicher Zeitplan kann mehrere Wochentage speichern und als Cron-Liste
  ausgeben.
- Monatlicher Zeitplan kann mehrere Monatstage sowie einzelne Monate speichern
  und als Cron-Liste ausgeben.
- Monatliche Backups erhalten einen Fallback auf den letzten Tag des Monats,
  wenn ein gewählter Monatstag wie 29, 30 oder 31 im jeweiligen Monat nicht
  existiert.
- Der Cron-Aufruf bleibt beim Monatsende-Fallback auf die relevanten
  Monatsend-Tage begrenzt.
- Info-Texte zum Zeitplan erklären detailliert, welche Felder bei täglich,
  wöchentlich und monatlich relevant sind.
- Zeitplan-Oberfläche klarer strukturiert.
- Aufbewahrung auf 1 bis 10 Backups begrenzt.
- Retention-Regel ergänzt: Bei gesetztem Limit werden nach erfolgreichem Backup
  alte Backups entfernt.
- Retention berücksichtigt nur vollständig abgeschlossene Backups mit
  `manifest.json`-Status `complete`, damit laufende oder unvollständige
  Backups nicht versehentlich in die normale Rotation fallen.
- Cron-Eintrag wird bei Deinstallation entfernt.

### Weboberfläche

- Dateisystem-Prüfung für das Backup-Verzeichnis ergänzt. Die Oberfläche zeigt
  den erkannten Dateisystemtyp, Mount und freien Speicher an und warnt bei
  NTFS/FUSE bzw. nicht typischen Linux-Dateisystemen, besonders für
  inkrementelle Snapshots. Der Hinweis nennt zusätzlich, dass `ext4` in der
  Praxis deutlich schneller als NTFS/FUSE sein kann.
- Kopfbereich mit Plugin-Icon, kompakter Titelgestaltung und Link zurück zur
  LoxBerry-Administration überarbeitet.
- Sichtbare deutsche Texte in der Weboberfläche auf echte Umlaute vereinheitlicht.
- Einstellungen-Seite ergänzt.
- Backup-Verzeichnis, Backup-Modus, Ausschlüsse, Docker-Verhalten, automatische
  Exporte, Retention, Zeitplan und Hooks konfigurierbar gemacht.
- Backup-Modus kann zwischen Vollbackup und inkrementellem Snapshot gewählt
  werden.
- Einstellungen können als JSON-Datei exportiert und nach einer Neuinstallation
  wieder importiert werden.
- Info-Buttons mit Hover-/Fokus-Hinweisen für Einstellungen und Backup-Aktionen
  ergänzt.
- Sicherheitsbestätigung für Root-Freigaben ergänzt.
- Backup- und Restore-Start prüfen, ob die Root-Freigabe zuvor bestätigt wurde.
- Live-Loganzeige für laufende Backup- und Restore-Jobs ergänzt.
- Live-Status unterscheidet laufende, abgeschlossene, fehlgeschlagene und
  gestoppte Jobs klarer.
- Live-Status stoppt die Aktualisierungsanzeige nach Abschluss und lädt die
  Backup-Liste danach neu.
- Live-Status bleibt erhalten, wenn während eines laufenden Backups ein anderes
  vollständiges Backup im Explorer geöffnet wird.
- Stop-Button im Live-Status ergänzt, um laufende Backups abbrechen zu können.
- Backup-Liste zeigt Status, Host, Grösse, Dateianzahl, Abschlusszeit,
  Exportstatus und Aktionen.
- Aktionen für laufende oder unvollständige Backups werden gesperrt, bis das
  Backup vollständig abgeschlossen ist.
- Backup-Liste um Aktionen für Dateien anzeigen, Restore auswählen, Export
  herunterladen und Löschen erweitert.
- Backup-Liste um Lösch-Button pro Backup mit Bestätigungsdialog ergänzt.
- Import-Bereich klarer als Import externer `tar.gz`-Backup-Archive benannt.
- Restore-Bereich wird nur noch angezeigt, wenn ein Backup für Restore
  ausgewählt wurde.
- Restore-Bereich mit Backup-Auswahl, Restore-Check, Restore-Plan und
  Startbestätigung aus der Backup-Liste ergänzt.
- Sichtbare Ladeanzeige für längere Formularaktionen ergänzt.
- Formularaktionen leiten nach erfolgreichem Speichern oder Backup-Start auf
  eine normale Seite weiter, damit der Browser beim Aktualisieren keine erneute
  Formularübermittlung anbietet.

### Backend

- `rsync`-basiertes Host-Backup ergänzt.
- Inkrementeller Snapshot-Modus mit `rsync --link-dest` ergänzt; jeder Snapshot
  bleibt direkt restore-fähig.
- Wenn noch kein vorheriges vollständiges Backup existiert, wird der erste
  Snapshot automatisch als vollständige Basiskopie erstellt.
- Preflight-Check warnt bei Snapshot-Modus, wenn das Backup-Ziel kein typisches
  Linux-Dateisystem für Hardlinks ist.
- Restore-Backend ergänzt.
- Manifest pro Backup ergänzt.
- Paketliste, systemd-Service-Liste, Mount-Liste und Docker-Inventar ergänzt.
- Backup- und Restore-Logs geben mehr Live-Fortschritt aus:
  Phasenmeldungen, rsync-Datei-/Fortschrittsausgabe, Export- und
  Retention-Schritte.
- Abschlussmeldung und `complete`-Manifest werden erst nach Export-Archiv und
  Aufbewahrungsregel geschrieben.
- Backup-Liste kann Status, Abschlusszeit, Grösse und Dateianzahl aus Logdateien
  und Backup-Ordnern ableiten, wenn `manifest.json` fehlt oder veraltet ist.
- Docker-Stop/Start protokolliert Container-Namen und IDs, arbeitet
  containerweise und nutzt Timeouts, wenn verfügbar.
- Backend-Kommando zum Stoppen laufender Backups ergänzt; zuvor durch das Backup
  gestoppte Docker-Container werden danach wieder gestartet.
- Task-Log-Suche auf mehrere LoxBerry-Logpfade erweitert.
- Sicherheitsprüfungen für Backup-IDs zentralisiert und auf Export, Import,
  Move, Explorer, Delete und Restore angewendet.
- Importierte Tar-Archive werden enger geprüft: nur ein sicherer
  Top-Level-Backupordner, keine absoluten Pfade und keine `..`-Pfade.
- Tar-Aufrufe für Export/Import gehärtet.
- Pre-/Post-Backup-Hooks werden nur ausgeführt, wenn sie Root gehören,
  ausführbar sind und nicht von Gruppe/anderen beschreibbar sind.

### Paketierung

- Plugin-ZIP-Build per `package.ps1` ergänzt.
- Plugin-ZIP-Build per `package.sh` für Linux/GitHub Actions ergänzt.
- GitHub Actions Workflow für automatischen ZIP-Build und Release-Asset-Upload
  ergänzt.
- `release.cfg` und `prerelease.cfg` für LoxBerry-Updates ergänzt.
- Installierbares ZIP zunächst nur über den GitHub-Pre-Release-Kanal vorgesehen.
- `.gitattributes` für passende Zeilenenden ergänzt.
- `.gitignore` für lokale Test- und Build-Artefakte ergänzt.

## [0.1.0] - Entwicklungsversion

### Hinweis

- Früher interner Entwicklungsstand vor der Beta-/Testversion 0.2.0.
- Nur für Tests auf nicht-kritischen Systemen vorgesehen.

[Unreleased]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/compare/v1.1.0-beta...develop
[1.1.0-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.1.0-beta
[1.0.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.0.0
[0.7.1-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.1-beta
[0.7.0-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.0-beta
[0.6.1-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.6.1-beta
[0.6.0-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.6.0-beta
[0.5.8]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.8
[0.5.8-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.8-beta
[0.5.7]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.7
[0.5.7-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.7-beta
[0.5.6-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.6-beta
[0.5.5-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.5-beta
[0.5.4-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.4-beta
[0.5.3-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.3-beta
[0.5.2]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.2
[0.5.2-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.2-beta
[0.5.1-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.1-beta
[0.5.0-beta]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.5.0-beta
[0.4.3]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.3
[0.4.2]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.2
[0.4.1]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.1
[0.4.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.4.0
[0.3.2]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.3.2
[0.3.1]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.3.1
[0.3.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.3.0
[0.2.0]: https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.2.0-beta
