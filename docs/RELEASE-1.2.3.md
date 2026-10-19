# LoxBerry Host Backup 1.2.3-beta

**Vorabfreigabe vom 19.10.2026.** Interne Programm- und Paketversion: `1.2.3`,
Release-Tag: `v1.2.3-beta`, Plugin-ZIP: `LoxBerryHostBackup_1.2.3.zip`.
Der stabile Kanal und `main` bleiben auf **1.2.0**; ältere Pakete unverändert.

**Freigabestatus:** Das Beta-Paket ist öffentlich veröffentlicht; Tag-Pipeline
und ZIP-Prüfung sind erfolgreich abgeschlossen. Der separate Aktivierungsstand
setzt `develop/prerelease.cfg` auf **1.2.3** und das geprüfte Beta-ZIP. Der
abschliessende Nachweis für seinen Push, seine CI und den live abgefragten Feed
wird im [GitHub-Pre-Release](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/tag/v1.2.3-beta)
festgehalten; der Paketnachweis allein belegt diese Kanalprüfung nicht.

## Gemeinsame Korrekturen

- **Dienstnamen:** Konkrete systemd-Namen werden durchgehend unverändert
  verarbeitet: `@`-Instanzen, weitere `@` im Instanzteil, `:`, `-`, `_`, Punkte,
  wörtliche Backslashes/`\xHH` und führende zulässige Satzzeichen, bis 255 Zeichen
  einschliesslich `.service`. Kein Unescaping; `systemctl --` trennt Namen von
  Optionen. Leere Templates, Steuerzeichen, Globs, `/` und Shell-Sonderzeichen
  bleiben abgewiesen. Ungültige gespeicherte Stop-Auswahlen werden vor dem ersten
  Stopp mit einer verständlichen Meldung erkannt.
- **Docker-Wiederanlauf:** Nachweislich gelöschte Container werden bei inaktiven
  Vorgängen automatisch aus der offenen Warteschlange genommen; ihr Nachweis
  bleibt geschützt archiviert. Kein Start eines gleichnamigen Ersatzcontainers
  und kein falscher Erfolgsstatus. Tatsächlich offene Wiederanläufe bleiben
  geschützt; unveränderte Fehler erzeugen nicht mehr alle fünf Minuten eine Mail.
- **Container-Updates:** Neue Backups verwenden die aktuell vorhandene
  vollständige ID. Zwischen abgeschlossenen Backups gelöschte Stop-Auswahlen
  werden erst nach unabhängig bestätigtem Fehlen übersprungen.
- **Sichere Dienstempfehlungen:** `dbus` wird nicht mehr wegen `db` als Datenbank
  empfohlen. Dienst-Aliase werden zusammengefasst; Avahi, ModemManager und D-Bus
  bleiben auch bei alten gespeicherten Auswahlen vor dem Stoppen geschützt.
  Ihre Dateien bleiben gemäss Quellenauswahl gesichert.

Keine neuen Sicherungsmodi oder zusätzlichen Einstellungen. Die bisherigen
NAS-Inode-, Dienstelisten- und Bedienungskorrekturen bleiben enthalten.

## Installation und Update

In der LoxBerry-Pluginverwaltung Vorabversionen zulassen und nach Updates suchen.
Alternativ das öffentliche
[LoxBerryHostBackup_1.2.3.zip](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.2.3-beta/LoxBerryHostBackup_1.2.3.zip)
direkt installieren, nicht entpacken. Der direkte Download benötigt kein
GitHub-Konto und ist unabhängig vom Abschluss der Kanalumstellung verfügbar.
Das Paket kann auch für eine Neuinstallation verwendet werden; Backup-Ziel,
Sicherungsverfahren und Quellen danach einrichten und die Vorprüfung ausführen.

Bestehende Installationen direkt aktualisieren, **nicht vorher deinstallieren.**
Aktive Vorgänge beenden lassen und Einstellungen vorher exportieren. Offene
Journale und vorhandene Einstellungen bleiben erhalten; ein laufender
Vorgang darf die Installation weiterhin vorübergehend sperren. Wer schon ein
Testpaket mit interner Version `1.2.3` installiert hat, erhält keinen höheren
numerischen Versionshinweis und kann das öffentliche Beta-ZIP bei Bedarf
manuell darüber installieren.

Nach dem Update Dienst-/Container-Auswahl und Vorprüfung kontrollieren, ein
manuelles Backup vollständig abschliessen lassen und den Wiederanlauf prüfen.
Nicht mehr auflösbare ausgewählte native Dienste müssen geprüft werden; echte
Stop-/Startfehler werden nicht automatisch ignoriert. Bewährte Backups und den
extern gesicherten Repository-Wiederherstellungsschlüssel aufbewahren.

## Freigabenachweise

- Entwicklungsbasis `d4e8e382b9cacb2482738812713775a3a32aff6a`:
  [CI 39298263840](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/39298263840)
  erfolgreich; der Release-Job dieses Branch-Laufs wurde bestimmungsgemäss übersprungen.
- Tag `v1.2.3-beta` auf `381854915f5d24bfc17383b6376d1a611a93ce91`:
  [Tag-CI 39303332839](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/39303332839)
  mit erfolgreichem Build- und Release-Job. 518 Grundtests mit 7 bedingten
  Auslassungen; zusätzlich 15 unprivilegierte Tests, Linux-Integrationssuiten
  mit 29 und 18 Tests, CIFS-Vorprüfung mit 6 Tests und Metadaten-Roundtrip sowie
  CIFS-Suiten mit 29 und 18 Tests. Browserregression und 8 Paketprüfungen erfolgreich.
- Öffentliches GitHub-Pre-Release, kein Entwurf. ZIP ohne Anmeldung mit HTTP 200
  geladen: **29'488'060 Bytes**. Identisch mit Workflow-Artefakt und Asset-Digest;
  zusätzliches lokales ZIP-Audit mit 8 Tests erfolgreich. 32 geprüfte Quell-/Modus-
  Einträge stimmen mit dem Tag überein; Paket und Laufzeit melden `1.2.3`.

SHA-256 des öffentlichen Plugin-ZIPs:

```text
a34d9aa3cc78e681550618980e7fab12c976e7c74800c99afde7a26422d3fc56
```

Die Vorab-Kanaldatei wird erst nach diesen Paketprüfungen umgestellt. Die
abschliessende Remote-/CI-Prüfung des Aktivierungscommits wird als eigener
Nachweis im GitHub-Pre-Release dokumentiert; der stabile Kanal, `main` und das
reguläre Release 1.2.0 bleiben unverändert.

## Prüfgrenzen

Der [Testplan](DR-TESTPLAN.md) umfasst vollständige Backup-/Wiederanlauf-Abläufe,
alte und neue Journale, Instanzdienste, gelöschte oder ersetzte Container,
Alias-Schutz, Fehlerfälle und Installation über einen vorhandenen Stand.
Das [Sicherheitsmodell](SECURITY.md) beschreibt die erhaltenen Schutzgrenzen.

Kontrollierte Docker-/systemd-Antworten und automatisierte Tests ersetzen weder
die Prüfung produktiver Anwenderdienste noch jede NAS-Konfiguration oder einen
bootfähigen Hardware-Restore. Die 7 bedingten Auslassungen sind keine bestandenen
Einzeltests. Ein grüner Branch-Lauf allein belegt weder eine Veröffentlichung
noch den live wirksamen Updatekanal.
