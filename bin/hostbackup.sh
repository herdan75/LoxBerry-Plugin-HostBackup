#!/bin/bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

PLUGIN_NAME="loxberryhostbackup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_FOLDER="$(basename "$SCRIPT_DIR")"
if [[ "$SCRIPT_DIR" == */bin/plugins/* ]]; then
  DETECTED_LBHOMEDIR="${SCRIPT_DIR%/bin/plugins/$PLUGIN_FOLDER}"
else
  DETECTED_LBHOMEDIR="/opt/loxberry"
  PLUGIN_FOLDER="${HOSTBACKUP_PLUGIN_FOLDER:-$PLUGIN_NAME}"
fi
LBHOMEDIR="${LBHOMEDIR:-$DETECTED_LBHOMEDIR}"
LBP_BINDIR="${LBPBINDIR:-$SCRIPT_DIR}"
if [[ "$SCRIPT_DIR" == /usr/libexec/loxberryhostbackup/releases/* ]]; then
  LBP_BINDIR="$SCRIPT_DIR"
fi
LBP_CONFIGDIR="${LBPCONFIGDIR:-${LBPCONFIG:-$LBHOMEDIR/config/plugins}/$PLUGIN_FOLDER}"
LBP_DATADIR="${LBPDATADIR:-${LBPDATA:-$LBHOMEDIR/data/plugins}/$PLUGIN_FOLDER}"
LBP_LOGDIR="${LBPLOGDIR:-${LBPLOG:-$LBHOMEDIR/log/plugins}/$PLUGIN_FOLDER}"
CONFIG_FILE="$LBP_CONFIGDIR/config.json"
OPERATION_LOCK_FILE="${HOSTBACKUP_OPERATION_LOCK_FILE:-/var/lock/${PLUGIN_FOLDER}.operation.lock}"
if [ "$LBHOMEDIR" = "/opt/loxberry" ]; then
  ROOT_STATE_DIR="/var/lib/$PLUGIN_FOLDER"
else
  ROOT_STATE_DIR="$LBP_DATADIR/root-state"
fi
LOCK_DIR="$ROOT_STATE_DIR/locks"
TASK_DIR="$ROOT_STATE_DIR/tasks"
TASK_LOG_DIR="$ROOT_STATE_DIR/logs"
RESTART_JOURNAL_DIR="$ROOT_STATE_DIR/restart-journals"
ROOT_IMPORT_DIR="$ROOT_STATE_DIR/imports"
QUARANTINE_DIR="$ROOT_STATE_DIR/import-quarantine"
TARGET_MARKER_NAME=".loxberry-hostbackup-target"
BACKUP_MARKER_NAME=".loxberry-hostbackup-backup"
DEFAULT_IMPORT_MAX_MB=65536

for runtime_dir in "$LBP_CONFIGDIR" "$LBP_DATADIR" "$LBP_LOGDIR"; do
  [ ! -L "$runtime_dir" ] || { echo "Unsafe symlink runtime directory: $runtime_dir" >&2; exit 13; }
  mkdir -p -- "$runtime_dir"
done
[ ! -L "$ROOT_STATE_DIR" ] && [ ! -L "$LOCK_DIR" ] && [ ! -L "$TASK_DIR" ] && [ ! -L "$TASK_LOG_DIR" ] && [ ! -L "$ROOT_IMPORT_DIR" ] && [ ! -L "$QUARANTINE_DIR" ] && [ ! -L "$RESTART_JOURNAL_DIR" ] || { echo "Unsafe root state directory symlink." >&2; exit 13; }
mkdir -p -- "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR" "$RESTART_JOURNAL_DIR"
[ -d "$ROOT_STATE_DIR" ] && [ ! -L "$ROOT_STATE_DIR" ] || { echo "Root state directory is unsafe." >&2; exit 13; }
chmod 700 "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR" "$RESTART_JOURNAL_DIR" 2>/dev/null || true

if [ "$(id -u)" -eq 0 ]; then
  for secure_dir in "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$TASK_LOG_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR" "$RESTART_JOURNAL_DIR"; do
    secure_owner="$(stat -c '%u' "$secure_dir" 2>/dev/null || echo -1)"
    secure_mode="$(stat -c '%a' "$secure_dir" 2>/dev/null || echo '')"
    [ "$secure_owner" = "0" ] && [ -n "$secure_mode" ] && (( (8#$secure_mode & 022) == 0 )) || {
      echo "Secure runtime directory must be root-owned and not writable by group or others: $secure_dir" >&2
      exit 13
    }
  done
fi

[ ! -L "$CONFIG_FILE" ] || { echo "Unsafe symlink configuration file: $CONFIG_FILE" >&2; exit 13; }
if [ ! -f "$CONFIG_FILE" ]; then
  cat > "$CONFIG_FILE" <<'JSON'
{
  "backup_root": "",
  "backup_mode": "full",
  "metadata_mode": "native-strict",
  "rsync_extra_excludes": [],
  "source_selection": {"policy": "local", "overrides": {}},
  "stop_docker_before_backup": false,
  "stop_targets": [],
  "create_export_after_backup": false,
  "mail_notify_enabled": false,
  "mail_notify_to": "",
  "mail_notify_success": true,
  "mail_notify_failure": true,
  "mail_notify_stopped": true,
  "mail_notify_restore": true,
  "keep_backups": 10,
  "schedule_enabled": false,
  "schedule_mode": "daily",
  "schedule_time": "02:00",
  "schedule_weekday": "0",
  "schedule_weekdays": ["0"],
  "schedule_monthday": "1",
  "schedule_monthdays": ["1"],
  "schedule_months": ["*"],
  "root_permission_ack": false,
  "pre_backup_hook": "",
  "post_backup_hook": ""
}
JSON
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
fi

if [ "$(id -u)" -eq 0 ]; then
  config_owner="$(stat -c '%u' "$CONFIG_FILE" 2>/dev/null || echo -1)"
  config_mode="$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || echo '')"
  config_dir_owner="$(stat -c '%u' "$LBP_CONFIGDIR" 2>/dev/null || echo -1)"
  config_dir_mode="$(stat -c '%a' "$LBP_CONFIGDIR" 2>/dev/null || echo '')"
  [ "$config_owner" = "0" ] && [ -n "$config_mode" ] && (( (8#$config_mode & 022) == 0 )) || {
    echo "Configuration must be root-owned and not writable by group or others." >&2
    exit 13
  }
  [ "$config_dir_owner" = "0" ] && [ -n "$config_dir_mode" ] && (( (8#$config_dir_mode & 022) == 0 )) || {
    echo "Configuration directory must be root-owned and not writable by group or others." >&2
    exit 13
  }
fi

json_get_string() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or die "Cannot read config: $!\n";
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) };
    die "Invalid config JSON: $@\n" if $@ || ref($cfg) ne "HASH";
    my $value = $cfg->{$key};
    print $value if defined $value && !ref($value);
  ' "$CONFIG_FILE" "$key"
}

json_get_bool() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or die "Cannot read config: $!\n";
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) };
    die "Invalid config JSON: $@\n" if $@ || ref($cfg) ne "HASH";
    print(($cfg->{$key} ? "true" : "false"));
  ' "$CONFIG_FILE" "$key"
}

json_get_number() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or die "Cannot read config: $!\n";
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) };
    die "Invalid config JSON: $@\n" if $@ || ref($cfg) ne "HASH";
    my $value = $cfg->{$key};
    print $value if defined $value && $value =~ /^\d+$/;
  ' "$CONFIG_FILE" "$key"
}

json_get_array_lines() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or die "Cannot read config: $!\n";
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) };
    die "Invalid config JSON: $@\n" if $@ || ref($cfg) ne "HASH";
    my $arr = $cfg->{$key};
    exit 0 unless ref($arr) eq "ARRAY";
    for my $item (@$arr) {
      next if ref($item);
      print "$item\n" if length($item);
    }
  ' "$CONFIG_FILE" "$key"
}

show_config() {
  perl -MJSON::PP -e '
    my ($file) = @ARGV;
    open my $fh, "<", $file or die "Cannot read config: $!";
    local $/;
    my $cfg = eval { decode_json(<$fh>) };
    die "Invalid config JSON: $@\n" if $@ || ref($cfg) ne "HASH";
    $cfg->{backup_root} //= "";
    $cfg->{backup_mode} = "full" unless ($cfg->{backup_mode} || "") =~ /^(full|snapshot)$/;
    $cfg->{metadata_mode} = "native-strict" unless ($cfg->{metadata_mode} || "") =~ /^(native-strict|network-compatible|fake-super|portable-archive)$/;
    $cfg->{rsync_extra_excludes} = [] unless ref($cfg->{rsync_extra_excludes}) eq "ARRAY";
    # Existing installations keep their previous scope until explicitly changed.
    $cfg->{source_selection} //= { policy => "legacy", overrides => {} };
    $cfg->{stop_docker_before_backup} = $cfg->{stop_docker_before_backup} ? JSON::PP::true : JSON::PP::false;
    $cfg->{stop_targets} = [] unless ref($cfg->{stop_targets}) eq "ARRAY";
    $cfg->{create_export_after_backup} = $cfg->{create_export_after_backup} ? JSON::PP::true : JSON::PP::false;
    $cfg->{mail_notify_enabled} = $cfg->{mail_notify_enabled} ? JSON::PP::true : JSON::PP::false;
    $cfg->{mail_notify_to} //= "";
    $cfg->{mail_notify_success} = exists $cfg->{mail_notify_success} ? ($cfg->{mail_notify_success} ? JSON::PP::true : JSON::PP::false) : JSON::PP::true;
    $cfg->{mail_notify_failure} = exists $cfg->{mail_notify_failure} ? ($cfg->{mail_notify_failure} ? JSON::PP::true : JSON::PP::false) : JSON::PP::true;
    $cfg->{mail_notify_stopped} = exists $cfg->{mail_notify_stopped} ? ($cfg->{mail_notify_stopped} ? JSON::PP::true : JSON::PP::false) : JSON::PP::true;
    $cfg->{mail_notify_restore} = exists $cfg->{mail_notify_restore} ? ($cfg->{mail_notify_restore} ? JSON::PP::true : JSON::PP::false) : JSON::PP::true;
    $cfg->{keep_backups} = ($cfg->{keep_backups} && $cfg->{keep_backups} =~ /^\d+$/) ? 0 + $cfg->{keep_backups} : 10;
    $cfg->{keep_backups} = 1 if $cfg->{keep_backups} < 1;
    $cfg->{keep_backups} = 3650 if $cfg->{keep_backups} > 3650;
    $cfg->{schedule_enabled} = $cfg->{schedule_enabled} ? JSON::PP::true : JSON::PP::false;
    $cfg->{schedule_mode} = $cfg->{schedule_mode} || "daily";
    $cfg->{schedule_time} = $cfg->{schedule_time} || "02:00";
    $cfg->{schedule_weekday} = defined $cfg->{schedule_weekday} ? "$cfg->{schedule_weekday}" : "0";
    if (ref($cfg->{schedule_weekdays}) ne "ARRAY" || !@{$cfg->{schedule_weekdays}}) {
      $cfg->{schedule_weekdays} = [ $cfg->{schedule_weekday} ];
    }
    $cfg->{schedule_monthday} = defined $cfg->{schedule_monthday} ? "$cfg->{schedule_monthday}" : "1";
    if (ref($cfg->{schedule_monthdays}) ne "ARRAY" || !@{$cfg->{schedule_monthdays}}) {
      $cfg->{schedule_monthdays} = [ $cfg->{schedule_monthday} ];
    }
    $cfg->{schedule_months} = ["*"] unless ref($cfg->{schedule_months}) eq "ARRAY" && @{$cfg->{schedule_months}};
    $cfg->{root_permission_ack} = $cfg->{root_permission_ack} ? JSON::PP::true : JSON::PP::false;
    $cfg->{pre_backup_hook} //= "";
    $cfg->{post_backup_hook} //= "";
    $cfg->{target_marker} //= "";
    $cfg->{target_mountpoint} //= "";
    $cfg->{target_source} //= "";
    $cfg->{target_fstype} //= "";
    $cfg->{target_majmin} //= "";
    $cfg->{import_max_size_mb} = ($cfg->{import_max_size_mb} && $cfg->{import_max_size_mb} =~ /^\d+$/) ? 0 + $cfg->{import_max_size_mb} : 65536;
    $cfg->{retention_mode} = "count" unless ($cfg->{retention_mode} || "") =~ /^(count|gfs)$/;
    my %maintenance_defaults = (keep_daily=>7, keep_weekly=>4, keep_monthly=>6, log_retention_days=>30, quarantine_retention_days=>7, integrity_interval_days=>7);
    for my $key (keys %maintenance_defaults) { $cfg->{$key} = $maintenance_defaults{$key} unless defined $cfg->{$key}; }
    $cfg->{integrity_enabled} = $cfg->{integrity_enabled} ? JSON::PP::true : JSON::PP::false;
    print JSON::PP->new->ascii->pretty->canonical->encode($cfg);
  ' "$CONFIG_FILE"
}

canonicalize_path() {
  local value="$1"
  [ -n "$value" ] && [ "${value#/}" != "$value" ] || return 1
  realpath -m -- "$value"
}

path_has_symlink_component() {
  perl -e '
    my ($path) = @ARGV;
    my $current = "";
    for my $part (grep { length } split m{/+}, $path) {
      $current .= "/$part";
      exit 0 if -l $current;
      last unless -e $current;
    }
    exit 1;
  ' "$1"
}

nearest_existing_path() {
  local probe="$1"
  while [ ! -e "$probe" ] && [ "$probe" != "/" ]; do
    probe="$(dirname -- "$probe")"
  done
  [ -e "$probe" ] || probe="/"
  printf '%s\n' "$probe"
}

new_marker_token() {
  if [ -r /proc/sys/kernel/random/uuid ]; then
    tr -d '\r\n' < /proc/sys/kernel/random/uuid
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    printf '%s-%s-%s\n' "$(date +%s%N)" "$$" "$RANDOM"
  fi
}

REGISTERED_ROOT=""
REGISTERED_MARKER=""
REGISTERED_MOUNTPOINT=""
REGISTERED_SOURCE=""
REGISTERED_FSTYPE=""
REGISTERED_MAJMIN=""

prepare_target_registration() {
  local configured="$1"
  local root probe marker_file tmp_marker
  if [ -n "$configured" ]; then
    root="$(canonicalize_path "$configured")" || { echo "Backup-Ziel muss ein absoluter Pfad sein." >&2; return 1; }
  else
    root="$(canonicalize_path "$LBP_DATADIR/backups")"
  fi
  require_allowed_backup_root "$root"
  if path_has_symlink_component "$root"; then
    echo "Backup-Ziel darf keine symbolischen Pfadkomponenten enthalten: $root" >&2
    return 1
  fi

  probe="$(nearest_existing_path "$root")"
  REGISTERED_MOUNTPOINT="$(findmnt -rn -T "$probe" -o TARGET 2>/dev/null | sed -n '1p')"
  REGISTERED_SOURCE="$(findmnt -rn -T "$probe" -o SOURCE 2>/dev/null | sed -n '1p')"
  REGISTERED_FSTYPE="$(findmnt -rn -T "$probe" -o FSTYPE 2>/dev/null | sed -n '1p')"
  REGISTERED_MAJMIN="$(findmnt -rn -T "$probe" -o MAJ:MIN 2>/dev/null | sed -n '1p')"
  [ -n "$REGISTERED_MOUNTPOINT" ] && [ -n "$REGISTERED_SOURCE" ] && [ -n "$REGISTERED_FSTYPE" ] || {
    echo "Mount-Identitaet des Backup-Ziels konnte nicht bestimmt werden." >&2
    return 1
  }
  case "$REGISTERED_FSTYPE" in
    cifs|smb3|nfs|nfs4|fuse.sshfs|sshfs|curlftpfs|fuse|fuseblk) REGISTERED_MAJMIN="" ;;
  esac

  if [ -n "$configured" ] && [ "$REGISTERED_MOUNTPOINT" = "/" ] && [ "${HOSTBACKUP_ALLOW_ROOTFS_TARGET:-0}" != "1" ]; then
    echo "Ein benutzerdefiniertes Backup-Ziel auf dem Root-Dateisystem ist gesperrt. Bitte separates Mount verwenden." >&2
    return 1
  fi

  mkdir -p -- "$root"
  [ -d "$root" ] && [ ! -L "$root" ] || { echo "Backup-Ziel ist kein sicheres Verzeichnis." >&2; return 1; }
  marker_file="$root/$TARGET_MARKER_NAME"
  if [ -r "$marker_file" ] && [ ! -L "$marker_file" ]; then
    REGISTERED_MARKER="$(tr -d '\r\n' < "$marker_file")"
  fi
  if [ -z "$REGISTERED_MARKER" ]; then
    REGISTERED_MARKER="$(new_marker_token)"
    tmp_marker="$root/.$TARGET_MARKER_NAME.$$"
    ( umask 077; printf '%s\n' "$REGISTERED_MARKER" > "$tmp_marker" )
    chmod 600 "$tmp_marker" 2>/dev/null || true
    mv -fT -- "$tmp_marker" "$marker_file"
  fi
  REGISTERED_ROOT="$root"
}

save_config() {
  require_root_for_write
  acquire_operation_lock exclusive
  show_config >/dev/null || { echo "Existing configuration is invalid; refusing to overwrite it automatically." >&2; return 12; }
  local backup_root="$1"
  local excludes_text="$2"
  local stop_docker="$3"
  local create_export="$4"
  local keep_backups="$5"
  local schedule_enabled="$6"
  local schedule_mode="$7"
  local schedule_time="$8"
  local schedule_weekday="$9"
  local schedule_monthday="${10}"
  local schedule_months="${11-*}"
  local schedule_weekdays="${12-$schedule_weekday}"
  local schedule_monthdays="${13-$schedule_monthday}"
  local pre_hook="${14}"
  local post_hook="${15}"
  local root_permission_ack="${16:-false}"
  local backup_mode="${17:-full}"
  local stop_targets="${18:-}"
  local mail_notify_enabled="${19:-false}"
  local mail_notify_to="${20:-}"
  local mail_notify_success="${21:-true}"
  local mail_notify_failure="${22:-true}"
  local mail_notify_stopped="${23:-true}"
  local mail_notify_restore="${24:-true}"
  local metadata_mode="${25:-native-strict}"
  local source_selection="${26:-}"

  python3 "$LBP_BINDIR/hostbackup-overview.py" check-settings "$backup_mode" "$metadata_mode" "$schedule_enabled" \
    "$schedule_mode" "$schedule_time" "$schedule_weekdays" "$schedule_monthdays" "$schedule_months"
  if [ -n "$source_selection" ]; then
    source_selection="$(python3 "$LBP_BINDIR/hostbackup-sources.py" validate --selection "$source_selection")" || return 18
  fi
  prepare_target_registration "$backup_root"
  [ -n "$backup_root" ] && backup_root="$REGISTERED_ROOT"

  [ ! -L "$CONFIG_FILE.lock" ] || { echo "Unsafe configuration lock symlink." >&2; return 13; }
  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MFcntl=:DEFAULT,:flock -MIO::Handle -e '
    my ($file, $backup_root, $excludes_text, $stop_docker, $create_export, $keep_backups, $schedule_enabled, $schedule_mode, $schedule_time, $schedule_weekday, $schedule_monthday, $schedule_months, $schedule_weekdays, $schedule_monthdays, $pre_hook, $post_hook, $root_permission_ack, $backup_mode, $stop_targets_text, $mail_notify_enabled, $mail_notify_to, $mail_notify_success, $mail_notify_failure, $mail_notify_stopped, $mail_notify_restore, $metadata_mode, $target_marker, $target_mountpoint, $target_source, $target_fstype, $target_majmin, $source_selection) = @ARGV;
    my @excludes;
    for my $line (split /\r?\n/, $excludes_text) {
      $line =~ s/^\s+|\s+$//g;
      next if $line eq "" || $line =~ /^#/;
      push @excludes, $line;
    }
    if ($backup_root ne "" && $backup_root !~ m{^/}) {
      die "Backup-Ziel muss leer oder ein absoluter Pfad sein.\n";
    }
    if ($backup_root eq "/" || $backup_root =~ m{^/(proc|sys|dev|run|tmp)(/|$)}) {
      die "Backup-Ziel darf nicht /, /proc, /sys, /dev, /run oder /tmp sein.\n";
    }
    if ($pre_hook ne "" && $pre_hook !~ m{^/}) {
      die "Pre-Backup-Hook muss leer oder ein absoluter Pfad sein.\n";
    }
    if ($post_hook ne "" && $post_hook !~ m{^/}) {
      die "Post-Backup-Hook muss leer oder ein absoluter Pfad sein.\n";
    }
    $mail_notify_to =~ s/^\s+|\s+$//g;
    if ($mail_notify_to ne "" && $mail_notify_to !~ /^[^\s\@]+@[^\s\@]+\.[^\s\@]+$/) {
      die "Mailadresse muss leer oder eine gueltige E-Mail-Adresse sein.\n";
    }
    $keep_backups = ($keep_backups =~ /^\d+$/) ? 0 + $keep_backups : 10;
    $keep_backups = 1 if $keep_backups < 1;
    $keep_backups = 3650 if $keep_backups > 3650;
    $backup_mode = "full" unless $backup_mode =~ /^(full|snapshot)$/;
    $schedule_mode = "daily" unless $schedule_mode =~ /^(daily|weekly|monthly)$/;
    $schedule_time = "02:00" unless $schedule_time =~ /^([01]\d|2[0-3]):[0-5]\d$/;
    $schedule_weekday = "0" unless $schedule_weekday =~ /^[0-6]$/;
    $schedule_monthday = "1" unless $schedule_monthday =~ /^([1-9]|[12]\d|3[01])$/;
    my %seen_weekday;
    my @weekdays;
    for my $weekday (split /,/, $schedule_weekdays) {
      $weekday =~ s/^\s+|\s+$//g;
      next unless $weekday =~ /^[0-6]$/;
      next if $seen_weekday{$weekday}++;
      push @weekdays, $weekday;
    }
    @weekdays = ($schedule_weekday) unless @weekdays;
    my %seen_monthday;
    my @monthdays;
    for my $day (split /,/, $schedule_monthdays) {
      $day =~ s/^\s+|\s+$//g;
      next unless $day =~ /^([1-9]|[12]\d|3[01])$/;
      next if $seen_monthday{$day}++;
      push @monthdays, $day;
    }
    @monthdays = ($schedule_monthday) unless @monthdays;
    my %seen;
    my @months;
    for my $month (split /,/, $schedule_months) {
      $month =~ s/^\s+|\s+$//g;
      if ($month eq "*") {
        @months = ("*");
        last;
      }
      next unless $month =~ /^([1-9]|1[0-2])$/;
      next if $seen{$month}++;
      push @months, $month;
    }
    @months = ("*") unless @months;
    my %seen_target;
    my @stop_targets;
    for my $entry (split /,/, ($stop_targets_text // "")) {
      $entry =~ s/^\s+|\s+$//g;
      next unless length $entry;
      my ($type, $name) = split /:/, $entry, 2;
      next unless defined $name && length $name;
      next unless $type =~ /^(docker|systemd)$/;
      next if $type eq "docker" && $name !~ /^[A-Za-z0-9_.-]+$/;
      next if $type eq "systemd" && $name !~ /^[A-Za-z0-9_.\@:\\-]+\.service$/;
      my $key = "$type:$name";
      next if $seen_target{$key}++;
      push @stop_targets, { type => $type, name => $name };
    }
    my $cfg = {
      backup_root => $backup_root,
      backup_mode => $backup_mode,
      metadata_mode => $metadata_mode,
      rsync_extra_excludes => \@excludes,
      stop_docker_before_backup => ($stop_docker eq "true" ? JSON::PP::true : JSON::PP::false),
      stop_targets => \@stop_targets,
      create_export_after_backup => ($create_export eq "true" ? JSON::PP::true : JSON::PP::false),
      mail_notify_enabled => ($mail_notify_enabled eq "true" ? JSON::PP::true : JSON::PP::false),
      mail_notify_to => $mail_notify_to,
      mail_notify_success => ($mail_notify_success eq "true" ? JSON::PP::true : JSON::PP::false),
      mail_notify_failure => ($mail_notify_failure eq "true" ? JSON::PP::true : JSON::PP::false),
      mail_notify_stopped => ($mail_notify_stopped eq "true" ? JSON::PP::true : JSON::PP::false),
      mail_notify_restore => ($mail_notify_restore eq "true" ? JSON::PP::true : JSON::PP::false),
      keep_backups => $keep_backups,
      schedule_enabled => ($schedule_enabled eq "true" ? JSON::PP::true : JSON::PP::false),
      schedule_mode => $schedule_mode,
      schedule_time => $schedule_time,
      schedule_weekday => $schedule_weekday,
      schedule_weekdays => \@weekdays,
      schedule_monthday => $schedule_monthday,
      schedule_monthdays => \@monthdays,
      schedule_months => \@months,
      root_permission_ack => ($root_permission_ack eq "true" ? JSON::PP::true : JSON::PP::false),
      pre_backup_hook => $pre_hook,
      post_backup_hook => $post_hook,
      target_marker => $target_marker,
      target_mountpoint => $target_mountpoint,
      target_source => $target_source,
      target_fstype => $target_fstype,
      target_majmin => $target_majmin,
      import_max_size_mb => 65536,
    };
    die "Refusing symlink config\n" if -l $file;
    sysopen(my $lock, "$file.lock", O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW, 0600) or die "Cannot lock config: $!";
    flock($lock, LOCK_EX) or die "Cannot lock config: $!";
    # Saving the main form must not reset separately configured maintenance options.
    sysopen(my $existing, $file, O_RDONLY | O_NOFOLLOW) or die "Cannot read existing config: $!";
    local $/;
    my $old = decode_json(<$existing>);
    close $existing;
    $cfg->{source_selection} = length($source_selection) ? decode_json($source_selection)
      : ($old->{source_selection} // { policy => "legacy", overrides => {} });
    for my $key (qw(retention_mode keep_daily keep_weekly keep_monthly log_retention_days quarantine_retention_days integrity_enabled integrity_interval_days)) {
      $cfg->{$key} = $old->{$key} if exists $old->{$key};
    }
    my ($fh, $tmp) = tempfile(".config-XXXXXX", DIR => dirname($file), UNLINK => 0);
    chmod 0600, $tmp or die "Cannot chmod config temp: $!";
    print $fh JSON::PP->new->ascii->pretty->canonical->encode($cfg) or die "Cannot write config: $!";
    $fh->flush or die "Cannot flush config: $!";
    $fh->sync or die "Cannot sync config: $!";
    close $fh or die "Cannot close config: $!";
    rename $tmp, $file or die "Cannot replace config: $!";
  ' "$CONFIG_FILE" "$backup_root" "$excludes_text" "$stop_docker" "$create_export" "$keep_backups" "$schedule_enabled" "$schedule_mode" "$schedule_time" "$schedule_weekday" "$schedule_monthday" "$schedule_months" "$schedule_weekdays" "$schedule_monthdays" "$pre_hook" "$post_hook" "$root_permission_ack" "$backup_mode" "$stop_targets" "$mail_notify_enabled" "$mail_notify_to" "$mail_notify_success" "$mail_notify_failure" "$mail_notify_stopped" "$mail_notify_restore" "$metadata_mode" "$REGISTERED_MARKER" "$REGISTERED_MOUNTPOINT" "$REGISTERED_SOURCE" "$REGISTERED_FSTYPE" "$REGISTERED_MAJMIN" "$source_selection"
  install_schedule
}

json_escape() {
  perl -MJSON::PP -e 'print encode_json($ARGV[0] // "")' "$1"
}

backup_root() {
  local configured
  configured="$(json_get_string backup_root)"
  if [ -n "$configured" ]; then
    canonicalize_path "$configured"
  else
    canonicalize_path "$LBP_DATADIR/backups"
  fi
}

require_allowed_backup_root() {
  local supplied="$1" root depth
  root="$(canonicalize_path "$supplied")" || { echo "Backup target must be absolute." >&2; return 14; }
  depth="$(printf '%s' "$root" | awk -F/ '{print NF-1}')"
  case "$root" in
    /|/bin|/boot|/etc|/home|/lib|/lib32|/lib64|/opt|/proc|/root|/run|/sbin|/sys|/tmp|/usr|/var|/dev|/proc/*|/sys/*|/dev/*|/run/*|/tmp/*)
      echo "Backup target resolves to a protected system path: $root" >&2
      return 14
      ;;
  esac
  [ "$depth" -ge 2 ] || { echo "Backup target is too broad: $root" >&2; return 14; }
  [ "$root" = "$supplied" ] || { echo "Backup target must be canonical (resolved: $root)." >&2; return 14; }
  if path_has_symlink_component "$root"; then
    echo "Backup target contains a symbolic path component: $root" >&2
    return 14
  fi
}

current_mount_value() {
  local root="$1" column="$2"
  findmnt -rn -T "$root" -o "$column" 2>/dev/null | sed -n '1p'
}

migrate_target_registration() {
  local root="$1" configured
  [ "$(id -u)" -eq 0 ] || return 1
  acquire_operation_lock exclusive
  configured="$(json_get_string backup_root)"
  prepare_target_registration "$configured"
  [ "$REGISTERED_ROOT" = "$root" ] || return 1
  [ ! -L "$CONFIG_FILE.lock" ] || { echo "Unsafe configuration lock symlink." >&2; return 13; }
  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MFcntl=:DEFAULT,:flock -MIO::Handle -e '
    my ($file, $marker, $mountpoint, $source, $fstype, $majmin) = @ARGV;
    sysopen(my $lock, "$file.lock", O_WRONLY | O_APPEND | O_CREAT | O_NOFOLLOW, 0600) or die $!;
    flock($lock, LOCK_EX) or die $!;
    open my $in, "<", $file or die $!;
    local $/;
    my $cfg = decode_json(<$in>);
    close $in;
    $cfg->{metadata_mode} ||= "native-strict";
    $cfg->{target_marker} = $marker;
    $cfg->{target_mountpoint} = $mountpoint;
    $cfg->{target_source} = $source;
    $cfg->{target_fstype} = $fstype;
    $cfg->{target_majmin} = $majmin;
    $cfg->{import_max_size_mb} ||= 65536;
    my ($out, $tmp) = tempfile(".config-migrate-XXXXXX", DIR => dirname($file), UNLINK => 0);
    chmod 0600, $tmp;
    print $out JSON::PP->new->ascii->pretty->canonical->encode($cfg) or die $!;
    $out->flush or die $!;
    $out->sync or die $!;
    close $out or die $!;
    rename $tmp, $file or die $!;
  ' "$CONFIG_FILE" "$REGISTERED_MARKER" "$REGISTERED_MOUNTPOINT" "$REGISTERED_SOURCE" "$REGISTERED_FSTYPE" "$REGISTERED_MAJMIN"
}

verify_backup_target() {
  local root="$1" require_write="${2:-false}"
  local expected_marker expected_mountpoint expected_source expected_fstype expected_majmin actual marker_file
  require_allowed_backup_root "$root"
  [ -d "$root" ] && [ ! -L "$root" ] || { echo "Backup target is missing or unsafe: $root" >&2; return 14; }
  expected_marker="$(json_get_string target_marker)"
  expected_mountpoint="$(json_get_string target_mountpoint)"
  expected_source="$(json_get_string target_source)"
  expected_fstype="$(json_get_string target_fstype)"
  expected_majmin="$(json_get_string target_majmin)"
  if [ -z "$expected_marker" ]; then
    migrate_target_registration "$root" || { echo "Backup target is not registered. Save settings again." >&2; return 14; }
    expected_marker="$(json_get_string target_marker)"
    expected_mountpoint="$(json_get_string target_mountpoint)"
    expected_source="$(json_get_string target_source)"
    expected_fstype="$(json_get_string target_fstype)"
    expected_majmin="$(json_get_string target_majmin)"
  fi
  marker_file="$root/$TARGET_MARKER_NAME"
  [ -f "$marker_file" ] && [ ! -L "$marker_file" ] || { echo "Backup target marker is missing." >&2; return 14; }
  actual="$(tr -d '\r\n' < "$marker_file")"
  [ "$actual" = "$expected_marker" ] || { echo "Backup target marker does not match the registered target." >&2; return 14; }
  actual="$(current_mount_value "$root" TARGET)"
  [ -n "$expected_mountpoint" ] && [ "$actual" = "$expected_mountpoint" ] || { echo "Backup target mountpoint changed or is not mounted." >&2; return 14; }
  actual="$(current_mount_value "$root" SOURCE)"
  [ -n "$expected_source" ] && [ "$actual" = "$expected_source" ] || { echo "Backup target source changed or is not mounted." >&2; return 14; }
  actual="$(current_mount_value "$root" FSTYPE)"
  [ -n "$expected_fstype" ] && [ "$actual" = "$expected_fstype" ] || { echo "Backup target filesystem changed." >&2; return 14; }
  if [ -n "$expected_majmin" ]; then
    actual="$(current_mount_value "$root" 'MAJ:MIN')"
    [ "$actual" = "$expected_majmin" ] || { echo "Backup target device identity changed." >&2; return 14; }
  fi
  if [ "$require_write" = "true" ]; then
    [ -w "$root" ] || { echo "Backup target is not writable." >&2; return 14; }
  fi
}

strict_child_path() {
  local root="$1" child="$2" canonical_root canonical_child
  canonical_root="$(canonicalize_path "$root")" || return 1
  canonical_child="$(canonicalize_path "$child")" || return 1
  case "$canonical_child" in
    "$canonical_root"/*) printf '%s\n' "$canonical_child" ;;
    *) return 1 ;;
  esac
}

backup_marker_matches() {
  local target="$1" backup_id="$2"
  local marker="$target/$BACKUP_MARKER_NAME"
  [ -f "$marker" ] && [ ! -L "$marker" ] || return 1
  [ "$(tr -d '\r\n' < "$marker")" = "$backup_id" ]
}

write_backup_marker() {
  local target="$1" backup_id="$2"
  local tmp="$target/.$BACKUP_MARKER_NAME.$$"
  ( umask 077; printf '%s\n' "$backup_id" > "$tmp" )
  chown root:root "$tmp" 2>/dev/null || true
  chmod 600 "$tmp" 2>/dev/null || true
  mv -fT -- "$tmp" "$target/$BACKUP_MARKER_NAME"
}

write_control_marker() {
  local path="$1" parent tmp
  parent="$(dirname -- "$path")"
  [ -d "$parent" ] && [ ! -L "$parent" ] || { echo "Unsafe control marker directory: $parent" >&2; return 13; }
  tmp="$parent/.$(basename -- "$path").$$"
  ( umask 077; : > "$tmp" )
  chown root:root "$tmp" 2>/dev/null || true
  chmod 0600 "$tmp" 2>/dev/null || true
  mv -fT -- "$tmp" "$path"
}

manifest_field() {
  local manifest="$1" field="$2"
  [ -f "$manifest" ] && [ ! -L "$manifest" ] && [ -r "$manifest" ] || return 1
  perl -MJSON::PP -e '
    my ($file, $field) = @ARGV;
    open my $fh, "<", $file or exit 1;
    local $/;
    my $data = eval { decode_json(<$fh>) };
    exit 1 if $@ || ref($data) ne "HASH";
    my $value = $data;
    for my $part (split /\./, $field) {
      exit 1 unless ref($value) eq "HASH" && exists $value->{$part};
      $value = $value->{$part};
    }
    exit 1 if ref($value);
    print $value;
  ' "$manifest" "$field"
}

safe_backup_target() {
  local root="$1" backup_id="$2" target expected_id
  require_backup_id "$backup_id"
  target="$(strict_child_path "$root" "$root/$backup_id")" || { echo "Refusing unsafe backup path." >&2; return 7; }
  [ -d "$target" ] && [ ! -L "$target" ] || { echo "Backup not found: $backup_id" >&2; return 6; }
  expected_id="$(manifest_field "$target/manifest.json" backup_id 2>/dev/null || true)"
  [ "$expected_id" = "$backup_id" ] || { echo "Backup manifest identity mismatch: $backup_id" >&2; return 7; }
  if ! backup_marker_matches "$target" "$backup_id"; then
    [ "$(id -u)" -eq 0 ] || { echo "Backup marker mismatch: $backup_id" >&2; return 7; }
    write_backup_marker "$target" "$backup_id"
  fi
  printf '%s\n' "$target"
}

acquire_operation_lock() {
  local mode="${1:-exclusive}" busy_notice="${2:-report}" lock_status=0 lock_mode=-x
  [ "${HOSTBACKUP_OPERATION_LOCK_HELD:-0}" = "1" ] && return 0
  [ ! -L "$OPERATION_LOCK_FILE" ] || { echo "Unsafe operation lock symlink." >&2; return 13; }
  exec 9>"$OPERATION_LOCK_FILE" || return $?
  [ "$mode" != "shared" ] || lock_mode=-s
  # Reserve 5 for contention only; util-linux uses sysexits codes for errors.
  flock -n -E 5 "$lock_mode" 9 || lock_status=$?
  if [ "$lock_status" -ne 0 ]; then
    exec 9>&-
    if [ "$lock_status" -eq 5 ] && [ "$busy_notice" != "quiet-busy" ]; then
      echo "Another HostBackup operation is active." >&2
    fi
    return "$lock_status"
  fi
  export HOSTBACKUP_OPERATION_LOCK_HELD=1
}

acquire_backup_lock() {
  local backup_id="$1" mode="${2:-exclusive}"
  [ "${HOSTBACKUP_BACKUP_LOCK_HELD:-}" = "$backup_id" ] && return 0
  require_backup_id "$backup_id"
  [ ! -L "$LOCK_DIR/$backup_id.lock" ] || { echo "Unsafe backup lock symlink: $backup_id" >&2; return 13; }
  exec 8>"$LOCK_DIR/$backup_id.lock"
  if [ "$mode" = "shared" ]; then
    flock -n -s 8 || { echo "Backup is busy: $backup_id" >&2; return 5; }
  else
    flock -n -x 8 || { echo "Backup is busy: $backup_id" >&2; return 5; }
  fi
  export HOSTBACKUP_BACKUP_LOCK_HELD="$backup_id"
}

mail_notify_enabled_for_event() {
  local event="$1"
  [ "$(json_get_bool mail_notify_enabled)" = "true" ] || return 1
  case "$event" in
    success) [ "$(json_get_bool mail_notify_success)" = "true" ] ;;
    failure) [ "$(json_get_bool mail_notify_failure)" = "true" ] ;;
    stopped) [ "$(json_get_bool mail_notify_stopped)" = "true" ] ;;
    restore) [ "$(json_get_bool mail_notify_restore)" = "true" ] ;;
    *) return 1 ;;
  esac
}

notify_hostbackup() {
  local event="$1"
  local severity="$2"
  local subject="$3"
  local message="$4"
  local logfile="${5:-}"
  local recipient helper notify_output
  mail_notify_enabled_for_event "$event" || return 0
  helper="$LBP_BINDIR/notify-hostbackup.php"
  command -v php >/dev/null 2>&1 || return 0
  [ -f "$helper" ] || return 0
  recipient="$(json_get_string mail_notify_to)"
  notify_output="$(php "$helper" "$event" "$severity" "$subject" "$message" "$logfile" "$recipient" 2>&1)" || {
    if [ -n "$logfile" ]; then
      printf '%s WARNING: Mail notification failed: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$notify_output" >> "$logfile"
    else
      printf 'WARNING: Mail notification failed: %s\n' "$notify_output" >&2
    fi
  }
}

backup_target_info() {
  local configured root probe fs_type source available_mb backup_mode status message linux_fs mode verify_message mountpoint majmin
  configured="$(json_get_string backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  mode="$(metadata_mode)"

  if [ -z "$configured" ]; then
    cat <<EOF
{
  "kind": "backup-target",
  "configured": false,
  "status": "info",
  "backup_root": "",
  "probe_path": "",
  "fs_type": "",
  "source": "",
  "mountpoint": "",
  "majmin": "",
  "available_mb": 0,
  "linux_filesystem": false,
  "backup_mode": $(json_escape "$backup_mode"),
  "metadata_mode": $(json_escape "$mode"),
  "message": "Noch kein Backup-Verzeichnis festgelegt. Bitte zuerst ein Backup-Ziel waehlen und die Einstellungen speichern."
}
EOF
    return 0
  fi

  root="$(backup_root)"
  probe="$root"
  fs_type="$(current_mount_value "$probe" FSTYPE)"
  source="$(current_mount_value "$probe" SOURCE)"
  mountpoint="$(current_mount_value "$probe" TARGET)"
  majmin="$(current_mount_value "$probe" 'MAJ:MIN')"
  available_mb="$(df -Pm "$probe" 2>/dev/null | awk 'NR==2 {print $4}')"
  [ -n "$fs_type" ] || fs_type="unknown"
  [ -n "$source" ] || source="unknown"
  [ -n "$available_mb" ] || available_mb=0

  linux_fs=false
  if printf '%s\n' "$fs_type" | grep -Eq '^(ext2|ext3|ext4|xfs|btrfs)$'; then
    linux_fs=true
  fi

  status="ok"
  message="Backup-Ziel ist registriert und die Mount-Identitaet stimmt. Metadaten-Modus: $mode."
  if ! verify_message="$(verify_backup_target "$root" false 2>&1)"; then
    status="error"
    message="$verify_message"
  elif [ "$mode" = "network-compatible" ]; then
    status="info"
    message="Hinweis: Network Compatible ist aktiv. ACLs und Hardlinks werden uebertragen, xattrs und File Capabilities jedoch bewusst nicht."
  elif [ "$backup_mode" = "snapshot" ] && [ "$linux_fs" != "true" ] && [ "$mode" != "fake-super" ]; then
    status="warning"
    message="Snapshot-Modus benoetigt verlaessliche Hardlinks. Das erkannte Zielprotokoll muss mit der Metadatenprobe bestaetigt werden."
  fi

  cat <<EOF
{
  "kind": "backup-target",
  "configured": true,
  "status": $(json_escape "$status"),
  "backup_root": $(json_escape "$root"),
  "probe_path": $(json_escape "$probe"),
  "fs_type": $(json_escape "$fs_type"),
  "source": $(json_escape "$source"),
  "mountpoint": $(json_escape "$mountpoint"),
  "majmin": $(json_escape "$majmin"),
  "available_mb": $available_mb,
  "linux_filesystem": $linux_fs,
  "backup_mode": $(json_escape "$backup_mode"),
  "metadata_mode": $(json_escape "$mode"),
  "message": $(json_escape "$message")
}
EOF
}

install_schedule() {
  require_root_for_write
  local cron_file="/etc/cron.d/loxberryhostbackup"
  local enabled mode time_value weekday weekdays monthday monthdays months month_field hour minute dom dow command_line
  local day fallback_start fallback_day normalized_monthdays backend_command
  local -a days
  enabled="$(json_get_bool schedule_enabled)"
  if [ "$enabled" != "true" ]; then
    rm -f "$cron_file"
    return 0
  fi

  mode="$(json_get_string schedule_mode)"
  time_value="$(json_get_string schedule_time)"
  weekday="$(json_get_string schedule_weekday)"
  weekdays="$(json_get_array_lines schedule_weekdays | paste -sd, -)"
  monthday="$(json_get_string schedule_monthday)"
  monthdays="$(json_get_array_lines schedule_monthdays | paste -sd, -)"
  months="$(json_get_array_lines schedule_months | paste -sd, -)"
  case "$mode" in daily|weekly|monthly) ;; *) mode="daily" ;; esac
  case "$time_value" in
    [0-2][0-9]:[0-5][0-9]) ;;
    *) time_value="02:00" ;;
  esac
  hour="${time_value%%:*}"
  minute="${time_value##*:}"
  hour="$((10#$hour))"
  minute="$((10#$minute))"
  case "$weekday" in [0-6]) ;; *) weekday="0" ;; esac
  case "$weekdays" in
    ""|*[!0-6,]*) weekdays="$weekday" ;;
  esac
  case "$monthday" in
    [1-9]|[12][0-9]|3[01]) ;;
    *) monthday="1" ;;
  esac
  case "$monthdays" in
    ""|*[!0-9,]*) monthdays="$monthday" ;;
  esac
  case "$months" in
    ""|"*") month_field="*" ;;
    *[!0-9,]*) month_field="*" ;;
    *) month_field="$months" ;;
  esac

  dom="*"
  dow="*"
  if [ "$mode" = "weekly" ]; then
    dow="$weekdays"
    month_field="*"
  elif [ "$mode" = "monthly" ]; then
    normalized_monthdays=","
    fallback_start=32
    IFS=',' read -r -a days <<< "$monthdays"
    for day in "${days[@]}"; do
      case "$day" in
        [1-9]|[12][0-9]|3[01]) ;;
        *) continue ;;
      esac
      case "$normalized_monthdays" in *",$day,"*) ;; *) normalized_monthdays="${normalized_monthdays}${day}," ;; esac
      if [ "$day" -ge 29 ] && [ "$day" -lt "$fallback_start" ]; then
        fallback_start="$day"
      fi
    done
    if [ "$fallback_start" -le 31 ]; then
      fallback_day=28
      while [ "$fallback_day" -le "$fallback_start" ]; do
        case "$normalized_monthdays" in *",$fallback_day,"*) ;; *) normalized_monthdays="${normalized_monthdays}${fallback_day}," ;; esac
        fallback_day=$((fallback_day + 1))
      done
    fi
    dom="$(printf '%s' "$normalized_monthdays" | sed 's/^,//; s/,$//')"
    [ -n "$dom" ] || dom="$monthday"
  else
    month_field="*"
  fi

  backend_command="$LBP_BINDIR/hostbackup.sh"
  [ "$LBHOMEDIR" != "/opt/loxberry" ] || backend_command="/usr/local/sbin/loxberryhostbackup"
  command_line="$backend_command schedule-run"
  cat > "$cron_file" <<EOF
# Managed by LoxBerry Host Backup.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$minute $hour $dom $month_field $dow root $command_line >/dev/null 2>&1
EOF
  chmod 644 "$cron_file"
}

schedule_run() {
  local enabled mode today last_day month selected_days selected_months day should_run
  enabled="$(json_get_bool schedule_enabled)"
  [ "$enabled" = "true" ] || exit 0
  mode="$(json_get_string schedule_mode)"

  if [ "$mode" != "monthly" ]; then
    start_backup "" accept-warnings
    return $?
  fi

  today="$(date '+%-d')"
  month="$(date '+%-m')"
  last_day="$(date -d "$(date '+%Y-%m-01') +1 month -1 day" '+%-d')"
  selected_days="$(json_get_array_lines schedule_monthdays | paste -sd, -)"
  selected_months="$(json_get_array_lines schedule_months | paste -sd, -)"

  case "$selected_months" in
    ""|"*") ;;
    *) case ",$selected_months," in *",$month,"*) ;; *) exit 0 ;; esac ;;
  esac

  should_run=false
  IFS=',' read -r -a days <<< "$selected_days"
  for day in "${days[@]}"; do
    case "$day" in
      [1-9]|[12][0-9]|3[01]) ;;
      *) continue ;;
    esac
    if [ "$day" -eq "$today" ]; then
      should_run=true
      break
    fi
    if [ "$day" -gt "$last_day" ] && [ "$today" -eq "$last_day" ]; then
      should_run=true
      break
    fi
  done

  [ "$should_run" = "true" ] || exit 0
  start_backup "" accept-warnings
}

log() {
  local msg="$1"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$msg"
}

prepare_log_file() {
  local path="$1" mode="${2:-append}"
  case "$path" in
    "$TASK_LOG_DIR"/*) ;;
    *) echo "Unsafe log path: $path" >&2; return 14 ;;
  esac
  [ -d "$TASK_LOG_DIR" ] && [ ! -L "$TASK_LOG_DIR" ] || { echo "Unsafe log directory: $TASK_LOG_DIR" >&2; return 14; }
  [ ! -L "$path" ] || { echo "Unsafe log symlink: $path" >&2; return 14; }
  [ ! -e "$path" ] || [ -f "$path" ] || { echo "Log path is not a regular file: $path" >&2; return 14; }
  perl -MFcntl=:DEFAULT -e '
    my ($path, $mode) = @ARGV;
    my $flags = O_WRONLY | O_CREAT | O_NOFOLLOW;
    $flags |= O_TRUNC if $mode eq "truncate";
    sysopen(my $fh, $path, $flags, 0640) or die "Cannot open log $path: $!\n";
    chmod 0640, $fh or die "Cannot chmod log $path: $!\n";
    close $fh or die "Cannot close log $path: $!\n";
  ' "$path" "$mode"
}

valid_task_name() {
  case "$1" in
    backup-*.log|restore-*.log|export-*.log|import-*.log|verify-*.log) ;;
    *) return 1 ;;
  esac
  case "$1" in *[!A-Za-z0-9._-]*|.*|*..*|*/*) return 1 ;; esac
}

