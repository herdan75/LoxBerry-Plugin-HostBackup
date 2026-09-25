# Portable Sicherungsstände auf NAS

Diese Anleitung beschreibt die Repository-Erweiterung von **1.2.0-beta vom
25.09.2026**, nicht nachträglich den Funktionsumfang der unveränderten
1.1.0-beta-Pakete. Das reguläre Release bleibt 1.0.0. Der Vorabkanal wurde nach
Prüfung des öffentlichen ZIPs auf 1.2.0 aktiviert; den Freigabenachweis und die
Prüfgrenzen nennen die [Release Notes](RELEASE-1.2.0-beta.md).

## Was sich ändert

Es bleiben vier Sicherungsverfahren und zwei Sicherungsarten. Normal sichtbar
sind **Linux-Dateisicherung** und **Portable Sicherung**; die zwei Spezialverfahren
stehen unter **Erweiterte Einstellungen**. Interne Konfigurationswerte bleiben
unverändert. Bestehende Einstellungen werden nicht automatisch umgestellt.

| Auswahl bei Portable Sicherung | Gespeichertes Format | Folgesicherung und Restore |
| --- | --- | --- |
| Vollbackup | Eigenständiges `rootfs.tar` (`portable-tar`) | Jedes Archiv enthält den gesamten ausgewählten Stand; System-Restore offline wie bisher |
| Platzsparende Sicherungsstände | Verschlüsseltes Repository (`portable-repository`) | Erster Stand vollständig, danach Wiederverwendung gemeinsamer Datenblöcke; Schlüssel und zusätzlicher Linux-Zwischenspeicher für Offline-Restore nötig |

Restic ist das interne Speicherwerkzeug, kein weiterer Benutzermodus. Linux-
Eigentümer, Rechte und weitere Metadaten werden innerhalb des Sicherungsformats
gespeichert. Das NAS muss sie nicht für jede gesicherte Datei direkt darstellen.
Das hilft beispielsweise bei SMB-Freigaben mit festen UID/GID und Dateirechten.
Es ersetzt nicht die eigene Zielprüfung: Schreibrechte, konsistente Dateizugriffe,
Mount-Identität, freier Platz, Quoten und ein erfolgreicher Rücklesetest bleiben
erforderlich. Ein bestandenes CIFS-Testszenario ist keine Zusage für jedes NAS.

Ein Stand beschreibt immer den vollständigen ausgewählten Dateibaum. Das heisst
nicht, dass jedes Mal die gesamte Datenmenge neu auf das NAS geschrieben wird.
Bei einer geänderten grossen Datei kann trotzdem viel gelesen werden müssen.
Logischer Sicherungsumfang und zusätzliche Repository-Belegung sind verschiedene
Werte; gemeinsame Daten dürfen nicht pro Stand mehrfach als belegter Speicher
addiert werden. Ein Sicherungsstand ist ausserdem kein atomarer Snapshot laufender
Datenbanken. Geeignete Dienste weiterhin gezielt stoppen oder Datenbank-Dumps
über die vorhandenen Hooks erzeugen.

Laufzeitgebundene **Unix-Sockets** werden bei portablen Repository-Ständen
ausdrücklich ausgelassen: Sie sind Kommunikationsendpunkte, keine dauerhaft
wiederherstellbaren Nutzdaten, und werden von ihren Diensten neu angelegt.
Gezählt werden nur per `lstat` bestätigte Sockets, nicht beliebige Dateien mit
der Endung `.sock`. Anzahl, bis zu 20 Beispielpfade und Begründung stehen im
Quellenauswahlbericht unter `omitted_runtime_sockets` sowie als Hinweis im Log.
FIFOs, Gerätedateien und symbolische Links bleiben in der Auswahlliste. Lese- oder
Mountfehler werden dadurch nicht ignoriert. Andere Sicherungsverfahren und
bestehende Vollarchive erhalten durch diese Repository-Regel keine neue Auslassung.

