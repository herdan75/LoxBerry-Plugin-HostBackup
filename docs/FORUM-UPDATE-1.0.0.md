# Forum-Update zu LoxBerry Host Backup 1.0.0 – Entwurf

**Noch nicht veröffentlichen.** Stand: 19.09.2026. Nach späterer Freigabe den
tatsächlich geprüften Download und Veröffentlichungsstatus ergänzen.

Hallo zusammen

ich bereite die erste Hauptversion **1.0.0** von LoxBerry Host Backup vor.
Der vollständige aktuelle Entwicklungsstand ist dafür auf `main` übernommen.
Die Version hat keinen Beta-Zusatz, ist aber noch nicht als neues Release
oder über die LoxBerry-Pluginseite freigegeben.

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

Derzeit bleiben öffentliche Releases, Update-Kanäle und Pluginseite unverändert.
Weitere Informationen zur Vorbereitung stehen in den
[Release Notes](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/blob/main/docs/RELEASE-1.0.0.md).

Viele Grüsse
Dani
