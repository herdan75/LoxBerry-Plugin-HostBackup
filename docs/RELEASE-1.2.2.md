# LoxBerry Host Backup 1.2.2-beta

**Vorabversion vom 15.10.2026.** Programm- und Paketversion: `1.2.2`.
GitHub-Tag: `v1.2.2-beta`. Das reguläre Release, `main` und der stabile
Plugin-Updatekanal bleiben unverändert auf **1.2.0**.

[**LoxBerryHostBackup_1.2.2.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.2-beta/LoxBerryHostBackup_1.2.2.zip)

## Neu in dieser Vorabversion

- **Dienst- und Docker-Auswahl:** Gebündelte systemd-Abfragen statt langsamer
  Einzelabfragen. Gemeinsames Backend-Zeitlimit von 45 Sekunden mit höchstens
  zwei weiteren Sekunden zur Abbrucheskalation; eigenes Browser-Zeitlimit von
  60 Sekunden. Fehler, Zeitüberschreitungen und unvollständige Antworten werden
  sichtbar, eine erneute Abfrage ist möglich. Gespeicherte und noch nicht
  gespeicherte Auswahlen bleiben erhalten; verschwundene ausgewählte Ziele
  bleiben bearbeitbar. Die Sicherungskonsistenz-Prüfung wird nicht umgangen.
- **Warnungen ansehen:** Die gespeicherte Abschlussprüfung ist direkt beim
  betroffenen Backup lesbar. Sie bleibt vom optionalen Inhaltsprüfbericht und
  von einem tatsächlichen Restore-Test getrennt.
- **Prüfbericht:** Fehlende, nicht lesbare, beschädigte und nicht mehr zum
  aktuellen Manifest passende Berichte werden unterschieden. Keine erfundenen
  Prüftermine, erfolgreichen Prüfungen oder Downloads für fehlende Nachweise.
  Strukturierte CGI-Fehler und belegte Vorgangssperren werden verständlich angezeigt.
- **Schliessbare Ansichten:** Prüfergebnisse, Aktionsmeldungen, Datei-/Restore-
  Ansichten und Live-Inhalte lassen sich schliessen und wieder öffnen, ohne
  Eingaben zu verlieren oder laufende Vorgänge zu beenden. Nach einem expliziten
  erfolgreichen Start erscheint der Live-Status einmalig; Polling öffnet keine
  bewusst geschlossenen Bereiche und verschiebt die Ansicht nicht wiederholt.
- **Parallele Aktionen:** Zusätzliche aufwendige Vorprüfungen werden bei belegter
  Vorgangssperre vor dem Zielzugriff abgewiesen. Gespeicherte Hinweise, Status,
  Log und einfache Datei-Ansichten bleiben zugänglich. Eine Pause der Logausgabe
  allein beweist keinen stillstehenden Backup-Prozess.
- **Bedienung:** Tastaturfähige Zielauswahl und unveränderte Vorgangszuordnung
  beim Öffnen weiterer Ansichten. Tests für Buttons, Downloads, Bestätigungen,
  Fehlerfälle sowie Desktop- und Mobilansichten erweitert.

Die Inode-Korrektur aus 1.2.1-beta bleibt enthalten. Sicherungsverfahren,
Repository-Format, Wiederherstellungsschlüssel und vorhandene Einstellungen
werden durch dieses Update nicht automatisch umgestellt.

## Update über LoxBerry

In der Pluginverwaltung **Vorabversionen zulassen** und nach Updates suchen.
LoxBerry zeigt die numerische Version **1.2.2** an. Damit gibt es auch gegenüber
1.2.1-beta und den bisherigen develop-Testpaketen mit Version 1.2.1 einen
Versionssprung. Die normalen Einstellungen für eine automatische Installation
gelten weiterhin; die Freigabe erzwingt keine Installation.