task_state_path() {
  valid_task_name "$1" || return 1
  printf '%s/%s.json\n' "$TASK_DIR" "$1"
}

process_start_ticks() {
  local pid="$1"
  [ -r "/proc/$pid/stat" ] || return 0
  awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true
}

task_state_write() {
  local task="$1" state="$2" phase="$3" log_file="$4" pid="${5:-$$}" exit_status="${6:-}" expected_state="${7:-}"
  local path start_ticks
  path="$(task_state_path "$task")" || return 1
  start_ticks="$(process_start_ticks "$pid")"
  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MFcntl=:DEFAULT,:flock -MIO::Handle -e '
    my ($file, $task, $state, $phase, $log, $pid, $ticks, $exit_status, $expected_state) = @ARGV;
    sysopen(my $lock, "$file.lock", O_WRONLY | O_CREAT | O_NOFOLLOW, 0600) or die $!;
    flock($lock, LOCK_EX) or die $!;
    if (length($expected_state // "")) {
      sysopen(my $current, $file, O_RDONLY | O_NOFOLLOW) or die $!;
      local $/; my $previous = decode_json(<$current>); close $current or die $!;
      exit 0 unless ($previous->{state} // "") eq $expected_state;
    }
    my $data = {
      task => $task, state => $state, phase => $phase, log_file => $log,
      pid => 0 + ($pid || 0), process_start_ticks => $ticks || "",
      updated_at => time(),
    };
    $data->{exit_status} = 0 + $exit_status if defined($exit_status) && length($exit_status);
    my ($fh, $tmp) = tempfile(".task-XXXXXX", DIR => dirname($file), UNLINK => 0);
    chmod 0600, $tmp;
    print $fh JSON::PP->new->ascii->canonical->pretty->encode($data) or die $!;
    $fh->flush or die $!;
    close $fh or die $!;
    rename $tmp, $file or die $!;
  ' "$path" "$task" "$state" "$phase" "$log_file" "$pid" "$start_ticks" "$exit_status" "$expected_state"
}

task_state_value() {
  local task="$1" field="$2" path
  path="$(task_state_path "$task")" || return 1
  [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ] || return 1
  manifest_field "$path" "$field"
}

task_process_is_current() {
  local task="$1" pid ticks current
  pid="$(task_state_value "$task" pid 2>/dev/null || true)"
  ticks="$(task_state_value "$task" process_start_ticks 2>/dev/null || true)"
  [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  current="$(process_start_ticks "$pid")"
  [ -n "$current" ] && [ "$current" = "$ticks" ]
}

task_failure_on_exit() {
  local status="$1" task="$2" log_file="$3" phase="${4:-failed}"
  if [ "$status" -ne 0 ]; then
    task_state_write "$task" failed "$phase" "$log_file" "$$" "$status" || true
  fi
}

install_task_failure_trap() {
  local task="$1" log_file="$2" cleanup_trap
  printf -v cleanup_trap 'HB_TASK_EXIT_STATUS=$?; trap - EXIT; task_failure_on_exit "$HB_TASK_EXIT_STATUS" %q %q; exit "$HB_TASK_EXIT_STATUS"' "$task" "$log_file"
  # Freeze already-validated task/path arguments before the function unwinds.
  # shellcheck disable=SC2064
  trap "$cleanup_trap" EXIT
}

launch_background() {
  local task="$1" log_file="$2"
  shift 2
  local pid
  prepare_log_file "$log_file" append
  task_state_write "$task" queued queued "$log_file" 0 ""
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >> "$log_file" 2>&1 &
  else
    nohup "$@" >> "$log_file" 2>&1 &
  fi
  pid=$!
  # A fast worker may already be running or finished. Register its PID only
  # while the task is still queued, atomically with every worker state write.
  task_state_write "$task" running launched "$log_file" "$pid" "" queued
  printf '%s\n' "$pid"
}

run_with_heartbeat() {
  local label="$1"
  shift
  "$@" &
  local cmd_pid=$!
  (
    while kill -0 "$cmd_pid" 2>/dev/null; do
      sleep 30
      kill -0 "$cmd_pid" 2>/dev/null || break
      log "$label still running"
    done
  ) &
  local heartbeat_pid=$!
  wait "$cmd_pid"
  local status=$?
  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  return "$status"
}

export_lock_held() {
  local lock_file="$1"
  [ -e "$lock_file" ] || return 1
  [ ! -L "$lock_file" ] && [ -f "$lock_file" ] || return 0
  if ( flock -n 9 ) 9>"$lock_file"; then
    return 1
  fi
  return 0
}

rsync_supports_info() {
  rsync --help 2>/dev/null | grep -- '--info=' >/dev/null
}

rsync_live_options() {
  if rsync_supports_info; then
    printf '%s\n' '--info=progress2,stats2'
    printf '%s\n' '--human-readable'
  else
    printf '%s\n' '--progress'
  fi
}

metadata_mode() {
  local mode
  mode="$(json_get_string metadata_mode)"
  case "$mode" in
    native-strict|network-compatible|fake-super|portable-archive) printf '%s\n' "$mode" ;;
    *) printf '%s\n' "native-strict" ;;
  esac
}

portable_snapshot() {
  [ "$(metadata_mode)" = portable-archive ] && [ "$(json_get_string backup_mode)" = snapshot ]
}

portable_helper() {
  python3 "$LBP_BINDIR/hostbackup-portable.py" --root "$(backup_root)" --state-dir "$ROOT_STATE_DIR" "$@"
}

repository_helper() {
  [ ! -L "$ROOT_STATE_DIR/repositories" ] || return 13
  [ -d "$ROOT_STATE_DIR/repositories" ] || mkdir -m 700 -- "$ROOT_STATE_DIR/repositories"
  python3 "$LBP_BINDIR/hostbackup-repository.py" --backup-root "$(backup_root)" --state-dir "$ROOT_STATE_DIR/repositories" "$@"
}

repository_action() {
  local action="$1"
  require_root_for_write
  require_root_permission_ack
  verify_backup_target "$(backup_root)" false
  acquire_operation_lock exclusive
  portable_helper "$action"
}

repository_stage() {
  require_root_for_write
  require_root_permission_ack
  require_backup_id "$1"
  verify_backup_target "$(backup_root)" false
  acquire_operation_lock exclusive
  # Explicit local Linux destination, never an implicit copy onto the SD card.
  portable_helper stage --backup-id "$1" --destination "$2"
}

repository_recover() {
  require_root_for_write
  require_root_permission_ack
  require_backup_id "$1"
  verify_backup_target "$(backup_root)" false
  acquire_operation_lock exclusive
  local backup_id="$1" staging="$2" destination="$3" mappings="$4" execute="${5:-}"
  local -a options=()
  case "$execute" in '') ;; --execute) options+=(--execute) ;; *) return 13 ;; esac
  portable_helper recover --backup-id "$backup_id" --staging "$staging" --destination "$destination" --map-json "$mappings" "${options[@]}"
}

repository_prune() {
  require_root_for_write
  require_root_permission_ack
  verify_backup_target "$(backup_root)" false
  acquire_operation_lock exclusive
  case "$#" in
    0) repository_helper prune ;;
    2)
      [ "$1" = --confirm-repository-id ] && [[ "$2" =~ ^[0-9a-f]{64}$ ]] || return 13
      repository_helper prune --confirm-repository-id "$2"
      ;;
    *) echo 'Use repository-prune [--confirm-repository-id FULL_REPOSITORY_ID].' >&2; return 13 ;;
  esac
}