## Einrichtung in der Oberfläche

Wichtige bestehende Sicherungen zunächst aufbewahren. Ein Repository wird nicht
aus einem alten Vollarchiv erzeugt, und die Einrichtung startet kein Backup.
Für portable Vollbackups ist diese Einrichtung nicht nötig. Die Kurzanleitung
in der Oberfläche beschreibt vier Phasen: Ziel mit Vollbackup speichern,
Repository einrichten, Wiederherstellungsdatei extern sichern und bestätigen,
danach auf platzsparende Sicherungsstände ohne Zusatzexport umstellen und prüfen.
Die folgenden Schritte erläutern diesen Ablauf im Detail.

Die vollständige Metadatenprüfung benötigt unter Linux `rsync`, GNU `tar`,
`findmnt`, Python 3 sowie `getfacl/setfacl`, `getfattr/setfattr` und `getcap/setcap`.
Auf Debian/LoxBerry stammen diese Werkzeuge aus `rsync`, `tar`, `util-linux`,
`python3`, `acl`, `attr` und `libcap2-bin`. Fehlende Werkzeuge werden nicht durch
eine schwächere Prüfung ersetzt. Die passende Restic-Engine für amd64, ARM oder
ARM64 wird dagegen checksum-geprüft mit dem Pluginpaket geliefert.

1. Das tatsächliche eingebundene NAS-/USB-Backup-Ziel und die gewünschten
   Datenquellen prüfen. Das Ziel selbst darf nicht als Quelle kopiert werden.
2. Zunächst **Portable Sicherung** und **Vollbackup** wählen, Ziel und
   Root-Freigabe speichern. Eine Fehlermeldung der Zielprüfung zuerst klären.
3. Im Bereich **Sicherungsverfahren** direkt bei der gewählten **Portable
   Sicherung** die **Einrichtung für platzsparende Sicherungsstände** aufklappen
   und den Status prüfen. Dieser Zusatzbereich ist nur bei Portable Sicherung
   sichtbar und zunächst zugeklappt.
   **Repository am gespeicherten Ziel einrichten** ausdrücklich ausführen.
4. **Geheime Wiederherstellungsdatei herunterladen** wählen. Die Datei enthält
   den Repository-Schlüssel: ausserhalb dieses LoxBerry sicher aufbewahren,
   beispielsweise in einem verschlüsselten Passwort-/Dateispeicher. Nicht in
   Foren, normalen Logs oder Diagnosepaketen teilen.
5. Prüfen, dass die heruntergeladene Datei dort vorhanden und zugänglich ist.
   Erst dann die Checkbox zur externen Aufbewahrung setzen und bestätigen.
   Der Download allein bestätigt die Aufbewahrung nicht automatisch.
6. Unter **Sicherungsart** jetzt **Platzsparende Sicherungsstände** wählen. Die
   dort unter **Zusatzexport** angeordnete Option **Nach jedem Backup ein tar.gz-Archiv erstellen**
   ausdrücklich deaktivieren; diese Exportart ist für Repository-Stände nicht
   verfügbar. Es erfolgt keine stille Korrektur.
7. Einstellungen speichern, **Nächstes Backup prüfen** ausführen und den
   gewünschten Sicherungsumfang sowie alle Prüfergebnisse kontrollieren.
8. Ein manuelles Testbackup vollständig abschliessen lassen. Struktur- und
   Inhaltsprüfung sowie einen Restore-Test durchführen, bevor alte bewährte
   Sicherungen aufgegeben werden. Erst dann den gewünschten Zeitplan verwenden.

