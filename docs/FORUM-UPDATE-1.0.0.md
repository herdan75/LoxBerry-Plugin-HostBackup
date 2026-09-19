# Forum-Update zu LoxBerry Host Backup 1.0.0

Textvorlage zur Veröffentlichung vom 19.09.2026. Der Beitrag wird nicht automatisch im Forum gepostet.

Hallo zusammen

die erste Hauptversion **1.0.0** von LoxBerry Host Backup ist als reguläres
GitHub-Release ohne Beta-Zusatz verfügbar. Der vollständige geprüfte Entwicklungsstand
ist auf `main` übernommen. Beide Update-Kanäle bieten dasselbe stabile Paket an.

Gegenüber dem bisherigen main-Stand 0.5.8 wurden besonders Datensicherheit,
Wiederherstellung und Bedienung erweitert:

- Vier Metadaten-Profile für lokale Linux-Dateisysteme und geeignete Netzwerkziele.
  Network Compatible lässt xattrs und File Capabilities bewusst aus, ohne dadurch
  manuelle oder automatische Backups mit einer Warnung zu blockieren.
- Geschützte Backup-Ziele, strengere Importprüfung, Restore-Vorschau,
  explizite Volume-Zuordnung und abgesicherte Root-Helfer.
- Erhalt gespeicherter Einstellungen bei Updates sowie neustartfeste Laufzeitdaten.
- Reparierte Installation und Zeitplaneinrichtung; kompakte Übersicht,
  lesbare Logs, Aufgabenhistorie, Wartungs- und Diagnosefunktionen.
- Ein belegter Backup-Lock erzeugt beim automatischen Dienst-Wiederanlauf keine
  Cron-Mail mehr. Echte Fehler bleiben sichtbar. Die Aufbewahrung erhält eine
  eigene Statusanzeige.

**Wichtig beim Umstieg von 0.5.8 oder älter:** Der erste inkrementelle Lauf
erstellt erneut eine vollständige Basiskopie, weil die alten Backups noch keine
Metadaten-Profilinformation enthalten. Bitte genügend Platz und Zeit einplanen.
Erst danach können folgende erfolgreiche Läufe wieder inkrementell arbeiten.
Von 0.6.x/0.7.x ist eine neue Basiskopie nicht allein wegen der neuen Versionsnummer
nötig; eine geeignete Referenz mit gleichem Profil bleibt erforderlich.

**Einstellungen immer zuerst speichern.** Das gilt auch für ausgewählte Optionen,
Dienste und Container. Zeitgesteuerte Backups verwenden nur den gespeicherten Stand.

Die Versionsnummer ist kein Nachweis eines vollständigen Restores. Offline-Restore
mit Systemstart und NAS-/Hardwaretests bleiben separat erforderlich. Die fehlende
Fortschrittsanzeige der Speicherberechnung und eine generische HTTP-500-Meldung
bei gesperrter Laufzeitprüfung sind weiterhin dokumentierte offene Punkte.

[**Version 1.0.0 herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.0.0/LoxBerryHostBackup_1.0.0.zip)

Alternativ in der LoxBerry-Plugin-Verwaltung nach Updates suchen. Nicht vorher
deinstallieren. Wer bereits das manuelle 1.0.0-Testpaket installiert hat, erhält
keinen höheren Versionshinweis und kann das Release-ZIP erneut installieren.

Details und Prüfnachweise stehen in den
[Release Notes](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.0.0).

Viele Grüsse
Dani