rsync_metadata_options() {
  local mode="$1" side="${2:-backup}"
  case "$mode:$side" in
    native-strict:*)
      printf '%s\n' '-aHAX' '--numeric-ids' '--sparse'
      ;;
    network-compatible:*)
      printf '%s\n' '-aHA' '--numeric-ids' '--sparse'
      ;;
    fake-super:backup)
      printf '%s\n' '-aHAX' '--numeric-ids' '--sparse' '-M--fake-super'
      ;;
    fake-super:restore)
      printf '%s\n' '-aHAX' '--numeric-ids' '--sparse' '--fake-super' '-M--super'
      ;;
    *)
      printf '%s\n' '-aHAX' '--numeric-ids' '--sparse'
      ;;
  esac
  if [ "$mode" = "fake-super" ]; then
    # rsync <= 3.2.7 with popt 1.19 can corrupt the destination of a local
    # -M transfer and still exit 0: https://github.com/RsyncProject/rsync/issues/505
    # Start the receiver as a separate LOCAL process. No SSH, network or eval;
    # -s carries filenames over the protocol, preserving spaces/metacharacters.
    printf '%s\n' '--whole-file' '--protect-args' "--rsh=/bin/sh -c 'shift; exec \"\$@\"' hostbackup-local"
  fi
}

rsync_destination() {
  if [ "$1" = "fake-super" ]; then
    printf 'hostbackup-local:%s\n' "$2"
  else
    printf '%s\n' "$2"
  fi
}

tar_metadata_options() {
  printf '%s\n' '--format=pax' '--numeric-owner' '--acls' '--xattrs' '--xattrs-include=*' '--selinux' '--sparse'
}

METADATA_PROBE_MESSAGE=""
METADATA_PROBE_JSON='{}'
metadata_capability_probe() {
  local root="$1" mode="$2" status=0 output report_file
  METADATA_PROBE_MESSAGE=""
  METADATA_PROBE_JSON='{}'
  verify_backup_target "$root" true || return 1
  if portable_snapshot; then
    output="$(portable_helper probe 2>&1)" || status=1
  else
    output="$(python3 "$LBP_BINDIR/hostbackup-metadata.py" --root "$root" --mode "$mode" --state-dir "$ROOT_STATE_DIR" 2>&1)" || status=1
  fi
  if ! METADATA_PROBE_JSON="$(printf '%s' "$output" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d,dict) and d.get("status") in ("ok","error") and isinstance(d.get("message"),str); print(json.dumps(d,ensure_ascii=True))' 2>/dev/null)"; then
    METADATA_PROBE_MESSAGE="Metadatenpruefung konnte nicht ausgefuehrt werden: ${output:0:2000}"
    METADATA_PROBE_JSON="{\"status\":\"error\",\"message\":$(json_escape "$METADATA_PROBE_MESSAGE"),\"checks\":[],\"advice\":[]}"
    status=1
  fi
  METADATA_PROBE_MESSAGE="$(printf '%s' "$METADATA_PROBE_JSON" | perl -MJSON::PP -e 'local $/; print decode_json(<STDIN>)->{message};')"
  if ! printf '%s' "$METADATA_PROBE_JSON" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["status"]=="ok" else 1)'; then status=1; fi
  if ! verify_backup_target "$root" true; then
    METADATA_PROBE_MESSAGE="Backup-Ziel hat sich waehrend der Metadatenpruefung geaendert."
    METADATA_PROBE_JSON="{\"status\":\"error\",\"message\":$(json_escape "$METADATA_PROBE_MESSAGE"),\"checks\":[],\"advice\":[]}"
    status=1
  fi
  # Private, atomic report; never write through an existing report symlink.
  report_file="$(mktemp "$ROOT_STATE_DIR/.metadata-report.XXXXXX")" || return 1
  if ! { printf '%s\n' "$METADATA_PROBE_JSON" > "$report_file" && chmod 600 "$report_file" && mv -fT -- "$report_file" "$ROOT_STATE_DIR/metadata-probe.json"; }; then
    rm -f -- "$report_file"
    return 1
  fi
  return "$status"
}

require_root_for_write() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This action needs root privileges. Use sudo." >&2
    exit 2
  fi
}

require_root_permission_ack() {
  if [ "$(json_get_bool root_permission_ack)" != "true" ]; then
    echo "Root-Freigabe wurde in den Plugin-Einstellungen noch nicht bestaetigt." >&2
    exit 15
  fi
}

valid_backup_id() {
  local value="$1"
  case "$value" in
    ""|.*|*..*|*/*|*[!A-Za-z0-9._-]*) return 1 ;;
    *) return 0 ;;
  esac
}

require_backup_id() {
  local value="$1"
  if ! valid_backup_id "$value"; then
    echo "Unsafe backup id: $value" >&2
    exit 11
  fi
}

validate_hook() {
  local hook="$1"
  local owner mode
  [ -n "$hook" ] || return 1
  case "$hook" in
    /*) ;;
    *) log "Skipping hook with non-absolute path: $hook"; return 1 ;;
  esac
  [ -f "$hook" ] && [ -x "$hook" ] || { log "Skipping hook that is not executable: $hook"; return 1; }
  owner="$(stat -c '%u' "$hook" 2>/dev/null || echo '')"
  mode="$(stat -c '%a' "$hook" 2>/dev/null || echo '')"
  [ "$owner" = "0" ] || { log "Skipping hook not owned by root: $hook"; return 1; }
  [ -n "$mode" ] || return 1
  if (( (8#$mode & 022) != 0 )); then
    log "Skipping hook writable by group/others: $hook"
    return 1
  fi
  return 0
}

host_arch() {
  uname -m 2>/dev/null || printf 'unknown'
}

host_os_pretty() {
  if [ -r /etc/os-release ]; then
    . /etc/os-release
    printf '%s\n' "${PRETTY_NAME:-unknown}"
  else
    printf 'unknown\n'
  fi
}

loxberry_version() {
  if [ -r "$LBHOMEDIR/system/daemons/system/versions.dat" ]; then
    sed -n '1p' "$LBHOMEDIR/system/daemons/system/versions.dat"
  elif [ -r "$LBHOMEDIR/system/versions.dat" ]; then
    sed -n '1p' "$LBHOMEDIR/system/versions.dat"
  else
    printf 'unknown\n'
  fi
}

docker_summary_json() {
  if command -v docker >/dev/null 2>&1; then
    printf '"available": true,'
    printf '"containers": '
    docker ps -a --format '{{json .}}' 2>/dev/null | perl -MJSON::PP -e '
      my @rows;
      while (<STDIN>) {
        chomp;
        push @rows, eval { decode_json($_) } if length;
      }
      print encode_json(\@rows);
    '
  else
    printf '"available": false, "containers": []'
  fi
}

write_manifest() {
  local target="$1"
  local backup_id="$2"
  local status="$3"
  local started_at="$4"
  local finished_at="$5"
  local size_bytes="$6"
  local files_count="$7"
  local manifest="$target/manifest.json"
  local package_file="$target/package-list.txt"
  local services_file="$target/systemd-services.txt"
  local mounts_file="$target/mounts.txt"

  if [ ! -e "$package_file" ] && command -v dpkg-query >/dev/null 2>&1; then
    dpkg-query -W -f='${binary:Package}\t${Version}\n' > "$package_file" 2>/dev/null || true
  fi
  if [ ! -e "$services_file" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl list-unit-files --type=service --no-pager > "$services_file" 2>/dev/null || true
  fi
  [ -e "$mounts_file" ] || mount > "$mounts_file" 2>/dev/null || true

  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MIO::Handle -e '
    my ($manifest, $backup_id, $status, $started_at, $finished_at, $size, $files, $os, $arch, $lbver, $backup_mode, $metadata_mode, $target_source, $target_fstype, $target_mountpoint) = @ARGV;
    my $target_dir = $manifest;
    $target_dir =~ s{/manifest\.json$}{};
    my @docker_stopped;
    if (open my $docker_fh, "<", "$target_dir/docker-running-containers.tsv") {
      while (my $line = <$docker_fh>) {
        chomp $line;
        my ($id, $name) = split /\t/, $line, 2;
        next unless defined $id && length $id;
        push @docker_stopped, { id => $id, name => ($name // "") };
      }
    }
    my @systemd_stopped;
    if (open my $systemd_fh, "<", "$target_dir/systemd-running-services.txt") {
      while (my $unit = <$systemd_fh>) {
        chomp $unit;
        next unless length $unit;
        push @systemd_stopped, $unit;
      }
    }
    my $data = {
      schema_version => 2,
      backup_id => $backup_id,
      status => $status,
      started_at => $started_at,
      finished_at => $finished_at,
      size_bytes => 0 + $size,
      files_count => 0 + $files,
      backup => {
        mode => $backup_mode,
        storage_format => ($metadata_mode eq "portable-archive" ? ($backup_mode eq "snapshot" ? "portable-repository" : "portable-tar") : "directory"),
      },
      metadata => {
        mode => $metadata_mode,
        probe_version => 1,
        fidelity => (($metadata_mode eq "network-compatible") ? "degraded" : "full"),
        preserved => {
          uid_gid => JSON::PP::true,
          mode => JSON::PP::true,
          acl => JSON::PP::true,
          xattr => (($metadata_mode eq "network-compatible") ? JSON::PP::false : JSON::PP::true),
          capabilities => (($metadata_mode eq "network-compatible") ? JSON::PP::false : JSON::PP::true),
          hardlinks => JSON::PP::true,
          symlinks => JSON::PP::true,
          special_files => JSON::PP::true,
          sparse => JSON::PP::true,
        },
      },
      target => {
        source => $target_source,
        fstype => $target_fstype,
        mountpoint => $target_mountpoint,
      },
      host => {
        hostname => scalar(`hostname 2>/dev/null`) || "unknown",
        os => $os,
        architecture => $arch,
      },
      loxberry => {
        home => $ENV{LBHOMEDIR} || "/opt/loxberry",
        version => $lbver,
      },
    };
    $data->{stopped_targets} = {
      docker => \@docker_stopped,
      systemd => \@systemd_stopped,
    } if @docker_stopped || @systemd_stopped;
    chomp $data->{host}->{hostname};
    my ($fh, $tmp) = tempfile(".manifest-XXXXXX", DIR => dirname($manifest), UNLINK => 0);
    chmod 0600, $tmp;
    print $fh JSON::PP->new->ascii->pretty->canonical->encode($data) or die $!;
    $fh->flush or die $!;
    close $fh or die $!;
    rename $tmp, $manifest or die "Cannot replace $manifest: $!";
  ' "$manifest" "$backup_id" "$status" "$started_at" "$finished_at" "$size_bytes" "$files_count" "$(host_os_pretty)" "$(host_arch)" "$(loxberry_version)" "$(json_get_string backup_mode)" "$(metadata_mode)" "$(json_get_string target_source)" "$(json_get_string target_fstype)" "$(json_get_string target_mountpoint)"

  {
    printf '{\n'
    printf '  "captured_at": "%s",\n' "$(date -Iseconds)"
    printf '  "docker": {'
    docker_summary_json
    printf '}\n'
    printf '}\n'
  } > "$target/docker.json"
}

backup_excludes() {
  local root="$1"
  cat <<EOF
/proc
/sys
/dev
/run
/tmp
/lost+found
/var/cache
$ROOT_STATE_DIR
$root
EOF
  json_get_array_lines rsync_extra_excludes
}

source_info() {
  local rules status=0
  rules="$(mktemp "$ROOT_STATE_DIR/.source-rules.XXXXXX")" || return 18
  if ! backup_excludes "$(backup_root)" > "$rules"; then rm -f -- "$rules"; return 18; fi
  python3 "$LBP_BINDIR/hostbackup-sources.py" source-info --config "$CONFIG_FILE" --excludes "$rules" || status=$?
  rm -f -- "$rules"
  return "$status"
}

run_hook() {
  local hook="$1"
  [ -n "$hook" ] || return 0
  validate_hook "$hook" || return 1
  "$hook"
}

selected_stop_targets() {
  perl -MJSON::PP -e '
    my ($file) = @ARGV;
    open my $fh, "<", $file or exit 0;
    local $/;
    my $cfg = eval { decode_json(<$fh>) } || {};
    my $targets = $cfg->{stop_targets};
    exit 0 unless ref($targets) eq "ARRAY";
    for my $target (@$targets) {
      next unless ref($target) eq "HASH";
      my $type = $target->{type} // "";
      my $name = $target->{name} // "";
      next unless $type =~ /^(docker|systemd)$/ && length $name;
      print "$type\t$name\n";
    }
  ' "$CONFIG_FILE"
}

protected_systemd_service() {
  local unit="$1"
  case "$unit" in
    loxberry.service|LoxBerryHostBackup.service|loxberryhostbackup.service) return 0 ;;
    ssh.service|sshd.service|dropbear.service|cron.service|crond.service|anacron.service) return 0 ;;
    dbus.service|polkit.service|systemd-*.service|udev.service) return 0 ;;
    getty@*.service|serial-getty@*.service|user@*.service) return 0 ;;
    networking.service|NetworkManager.service) return 0 ;;
    docker.service|containerd.service) return 0 ;;
    apache2.service|lighttpd.service|nginx.service|php*-fpm.service) return 0 ;;
    *.mount|*.socket|*.timer) return 0 ;;
  esac
  return 1
}

systemd_service_group() {
  local unit="$1"
  local description="${2:-}"
  local metadata
  metadata="$(systemctl show "$unit" -p ExecStart -p FragmentPath -p Description --no-pager 2>/dev/null || true)"
  if printf '%s\n%s\n%s\n' "$unit" "$description" "$metadata" | grep -Eiq '(/plugins/|/opt/loxberry/(bin|data|config)/plugins|stats4lox|loxone|loxhue|netatmo|zigbee|mqtt|miniserver)'; then
    printf '%s\n' "LoxBerry-/Plugin-Dienste"
  else
    printf '%s\n' "Weitere Systemdienste"
  fi
}

friendly_systemd_label() {
  local unit="$1"
  local description="${2:-}"
  local label="${description:-$unit}"

  case "$unit $description" in
    *stats4lox*|*Stats4Lox*) label="Stats4Lox" ;;
    *netatmo*|*Netatmo*) label="Netatmo" ;;
    *zigbee*|*Zigbee*|*ZigBee*) label="Zigbee / MQTT" ;;
    *mqtt*|*MQTT*) label="MQTT / ZigbeeMQTT" ;;
    *miniserver*|*Miniserver*) label="Miniserver Backup" ;;
    *loxhue*|*LoxHue*|*hue*) label="LoxHue / Hue Bridge" ;;
  esac

  printf '%s\n' "$label"
}

discover_stop_targets() {
  local tmp unit active sub description group name image status
  tmp="$(mktemp)"

  if command -v docker >/dev/null 2>&1; then
    docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null |
      while IFS="$(printf '\t')" read -r name image status; do
        [ -n "$name" ] || continue
        printf 'docker\t%s\t%s\tDocker-Container\t%s\t%s\n' "$name" "$name" "$status" "$image" >> "$tmp"
      done || true
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl list-units --type=service --state=running --all --no-legend --no-pager 2>/dev/null |
      while read -r unit _load active sub description; do
        [ -n "$unit" ] || continue
        protected_systemd_service "$unit" && continue
        group="$(systemd_service_group "$unit" "$description")"
        label="$(friendly_systemd_label "$unit" "$description")"
        printf 'systemd\t%s\t%s\t%s\t%s\t%s\n' "$unit" "$label" "$group" "${active}/${sub}" "$unit" >> "$tmp"
      done || true

    systemctl list-unit-files --type=service --no-legend --no-pager 2>/dev/null |
      while read -r unit _state _rest; do
        [ -n "$unit" ] || continue
        protected_systemd_service "$unit" && continue
        grep -F "$(printf 'systemd\t%s\t' "$unit")" "$tmp" >/dev/null 2>&1 && continue
        group="$(systemd_service_group "$unit" "")"
        [ "$group" = "LoxBerry-/Plugin-Dienste" ] || continue
        description="$(systemctl show "$unit" -p Description --value --no-pager 2>/dev/null || true)"
        active="$(systemctl is-active "$unit" 2>/dev/null || true)"
        label="$(friendly_systemd_label "$unit" "$description")"
        printf 'systemd\t%s\t%s\t%s\t%s\t%s\n' "$unit" "$label" "$group" "${active:-inactive}" "$unit" >> "$tmp"
      done || true
  fi

  perl -MJSON::PP -e '
    my ($cfg_file, $targets_file) = @ARGV;
    my %selected;
    my $recommend_re = qr/(mariadb|mysql|postgres|postgresql|influx|grafana|telegraf|mosquitto|mqtt|zigbee|node-?red|nodered|stats4lox|netatmo|miniserver|loxhue|huebridge|redis|mongodb|prometheus|homeassistant|home-assistant|portainer|database|db|broker)/i;
    if (open my $fh, "<", $cfg_file) {
      local $/;
      my $cfg = eval { decode_json(<$fh>) } || {};
      if (ref($cfg->{stop_targets}) eq "ARRAY") {
        for my $target (@{$cfg->{stop_targets}}) {
          next unless ref($target) eq "HASH";
          my $type = $target->{type} // "";
          my $name = $target->{name} // "";
          $selected{"$type:$name"} = 1 if length $type && length $name;
        }
      }
    }
    my @items;
    if (open my $fh, "<", $targets_file) {
      while (my $line = <$fh>) {
        chomp $line;
        my ($type, $name, $label, $group, $status, $details) = split /\t/, $line, 6;
        next unless $type && $name;
        my $joined = join(" ", grep { defined && length } ($type, $name, $label, $group, $status, $details));
        my $active = ($type eq "docker" && ($status // "") =~ /^Up\b/i)
          || ($type eq "systemd" && ($status // "") =~ /active|running/i);
        my $recommended = 0;
        if ($active && $type eq "docker") {
          $recommended = 1;
        } elsif ($active && $type eq "systemd" && (($group // "") eq "LoxBerry-/Plugin-Dienste" || $joined =~ $recommend_re)) {
          $recommended = 1;
        }
        push @items, {
          type => $type,
          name => $name,
          label => length($label // "") ? $label : $name,
          group => length($group // "") ? $group : "Weitere Dienste",
          status => $status // "",
          details => $details // "",
          recommended => ($recommended ? JSON::PP::true : JSON::PP::false),
          selected => ($selected{"$type:$name"} ? JSON::PP::true : JSON::PP::false),
        };
      }
    }
    @items = sort { ($a->{group} cmp $b->{group}) || ($a->{label} cmp $b->{label}) } @items;
    print JSON::PP->new->ascii->canonical->pretty->encode(\@items);
  ' "$CONFIG_FILE" "$tmp"
  rm -f "$tmp"
}

restart_journal_path_is_safe() {
  local state_dir="$1" task
  case "$state_dir" in "$RESTART_JOURNAL_DIR"/*) ;; *) return 13 ;; esac
  task="${state_dir#"$RESTART_JOURNAL_DIR/"}"
  valid_task_name "$task" || return 13
  [ -d "$state_dir" ] && [ ! -L "$state_dir" ] && [ ! -L "$state_dir/journal.json" ]
}

restart_journal_update() {
  local state_dir="$1" action="$2" type="${3:-}" identity="${4:-}" label="${5:-}"
  restart_journal_path_is_safe "$state_dir" || { echo "Unsafe restart journal." >&2; return 13; }
  perl -MJSON::PP -MFile::Temp=tempfile -MFcntl=:DEFAULT -MIO::Handle -e '
    my ($dir, $action, $type, $id, $label) = @ARGV;
    my ($task) = $dir =~ m{([^/]+)$};
    my $file = "$dir/journal.json";
    my $data = {task => $task, entries => []};
    if (-e $file) {
      sysopen(my $in, $file, O_RDONLY | O_NOFOLLOW) or die "Cannot read restart journal: $!\n";
      local $/; $data = decode_json(<$in>); close $in or die $!;
      die "Invalid restart journal\n" unless ref($data) eq "HASH" && ($data->{task} // "") eq $task && ref($data->{entries}) eq "ARRAY";
    } elsif ($action ne "init") { die "Restart journal missing\n"; }
    for my $entry (@{$data->{entries}}) {
      die "Invalid journal entry\n" unless ref($entry) eq "HASH" && ($entry->{type} // "") =~ /\A(?:docker|systemd)\z/ && ($entry->{id} // "") =~ /\A[A-Za-z0-9][A-Za-z0-9_.@:\\-]*\z/ && ($entry->{phase} // "") =~ /\A(?:intended|stopped|restarted)\z/;
    }
    if ($action eq "pending") {
      for my $entry (reverse @{$data->{entries}}) {
        next if $entry->{phase} eq "restarted";
        print "$entry->{type}\t$entry->{id}\t$entry->{phase}\n";
      }
      exit 0;
    }
    if ($action ne "init") {
      die "Invalid restart operation\n" unless $action =~ /\A(?:intended|stopped|restarted)\z/ && $type =~ /\A(?:docker|systemd)\z/ && $id =~ /\A[A-Za-z0-9][A-Za-z0-9_.@:\\-]*\z/;
      my ($entry) = grep { $_->{type} eq $type && $_->{id} eq $id } @{$data->{entries}};
      if (!$entry) {
        die "Missing restart intent\n" unless $action eq "intended";
        $entry = {type => $type, id => $id}; push @{$data->{entries}}, $entry;
      }
      $entry->{phase} = $action; $entry->{updated_at} = time();
    }
    my ($out, $tmp) = tempfile(".journal-XXXXXX", DIR => $dir, UNLINK => 0);
    chmod 0600, $tmp or die $!;
    print $out JSON::PP->new->ascii->canonical->encode($data) or die $!;
    $out->flush or die $!; $out->sync or die "Cannot sync restart journal: $!\n";
    close $out or die $!; rename $tmp, $file or die $!;
    if ($^O eq "linux") {
      sysopen(my $directory, $dir, O_RDONLY) or die $!;
      $directory->sync or die "Cannot sync restart directory: $!\n";
      close $directory or die $!;
      if ($action eq "init") {
        (my $parent = $dir) =~ s{/[^/]+$}{};
        sysopen(my $parent_directory, $parent, O_RDONLY) or die $!;
        $parent_directory->sync or die "Cannot sync restart journal parent: $!\n";
        close $parent_directory or die $!;
      }
    }
  ' "$state_dir" "$action" "$type" "$identity" "$label"
}

restart_journal_create() {
  local task="$1" state_dir="$RESTART_JOURNAL_DIR/$1"
  valid_task_name "$task" || return 13
  [ ! -e "$state_dir" ] && [ ! -L "$state_dir" ] || { echo "A restart journal already exists for $task; recover it first." >&2; return 20; }
  mkdir -m 700 -- "$state_dir" || return 20
  restart_journal_update "$state_dir" init || return 20
  printf '%s\n' "$state_dir"
}

restart_journal_finish() {
  local state_dir="$1" pending control name entry
  restart_journal_path_is_safe "$state_dir" || return 13
  pending="$(restart_journal_update "$state_dir" pending)" || return 20
  [ -z "$pending" ] || { log "ERROR: Service recovery is still pending in $state_dir"; return 20; }
  # Preserve the journal itself when unexpected material needs investigation.
  for entry in "$state_dir"/* "$state_dir"/.[!.]* "$state_dir"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    case "${entry##*/}" in
      repository-controls) ;;
      journal.json|selected-stop-targets.tsv|docker-to-stop.tsv|post-hook.started|post-hook.done|restart.done|source-files.nul|repository-candidate.json)
        [ -f "$entry" ] && [ ! -L "$entry" ] || return 20 ;;
      *) return 20 ;;
    esac
  done
  # Portable workers keep recovery controls private until publication. Remove
  # only these known temporary files, never repository keys or unknown data.
  control="$state_dir/repository-controls"
  if [ -e "$control" ] || [ -L "$control" ]; then
    [ -d "$control" ] && [ ! -L "$control" ] || return 20
    local -a names=(manifest.json rsync-excludes.txt source-selection.json source-mounts.json
      mounts.txt metadata-probe.json package-list.txt systemd-services.txt docker.json backup-validation.json)
    for name in "${names[@]}"; do
      [ ! -L "$control/$name" ] && { [ ! -e "$control/$name" ] || [ -f "$control/$name" ]; } || return 20
    done
    for name in "${names[@]}"; do rm -f -- "$control/$name" || return 20; done
    rmdir -- "$control" || return 20
  fi
  [ ! -L "$state_dir/repository-candidate.json" ] && { [ ! -e "$state_dir/repository-candidate.json" ] || [ -f "$state_dir/repository-candidate.json" ]; } || return 20
  rm -f -- "$state_dir/repository-candidate.json" || return 20
  # Remove only the known local control files; retain unexpected data for diagnosis.
  rm -f -- "$state_dir/journal.json" "$state_dir/selected-stop-targets.tsv" "$state_dir/docker-to-stop.tsv" "$state_dir/post-hook.started" "$state_dir/post-hook.done" "$state_dir/restart.done" "$state_dir/source-files.nul" || return 20
  rmdir -- "$state_dir" || return 20
}

restart_journal_retry_type() {
  local state_dir="$1" requested_type="$2" pending type identity phase failed=0
  pending="$(restart_journal_update "$state_dir" pending)" || return 20
  while IFS=$'\t' read -r type identity phase; do
    [ "$type" = "$requested_type" ] || continue
    log "Recovering $type $identity (journal state: $phase)"
    if [ "$type" = docker ]; then
      if ! command -v docker >/dev/null 2>&1; then failed=1; continue; fi
      if [ "$(docker inspect --format '{{.State.Running}}' "$identity" 2>/dev/null || true)" != true ]; then
        if command -v timeout >/dev/null 2>&1; then timeout 45 docker start "$identity" || true;
        else docker start "$identity" || true; fi
      fi
      if [ "$(docker inspect --format '{{.State.Running}}' "$identity" 2>/dev/null || true)" != true ]; then
        log "ERROR: Docker container $identity did not restart; journal retained for retry"; failed=1; continue
      fi
    else
      if ! command -v systemctl >/dev/null 2>&1; then failed=1; continue; fi
      if ! systemctl is-active --quiet "$identity" 2>/dev/null; then
        if command -v timeout >/dev/null 2>&1; then timeout 45 systemctl start "$identity" || true;
        else systemctl start "$identity" || true; fi
      fi
      if ! systemctl is-active --quiet "$identity" 2>/dev/null; then
        log "ERROR: Systemd service $identity did not restart; journal retained for retry"; failed=1; continue
      fi
    fi
    restart_journal_update "$state_dir" restarted "$type" "$identity" || failed=1
  done <<< "$pending"
  return "$failed"
}