Aufklappen, Zuklappen und Profilwechsel starten keine Einrichtung und stellen
Sicherungsart oder Exportoption nicht automatisch um. Die externe
Schlüsselaufbewahrung wird nur durch die eigene Bestätigungsaktion bestätigt,
nicht durch normales Speichern der Einstellungen.
Mit JavaScript wird der Status bei gewählter Portable Sicherung auch im
zugeklappten Bereich rein lesend geladen; für späteres Speichern muss die
Einrichtung nicht erneut aufgeklappt werden. Ohne JavaScript richtet sich die
Sichtbarkeit nach dem serverseitig angezeigten Verfahren. Nach einem Wechsel
zuerst speichern und die neu geladene Seite verwenden; die eigenen
Einrichtungs-, Download- und Bestätigungsbuttons bleiben nutzbar.

Die Freigabe gilt für das gespeicherte Ziel und dessen Repository. Bei einem
Zielwechsel reicht der bestätigte Schlüssel eines anderen Repositorys nicht.
Zunächst die Zielkonfiguration mit Vollbackup speichern, danach das gewünschte
Repository dort ausdrücklich einrichten. Bei einem bereits bestehenden
Repository ohne lokale Zuordnung nicht neu initialisieren, sondern den unten
beschriebenen Recovery-/Wiederanbindungsweg verwenden.

## Schlüssel, Aufbewahrung und Export

Der laufende Host hält seine lokale Repository-Zuordnung und den Schlüssel in
rootgeschütztem Status, nicht in der normalen Plugin-Konfiguration. Ein
Konfigurationsexport ersetzt deshalb **nicht** die Wiederherstellungsdatei.
Umgekehrt enthält die Wiederherstellungsdatei weder das Backup selbst noch
automatisch die Zugangsdaten zur NAS-Freigabe. Für den Notfall werden benötigt:

- die vollständige gemeinsame Repository-Datenbasis mit den zugehörigen
  Sicherungsinformationen auf dem Backup-Ziel,
- die passende externe Wiederherstellungsdatei,
- Zugang zum NAS und ein vertrauenswürdiger passender Linux-Recovery-Helfersatz.

Ein einzelner Backup-Ordner ist kein transportierbares Repository-Backup.
Interne Dateien nicht manuell verschieben, löschen, bearbeiten oder einzeln
zippen. Die normale Einzelarchiv-Exportfunktion, Ordneransicht mit Einzeldatei-
Restore und direkter Online-Restore werden für diese Stände nicht angeboten.
Wer ein eigenständiges TAR benötigt, kann weiterhin bewusst ein portables
Vollbackup erstellen; ein Restic-TAR-Dump wird nicht als gleichwertiger
metadatentreuer Vollsystemexport ausgegeben.

Schutzmarkierungen, Prüfungen und Aufbewahrung bleiben in der Pluginoberfläche
nutzbar. Nur diese integrierte Verwaltung für Stände verwenden. Die automatische
Aufbewahrung entfernt die ausgewählten Stand-Verweise, führt aber **keine
Repository-Platzbereinigung** aus. Auch ausschliesslich gelöschten Ständen
zugehörige Blöcke belegen zunächst weiter Platz. Noch referenzierte gemeinsame
Blöcke dürfen ohnehin nicht entfernt werden. Eine zusätzliche
NAS-Sicherung des Repositorys muss einen konsistenten Gesamtstand erfassen,
nicht parallel eine beliebige Mischung aus laufenden Backup-/Wartungsschritten.

### Repository-Platz bewusst bereinigen

Im eingerichteten LoxBerry als Root zunächst nur die Vorschau aufrufen:

```sh
/usr/local/sbin/loxberryhostbackup repository-prune
```

Nach Kontrolle des Backup-Ziels, der angezeigten vollständigen Repository-ID und
einer erfolgreichen Inhaltsprüfung kann die Bereinigung ausdrücklich ausgeführt
werden. Den Platzhalter durch genau diese 64-stellige ID ersetzen:

```sh
/usr/local/sbin/loxberryhostbackup repository-prune --confirm-repository-id REPOSITORY_ID
```

