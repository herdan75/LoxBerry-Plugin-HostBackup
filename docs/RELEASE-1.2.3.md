# LoxBerry Host Backup 1.2.3 – Entwicklungsstand

**Noch nicht veröffentlicht.** Interne Programm- und Paketversion: `1.2.3`.
Vorbereitung für eine spätere `1.2.3-beta`; es gibt dafür noch keinen öffentlichen
Release-Download und kein Update-Angebot über LoxBerry. Der Vorabkanal bleibt
auf **1.2.2-beta**, der stabile Kanal und `main` bleiben auf **1.2.0**.

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

## Testpaket installieren

Ein aus diesem Entwicklungsstand gebautes `LoxBerryHostBackup_1.2.3.zip` kann manuell über die
bestehende Installation installiert werden. **Nicht vorher deinstallieren.**
Aktive Vorgänge beenden lassen und Einstellungen vorher exportieren. Offene
Journale und vorhandene Einstellungen sollen erhalten bleiben; ein laufender
Vorgang darf die Installation weiterhin vorübergehend sperren.

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
Diese Entwicklungsnotiz behauptet noch keine bestandene Freigabeprüfung:
Testergebnisse müssen dem genauen Commit zugeordnet werden.

Kontrollierte Docker-/systemd-Antworten und automatisierte Tests ersetzen weder
die Prüfung produktiver Anwenderdienste noch jede NAS-Konfiguration oder einen
bootfähigen Hardware-Restore. Ein develop-Push oder Workflow-Artefakt ist keine
Veröffentlichung. Eine spätere Freigabe benötigt gesondert geprüfte Tag-Pipeline,
öffentlichen ZIP-Download und anschliessende Aktivierung des Vorabfeeds.