recover_restart_journals() {
  require_root_for_write || return $?
  local state_dir task log_file failed=0 busy_notice=report lock_status=0
  case "$#:${1:-}" in
    0:) ;;
    1:--scheduled) busy_notice=quiet-busy ;;
    *) echo "Usage: recover-services [--scheduled]" >&2; return 64 ;;
  esac
  acquire_operation_lock exclusive "$busy_notice" || lock_status=$?
  if [ "$lock_status" -ne 0 ]; then
    # Cron will retry in five minutes. Do not touch journals or active tasks.
    [ "$lock_status" -ne 5 ] || [ "$busy_notice" != quiet-busy ] || return 0
    return "$lock_status"
  fi
  for state_dir in "$RESTART_JOURNAL_DIR"/*; do
    [ -d "$state_dir" ] && [ ! -L "$state_dir" ] || continue
    task="$(basename -- "$state_dir")"
    valid_task_name "$task" || { failed=1; continue; }
    task_process_is_current "$task" && continue
    log_file="$TASK_LOG_DIR/$task"
    prepare_log_file "$log_file" append || { failed=1; continue; }
    log "Recovering interrupted task $task from local restart journal" | tee -a "$log_file"
    if start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file" && restart_journal_finish "$state_dir"; then
      task_state_write "$task" failed recovered_after_interruption "$log_file" 0 20 || failed=1
    else
      task_state_write "$task" failed cleanup_failed "$log_file" 0 20 || true
      failed=1
    fi
  done
  return "$failed"
}

stop_docker_if_requested() {
  if [ "$(json_get_bool stop_docker_before_backup)" = "true" ] && command -v docker >/dev/null 2>&1; then
    local state_dir="$1" failed=0
    local id name
    docker ps --format '{{.ID}}\t{{.Names}}' > "$state_dir/docker-to-stop.tsv" 2>/dev/null || return 1
    if [ -s "$state_dir/docker-to-stop.tsv" ]; then
      log "Docker containers running before backup:"
      while IFS="$(printf '\t')" read -r id name; do
        [ -n "$id" ] || continue
        log "  $name ($id)"
      done < "$state_dir/docker-to-stop.tsv"
      while IFS="$(printf '\t')" read -r id name; do
        [ -n "$id" ] || continue
        restart_journal_update "$state_dir" intended docker "$id" "$name" || return 20
        log "Stopping Docker container $name ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker stop -t 30 "$id" || failed=1
        else
          docker stop -t 30 "$id" || failed=1
        fi
        if [ "$(docker inspect --format '{{.State.Running}}' "$id" 2>/dev/null || true)" = "false" ]; then
          restart_journal_update "$state_dir" stopped docker "$id" "$name" || return 20
        else
          log "ERROR: Docker container $name ($id) is still running"
          failed=1
        fi
      done < "$state_dir/docker-to-stop.tsv"
    else
      log "No running Docker containers found before backup"
    fi
    return "$failed"
  fi
}

stop_selected_systemd_targets() {
  local state_dir="$1"
  local targets_file="$2"
  local unit failed=0
  [ -s "$targets_file" ] || return 0
  command -v systemctl >/dev/null 2>&1 || return 0
  while IFS="$(printf '\t')" read -r type unit; do
    [ "$type" = "systemd" ] || continue
    [ -n "$unit" ] || continue
    protected_systemd_service "$unit" && { log "Skipping protected systemd service $unit"; continue; }
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
      restart_journal_update "$state_dir" intended systemd "$unit" || return 20
      log "Stopping systemd service $unit"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 systemctl stop "$unit" || failed=1
      else
        systemctl stop "$unit" || failed=1
      fi
      if ! systemctl is-active --quiet "$unit" 2>/dev/null; then
        restart_journal_update "$state_dir" stopped systemd "$unit" || return 20
      else
        log "ERROR: systemd service $unit is still active"
        failed=1
      fi
    else
      log "Systemd service $unit is not running; nothing to stop"
    fi
  done < "$targets_file"
  return "$failed"
}

stop_selected_docker_targets() {
  local state_dir="$1"
  local targets_file="$2"
  local type name id running failed=0
  [ -s "$targets_file" ] || return 0
  command -v docker >/dev/null 2>&1 || return 0
  while IFS="$(printf '\t')" read -r type name; do
    [ "$type" = "docker" ] || continue
    [ -n "$name" ] || continue
    running="$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)"
    if [ "$running" = "true" ]; then
      id="$(docker inspect --format '{{.Id}}' "$name" 2>/dev/null | cut -c1-12)"
      restart_journal_update "$state_dir" intended docker "${id:-$name}" "$name" || return 20
      log "Stopping Docker container $name (${id:-unknown})"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 docker stop -t 30 "$name" || failed=1
      else
        docker stop -t 30 "$name" || failed=1
      fi
      if [ "$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)" = "false" ]; then
        restart_journal_update "$state_dir" stopped docker "${id:-$name}" "$name" || return 20
      else
        log "ERROR: Docker container $name is still running"
        failed=1
      fi
    else
      log "Docker container $name is not running; nothing to stop"
    fi
  done < "$targets_file"
  return "$failed"
}

stop_backup_targets() {
  local state_dir="$1"
  local targets_file="$state_dir/selected-stop-targets.tsv"
  restart_journal_path_is_safe "$state_dir" || return 13
  selected_stop_targets > "$targets_file" || return 20
  if [ -s "$targets_file" ]; then
    log "Stopping selected native services and Docker containers if they are running"
    stop_selected_systemd_targets "$state_dir" "$targets_file" || return $?
    stop_selected_docker_targets "$state_dir" "$targets_file" || return $?
  else
    log "No individual stop targets configured; checking legacy Docker option"
    stop_docker_if_requested "$state_dir"
  fi
}

start_docker_if_needed() {
  local state_dir="$1"
  if [ -f "$state_dir/journal.json" ]; then
    restart_journal_retry_type "$state_dir" docker
    return $?
  fi
  local state_tsv="$state_dir/docker-running-containers.tsv"
  local state_file="$state_dir/docker-running-containers.txt"
  local id name source_file failed=0
  if command -v docker >/dev/null 2>&1; then
    if [ -s "$state_tsv" ]; then
      source_file="$state_tsv"
      while IFS="$(printf '\t')" read -r id name; do
        [ -n "$id" ] || continue
        log "Starting Docker container $name ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker start "$id" || failed=1
        else
          docker start "$id" || failed=1
        fi
        [ "$(docker inspect --format '{{.State.Running}}' "$id" 2>/dev/null || true)" = "true" ] || { log "ERROR: Docker container $name ($id) did not restart"; failed=1; }
      done < "$source_file"
    elif [ -s "$state_file" ]; then
      while IFS= read -r id; do
        [ -n "$id" ] || continue
        name="$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')"
        log "Starting Docker container ${name:-unknown} ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker start "$id" || failed=1
        else
          docker start "$id" || failed=1
        fi
        [ "$(docker inspect --format '{{.State.Running}}' "$id" 2>/dev/null || true)" = "true" ] || { log "ERROR: Docker container ${name:-unknown} ($id) did not restart"; failed=1; }
      done < "$state_file"
    else
      log "No Docker container state file found for restart"
    fi
  fi
  return "$failed"
}

start_systemd_if_needed() {
  local state_dir="$1"
  if [ -f "$state_dir/journal.json" ]; then
    restart_journal_retry_type "$state_dir" systemd
    return $?
  fi
  local state_file="$state_dir/systemd-running-services.txt"
  local unit failed=0
  if command -v systemctl >/dev/null 2>&1 && [ -s "$state_file" ]; then
    while IFS= read -r unit; do
      [ -n "$unit" ] || continue
      log "Starting systemd service $unit"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 systemctl start "$unit" || failed=1
      else
        systemctl start "$unit" || failed=1
      fi
      systemctl is-active --quiet "$unit" 2>/dev/null || { log "ERROR: systemd service $unit did not restart"; failed=1; }
    done < <(tac "$state_file" 2>/dev/null)
  fi
  return "$failed"
}

log_restart_targets() {
  local state_dir="$1"
  if [ -f "$state_dir/journal.json" ]; then
    log "Pending service/container recovery from local journal:"
    restart_journal_update "$state_dir" pending
    return $?
  fi
  local docker_file="$state_dir/docker-running-containers.tsv"
  local systemd_file="$state_dir/systemd-running-services.txt"
  local id name unit found=0

  if [ -s "$docker_file" ]; then
    found=1
    log "Docker containers recorded for restart:"
    while IFS="$(printf '\t')" read -r id name; do
      [ -n "$id" ] || continue
      log "  ${name:-unknown} ($id)"
    done < "$docker_file"
  fi

  if [ -s "$systemd_file" ]; then
    found=1
    log "Systemd services recorded for restart:"
    while IFS= read -r unit; do
      [ -n "$unit" ] || continue
      log "  $unit"
    done < "$systemd_file"
  fi

  [ "$found" -eq 1 ] || log "No stopped services or Docker containers recorded for restart"
}

start_backup_targets_if_needed() {
  local state_dir="$1"
  local failed=0
  restart_journal_update "$state_dir" pending >/dev/null || return 20
  log_restart_targets "$state_dir"
  start_docker_if_needed "$state_dir" || failed=1
  start_systemd_if_needed "$state_dir" || failed=1
  return "$failed"
}

backup_cleanup_on_exit() {
  local status="$1"
  local target="$2"
  local log_file="$3"
  local already_restarted="$4"
  local post_hook="${5:-}"
  local task="${6:-}"
  local state_dir="${7:-$RESTART_JOURNAL_DIR/$task}" cleanup_failed=0 manifest_status=""

  if [ "$already_restarted" != "true" ] && [ ! -d "$state_dir" ]; then
    cleanup_failed=1
    log "ERROR: Local restart journal is missing; service recovery could not be verified" | tee -a "$log_file" || true
  fi
  if [ "$already_restarted" != "true" ] && [ -d "$state_dir" ]; then
    if [ -n "$log_file" ]; then
      log "Cleanup: restarting services and Docker containers after interrupted backup (exit status $status)" | tee -a "$log_file" || true
      start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file" || cleanup_failed=1
    else
      log "Cleanup: restarting services and Docker containers after interrupted backup (exit status $status)" || true
      start_backup_targets_if_needed "$state_dir" || cleanup_failed=1
    fi
    if [ "$cleanup_failed" -eq 0 ]; then write_control_marker "$state_dir/restart.done" || cleanup_failed=1; fi
  fi
  if [ -d "$state_dir" ] && [ ! -e "$state_dir/post-hook.started" ] && [ ! -e "$state_dir/post-hook.done" ]; then
    write_control_marker "$state_dir/post-hook.started" || cleanup_failed=1
    if ! run_hook "$post_hook" 2>&1 | tee -a "$log_file"; then
      cleanup_failed=1
    fi
    write_control_marker "$state_dir/post-hook.done" || cleanup_failed=1
  fi
  if [ -d "$state_dir" ] && [ "$cleanup_failed" -eq 0 ]; then
    restart_journal_finish "$state_dir" || cleanup_failed=1
  fi
  # A late stop after successful validation must not invalidate the data.
  manifest_status="$(manifest_field "$target/manifest.json" status 2>/dev/null || true)"
  if [ -n "$task" ] && [ "$cleanup_failed" -eq 0 ] && { [ "$manifest_status" = complete ] || [ "$manifest_status" = complete_with_warnings ]; } && { [ "$status" -eq 129 ] || [ "$status" -eq 130 ] || [ "$status" -eq 143 ]; }; then
    task_state_write "$task" finished complete "$log_file" 0 0 || true
    log "Backup already finalized before the stop signal; completed result preserved" | tee -a "$log_file" || true
    return 0
  fi
  if [ -n "$task" ] && { [ "$status" -ne 0 ] || [ "$cleanup_failed" -ne 0 ]; }; then
    task_state_write "$task" failed "$([ "$cleanup_failed" -eq 0 ] && printf failed || printf cleanup_failed)" "$log_file" "$$" "$status" || true
  fi
  if [ "$status" -ne 0 ] && [ -r "$target/manifest.json" ] && [ "$manifest_status" != complete ] && [ "$manifest_status" != complete_with_warnings ]; then
    local backup_id started size files
    backup_id="$(basename -- "$target")"
    started="$(manifest_started_at "$target")"
    [ -n "$started" ] || started="$(date -Iseconds)"
    # Interrupted/missing media must never delay host recovery for another size scan.
    size="$(manifest_field "$target/manifest.json" size_bytes 2>/dev/null || printf 0)"
    files="$(manifest_field "$target/manifest.json" files_count 2>/dev/null || printf 0)"
    write_manifest "$target" "$backup_id" "$([ "$cleanup_failed" -eq 0 ] && printf failed || printf cleanup_failed)" "$started" "$(date -Iseconds)" "${size:-0}" "${files:-0}" || true
  fi
  return "$cleanup_failed"
}

selected_docker_stop_count() {
  selected_stop_targets | awk '$1 == "docker" { count++ } END { print count + 0 }'
}

calculate_size() {
  local path="$1"
  du -sB1 "$path" 2>/dev/null | awk '{print $1}' || printf '0'
}

calculate_files() {
  local path="$1"
  if [ -d "$path/rootfs" ] && [ ! -L "$path/rootfs" ]; then
    find "$path/rootfs" -xdev -type f 2>/dev/null | wc -l | tr -d ' '
  elif [ -f "$path/rootfs.tar" ] && [ ! -L "$path/rootfs.tar" ]; then
    tar -tf "$path/rootfs.tar" 2>/dev/null | wc -l | tr -d ' '
  else
    printf '0\n'
  fi
}

validate_completed_backup() {
  local target="$1"
  local backup_mode="$2"
  local previous_backup="${3:-}"
  local size_bytes="${4:-0}"
  local files_count="${5:-0}"
  local copy_status="${6:-0}"
  local validation_file="$target/backup-validation.json"
  local status="ok"
  local manifest_ok rootfs_ok etc_ok loxberry_ok varlib_ok mntdocker_ok hardlink_ok size_ok files_ok metadata_ok
  local hardlink_value="not_checked"
  local metadata_value metadata_mode_value metadata_informational=false list_file min_size min_files

  [ -r "$target/manifest.json" ] && manifest_ok=true || manifest_ok=false
  if [ -d "$target/rootfs" ] && [ ! -L "$target/rootfs" ]; then
    rootfs_ok=true
    [ -d "$target/rootfs/etc" ] && etc_ok=true || etc_ok=false
    [ -d "$target/rootfs/opt/loxberry" ] && loxberry_ok=true || loxberry_ok=false
    [ -d "$target/rootfs/var/lib" ] && varlib_ok=true || varlib_ok=false
    [ -d "$target/rootfs/mnt/docker" ] && mntdocker_ok=true || mntdocker_ok=false
  elif [ -f "$target/rootfs.tar" ] && [ ! -L "$target/rootfs.tar" ]; then
    list_file="$(mktemp)"
    if tar -tf "$target/rootfs.tar" > "$list_file" 2>/dev/null; then
      rootfs_ok=true
      grep -Eq '^(\./)?etc(/|$)' "$list_file" && etc_ok=true || etc_ok=false
      grep -Eq '^(\./)?opt/loxberry(/|$)' "$list_file" && loxberry_ok=true || loxberry_ok=false
      grep -Eq '^(\./)?var/lib(/|$)' "$list_file" && varlib_ok=true || varlib_ok=false
      grep -Eq '^(\./)?mnt/docker(/|$)' "$list_file" && mntdocker_ok=true || mntdocker_ok=false
    else
      rootfs_ok=false; etc_ok=false; loxberry_ok=false; varlib_ok=false; mntdocker_ok=false
    fi
    rm -f "$list_file"
  else
    rootfs_ok=false; etc_ok=false; loxberry_ok=false; varlib_ok=false; mntdocker_ok=false
  fi
  min_size="${HOSTBACKUP_MIN_SIZE_BYTES:-104857600}"
  min_files="${HOSTBACKUP_MIN_FILES:-100}"
  [ "${size_bytes:-0}" -ge "$min_size" ] && size_ok=true || size_ok=false
  [ "${files_count:-0}" -ge "$min_files" ] && files_ok=true || files_ok=false
  metadata_mode_value="$(metadata_mode)"
  metadata_ok=true
  metadata_value="copy completed with configured metadata options; structural validation, not a complete restore test"
  if [ "$metadata_mode_value" = "network-compatible" ]; then
    metadata_value="xattrs and file capabilities intentionally omitted"
    metadata_informational=true
  fi
  if [ "$copy_status" -eq 24 ]; then
    metadata_ok=false
    metadata_value="source files vanished during backup"
    metadata_informational=false
  fi

  hardlink_ok=true
  if [ "$backup_mode" = "snapshot" ] && [ -n "$previous_backup" ] && [ -d "$previous_backup/rootfs" ]; then
    if ! hardlink_value="$(snapshot_reference_stats "$target/rootfs" "$previous_backup/rootfs")"; then
      hardlink_ok=false
      hardlink_value="reference_comparison_failed"
    fi
  fi

  if [ "$manifest_ok" != "true" ] || [ "$rootfs_ok" != "true" ] || [ "$etc_ok" != "true" ] || [ "$loxberry_ok" != "true" ]; then
    status="error"
  elif [ "$varlib_ok" != "true" ] || [ "$size_ok" != "true" ] || [ "$files_ok" != "true" ] || [ "$hardlink_ok" != "true" ] || [ "$metadata_ok" != "true" ]; then
    status="warning"
  fi

  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MIO::Handle -e '
    my ($file, $status, $manifest_ok, $rootfs_ok, $etc_ok, $loxberry_ok, $varlib_ok, $mntdocker_ok, $hardlink_ok, $hardlink_value, $size_ok, $files_ok, $size_bytes, $files_count, $metadata_ok, $metadata_value, $metadata_mode, $metadata_informational) = @ARGV;
    my $bool = sub { $_[0] eq "true" ? JSON::PP::true : JSON::PP::false };
    my $hardlink_details = eval { decode_json($hardlink_value) };
    if (ref($hardlink_details) eq "HASH") {
      $hardlink_value = "Referenz-Wiederverwendung: $hardlink_details->{reference_reused_files} Dateien; geprueft: $hardlink_details->{files_checked}; weitere Namen desselben Inodes im Snapshot: $hardlink_details->{intra_snapshot_aliases}.";
    } else { $hardlink_details = {}; }
    my $data = {
      status => $status,
      checked_at => scalar localtime(),
      checks => [
        { name => "manifest.json vorhanden", ok => $bool->($manifest_ok) },
        { name => "rootfs vorhanden", ok => $bool->($rootfs_ok) },
        { name => "/etc vorhanden", ok => $bool->($etc_ok) },
        { name => "/opt/loxberry vorhanden", ok => $bool->($loxberry_ok) },
        { name => "/var/lib vorhanden", ok => $bool->($varlib_ok) },
        { name => "/mnt/docker vorhanden", ok => $bool->($mntdocker_ok), optional => JSON::PP::true },
        { name => "Snapshot-Hardlinks", ok => $bool->($hardlink_ok), value => $hardlink_value, statistics => $hardlink_details, optional => JSON::PP::true, informational => JSON::PP::true },
        { name => "Backup-Groesse plausibel", ok => $bool->($size_ok), value => $size_bytes },
        { name => "Dateianzahl plausibel", ok => $bool->($files_ok), value => $files_count },
        { name => "Metadaten-Fidelitaet", ok => $bool->($metadata_ok), value => $metadata_value, mode => $metadata_mode, informational => $bool->($metadata_informational) },
      ],
    };
    my ($fh, $tmp) = tempfile(".validation-XXXXXX", DIR => dirname($file), UNLINK => 0);
    chmod 0600, $tmp;
    print $fh JSON::PP->new->ascii->canonical->pretty->encode($data) or die $!;
    $fh->flush or die $!;
    close $fh or die $!;
    rename $tmp, $file or die $!;
  ' "$validation_file" "$status" "$manifest_ok" "$rootfs_ok" "$etc_ok" "$loxberry_ok" "$varlib_ok" "$mntdocker_ok" "$hardlink_ok" "$hardlink_value" "$size_ok" "$files_ok" "$size_bytes" "$files_count" "$metadata_ok" "$metadata_value" "$metadata_mode_value" "$metadata_informational"

  log "Backup validation status: $status"
  case "$status" in
    ok) return 0 ;;
    warning) return 1 ;;
    *) return 2 ;;
  esac
}

snapshot_reference_stats() {
  local snapshot="$1" reference="$2"
  [ -d "$snapshot" ] && [ ! -L "$snapshot" ] && [ -d "$reference" ] && [ ! -L "$reference" ] || return 1
  perl -MFile::Find -MJSON::PP -e '
    my ($snapshot, $reference) = @ARGV;
    my ($checked, $reused, $linked, $aliases) = (0, 0, 0, 0);
    my %inodes;
    find({no_chdir => 1, wanted => sub {
      my $path = $File::Find::name;
      my @current = lstat($path); die "Cannot inspect snapshot path: $!\n" unless @current;
      return unless -f _ && !-l _;
      $checked++; $linked++ if $current[3] > 1;
      $aliases++ if $inodes{"$current[0]:$current[1]"}++;
      my $relative = substr($path, length($snapshot) + 1);
      my @previous = lstat("$reference/$relative");
      if (@previous && -f _ && !-l _ && $current[0] == $previous[0] && $current[1] == $previous[1]) { $reused++; }
    }}, $snapshot);
    print JSON::PP->new->canonical->encode({files_checked => $checked, reference_reused_files => $reused, files_with_multiple_links => $linked, intra_snapshot_aliases => $aliases});
  ' "$snapshot" "$reference"
}

manifest_started_at() {
  local target="$1"
  local manifest="$target/manifest.json"
  [ -r "$manifest" ] || return 0
  perl -MJSON::PP -e '
    local $/;
    open my $fh, "<", $ARGV[0] or exit 0;
    my $data = eval { decode_json(<$fh>) } || {};
    print $data->{started_at} if defined $data->{started_at};
  ' "$manifest" 2>/dev/null || true
}

latest_complete_backup() {
  local root="$1"
  local current_id="${2:-}"
  local tmp id path _time status validation previous_mode current_mode
  current_mode="$(metadata_mode)"
  tmp="$(mktemp)"
  find "$root" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f %p\n' > "$tmp" 2>/dev/null || true
  sort -rn "$tmp" -o "$tmp"
  while read -r _time id path; do
    [ "$id" != "$current_id" ] || continue
    [ -d "$path/rootfs" ] && [ ! -L "$path/rootfs" ] || continue
    status="$(manifest_field "$path/manifest.json" status 2>/dev/null || true)"
    validation="$(manifest_field "$path/backup-validation.json" status 2>/dev/null || true)"
    previous_mode="$(manifest_field "$path/manifest.json" metadata.mode 2>/dev/null || true)"
    [ "$previous_mode" = "$current_mode" ] || continue
    if ! { [ "$status" = "complete" ] && [ "$validation" = "ok" ]; } \
      && ! { [ "$status" = "complete_with_warnings" ] && [ "$validation" = "warning" ] && [ "$previous_mode" = "network-compatible" ]; }; then
      continue
    fi
    rm -f "$tmp"
    printf '%s\n' "$path"
    return 0
  done < "$tmp"
  rm -f "$tmp"
}

latest_sized_complete_backup() {
  local root="$1"
  local current_id="${2:-}"
  local tmp id path _time status size_bytes
  tmp="$(mktemp)"
  find "$root" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f %p\n' > "$tmp" 2>/dev/null || true
  sort -rn "$tmp" -o "$tmp"
  while read -r _time id path; do
    [ "$id" != "$current_id" ] || continue
    if ! { [ -d "$path/rootfs" ] && [ ! -L "$path/rootfs" ]; } \
      && ! { [ -f "$path/rootfs.tar" ] && [ ! -L "$path/rootfs.tar" ]; }; then
      continue
    fi
    status="$(manifest_field "$path/manifest.json" status 2>/dev/null || true)"
    case "$status" in
      complete|complete_with_warnings) ;;
      *) continue ;;
    esac
    size_bytes="$(manifest_field "$path/manifest.json" size_bytes 2>/dev/null || true)"
    printf '%s\n' "$size_bytes" | grep -Eq '^[1-9][0-9]*$' || continue
    rm -f "$tmp"
    printf '%s\n' "$path"
    return 0
  done < "$tmp"
  rm -f "$tmp"
}

baseline_space_requirement_mb() {
  perl -e '
    my $bytes = shift // 0;
    exit 1 unless $bytes =~ /^\d+$/ && $bytes > 0;
    my $mib = 1024 * 1024;
    my $estimate = int(($bytes + $mib - 1) / $mib);
    my $reserve = int(($estimate + 4) / 5);
    $reserve = 1024 if $reserve < 1024;
    print "$estimate ", $estimate + $reserve, "\n";
  ' "$1"
}

preflight_backup() {
  local root available_mb docker_available docker_running excludes_count status warnings_json notices_json checks_json rsync_available target_writable backup_mode fs_type mode probe_ok target_ok target_message copy_tool_name
  local full_baseline_required baseline_estimate_mb baseline_required_mb baseline_space_ok baseline_reference estimate_backup estimate_bytes baseline_check_value available_inodes
  local -a notices=()
  local source_json source_ok=true source_message="" repository_ok=true repository_message="" repository_status repository_lineage
  METADATA_PROBE_JSON='{}'
  METADATA_PROBE_MESSAGE=""
  require_root_permission_ack
  root="$(backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  mode="$(metadata_mode)"
  if portable_snapshot; then
    repository_ok=false
    repository_message="Portable Sicherungsstaende: Repository einrichten, Wiederherstellungsschluessel herunterladen und extern aufbewahren."
    if repository_status="$(portable_helper status 2>/dev/null)" && printf '%s' "$repository_status" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("initialized") and d.get("key_confirmed") and d.get("available") else 1)'; then
      repository_ok=true
      repository_message="Repository und externe Schluesselbestaetigung vorhanden."
    fi
    notices+=("Portable Sicherungsstaende teilen Datenbloecke im Repository. Einzelne Stand-Verzeichnisse sind kein eigenstaendiges Backup. Wiederherstellungsschluessel und gesamtes Repository aufbewahren.")
  fi
  target_ok=false
  target_message=""
  if [ -z "$(json_get_string backup_root)" ]; then
    target_message="Kein Backup-Ziel gespeichert. Bitte ein separates Backup-Ziel festlegen und Einstellungen speichern."
  elif target_message="$(verify_backup_target "$root" true 2>&1)"; then
    target_ok=true
  fi
  if ! source_json="$(source_info)"; then source_ok=false; fi
  if ! source_message="$(printf '%s' "$source_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("; ".join(d.get("errors",[]))); sys.exit(0 if d.get("status")=="ok" else 1)')"; then
    source_ok=false
    [ -n "$source_message" ] || source_message="Datenquellen konnten nicht sicher ermittelt werden."
    source_json="{\"status\":\"error\",\"errors\":[$(json_escape "$source_message")]}"
  fi
  if [ "$source_ok" = true ]; then
    while IFS= read -r notice; do notices+=("$notice"); done < <(printf '%s' "$source_json" | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin).get("notices",[])))')
  fi
  available_mb="$(df -Pm "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  available_inodes="$(df -Pi "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  case "$available_inodes" in ''|*[!0-9]*) available_inodes=-1 ;; esac
  fs_type="$(current_mount_value "$root" FSTYPE)"
  case "$available_mb" in
    ''|*[!0-9]*) available_mb=0 ;;
  esac
  full_baseline_required=false
  baseline_estimate_mb=0
  baseline_required_mb=0
  baseline_space_ok=true
  baseline_reference=""
  baseline_check_value="nicht erforderlich"
  if [ "$target_ok" = "true" ]; then
    if [ "$backup_mode" = "snapshot" ] && [ "$mode" != "portable-archive" ]; then
      baseline_reference="$(latest_complete_backup "$root")"
    elif portable_snapshot && [ "$repository_ok" = true ] && [ "$source_ok" = true ]; then
      repository_lineage="$(printf '%s' "$source_json" | python3 -c 'import hashlib,json,sys; d=json.load(sys.stdin); print(hashlib.sha256(json.dumps(d["selection"],sort_keys=True).encode()).hexdigest())')"
      baseline_reference="$(portable_helper parent --lineage "$repository_lineage" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("backup_id") or "")')" || baseline_reference=""
    fi
    if [ -z "$baseline_reference" ]; then
      full_baseline_required=true
      baseline_check_value="vollstaendige Basiskopie; Groessenschaetzung nicht verfuegbar"
      estimate_backup="$(latest_sized_complete_backup "$root")"
      if [ -n "$estimate_backup" ]; then
        estimate_bytes="$(manifest_field "$estimate_backup/manifest.json" size_bytes 2>/dev/null || true)"
        if read -r baseline_estimate_mb baseline_required_mb < <(baseline_space_requirement_mb "$estimate_bytes"); then
          baseline_check_value="vollstaendige Basiskopie; Schaetzung ${baseline_estimate_mb} MB; mit Reserve mindestens ${baseline_required_mb} MB"
          if [ "$available_mb" -lt "$baseline_required_mb" ]; then
            baseline_space_ok=false
          fi
        fi
      fi
      if [ "$backup_mode" = snapshot ]; then
        notices+=("Hinweis: Keine kompatible Snapshot-Referenz vorhanden. Der naechste Lauf erstellt eine vollstaendige Basiskopie.")
      fi
      if [ "$baseline_estimate_mb" -eq 0 ]; then
        notices+=("Hinweis: Fuer diese vollstaendige Kopie ist noch keine verlaessliche Groessenschaetzung vorhanden. Bitte genuegend freien Platz fuer alle eingeschlossenen Daten vorsehen.")
      fi
    else
      baseline_check_value="inkrementelle Referenz vorhanden: $(basename -- "$baseline_reference")"
    fi
  fi
  notices+=("Hinweis: Die Speicherpruefung ist eine Schaetzung aus frueheren Sicherungen. Zusaetzliche Quelldaten, Inodes, Benutzer-/NAS-Quoten und Aenderungen waehrend des Backups koennen den tatsaechlich benoetigten Platz beeinflussen.")
  rsync_available=false
  copy_tool_name="rsync"
  if [ "$mode" = "portable-archive" ]; then
    copy_tool_name="tar"
    command -v tar >/dev/null 2>&1 && rsync_available=true
    if portable_snapshot; then
      copy_tool_name="Restic (gepruefte Laufzeit)"
      rsync_available=false
      [ -x "$LBP_BINDIR/restic" ] && rsync_available=true
    fi
  else
    command -v rsync >/dev/null 2>&1 && rsync_available=true
  fi
  target_writable=$target_ok
  docker_available=false
  docker_running=0
  if command -v docker >/dev/null 2>&1; then
    docker_available=true
    docker_running="$(docker ps -q 2>/dev/null | wc -l | tr -d ' ')"
  fi
  excludes_count="$(backup_excludes "$root" | wc -l | tr -d ' ')"
  status="ok"
  warnings_json="[]"
  notices_json="[]"
  probe_ok=false
  if [ "$target_ok" = "true" ] && [ "$repository_ok" = true ] && metadata_capability_probe "$root" "$mode"; then
    probe_ok=true
  fi
  if portable_snapshot && [ "$(json_get_bool create_export_after_backup)" = true ]; then
    status="error"
    warnings_json='["Automatischen tar.gz-Export fuer portable Sicherungsstaende bewusst deaktivieren. Fuer ein eigenstaendiges TAR weiterhin Portable Sicherung mit Vollbackup verwenden; bestehende Vollarchive bleiben unveraendert."]'
  elif [ "$repository_ok" != true ]; then
    status="error"
    warnings_json="[$(json_escape "$repository_message")]"
  elif [ "$source_ok" != true ]; then
    status="error"
    warnings_json="[$(json_escape "$source_message")]"
  elif [ "$rsync_available" != "true" ] || [ "$target_writable" != "true" ] || [ "$probe_ok" != "true" ]; then
    status="error"
    warnings_json="$(perl -MJSON::PP -e 'print encode_json([$ARGV[0]])' "${target_message:-${METADATA_PROBE_MESSAGE:-Pflichtcheck fehlgeschlagen: rsync, Zielidentitaet, Schreibzugriff oder Metadatenprobe.}}")"
  elif [ "$available_inodes" -eq 0 ]; then
    status="error"
    warnings_json='["Auf dem Backup-Ziel sind keine freien Inodes mehr verfuegbar. Neue Dateien koennen nicht angelegt werden."]'
  elif [ "$baseline_space_ok" != "true" ]; then
    status="error"
    warnings_json="$(perl -MJSON::PP -e 'print encode_json([$ARGV[0]])' "Vollstaendige Basiskopie benoetigt voraussichtlich mindestens ${baseline_required_mb} MB, auf dem Backup-Ziel sind aber nur ${available_mb} MB frei. Bitte unvollstaendige oder nicht mehr benoetigte Backups loeschen beziehungsweise das Ziel vergroessern.")"
  elif [ "$available_mb" -lt 1024 ]; then
    status="warning"
    warnings_json='["Backup-Ziel hat weniger als 1 GB freien Speicher."]'
  elif [ "$docker_running" -gt 0 ] && [ "$(json_get_bool stop_docker_before_backup)" != "true" ] && [ "$(selected_docker_stop_count)" -eq 0 ]; then
    status="warning"
    warnings_json='["Docker-Container laufen. Fuer konsistente Datenbanken ggf. einzelne Container in den Stop-Zielen auswaehlen oder Hooks konfigurieren."]'
  fi
  if [ "$mode" = "network-compatible" ]; then
    notices+=("Hinweis: Network Compatible laesst xattrs und File Capabilities bewusst aus. Dies ist der konfigurierte Normalbetrieb fuer CIFS-/NFS-Ziele und behindert den Backup-Start nicht.")
  fi
  notices_json="$(perl -MJSON::PP -e 'print encode_json(\@ARGV)' "${notices[@]}")"
  checks_json="$(cat <<EOF
[
  {"name":"Kopierwerkzeug ($copy_tool_name) verfuegbar","ok":$rsync_available},
  {"name":"Backup-Ziel beschreibbar","ok":$target_writable},
  {"name":"Backup-Modus","ok":true,"value":"$backup_mode"},
  {"name":"Metadaten-Modus","ok":$probe_ok,"value":"$mode","details":$(json_escape "${METADATA_PROBE_MESSAGE:-}")},
  {"name":"Portable Repository und Wiederherstellungsschluessel","ok":$repository_ok,"details":$(json_escape "$repository_message")},
  {"name":"Datenquellen-Auswahl","ok":$source_ok,"details":$(json_escape "$source_message")},
  {"name":"Dateisystem","ok":true,"value":"$fs_type"},
  {"name":"Freier Speicher MB","ok":$([ "$available_mb" -ge 1024 ] && echo true || echo false),"value":"$available_mb"},
  {"name":"Speicher fuer Snapshot-Basiskopie","ok":$baseline_space_ok,"value":$(json_escape "$baseline_check_value")},
  {"name":"Freie Inodes","ok":$([ "$available_inodes" -ne 0 ] && echo true || echo false),"value":"$available_inodes (-1: unbekannt)"},
  {"name":"Docker verfuegbar","ok":$docker_available,"value":"running=$docker_running"},
  {"name":"Exclude-Regeln","ok":true,"value":"$excludes_count"}
]
EOF
)"
  cat <<EOF
{
  "kind": "backup",
  "status": "$status",
  "backup_root": $(json_escape "$root"),
  "available_mb": $available_mb,
  "full_baseline_required": $full_baseline_required,
  "baseline_estimate_mb": $baseline_estimate_mb,
  "baseline_required_mb": $baseline_required_mb,
  "warnings": $warnings_json,
  "notices": $notices_json,
  "checks": $checks_json,
  "metadata_probe": $METADATA_PROBE_JSON,
  "source_selection": $source_json
}
EOF
}

restore_eligibility() {
  local backup_id="$1" degraded_confirmation="${2:-false}"
  local root target manifest_status validation_status metadata_value storage_format
  local inspection_json inspection_status inspection_mode
  root="$(backup_root)"
  verify_backup_target "$root" false
  target="$(safe_backup_target "$root" "$backup_id")"
  manifest_status="$(manifest_field "$target/manifest.json" status 2>/dev/null || true)"
  validation_status="$(manifest_field "$target/backup-validation.json" status 2>/dev/null || true)"
  metadata_value="$(manifest_field "$target/manifest.json" metadata.mode 2>/dev/null || true)"
  storage_format="$(manifest_field "$target/manifest.json" backup.storage_format 2>/dev/null || true)"
  case "$manifest_status:$validation_status" in
    complete:ok) ;;
    complete_with_warnings:warning)
      [ "$degraded_confirmation" = "confirm-degraded" ] || { echo "Backup ist eingeschraenkt und benoetigt eine separate Bestaetigung." >&2; return 18; }
      ;;
    *) echo "Backup ist nicht vollstaendig und erfolgreich validiert." >&2; return 18 ;;
  esac
  if [ "$metadata_value" = "network-compatible" ]; then
    [ "$degraded_confirmation" = "confirm-degraded" ] || { echo "Hinweis zu reduzierten Metadaten muss vor dem Restore separat bestaetigt werden." >&2; return 18; }
  fi
  if [ "$storage_format" = "portable-tar" ] || [ "$metadata_value" = "portable-archive" ]; then
    if [ "$storage_format" = portable-repository ]; then
      echo "Portable Sicherungsstaende nur offline aus dem authentifizierten Repository wiederherstellen. Siehe docs/PORTABLE-REPOSITORY.md und repository-stage." >&2
      return 18
    fi
    [ -f "$target/rootfs.tar" ] && [ ! -L "$target/rootfs.tar" ] || { echo "Portable rootfs archive is missing." >&2; return 18; }
    [ "${HOSTBACKUP_OFFLINE_RESTORE:-0}" = "1" ] || { echo "Portable Archive Restore ist nur mit HOSTBACKUP_OFFLINE_RESTORE=1 in einer Offline-/Rescue-Umgebung erlaubt." >&2; return 18; }
  else
    perl -e 'exit((-d $ARGV[0] && !-l $ARGV[0]) ? 0 : 1)' "$target/rootfs" || { echo "Backup rootfs is not a real directory." >&2; return 18; }
  fi
  inspection_json="$(inspect_backup_directory "$target")" || return 18
  if ! read -r inspection_status inspection_mode < <(printf '%s' "$inspection_json" | perl -MJSON::PP -e 'local $/; my $d=decode_json(<STDIN>); print(($d->{status} // "error"), " ", ($d->{metadata_mode} // "legacy-unknown"), "\n");'); then
    echo "Lokale Inhaltspruefung lieferte kein gueltiges Ergebnis." >&2; return 18
  fi
  case "$inspection_status" in
    ok) ;;
    warning)
      [ "$degraded_confirmation" = confirm-degraded ] || { echo "Lokale Inhaltspruefung meldet Einschraenkungen. Restore erfordert confirm-degraded." >&2; return 18; }
      ;;
    *) echo "Lokale Inhaltspruefung hat den Restore nicht freigegeben." >&2; return 18 ;;
  esac
  if [ "$inspection_mode" = legacy-unknown ] && [ "$degraded_confirmation" != confirm-degraded ]; then
    echo "Lokale Inhaltspruefung kann das alte Metadaten-Profil nicht bestaetigen." >&2; return 18
  fi
  printf '%s\n' "$target"
}

preflight_restore() {
  local backup_id="$1"
  local root target status warnings_json notices_json backup_arch host_arch_value backup_status rsync_available validation_status metadata_value storage_format data_ok copy_tool_name requires_degraded=false requires_offline=false
  require_root_permission_ack
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  target="$(safe_backup_target "$root" "$backup_id")"
  host_arch_value="$(host_arch)"
  backup_arch="$(perl -MJSON::PP -e 'local $/; open my $fh,"<",$ARGV[0] or exit 0; my $d=eval{decode_json(<$fh>)}||{}; print $d->{host}{architecture} // "";' "$target/manifest.json" 2>/dev/null || true)"
  backup_status="$(perl -MJSON::PP -e 'local $/; open my $fh,"<",$ARGV[0] or exit 0; my $d=eval{decode_json(<$fh>)}||{}; print $d->{status} // "";' "$target/manifest.json" 2>/dev/null || true)"
  validation_status="$(manifest_field "$target/backup-validation.json" status 2>/dev/null || true)"
  metadata_value="$(manifest_field "$target/manifest.json" metadata.mode 2>/dev/null || true)"
  storage_format="$(manifest_field "$target/manifest.json" backup.storage_format 2>/dev/null || true)"
  rsync_available=false
  copy_tool_name="rsync"
  data_ok=false
  if [ "$storage_format" = portable-repository ]; then
    copy_tool_name="Restic + Linux-Staging"
    [ -x "$LBP_BINDIR/restic" ] && rsync_available=true
    if maintenance_helper repository-check "$root" "$backup_id" >/dev/null; then data_ok=true; fi
  elif [ "$storage_format" = "portable-tar" ]; then
    copy_tool_name="tar"
    command -v tar >/dev/null 2>&1 && rsync_available=true
    [ -f "$target/rootfs.tar" ] && [ ! -L "$target/rootfs.tar" ] && data_ok=true
  else
    command -v rsync >/dev/null 2>&1 && rsync_available=true
    [ -d "$target/rootfs" ] && [ ! -L "$target/rootfs" ] && data_ok=true
  fi
  status="ok"
  warnings_json="[]"
  notices_json="[]"
  if [ "$rsync_available" != "true" ] || [ "$data_ok" != "true" ]; then
    status="error"
    warnings_json='["Pflichtcheck fehlgeschlagen: Kopierwerkzeug oder Backup-Daten fehlen."]'
  elif [ "$backup_status" != "complete" ] || [ "$validation_status" != "ok" ]; then
    if [ "$backup_status" = "complete_with_warnings" ] && [ "$validation_status" = "warning" ]; then
      status="warning"
      requires_degraded=true
      warnings_json='["Backup wurde mit eingeschraenkter Metadaten-Fidelitaet abgeschlossen und muss separat bestaetigt werden."]'
    else
      status="error"
      warnings_json='["Backup ist nicht vollstaendig und erfolgreich validiert."]'
    fi
  elif [ "$storage_format" = portable-repository ]; then
    status="warning"
    requires_offline=true
    warnings_json='["Portable Sicherungsstaende benoetigen Wiederherstellungsschluessel und ausreichend leeres Linux-Staging. Nur Offline-Recovery; siehe PORTABLE-REPOSITORY.md. Kein automatischer Wechsel zwischen x86 und ARM."]'
  elif [ "$storage_format" = "portable-tar" ]; then
    status="warning"
    requires_offline=true
    warnings_json='["Portable Archive darf nur aus einer Offline-/Rescue-Umgebung mit HOSTBACKUP_OFFLINE_RESTORE=1 wiederhergestellt werden."]'
  elif [ -n "$backup_arch" ] && [ "$backup_arch" != "$host_arch_value" ]; then
    status="warning"
    warnings_json='["Backup-Architektur unterscheidet sich vom Zielsystem."]'
  fi
  if [ "$metadata_value" = "network-compatible" ]; then
    requires_degraded=true
    notices_json='["Network Compatible: xattrs und File Capabilities sind absichtlich nicht enthalten. Vor dem Restore ist eine bewusste Bestaetigung erforderlich."]'
  fi
  cat <<EOF
{
  "kind": "restore",
  "status": "$status",
  "backup_id": $(json_escape "$backup_id"),
  "backup_path": $(json_escape "$target"),
  "warnings": $warnings_json,
  "notices": $notices_json,
  "checks": [
    {"name":"Kopierwerkzeug ($copy_tool_name) verfuegbar","ok":$rsync_available},
    {"name":"Backup-Daten vorhanden","ok":$data_ok},
    {"name":"Backup vollstaendig","ok":$([ "$backup_status" = "complete" ] || [ "$backup_status" = "complete_with_warnings" ] && echo true || echo false),"value":$(json_escape "$backup_status")},
    {"name":"Validierung","ok":$([ "$validation_status" = "ok" ] || [ "$validation_status" = "warning" ] && echo true || echo false),"value":$(json_escape "$validation_status")},
    {"name":"Metadaten-Modus","ok":true,"value":$(json_escape "$metadata_value")},
    {"name":"Architektur passend","ok":$([ -z "$backup_arch" ] || [ "$backup_arch" = "$host_arch_value" ] && echo true || echo false),"value":$(json_escape "$backup_arch -> $host_arch_value")}
  ],
  "requires_degraded_confirmation": $requires_degraded,
  "requires_offline_restore": $requires_offline
}
EOF
}

create_backup() {
  require_root_for_write
  require_root_permission_ack

  local root backup_id target rootfs log_file started finished size files exclude_file backup_mode previous_backup
  local mode task validation_status final_status post_hook pre_hook rsync_status export_status portable_excludes state_dir preflight_json preflight_status cleanup_trap
  local source_list="" selection_active=false source_plan_json repository_candidate="" repository_validation="" lineage=""
  local control_dir="" source_report=""
  local -a rsync_opts=() metadata_opts=() tar_opts=()
  root="$(backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  mode="$(metadata_mode)"
  if [ "$mode" = "portable-archive" ]; then
    command -v tar >/dev/null 2>&1 || { echo "tar is required." >&2; exit 3; }
  else
    command -v rsync >/dev/null 2>&1 || { echo "rsync is required." >&2; exit 3; }
  fi
  verify_backup_target "$root" true
  backup_id="${1:-$(date '+%Y%m%d-%H%M%S')}"
  backup_id="$(printf '%s' "$backup_id" | tr -cd 'A-Za-z0-9._-')"
  require_backup_id "$backup_id"
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  target="$(strict_child_path "$root" "$root/$backup_id")" || { echo "Unsafe backup target." >&2; exit 7; }
  rootfs="$target/rootfs"
  log_file="$TASK_LOG_DIR/backup-$backup_id.log"
  task="backup-$backup_id.log"
  exclude_file="$target/rsync-excludes.txt"

  if [ -e "$target" ]; then
    echo "Backup already exists: $backup_id" >&2
    exit 4
  fi

  prepare_log_file "$log_file" append
  if ! preflight_json="$(preflight_backup 2>&1)"; then
    printf '%s\n' "$preflight_json" >> "$log_file"
    task_state_write "$task" failed preflight_error "$log_file" 0 17
    return 17
  fi
  preflight_status="$(printf '%s' "$preflight_json" | perl -MJSON::PP -e 'local $/; my $d=decode_json(<STDIN>); print $d->{status} // "error";')" || preflight_status=error
  if [ "$preflight_status" = error ]; then
    printf '%s\n' "$preflight_json" >> "$log_file"
    task_state_write "$task" failed preflight_error "$log_file" 0 17
    return 17
  fi
  mkdir -p -- "$target"
  chmod 700 "$target" 2>/dev/null || true
  write_backup_marker "$target" "$backup_id"
  if [ "$mode" != "portable-archive" ]; then
    mkdir -p -- "$rootfs"
  fi
  started="$(date -Iseconds)"
  backup_excludes "$root" > "$exclude_file"
  write_manifest "$target" "$backup_id" "running" "$started" "" 0 0

  pre_hook="$(json_get_string pre_backup_hook)"
  post_hook="$(json_get_string post_backup_hook)"
  # Referenced from the frozen EXIT trap.
  # shellcheck disable=SC2034
  HB_BACKUP_RESTART_DONE=false
  task_state_write "$task" running initializing "$log_file" "$$" ""
  state_dir="$(restart_journal_create "$task")"
  control_dir="$target"
  if portable_snapshot; then
    control_dir="$state_dir/repository-controls"
    mkdir -m 700 -- "$control_dir"
    exclude_file="$control_dir/rsync-excludes.txt"
    (umask 077; backup_excludes "$root" > "$exclude_file")
    (umask 077; write_manifest "$control_dir" "$backup_id" running "$started" "" 0 0)
  fi
  source_report="$control_dir/source-selection.json"
  # Errexit can unwind function locals before EXIT executes. Freeze paths now.
  printf -v cleanup_trap 'HB_BACKUP_EXIT_STATUS=$?; trap - EXIT; backup_cleanup_on_exit "$HB_BACKUP_EXIT_STATUS" %q %q "${HB_BACKUP_RESTART_DONE:-false}" %q %q %q || { [ "$HB_BACKUP_EXIT_STATUS" -ne 0 ] || HB_BACKUP_EXIT_STATUS=20; }; exit "$HB_BACKUP_EXIT_STATUS"' "$target" "$log_file" "$post_hook" "$task" "$state_dir"
  # Intentionally freeze shell-quoted cleanup arguments.
  # shellcheck disable=SC2064
  trap "$cleanup_trap" EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  log "Starting backup $backup_id" | tee -a "$log_file"
  log "Backup mode: $backup_mode" | tee -a "$log_file"
  log "Metadata mode: $mode" | tee -a "$log_file"
  log "Backup target: $target" | tee -a "$log_file"
  log "Root filesystem copy target: $rootfs" | tee -a "$log_file"
  log "Exclude rules written to: $exclude_file" | tee -a "$log_file"
  log "Running pre-backup hook if configured" | tee -a "$log_file"
  task_state_write "$task" running pre_hook "$log_file" "$$" ""
  run_hook "$pre_hook" 2>&1 | tee -a "$log_file"
  log "Stopping selected services and Docker containers if configured" | tee -a "$log_file"
  task_state_write "$task" running stopping_services "$log_file" "$$" ""
  stop_backup_targets "$state_dir" 2>&1 | tee -a "$log_file"

  # Enumerate only after services are quiesced, so newly created database files
  # are not missed. Any enumeration failure uses the normal restart EXIT trap.
  source_plan_json="$(source_info)" || return 18
  selection_active="$(printf '%s' "$source_plan_json" | python3 -c 'import json,sys; s=json.load(sys.stdin)["selection"]; print("true" if s["policy"] != "legacy" or s["overrides"] else "false")')"
  local -a source_options=()
  if portable_snapshot; then selection_active=true; source_options+=(--omit-sockets); fi
  if [ "$selection_active" = true ]; then
    task_state_write "$task" running selecting_sources "$log_file" "$$" ""
    log "Preparing explicit file list for selected local volumes and network shares" | tee -a "$log_file"
    source_list="$state_dir/source-files.nul"
    (umask 077; set -o noclobber; python3 "$LBP_BINDIR/hostbackup-sources.py" files --config "$CONFIG_FILE" --excludes "$exclude_file" --report "$source_report" "${source_options[@]}" > "$source_list") 2>> "$log_file" || return 18
    [ -s "$source_list" ] || { log "ERROR: Source file list is empty" | tee -a "$log_file"; return 18; }
    if portable_snapshot; then
      python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); s=d.get("omitted_runtime_sockets",{}); print("Portable source selection: %s transient Unix sockets omitted (IPC endpoints, not persistent files); details in source-selection.json." % s.get("count",0))' "$source_report" | tee -a "$log_file"
    fi
  fi

  while IFS= read -r opt; do
    rsync_opts+=("$opt")
  done < <(rsync_live_options)
  while IFS= read -r opt; do
    metadata_opts+=("$opt")
  done < <(rsync_metadata_options "$mode" backup)

  if [ "$backup_mode" = "snapshot" ] && [ "$mode" != "portable-archive" ]; then
    previous_backup="$(latest_complete_backup "$root" "$backup_id")"
    if [ -n "$previous_backup" ] && [ -d "$previous_backup/rootfs" ]; then
      rsync_opts+=(--link-dest="$previous_backup/rootfs")
      log "Snapshot reference: $previous_backup/rootfs" | tee -a "$log_file"
    else
      log "No complete previous backup found. Creating first snapshot as full copy." | tee -a "$log_file"
    fi
  fi

  task_state_write "$task" running copying "$log_file" "$$" ""
  set +e
  if portable_snapshot; then
    repository_candidate="$state_dir/repository-candidate.json"
    lineage="$(printf '%s' "$source_plan_json" | python3 -c 'import hashlib,json,sys; d=json.load(sys.stdin); print(hashlib.sha256(json.dumps(d["selection"],sort_keys=True).encode()).hexdigest())')"
    log "Creating portable repository snapshot; unchanged data blocks are reused" | tee -a "$log_file"
    (umask 077; repository_helper backup --backup-id "$backup_id" --files-from "$source_list" --lineage "$lineage" > "$repository_candidate") 2>> "$log_file"
    rsync_status=$?
    # stdout is a bounded machine receipt, not progress or secret material.
    [ "$rsync_status" -ne 0 ] || python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps(d["summary"]))' "$repository_candidate" | tee -a "$log_file"
  elif [ "$mode" = "portable-archive" ]; then
    portable_excludes="$target/tar-excludes.txt"
    sed 's#^/##; /^$/d' "$exclude_file" > "$portable_excludes"
    while IFS= read -r opt; do tar_opts+=("$opt"); done < <(tar_metadata_options)
    log "Creating portable root filesystem archive" | tee -a "$log_file"
    if [ "$selection_active" = true ]; then
      tar "${tar_opts[@]}" -C / -cpf "$target/rootfs.tar" --no-recursion --null --verbatim-files-from --files-from="$source_list" 2>&1 | tee -a "$log_file"
      rsync_status=${PIPESTATUS[0]}
    else
      tar "${tar_opts[@]}" --exclude-from="$portable_excludes" -C / -cpf "$target/rootfs.tar" . 2>&1 | tee -a "$log_file"
      rsync_status=${PIPESTATUS[0]}
    fi
  else
    log "Starting rsync copy from / to $rootfs" | tee -a "$log_file"
    log "rsync live output follows. Large files or slow storage can keep one line active for a while." | tee -a "$log_file"
    if [ "$selection_active" = true ]; then
      rsync_opts+=(--from0 --files-from="$source_list" --no-recursive --dirs)
    fi
    rsync "${metadata_opts[@]}" --delete "${rsync_opts[@]}" --exclude-from="$exclude_file" / "$(rsync_destination "$mode" "$rootfs/")" 2>&1 | tee -a "$log_file"
    rsync_status=${PIPESTATUS[0]}
  fi
  set -e
  # Docker/service restart can legitimately change mounts, so verify the source
  # snapshot now, while the quiesced source state is still expected to match.
  if [ "$selection_active" = true ] && ! python3 "$LBP_BINDIR/hostbackup-sources.py" verify --report "$source_report" >> "$log_file" 2>&1; then
    log "ERROR: Source mounts changed during the copy; backup cannot be accepted" | tee -a "$log_file"
    rsync_status=18
  fi
  log "Backup copy finished with status $rsync_status" | tee -a "$log_file"
  log "Starting services and Docker containers again if they were stopped" | tee -a "$log_file"
  task_state_write "$task" running restarting_services "$log_file" "$$" ""
  start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file"
  # Referenced from the frozen EXIT trap.
  # shellcheck disable=SC2034
  HB_BACKUP_RESTART_DONE=true
  write_control_marker "$state_dir/restart.done"
  log "Running post-backup hook if configured" | tee -a "$log_file"
  task_state_write "$task" running post_hook "$log_file" "$$" ""
  write_control_marker "$state_dir/post-hook.started"
  run_hook "$post_hook" 2>&1 | tee -a "$log_file"
  write_control_marker "$state_dir/post-hook.done"
  verify_backup_target "$root" true

  log "Calculating backup size and file count" | tee -a "$log_file"
  finished="$(date -Iseconds)"
  size="$(calculate_size "$target")"
  files="$(calculate_files "$target")"

  if [ "$rsync_status" -eq 0 ] || [ "$rsync_status" -eq 24 ]; then
    log "Root filesystem copy for backup $backup_id finished" | tee -a "$log_file"
  else
    write_manifest "$target" "$backup_id" "failed" "$started" "$finished" "$size" "$files"
    log "Backup $backup_id failed with rsync status $rsync_status" | tee -a "$log_file"
    notify_hostbackup "failure" 3 "LoxBerry Host Backup fehlgeschlagen" "Backup $backup_id ist fehlgeschlagen. rsync Status: $rsync_status." "$log_file"
    exit "$rsync_status"
  fi

  finished="$(date -Iseconds)"
  size="$(calculate_size "$target")"
  files="$(calculate_files "$target")"
  write_manifest "$target" "$backup_id" "validating" "$started" "$finished" "$size" "$files"
  log "Checking completed backup" | tee -a "$log_file"
  task_state_write "$task" running validating "$log_file" "$$" ""
  set +e
  if portable_snapshot; then
    repository_validation="$(portable_helper validate-candidate --candidate "$repository_candidate" --controls "$control_dir" --min-files "${HOSTBACKUP_MIN_FILES:-100}" --min-bytes "${HOSTBACKUP_MIN_SIZE_BYTES:-104857600}" 2>> "$log_file")"
    validation_status=$?
    if [ "$validation_status" -eq 0 ]; then
      read -r size files final_status < <(printf '%s' "$repository_validation" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["size_bytes"],d["files_count"],d["status"])')
      [ "$final_status" != warning ] || validation_status=1
    else
      validation_status=2
    fi
    printf '%s\n' "$repository_validation" | tee -a "$log_file"
  else
    validate_completed_backup "$target" "$backup_mode" "${previous_backup:-}" "$size" "$files" "$rsync_status" 2>&1 | tee -a "$log_file"
    validation_status=${PIPESTATUS[0]}
  fi
  set -e
  case "$validation_status" in
    0) final_status="complete" ;;
    1) final_status="complete_with_warnings" ;;
    *)
      write_manifest "$target" "$backup_id" "failed" "$started" "$finished" "$size" "$files"
      log "Backup $backup_id failed validation" | tee -a "$log_file"
      exit 19
      ;;
  esac
  if portable_snapshot; then
    write_manifest "$target" "$backup_id" validating "$started" "$finished" "$size" "$files"
    (umask 077; write_manifest "$control_dir" "$backup_id" validating "$started" "$finished" "$size" "$files")
    verify_backup_target "$root" false
    if ! portable_helper publish --candidate "$repository_candidate" --controls "$control_dir" --destination "$target" >> "$log_file" 2>&1; then
      log "Repository-Commit/cache publication incomplete. Do not delete repository data; inspect authenticated repository." | tee -a "$log_file"
      return 19
    fi
  else
    write_manifest "$target" "$backup_id" "$final_status" "$started" "$finished" "$size" "$files"
  fi

  if [ "$(json_get_bool integrity_enabled)" = true ]; then
    task_state_write "$task" running recording_integrity "$log_file" "$$" ""
    if ! maintenance_helper integrity "$root" "$backup_id" --record 2>&1 | tee -a "$log_file"; then
      log "Inhaltspruef-Basis konnte nicht erstellt werden; Kopierergebnis bleibt erhalten. Pruefbericht kontrollieren." | tee -a "$log_file"
    fi
  fi

  if [ "$(json_get_bool create_export_after_backup)" = "true" ]; then
    log "Creating export archive for finalized backup $backup_id" | tee -a "$log_file"
    set +e
    export_backup "$backup_id" 2>&1 | tee -a "$log_file"
    export_status=${PIPESTATUS[0]}
    set -e
    if [ "$export_status" -ne 0 ]; then
      log "Backup $backup_id failed while creating export archive" | tee -a "$log_file"
      task_state_write "$task" failed export_failed "$log_file" "$$" "$export_status"
      restart_journal_finish "$state_dir"
      trap - EXIT HUP INT TERM
      notify_hostbackup "failure" 3 "LoxBerry Host Backup fehlgeschlagen" "Backup $backup_id ist beim Erstellen des Export-Archivs fehlgeschlagen." "$log_file"
      exit "$export_status"
    fi
  fi

  task_state_write "$task" running retention "$log_file" "$$" ""
  log "Applying backup retention policy" | tee -a "$log_file"
  if ! prune_old_backups 2>&1 | tee -a "$log_file"; then
    log "Aufbewahrung konnte nicht vollstaendig angewendet werden. Backups und Bereinigungsvorschau pruefen." | tee -a "$log_file"
  fi

  log "Backup $backup_id finished" | tee -a "$log_file"
  restart_journal_finish "$state_dir"
  task_state_write "$task" finished complete "$log_file" "$$" 0
  trap - EXIT HUP INT TERM
  notify_hostbackup "success" 6 "LoxBerry Host Backup erfolgreich" "Backup $backup_id wurde erfolgreich abgeschlossen. Groesse: $size Bytes, Dateien: $files." "$log_file"
  printf '%s\n' "$backup_id"
}

start_backup() {
  require_root_for_write
  local backup_id log_file task accept_warnings preflight_json preflight_status pid
  backup_id="${1:-$(date '+%Y%m%d-%H%M%S')-$$}"
  accept_warnings="${2:-}"
  backup_id="$(printf '%s' "$backup_id" | tr -cd 'A-Za-z0-9._-')"
  require_backup_id "$backup_id"
  log_file="$TASK_LOG_DIR/backup-$backup_id.log"
  task="backup-$backup_id.log"
  [ ! -e "$log_file" ] || { echo "Task already exists: $task" >&2; return 4; }
  prepare_log_file "$log_file" truncate
  task_state_write "$task" queued preflight "$log_file" "$$" ""
  if ! acquire_operation_lock exclusive 2>> "$log_file" || ! acquire_backup_lock "$backup_id" exclusive 2>> "$log_file"; then
    log "Backup start rejected: another HostBackup operation is active" >> "$log_file"
    task_state_write "$task" failed busy "$log_file" 0 5
    printf '%s\n' "Backup attempt $backup_id rejected: another operation is active." >&2
    return 5
  fi
  if ! recover_restart_journals >> "$log_file" 2>&1; then
    task_state_write "$task" failed cleanup_failed "$log_file" 0 20
    echo "Pending services could not be restarted. See the retained recovery journal." >&2
    return 20
  fi
  if ! preflight_json="$(preflight_backup 2>&1)"; then
    printf '%s\n' "$preflight_json" >> "$log_file"
    task_state_write "$task" failed preflight_error "$log_file" 0 17
    printf '%s\n' "$preflight_json" >&2
    return 17
  fi
  preflight_status="$(printf '%s' "$preflight_json" | perl -MJSON::PP -e 'local $/; my $d=decode_json(<STDIN>); print $d->{status} // "error";')" || preflight_status=error
  printf '%s\n' "$preflight_json" >> "$log_file"
  case "$preflight_status" in
    ok|warning) ;;
    *) task_state_write "$task" failed preflight_error "$log_file" 0 17; printf '%s\n' "$preflight_json" >&2; return 17 ;;
  esac
  if [ "$preflight_status" = "warning" ] && [ "$accept_warnings" != "accept-warnings" ]; then
    task_state_write "$task" failed preflight_warning "$log_file" 0 16
    printf '%s\n' "$preflight_json" >&2
    echo "Preflight-Warnungen muessen explizit bestaetigt werden." >&2
    return 16
  fi
  if pid="$(launch_background "$task" "$TASK_LOG_DIR/backup-$backup_id.launch.log" "$0" backup "$backup_id")" && [ -n "$pid" ]; then
    :
  else
    task_state_write "$task" failed launch_failed "$log_file" 0 14
    echo "Backup process could not be launched." >&2; return 14
  fi
  printf '%s\n' "$backup_id"
}

stop_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1"
  local root target log_file started finished size files task pid pgid ticks current_ticks waited=0
  local state_dir state manifest_status signalled=false recovery_failed=0
  require_backup_id "$backup_id"
  root="$(backup_root)"
  target="$(strict_child_path "$root" "$root/$backup_id")" || { echo "Unsafe backup path." >&2; exit 7; }
  log_file="$TASK_LOG_DIR/backup-$backup_id.log"
  task="backup-$backup_id.log"
  state_dir="$RESTART_JOURNAL_DIR/$task"
  [ -d "$target" ] || [ -f "$TASK_DIR/$task.json" ] || { echo "Backup task not found: $backup_id" >&2; exit 6; }
  prepare_log_file "$log_file" append

  log "Stop requested for backup $backup_id" | tee -a "$log_file"

  pid="$(task_state_value "$task" pid 2>/dev/null || true)"
  state="$(task_state_value "$task" state 2>/dev/null || true)"
  manifest_status="$(manifest_field "$target/manifest.json" status 2>/dev/null || true)"
  ticks="$(task_state_value "$task" process_start_ticks 2>/dev/null || true)"
  current_ticks="$(process_start_ticks "$pid")"
  if [ "$state" != finished ] && [ "$state" != stopped ] && [ "$manifest_status" != complete ] && [ "$manifest_status" != complete_with_warnings ] && [ -n "$pid" ] && [ "$pid" -gt 1 ] 2>/dev/null && [ -n "$ticks" ] && [ "$ticks" = "$current_ticks" ] && kill -0 "$pid" 2>/dev/null; then
    signalled=true
    pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
    log "Stopping backup process group ${pgid:-$pid}" | tee -a "$log_file"
    if [ -n "$pgid" ] && [ "$pgid" -gt 1 ] 2>/dev/null; then
      kill -TERM -- "-$pgid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    else
      kill -TERM "$pid" 2>/dev/null || true
    fi
    while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt 30 ]; do
      sleep 1
      waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      [ -n "$pgid" ] && kill -KILL -- "-$pgid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  else
    log "No running backup process found for $backup_id" | tee -a "$log_file"
  fi

  acquire_operation_lock exclusive || return $?
  acquire_backup_lock "$backup_id" exclusive || return $?
  state="$(task_state_value "$task" state 2>/dev/null || true)"
  manifest_status="$(manifest_field "$target/manifest.json" status 2>/dev/null || true)"
  if [ "$state" = finished ] || [ "$state" = stopped ] || [ "$manifest_status" = complete ] || [ "$manifest_status" = complete_with_warnings ]; then
    log "Backup $backup_id already completed; stop request has no effect" | tee -a "$log_file"
    return 0
  fi
  if [ -d "$state_dir" ]; then
    log "Restarting services and Docker containers stopped by this backup if needed" | tee -a "$log_file"
    if start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file"; then
      restart_journal_finish "$state_dir" || recovery_failed=1
    else
      recovery_failed=1
    fi
  fi
  if [ "$recovery_failed" -ne 0 ]; then
    task_state_write "$task" failed cleanup_failed "$log_file" 0 20
    return 20
  fi
  if [ "$signalled" != true ]; then
    log "No active process was stopped; preserving the existing task result" | tee -a "$log_file"
    return 0
  fi
  if ! verify_backup_target "$root" false >> "$log_file" 2>&1 || [ ! -f "$target/manifest.json" ]; then
    task_state_write "$task" stopped target_unavailable "$log_file" 0 0
    return 0
  fi
  started="$(manifest_started_at "$target")"
  [ -n "$started" ] || started="$(date -Iseconds)"
  finished="$(date -Iseconds)"
  size="$(manifest_field "$target/manifest.json" size_bytes 2>/dev/null || printf 0)"
  files="$(manifest_field "$target/manifest.json" files_count 2>/dev/null || printf 0)"
  write_manifest "$target" "$backup_id" "stopped" "$started" "$finished" "${size:-0}" "${files:-0}"
  task_state_write "$task" stopped stopped "$log_file" "$$" 0
  log "Backup $backup_id stopped by user" | tee -a "$log_file"
  notify_hostbackup "stopped" 4 "LoxBerry Host Backup abgebrochen" "Backup $backup_id wurde durch den Benutzer abgebrochen. Bereits gestoppte Dienste und Container wurden wieder gestartet, soweit moeglich." "$log_file"
}

log_dirs() {
  printf '%s\n' "$TASK_LOG_DIR"
}

task_log_path() {
  local task="$1"
  local dir path
  case "$task" in
    *[!A-Za-z0-9._-]*|.*|*..*|*/*) echo "Unsafe task id." >&2; exit 11 ;;
    backup-*.log|restore-*.log|export-*.log|import-*.log|verify-*.log) ;;
    *) echo "Unsafe task id." >&2; exit 11 ;;
  esac
  while IFS= read -r dir; do
    path="$dir/$task"
    if [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ]; then
      printf '%s\n' "$path"
      return 0
    fi
  done < <(log_dirs)
  printf '%s/%s\n' "$TASK_LOG_DIR" "$task"
}

