# 1.2.5 – Geprüfte Programmbasis und Prüfgrenzen

Stand: 31.10.2026. Die geprüfte Programmbasis `da034bd` wird unverändert für
1.2.5-beta übernommen. Stabiles Release und regulärer Updatekanal bleiben 1.2.4.
Dieser Text trennt die Entwicklungsprüfung von Tag-/Paketprüfung und Aktivierung
des Vorabfeeds. Der aktuelle Freigabestatus steht in den
[Release Notes](RELEASE-1.2.5-beta.md) und beim
[GitHub-Pre-Release](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.5-beta).

## Korrekturen

Mount-Root und Benutzerpfad sind verschiedene Angaben. Linux hängt bei
gelöschten Dentries den Marker `//deleted` an die Mount-Root-Identität an;
systemd-nspawn verwendet solche temporären Bind-Mounts unter `/proc`.
HostBackup akzeptiert den terminalen Marker nur in diesem Identitätsfeld und
behält ihn unverändert. Strenge Pfadprüfung und Schutz gegen den Austausch
ausgewählter Quellen werden nicht abgeschaltet. Die vorhandene Unterstützung
von Namespace-Kennungen und Automount-Schichten bleibt erhalten.

cgroup-/cgroup2-Namespaces können weitere interne Kennungen wie `/..` oder
`/../../system.slice` liefern. Führende Elternsegmente sind ausschliesslich in
diesem dateisystemspezifischen Identitätsfeld zulässig, nicht in auswählbaren
Quellpfaden oder Mount-Zielen. Die Mount-Tabelle wird nach ihrem Linux-Format
zerlegt: Unicode-Leerzeichen oder Unicode-Zeilentrenner in Dateinamen sind keine
Feld- oder Datensatztrenner. Echte ungültige Inventare bleiben Fehler.

Die Docker-Vorprüfung unterscheidet fehlenden Client, fehlgeschlagene oder
zeitüberschrittene Engine-Abfrage und eine erfolgreiche Abfrage mit null oder
mehr laufenden Containern. Eine unbekannte Anzahl wird nicht als null angezeigt.
Docker ist keine Pflicht für ein LoxBerry ohne benötigte Docker-Stopps. Sind
solche Stopps konfiguriert, bleibt die Erreichbarkeit Voraussetzung. Ein Fehler
darf weder andere Vorprüfungsfehler verdecken noch durch Shell-Fehlerbehandlung
eine unlesbare Antwort erzeugen.

Dies gilt auch nach der Vorprüfung: Die zusätzliche Inventarisierung für
`docker.json` ist zeitlich begrenzt und dokumentiert einen unbekannten Zustand
bei nicht erreichbarer Engine oder ungültiger Antwort. Optionale Inventardaten
sind keine Voraussetzung für die Sicherung. Die Datei wird vollständig und
atomar geschrieben; echte Schreibfehler werden nicht unterdrückt. Tests des
Backup-Workers müssen deshalb das echte `write_manifest()` einschliessen,
nicht nur die isolierte Vorprüfung oder eine ersetzte Manifest-Funktion.

Ein LoxBerry-Container sichert nur sichtbare ausgewählte Quellen. Die Korrektur
erkennt oder steuert keine Anwendungen auf dem äusseren Host automatisch.
Keine neue Socket-Freigabe, keine Änderung von Docker-Kontexten und keine
Erweiterung der Berechtigungen.

## Regressionsumfang

| Bereich | Abgedeckte Regressionsfälle |
| --- | --- |
| Mount-Identitäten | nspawn-Muster für boot_id/kmsg, terminales `//deleted`, cgroup-/cgroup2-Elternsegmente, Namespace-IDs, Automount/gestapelte Mounts, Report-Roundtrip, beide Grundregeln |
| Mount-Namen | Unicode-Leerzeichen und -Zeilentrenner, normale maskierte Leerzeichen und Backslashes, unveränderte Pfade und Netzquellen-Ausschlüsse, ungültige Datensätze |
| Quellenschutz | Ungültige Benutzerpfade/Mount-Ziele, relevante Mount-Ersetzung/Entfernung/Überdeckung, Ausschlüsse, nicht relevante Mount-Änderungen |
| Docker-Vorprüfung | Client fehlt, leere/laufende Engine, Fehler/Timeout/ungültige Antwort, explizite Docker-Stopps, Legacy-Stop-all, reine systemd-Auswahl, direkte und abgefangene Shell-Aufrufe |
| Docker-Dokumentation | Echte Manifest-/Worker-Funktionen, fehlender Client, nicht erreichbare oder hängende Engine, gültige leere Liste gegenüber unbekanntem Status, ungültige/partielle Antworten, atomare Datei, echte Schreibfehler |
| NAS | Unbekannte Inodes bei 0/0/0 gegenüber tatsächlich erschöpften Inodes, CIFS, Profile/Metadaten, portable Vollarchive und Repository-Stände |
| Dienste und Wiederanlauf | systemd-Instanzen und Aliasnamen, gestoppte/ersetzte/gelöschte Docker-IDs, unerreichbare Engine, persistente Journale und Upgrade ohne Deinstallation |
| Überwachungen | LoxPanel-Sperrprotokolle und manuelle Altvarianten, fehlende Plugins, fremde Wiederstarts, keine automatische AudioServer4Home-Koordination |
| Kopie und Aufbewahrung | Flüchtige Diagnoseprotokolle, echte geänderte Nutzdaten, TAR/rsync/restic, letzter geprüfter Stand, Restore- und Importgrenzen |
| Oberfläche | Vorprüfungsanzeige, Prüfberichte, schliessbare Bereiche, laufende Vorgänge, Browseraktionen und Downloadrechte |
| Installation | Syntax/ShellCheck/sudoers/PHP, Update-Erhalt der Konfiguration, ZIP-Inhalt, Dateirechte und checksum-gepinnte Laufzeit |