Der Aufruf verwendet die globale Vorgangssperre und prüft das Repository vor und
nach dem Schritt. Er entfernt nur vollständig unbenutzte Datenpakete, ohne grosse
Pakete neu zu schreiben (`--max-repack-size 0`). Teilweise noch verwendete Pakete
bleiben deshalb erhalten; die Vorschau ist keine Zusage, dass die gesamte
logische Grösse gelöschter Stände frei wird. Abgebrochene unbestätigte Kandidaten
werden nicht automatisch verworfen. Bei einer Sperre oder Fehlermeldung nichts
erzwingen, keine Sperrdateien löschen und keine internen Dateien manuell entfernen.
Der direkte Adapter ist kein Ersatz für die gesperrte Plugin-Verwaltung.

## Offline-Wiederherstellung

Die folgenden Befehle sind für eine getrennte, vertrauenswürdige Linux-Rescue-
Umgebung gedacht, in der der passende HostBackup-Helfersatz inklusive geprüfter
Engine installiert ist. Sie sind **keine** Anleitung, das laufende LoxBerry-
Root-Dateisystem zu überschreiben. Quellbackup, Zwischenspeicher und Restore-Ziel
müssen getrennt sein. Vor jeder Ausführung die tatsächlichen Pfade prüfen.

Voraussetzungen:

- Backup-Architektur und Rescue-Architektur stimmen überein. x86/VMware zu ARM/
  Raspberry Pi ist keine automatische Vollsystemmigration. Auch bei gleicher
  Architektur müssen Zielhardware, Kernel und Bootumgebung separat passen.
- Das NAS ist wirklich eingehängt und das richtige Repository zugänglich.
  Bei verlorenem Mount oder falschem Schlüssel abbrechen, nicht neu initialisieren.
- Ein leeres, rootgeschütztes Verzeichnis auf einem geeigneten Linux-Dateisystem
  dient als **Staging**. Es benötigt Platz für den vollständigen wiederhergestellten
  Stand, zusätzlich 20 Prozent und 1 GiB Reserve. Linux-Metadaten werden dort
  vor dem Restore geprüft. Derselbe feste-Rechte-SMB-Mount ist dafür ungeeignet.
- Ein gesondertes vorbereitetes Offline-Systemziel ist eingehängt, beispielsweise
  unter `/mnt/recovery-root`. Es darf nicht `/` sein. Zusätzliche Boot-/Daten-
  Volumes ausdrücklich zuordnen; ausgelassene Volumes in der Vorschau prüfen.
- Auch zugeordnete Ziel-Volumes müssen die verlangte Linux-Metadatenprüfung
  bestehen, bevor Systemdateien überschrieben werden. FAT-/exFAT-Bootpartitionen
  erfüllen diese Prüfung nicht. Deren Vorbereitung und erforderliche Bootdateien
  müssen im passenden hardwarebezogenen Recovery-Verfahren separat behandelt
  werden; keine automatische vollständige Raspberry-Pi-Bootreparatur versprechen.
- Der Stand ist vollständig abgeschlossen und geprüft. Ein Stand mit Warnungen
  wird nicht automatisch für den vollständigen System-Restore freigegeben.

### 1. Vorhandenes Repository am neuen Rescue-Host anbinden

Die Beispiele als Root ausführen und alle Beispielpfade ersetzen. Niemals eine
vorhandene lokale Schlüsselzuordnung oder Wiederherstellungsdatei überschreiben.
Auf einem bereits verwendeten Helferhost zuerst dessen Zustand klären; keine
pauschale Bereinigung von `/var/lib/loxberryhostbackup` durchführen.

