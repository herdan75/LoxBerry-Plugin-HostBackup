# LoxBerry Host Backup 1.2.0-beta

Vorabversion vom 25.09.2026 auf `develop`, Tag **v1.2.0-beta**.
Plugin- und Paketversion: **1.2.0**. Das reguläre Release **1.0.0** bleibt unverändert.

## Download und Installation

[**LoxBerryHostBackup_1.2.0.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.0-beta/LoxBerryHostBackup_1.2.0.zip)

Das öffentliche Release-ZIP wird nach erfolgreichem Tag-Prüflauf bereitgestellt.
Es benötigt keine GitHub-Anmeldung und wird **unverändert, ohne Entpacken** in
LoxBerry installiert. **Bei einem Update nicht vorher deinstallieren.** Nur bei
einem GitHub-Actions-Artefakt muss der äussere ZIP-Umschlag entpackt werden.

## Neu gegenüber 1.1.0-beta

- **Portable, platzsparende NAS-Sicherungsstände:** Ein verschlüsseltes Repository
  bewahrt gemeinsame Datenblöcke auf. Der erste Stand benötigt eine vollständige
  Basis; Folgesicherungen verwenden vorhandene Daten wieder. Jeder Stand beschreibt
  den vollständigen ausgewählten Dateibaum, ist aber ohne Repository nicht eigenständig.
- **Linux-Metadaten innerhalb des Formats:** Eigentümer, Rechte, ACLs, xattrs und
  Links müssen nicht als native Eigenschaften jeder Datei auf dem NAS verfügbar
  sein. Feste SMB-Rechte sind daher nicht grundsätzlich ein Hindernis. Die
  Zielprüfung bleibt verbindlich; keine Garantie für jedes NAS oder jede Einbindung.
- **Vier verständlicher benannte Verfahren:** Linux-Dateisicherung (bisher Native
  Strict), Portable Sicherung (bisher Portable Archive) sowie unter erweiterten
  Einstellungen Dateisicherung mit reduzierten Metadaten (Network Compatible)
  und Metadaten in Dateiattributen speichern (Fake Super).
- **Zwei Sicherungsarten:** Vollbackup und Platzsparende Sicherungsstände. Bei der
  Dateisicherung werden Hardlinks, bei portablen Ständen Repository-Datenblöcke
  wiederverwendet. Restic ist ein internes Speicherwerkzeug, kein fünfter Modus.
- **Gezielte Einrichtung und Schlüssel-Recovery:** Repository am gespeicherten
  Ziel einrichten, geheime Wiederherstellungsdatei extern sichern und separat
  bestätigen. Die passende checksum-geprüfte Engine für amd64, ARM oder ARM64
  wird im Pluginpaket mitgeliefert.
- **Aufgeräumte Bedienung:** Portable Einrichtung direkt beim Sicherungsverfahren,
  Zusatzexport unter Sicherungsart. Erweiterte Aufbewahrung und Integritätsprüfung
  stehen unter Optionen und Freigaben direkt nach den zu stoppenden Diensten,
  mit einheitlicher Schrift und kontextbezogenem Infobutton.
- **Kurzanleitung und Hilfen:** Einrichtung, gespeicherte Einstellungen, externe
  Schlüsselbestätigung, Aufbewahrung und Restore-Grenzen sind ausführlicher erklärt.

Bestehende Einstellungen und Vollarchive werden nicht automatisch umgestellt
oder umgewandelt. Ein portables Vollbackup bleibt ein eigenständiges `rootfs.tar`.
Das neue Repository-Verfahren ist ausdrücklich zu wählen und einzurichten.

## Sicher aktualisieren und testen

1. Laufende Backup-, Restore- und Installationsvorgänge beenden lassen.
2. Einstellungen exportieren und bewährte Backups behalten. Bei bereits genutzten
   Repository-Testständen zusätzlich die passende Wiederherstellungsdatei extern
   sichern und deren Zugänglichkeit prüfen. Ein Konfigurationsexport enthält den
   Repository-Schlüssel nicht.
3. ZIP als Update installieren oder in LoxBerry den Vorabkanal wählen und nach
   Updates suchen. Paketversion 1.2.0 ist höher als frühere Testpakete mit 1.1.0.
4. Ziel, Verfahren, Sicherungsart, Datenquellen, Ausschlüsse, Stop-Dienste und
   Zeitplan prüfen. Vorhandene Einstellungen bleiben erhalten; nichts wird still
   auf Portable Sicherung oder die lokale Datenquellen-Grundregel umgestellt.
5. Änderungen zuerst speichern, danach **Nächstes Backup prüfen** ausführen.
6. Ein manuelles Testbackup vollständig abschliessen lassen, Protokoll und
   Wiederanlauf gestoppter Dienste kontrollieren und einen Restore-Test durchführen.

Eine einzelne Cron-Rechtemeldung während der Installation kann durch das kurze
Rechtefenster beim Dateiaustausch entstehen. Wiederholte Meldungen nach Abschluss
sind nicht normal und müssen anhand von Dateirechten und Installationslog geklärt
werden. Die Sicherheitsprüfung nicht abschalten und keine pauschalen Rechte ändern.

## Portable Sicherungsstände einrichten

Für portable Vollarchive ist diese Einrichtung nicht erforderlich.

