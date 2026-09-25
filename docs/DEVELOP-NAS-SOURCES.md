# NAS- und Datenquellenauswahl ab 1.1.0-beta

Die Datenquellenauswahl und detaillierte NAS-Diagnose sind Teil der Vorabversion
1.1.0-beta auf Basis von 1.0.0. Das stabile Release 1.0.0 bleibt unverändert.
Installationskorrekturen und Grenzen stehen in den [Release Notes](RELEASE-1.1.0-beta.md).

Die folgenden verständlicheren Bezeichnungen gehören zum aktuellen develop-Stand.
Bereits veröffentlichte Pakete können noch die alten Namen anzeigen. Die Zuordnung
steht unter [Sicherungsverfahren](../README.md#sicherungsverfahren); vorhandene
Konfigurationswerte werden durch die Umbenennung nicht verändert.

## Die beiden Forum-Befunde

1. Netzfreigaben unter `/media/smb/...` konnten zusammen mit `/` ungewollt
   rekursiv kopiert werden. Neue Konfigurationen verwenden eine lokale Grundregel
   mit ausdrücklich gewählten Netzfreigaben. Bestehende Einstellungen bleiben
   unverändert; diese Nutzer müssen die neue Grundregel bewusst speichern.
   Ohne gespeichertes Ziel wird nicht mehr auf den lokalen Standardpfad ausgewichen.
2. Dateisicherung mit reduzierten Metadaten benötigt weiterhin echte Eigentümer, Rechte, ACLs und
   Links. Ein CIFS-Mount mit festen Werten kann das nicht erfüllen. Jeder
   Prüfschritt wird nun sichtbar; ein unpassendes Profil bleibt blockiert.
   Portable Sicherung mit Vollbackup ist der vorgesehene Weg für ein solches Ziel,
   sofern dessen eigener Roundtrip gelingt. Kein stiller Profilwechsel.

## Sichere Anwendung des Testpakets

### Öffentliches Pre-Release herunterladen

[**LoxBerryHostBackup_1.1.0.zip herunterladen**](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/releases/download/v1.1.0-beta/LoxBerryHostBackup_1.1.0.zip)

Dieses ZIP **ohne Entpacken** in der LoxBerry-Plugin-Verwaltung installieren.
Der öffentliche Release-Download erfordert keine Anmeldung bei GitHub.
Programm- und Paketversion sind 1.1.0; der Release-Tag lautet v1.1.0-beta.
Der Vorabkanal ist nach erfolgreicher Downloadprüfung auf dieses Paket gesetzt.

### Alternativ: neuere GitHub-Actions-Testpakete

1. Bei GitHub mit dem eigenen Konto anmelden und die
   [Builds des develop-Teststands](https://github.com/herdan75/LoxBerry-Plugin-HostBackup/actions/workflows/build-plugin.yml?query=branch%3Adevelop)
   öffnen. Den neuesten **erfolgreichen** Lauf für `develop` auswählen und dessen
   Commit prüfen. Ein Link zu einem älteren einzelnen Lauf bleibt auf diesem
   alten Stand; er wechselt nach einem Push nicht automatisch zum neuesten ZIP.
2. Unten unter **Artifacts** auf **LoxBerryHostBackup** klicken.
3. Das heruntergeladene Artefakt-ZIP **einmal entpacken**. Es enthält das eigentliche
   Installationspaket **LoxBerryHostBackup_1.1.0.zip**. Dieses innere ZIP unverändert
   in der LoxBerry-Plugin-Verwaltung hochladen, nicht das äussere Artefakt-ZIP.

GitHub-Artefakte sind zeitlich befristet. Spätere develop-Commits werden nicht
allein durch einen Push zum veröffentlichten Release; ein einzelner Run-Link
bleibt auf seinem Commit. Für das veröffentlichte Paket den direkten Link oben
verwenden. Frühere Testpakete trugen noch dieselbe Versionsnummer wie 1.0.0;
1.1.0-beta ist nun davon unterscheidbar.

### Installation und erster Test

Einstellungen exportieren und laufende Aufgaben beenden lassen. Testpaket
manuell über die Plugin-Verwaltung installieren, nicht vorher deinstallieren.
Unter Laufwerke und Netzfreigaben lokale Grundregel auswählen, gewünschte
eingebundene Freigaben aktivieren und speichern. Vorherige Ausschlüsse behalten
ihre Wirkung. Der Sicherungsdatenträger darf nicht als Quelldaten mitgesichert
werden; das Backup-Ziel selbst bleibt automatisch ausgeschlossen.

Die Hauptliste zeigt Datenträger, Netzfreigaben und gespeicherte Ausnahmen.
System-, Automount- und Docker-Einbindungen stehen unter aufklappbaren technischen
Details, einschliesslich der Anzahl der weiterhin berücksichtigten Einbindungen.
Diese kompaktere Darstellung ändert weder Grundregel noch Sicherungsumfang.
Längere Erläuterungen stehen unter „Hinweise zur Auswahl“; der Speicherhinweis
bleibt direkt sichtbar. Die Typografie wird unabhängig von globalen LoxBerry-
Schriftregeln gesetzt.

Die Auswahl heisst jetzt funktionsbezogen „Lokale Laufwerke; Netzfreigaben
einzeln (empfohlen)“ oder „Alle eingebundenen Laufwerke und Netzfreigaben“ statt
„Bisheriges Verhalten“. Der Infobutton direkt neben Datenquellen erklärt beide
Regeln und ihre Folgen. Die internen Werte local/legacy, der Standard für neue
Konfigurationen und vorhandene Einstellungen werden dadurch nicht geändert.
Auch bei einem ODROID N2+ mit USB-Nutzdaten ist die lokale Regel passend: den
Nutzdatenträger eingeschlossen und den reinen Backup-Datenträger ausgeschlossen
lassen. Ziel, Sicherungsverfahren, Sicherungsart und Zeitplan bleiben bestehen.

Bei einem Metadatenfehler die einzelnen Prüfschritte lesen. Falls das NAS feste
Eigentümer/Rechte erzwingt, Portable Sicherung **und** Vollbackup auswählen und
speichern; erneut prüfen. Archive sind nicht inkrementell und erfordern für
den System-Restore eine Offline-/Rescue-Umgebung.

Der aktuelle develop-Stand ergänzt **Portable Sicherung** um **Platzsparende
Sicherungsstände** in einem verschlüsselten Repository. Das ist kein fünftes
Profil und keine Änderung bestehender Vollarchive. Erst nach Einrichtung am
gespeicherten Ziel und bestätigter externer Schlüsselaufbewahrung umstellen;
automatischen tar.gz-Export unter **Sicherungsart / Zusatzexport** bewusst
deaktivieren. Die zunächst zugeklappte **Einrichtung für platzsparende
Sicherungsstände** steht direkt unter **Sicherungsverfahren** und ist nur bei
gewählter **Portable Sicherung** sichtbar. Portable Vollbackups benötigen diese
Einrichtung nicht. Aufklappen oder ein Profilwechsel ändern keine weiteren
Einstellungen und richten kein Repository ein. Für Repository-Stände ist beim
Offline-Restore zusätzlicher Linux-Zwischenspeicher nötig. Die
[Repository-Anleitung](PORTABLE-REPOSITORY.md) beschreibt Voraussetzungen und
Recovery. Ein bereits veröffentlichtes 1.1.0-beta-Paket enthält diese neue
develop-Erweiterung nicht automatisch.

## Technische Schutzmassnahmen

- Auswahl anhand der Kernel-Mount-Tabelle ohne Auslesen von Zugangsdaten.
- Kein Betreten ausgeschlossener autofs-/Netzwerkbäume zur Dateierfassung.
- Dateiliste nach dem Dienst-Stopp; rsync und tar verarbeiten sie ohne Rekursion.
- Bei einem Erfassungsfehler greift derselbe Dienst-Wiederanlauf wie bei anderen
  Backupfehlern. Eine Teilliste wird nicht kopiert.
- Mount-Identität vor/nach Erfassung und nach der Kopie prüfen; erst danach
  Dienste/Container wieder starten, da deren Mount-Änderungen erwartet werden.
- `source-selection.json` hält die tatsächliche Auswahl fest und schützt beim
  Volume-Restore vor der Auswahl nicht gesicherter Quellen.
- Metadaten-Diagnose ist begrenzt, enthält keine Mount-Zugangsdaten und liegt
  atomar ersetzt mit Modus 0600 in den geschützten Laufzeitdaten.

## Prüfumfang und Grenzen

Automatische Tests prüfen die Auswahl von zehn NAS-Freigaben, erhaltene
USB-/Boot-Daten, Ausschlüsse, fehlende Quellen, unveränderte Alt-Konfigurationen,
Dateilistentransport, Restore-Schutz und sichere Anzeige/Übernahme im Browser.

`tests/run-cifs.sh` erzeugt nur auf einem ausdrücklich freigegebenen, isolierten
Linux-Testsystem einen temporären lokalen Samba-Server mit echtem CIFS-Mount.
Mit `forceuid`, `forcegid`, festen Dateirechten und `nounix` muss Network
Compatible einen detaillierten Fehler liefern. Portable Sicherung muss dort
Metadaten erfolgreich sichern und lokal wiederherstellen. Die CIFS-Quelle darf
nur nach ausdrücklicher Auswahl durch rsync/tar kopiert werden.

Windows-Tests ersetzen diese Linux-Prüfung nicht. Ein grüner CIFS-Test ersetzt
seinerseits keinen Gegencheck auf der konkreten QNAP/Synology mit deren Mount-Optionen,
keinen vollständigen System-/Boot-Restore und keinen echten LoxBerry-Neustarttest.