**Falls auf dem frischen Rescue-Linux noch keine HostBackup-Helfer installiert
sind:** Zuerst die oben genannten Systemwerkzeuge bereitstellen. Das passende
unveränderte Plugin-ZIP aus einer vertrauenswürdigen Quelle herunterladen und
seine veröffentlichte Prüfsumme kontrollieren. Das eigentliche Installations-ZIP
(nicht den GitHub-Artefakt-Umschlag) in ein leeres Verzeichnis entpacken, hier als
Beispiel `/mnt/tools/hostbackup-package`. Dann nur die Recovery-Helfer in eine
neue Root-Laufzeit kopieren; kein laufendes Plugin ersetzen:

```sh
test -f /mnt/tools/hostbackup-package/bin/hostbackup-engine.py || exit 1
install -d -o root -g root -m 0755 /usr/libexec/loxberryhostbackup/releases
runtime=$(mktemp -d /usr/libexec/loxberryhostbackup/releases/rescue.XXXXXXXX)
for helper in /mnt/tools/hostbackup-package/bin/*.py; do
  test -f "$helper" && test ! -L "$helper" || exit 1
  install -o root -g root -m 0755 "$helper" "$runtime/"
done
python3 "$runtime/hostbackup-engine.py" install /mnt/tools/hostbackup-package "$runtime" || exit 1
```

Der Helfer prüft die mitgelieferte Architektur und Engine-Prüfsumme; dafür ist
kein Download während der Wiederherstellung nötig. Die Variable `runtime` in
derselben Shell für die folgenden Schritte behalten. Existiert bereits eine
vertrauenswürdige installierte Laufzeit, wird stattdessen deren Verweis verwendet:

```sh
runtime=${runtime:-$(readlink -f /usr/libexec/loxberryhostbackup/current)}
test -f "$runtime/hostbackup-repository.py"
test -f "$runtime/hostbackup-portable.py"
findmnt -T "/mnt/nas/loxberry-hostbackup" -o TARGET,SOURCE,FSTYPE
```

Nur wenn die Helfer vorhanden sind und das richtige NAS-Dateisystem angezeigt
wird, den privaten Zustand in der frischen Rescue-Umgebung anlegen. Die externe
Recovery-Datei mit Modus `0600` unter einem noch nicht belegten Root-Pfad ablegen:

```sh
install -d -m 0700 /var/lib/loxberryhostbackup /var/lib/loxberryhostbackup/repositories
test ! -e /root/hostbackup-recovery.json && install -m 0600 "/media/recovery-key/loxberryhostbackup-recovery-key.json" /root/hostbackup-recovery.json
python3 "$runtime/hostbackup-repository.py" \
  --backup-root "/mnt/nas/loxberry-hostbackup" \
  --state-dir /var/lib/loxberryhostbackup/repositories \
  attach --recovery-key /root/hostbackup-recovery.json
```

Bei einem Fehler stoppen. `attach` prüft den Schlüssel und die Repository-
Identität; es ist kein `init`. Bereits vorhandener lokaler Zustand wird nicht
automatisch überschrieben. Abgeschlossene authentifizierte Stände auflisten:

```sh
python3 "$runtime/hostbackup-repository.py" \
  --backup-root "/mnt/nas/loxberry-hostbackup" \
  --state-dir /var/lib/loxberryhostbackup/repositories list
```

### 2. Vollständigen Stand bereitstellen und Restore vorschauen

`BACKUP_ID` durch die gewählte vollständige Backup-ID ersetzen. Staging und
Offline-Ziel vorher auf getrennten geeigneten Datenträgern vorbereiten und
Einbindung, freien Platz sowie Inhalt prüfen. Der Helfer löscht Staging nicht:
das angegebene Verzeichnis muss bereits existieren, leer und rootgeschützt sein.

```sh
HOSTBACKUP_OFFLINE_RESTORE=1 python3 "$runtime/hostbackup-portable.py" \
  --root "/mnt/nas/loxberry-hostbackup" \
  --state-dir /var/lib/loxberryhostbackup recover \
  --backup-id BACKUP_ID \
  --staging "/mnt/linux-staging/preview" \
  --destination "/mnt/recovery-root" \
  --map-json '[]'
```