list_tasks() {
  local dirs=()
  local dir
  mkdir -p "$TASK_LOG_DIR"
  while IFS= read -r dir; do
    dirs+=("$dir")
  done < <(log_dirs)
  perl -MJSON::PP -e '
    my @dirs = @ARGV;
    my @items;
    my %seen;
    for my $dir (@dirs) {
      next if !$dir || $seen{"dir:$dir"}++;
      opendir(my $dh, $dir) or next;
      for my $name (sort grep { /^(backup|restore|export|import|verify)-.*\.log$/ || /\.(launch)\.log$/ } readdir($dh)) {
        my $path = "$dir/$name";
        my @st = lstat($path);
        next unless @st && -f _ && !-l _;
        my $key = "$name:$st[7]:$st[9]";
        next if $seen{$key}++;
        push @items, { task => $name, size => 0 + $st[7], mtime => 0 + $st[9], path => $path };
      }
    }
    print JSON::PP->new->ascii->canonical->pretty->encode(\@items);
  ' "${dirs[@]}"
}

show_task_log() {
  local task="$1"
  local lines="${2:-300}"
  local path
  path="$(task_log_path "$task")"
  [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ] || { echo "Task log not found: $task" >&2; exit 14; }
  tail -n "$lines" "$path"
}

task_status() {
  local task="$1"
  local lines="${2:-400}"
  local max_bytes path size mtime state content_b64 recent_log backup_id info status message now state_file phase state_value
  path="$(task_log_path "$task")"
  if [ ! -f "$path" ] || [ -L "$path" ] || [ ! -r "$path" ]; then
    case "$task" in
      export-*.log)
        backup_id="${task#export-}"
        backup_id="${backup_id%.log}"
        require_backup_id "$backup_id"
        info="$(export_info "$backup_id" 2>/dev/null || true)"
        status="$(printf '%s' "$info" | perl -MJSON::PP -e 'local $/; my $data = eval { decode_json(<STDIN>) } || {}; print $data->{status} // "";')"
        now="$(date +%s)"
        case "$status" in
          available)
            state="finished"
            message="Exportarchiv ist vorhanden. Das Export-Log wurde nicht gefunden; der Exportstatus wurde ueber export-info bestaetigt."
            ;;
          running)
            state="running"
            message="Export laeuft. Die Logdatei wurde noch nicht gefunden."
            ;;
          failed)
            state="failed"
            message="Export ist fehlgeschlagen. Das Export-Log wurde nicht gefunden; der Status wurde ueber export-info ermittelt."
            ;;
          *)
            echo "Task log not found: $task" >&2
            exit 14
            ;;
        esac
        content_b64="$(printf '%s\n' "$message" | base64 -w 0)"
        cat <<EOF
{
  "task": $(json_escape "$task"),
  "state": $(json_escape "$state"),
  "size": 0,
  "mtime": $now,
  "now": $now,
  "content_b64": $(json_escape "$content_b64")
}
EOF
        return 0
        ;;
      import-*.log)
        now="$(date +%s)"
        message="Import-Log wurde noch nicht gefunden. Der Import kann noch starten oder bereits laufen."
        content_b64="$(printf '%s\n' "$message" | base64 -w 0)"
        cat <<EOF
{
  "task": $(json_escape "$task"),
  "state": "running",
  "size": 0,
  "mtime": $now,
  "now": $now,
  "content_b64": $(json_escape "$content_b64")
}
EOF
        return 0
        ;;
    esac
    echo "Task log not found: $task" >&2
    exit 14
  fi
  max_bytes=32768
  size="$(stat -c '%s' "$path" 2>/dev/null || echo 0)"
  mtime="$(stat -c '%Y' "$path" 2>/dev/null || echo 0)"
  state="running"
  phase=""
  state_file="$(task_state_path "$task" 2>/dev/null || true)"
  if [ -n "$state_file" ] && [ -f "$state_file" ] && [ ! -L "$state_file" ] && [ -r "$state_file" ]; then
    state_value="$(task_state_value "$task" state 2>/dev/null || true)"
    phase="$(task_state_value "$task" phase 2>/dev/null || true)"
    case "$state_value" in running|queued|finished|failed|stopped|cleanup_failed) state="$state_value" ;; esac
    if { [ "$state" = "running" ] || [ "$state" = "queued" ]; } && ! task_process_is_current "$task"; then
      state="failed"
      phase="process_missing"
      task_state_write "$task" failed "$phase" "$path" "$$" 21 || true
    fi
  fi
  recent_log="$(tail -c 65536 "$path" 2>/dev/null || true)"
  if { [ ! -f "$state_file" ] || [ -L "$state_file" ] || [ ! -r "$state_file" ]; } && grep -qE ' (Backup|Restore|Export|Import) .* (finished|completed)$' <<< "$recent_log"; then
    state="finished"
  elif { [ ! -f "$state_file" ] || [ -L "$state_file" ] || [ ! -r "$state_file" ]; } && grep -qE ' (Backup|Restore|Export|Import) .* failed' <<< "$recent_log"; then
    state="failed"
  elif { [ ! -f "$state_file" ] || [ -L "$state_file" ] || [ ! -r "$state_file" ]; } && grep -qE ' Backup .* stopped by user$' <<< "$recent_log"; then
    state="stopped"
  elif { [ ! -f "$state_file" ] || [ -L "$state_file" ] || [ ! -r "$state_file" ]; } && [ "$(( $(date +%s) - mtime ))" -gt 300 ]; then
    state="stale"
  fi
  content_b64="$(tail -c "$max_bytes" "$path" | tail -n "$lines" | base64 -w 0)"
  cat <<EOF
{
  "task": $(json_escape "$task"),
  "state": $(json_escape "$state"),
  "phase": $(json_escape "$phase"),
  "size": $size,
  "mtime": $mtime,
  "now": $(date +%s),
  "content_b64": $(json_escape "$content_b64")
}
EOF
}

