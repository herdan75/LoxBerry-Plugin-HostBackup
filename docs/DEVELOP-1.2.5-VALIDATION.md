# 1.2.5 – Entwicklungsstand und Prüfgrenzen

Stand: 30.10.2026. Nur develop; noch nicht veröffentlicht. Beide öffentlichen
Updatekanäle bleiben unverändert bei 1.2.4. Dieser Text beschreibt den Prüfumfang,
nicht das Ergebnis eines noch laufenden oder zukünftigen CI-Laufs. Massgeblich
ist der erfolgreiche GitHub-Actions-Lauf des tatsächlich installierten Commits.

## Korrekturen

Mount-Root und Benutzerpfad sind verschiedene Angaben. Linux hängt bei
gelöschten Dentries den Marker `//deleted` an die Mount-Root-Identität an;
systemd-nspawn verwendet solche temporären Bind-Mounts unter `/proc`.
HostBackup akzeptiert den terminalen Marker nur in diesem Identitätsfeld und
behält ihn unverändert. Strenge Pfadprüfung und Schutz gegen den Austausch
ausgewählter Quellen werden nicht abgeschaltet. Die vorhandene Unterstützung
von Namespace-Kennungen und Automount-Schichten bleibt erhalten.

Die Docker-Vorprüfung unterscheidet fehlenden Client, fehlgeschlagene oder
zeitüberschrittene Engine-Abfrage und eine erfolgreiche Abfrage mit null oder
mehr laufenden Containern. Eine unbekannte Anzahl wird nicht als null angezeigt.
Docker ist keine Pflicht für ein LoxBerry ohne benötigte Docker-Stopps. Sind
solche Stopps konfiguriert, bleibt die Erreichbarkeit Voraussetzung. Ein Fehler
darf weder andere Vorprüfungsfehler verdecken noch durch Shell-Fehlerbehandlung
eine unlesbare Antwort erzeugen.

Ein LoxBerry-Container sichert nur sichtbare ausgewählte Quellen. Die Korrektur
erkennt oder steuert keine Anwendungen auf dem äusseren Host automatisch.
Keine neue Socket-Freigabe, keine Änderung von Docker-Kontexten und keine
Erweiterung der Berechtigungen.

## Regressionsumfang

| Bereich | Weiterhin zu prüfende Fälle |
| --- | --- |
| Mount-Identitäten | nspawn-Muster für boot_id/kmsg, terminales `//deleted`, Namespace-IDs, Automount/gestapelte Mounts, Report-Roundtrip, beide Grundregeln |
| Quellenschutz | Ungültige Benutzerpfade/Mount-Ziele, relevante Mount-Ersetzung/Entfernung/Überdeckung, Ausschlüsse, nicht relevante Mount-Änderungen |
| Docker-Vorprüfung | Client fehlt, leere/laufende Engine, Fehler/Timeout/ungültige Antwort, explizite Docker-Stopps, Legacy-Stop-all, reine systemd-Auswahl, direkte und abgefangene Shell-Aufrufe |
| NAS | Unbekannte Inodes bei 0/0/0 gegenüber tatsächlich erschöpften Inodes, CIFS, Profile/Metadaten, portable Vollarchive und Repository-Stände |
| Dienste und Wiederanlauf | systemd-Instanzen und Aliasnamen, gestoppte/ersetzte/gelöschte Docker-IDs, unerreichbare Engine, persistente Journale und Upgrade ohne Deinstallation |
| Überwachungen | LoxPanel-Sperrprotokolle und manuelle Altvarianten, fehlende Plugins, fremde Wiederstarts, keine automatische AudioServer4Home-Koordination |
| Kopie und Aufbewahrung | Flüchtige Diagnoseprotokolle, echte geänderte Nutzdaten, TAR/rsync/restic, letzter geprüfter Stand, Restore- und Importgrenzen |
| Oberfläche | Vorprüfungsanzeige, Prüfberichte, schliessbare Bereiche, laufende Vorgänge, Browseraktionen und Downloadrechte |
| Installation | Syntax/ShellCheck/sudoers/PHP, Update-Erhalt der Konfiguration, ZIP-Inhalt, Dateirechte und checksum-gepinnte Laufzeit |

## Nachweis und Grenzen

Die vollständige bestehende Linux-Suite, echte Linux-/CIFS-Integration,
unprivilegierte Downloads, Browserregressionen und Paketprüfung laufen im
GitHub-Workflow `Build plugin ZIP`. Windows-Prüfungen ersetzen insbesondere
keine Linux-Mounts, Dateisperren, Signale oder Eigentümerprüfungen. Übersprungene
Tests sind keine bestandenen Tests. Ein fehlgeschlagener Pflichtschritt ist
kein freigegebener Teststand.

Das getestete Actions-Artefakt muss zum geprüften Commit gehören. Seine
Installation erfolgt ohne vorherige Deinstallation, nach Abschluss aktiver
Vorgänge und mit aufbewahrten bewährten Backups. Anschliessend gespeicherte
Quellen und Stop-Auswahl kontrollieren, Vorprüfung und manuelles Backup testen.

Automatisierte Regressionen sind keine Zusicherung für jedes NAS, jeden Kernel
oder jede Container-Konfiguration. MiLox' konkrete Installation und ein
vollständiger System-Restore sind damit noch nicht praktisch bestätigt.

## Technische Grundlagen

- [Linux v6.8: dentry_path und //deleted](https://github.com/torvalds/linux/blob/v6.8/fs/d_path.c#L349-L357)
- [systemd v255: temporäre nspawn-Bind-Mounts](https://github.com/systemd/systemd/blob/v255/src/nspawn/nspawn.c)
- [Docker: Client-/Daemon-Verbindung prüfen](https://docs.docker.com/engine/daemon/troubleshoot/#check-which-host-your-client-is-connecting-to)
- [Docker: Zugriff auf die Engine absichern](https://docs.docker.com/engine/security/protect-access/)