Ohne `--execute` wird der vollständige Stand aus dem Repository in Staging
bereitgestellt und eine Datei-/Löschvorschau erzeugt. Das ist nicht nur eine
kleine Statusabfrage: es benötigt Zeit und den vollständigen Staging-Platz.
Das Offline-Systemziel wird in diesem Vorschauaufruf noch nicht wiederhergestellt.

`[]` bedeutet **keine zusätzlichen Volume-Zuordnungen**. Im Backup vorhandene
separate Volumes werden deshalb nicht automatisch übernommen. Für tatsächlich
gesicherte und am Ziel vorbereitete Volumes die passende Zuordnung angeben, z. B.
`--map-json '[{"source":"/boot","destination":"/mnt/recovery-root/boot"}]'`.
Dieses Beispiel nur verwenden, wenn es zur tatsächlichen Quell-/Zielstruktur
passt. Ausschlüsse, ausgelassene Volumes und geplante Löschungen kontrollieren.

### 3. Bewusst ausführen und Ergebnis kontrollieren

Erst nach Prüfung derselben Backup-ID, Zielpfade und Volume-Zuordnungen den
Aufruf mit `--execute` wiederholen. Dieser Schritt kann Dateien am Offline-Ziel
überschreiben und im freigegebenen Bereich löschen. Für den erneuten Aufruf einen
**anderen leeren Staging-Pfad** verwenden oder den vorherigen nach eigener
genauer Prüfung bewusst bereinigen. Keine automatische Löschung wird angeboten.
Zwei gleichzeitig behaltene Staging-Stände benötigen entsprechend mehr Platz.

```sh
HOSTBACKUP_OFFLINE_RESTORE=1 python3 "$runtime/hostbackup-portable.py" \
  --root "/mnt/nas/loxberry-hostbackup" \
  --state-dir /var/lib/loxberryhostbackup recover \
  --backup-id BACKUP_ID \
  --staging "/mnt/linux-staging/execute" \
  --destination "/mnt/recovery-root" \
  --map-json '[]' --execute
```

Auch hier erforderliche Volume-Zuordnungen aus der geprüften Vorschau übernehmen.
Ein Ende mit Fehlern ist kein erfolgreicher Restore. Anschliessend Rechte,
Dateien, Datenbanken, Bootkonfiguration und Anwendungen prüfen und einen
kontrollierten Starttest auf der passenden Zielhardware durchführen. Erst dieser
Test belegt, ob das konkrete System wieder betriebsfähig ist. Partitionierung,
Bootloader-Reparatur und Hardwaremigration erledigt diese Dateiwiederherstellung
nicht automatisch.

Auf einem vorhandenen vertrauenswürdig eingerichteten LoxBerry steht alternativ
der verkürzte Root-Aufruf `repository-recover ID STAGING ZIEL MAP_JSON [--execute]`
über `/usr/local/sbin/loxberryhostbackup` bereit. Er verwendet das gespeicherte
Backup-Ziel und dieselben Offline-/Staging-Grenzen. Die vollständige Recovery-
Anleitung gilt weiterhin; kein Aufruf darf direkt auf `/` zielen.

## Prüfungen und Grenzen

Die automatisierten Linux-/CIFS-Tests prüfen definierte Dateitypen, Inhalte und
Metadaten unter künstlich eingeschränkten SMB-Mountbedingungen. Die
[DR-Testmatrix](DR-TESTPLAN.md) bleibt für eine Freigabe verbindlich. Tests auf
x86-Linux ersetzen weder Messungen auf kleiner ARM-Hardware noch reale QNAP-/
Synology-, Stromausfall- oder bootfähige Ende-zu-Ende-Systemtests. Vor produktiver
Nutzung eigene Sicherungs- und Wiederherstellungstests durchführen und eine
weitere unabhängige Sicherung behalten.
