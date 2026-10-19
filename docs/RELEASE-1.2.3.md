# LoxBerry Host Backup 1.2.3-beta

**Vorabfreigabe vom 19.10.2026.** Interne Programm- und Paketversion: `1.2.3`,
Release-Tag: `v1.2.3-beta`, Plugin-ZIP: `LoxBerryHostBackup_1.2.3.zip`.
Der stabile Kanal und `main` bleiben auf **1.2.0**; ältere Pakete unverändert.

**Freigabestatus:** Die Entwicklungsbasis `d4e8e38` ist erfolgreich geprüft.
Tag-Pipeline und öffentlicher ZIP-Download benötigen noch ihre eigene Prüfung.
Erst danach wird der bisherige Vorabfeed von **1.2.2-beta** auf **1.2.3-beta**
umgestellt. Der Branch-Lauf allein ist kein Nachweis der Veröffentlichung.

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

Nach Aktivierung des neuen Vorabfeeds in der LoxBerry-Pluginverwaltung
Vorabversionen zulassen und nach Updates suchen. Alternativ das freigegebene
`LoxBerryHostBackup_1.2.3.zip` direkt installieren, nicht entpacken.
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

## Prüfung und Grenzen

Der [Testplan](DR-TESTPLAN.md) umfasst vollständige Backup-/Wiederanlauf-Abläufe,
alte und neue Journale, Instanzdienste, gelöschte oder ersetzte Container,
Alias-Schutz, Fehlerfälle und Installation über einen vorhandenen Stand.
Das [Sicherheitsmodell](SECURITY.md) beschreibt die erhaltenen Schutzgrenzen.
Die Entwicklungsbasis `d4e8e382b9cacb2482738812713775a3a32aff6a` hat
[CI-Lauf 39298263840](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/runs/39298263840)
erfolgreich abgeschlossen: Build-/Testjob erfolgreich, Release-Job beim
Branch-Lauf bestimmungsgemäss übersprungen. Dies belegt die Entwicklungsabnahme,
nicht die noch gesondert nachzuweisende Tag-/Paketfreigabe.

Kontrollierte Docker-/systemd-Antworten und automatisierte Tests ersetzen weder
die Prüfung produktiver Anwenderdienste noch jede NAS-Konfiguration oder einen
bootfähigen Hardware-Restore. Ein develop-Push oder Workflow-Artefakt ist keine
Veröffentlichung. Die Freigabe benötigt gesondert geprüfte Tag-Pipeline,
öffentlichen ZIP-Download und anschliessende Aktivierung des Vorabfeeds.