1. **Portable Sicherung** und zunächst **Vollbackup** wählen, das tatsächlich
   eingebundene Ziel und die Root-Freigabe speichern.
2. Beim Sicherungsverfahren die Einrichtung aufklappen und **Repository am
   gespeicherten Ziel einrichten** ausdrücklich ausführen.
3. **Geheime Wiederherstellungsdatei herunterladen**, ausserhalb dieses LoxBerry
   vertraulich aufbewahren und den externen Speicherort kontrollieren. Danach die
   eigene Bestätigungsaktion ausführen. Normales Speichern genügt dafür nicht.
4. **Platzsparende Sicherungsstände** wählen. Unter **Sicherungsart / Zusatzexport**
   den automatischen tar.gz-Export ausdrücklich deaktivieren.
5. Speichern, prüfen und ein manuelles Testbackup durchführen.

Die [vollständige Repository-Anleitung](PORTABLE-REPOSITORY.md) erklärt Einrichtung,
Wiederanbindung mit externem Schlüssel und Offline-Recovery. Bei verlorenem
lokalem Zustand ein bestehendes Repository anbinden, nicht neu initialisieren.

## Grenzen, Aufbewahrung und Wiederherstellung

- Repository-Stände benötigen die gesamte gemeinsame Datenbasis, den passenden
  externen Schlüssel und NAS-Zugang. Ein einzelner Standordner oder der Export der
  Plugin-Einstellungen ist kein vollständiges Repository-Backup.
- Kein normaler Einzelarchiv-Export, Web-Dateibrowser/Einzeldatei-Restore oder
  direkter Online-System-Restore für Repository-Stände.
- Der System-Restore erfolgt offline mit einem zusätzlichen leeren geeigneten
  Linux-Zwischenspeicher: vollständiger Stand plus 20 Prozent und 1 GiB Reserve.
  Der Zwischenspeicher darf nicht der eingeschränkte SMB-Mount sein.
- Zusätzliche Volumes benötigen ausdrückliche Zuordnungen. Kein automatischer
  Wechsel zwischen x86 und ARM, keine Partitionierung oder Bootloader-Reparatur.
  FAT-/exFAT-Bootpartitionen müssen hardwarebezogen separat vorbereitet werden.
- Aufbewahrung entfernt Stand-Verweise, führt aber keine automatische
  Repository-Platzbereinigung aus. Die gesonderte konservative Bereinigung ist
  dokumentiert; teilweise noch verwendete Datenpakete können weiter Platz belegen.
- Sicherungsstände sind keine atomaren Datenbank-Snapshots. Geeignete Dienste
  stoppen oder anwendungsspezifische Dumps verwenden.
- Bei Repository-Ständen werden echte laufzeitgebundene Unix-Sockets ausgelassen
  und im Auswahlbericht/Log ausgewiesen; andere Lese- oder Mountfehler nicht ignoriert.
- Eine erfolgreiche Inhaltsprüfung ersetzt keinen bootfähigen Ende-zu-Ende-Restore.
  Weitere unabhängige Sicherungen bleiben wichtig.

## Update-Kanäle und Pluginseite

`main/release.cfg`, Stable 1.0.0 und dessen ZIP bleiben unverändert. Der entfernte
Vorabkanal wird erst nach Prüfung des öffentlichen 1.2.0-ZIP-Downloads auf 1.2.0
umgestellt. Bis dahin bleibt das bestehende 1.1.0-beta-Angebot erreichbar.

Die mit dem neuen ZIP archivierte `prerelease.cfg` kann deshalb noch 1.1.0 nennen.
Für die Update-Erkennung zählt die in `plugin.cfg` hinterlegte entfernte Adresse,
nicht diese archivierte Kopie. Vorabkanal bewusst wählen; vollautomatische
Installation hängt zusätzlich von den persönlichen LoxBerry-Updateeinstellungen ab.

Auf der Pluginseite bleiben Status **STABLE**, Version **1.0.0** und regulärer
Download bestehen. **Pre-Release Download** erhält den neuen Direktlink.
Wiki und Forum werden durch einen GitHub-Push nicht automatisch bearbeitet.

## Prüfstand

Freigabe erfolgt über die vollständige Tag-Pipeline: Linux-Hauptsuite mit echten
Root-/Plattformbenutzerrechten, unprivilegierte Downloads, native und echte
SMB/CIFS-Repository-/Recovery-Tests, Browserbedienung, ShellCheck, sudoers-/PHP-
Prüfung sowie ZIP-Bau und Prüfung der eingebetteten Engines.

Die Entwicklungsbasis `667dca2` bestand bereits
[Prüflauf 36098171134](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/36098171134):
370 Tests in der Hauptsuite (drei vorgesehene Skips), 15 Downloadtests sowie
29 Repository- und 18 Portable-Tests jeweils unter Linux und SMB/CIFS. Die
separaten verpflichtenden Integrationsschritte waren erfolgreich. Lokal bestanden
35 Browser-Szenarien. Dies ist der Nachweis für die Entwicklungsbasis, nicht für
einen späteren Versionscommit.

Der endgültige Tag-Prüflauf und die Prüfsumme des öffentlichen Pakets werden
nach erfolgreicher Veröffentlichung in den GitHub-Release-Notizen dokumentiert.
Eine breite NAS-/Hardwareabnahme und ein vollständiger LoxBerry-Boot-Restore
werden durch diese automatisierten Tests nicht behauptet.
