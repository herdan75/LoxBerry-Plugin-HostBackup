# LoxBerry Host Backup 1.2.0

Reguläres Release vom 04.10.2026 auf `main`, Tag **v1.2.0**.
Plugin- und Paketversion: **1.2.0**, ohne Beta-Zusatz.

## Herkunft und Umfang

Der vollständige Stand der Vorabversion auf `develop`, Commit
`af2d55dd15d05d853f8a0b8627a7b64c2943f7e0`, wird auf `main` übernommen.
Gegenüber diesem Stand ändern sich nur Updatekanäle, zugehörige Regressionstests
und Dokumentation. Backup-, Restore-, Repository-, Aufbewahrungs- und
Benachrichtigungsabläufe bleiben unverändert.

Die reguläre Freigabe ersetzt keinen eigenen Restore-Test und stellt keine
pauschale Kompatibilitätszusage für jedes NAS oder jede Hardware dar.

## Neu gegenüber dem regulären Release 1.0.0

- **Portable, platzsparende NAS-Sicherungsstände:** Ein verschlüsseltes
  Repository verwendet unveränderte Datenblöcke erneut. Der erste Stand
  benötigt eine vollständige Basis; spätere Stände beschreiben jeweils den
  vollständigen ausgewählten Dateibaum, benötigen aber die gemeinsame Datenbasis.
  Das eigenständige portable TAR-Vollbackup bleibt verfügbar.
- **Metadaten im Backupformat:** Linux-Eigentümer, Rechte, ACLs, xattrs und Links
  müssen bei portablen Sicherungen nicht als native Eigenschaften jeder Datei
  auf dem NAS funktionieren. Die eigene Zielprüfung bleibt verbindlich.
- **Vier verständlich benannte Sicherungsverfahren:** Linux-Dateisicherung
  (bisher Native Strict), Portable Sicherung (Portable Archive), Dateisicherung
  mit reduzierten Metadaten (Network Compatible) und Metadaten in Dateiattributen
  speichern (Fake Super). Die beiden Spezialverfahren stehen unter erweiterten
  Einstellungen. Es gibt weiterhin Vollbackups und platzsparende Sicherungsstände.
- **Explizite Datenquellenauswahl:** Neue Konfigurationen beziehen lokale
  Laufwerke und nur einzeln gewählte Netzfreigaben ein. Vorhandene Einstellungen
  bleiben erhalten. Automount-Sammelbereiche werden nicht pauschal aktiviert;
  eine gewählte, fehlende Quelle verhindert den Start statt still zu fehlen.
- **Bessere NAS-Diagnose:** Metadatenprüfungen zeigen einzelne Schritte,
  Soll-/Ist-Werte und Werkzeugfehler. Echte Metadatenfehler werden nicht ignoriert.
- **Robustere Installation:** Gesicherte Konfiguration, sichere Vorbereitung
  geschützter Restdateien und Prüfung des echten Backends vor seiner Aktivierung.
- **Überarbeitete Oberfläche und Hilfen:** Kompakte Datenquellenansicht,
  technische Einbindungen in aufklappbaren Details, kontextbezogene Infobuttons,
  passende Einordnung von Repository-Einrichtung, Zusatzexport und Aufbewahrung.
  Kurzanleitung und Dokumentation erklären den vollständigen Einrichtungsweg.

## Download und Installation

[**LoxBerryHostBackup_1.2.0.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.0/LoxBerryHostBackup_1.2.0.zip)

- Reguläres GitHub-Release, **kein Pre-Release**. Für den öffentlichen Download
  ist keine GitHub-Anmeldung nötig.
- Das öffentliche Plugin-ZIP **ohne Entpacken** installieren. Bei einem
  GitHub-Actions-Artefakt hingegen nur den äusseren ZIP-Umschlag entpacken.
- In der LoxBerry-Pluginverwaltung den regulären Kanal verwenden und nach
  Updates suchen. Die automatische Installation hängt von den persönlichen
  LoxBerry-Einstellungen ab. **Nicht vorher deinstallieren.**
- Beide entfernten Updatekanäle werden nach erfolgreicher öffentlicher
  Downloadprüfung auf das reguläre Paket gesetzt. Der Vorabkanal folgt diesem
  Stand, solange keine neuere Vorabversion veröffentlicht wird.
- Bereits installierte **1.2.0-beta**- und gleich nummerierte Testpakete tragen
  intern ebenfalls **1.2.0**. Daher kein höheres automatisches Update-Angebot;
  das stabile ZIP bei Bedarf manuell darüber installieren. Der Programmstand
  bleibt gleich, Release-Dokumentation und Kanalmetadaten werden aktualisiert.
- Ältere Release-Tags und ZIPs bleiben unverändert erhalten. Wiki und Forum
  werden durch einen Git-Push nicht automatisch bearbeitet.

Vor dem Update laufende Vorgänge beenden lassen, Plugin-Einstellungen exportieren
und bewährte Sicherungen behalten. Bei vorhandenen Repository-Ständen die externe
Wiederherstellungsdatei bereithalten; der Konfigurationsexport enthält den Schlüssel
nicht. Anschliessend Ziel, Quellen, Ausschlüsse, Verfahren, Dienste und Zeitplan
prüfen. Änderungen speichern, **Nächstes Backup prüfen** ausführen und ein
manuelles Testbackup einschliesslich Dienst-Wiederanlauf kontrollieren.

Das Update stellt weder das Sicherungsverfahren noch die Datenquellen-Grundregel
automatisch um und wandelt vorhandene Vollarchive nicht in Repository-Stände um.

## Portable Sicherungsstände einrichten