list_backups_raw() {
  local root
  local dirs=()
  local dir
  root="$(backup_root)"
  verify_backup_target "$root" false
  while IFS= read -r dir; do
    dirs+=("$dir")
  done < <(log_dirs)
  perl -MJSON::PP -MFcntl=:flock -e '
    my ($root, $lock_root, @log_dirs) = @ARGV;
    sub export_lock_held {
      my ($lock_path) = @_;
      return 0 unless -e $lock_path;
      return 1 if -l $lock_path || !-f $lock_path;
      open my $lfh, ">>", $lock_path or return 0;
      my $locked = flock($lfh, LOCK_EX | LOCK_NB);
      close $lfh;
      return $locked ? 0 : 1;
    }
    sub log_summary {
      my ($id) = @_;
      my %summary;
      my $max_tail = 262144;
      for my $dir (@log_dirs) {
        my $path = "$dir/backup-$id.log";
        next unless -f $path && !-l $path && -r $path;
        open my $fh, "<", $path or next;
        my $size = -s $fh;
        if ($size && $size > $max_tail) {
          seek($fh, $size - $max_tail, 0);
          <$fh>;
        }
        while (my $line = <$fh>) {
          chomp $line;
          if ($line =~ /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) Backup \Q$id\E finished$/) {
            $summary{status} = "complete";
            $summary{finished_at} = $1;
          } elsif ($line =~ /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) Backup \Q$id\E failed\b/) {
            $summary{status} = "failed";
            $summary{finished_at} = $1;
          } elsif ($line =~ /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) Backup \Q$id\E stopped by user$/) {
            $summary{status} = "stopped";
            $summary{finished_at} = $1;
          }
        }
        close $fh;
        last if $summary{status};
      }
      return \%summary;
    }
    sub export_log_summary {
      my ($id) = @_;
      my %summary;
      my $max_tail = 131072;
      for my $dir (@log_dirs) {
        my $path = "$dir/export-$id.log";
        next unless -f $path && !-l $path && -r $path;
        open my $fh, "<", $path or next;
        my $size = -s $fh;
        if ($size && $size > $max_tail) {
          seek($fh, $size - $max_tail, 0);
          <$fh>;
        }
        while (my $line = <$fh>) {
          chomp $line;
          if ($line =~ /Export \Q$id\E finished/) {
            $summary{status} = "available";
            $summary{message} = "Export abgeschlossen";
          } elsif ($line =~ /Export \Q$id\E failed/) {
            $summary{status} = "failed";
            $summary{message} = $line;
          }
        }
        close $fh;
        last if $summary{status};
      }
      return \%summary;
    }
    opendir(my $dh, $root) or do { print "[]"; exit 0; };
    my @items;
    for my $entry (sort readdir($dh)) {
      next if $entry =~ /^\./;
      my $dir = "$root/$entry";
      next unless -d $dir && !-l $dir;
      my $manifest = "$dir/manifest.json";
      my $validation = "$dir/backup-validation.json";
      my $data = {};
      if (-f $manifest && !-l $manifest && -r $manifest) {
        local $/;
        open my $fh, "<", $manifest;
        $data = eval { decode_json(<$fh>) } || {};
        $data = {} unless ref($data) eq "HASH";
      }
      if (-f $validation && !-l $validation && -r $validation) {
        local $/;
        open my $vh, "<", $validation;
        $data->{validation} = eval { decode_json(<$vh>) } || {};
        $data->{validation} = {} unless ref($data->{validation}) eq "HASH";
      }
      my $archive = "$root/$entry.tar.gz";
      my $lock = "$lock_root/export-$entry.lock";
      my @tmp_archives = grep { -f $_ && !-l $_ } glob("$archive.tmp.*");
      my $export_running = @tmp_archives || export_lock_held($lock);
      my $log = log_summary($entry);
      my $export_log = export_log_summary($entry);
      if (($data->{status} || "") eq "running" && $log->{status}) {
        $data->{status} = $log->{status};
      } elsif (!$data->{status} && $log->{status}) {
        $data->{status} = $log->{status};
      }
      $data->{finished_at} ||= $log->{finished_at} if $log->{finished_at};
      $data->{size_bytes} = 0 unless defined $data->{size_bytes};
      $data->{files_count} = 0 unless defined $data->{files_count};
      $data->{backup_id} ||= $entry;
      $data->{path} = $dir;
      $data->{export_file} = -f $archive && !-l $archive ? $archive : undef;
      if ($export_running) {
        $data->{export_status} = "running";
        $data->{export_size_bytes} = 0;
        $data->{export_mtime} = 0;
        $data->{export_message} = -f $archive && !-l $archive
          ? "Export wird neu erstellt. Das bisherige Archiv bleibt bis zum Abschluss erhalten."
          : "Export wird erstellt";
      } elsif (-f $archive && !-l $archive && -f "$archive.sha256" && !-l "$archive.sha256" && -f "$archive.json" && !-l "$archive.json") {
        my @ast = stat($archive);
        $data->{export_status} = "available";
        $data->{export_size_bytes} = 0 + ($ast[7] || 0);
        $data->{export_mtime} = 0 + ($ast[9] || 0);
        $data->{export_message} = "Export vorhanden und bereit zum Download";
      } elsif (-f $archive && !-l $archive) {
        $data->{export_status} = "failed";
        $data->{export_size_bytes} = 0;
        $data->{export_mtime} = 0;
        $data->{export_message} = "Export-Integritaetsdaten fehlen; bitte neu erstellen";
      } elsif (($export_log->{status} || "") eq "failed") {
        $data->{export_status} = "failed";
        $data->{export_size_bytes} = 0;
        $data->{export_mtime} = 0;
        $data->{export_message} = $export_log->{message} || "Export fehlgeschlagen";
      } else {
        $data->{export_status} = "missing";
        $data->{export_size_bytes} = 0;
        $data->{export_mtime} = 0;
        $data->{export_message} = "Noch kein Exportarchiv vorhanden";
      }
      push @items, $data;
    }
    print JSON::PP->new->ascii->canonical->pretty->encode(\@items);
  ' "$root" "$LOCK_DIR" "${dirs[@]}"
}

list_backups() {
  local root protected
  root="$(backup_root)"
  verify_backup_target "$root" false
  protected="$(maintenance_helper pins "$root")"
  list_backups_raw | python3 -c 'import json,sys; items=json.load(sys.stdin); pins=set(json.loads(sys.argv[1])["backup_ids"]); [item.update(pinned=item.get("backup_id") in pins) for item in items]; print(json.dumps(items))' "$protected"
}

export_cleanup_on_exit() {
  local status="$1" task="$2" log_file="$3" temporary="$4" checksum_temporary="$5" descriptor_temporary="$6" failed=0
  rm -f -- "$temporary" "$checksum_temporary" "$descriptor_temporary" || failed=1
  task_failure_on_exit "$status" "$task" "$log_file" "$([ "$failed" -eq 0 ] && printf failed || printf cleanup_failed)"
  return "$failed"
}

export_backup() {
  local backup_id="$1"
  local root target archive tmp lock_file checksum descriptor manifest_hash task log_file status validation checksum_tmp descriptor_tmp cleanup_trap
  local -a tar_opts=()
  require_root_for_write
  require_backup_id "$backup_id"
  task="export-$backup_id.log"
  log_file="$TASK_LOG_DIR/$task"
  prepare_log_file "$log_file" append
  install_task_failure_trap "$task" "$log_file"
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  archive="$root/$backup_id.tar.gz"
  if [ "$(manifest_field "$target/manifest.json" backup.storage_format)" = portable-repository ]; then
    echo "Portable Sicherungsstaende zuerst mit repository-stage ID LEERES_LINUX_VERZEICHNIS bereitstellen. Ein einzelner Repository-Ordner ist kein exportierbares Backup. Siehe Wiederherstellungsschritte." >&2
    return 18
  fi
  tmp="$archive.tmp.$$"
  lock_file="$LOCK_DIR/export-$backup_id.lock"
  status="$(manifest_field "$target/manifest.json" status 2>/dev/null || true)"
  validation="$(manifest_field "$target/backup-validation.json" status 2>/dev/null || true)"
  case "$status:$validation" in complete:ok|complete_with_warnings:warning) ;; *) echo "Only validated backups can be exported." >&2; exit 18 ;; esac
  if { [ ! -d "$target/rootfs" ] || [ -L "$target/rootfs" ]; } && { [ ! -f "$target/rootfs.tar" ] || [ -L "$target/rootfs.tar" ]; }; then
    log "Export $backup_id failed: rootfs not found"
    echo "Backup rootfs not found: $backup_id" >&2
    exit 6
  fi
  [ ! -L "$lock_file" ] || { echo "Unsafe export lock symlink: $backup_id" >&2; exit 13; }
  exec 7>"$lock_file"
  flock -n 7 || { log "Export $backup_id failed: already running"; echo "Export already running: $backup_id" >&2; exit 5; }
  rm -f "$tmp"
  log "Starting export $backup_id"
  task_state_write "$task" running archiving "$log_file" "$$" ""
  checksum_tmp="$archive.sha256.tmp.$$"
  descriptor="$archive.json"
  descriptor_tmp="$descriptor.tmp.$$"
  printf -v cleanup_trap 'HB_EXPORT_EXIT_STATUS=$?; trap - EXIT; export_cleanup_on_exit "$HB_EXPORT_EXIT_STATUS" %q %q %q %q %q || { [ "$HB_EXPORT_EXIT_STATUS" -ne 0 ] || HB_EXPORT_EXIT_STATUS=20; }; exit "$HB_EXPORT_EXIT_STATUS"' "$task" "$log_file" "$tmp" "$checksum_tmp" "$descriptor_tmp"
  # Intentionally freeze shell-quoted cleanup arguments.
  # shellcheck disable=SC2064
  trap "$cleanup_trap" EXIT
  while IFS= read -r opt; do tar_opts+=("$opt"); done < <(tar_metadata_options)
  if ! run_with_heartbeat "Export $backup_id" tar "${tar_opts[@]}" -C "$root" -czf "$tmp" -- "$backup_id"; then
    rm -f "$tmp"
    log "Export $backup_id failed during archive creation"
    exit 15
  fi
  if ! tar -tzf "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp"
    log "Export $backup_id failed integrity check"
    exit 16
  fi
  checksum="$(sha256sum "$tmp" | awk '{print $1}')"
  manifest_hash="$(sha256sum "$target/manifest.json" | awk '{print $1}')"
  printf '%s  %s\n' "$checksum" "$(basename "$archive")" > "$checksum_tmp"
  perl -MJSON::PP -e '
    my ($file, $id, $archive, $checksum, $manifest_hash) = @ARGV;
    my $data = { schema_version => 1, backup_id => $id, archive => $archive, sha256 => $checksum, manifest_sha256 => $manifest_hash, created_at => scalar gmtime() . "Z" };
    open my $fh, ">", $file or die $!;
    print $fh JSON::PP->new->ascii->canonical->pretty->encode($data) or die $!;
    close $fh or die $!;
  ' "$descriptor_tmp" "$backup_id" "$(basename "$archive")" "$checksum" "$manifest_hash"
  verify_backup_target "$root" true
  mv -fT -- "$tmp" "$archive"
  mv -fT -- "$checksum_tmp" "$archive.sha256"
  mv -fT -- "$descriptor_tmp" "$descriptor"
  task_state_write "$task" finished complete "$log_file" "$$" 0
  trap - EXIT
  log "Export $backup_id finished"
  printf '%s\n' "$archive"
}