Vor dem Update aktive Aufgaben beenden lassen und Einstellungen exportieren.
Das Update ohne vorherige Deinstallation durchführen. Bei manueller Installation
das ZIP unverändert verwenden. Vorhandene Repositorys nicht neu initialisieren
und den extern gesicherten Wiederherstellungsschlüssel aufbewahren.

Der Vorabfeed auf `develop` wird erst nach erfolgreicher Tag-Pipeline und Prüfung
des öffentlichen ZIP-Downloads aktiviert. Eine Wiki-Änderung oder ein GitHub-Tag
allein aktiviert kein Plugin-Update. Paket und zugehörige Release Notes werden
öffentlich ohne GitHub-Anmeldung erreichbar gemacht.

## Automatisierte Prüfung

Die bereits vollständig geprüfte Entwicklungsbasis ist Commit
`3242c6a22004cbe3a4a87c9c3a0790598e8d4a95`:
[CI-Lauf 38784906571](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/38784906571).

- Linux-Hauptsuite mit 442 Tests: 435 bestanden, sieben bedingte Spezialtests
  zunächst ausgelassen. Separate Pflichtschritte prüfen Paket, portable
  Wiederherstellung und echte Linux-/CIFS-Szenarien.
- 15 zusätzliche Downloadtests als unprivilegierter Benutzer.
- Repository-, Metadaten-, Recovery- und Inode-Prüfungen auf einem echten
  kurzlebigen Samba-/CIFS-Testmount mit eingeschränkten Rechten.
- 58 Browser-Prüfgruppen mit tatsächlichem CGI, Produktions-JavaScript und CSS;
  Backendaktionen dabei sicher simuliert. Darunter verzögerte Dienstantworten,
  ein tatsächliches 60-Sekunden-Browser-Zeitlimit, Wiederholung, Auswahl-Erhalt,
  Berichte, Schliessen/Wiederöffnen, Aktionsparameter und Bestätigungen.
- Reale CGI-/Backend-Vertragstests für den Prüfbericht und Linux-Sperrtests;
  ShellCheck, sudoers-, Syntax-, ZIP- und eingebettete Engine-Prüfungen.

Die Veröffentlichungsvorbereitung ändert gegenüber dieser Basis nur
Versionsangaben, Kanalziele, zugehörige Tests und Dokumentation, nicht die
Produktionslogik. Der getaggte Release-Stand muss die gesamte CI erneut bestehen.
Der genaue Release-Lauf und die SHA-256-Prüfsumme des veröffentlichten ZIPs
werden in den [öffentlichen Release Notes](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.2-beta)
festgehalten. Die Prüfsumme eines früheren develop-ZIPs gilt dafür nicht.

Die vollständige [Button- und Abnahmematrix](DR-TESTPLAN.md) trennt
Browser-Vertragstests, echte Backend-/CIFS-Tests und noch erforderliche
Praxisabnahmen.

## Grenzen und empfohlene Praxisabnahme

Automatisierte Tests bestätigen weder jede NAS-/Mount-Konfiguration noch einen
bootfähigen System-Restore auf beliebiger Hardware. Die ursprüngliche Ursache
eines gemeldeten HTTP-500-Fehlers oder eines vermuteten Stillstands ist ohne
die betreffenden Laufzeitprotokolle nicht abschliessend belegt. Insbesondere
bleibt die Bestätigung der Diensteliste auf Sebastians Gerät eine Praxisprüfung.

Nach dem Update die Dienst-/Container-Auswahl laden und gespeicherte Ziele
kontrollieren. Änderungen speichern, Vorprüfung ausführen und einen manuellen
Testlauf einschliesslich Wiederanlauf und Abschlussprüfung kontrollieren.
Warnhinweise und Inhaltsprüfbericht getrennt ansehen. Bewährte Sicherungen
behalten; einen vollständigen Restore nur in einer geeigneten getrennten
Test-/Rescue-Umgebung prüfen. Portable System-Restores bleiben offline.
