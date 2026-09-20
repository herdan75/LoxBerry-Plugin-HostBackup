# LoxBerry Host Backup: Vorabversion 1.1.0-beta

Hallo zusammen,

die bisherigen develop-Erweiterungen stehen als separate Vorabversion
**1.1.0-beta** zum Testen bereit. **Das stabile Release bleibt 1.0.0.**

Enthalten sind eine explizite Datenquellenauswahl, genauere NAS-Metadaten-Diagnosen,
eine kompaktere Oberfläche mit zusätzlichen Infobuttons und eine erweiterte
Kurzanleitung. Ausserdem wurde der Installationsablauf für zurückgebliebene
geschützte Programmdateien nach einer früheren Deinstallation korrigiert.
Die Fehlermeldung einer nicht erreichbaren Dateisystem-Prüfung bleibt normal
formatiert und erlaubt einen erneuten Prüfversuch.

[**Pre-Release direkt herunterladen: LoxBerryHostBackup_1.1.0.zip**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.1.0-beta/LoxBerryHostBackup_1.1.0.zip)

Keine GitHub-Anmeldung erforderlich. Dieses ZIP direkt installieren,
**nicht entpacken und das bestehende Plugin nicht vorher deinstallieren**.
Vorher aktive Vorgänge beenden lassen und nach Möglichkeit Einstellungen exportieren.

Bestehende Datenquellen-Einstellungen werden nicht automatisch umgestellt.
Wer Netzfreigaben nicht pauschal mitsichern möchte, wählt **Lokale Laufwerke;
Netzfreigaben einzeln (empfohlen)**, kontrolliert gespeicherte Ausnahmen,
speichert und öffnet danach **Nächstes Backup prüfen**. Lokale USB-Nutzdaten
bleiben berücksichtigt, sofern sie nicht ausgeschlossen sind.

Network Compatible ist weiterhin kein Umgehen erforderlicher Metadaten.
Falls das NAS feste Rechte oder Eigentümer erzwingt, zeigt die Vorprüfung
genauere Ursachen. Portable Archive mit Vollbackup kann eine Alternative sein,
wenn dessen eigener Test erfolgreich ist; der System-Restore erfolgt dabei offline.

Die Release-Seite dokumentiert die automatischen Linux-/CIFS-/Browserprüfungen.
Sie ersetzen keinen vollständigen Restore-Test auf der eigenen Hardware und
belegen nicht automatisch eine Reparatur auf jeder VM oder NAS-Konfiguration.
Bei Installationsfehlern bitte das vollständige Log und den verwendeten
Downloadlink senden, keine Passwörter und keine pauschalen Rechteänderungen.

Danke für eure Tests und Rückmeldungen!

Grüsse
Dani
