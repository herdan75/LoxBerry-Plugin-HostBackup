# LoxBerry Host Backup 0.7.0-beta

Pre-Release vom 13.09.2026 · interne Plugin-Version 0.7.0 · Stable bleibt 0.5.8.

Diese Vorabversion erweitert 0.6.1-beta um abgesicherte Backup-/Restoreabläufe,
eine robustere Bedienung und optionale Prüf-, Aufbewahrungs- und Diagnosefunktionen.
Sie ist für freiwillige Tests vorgesehen, nicht als alleinige Absicherung
kritischer Systeme. Ein erfolgreicher Backup- oder Inhaltsprüflauf ist kein
Nachweis eines bootfähigen vollständigen Restores.

## Installation und Update

**Korrigiertes Paket vom 13.09.2026, ohne Versionswechsel:** Der gemeldete
POSTROOT-Fehler `Unsafe trusted directory: /etc/cron.d` ist behoben. LoxBerrys
vorgesehene Cron-Verknüpfung wird gezielt unterstützt, bei weiterhin geprüften
Root-Rechten. Versionsnummer und Downloadlink bleiben unverändert.

[LoxBerryHostBackup_0.7.0.zip herunterladen](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v0.7.0-beta/LoxBerryHostBackup_0.7.0.zip)

Nach einem fehlgeschlagenen Installationsversuch dieses ZIP **frisch herunterladen
und erneut über die Plugin-Verwaltung installieren**, ohne vorherige Deinstallation.
Eine bereits eingetragene Version 0.7.0 erhält wegen der identischen Versionsnummer
keine neue Update-Meldung. Vorhandene Einstellungen anschliessend kontrollieren.

Den Pre-Release-Kanal in der LoxBerry-Plugin-Verwaltung aktivieren und nach
Updates suchen. Alternativ das ZIP über die Plugin-Verwaltung installieren.
Die Updateinformation kommt aus `prerelease.cfg`; Stable bleibt unverändert.

1. Laufende Backup-/Restoreaufgaben beenden lassen und Einstellungen exportieren.
2. Update installieren, danach Ziel, Ausschlüsse, Profil und Zeitplan kontrollieren.
3. **Geänderte Einstellungen zuerst mit „Änderungen speichern“ übernehmen.**
   Auch Optionsfelder, Dienste, Container und Zeitpläne werden nicht automatisch
   gespeichert. Manuelle und geplante Backups verwenden gespeicherte Werte.
4. Freien Speicher kontrollieren und zuerst ein manuelles Testbackup durchführen.

Bestehende Einstellungen und Backupdaten werden beim Update nicht absichtlich
zurückgesetzt oder gelöscht. Neue optionale Inhaltsprüfungen benötigen Zeit und
zusätzlichen lokalen Speicher; sie müssen bewusst aktiviert werden.

> [!IMPORTANT]
> **Von 0.5.8 oder älter kommend wird zuerst nochmals eine vollständige
> Basiskopie erstellt – erst danach wieder inkrementell gesichert.**
> Den alten Backups fehlt die erforderliche Metadaten-Profilinformation für eine
> Hardlink-Referenz. Zusätzlichen Platz einplanen; das letzte brauchbare Backup
> wird nicht vorab zur Platzbeschaffung gelöscht. Ein Upgrade von 0.6.x allein
> erzwingt keine neue Basiskopie, wenn eine verwendbare Referenz mit demselben
> Profil vorhanden ist. Ein Profilwechsel kann dagegen eine neue Basis erfordern.

## Daten- und Wiederherstellungssicherheit

- Restore berücksichtigt gespeicherte Ausschlüsse und schützt dadurch auch bei
  rsync-Löschungen nicht gesicherte Nutzdaten. Explizite Offline-Ziele,
  Volume-Zuordnungen und eine echte Vorschau sind vor dem Schreiben verfügbar.
- Dienst-/Containerstopps werden vorab dauerhaft lokal protokolliert. Ein
  Wiederanlauf kann auch nach Neustart oder Verlust des Backup-Mediums nachgeholt
  werden; verspätete Stopps überschreiben keine abgeschlossenen Aufgaben mehr.
- Root-Helfer liegen in geschützten Versionsverzeichnissen und werden atomar
  aktiviert. Importstrukturen und Kontrollinformationen werden lokal geprüft;
  importierte Erfolgsmeldungen werden nicht ungeprüft übernommen.
- Neue Basiskopien und volle Inodes werden korrekt vorgeprüft. Tägliche,
  wöchentliche und monatliche Zeitpläne verwenden denselben Startweg.
- Metadaten werden mit einer echten Rückkopie geprüft. Snapshot-Wiederverwendung
  wird von blossen Hardlinks innerhalb eines Backups unterschieden.
