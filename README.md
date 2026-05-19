# LoxBerry Host Backup

LoxBerry Host Backup is a disaster-recovery plugin for a complete host backup.
It is intended for LoxBerry systems that also run Docker containers, DietPi
software, native services, scripts, and other data outside LoxBerry itself.

The plugin is deliberately not based on the older Raspberry Pi specific
LoxBerry backup plugin. Its primary backup mode is an `rsync` snapshot of the
whole host filesystem with runtime-only paths excluded.

## Goals

- Full host backup comparable to DietPi-Backup.
- Restore a freshly installed LoxBerry/DietPi/Debian host from backup.
- Include LoxBerry, Docker data, native services, package state, and user data.
- Show existing backup files in the LoxBerry web UI.
- Browse the content of a backup snapshot from the web UI.
- Download individual files from a backup snapshot.
- Start backups in the background from the web UI.
- Export a backup as a `.tar.gz` archive.
- Move a full backup set to another absolute storage path.
- Restore a selected backup from the web UI after explicit confirmation.
- Run preflight checks before backup and restore.
- Show running backup/restore tasks as terminal-like live log output in the web UI.
- Keep a manifest next to every backup for restore checks and migration review.

## Backup content

The default backup source is `/`.

Default excludes:

- `/proc`
- `/sys`
- `/dev`
- `/run`
- `/tmp`
- `/lost+found`
- `/var/cache`
- The configured backup directory itself

The snapshot includes `/etc`, `/opt`, `/home`, `/var/lib`, mounted data paths
such as DietPi userdata, Docker volumes and bind mounts, systemd units, cron
jobs, scripts, LoxBerry configuration, and native application data. Add network
shares or very large media paths to `rsync_extra_excludes` if they should not be
part of disaster recovery.

## Important notes

For consistent Docker and database backups, stop affected containers or add
pre/post hooks before the backup. A live filesystem backup can otherwise contain
inconsistent database files.

For a true full restore, prefer a rescue/offline environment or a fresh target
installation where this plugin is installed first. Then run the restore from
the web UI or from the command line.

## Command line

After installation, the backend is available at:

```sh
/opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh
```

Examples:

```sh
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh backup
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh start
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh preflight-backup
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh list
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh export BACKUP_ID
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh import BACKUP_ID.tar.gz
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh browse BACKUP_ID opt/loxberry
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh cat-file BACKUP_ID etc/hosts
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh move BACKUP_ID /mnt/backupdisk
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh restore-plan BACKUP_ID
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh preflight-restore BACKUP_ID
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh restore BACKUP_ID
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh start-restore BACKUP_ID
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh tasks
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh task-log backup-BACKUP_ID.log
sudo /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh task-status backup-BACKUP_ID.log
```

Restore is intentionally guarded and requires `ALLOW_RESTORE=1`:

```sh
sudo ALLOW_RESTORE=1 /opt/loxberry/bin/plugins/loxberryhostbackup/hostbackup.sh restore BACKUP_ID
```
