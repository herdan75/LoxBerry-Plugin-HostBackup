# LoxBerry Host Backup 1.1.0-beta

Vorabversion vom 20.09.2026 auf `develop`, Tag **v1.1.0-beta**.
Plugin- und Paketversion: **1.1.0**. Das reguläre Release **1.0.0** bleibt unverändert.

## Download

[**LoxBerryHostBackup_1.1.0.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.1.0-beta/LoxBerryHostBackup_1.1.0.zip)

Öffentlicher Direktdownload ohne GitHub-Anmeldung. Das ZIP unverändert in
LoxBerry installieren, **nicht entpacken**. Das Entpacken einer äusseren ZIP
ist nur bei GitHub-Actions-Artefakten nötig, nicht bei diesem Release-Download.

## Neu gegenüber 1.0.0

- **Datenquellen gezielt auswählen:** Neue Einstellungen verwenden lokale
  Laufwerke; Netzfreigaben werden einzeln eingeschlossen. Bestehende Einstellungen
  behalten ihren bisherigen Umfang. Backup-Ziel und Ausschlüsse bleiben geschützt.
  Fehlende explizit gewählte Quellen blockieren den Start statt unbemerkt zu fehlen.
- **NAS-Diagnose:** Einzelne Metadatenprüfungen mit Soll-/Ist-Werten und
  begrenzter Werkzeugausgabe statt einer alleinigen allgemeinen Fehlermeldung.
  Network Compatible benötigt weiterhin Eigentümer, Rechte, ACLs und Links;
  xattrs und File Capabilities sind bewusst ausgenommen. Feste CIFS-Rechte werden
  nicht durch Abschalten der Prüfung übergangen. Portable Archive mit Vollbackup
  bleibt eine Alternative, sofern dessen eigener Roundtrip gelingt.
- **Installation nach Restdateien:** Konfiguration wird vor dem Austausch
  gesichert; alte geschützte Programmkopien werden auch bei als Neuinstallation
  erkanntem Ablauf vorbereitet. Zurückgebliebene Launcher werden weiterhin nicht
  als Backup-Backend aktiviert. Die dauerhafte Konfigurationssicherung übersteht
  auch Abbruch, einen weiteren Installationsversuch und Neustart. Backup-Ziele bleiben unberührt.
- **Bedienung:** Kompakte Datenquellenansicht, zusätzliche Infobuttons und eine
  erweiterte Kurzanleitung. Fehler der Dateisystem-Prüfung bleiben normal
  formatiert und können erneut geprüft werden, ohne Einstellungen zu verwerfen.

## Sicher aktualisieren

1. Laufende Backup-/Restore-/Installationsvorgänge zuerst beenden lassen.
2. Wenn die Oberfläche erreichbar ist, Einstellungen exportieren.
3. Das ZIP als Update installieren, **nicht vorher deinstallieren**.
4. Ziel, Metadaten-Profil, Datenquellen, Ausschlüsse, Stop-Dienste und Zeitplan prüfen.
5. Für die lokale Empfehlung unter Datenquellen ausdrücklich
   **Lokale Laufwerke; Netzfreigaben einzeln (empfohlen)** auswählen. Bewusst
   gespeicherte Ausnahmen bleiben wirksam; ein Update stellt alte Konfigurationen
   nicht still um. USB-Nutzdaten eingeschlossen, reine Backup-Datenträger ausgeschlossen lassen.
6. Änderungen **zuerst speichern**, danach **Nächstes Backup prüfen** und ein
   manuelles Testbackup ausführen. Metadatenfehler nicht umgehen.

Die Versionsnummer allein erzwingt keine neue Snapshot-Basiskopie. Entscheidend
bleiben geeignete Referenz, Profil und tatsächlicher Sicherungsumfang. Neue
Quellen können zusätzlichen Platz und Zeit benötigen.

Bei bereits beschädigter Installation keine weiteren Deinstallationen, keine
pauschalen Rechteänderungen und keine parallelen Installer starten. Vollständiges
Installationslog sichern; nicht auf Grundlage eines Screenshot-Ausschnitts
Laufzeitdaten oder vorhandene Backups löschen.

## Update-Kanäle und Pluginseite

- `main/release.cfg` und das stabile ZIP bleiben bei 1.0.0.
- `develop/prerelease.cfg` wird erst nach erfolgreicher Prüfung des öffentlichen
  ZIP-Downloads auf 1.1.0 umgestellt. Automatische Update-Angebote setzen den
  bewusst gewählten Vorabkanal voraus; die Installationsart bestimmt LoxBerry.
- Die mit dem ZIP archivierte Vorabkanaldatei kann noch auf 1.0.0 stehen.
  Für Update-Angebote zählt die in `plugin.cfg` hinterlegte entfernte Kanaladresse,
  nicht diese archivierte Kopie; sie wird nach der Downloadprüfung aktiviert.
- Auf der Pluginseite bleiben Status **STABLE**, Version **1.0.0** und regulärer
  Download bestehen. Nur **Pre-Release Download** erhält den Direktlink oben.
- Pluginseite und Forum werden nicht automatisch durch GitHub geändert.

## Prüfung und Grenzen

Freigabekriterien sind die vollständige Linux-Testpipeline mit echten
Root-/Plattformbenutzerrechten, Neuinstallation mit Restdateien ohne Upgrade-Purge,
reguläre Deinstallation/Neuinstallation, unveränderte Schutzgrenzen, tatsächlichem
Samba/CIFS-Mount, Browser-Fehler-/Wiederholungsprüfung und gebautem Plugin-ZIP.
Die Release-Seite nennt den zugehörigen Prüflauf und die SHA-256-Prüfsumme.

Das ist kein Nachweis einer Reparatur auf Klaus' konkreter VM oder einer
vollständigen LoxBerry-/QNAP-/Boot-Restore-Abnahme. Die tatsächliche Ursache auf
seinem System muss bei weiterem Fehler anhand des vollständigen Logs geprüft werden.
Speicherberechnung ohne Zwischenfortschritt, die bekannte generische HTTP-500-
Meldung bei konkurrierender Laufzeitdateien-Prüfung und produktive Restoretests
bleiben gesonderte Grenzen. Ein dateibasiertes Backup richtet Partitionen und
Bootloader nicht automatisch ein. Nicht als einzige Absicherung kritischer Systeme verwenden.