## Nachweis und Grenzen

Die [GitHub-Prüfung 41189024061](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/41189024061)
für `da034bd2f59905c3aabab862e69f994aaf9e2a8d` war erfolgreich:

- Hauptsuite: 874 Tests mit zehn zunächst ausgesparten Integrations-/Paketprüfungen.
  Diese opt-in Prüfungen beziehungsweise Testklassen liefen in den nachfolgenden
  verpflichtenden Schritten; die ursprünglichen Skips selbst sind keine Erfolge.
- 144 zusätzliche Linux-/CIFS-Integrationstest-Durchläufe: 32 + 18 + 38 + 6 + 32 + 18.
- 15 unprivilegierte Downloadtests, 67 Browserfälle und acht Paketprüfungen.
- Syntax, ShellCheck, sudoers und PHP erfolgreich; das Actions-ZIP stimmte bei
  allen 66 versionierten Paketdateien mit dem Commit überein, einschliesslich
  der geprüften ausführbaren Dateimodi. Das belegt noch kein veröffentlichtes ZIP.

Die vollständige bestehende Linux-Suite, echte Linux-/CIFS-Integration,
unprivilegierte Downloads, Browserregressionen und Paketprüfung laufen im
GitHub-Workflow `Build plugin ZIP`. Windows-Prüfungen ersetzen insbesondere
keine Linux-Mounts, Dateisperren, Signale oder Eigentümerprüfungen. Übersprungene
Tests sind keine bestandenen Tests. Ein fehlgeschlagener Pflichtschritt ist
kein freigegebener Teststand.

Die cgroup-Elternkennungen werden anhand dokumentierter Kernel-Ausgaben in
Parser-, Auswahl- und Identitätsvergleichstests simuliert; dabei wird keine
laufende Host-cgroup verändert. Unicode-Namen und gelöschte Bind-Mount-Quellen
werden zusätzlich in privaten Linux-Mount-Namespaces geprüft. Docker-Fehler
werden mit kontrollierten Client-/Dienst-Doubles simuliert; die echten
Manifest- und Worker-Funktionen sowie die Linux-Prozesszeitlimits bleiben im
Test aktiv. Das ist kein Test gegen eine produktive Docker-Engine.

Das getestete Actions-Artefakt muss zum geprüften Commit gehören. Seine
Installation erfolgt ohne vorherige Deinstallation, nach Abschluss aktiver
Vorgänge und mit aufbewahrten bewährten Backups. Anschliessend gespeicherte
Quellen und Stop-Auswahl kontrollieren, Vorprüfung und manuelles Backup testen.

Für den letzten Teststand liegt eine positive Rückmeldung vor. Sie ist keine
Zusicherung für jedes NAS, jeden Kernel oder jede Container-Konfiguration und
kein Nachweis eines vollständigen bootfähigen System-Restores. Produktive
Hardware und Anwendungskonsistenz müssen weiterhin vor Ort geprüft werden.

## Technische Grundlagen

- [Linux v6.8: dentry_path und //deleted](https://github.com/torvalds/linux/blob/v6.8/fs/d_path.c#L349-L357)
- [systemd v255: temporäre nspawn-Bind-Mounts](https://github.com/systemd/systemd/blob/v255/src/nspawn/nspawn.c)
- [Linux: cgroup-Namespaces und Mount-Roots mit Elternsegmenten](https://man7.org/linux/man-pages/man7/cgroup_namespaces.7.html)
- [Linux v6.8: Format der Mount-Tabelle und maskierte Zeichen](https://github.com/torvalds/linux/blob/v6.8/fs/proc_namespace.c)
- [Docker: Container-Inventar und Ausgabeformat](https://docs.docker.com/reference/cli/docker/container/ls/)
- [Docker: Client-/Daemon-Verbindung prüfen](https://docs.docker.com/engine/daemon/troubleshoot/#check-which-host-your-client-is-connecting-to)
- [Docker: Zugriff auf die Engine absichern](https://docs.docker.com/engine/security/protect-access/)