Für eigenständige portable Vollarchive ist diese Einrichtung nicht erforderlich.

1. **Portable Sicherung** und zunächst **Vollbackup** wählen. Das tatsächlich
   eingebundene Backup-Ziel und die Root-Freigabe speichern.
2. Beim Sicherungsverfahren die Einrichtung öffnen und das Repository am
   gespeicherten Ziel ausdrücklich einrichten.
3. Die **geheime Wiederherstellungsdatei herunterladen**, ausserhalb des LoxBerry
   vertraulich aufbewahren und die sichere Aufbewahrung separat bestätigen.
4. **Platzsparende Sicherungsstände** wählen. Unter **Sicherungsart / Zusatzexport**
   den automatischen tar.gz-Export ausdrücklich deaktivieren.
5. Speichern, Zielvorprüfung durchführen und ein manuelles Testbackup abschliessen.

Die [Repository-Anleitung](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v1.2.0/docs/PORTABLE-REPOSITORY.md)
beschreibt auch die Wiederanbindung eines bestehenden Repositorys mit dem externen
Schlüssel. Ein bestehendes Repository bei verlorenem lokalen Zustand nicht neu
initialisieren. Bei einem neuen Ziel Einrichtung und Schlüsselbestätigung passend
zu diesem Ziel durchführen. Für die erste Basis Zeit und freien Platz einplanen.

## Aufbewahrung, Wiederherstellung und Grenzen

- Repository-Stände benötigen das gesamte gemeinsame Repository, den passenden
  externen Schlüssel und gegebenenfalls NAS-Zugang. Ein einzelner Standordner ist
  kein eigenständiges Backup. Gemeinsame Daten nicht manuell löschen.
- Kein normaler Einzelarchiv-Export, Web-Dateibrowser/Einzeldatei-Restore oder
  direkter Online-System-Restore für Repository-Stände.
- Der portable System-Restore erfolgt offline. Repository-Stände benötigen
  zusätzlich leeren geeigneten Linux-Zwischenspeicher für den vollständigen Stand
  plus 20 Prozent und 1 GiB Reserve; ein eingeschränkter SMB-Mount genügt nicht.
- Aufbewahrung entfernt Stand-Verweise, führt aber keine automatische vollständige
  Repository-Platzbereinigung aus. Die gesonderte konservative Bereinigung und
  ihre Grenzen sind in der Repository-Anleitung beschrieben.
- Zusätzliche Volumes benötigen explizite Restore-Zuordnungen. Keine automatische
  Partitionierung, Bootloader-Reparatur oder Migration zwischen x86 und ARM.
  FAT-/exFAT-Bootpartitionen müssen hardwarebezogen separat vorbereitet werden.
- Kein atomarer Datenbank-Snapshot. Passende Dienste stoppen oder zusätzliche
  anwendungsspezifische Dumps erstellen; nach dem Backup den Wiederanlauf prüfen.
- Eine erfolgreiche Inhaltsprüfung ersetzt keinen bootfähigen Ende-zu-Ende-Restore.
  Weitere unabhängige Sicherungen bleiben wichtig.
- Fortschrittsanzeige der Speicherberechnung, generische Fehlermeldungen bei
  belegten Wartungssperren und die Überarbeitung der Mail-/Benachrichtigungssemantik
  bleiben getrennte offene Themen. Diese Promotion erweitert deren Umfang nicht.

## Freigabe und Prüfnachweise

Der Ausgangsstand `af2d55d` bestand bereits die
[Linux-/SMB-/Browser-Pipeline 36159997178](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/36159997178).
Das ist ein Nachweis der Beta-Basis, nicht des neuen Release-Commits.

Vor der regulären Veröffentlichung wird der Release-Commit separat geprüft:
Linux-Hauptsuite mit echten Root-/Webbenutzerrechten, unprivilegierte Downloads,
native und echte SMB/CIFS-Repository-/Recovery-Tests, Browserbedienung, ShellCheck,
sudoers-/PHP-Prüfung sowie Paketbau und Audit der eingebetteten Engines.
Die endgültigen Prüfläufe und die öffentliche Paketprüfsumme werden nach
erfolgreicher Veröffentlichung in den GitHub-Release-Notizen dokumentiert.

Breite NAS-/Hardware-Abnahme, echter LoxBerry-Neustart und vollständiger Offline-
Restore mit anschliessendem Systemstart bleiben gesonderte Hardwareprüfungen.

## Sichere Kanalaktivierung

1. Release-Commit auf dem Vorbereitungsbranch prüfen; die live abgefragten
   Branches `main` und `develop` bleiben zunächst auf ihren bisherigen Ständen.
2. Geprüften Commit als `v1.2.0` taggen. Die Tag-Pipeline veröffentlicht erst nach
   erneut erfolgreichen Prüfungen das reguläre ZIP.
3. Öffentlichen Download ohne Anmeldung, ZIP-Struktur, Versionen, Unix-Rechte,
   eingebettete Engines und SHA-256 kontrollieren.
4. Erst danach `main` und `develop` per Fast-forward nachführen. Damit werden
   `main/release.cfg` und `develop/prerelease.cfg` auf das verfügbare ZIP aktiviert.
5. Beide Live-Raw-Adressen, regulären Release-Status und unveränderte frühere
   Tags/Assets abschliessend prüfen. Keine Tags verschieben oder ZIPs ersetzen.

Die vorbereiteten Felder für den separat gepflegten Wiki-Eintrag stehen unter
[Pluginseite 1.2.0](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v1.2.0/docs/PLUGINSEITE-1.2.0.txt).
