# Changelog

## 0.1.0

- Initial prototype for full host backups.
- Added rsync-based backup and restore backend.
- Added backup manifest, package inventory, service inventory, mount inventory, and Docker inventory.
- Added web UI for listing, starting, importing, exporting, downloading, deleting, and restore planning.
- Added backup snapshot explorer with individual file downloads.
- Added controlled move action for full backup sets.
- Added selected-backup restore workflow in the web UI.
- Added backup and restore preflight checks.
- Added terminal-like live task log view for running backup and restore jobs.
- Added web UI settings for backup target, excludes, Docker handling, exports, retention, and hooks.
- Added daily, weekly, and monthly cron scheduling with retention-based pruning.