- Fake Super erhält einen lokalen Kompatibilitätsweg für den bekannten
  [rsync-3.2.7-Fehler bei lokalen `-M`-Transfers](https://github.com/RsyncProject/rsync/issues/505),
  ohne zusätzliche SSH-Einrichtung oder Netzwerkdienst.
- Exporte und vollständige Logs werden über das Root-Backend gestreamt;
  Exportprüfung und Ausgabe beziehen sich auf dieselbe geöffnete Datei.

## Bedienung und neue Funktionen

- Startübersicht mit letztem Ergebnis, laufender Aufgabe, nächstem Termin und
  Zielkapazität; Vorschau zeigt gespeicherte Profile, Volumes, Ausschlüsse und
  Snapshot-Referenz.
- Ungespeicherte Eingaben bleiben bei Speicherfehlern, Token-Erneuerung und
  Aufgabenabschluss erhalten. Widersprüchliche Profile/Zeitpläne werden erkannt.
  Hilfen, mobile Tabellen und Live-Logs mit horizontalem Scrollen sind verbessert.
- Speicherübersicht trennt logische Grösse, tatsächliche Belegung, geteilte
  Dateien, Exporte und fehlgeschlagene Stände.
- Einzeldateien und Ordner können in einen neuen Unterordner wiederhergestellt
  werden. Zu jedem Backup gibt es ein herunterladbares Recovery-Blatt.
- Optionale Inhaltsprüfbasis, spätere/geplante Vergleiche und Prüfberichte.
  Eigene externe Restoretests lassen sich getrennt mit Datum, Ergebnis und Notiz
  dokumentieren; Benutzerangaben ändern die technische Restore-Freigabe nicht.
- Anzahl- oder tägliche/wöchentliche/monatliche Aufbewahrung, Schutz einzelner
  Backups sowie bestätigte Bereinigung anhand einer Vorschau. Das letzte
  brauchbare Backup bleibt geschützt.
- Gesonderte Log-/Quarantänebereinigung und Diagnose-ZIP. Optionale vollständige
  Originalprotokolle können private Daten enthalten und sind vor Weitergabe zu prüfen.

## NAS und automatische Backups

`Network Compatible` bleibt das bewusst auswählbare Profil für geeignete
CIFS-/NFS-/NAS-Ziele ohne vollständige Linux-xattr-Unterstützung. Es verzichtet
auf xattrs und File Capabilities; der neutrale Hinweis blockiert weder manuelle
noch zeitgesteuerte Backups und verlangt keine zusätzliche Startbestätigung.
Echte Übertragungsfehler bleiben Fehler. Für Restore gelten weiterhin die
Bestätigungen wegen reduzierter Metadaten. `Native Strict` bleibt Standard.

Die zurückgestellte **AP-14 zur Mail-/Benachrichtigungssemantik ist nicht Teil
dieses Updates**.

## Prüfung und bekannte Grenzen

- [Linux-Abnahme der Installationskorrektur](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34753883131):
  188 Tests ohne Skips, zehn Browser-Prüfblöcke sowie Rechteprüfung und ZIP-Build
  erfolgreich. Der neue Test reproduziert die frühere Cron-Ablehnung und prüft
  anschliessend Installation und erneute Installation mit dem echten Backend.
- [Linux-Abnahme](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/34753075077):
  187 Tests ohne Skips, alle zehn Browser-Prüfblöcke sowie Rechte-/Metadatenprüfung
  und ZIP-Build erfolgreich. Der Release-Tag wird vor Veröffentlichung erneut geprüft.
- Lokaler Windows-Gesamtlauf: 176 Tests, davon 13 plattformbedingte Skips;
  weitere Syntax-/Backend-Smokes erfolgreich. ShellCheck ohne Befunde.
- Zehn Browser-Prüfblöcke mit echter CGI-Ausgabe und produktivem JavaScript/CSS
  bestanden; Backendantworten im Browsertest sind simuliert.
- Paketveröffentlichung erst nach erfolgreicher Linux-CI mit Integrations- und
  Browserprüfungen. Den zugehörigen Lauf und dessen tatsächliche Ergebnisse
  dokumentiert die [GitHub-Release-Seite](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v0.7.0-beta).
- Echte LoxBerry-Neustart-/NAS-Tests und ein vollständiger Offline-Restore mit
  Systemstart sind für diesen neuen Stand noch nicht als Hardwareabnahme belegt.
  Automatisierte Fixtures ersetzen diese Tests nicht; die stabile Freigabe
  bleibt an den [Disaster-Recovery-Testplan](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.0-beta/docs/DR-TESTPLAN.md) gebunden.
- Kein Disk-Image und keine automatische Wiederherstellung von Partitionierung,
  Bootloader oder beliebigen Plattform-/Architekturwechseln. Datenbanken brauchen
  weiterhin eine konsistente Stop-/Dump-Strategie.

Details: [README](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.0-beta/README.md),
[Changelog](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.0-beta/CHANGELOG.md),
[Umsetzungs- und Prüfbericht](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.0-beta/docs/IMPLEMENTATION-2026-09.md),
[Sicherheitsmodell](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/v0.7.0-beta/docs/SECURITY.md).
