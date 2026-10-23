# LoxBerry Host Backup 1.2.4

Reguläres Release vom **23.10.2026**. Programm- und Paketversion: `1.2.4`,
Tag: `v1.2.4`, Plugin-ZIP: `LoxBerryHostBackup_1.2.4.zip`.
Regulärer LoxBerry-Kanal und Vorabversionskanal verwenden dasselbe stabile Paket.
Es gibt für diese Freigabe kein zusätzliches `1.2.4-beta`-Paket.

## Änderungen gegenüber 1.2.0

- **NAS-Ziele:** Unbekannte Inode-Gesamtzahlen, etwa `df -i` mit `0/0/0` auf
  CIFS-/NAS-Zielen, blockieren nicht mehr allein den Start. Bekannte erschöpfte
  Inodes, fehlender Speicher und andere Pflichtfehler bleiben blockierend.
- **Dienstelisten und Bedienung:** Gebündelte Abfragen mit begrenzten Zeitlimits,
  erneutes Laden ohne Verlust vorhandener Auswahlen, schliessbare Ergebnis- und
  Statusansichten, direkt lesbare Abschluss-Hinweise und klare Prüfbericht-Fehler.
  Aufwendige konkurrierende Aktionen werden bei laufenden Vorgängen abgefangen.
- **Dienstnamen und Wiederanlauf:** Gültige systemd-Instanznamen bleiben unverändert
  erhalten; Aliase werden zusammengefasst und kritische Dienste geschützt.
  Bestätigt gelöschte Docker-IDs werden mit erhaltenem Nachweis aus der offenen
  Warteschlange genommen. Kein Start eines gleichnamigen Ersatzcontainers und
  keine falsche Erfolgsmeldung. Unveränderte Wiederanlauf-Fehler verursachen nicht
  mehr alle fünf Minuten eine Mail; tatsächliche Wiederanläufe bleiben geschützt.
- **LoxPanel 0.9.9:** Unterstützung des tatsächlich veröffentlichten Controllers
  mit ausgelagerter Sperrprüfung. Bei ausgewähltem Container wird die gemeinsame
  Watchdog-Sperre vor dem Stopp bis nach dem Wiederanlaufversuch gehalten,
  auch in Fehler-/Abbruchpfaden. Kein Pull, Image-Update oder Neuanlegen des
  Containers und kein zusätzlicher Sicherungsmodus.
- **Flüchtige Diagnoseprotokolle:** Bekannte LoxBerry-Diagnoseinhalte werden für
  alle Sicherungsverfahren standardmässig vor der Dateiaufzählung ausgelassen.
  Verzeichnisstruktur, Rechte und Links bleiben erhalten; Daten, Konfigurationen
  und dauerhafte Installationsnachweise werden nicht durch diese Regel
  ausgeschlossen. Keine pauschale Ausnahme für `.log` oder wichtige Änderungen.
  TAR-Verzeichnisänderungen werden nur nach zusätzlichem Metadatenvergleich als
  unkritisch behandelt. Die ausdrücklich aktivierbare Mitsicherung bleibt möglich.
- **Quellenprüfung:** Nur Änderungen am tatsächlich eingefrorenen Sicherungsumfang
  und seinen Zugriffswegen blockieren. Vollständig ausgeschlossene Mounts dürfen
  sich ändern. Ersetzte, verschwundene oder überdeckte ausgewählte Quellen bleiben
  Fehler. Gültige Docker-Namespace-Kennungen werden nicht als relative Pfade abgewiesen.
- **Diagnose und Aufbewahrung:** Unerwarteter Container-Wiederanlauf, entfernte IDs
  und nicht erreichbares Docker erhalten getrennte Hinweise mit ursprünglichem
  Namen, ID und nächsten Schritten. Neue Stände mit Hinweisen verdrängen nicht den
  letzten vollständig geprüften Stand derselben Host-/Formatlinie.

Alle Details und die historischen Beta-Einträge stehen im [Changelog](../CHANGELOG.md).
Die vier bestehenden Sicherungsverfahren und die bisherigen Backupformate bleiben
erhalten; es werden keine neuen Modi eingeführt.

## LoxPanel und AudioServer4Home

Die automatische Koordination wurde mit **LoxPanel 0.9.9** und den bereits
unterstützten Sperrvarianten geprüft. Sie gilt für einen in HostBackup ausgewählten
Container und startet nur wieder, was zuvor lief und durch dieses Backup gestoppt
wurde. Die Erkennung richtet sich nach dem tatsächlich vorhandenen Sperrprotokoll,
nicht allein nach der Versionsnummer. Unbekannte künftige Controller-Änderungen
sind nicht pauschal freigegeben; eine dauerhaft zugesicherte Backup-Schnittstelle
mit LoxPanel besteht noch nicht.

Die veröffentlichten LoxPanel-Versionen **0.3.0 bis 0.7.0** erfordern weiterhin
einen bewussten Stopp in ihrer eigenen Oberfläche **vor der Vorprüfung**. Dieser
Stopp bleibt erhalten; die Anwendung anschliessend dort selbst wieder einschalten.
Ein blosses `docker stop` ist nicht gleichwertig.