export_info() {
  local backup_id="$1"
  local root target archive lock_file tmp_count status message size mtime descriptor_manifest_hash current_manifest_hash
  local expected_checksum actual_checksum descriptor_checksum descriptor_archive
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  target="$(safe_backup_target "$root" "$backup_id")"
  archive="$root/$backup_id.tar.gz"
  lock_file="$LOCK_DIR/export-$backup_id.lock"
  tmp_count="$(find "$root" -maxdepth 1 -type f -name "$backup_id.tar.gz.tmp.*" 2>/dev/null | wc -l)"
  status="missing"
  message="Noch kein Exportarchiv vorhanden"
  size=0
  mtime=0
  if [ "${tmp_count:-0}" -gt 0 ] || export_lock_held "$lock_file"; then
    status="running"
    if [ -f "$archive" ] && [ ! -L "$archive" ]; then
      message="Export wird neu erstellt. Das bisherige Archiv bleibt bis zum Abschluss erhalten."
    else
      message="Export wird erstellt"
    fi
  elif [ -f "$archive" ] && [ ! -L "$archive" ]; then
    if [ ! -f "$archive.sha256" ] || [ -L "$archive.sha256" ] || [ ! -f "$archive.json" ] || [ -L "$archive.json" ]; then
      status="failed"
      message="Export-Integritaetsdaten fehlen. Bitte Export neu erstellen."
    else
      expected_checksum="$(perl -e '
        my ($file, $expected_name) = @ARGV;
        open my $fh, "<", $file or exit 1;
        my $line = <$fh> // "";
        chomp $line;
        exit 1 unless $line =~ /^([0-9a-f]{64})  \Q$expected_name\E$/;
        print $1;
      ' "$archive.sha256" "$(basename "$archive")" 2>/dev/null || true)"
      actual_checksum="$(sha256sum "$archive" 2>/dev/null | awk '{print $1}')"
      descriptor_checksum="$(manifest_field "$archive.json" sha256 2>/dev/null || true)"
      descriptor_archive="$(manifest_field "$archive.json" archive 2>/dev/null || true)"
      if [ -z "$expected_checksum" ] || [ "$expected_checksum" != "$actual_checksum" ] || [ "$descriptor_checksum" != "$actual_checksum" ] || [ "$descriptor_archive" != "$(basename "$archive")" ]; then
        status="failed"
        message="Export-Pruefsumme stimmt nicht. Archiv nicht verwenden."
      else
        descriptor_manifest_hash="$(manifest_field "$archive.json" manifest_sha256 2>/dev/null || true)"
        current_manifest_hash="$(sha256sum "$target/manifest.json" | awk '{print $1}')"
        if [ -z "$descriptor_manifest_hash" ] || [ "$descriptor_manifest_hash" != "$current_manifest_hash" ] || [ "$(manifest_field "$archive.json" backup_id 2>/dev/null || true)" != "$backup_id" ]; then
          status="failed"
          message="Export-Descriptor passt nicht zum finalen Backup-Manifest. Bitte Export neu erstellen."
        else
          status="available"
          message="Export vorhanden, Pruefsumme und Manifest-Bezug sind gueltig"
          size="$(stat -c '%s' "$archive" 2>/dev/null || echo 0)"
          mtime="$(stat -c '%Y' "$archive" 2>/dev/null || echo 0)"
        fi
      fi
    fi
  fi
  cat <<EOF
{
  "backup_id": $(json_escape "$backup_id"),
  "status": $(json_escape "$status"),
  "message": $(json_escape "$message"),
  "archive": $(json_escape "$archive"),
  "size_bytes": $size,
  "mtime": $mtime
}
EOF
}

download_export() {
  local backup_id="$1" root target archive lock_file
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  archive="$root/$backup_id.tar.gz"
  lock_file="$LOCK_DIR/export-$backup_id.lock"
  [ ! -L "$lock_file" ] || return 13
  exec 7>"$lock_file"
  flock -sn 7 || { echo "Export wird noch erstellt. Bitte nach Abschluss erneut laden." >&2; return 5; }
  python3 "$LBP_BINDIR/hostbackup-download.py" export "$archive" "$backup_id.tar.gz" \
    --descriptor "$archive.json" --checksum "$archive.sha256" --manifest "$target/manifest.json"
}

download_log() {
  local task="$1" path
  valid_task_name "$task" || return 11
  path="$(task_log_path "$task")"
  python3 "$LBP_BINDIR/hostbackup-download.py" log "$path" "$task"
}

start_export() {
  require_root_for_write
  local backup_id="$1"
  local log_file task pid
  require_backup_id "$backup_id"
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" shared
  log_file="$TASK_LOG_DIR/export-$backup_id.log"
  prepare_log_file "$log_file" truncate
  log "Export $backup_id queued" >> "$log_file"
  task="export-$backup_id.log"
  pid="$(launch_background "$task" "$log_file" "$0" export "$backup_id")"
  [ -n "$pid" ] || { echo "Export process could not be launched." >&2; exit 14; }
  if [ ! -r "$log_file" ]; then
    echo "Export log is not readable: $log_file" >&2
    exit 14
  fi
  printf 'export-%s.log\n' "$backup_id"
}

delete_export() {
  require_root_for_write
  local backup_id="$1"
  local root archive lock_file
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  safe_backup_target "$root" "$backup_id" >/dev/null
  archive="$root/$backup_id.tar.gz"
  lock_file="$LOCK_DIR/export-$backup_id.lock"
  [ ! -L "$lock_file" ] || { echo "Unsafe export lock symlink: $backup_id" >&2; exit 13; }
  exec 7>"$lock_file"
  flock -n 7 || { echo "Export laeuft noch und kann nicht geloescht werden: $backup_id" >&2; exit 5; }
  rm -f "$archive" "$archive".tmp.* "$archive.sha256" "$archive.json"
}

validate_import_archive() {
  local archive="$1" max_bytes="$2"
  command -v python3 >/dev/null 2>&1 || { echo "python3 is required for safe archive validation." >&2; return 13; }
  python3 "$LBP_BINDIR/validate-import-archive.py" --json "$archive" "$max_bytes"
}

inspect_backup_directory() {
  local target="$1" max_bytes="${2:-9223372036854775807}"
  if [ "$(manifest_field "$target/manifest.json" backup.storage_format 2>/dev/null || true)" = portable-repository ]; then
    local root id expected
    root="$(backup_root)"; id="${target##*/}"
    expected="$(safe_backup_target "$root" "$id")" || return 18
    [ "$target" = "$expected" ] || { echo 'Repository-Kontrolldateien koennen nicht als Einzelarchiv importiert werden.' >&2; return 18; }
    maintenance_helper repository-check "$root" "$id"
    return
  fi
  python3 "$LBP_BINDIR/validate-import-archive.py" --backup-dir --json "$target" "$max_bytes"
}

write_import_validation() {
  local target="$1" archive="$2" archive_hash="$3" result
  result="$(inspect_backup_directory "$target")" || return 18
  printf '%s' "$result" | python3 -c '
import json, os, pathlib, sys, tempfile
directory, archive, digest = map(str, sys.argv[1:])
result = json.load(sys.stdin)
result["validation_source"] = "local-import-inspection"
def replace(name, data):
    fd, temporary = tempfile.mkstemp(prefix=".import-control-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, str(pathlib.Path(directory) / name))
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
replace("backup-validation.json", json.dumps(result, indent=2, ensure_ascii=True) + "\n")
replace("import-source.sha256", digest + "  " + pathlib.Path(archive).name + "\n")
manifest = json.loads((pathlib.Path(directory) / "manifest.json").read_text(encoding="utf-8"))
manifest["status"] = "complete_with_warnings" if result["status"] == "warning" else "complete"
replace("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True) + "\n")
' "$target" "$archive" "$archive_hash"
}

quarantine_import_archive() {
  local archive="$1" quarantine="$QUARANTINE_DIR" destination
  [ ! -L "$quarantine" ] || return 1
  mkdir -p -- "$quarantine" || return 1
  chmod 0700 "$quarantine" 2>/dev/null || true
  [ -d "$quarantine" ] && [ ! -L "$quarantine" ] || return 1
  if [ "$(id -u)" -eq 0 ]; then
    [ "$(stat -c '%u' "$quarantine" 2>/dev/null || echo -1)" = "0" ] || return 1
  fi
  destination="$quarantine/$(basename -- "$archive").failed.$(date +%s).$$"
  mv -fT -- "$archive" "$destination"
}

import_cleanup_on_exit() {
  local status="$1" task="$2" log_file="$3" staging="$4" archive="$5" cleanup_archive="$6" failed=0
  if [ -n "$staging" ]; then
    rm -rf --one-file-system -- "$staging" 2>/dev/null || failed=1
  fi
  if [ "$cleanup_archive" = 1 ] && { [ -e "$archive" ] || [ -L "$archive" ]; }; then
    if [ "$status" -eq 0 ]; then
      rm -f -- "$archive" || failed=1
    elif ! quarantine_import_archive "$archive" 2>/dev/null; then
      log "Import archive retained for diagnosis: $archive" >> "$log_file" || true
      failed=1
    fi
  fi
  task_failure_on_exit "$status" "$task" "$log_file" "$([ "$failed" -eq 0 ] && printf failed || printf cleanup_failed)"
  return "$failed"
}

install_import_cleanup_trap() {
  local task="$1" log_file="$2" staging="$3" archive="$4" cleanup_archive="$5" cleanup_trap
  printf -v cleanup_trap 'HB_IMPORT_EXIT_STATUS=$?; trap - EXIT; import_cleanup_on_exit "$HB_IMPORT_EXIT_STATUS" %q %q %q %q %q || { [ "$HB_IMPORT_EXIT_STATUS" -ne 0 ] || HB_IMPORT_EXIT_STATUS=20; }; exit "$HB_IMPORT_EXIT_STATUS"' "$task" "$log_file" "$staging" "$archive" "$cleanup_archive"
  # Intentionally freeze shell-quoted cleanup arguments.
  # shellcheck disable=SC2064
  trap "$cleanup_trap" EXIT
}

import_backup() {
  require_root_for_write
  local archive="$1"
  local root top staging extracted max_mb max_bytes archive_size task log_file archive_hash validation_json expanded_size free_bytes
  local -a tar_opts=()
  task="${HOSTBACKUP_TASK_ID:-import-$(date '+%Y%m%d-%H%M%S')-$$.log}"
  valid_task_name "$task" || return 11
  log_file="$TASK_LOG_DIR/$task"
  prepare_log_file "$log_file" append
  task_state_write "$task" running inspecting "$log_file" "$$" ""
  install_import_cleanup_trap "$task" "$log_file" '' "$archive" "${HOSTBACKUP_IMPORT_CLEANUP:-0}"
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock exclusive
  [ -r "$archive" ] || { echo "Archive not readable: $archive" >&2; exit 9; }
  max_mb="$(json_get_number import_max_size_mb)"
  [ -n "$max_mb" ] || max_mb="$DEFAULT_IMPORT_MAX_MB"
  max_bytes=$((max_mb * 1024 * 1024))
  archive_size="$(stat -c '%s' "$archive" 2>/dev/null || echo 0)"
  [ "$archive_size" -gt 0 ] && [ "$archive_size" -le "$max_bytes" ] || { echo "Archive exceeds configured size limit." >&2; exit 20; }
  validation_json="$(validate_import_archive "$archive" "$max_bytes")"
  top="$(printf '%s' "$validation_json" | perl -MJSON::PP -e 'local $/; my $d=decode_json(<STDIN>); print $d->{backup_id} // "";')"
  expanded_size="$(printf '%s' "$validation_json" | perl -MJSON::PP -e 'local $/; my $d=decode_json(<STDIN>); print 0 + ($d->{expanded_size} // 0);')"
  require_backup_id "$top"
  free_bytes="$(df -PB1 "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  [ "${free_bytes:-0}" -gt $((expanded_size + 268435456)) ] || { echo "Backup target does not have enough free space for the expanded import." >&2; exit 20; }
  acquire_backup_lock "$top" exclusive
  if [ -e "$root/$top" ]; then
    echo "Backup already exists: $top" >&2
    exit 4
  fi
  staging="$(mktemp -d "$root/.$top.import.XXXXXX")" || return 20
  extracted="$staging/$top"
  install_import_cleanup_trap "$task" "$log_file" "$staging" "$archive" "${HOSTBACKUP_IMPORT_CLEANUP:-0}"
  archive_hash="$(sha256sum "$archive" | awk '{print $1}')"
  task_state_write "$task" running extracting "$log_file" "$$" ""
  log "Starting import from $archive"
  while IFS= read -r opt; do tar_opts+=("$opt"); done < <(tar_metadata_options)
  if ! run_with_heartbeat "Import $top" tar "${tar_opts[@]}" --same-owner --same-permissions --delay-directory-restore --no-overwrite-dir -C "$staging" -xzf "$archive"; then
    log "Import $top failed during archive extraction"
    exit 15
  fi
  [ -d "$extracted" ] && [ ! -L "$extracted" ] || { echo "Imported backup directory is unsafe." >&2; exit 12; }
  [ -f "$extracted/manifest.json" ] && [ ! -L "$extracted/manifest.json" ] || { echo "Imported manifest is not a safe regular file." >&2; exit 12; }
  [ -f "$extracted/backup-validation.json" ] && [ ! -L "$extracted/backup-validation.json" ] || { echo "Imported validation is not a safe regular file." >&2; exit 12; }
  chown root:root "$extracted" "$extracted/manifest.json" "$extracted/backup-validation.json"
  chmod 0700 "$extracted"
  chmod 0600 "$extracted/manifest.json" "$extracted/backup-validation.json"
  if [ -e "$extracted/rootfs" ]; then
    perl -e 'exit((-d $ARGV[0] && !-l $ARGV[0]) ? 0 : 1)' "$extracted/rootfs" || { echo "Imported rootfs is not a real directory." >&2; exit 12; }
  else
    [ -f "$extracted/rootfs.tar" ] && [ ! -L "$extracted/rootfs.tar" ] || { echo "Imported archive does not contain safe backup data." >&2; exit 12; }
    python3 "$LBP_BINDIR/validate-import-archive.py" --rootfs-tar "$extracted/rootfs.tar" "$max_bytes"
  fi
  [ "$(manifest_field "$extracted/manifest.json" backup_id 2>/dev/null || true)" = "$top" ] || { echo "Imported manifest id mismatch." >&2; exit 12; }
  case "$(manifest_field "$extracted/manifest.json" status 2>/dev/null || true):$(manifest_field "$extracted/backup-validation.json" status 2>/dev/null || true)" in
    complete:ok|complete_with_warnings:warning) ;;
    *) echo "Imported backup is not complete and validated." >&2; exit 12 ;;
  esac
  write_import_validation "$extracted" "$archive" "$archive_hash"
  write_backup_marker "$extracted" "$top"
  verify_backup_target "$root" true
  mv -- "$extracted" "$root/$top"
  rmdir "$staging"
  task_state_write "$task" finished complete "$log_file" "$$" 0
  log "Import $top finished"
  if [ "${HOSTBACKUP_IMPORT_CLEANUP:-0}" = "1" ]; then rm -f -- "$archive"; fi
  trap - EXIT
  printf '%s\n' "$top"
}

