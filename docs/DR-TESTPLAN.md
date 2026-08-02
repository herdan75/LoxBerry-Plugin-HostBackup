# Disaster-Recovery-Testplan

Dieser Plan ist vor einer neuen stabilen Veröffentlichung und danach mindestens
bei Änderungen an rsync-/tar-Optionen, Mount-Prüfung, Import, Restore oder
Retention auszuführen. Produktive Daten werden durch synthetische Marker und
Testdienste ersetzt.

## Testmatrix

| Ziel | Profil | Backup-Modus | Erwartung |
|---|---|---|---|
| ext4/xfs/btrfs | Native Strict | Full + Snapshot | `complete`, Validierung `ok`, Metadaten vollständig |
| CIFS Synology | Network Compatible | Full | `complete`, Validierung `ok`, neutraler Hinweis auf bewusst ausgelassene xattrs |
| NFS Synology | Network Compatible | Full | `complete`, Validierung `ok`, neutraler Hinweis auf bewusst ausgelassene xattrs |
| Ziel mit stabilen user-xattrs | Fake Super | Full + Snapshot | `complete`, `user.rsync.*` nachweisbar |
| CIFS/NFS | Portable Archive | Full | `complete`, `rootfs.tar`, Restore nur offline |

Snapshot ist mit Portable Archive abzulehnen. Native Strict muss auf einem Ziel,
das die Probe nicht besteht, vor dem eigentlichen Backup fehlschlagen.

## Testdaten

Auf einem isolierten LoxBerry-/DietPi-Testhost anlegen:

- normale Datei mit UID/GID ungleich Root und Modus `0640`,
- Verzeichnis mit Default-ACL und Datei mit zusätzlicher ACL,
- `user.*`-xattr,
- Testkopie einer Datei mit `security.capability`,
- Hardlink-Paar und relativer Symlink,
- Sparse-Datei mit mindestens 1 GiB logischer Grösse,
- Test-systemd-Dienst und Testcontainer mit eindeutigem Vorher-Zustand,
- kleine Testdatenbank mit applikationsspezifischem Dump-Hook.

Prüfsummen und Metadaten vorab mit `sha256sum`, `stat`, `getfacl`, `getfattr`,
`getcap`, `du` und `ls -li` erfassen.

## Ablauf je Matrixzeile

1. Ziel einhängen, Einstellungen speichern und Zielmarker dokumentieren.
2. Preflight ausführen und Metadaten-Roundtrip prüfen.
3. Backup starten; Task-Phasen und Dienst-/Container-Stop beobachten.
4. Manifest, Validierungsdatei, Marker, Dateizahl und Status prüfen.
5. Export erzeugen; `sha256sum -c` und Descriptor/Manifest-Hash prüfen.
6. Export löschen, neu erzeugen, extern kopieren und wieder importieren.
7. Import mit Traversal-, Symlink-, Hardlink-, Duplicate- und Grössen-Testarchiven
   wiederholen; jeder negative Fall muss ohne Veröffentlichung im Backup-Ziel
   enden.
8. Restore auf einem frisch installierten, isolierten Zielhost aus Rescue-/
   Offline-Umgebung durchführen.
9. Prüfsummen, UID/GID, Modi, ACLs, xattrs, Capabilities, Hardlinks, Symlinks und
   Sparse-Belegung vergleichen.
10. Dienste, Container, LoxBerry-Weboberfläche, Netzwerk und Testdatenbank prüfen.

Bei Network Compatible sind fehlende xattrs/Capabilities der erwartete und zu
dokumentierende Unterschied. Alle regulären Dateiinhalte, UID/GID, Modi, ACLs,
Hardlinks und Symlinks müssen trotzdem übereinstimmen.

## Fehler- und Abbruchtests

- NAS während der Kopie aushängen: Task muss fehlschlagen; lokaler Fallback darf
  nicht verwendet werden.
- Backup während Dienst-Stopp, Kopie, Validierung und Export mit `TERM` stoppen:
  nur zuvor laufende Ziele werden neu gestartet; Task zeigt Fehler/Stopped oder
  `cleanup_failed` mit Logdetails.
- Parallel Backup, Restore, Import, Export, Löschen und Retention anstossen:
  konfliktbehaftete Aktionen müssen am globalen oder Backup-Lock scheitern.
- PID wiederverwenden simulieren: abweichende `/proc`-Startzeit darf keinen
  fremden Prozess stoppen.
- Manifest, Marker, Validierung und Export-Prüfsumme einzeln manipulieren: Browse,
  Export, Löschen oder Restore müssen entsprechend blockieren.
- Pre-/Post-Hook fehlschlagen lassen: Backup muss fehlschlagen und der
  Wiederanlauf muss trotzdem geprüft werden.

## Freigabekriterium

Eine stabile Veröffentlichung ist erst freigabefähig, wenn alle automatisierten
Tests grün sind und jede relevante Matrixzeile einen datierten Testnachweis mit
Host-/OS-Version, Dateisystem, Profil, Backup-ID, Restore-Ziel und Ergebnis hat.
Ein fehlender echter Offline-Restore bleibt ein Release-Blocker und darf nicht
durch einen erfolgreichen Backup- oder Exporttest ersetzt werden.