**AudioServer4Home wird nicht automatisch koordiniert.** Vor der Vorprüfung in
seiner eigenen Oberfläche stoppen und nach dem Backup selbst wieder einschalten.
Andere Überwachungen ebenfalls passend zur Anwendung abstimmen. Während des
Backups keine manuellen Container-Starts oder Updates durchführen.

## Download und Update

[**LoxBerryHostBackup_1.2.4.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.4/LoxBerryHostBackup_1.2.4.zip)

- In der LoxBerry-Pluginverwaltung nach Updates suchen. Kein Beta-Opt-in nötig;
  auch der Vorabversionskanal liefert dasselbe Paket. Die automatische Installation
  hängt von der persönlichen LoxBerry-Einstellung ab.
- Alternativ das öffentliche ZIP ohne Entpacken installieren. Für den Download
  ist kein GitHub-Konto nötig. Bei Actions-Artefakten nur den äusseren ZIP-Umschlag
  entpacken und das enthaltene Plugin-ZIP installieren.
- **Nicht vorher deinstallieren.** Aktive Vorgänge beenden lassen, Einstellungen
  exportieren und bewährte Backups behalten. Ein aktiver Backup-/Recovery-Vorgang
  darf die Installation vorübergehend sperren. Keine parallelen Installationen.
- Bereits installierte manuelle Testpakete mit Version **1.2.4** erhalten keinen
  numerischen Versionssprung. Das endgültige Release-ZIP nochmals darüber
  installieren, um sicher den veröffentlichten Stand zu verwenden.
- Backup-Ziel, Quellen, Verfahren, Zeitplan, Stop-Auswahl und offene Nachweise
  bleiben erhalten. Vorhandene Backups werden nicht in andere Formate umgewandelt.
  **Geänderter Standard:** Flüchtige Diagnoseprotokolle sind ohne ausdrückliche
  Freigabe ausgeschlossen; eine bereits aktivierte Mitsicherung bleibt erhalten.
- Nach dem Update Diensteliste laden, Auswahl kontrollieren, speichern,
  **Nächstes Backup prüfen** ausführen und ein manuelles Testbackup einschliesslich
  Wiederanlauf kontrollieren. Neuinstallationen richten vorher Ziel und Quellen ein.
- Für portable Repository-Stände die externe Wiederherstellungsdatei behalten;
  sie ist nicht Bestandteil des Konfigurationsexports.

## Prüfungen und Freigabenachweise

Die unveränderte Programmbasis `62c13f40e4f42873374324c6f12ec06f1b520577`
bestand die [GitHub-Prüfung 39995108339](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/39995108339):

- 825 Grundtests mit zehn vorgesehenen Auslassungen; diese Auslassungen sind keine
  bestandenen Einzeltests.
- Zusätzliche Linux-/CIFS-/Repository-/Metadatenprüfungen, echte Dateisperren,
  Signal-/Abbruchbehandlung, Installations- und Wiederanlaufpfade.
- 65 Browserprüfungen und acht Paketprüfungen; ShellCheck, sudoers und Syntaxprüfungen.
- Download des Workflow-Pakets und Abgleich mit dem Commit: 63 Nutzdateien,
  zwölf ausführbare Dateien, Unix-Rechte, Zeilenenden und ZIP-Integrität geprüft.

Diese Belege gelten für die Programmbasis, nicht automatisch für den Release-Tag
oder die Live-Updatekanäle. Die Release-Vorbereitung ändert nur Dokumentation,
Kanalmetadaten und dazugehörige Prüfungen; die Programmlogik bleibt unverändert.
Die Tag-Pipeline prüft den Release-Commit erneut. Anschliessend werden öffentlicher
Download, SHA-256, Paketinhalt und beide live abgefragten Kanaldateien kontrolliert.
Die endgültigen Run-Links und Paketprüfsummen werden im
[GitHub-Release v1.2.4](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.4)
dokumentiert; bis dahin sind diese Freigabeschritte nicht durch den Basislauf belegt.
Ältere Tags und ZIPs bleiben unverändert. Wiki-/Pluginseite werden separat gepflegt.

Weitere technische Belege enthält die
[Entwicklungsvalidierung 1.2.4](DEVELOP-1.2.4-VALIDATION.md); dort beschriebene
Zwischenstände und damals unveränderte Updatekanäle sind historische Angaben.

## Grenzen

Automatisierte Tests ersetzen weder die Prüfung jedes Anwender-NAS noch die
Anwendungskonsistenz produktiver Datenbanken oder einen bootfähigen Hardware-Restore.
Echte Fehler werden nicht pauschal ignoriert. Ein vollständig abgeschlossenes
Backup ist kein Nachweis eines erfolgreichen System-Restores.

Portable System-Restores erfolgen offline. Repository-Stände benötigen das ganze
gemeinsame Repository und den externen Schlüssel; der Standordner allein reicht
nicht. Es gibt keine automatische Partitionierung, Bootloader-Reparatur oder
garantierte Migration zwischen CPU-Architekturen. Einen eigenen Restore-Test
durchführen und zusätzliche unabhängige Sicherungen behalten.