require_staged_import_archive() {
  local archive="$1"
  local staging="$LBP_DATADIR/imports"
  local archive_real staging_real link_count
  [ -f "$archive" ] && [ ! -L "$archive" ] && [ -r "$archive" ] || { echo "Archive is not a safe regular file: $archive" >&2; exit 9; }
  [ -d "$staging" ] && [ ! -L "$staging" ] || { echo "Import staging directory is missing or unsafe: $staging" >&2; exit 13; }
  archive_real="$(readlink -f "$archive" 2>/dev/null || true)"
  staging_real="$(readlink -f "$staging" 2>/dev/null || true)"
  [ -n "$archive_real" ] || { echo "Archive path could not be resolved: $archive" >&2; exit 9; }
  [ -n "$staging_real" ] || { echo "Import staging directory could not be resolved: $staging" >&2; exit 9; }
  case "$archive_real" in
    "$staging_real"/*.tar.gz|"$staging_real"/*.tgz)
      link_count="$(stat -c '%h' "$archive_real" 2>/dev/null || echo 0)"
      [ "$link_count" -eq 1 ] || { echo "Import archive must not have additional hardlinks." >&2; exit 13; }
      printf '%s\n' "$archive_real"
      ;;
    *) echo "Background import requires a staged tar.gz or tgz archive in $staging_real." >&2; exit 13 ;;
  esac
}

claim_staged_import_archive() {
  local archive destination
  archive="$(require_staged_import_archive "$1")"
  destination="$ROOT_IMPORT_DIR/incoming-$(date '+%Y%m%d-%H%M%S')-$$.tar.gz"
  [ ! -e "$destination" ] && [ ! -L "$destination" ] || { echo "Import claim path already exists." >&2; exit 13; }
  if ! mv -T -- "$archive" "$destination"; then
    echo "Import archive could not be moved into the root-owned staging directory." >&2
    exit 13
  fi
  if [ ! -f "$destination" ] || [ -L "$destination" ] || [ "$(stat -c '%h' "$destination" 2>/dev/null || echo 0)" -ne 1 ]; then
    rm -rf --one-file-system -- "$destination" 2>/dev/null || true
    echo "Claimed import archive is not a safe regular file." >&2
    exit 13
  fi
  chown root:root "$destination"
  chmod 0600 "$destination"
  printf '%s\n' "$destination"
}

start_import() {
  require_root_for_write
  local archive="$1"
  local task_id log_file pid archive_size free_bytes root
  acquire_operation_lock exclusive
  root="$(backup_root)"
  verify_backup_target "$root" true
  task_id="import-$(date '+%Y%m%d-%H%M%S')-$$.log"
  log_file="$TASK_LOG_DIR/$task_id"
  prepare_log_file "$log_file" truncate
  archive="$(claim_staged_import_archive "$archive")"
  task_state_write "$task_id" queued preparing "$log_file" "$$" ""
  install_import_cleanup_trap "$task_id" "$log_file" '' "$archive" 1
  log "Import queued from $archive" >> "$log_file"
  archive_size="$(stat -c '%s' "$archive" 2>/dev/null || echo 0)"
  free_bytes="$(df -PB1 "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  [ "${free_bytes:-0}" -gt $((archive_size + 268435456)) ] || { echo "Not enough staging space for import." >&2; exit 20; }
  if ! pid="$(launch_background "$task_id" "$log_file" env HOSTBACKUP_IMPORT_CLEANUP=1 HOSTBACKUP_TASK_ID="$task_id" "$0" import "$archive")"; then
    echo "Import process could not be launched." >&2
    exit 14
  fi
  [ -n "$pid" ] || { echo "Import process could not be launched." >&2; exit 14; }
  # The worker now owns archive cleanup and the persistent task result.
  trap - EXIT
  if [ ! -r "$log_file" ]; then
    echo "Import log is not readable: $log_file" >&2
    exit 14
  fi
  printf '%s\n' "$task_id"
}

move_backup() {
  require_root_for_write
  local backup_id="$1"
  local destination_root="$2"
  local root target archive destination canonical_destination destination_mount
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  target="$(safe_backup_target "$root" "$backup_id")"
  if [ "$(manifest_field "$target/manifest.json" backup.storage_format)" = portable-repository ]; then
    echo "Repository-Sicherungsstaende teilen Datenbloecke. Einzelne Stand-Verzeichnisse duerfen nicht verschoben werden; gesamtes Repository samt Wiederherstellungsschluessel benoetigt." >&2
    return 18
  fi
  archive="$root/$backup_id.tar.gz"
  canonical_destination="$(canonicalize_path "$destination_root")" || { echo "Destination must be absolute." >&2; exit 13; }
  require_allowed_backup_root "$canonical_destination"
  path_has_symlink_component "$canonical_destination" && { echo "Destination contains a symlink component." >&2; exit 13; }
  destination_mount="$(current_mount_value "$(nearest_existing_path "$canonical_destination")" TARGET)"
  [ -n "$destination_mount" ] && [ "$destination_mount" != "/" ] || { echo "Destination must be on a separate mounted filesystem." >&2; exit 13; }
  mkdir -p -- "$canonical_destination"
  destination="$canonical_destination/$backup_id"
  [ ! -e "$destination" ] || { echo "Destination already exists: $destination" >&2; exit 4; }
  mv "$target" "$destination"
  if [ -f "$archive" ]; then
    mv "$archive" "$canonical_destination/$backup_id.tar.gz"
    [ ! -f "$archive.sha256" ] || mv "$archive.sha256" "$canonical_destination/$backup_id.tar.gz.sha256"
    [ ! -f "$archive.json" ] || mv "$archive.json" "$canonical_destination/$backup_id.tar.gz.json"
  fi
  printf '%s\n' "$destination"
}

browse_backup() {
  local backup_id="$1"
  local rel_path="${2:-}"
  local root base
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_backup_lock "$backup_id" shared
  base="$(safe_backup_target "$root" "$backup_id")/rootfs"
  [ -d "$base" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  perl -MJSON::PP -MCwd=abs_path -MFile::Spec -e '
    my ($base, $rel) = @ARGV;
    $rel ||= "";
    die "Unsafe path\n" if $rel =~ m{(^/|(^|/)\.\.(/|$))};
    my $base_abs = abs_path($base) or die "Missing base\n";
    my $dir = File::Spec->catdir($base_abs, split m{/+}, $rel);
    my $dir_abs = abs_path($dir) or die "Missing path\n";
    die "Path escapes backup\n" unless $dir_abs eq $base_abs || index($dir_abs, $base_abs . "/") == 0;
    die "Not a directory\n" unless -d $dir_abs;
    opendir(my $dh, $dir_abs) or die "Cannot open directory\n";
    my @items;
    for my $name (sort grep { $_ ne "." && $_ ne ".." } readdir($dh)) {
      my $path = "$dir_abs/$name";
      my @st = lstat($path);
      next unless @st;
      my $type = -l _ ? "symlink" : -d _ ? "directory" : -f _ ? "file" : "other";
      my $child_rel = length($rel) ? "$rel/$name" : $name;
      push @items, {
        name => $name,
        path => $child_rel,
        type => $type,
        size => 0 + $st[7],
        mtime => 0 + $st[9],
      };
    }
    print JSON::PP->new->ascii->canonical->pretty->encode({
      backup_id => undef,
      path => $rel,
      items => \@items,
    });
  ' "$base" "$rel_path"
}

cat_backup_file() {
  local backup_id="$1"
  local rel_path="$2"
  local root base
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_backup_lock "$backup_id" shared
  base="$(safe_backup_target "$root" "$backup_id")/rootfs"
  [ -d "$base" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  perl -MCwd=abs_path -MFile::Spec -MFcntl=:DEFAULT -e '
    my ($base, $rel) = @ARGV;
    die "Unsafe path\n" if !$rel || $rel =~ m{(^/|(^|/)\.\.(/|$))};
    my $base_abs = abs_path($base) or die "Missing base\n";
    my $file = File::Spec->catfile($base_abs, split m{/+}, $rel);
    my $file_abs = abs_path($file) or die "Missing file\n";
    die "Path escapes backup\n" unless index($file_abs, $base_abs . "/") == 0;
    die "Not a regular file\n" unless -f $file_abs;
    sysopen my $fh, $file_abs, O_RDONLY | O_NOFOLLOW or die "Cannot open file\n";
    binmode $fh;
    binmode STDOUT;
    my $buffer;
    while (read($fh, $buffer, 65536)) {
      print $buffer;
    }
  ' "$base" "$rel_path"
}

delete_backup() {
  require_root_for_write
  local backup_id="$1"
  local root target archive trash
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  target="$(safe_backup_target "$root" "$backup_id")"
  maintenance_helper delete-check "$root" "$backup_id" >/dev/null
  if [ "$(manifest_field "$target/manifest.json" backup.storage_format)" = portable-repository ]; then
    maintenance_helper repository-forget "$root" "$backup_id" >/dev/null
  fi
  archive="$root/$backup_id.tar.gz"
  trash="$(strict_child_path "$root" "$root/.trash-$backup_id-$(date +%s)-$$")" || { echo "Unsafe trash path." >&2; exit 7; }
  mv -- "$target" "$trash"
  rm -rf --one-file-system -- "$trash"
  rm -f -- "$archive" "$archive.sha256" "$archive.json"
  if ! maintenance_helper forget-integrity "$root" "$backup_id" --marker "$backup_id"; then
    log "Backup wurde geloescht; seine lokale Inhaltspruefbasis konnte nicht entfernt werden." >&2
  fi
}

recovery_helper() {
  local action="$1" root="$2" target="$3" destination="$4" mappings="$5"
  shift 5
  python3 "$LBP_BINDIR/hostbackup-recovery.py" "$action" --backup "$target" --backup-root "$root" \
    --destination "$destination" --map-json "$mappings" \
    --protect-host "$LBP_CONFIGDIR" --protect-host "$LBP_DATADIR" --protect-host "$LBP_LOGDIR" \
    --protect-host "$ROOT_STATE_DIR" --protect-host /usr/libexec/loxberryhostbackup \
    --protect-host /usr/local/sbin/loxberryhostbackup --protect-host /usr/local/sbin/loxberryhostbackup-sudo "$@"
}

restore_plan() {
  local backup_id="$1" destination="${2:-/}" mappings="${3:-[]}"
  local root target mode storage_format inspection
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  inspection="$(inspect_backup_directory "$target")"
  mode="$(manifest_field "$target/manifest.json" metadata.mode)"
  storage_format="$(manifest_field "$target/manifest.json" backup.storage_format)"
  [ -n "$mode" ] || mode=native-strict
  [ -n "$storage_format" ] || storage_format=directory
  printf 'Restore-Vorschau: %s\nBestehende Dateien im freigegebenen Zielbereich koennen ersetzt oder geloescht werden.\nBackup-Ausschluesse bleiben geschuetzt; separate Volumes erfordern eine ausdrueckliche Zuordnung.\n\n' "$backup_id"
  printf 'Lokale Inhaltspruefung (warning erfordert confirm-degraded; eine Strukturpruefung ersetzt keinen vollstaendigen Restoretest):\n%s\n\n' "$inspection"
  recovery_helper plan "$root" "$target" "$destination" "$mappings"
  recovery_helper execute "$root" "$target" "$destination" "$mappings" --mode "$mode" --storage-format "$storage_format" --dry-run
}

restore_excludes() {
  local root="$1" target="$2" output="$3"
  recovery_helper excludes "$root" "$target" "${4:-/}" "${5:-[]}" --output "$output"
}

restore_cleanup_on_exit() {
  local status="$1" state_dir="$2" log_file="$3" task="$4" restarted="$5"
  local failed=0
  if [ "$restarted" != "true" ] && [ ! -d "$state_dir" ]; then
    log "ERROR: Local restore restart journal is missing; recovery could not be verified" | tee -a "$log_file" || true
    failed=1
  fi
  if [ "$restarted" != "true" ] && [ -d "$state_dir" ]; then
    start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file" || failed=1
  fi
  if [ "$failed" -eq 0 ] && [ -d "$state_dir" ]; then
    restart_journal_finish "$state_dir" || failed=1
  fi
  if [ "$status" -ne 0 ] || [ "$failed" -ne 0 ]; then
    task_state_write "$task" failed "$([ "$failed" -eq 0 ] && printf failed || printf cleanup_failed)" "$log_file" "$$" "$status" || true
  fi
  return "$failed"
}

restore_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1" degraded_confirmation="${2:-false}" restore_dest="${3:-${HOSTBACKUP_RESTORE_DEST:-/}}" mappings="${4:-[]}"
  local root target state_dir mode storage_format task
  local log_file rsync_status cleanup_trap
  require_backup_id "$backup_id"
  [ "${ALLOW_RESTORE:-}" = "1" ] || { echo "Set ALLOW_RESTORE=1 to run restore." >&2; exit 8; }
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" shared
  target="$(restore_eligibility "$backup_id" "$degraded_confirmation")"
  mode="$(manifest_field "$target/manifest.json" metadata.mode)"
  storage_format="$(manifest_field "$target/manifest.json" backup.storage_format)"
  if [ -z "$mode" ] || [ "$mode" = "legacy-unknown" ]; then
    [ "$degraded_confirmation" = confirm-degraded ] || { echo "Legacy-Metadaten benoetigen eine ausdrueckliche Bestaetigung." >&2; return 18; }
    mode=native-strict
  fi
  [ -n "$storage_format" ] || storage_format=directory
  if [ "$storage_format" = "portable-tar" ]; then
    command -v tar >/dev/null 2>&1 || { echo "tar is required." >&2; exit 3; }
  else
    command -v rsync >/dev/null 2>&1 || { echo "rsync is required." >&2; exit 3; }
  fi
  log_file="$TASK_LOG_DIR/restore-$backup_id.log"
  task="restore-$backup_id.log"
  prepare_log_file "$log_file" truncate
  task_state_write "$task" running preflight "$log_file" "$$" ""
  state_dir="$(restart_journal_create "$task")"
  # Referenced from the frozen EXIT trap.
  # shellcheck disable=SC2034
  HB_RESTORE_RESTART_DONE=false
  printf -v cleanup_trap 'HB_RESTORE_EXIT_STATUS=$?; trap - EXIT; restore_cleanup_on_exit "$HB_RESTORE_EXIT_STATUS" %q %q %q "${HB_RESTORE_RESTART_DONE:-false}" || { [ "$HB_RESTORE_EXIT_STATUS" -ne 0 ] || HB_RESTORE_EXIT_STATUS=20; }; exit "$HB_RESTORE_EXIT_STATUS"' "$state_dir" "$log_file" "$task"
  # Intentionally freeze shell-quoted cleanup arguments.
  # shellcheck disable=SC2064
  trap "$cleanup_trap" EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  log "Starting restore $backup_id" | tee -a "$log_file"
  log "Restoring from $target to $restore_dest" | tee -a "$log_file"
  task_state_write "$task" running planning "$log_file" "$$" ""
  recovery_helper plan "$root" "$target" "$restore_dest" "$mappings" 2>&1 | tee -a "$log_file"
  recovery_helper execute "$root" "$target" "$restore_dest" "$mappings" --mode "$mode" --storage-format "$storage_format" --dry-run 2>&1 | tee -a "$log_file"
  # No downtime before the complete, exclusion-aware plan succeeds.
  if [ "$restore_dest" = / ]; then
    task_state_write "$task" running stopping_services "$log_file" "$$" ""
    stop_backup_targets "$state_dir" 2>&1 | tee -a "$log_file"
  fi
  task_state_write "$task" running restoring "$log_file" "$$" ""
  set +e
  recovery_helper execute "$root" "$target" "$restore_dest" "$mappings" --mode "$mode" --storage-format "$storage_format" 2>&1 | tee -a "$log_file"
  rsync_status=${PIPESTATUS[0]}
  set -e
  log "restore copy finished with status $rsync_status" | tee -a "$log_file"
  if [ "$rsync_status" -eq 0 ]; then
    task_state_write "$task" running restarting_services "$log_file" "$$" ""
    start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file"
    # Referenced from the frozen EXIT trap.
    # shellcheck disable=SC2034
    HB_RESTORE_RESTART_DONE=true
    restart_journal_finish "$state_dir"
    log "Restore $backup_id finished" | tee -a "$log_file"
    task_state_write "$task" finished complete "$log_file" "$$" 0
    trap - EXIT HUP INT TERM
    notify_hostbackup "restore" 5 "LoxBerry Host Backup Restore abgeschlossen" "Restore $backup_id wurde abgeschlossen. Bitte System, Dienste und Docker-Container pruefen." "$log_file"
  else
    log "Restore $backup_id failed with rsync status $rsync_status" | tee -a "$log_file"
    notify_hostbackup "restore" 3 "LoxBerry Host Backup Restore fehlgeschlagen" "Restore $backup_id ist fehlgeschlagen. rsync Status: $rsync_status." "$log_file"
    exit "$rsync_status"
  fi
}

start_restore() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1" degraded_confirmation="${2:-false}" destination="${3:-/}" mappings="${4:-[]}"
  local log_file task pid
  require_backup_id "$backup_id"
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" shared
  restore_eligibility "$backup_id" "$degraded_confirmation" >/dev/null
  recovery_helper plan "$(backup_root)" "$(safe_backup_target "$(backup_root)" "$backup_id")" "$destination" "$mappings" >/dev/null
  log_file="$TASK_LOG_DIR/restore-$backup_id.launch.log"
  prepare_log_file "$log_file" truncate
  task="restore-$backup_id.log"
  pid="$(launch_background "$task" "$log_file" env ALLOW_RESTORE=1 "$0" restore "$backup_id" "$degraded_confirmation" "$destination" "$mappings")"
  [ -n "$pid" ] || { echo "Restore process could not be launched." >&2; exit 14; }
  printf '%s\n' "$backup_id"
}

start_restore_files() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1" relative="$2" destination="$3" task log_file pid root target
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  inspect_backup_directory "$target" >/dev/null
  task="restore-partial-$backup_id-$(date +%s).log"
  log_file="$TASK_LOG_DIR/$task"
  prepare_log_file "$log_file" truncate
  pid="$(launch_background "$task" "$log_file" "$0" restore-files-worker "$backup_id" "$relative" "$destination" "$task")"
  [ -n "$pid" ] || return 14
  printf '%s\n' "$task"
}

restore_files_worker() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1" relative="$2" destination="$3" task="$4" root target mode storage_format log_file
  valid_task_name "$task" || return 11
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  log_file="$TASK_LOG_DIR/$task"
  task_state_write "$task" running inspecting "$log_file" "$$" ""
  install_task_failure_trap "$task" "$log_file"
  inspect_backup_directory "$target" >/dev/null
  mode="$(manifest_field "$target/manifest.json" metadata.mode)"
  storage_format="$(manifest_field "$target/manifest.json" backup.storage_format)"
  [ -n "$mode" ] && [ "$mode" != legacy-unknown ] || mode=native-strict
  [ -n "$storage_format" ] || storage_format=directory
  task_state_write "$task" running restoring "$log_file" "$$" ""
  recovery_helper files "$root" "$target" "$destination" '[]' --relative "$relative" --mode "$mode" --storage-format "$storage_format"
  task_state_write "$task" finished complete "$log_file" "$$" 0
  trap - EXIT
}

recovery_sheet() {
  local backup_id="$1" root target
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  python3 - "$target" "$backup_id" <<'PY'
import json, pathlib, shlex, sys
target, backup_id = pathlib.Path(sys.argv[1]), sys.argv[2]
manifest_path = target / "manifest.json"
if manifest_path.is_symlink(): raise SystemExit(18)
manifest = json.loads(manifest_path.read_text())
print('Content-Type: text/plain; charset=utf-8\r\nContent-Disposition: attachment; filename="recovery-' + backup_id + '.txt"\r\nCache-Control: no-store\r\n\r\n', end='')
print('LoxBerry Host Backup - Recovery-Blatt\n')
print('Backup:', backup_id, '\nQuelle:', target, '\nStatus:', manifest.get('status'))
print('Metadaten:', manifest.get('metadata', {}).get('mode', 'legacy-unknown'))
print('Format:', manifest.get('backup', {}).get('storage_format', 'directory'))
print('Architektur:', manifest.get('host', {}).get('architecture', 'unbekannt'))
if manifest.get('backup', {}).get('storage_format') == 'portable-repository':
    print('''
Dieser Stand besteht aus geteilten Repository-Daten, nicht aus einem eigenstaendigen TAR.
Wiederherstellung benoetigt das gesamte .portable-repository UND die separat gesicherte
geheime Recovery-JSON-Datei. Dieses Blatt enthaelt keinen Schluessel.

1. Vertrauenswuerdige HostBackup-Laufzeit in einem passenden Linux-Rescue-System verwenden.
2. Repository einbinden. Bei Verlust des alten Hosts mit Recovery-Datei WIEDERANBINDEN;
   niemals ein neues Repository ueber die alten Daten initialisieren.
3. Fuer die Bereitstellung einen separaten leeren, rootgeschuetzten Linux-Staging-Ordner
   mit Platz fuer alle logischen Daten plus 20 Prozent und mindestens 1 GiB Reserve waehlen.
4. Details und vollstaendige Befehle: docs/PORTABLE-REPOSITORY.md im Plugin-Paket.
5. Vorschau (laedt die Daten ins Staging, schreibt noch nicht ins Ziel):
''')
    print('/usr/local/sbin/loxberryhostbackup repository-recover', shlex.quote(backup_id),
          '/mnt/staging/leerer-ordner /mnt/recovery-root', "'[]'")
    print('''
Separaten Quell-Volumes bewusst Ziel-Volumes zuordnen. Vor jeder Ausfuehrung Datenverlust
durch ersetzte/geloeschte Zieldateien pruefen. HOSTBACKUP_OFFLINE_RESTORE=1 und --execute
sind erst nach dieser Kontrolle zu verwenden. Pro Lauf leeres Staging verwenden; es wird
nicht automatisch bereinigt. Das Ziel / bleibt gesperrt. Kein automatischer x86/ARM-Umzug.
Bootloader, Partitionen, fstab, Dienste und erfolgreicher Systemstart sind separat zu pruefen.
''')
    raise SystemExit(0)
print('''
1. Backup-Datentraeger getrennt verwahren; dieses Blatt ist kein Nachweis eines Restoretests.
2. Passendes Rescue-System starten. Backup-Medium lesbar und Zielsystem separat mounten.
3. Vertrauenswuerdige HostBackup-Installation verwenden, Backup-Speicher registrieren und
   vorab die lokale Import-/Strukturpruefung ausfuehren. Keine Hilfsskripte aus dem Backup als root ausfuehren.
4. Offline-Ziel z.B. /mnt/recovery-root anlegen/mounten. Das muss der ZIEL-Datentraeger sein.
5. Vorschau aufrufen und jede Auslassung/Loeschung kontrollieren:
''')
print('/usr/local/sbin/loxberryhostbackup restore-plan', shlex.quote(backup_id), '/mnt/recovery-root')
print('''
Separate Quell-Volumes werden NICHT automatisch restauriert. Die Volume-Zuordnung ist
eine JSON-Liste: [{"source":"/media/data","destination":"/mnt/recovery-root/media/data"}].
Die Quelldaten muessen im Backup enthalten und im Mount-Inventar aufgezeichnet sein.
Die JSON-Liste als weiteren Parameter an restore-plan bzw. nach Zielpfad an restore uebergeben.

6. Erst nach Kontrolle aus der Rescue-Konsole starten:
''')
print('ALLOW_RESTORE=1 HOSTBACKUP_OFFLINE_RESTORE=1 /usr/local/sbin/loxberryhostbackup restore', shlex.quote(backup_id), 'confirm-degraded /mnt/recovery-root')
print('''
confirm-degraded bestaetigt bewusst reduzierte oder unbekannte Metadaten; ein fehlerhaftes
Backup wird dadurch nicht zugelassen. Native-Restore kann Dateien im freigegebenen Zielbereich
loeschen. Gespeicherte Ausschluesse bleiben geschuetzt. Portable Archive loescht keine zusaetzlichen Dateien.
7. Bootpartition/Bootloader, fstab, Volume-Zuordnungen, Netzwerk, Dienste und Anwendungen pruefen.
   Das Plugin partitioniert keine Datentraeger und installiert keinen Bootloader automatisch.
8. Erst nach erfolgreichem Teststart gilt der komplette Disaster-Recovery-Ablauf als getestet.
''')
PY
}

prune_old_backups() {
  local root preview digest
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock exclusive
  preview="$(maintenance_helper retention "$root" --caller-pid "$$")" || return
  digest="$(printf '%s' "$preview" | python3 -c 'import json,sys; print(json.load(sys.stdin)["preview_digest"])')" || return
  maintenance_helper retention "$root" --apply "$digest" --caller-pid "$$"
}

maintenance_helper() {
  python3 "$LBP_BINDIR/hostbackup-maintenance.py" "$@" --state "$ROOT_STATE_DIR" --config "$CONFIG_FILE"
}

plugin_version() {
  if [ -f "$LBP_BINDIR/runtime-version" ] && [ ! -L "$LBP_BINDIR/runtime-version" ]; then
    head -c 100 "$LBP_BINDIR/runtime-version" | tr -d '\r\n'
  elif [ -f "$LBP_BINDIR/../plugin.cfg" ] && [ ! -L "$LBP_BINDIR/../plugin.cfg" ]; then
    sed -n 's/^VERSION=//p' "$LBP_BINDIR/../plugin.cfg" | head -n 1 | tr -d '\r\n'
  else
    printf unknown
  fi
}

maintenance_config() {
  require_root_for_write
  acquire_operation_lock exclusive
  python3 - "$CONFIG_FILE" "${1:?Settings JSON required}" <<'PY'
import fcntl, json, os, pathlib, sys, tempfile
path = pathlib.Path(sys.argv[1])
changes = json.loads(sys.argv[2])
bounds = {'keep_backups': (1,3650), 'keep_daily': (0,3650), 'keep_weekly': (0,520), 'keep_monthly': (0,120),
          'log_retention_days': (1,3650), 'quarantine_retention_days': (1,3650), 'integrity_interval_days': (1,365)}
if not isinstance(changes, dict) or set(changes) - set(bounds) - {'retention_mode','integrity_enabled'}:
    raise SystemExit('Ungueltige Wartungseinstellungen.')
for key, value in changes.items():
    if key in bounds and (type(value) is not int or not bounds[key][0] <= value <= bounds[key][1]):
        raise SystemExit('Ungueltiger Zahlenwert: ' + key)
if 'retention_mode' in changes and changes['retention_mode'] not in ('count','gfs'):
    raise SystemExit('Aufbewahrungsmodus muss count oder gfs sein.')
if 'integrity_enabled' in changes and type(changes['integrity_enabled']) is not bool:
    raise SystemExit('Inhaltspruefung muss true oder false sein.')
lock_fd = os.open(str(path) + '.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
with os.fdopen(lock_fd, 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as source: data = json.load(source)
    data.update(changes)
    if data.get('retention_mode') == 'gfs' and sum(data.get(k,v) for k,v in [('keep_daily',7),('keep_weekly',4),('keep_monthly',6)]) == 0:
        raise SystemExit('Mindestens eine GFS-Aufbewahrung muss groesser als 0 sein.')
    fd, tmp = tempfile.mkstemp(prefix='.config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2); out.write('\n'); out.flush(); os.fsync(out.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
print(json.dumps({'status':'ok','settings':data}))
PY
}

maintenance_action() {
  local action="$1" root backup_id="${2:-}"
  root="$(backup_root)"
  case "$action" in
    cleanup-runtime)
      [ -z "${3:-}" ] || require_root_for_write
      acquire_operation_lock exclusive
      if [ -n "${3:-}" ]; then maintenance_helper cleanup-runtime --apply "$3"; else maintenance_helper cleanup-runtime; fi
      return ;;
    diagnostics)
      local version
      version="$(plugin_version)"
      if [ -n "$backup_id" ]; then
        valid_task_name "$backup_id" || return 11
        maintenance_helper diagnostics --version "$version" --task "$backup_id"
      else maintenance_helper diagnostics --version "$version"; fi
      return ;;
  esac
  verify_backup_target "$root" false
  case "$action" in
    protect|retention|record-restore-test) require_root_for_write; acquire_operation_lock exclusive ;;
    *) acquire_operation_lock shared ;;
  esac
  if [ -n "$backup_id" ] && [ "$action" != diagnostics ]; then
    require_backup_id "$backup_id"
    acquire_backup_lock "$backup_id" shared
    safe_backup_target "$root" "$backup_id" >/dev/null
  fi
  case "$action" in
    storage) maintenance_helper storage "$root" ;;
    protect) maintenance_helper protect "$root" "$backup_id" "${3:?true or false required}" ;;
    inspect) inspect_backup_directory "$(safe_backup_target "$root" "$backup_id")" ;;
    report) maintenance_helper integrity "$root" "$backup_id" --report ;;
    record-restore-test)
      maintenance_helper record-restore-test "$root" "$backup_id" --result "${3:?RESULT required}" --tested-at "${4:?DATE required}" --note "${5:-}" ;;
    retention)
      if [ -n "${3:-}" ]; then maintenance_helper retention "$root" --apply "$3"; else maintenance_helper retention "$root"; fi ;;
  esac
}

start_integrity_check() {
  require_root_for_write
  local backup_id="$1" root target task log_file pid
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" exclusive
  target="$(safe_backup_target "$root" "$backup_id")"
  task="verify-$backup_id-$(date +%s)-$$.log"
  log_file="$TASK_LOG_DIR/$task"
  prepare_log_file "$log_file" truncate
  pid="$(launch_background "$task" "$log_file" "$0" verify-worker "$backup_id" "$task")"
  [ -n "$pid" ] || return 14
  printf '%s\n' "$task"
}

integrity_worker() {
  local backup_id="$1" task="$2" root target log_file report status
  require_root_for_write
  require_backup_id "$backup_id"
  valid_task_name "$task" || return 11
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" exclusive
  target="$(safe_backup_target "$root" "$backup_id")"
  log_file="$TASK_LOG_DIR/$task"
  task_state_write "$task" running verifying "$log_file" "$$" ""
  install_task_failure_trap "$task" "$log_file"
  inspect_backup_directory "$target"
  report="$(maintenance_helper integrity "$root" "$backup_id" --verify)"
  printf '%s\n' "$report"
  status="$(printf '%s' "$report" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  case "$status" in verified|ok|baseline_created) ;; *) return 19 ;; esac
  task_state_write "$task" finished "$status" "$log_file" "$$" 0
  trap - EXIT
}

integrity_schedule() {
  [ "$(json_get_bool integrity_enabled)" = true ] || return 0
  require_root_for_write
  local root due backup_id
  root="$(backup_root)"
  verify_backup_target "$root" false
  # A shared lock prevents a backup/restore/cleanup from changing the inventory.
  acquire_operation_lock shared
  due="$(maintenance_helper integrity-due "$root")"
  backup_id="$(printf '%s' "$due" | python3 -c 'import json,sys; ids=json.load(sys.stdin)["backup_ids"]; print(ids[0] if ids else "")')"
  [ -n "$backup_id" ] || return 0
  start_integrity_check "$backup_id"
}

task_overview() {
  local root=""
  root="$(backup_root)"
  verify_backup_target "$root" false >/dev/null 2>&1 || root=""
  python3 "$LBP_BINDIR/hostbackup-overview.py" overview --config "$CONFIG_FILE" --root "$root" --state "$ROOT_STATE_DIR"
}

backup_preview() {
  local root reference="" preflight excludes
  root="$(backup_root)"
  verify_backup_target "$root" false
  preflight="$(preflight_backup)"
  if [ "$(json_get_string backup_mode)" = snapshot ] && [ "$(metadata_mode)" != portable-archive ]; then
    reference="$(latest_complete_backup "$root")"
    [ -z "$reference" ] || reference="$(basename -- "$reference")"
  fi
  excludes="$(backup_excludes "$root")"
  printf '%s' "$excludes" | python3 -c 'import json,sys; print(json.dumps({"excludes":sys.stdin.read().splitlines(),"preflight":json.loads(sys.argv[1])}))' "$preflight" \
    | python3 "$LBP_BINDIR/hostbackup-overview.py" preview --config "$CONFIG_FILE" --root "$root" --reference "$reference"
}

usage() {
  cat <<EOF
Usage: $0 ACTION [ARG]

Actions:
  backup [NAME]          Create a full host backup
  start [NAME] [accept-warnings] Start a host backup in the background
  preflight-backup       Check whether backup can start
  preflight-restore ID   Check whether restore can start
  config                 Print plugin config as JSON
  target-info            Show backup target filesystem information as JSON
  stop-targets           List selectable Docker/systemd stop targets as JSON
  save-config ARGS       Save plugin config
  install-schedule       Install or remove the configured cron schedule
  schedule-run           Run configured schedule with monthly fallback logic
  recover-services [--scheduled] Retry recovery journals; scheduled mode silently skips a busy operation lock
  task-overview          Show current/history tasks, target and next scheduled start
  backup-preview         Show saved sources, excludes and snapshot reference
  repository-status     Show portable repository readiness without exposing keys
  repository-init       Initialise repository at the saved registered target
  repository-key-export Stream secret recovery JSON; save off-host, never into logs
  repository-confirm-key Confirm the separately downloaded recovery key
  repository-stage ID EMPTY_LINUX_DIR Materialise one authenticated stand offline
  repository-recover ID STAGE DEST [MAP_JSON] [--execute] Offline staged system restore
  repository-prune [--confirm-repository-id ID] Preview, or explicitly reclaim wholly unused packs
  storage-info           Measure logical/allocated/shared and local state storage
  tasks                  List task logs as JSON
  task-log TASK [LINES]  Print recent task log lines
  task-status TASK [N]   Print task status and recent log as JSON
  stop BACKUP_ID         Stop a running backup and restart stopped services/containers
  list                   List backups as JSON
  export BACKUP_ID       Create/export BACKUP_ID.tar.gz
  start-export BACKUP_ID Create/export BACKUP_ID.tar.gz in the background
  export-info BACKUP_ID  Show export archive status as JSON
  download-export ID     Stream checked archive including HTTP download headers
  download-log TASK      Stream complete original log including HTTP headers
  delete-export BACKUP_ID Delete the export archive for BACKUP_ID
  import ARCHIVE.tar.gz   Import an exported backup archive
  start-import ARCHIVE.tar.gz Import an exported backup archive in the background
  move BACKUP_ID DIR      Move a backup and its export archive to DIR
  browse BACKUP_ID [PATH] List files inside a backup as JSON
  cat-file BACKUP_ID PATH Print one file from a backup
  delete BACKUP_ID       Delete a backup
  restore-plan ID [DEST] [MAP_JSON] Preview actual file changes and omitted volumes
  restore ID [confirm-degraded] [DEST] [MAP_JSON] Requires ALLOW_RESTORE=1
  start-restore ID [confirm-degraded] [DEST] [MAP_JSON] Restore in background
  restore-files ID PATH DEST Restore into a fresh recovered-* directory
  recovery-sheet ID      Download backup-specific offline recovery instructions
  inspect-backup ID      Locally inspect stored backup structure
  verify-backup ID       Start comparison with local integrity baseline
  verification-report ID Print last integrity report as JSON
  record-restore-test ID RESULT DATE NOTE Document an external manual restore test
  integrity-schedule    Check one due backup when optional integrity is enabled
  protect-backup ID true|false  Protect a backup against cleanup/deletion
  maintenance-config JSON Save validated retention/integrity settings
  maintenance-preview  Show the current retention deletion plan and digest
  maintenance-run DIGEST Apply the unchanged, previously inspected deletion plan
  runtime-cleanup-preview Show old log/quarantine cleanup plan
  runtime-cleanup-run DIGEST Apply the unchanged runtime cleanup plan
  diagnostics [TASK]    Download redacted diagnostics and optional original log
EOF
}

action="${1:-}"
case "$action" in
  backup) shift; create_backup "${1:-}" ;;
  start) shift; start_backup "${1:-}" "${2:-}" ;;
  preflight-backup) preflight_backup ;;
  preflight-restore) shift; preflight_restore "${1:?BACKUP_ID required}" ;;
  config) show_config ;;
  target-info) backup_target_info ;;
  source-info) source_info ;;
  repository-status) repository_action status ;;
  repository-init) repository_action init ;;
  repository-key-export) repository_action key-export ;;
  repository-confirm-key) repository_action confirm-key ;;
  repository-stage) shift; repository_stage "${1:?BACKUP_ID required}" "${2:?EMPTY_LINUX_STAGING_DIRECTORY required}" ;;
  repository-recover) shift; repository_recover "${1:?BACKUP_ID required}" "${2:?EMPTY_LINUX_STAGING_DIRECTORY required}" "${3:?OFFLINE_DESTINATION required}" "${4:-[]}" "${5:-}" ;;
  repository-prune) shift; repository_prune "$@" ;;
  stop-targets) discover_stop_targets ;;
  save-config) shift; save_config "${1:-}" "${2:-}" "${3:-false}" "${4:-false}" "${5:-10}" "${6:-false}" "${7:-daily}" "${8:-02:00}" "${9:-0}" "${10:-1}" "${11-*}" "${12-0}" "${13-1}" "${14:-}" "${15:-}" "${16:-false}" "${17:-full}" "${18:-}" "${19:-false}" "${20:-}" "${21:-true}" "${22:-true}" "${23:-true}" "${24:-true}" "${25:-native-strict}" "${26:-}" ;;
  install-schedule) install_schedule ;;
  schedule-run) schedule_run ;;
  recover-services) shift; recover_restart_journals "$@" ;;
  tasks) list_tasks ;;
  task-overview) task_overview ;;
  backup-preview) backup_preview ;;
  storage-info) maintenance_action storage ;;
  inspect-backup) shift; maintenance_action inspect "${1:?BACKUP_ID required}" ;;
  protect-backup) shift; maintenance_action protect "${1:?BACKUP_ID required}" "${2:?true or false required}" ;;
  verify-backup) shift; start_integrity_check "${1:?BACKUP_ID required}" ;;
  verify-worker) shift; integrity_worker "${1:?BACKUP_ID required}" "${2:?TASK required}" ;;
  integrity-schedule) integrity_schedule ;;
  verification-report) shift; maintenance_action report "${1:?BACKUP_ID required}" ;;
  record-restore-test) shift; maintenance_action record-restore-test "${1:?BACKUP_ID required}" "${2:?RESULT required}" "${3:?DATE required}" "${4:-}" ;;
  maintenance-config) shift; maintenance_config "${1:?JSON required}" ;;
  maintenance-preview) maintenance_action retention ;;
  maintenance-run) shift; maintenance_action retention "" "${1:?DIGEST required}" ;;
  runtime-cleanup-preview) maintenance_action cleanup-runtime ;;
  runtime-cleanup-run) shift; maintenance_action cleanup-runtime "" "${1:?DIGEST required}" ;;
  diagnostics) shift; maintenance_action diagnostics "${1:-}" ;;
  task-log) shift; show_task_log "${1:?TASK required}" "${2:-300}" ;;
  task-status) shift; task_status "${1:?TASK required}" "${2:-400}" ;;
  stop) shift; stop_backup "${1:?BACKUP_ID required}" ;;
  list) list_backups ;;
  export) shift; export_backup "${1:?BACKUP_ID required}" ;;
  start-export) shift; start_export "${1:?BACKUP_ID required}" ;;
  export-info) shift; export_info "${1:?BACKUP_ID required}" ;;
  download-export) shift; download_export "${1:?BACKUP_ID required}" ;;
  download-log) shift; download_log "${1:?TASK required}" ;;
  delete-export) shift; delete_export "${1:?BACKUP_ID required}" ;;
  import) shift; import_backup "${1:?ARCHIVE required}" ;;
  start-import) shift; start_import "${1:?ARCHIVE required}" ;;
  move) shift; move_backup "${1:?BACKUP_ID required}" "${2:?DIR required}" ;;
  browse) shift; browse_backup "${1:?BACKUP_ID required}" "${2:-}" ;;
  cat-file) shift; cat_backup_file "${1:?BACKUP_ID required}" "${2:?PATH required}" ;;
  delete) shift; delete_backup "${1:?BACKUP_ID required}" ;;
  restore-plan) shift; restore_plan "${1:?BACKUP_ID required}" "${2:-/}" "${3:-[]}" ;;
  restore) shift; restore_backup "${1:?BACKUP_ID required}" "${2:-false}" "${3:-${HOSTBACKUP_RESTORE_DEST:-/}}" "${4:-[]}" ;;
  start-restore) shift; start_restore "${1:?BACKUP_ID required}" "${2:-false}" "${3:-/}" "${4:-[]}" ;;
  restore-files) shift; start_restore_files "${1:?BACKUP_ID required}" "${2:?PATH required}" "${3:?DEST required}" ;;
  restore-files-worker) shift; restore_files_worker "${1:?BACKUP_ID required}" "${2:?PATH required}" "${3:?DEST required}" "${4:?TASK required}" ;;
  recovery-sheet) shift; recovery_sheet "${1:?BACKUP_ID required}" ;;
  *) usage; exit 1 ;;
esac
