#!/bin/bash
set -euo pipefail

PLUGIN_NAME="loxberryhostbackup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_FOLDER="$(basename "$SCRIPT_DIR")"
if [[ "$SCRIPT_DIR" == */bin/plugins/* ]]; then
  DETECTED_LBHOMEDIR="${SCRIPT_DIR%/bin/plugins/$PLUGIN_FOLDER}"
else
  DETECTED_LBHOMEDIR="/opt/loxberry"
  PLUGIN_FOLDER="$PLUGIN_NAME"
fi
LBHOMEDIR="${LBHOMEDIR:-$DETECTED_LBHOMEDIR}"
LBP_BINDIR="${LBPBINDIR:-$SCRIPT_DIR}"
LBP_CONFIGDIR="${LBPCONFIGDIR:-${LBPCONFIG:-$LBHOMEDIR/config/plugins/$PLUGIN_FOLDER}}"
LBP_DATADIR="${LBPDATADIR:-${LBPDATA:-$LBHOMEDIR/data/plugins/$PLUGIN_FOLDER}}"
LBP_LOGDIR="${LBPLOGDIR:-${LBPLOG:-$LBHOMEDIR/log/plugins/$PLUGIN_FOLDER}}"
CONFIG_FILE="$LBP_CONFIGDIR/config.json"
OPERATION_LOCK_FILE="${HOSTBACKUP_OPERATION_LOCK_FILE:-/var/lock/${PLUGIN_FOLDER}.operation.lock}"
if [ "$LBHOMEDIR" = "/opt/loxberry" ]; then
  ROOT_STATE_DIR="/var/lib/$PLUGIN_FOLDER"
else
  ROOT_STATE_DIR="$LBP_DATADIR/root-state"
fi
LOCK_DIR="$ROOT_STATE_DIR/locks"
TASK_DIR="$ROOT_STATE_DIR/tasks"
ROOT_IMPORT_DIR="$ROOT_STATE_DIR/imports"
QUARANTINE_DIR="$ROOT_STATE_DIR/import-quarantine"
TARGET_MARKER_NAME=".loxberry-hostbackup-target"
BACKUP_MARKER_NAME=".loxberry-hostbackup-backup"
DEFAULT_IMPORT_MAX_MB=65536

for runtime_dir in "$LBP_CONFIGDIR" "$LBP_DATADIR" "$LBP_LOGDIR"; do
  [ ! -L "$runtime_dir" ] || { echo "Unsafe symlink runtime directory: $runtime_dir" >&2; exit 13; }
  mkdir -p -- "$runtime_dir"
done
[ ! -L "$ROOT_STATE_DIR" ] && [ ! -L "$LOCK_DIR" ] && [ ! -L "$TASK_DIR" ] && [ ! -L "$ROOT_IMPORT_DIR" ] && [ ! -L "$QUARANTINE_DIR" ] || { echo "Unsafe root state directory symlink." >&2; exit 13; }
mkdir -p -- "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"
[ -d "$ROOT_STATE_DIR" ] && [ ! -L "$ROOT_STATE_DIR" ] || { echo "Root state directory is unsafe." >&2; exit 13; }
chmod 700 "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR" 2>/dev/null || true

if [ "$(id -u)" -eq 0 ]; then
  for secure_dir in "$LBP_LOGDIR" "$ROOT_STATE_DIR" "$LOCK_DIR" "$TASK_DIR" "$ROOT_IMPORT_DIR" "$QUARANTINE_DIR"; do
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
    $cfg->{keep_backups} = 10 if $cfg->{keep_backups} > 10;
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
  local schedule_months="${11:-*}"
  local schedule_weekdays="${12:-$schedule_weekday}"
  local schedule_monthdays="${13:-$schedule_monthday}"
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

  case "$metadata_mode" in
    native-strict|network-compatible|fake-super|portable-archive) ;;
    *) metadata_mode="native-strict" ;;
  esac
  prepare_target_registration "$backup_root"
  [ -n "$backup_root" ] && backup_root="$REGISTERED_ROOT"

  [ ! -L "$CONFIG_FILE.lock" ] || { echo "Unsafe configuration lock symlink." >&2; return 13; }
  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MFcntl=:DEFAULT,:flock -MIO::Handle -e '
    my ($file, $backup_root, $excludes_text, $stop_docker, $create_export, $keep_backups, $schedule_enabled, $schedule_mode, $schedule_time, $schedule_weekday, $schedule_monthday, $schedule_months, $schedule_weekdays, $schedule_monthdays, $pre_hook, $post_hook, $root_permission_ack, $backup_mode, $stop_targets_text, $mail_notify_enabled, $mail_notify_to, $mail_notify_success, $mail_notify_failure, $mail_notify_stopped, $mail_notify_restore, $metadata_mode, $target_marker, $target_mountpoint, $target_source, $target_fstype, $target_majmin) = @ARGV;
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
    $keep_backups = 10 if $keep_backups > 10;
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
    my ($fh, $tmp) = tempfile(".config-XXXXXX", DIR => dirname($file), UNLINK => 0);
    chmod 0600, $tmp or die "Cannot chmod config temp: $!";
    print $fh JSON::PP->new->ascii->pretty->canonical->encode($cfg) or die "Cannot write config: $!";
    $fh->flush or die "Cannot flush config: $!";
    $fh->sync or die "Cannot sync config: $!";
    close $fh or die "Cannot close config: $!";
    rename $tmp, $file or die "Cannot replace config: $!";
  ' "$CONFIG_FILE" "$backup_root" "$excludes_text" "$stop_docker" "$create_export" "$keep_backups" "$schedule_enabled" "$schedule_mode" "$schedule_time" "$schedule_weekday" "$schedule_monthday" "$schedule_months" "$schedule_weekdays" "$schedule_monthdays" "$pre_hook" "$post_hook" "$root_permission_ack" "$backup_mode" "$stop_targets" "$mail_notify_enabled" "$mail_notify_to" "$mail_notify_success" "$mail_notify_failure" "$mail_notify_stopped" "$mail_notify_restore" "$metadata_mode" "$REGISTERED_MARKER" "$REGISTERED_MOUNTPOINT" "$REGISTERED_SOURCE" "$REGISTERED_FSTYPE" "$REGISTERED_MAJMIN"
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
  local mode="${1:-exclusive}"
  [ "${HOSTBACKUP_OPERATION_LOCK_HELD:-0}" = "1" ] && return 0
  [ ! -L "$OPERATION_LOCK_FILE" ] || { echo "Unsafe operation lock symlink." >&2; return 13; }
  exec 9>"$OPERATION_LOCK_FILE"
  if [ "$mode" = "shared" ]; then
    flock -n -s 9 || { echo "Another HostBackup operation is active." >&2; return 5; }
  else
    flock -n -x 9 || { echo "Another HostBackup operation is active." >&2; return 5; }
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
  local root probe fs_type source available_mb backup_mode status message linux_fs mode verify_message mountpoint majmin
  root="$(backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  mode="$(metadata_mode)"
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
  local day fallback_start fallback_day normalized_monthdays
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
    command_line="$LBP_BINDIR/hostbackup.sh schedule-run"
  else
    month_field="*"
  fi

  command_line="${command_line:-$LBP_BINDIR/hostbackup.sh start}"
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
    return 0
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
    "$LBP_LOGDIR"/*) ;;
    *) echo "Unsafe log path: $path" >&2; return 14 ;;
  esac
  [ -d "$LBP_LOGDIR" ] && [ ! -L "$LBP_LOGDIR" ] || { echo "Unsafe log directory: $LBP_LOGDIR" >&2; return 14; }
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
    backup-*.log|restore-*.log|export-*.log|import-*.log) ;;
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
  local task="$1" state="$2" phase="$3" log_file="$4" pid="${5:-$$}" exit_status="${6:-}"
  local path start_ticks
  path="$(task_state_path "$task")" || return 1
  start_ticks="$(process_start_ticks "$pid")"
  perl -MJSON::PP -MFile::Basename=dirname -MFile::Temp=tempfile -MIO::Handle -e '
    my ($file, $task, $state, $phase, $log, $pid, $ticks, $exit_status) = @ARGV;
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
  ' "$path" "$task" "$state" "$phase" "$log_file" "$pid" "$start_ticks" "$exit_status"
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
  task_state_write "$task" running launched "$log_file" "$pid" ""
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
}

tar_metadata_options() {
  printf '%s\n' '--format=pax' '--numeric-owner' '--acls' '--xattrs' '--xattrs-include=*' '--selinux' '--sparse'
}

METADATA_PROBE_MESSAGE=""
metadata_capability_probe() {
  local root="$1" mode="$2" source_dir target_dir archive status=0
  local -a options=()
  verify_backup_target "$root" true || return 1
  source_dir="$(mktemp -d "$LBP_DATADIR/.metadata-source.XXXXXX")"
  target_dir="$root/.metadata-probe.$$"
  archive="$root/.metadata-probe.$$.tar"
  trap 'rm -rf -- "$source_dir" "$target_dir"; rm -f -- "$archive"' RETURN
  mkdir -p -- "$source_dir/sub"
  printf 'metadata-probe\n' > "$source_dir/sub/file"
  ln "$source_dir/sub/file" "$source_dir/sub/hardlink"
  ln -s sub/file "$source_dir/symlink"
  dd if=/dev/zero of="$source_dir/sparse" bs=1 count=0 seek=1048576 2>/dev/null
  chmod 6750 "$source_dir/sub/file"
  if command -v setfattr >/dev/null 2>&1; then
    setfattr -n user.loxberryhostbackup -v probe "$source_dir/sub/file" || status=1
  fi
  if command -v setfacl >/dev/null 2>&1; then
    setfacl -m u:daemon:r-- "$source_dir/sub/file" || status=1
  fi

  if [ "$mode" = "portable-archive" ]; then
    while IFS= read -r opt; do options+=("$opt"); done < <(tar_metadata_options)
    tar "${options[@]}" -C "$source_dir" -cpf "$archive" . || status=1
    tar -tf "$archive" >/dev/null 2>&1 || status=1
  else
    while IFS= read -r opt; do options+=("$opt"); done < <(rsync_metadata_options "$mode" backup)
    rsync "${options[@]}" "$source_dir/" "$target_dir/" >/dev/null 2>&1 || status=1
    [ -f "$target_dir/sub/file" ] && [ -L "$target_dir/symlink" ] || status=1
    [ "$(stat -c '%i' "$target_dir/sub/file" 2>/dev/null)" = "$(stat -c '%i' "$target_dir/sub/hardlink" 2>/dev/null)" ] || status=1
    if [ "$mode" = "native-strict" ] && command -v getfattr >/dev/null 2>&1 && command -v setfattr >/dev/null 2>&1; then
      getfattr -n user.loxberryhostbackup "$target_dir/sub/file" >/dev/null 2>&1 || status=1
    fi
    if [ "$mode" = "fake-super" ]; then
      command -v getfattr >/dev/null 2>&1 || status=1
      getfattr -d -m '^user\.rsync\.' "$target_dir/sub/file" 2>/dev/null | grep 'user.rsync.' >/dev/null || status=1
    fi
  fi
  verify_backup_target "$root" true || status=1
  rm -rf -- "$source_dir" "$target_dir"
  rm -f -- "$archive"
  trap - RETURN
  if [ "$status" -ne 0 ]; then
    METADATA_PROBE_MESSAGE="Metadaten-Roundtrip fuer Modus $mode ist fehlgeschlagen."
    return 1
  fi
  METADATA_PROBE_MESSAGE="Metadaten-Roundtrip fuer Modus $mode erfolgreich."
  return 0
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
        storage_format => ($metadata_mode eq "portable-archive" ? "portable-tar" : "directory"),
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
        log "Stopping Docker container $name ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker stop -t 30 "$id" || failed=1
        else
          docker stop -t 30 "$id" || failed=1
        fi
        if [ "$(docker inspect --format '{{.State.Running}}' "$id" 2>/dev/null || true)" = "false" ]; then
          printf '%s\t%s\n' "$id" "$name" >> "$state_dir/docker-running-containers.tsv"
          printf '%s\n' "$id" >> "$state_dir/docker-running-containers.txt"
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
      log "Stopping systemd service $unit"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 systemctl stop "$unit" || failed=1
      else
        systemctl stop "$unit" || failed=1
      fi
      if ! systemctl is-active --quiet "$unit" 2>/dev/null; then
        printf '%s\n' "$unit" >> "$state_dir/systemd-running-services.txt"
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
      log "Stopping Docker container $name (${id:-unknown})"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 docker stop -t 30 "$name" || failed=1
      else
        docker stop -t 30 "$name" || failed=1
      fi
      if [ "$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)" = "false" ]; then
        printf '%s\t%s\n' "${id:-$name}" "$name" >> "$state_dir/docker-running-containers.tsv"
        printf '%s\n' "${id:-$name}" >> "$state_dir/docker-running-containers.txt"
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
  selected_stop_targets > "$targets_file" || true
  if [ -s "$targets_file" ]; then
    log "Stopping selected native services and Docker containers if they are running"
    stop_selected_systemd_targets "$state_dir" "$targets_file"
    stop_selected_docker_targets "$state_dir" "$targets_file"
  else
    log "No individual stop targets configured; checking legacy Docker option"
    stop_docker_if_requested "$state_dir"
  fi
}

start_docker_if_needed() {
  local state_dir="$1"
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
  log_restart_targets "$state_dir"
  start_docker_if_needed "$state_dir" || failed=1
  start_systemd_if_needed "$state_dir" || failed=1
  return "$failed"
}

backup_cleanup_on_exit() {
  local status="$1"
  local state_dir="$2"
  local log_file="$3"
  local already_restarted="$4"
  local post_hook="${5:-}"
  local task="${6:-}"
  local cleanup_failed=0

  [ -n "$state_dir" ] && [ -d "$state_dir" ] || return 0

  if [ "$already_restarted" != "true" ] && [ ! -e "$state_dir/restart.done" ] && { [ -s "$state_dir/docker-running-containers.tsv" ] || [ -s "$state_dir/docker-running-containers.txt" ] || [ -s "$state_dir/systemd-running-services.txt" ]; }; then
    if [ -n "$log_file" ]; then
      log "Cleanup: restarting services and Docker containers after interrupted backup (exit status $status)" | tee -a "$log_file" || true
      start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file" || cleanup_failed=1
    else
      log "Cleanup: restarting services and Docker containers after interrupted backup (exit status $status)" || true
      start_backup_targets_if_needed "$state_dir" || cleanup_failed=1
    fi
    [ "$cleanup_failed" -eq 0 ] && write_control_marker "$state_dir/restart.done"
  fi
  if [ ! -e "$state_dir/post-hook.started" ] && [ ! -e "$state_dir/post-hook.done" ]; then
    write_control_marker "$state_dir/post-hook.started"
    if ! run_hook "$post_hook" 2>&1 | tee -a "$log_file"; then
      cleanup_failed=1
    fi
    write_control_marker "$state_dir/post-hook.done"
  fi
  if [ -n "$task" ] && [ "$status" -ne 0 ]; then
    task_state_write "$task" failed "$([ "$cleanup_failed" -eq 0 ] && printf failed || printf cleanup_failed)" "$log_file" "$$" "$status" || true
  fi
  if [ "$status" -ne 0 ] && [ -r "$state_dir/manifest.json" ]; then
    local backup_id started size files
    backup_id="$(basename -- "$state_dir")"
    started="$(manifest_started_at "$state_dir")"
    [ -n "$started" ] || started="$(date -Iseconds)"
    size="$(calculate_size "$state_dir")"
    files="$(calculate_files "$state_dir")"
    write_manifest "$state_dir" "$backup_id" "$([ "$cleanup_failed" -eq 0 ] && printf failed || printf cleanup_failed)" "$started" "$(date -Iseconds)" "$size" "$files" || true
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
      grep -Eq '^\./?etc(/|$)' "$list_file" && etc_ok=true || etc_ok=false
      grep -Eq '^\./?opt/loxberry(/|$)' "$list_file" && loxberry_ok=true || loxberry_ok=false
      grep -Eq '^\./?var/lib(/|$)' "$list_file" && varlib_ok=true || varlib_ok=false
      grep -Eq '^\./?mnt/docker(/|$)' "$list_file" && mntdocker_ok=true || mntdocker_ok=false
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
  metadata_value="full"
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
    hardlink_value="none_found"
    if find "$target/rootfs" -xdev -type f -links +1 -print -quit 2>/dev/null | grep -q .; then
      hardlink_value="found"
    else
      hardlink_ok=false
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
        { name => "Snapshot-Hardlinks", ok => $bool->($hardlink_ok), value => $hardlink_value, optional => JSON::PP::true },
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

preflight_backup() {
  local root available_mb docker_available docker_running excludes_count status warnings_json notices_json checks_json rsync_available target_writable backup_mode fs_type mode probe_ok target_ok target_message copy_tool_name
  require_root_permission_ack
  root="$(backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  mode="$(metadata_mode)"
  target_ok=false
  target_message=""
  if target_message="$(verify_backup_target "$root" true 2>&1)"; then
    target_ok=true
  fi
  available_mb="$(df -Pm "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  fs_type="$(current_mount_value "$root" FSTYPE)"
  [ -n "$available_mb" ] || available_mb=0
  rsync_available=false
  copy_tool_name="rsync"
  if [ "$mode" = "portable-archive" ]; then
    copy_tool_name="tar"
    command -v tar >/dev/null 2>&1 && rsync_available=true
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
  if [ "$target_ok" = "true" ] && metadata_capability_probe "$root" "$mode"; then
    probe_ok=true
  fi
  if [ "$rsync_available" != "true" ] || [ "$target_writable" != "true" ] || [ "$probe_ok" != "true" ]; then
    status="error"
    warnings_json="$(perl -MJSON::PP -e 'print encode_json([$ARGV[0]])' "${target_message:-${METADATA_PROBE_MESSAGE:-Pflichtcheck fehlgeschlagen: rsync, Zielidentitaet, Schreibzugriff oder Metadatenprobe.}}")"
  elif [ "$backup_mode" = "snapshot" ] && [ "$mode" = "portable-archive" ]; then
    status="error"
    warnings_json='["Portable Archive kann nicht mit inkrementellen Snapshots kombiniert werden."]'
  elif [ "$available_mb" -lt 1024 ]; then
    status="warning"
    warnings_json='["Backup-Ziel hat weniger als 1 GB freien Speicher."]'
  elif [ "$docker_running" -gt 0 ] && [ "$(json_get_bool stop_docker_before_backup)" != "true" ] && [ "$(selected_docker_stop_count)" -eq 0 ]; then
    status="warning"
    warnings_json='["Docker-Container laufen. Fuer konsistente Datenbanken ggf. einzelne Container in den Stop-Zielen auswaehlen oder Hooks konfigurieren."]'
  fi
  if [ "$mode" = "network-compatible" ]; then
    notices_json='["Hinweis: Network Compatible laesst xattrs und File Capabilities bewusst aus. Dies ist der konfigurierte Normalbetrieb fuer CIFS-/NFS-Ziele und behindert den Backup-Start nicht."]'
  fi
  checks_json="$(cat <<EOF
[
  {"name":"Kopierwerkzeug ($copy_tool_name) verfuegbar","ok":$rsync_available},
  {"name":"Backup-Ziel beschreibbar","ok":$target_writable},
  {"name":"Backup-Modus","ok":true,"value":"$backup_mode"},
  {"name":"Metadaten-Modus","ok":$probe_ok,"value":"$mode"},
  {"name":"Dateisystem","ok":true,"value":"$fs_type"},
  {"name":"Freier Speicher MB","ok":$([ "$available_mb" -ge 1024 ] && echo true || echo false),"value":"$available_mb"},
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
  "warnings": $warnings_json,
  "notices": $notices_json,
  "checks": $checks_json
}
EOF
}

restore_eligibility() {
  local backup_id="$1" degraded_confirmation="${2:-false}"
  local root target manifest_status validation_status metadata_value storage_format
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
    [ -f "$target/rootfs.tar" ] && [ ! -L "$target/rootfs.tar" ] || { echo "Portable rootfs archive is missing." >&2; return 18; }
    [ "${HOSTBACKUP_OFFLINE_RESTORE:-0}" = "1" ] || { echo "Portable Archive Restore ist nur mit HOSTBACKUP_OFFLINE_RESTORE=1 in einer Offline-/Rescue-Umgebung erlaubt." >&2; return 18; }
  else
    perl -e 'exit((-d $ARGV[0] && !-l $ARGV[0]) ? 0 : 1)' "$target/rootfs" || { echo "Backup rootfs is not a real directory." >&2; return 18; }
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
  if [ "$storage_format" = "portable-tar" ]; then
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

  local root backup_id target rootfs log_file started finished size files exclude_file backup_mode previous_backup restart_done
  local mode task validation_status final_status post_hook pre_hook rsync_status export_status portable_excludes
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
  metadata_capability_probe "$root" "$mode" || { echo "$METADATA_PROBE_MESSAGE" >&2; exit 17; }
  backup_id="${1:-$(date '+%Y%m%d-%H%M%S')}"
  backup_id="$(printf '%s' "$backup_id" | tr -cd 'A-Za-z0-9._-')"
  require_backup_id "$backup_id"
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  target="$(strict_child_path "$root" "$root/$backup_id")" || { echo "Unsafe backup target." >&2; exit 7; }
  rootfs="$target/rootfs"
  log_file="$LBP_LOGDIR/backup-$backup_id.log"
  task="backup-$backup_id.log"
  exclude_file="$target/rsync-excludes.txt"

  if [ -e "$target" ]; then
    echo "Backup already exists: $backup_id" >&2
    exit 4
  fi

  prepare_log_file "$log_file" truncate
  mkdir -p -- "$target"
  chmod 700 "$target" 2>/dev/null || true
  write_backup_marker "$target" "$backup_id"
  if [ "$mode" != "portable-archive" ]; then
    mkdir -p -- "$rootfs"
  elif [ "$backup_mode" = "snapshot" ]; then
    echo "Portable Archive cannot be combined with snapshot mode." >&2
    exit 17
  fi
  started="$(date -Iseconds)"
  backup_excludes "$root" > "$exclude_file"
  write_manifest "$target" "$backup_id" "running" "$started" "" 0 0

  pre_hook="$(json_get_string pre_backup_hook)"
  post_hook="$(json_get_string post_backup_hook)"
  restart_done="false"
  task_state_write "$task" running initializing "$log_file" "$$" ""
  trap 'backup_cleanup_on_exit "$?" "$target" "$log_file" "$restart_done" "$post_hook" "$task"' EXIT
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
  stop_backup_targets "$target" 2>&1 | tee -a "$log_file"

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
  if [ "$mode" = "portable-archive" ]; then
    portable_excludes="$target/tar-excludes.txt"
    sed 's#^/##; /^$/d' "$exclude_file" > "$portable_excludes"
    while IFS= read -r opt; do tar_opts+=("$opt"); done < <(tar_metadata_options)
    log "Creating portable root filesystem archive" | tee -a "$log_file"
    tar "${tar_opts[@]}" --exclude-from="$portable_excludes" -C / -cpf "$target/rootfs.tar" . 2>&1 | tee -a "$log_file"
    rsync_status=${PIPESTATUS[0]}
  else
    log "Starting rsync copy from / to $rootfs" | tee -a "$log_file"
    log "rsync live output follows. Large files or slow storage can keep one line active for a while." | tee -a "$log_file"
    rsync "${metadata_opts[@]}" --delete "${rsync_opts[@]}" --exclude-from="$exclude_file" / "$rootfs/" 2>&1 | tee -a "$log_file"
    rsync_status=${PIPESTATUS[0]}
  fi
  set -e
  log "Backup copy finished with status $rsync_status" | tee -a "$log_file"
  verify_backup_target "$root" true

  log "Starting services and Docker containers again if they were stopped" | tee -a "$log_file"
  task_state_write "$task" running restarting_services "$log_file" "$$" ""
  start_backup_targets_if_needed "$target" 2>&1 | tee -a "$log_file"
  restart_done="true"
  write_control_marker "$target/restart.done"
  log "Running post-backup hook if configured" | tee -a "$log_file"
  task_state_write "$task" running post_hook "$log_file" "$$" ""
  write_control_marker "$target/post-hook.started"
  run_hook "$post_hook" 2>&1 | tee -a "$log_file"
  write_control_marker "$target/post-hook.done"

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
  validate_completed_backup "$target" "$backup_mode" "${previous_backup:-}" "$size" "$files" "$rsync_status" 2>&1 | tee -a "$log_file"
  validation_status=${PIPESTATUS[0]}
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
  write_manifest "$target" "$backup_id" "$final_status" "$started" "$finished" "$size" "$files"

  if [ "$(json_get_bool create_export_after_backup)" = "true" ]; then
    log "Creating export archive for finalized backup $backup_id" | tee -a "$log_file"
    set +e
    export_backup "$backup_id" 2>&1 | tee -a "$log_file"
    export_status=${PIPESTATUS[0]}
    set -e
    if [ "$export_status" -ne 0 ]; then
      log "Backup $backup_id failed while creating export archive" | tee -a "$log_file"
      task_state_write "$task" failed export_failed "$log_file" "$$" "$export_status"
      trap - EXIT HUP INT TERM
      notify_hostbackup "failure" 3 "LoxBerry Host Backup fehlgeschlagen" "Backup $backup_id ist beim Erstellen des Export-Archivs fehlgeschlagen." "$log_file"
      exit "$export_status"
    fi
  fi

  log "Applying backup retention policy" | tee -a "$log_file"
  prune_old_backups

  log "Backup $backup_id finished" | tee -a "$log_file"
  task_state_write "$task" finished complete "$log_file" "$$" 0
  trap - EXIT HUP INT TERM
  notify_hostbackup "success" 6 "LoxBerry Host Backup erfolgreich" "Backup $backup_id wurde erfolgreich abgeschlossen. Groesse: $size Bytes, Dateien: $files." "$log_file"
  printf '%s\n' "$backup_id"
}

start_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id log_file task accept_warnings preflight_json preflight_status pid
  backup_id="${1:-$(date '+%Y%m%d-%H%M%S')}"
  accept_warnings="${2:-}"
  backup_id="$(printf '%s' "$backup_id" | tr -cd 'A-Za-z0-9._-')"
  require_backup_id "$backup_id"
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  preflight_json="$(preflight_backup)"
  preflight_status="$(printf '%s' "$preflight_json" | perl -MJSON::PP -e 'local $/; my $d=decode_json(<STDIN>); print $d->{status} // "error";')"
  [ "$preflight_status" != "error" ] || { printf '%s\n' "$preflight_json" >&2; exit 17; }
  if [ "$preflight_status" = "warning" ] && [ "$accept_warnings" != "accept-warnings" ]; then
    printf '%s\n' "$preflight_json" >&2
    echo "Preflight-Warnungen muessen explizit bestaetigt werden." >&2
    exit 16
  fi
  log_file="$LBP_LOGDIR/backup-$backup_id.launch.log"
  task="backup-$backup_id.log"
  prepare_log_file "$log_file" truncate
  pid="$(launch_background "$task" "$log_file" "$0" backup "$backup_id")"
  [ -n "$pid" ] || { echo "Backup process could not be launched." >&2; exit 14; }
  printf '%s\n' "$backup_id"
}

stop_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1"
  local root target log_file started finished size files task pid pgid ticks current_ticks waited=0
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  target="$(strict_child_path "$root" "$root/$backup_id")" || { echo "Unsafe backup path." >&2; exit 7; }
  log_file="$LBP_LOGDIR/backup-$backup_id.log"
  task="backup-$backup_id.log"
  [ -d "$target" ] || { echo "Backup not found: $backup_id" >&2; exit 6; }
  prepare_log_file "$log_file" append

  log "Stop requested for backup $backup_id" | tee -a "$log_file"

  pid="$(task_state_value "$task" pid 2>/dev/null || true)"
  ticks="$(task_state_value "$task" process_start_ticks 2>/dev/null || true)"
  current_ticks="$(process_start_ticks "$pid")"
  if [ -n "$pid" ] && [ -n "$ticks" ] && [ "$ticks" = "$current_ticks" ] && kill -0 "$pid" 2>/dev/null; then
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

  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" exclusive
  if [ ! -e "$target/restart.done" ]; then
    log "Restarting services and Docker containers stopped by this backup if needed" | tee -a "$log_file"
    start_backup_targets_if_needed "$target" 2>&1 | tee -a "$log_file"
    write_control_marker "$target/restart.done"
  fi
  started="$(manifest_started_at "$target")"
  [ -n "$started" ] || started="$(date -Iseconds)"
  finished="$(date -Iseconds)"
  size="$(calculate_size "$target")"
  files="$(calculate_files "$target")"
  write_manifest "$target" "$backup_id" "stopped" "$started" "$finished" "$size" "$files"
  task_state_write "$task" stopped stopped "$log_file" "$$" 0
  log "Backup $backup_id stopped by user" | tee -a "$log_file"
  notify_hostbackup "stopped" 4 "LoxBerry Host Backup abgebrochen" "Backup $backup_id wurde durch den Benutzer abgebrochen. Bereits gestoppte Dienste und Container wurden wieder gestartet, soweit moeglich." "$log_file"
}

log_dirs() {
  local dir
  for dir in \
    "$LBP_LOGDIR" \
    "$LBHOMEDIR/log/plugins" \
    "$LBHOMEDIR/log/plugins/$PLUGIN_FOLDER" \
    "$LBHOMEDIR/log/ramlog/log/plugins" \
    "$LBHOMEDIR/log/ramlog/log/plugins/$PLUGIN_FOLDER"
  do
    [ -n "$dir" ] || continue
    printf '%s\n' "$dir"
  done | awk '!seen[$0]++'
}

task_log_path() {
  local task="$1"
  local dir path
  case "$task" in
    *[!A-Za-z0-9._-]*|.*|*..*|*/*) echo "Unsafe task id." >&2; exit 11 ;;
    backup-*.log|restore-*.log|export-*.log|import-*.log) ;;
    *) echo "Unsafe task id." >&2; exit 11 ;;
  esac
  while IFS= read -r dir; do
    path="$dir/$task"
    if [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ]; then
      printf '%s\n' "$path"
      return 0
    fi
  done < <(log_dirs)
  printf '%s/%s\n' "$LBP_LOGDIR" "$task"
}

list_tasks() {
  local dirs=()
  local dir
  mkdir -p "$LBP_LOGDIR"
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
      for my $name (sort grep { /^(backup|restore|export|import)-.*\.log$/ || /\.(launch)\.log$/ } readdir($dh)) {
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

list_backups() {
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
      }
      if (-f $validation && !-l $validation && -r $validation) {
        local $/;
        open my $vh, "<", $validation;
        $data->{validation} = eval { decode_json(<$vh>) } || {};
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

export_backup() {
  local backup_id="$1"
  local root target archive tmp lock_file checksum descriptor manifest_hash task log_file status validation checksum_tmp descriptor_tmp
  local -a tar_opts=()
  require_root_for_write
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" shared
  target="$(safe_backup_target "$root" "$backup_id")"
  archive="$root/$backup_id.tar.gz"
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
  task="export-$backup_id.log"
  log_file="$LBP_LOGDIR/$task"
  prepare_log_file "$log_file" append
  task_state_write "$task" running archiving "$log_file" "$$" ""
  checksum_tmp="$archive.sha256.tmp.$$"
  descriptor="$archive.json"
  descriptor_tmp="$descriptor.tmp.$$"
  trap 'status=$?; rm -f -- "$tmp" "$checksum_tmp" "$descriptor_tmp"; if [ "$status" -ne 0 ]; then task_state_write "$task" failed failed "$log_file" "$$" "$status" || true; fi' EXIT
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

start_export() {
  require_root_for_write
  local backup_id="$1"
  local log_file task pid
  require_backup_id "$backup_id"
  acquire_operation_lock shared
  acquire_backup_lock "$backup_id" shared
  log_file="$LBP_LOGDIR/export-$backup_id.log"
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

import_backup() {
  require_root_for_write
  local archive="$1"
  local root top staging extracted max_mb max_bytes archive_size task log_file archive_hash validation_json expanded_size free_bytes
  local -a tar_opts=()
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
  staging="$(strict_child_path "$root" "$root/.$top.import.$$" )" || { echo "Unsafe import staging path." >&2; exit 7; }
  extracted="$staging/$top"
  rm -rf --one-file-system "$staging"
  mkdir -m 0700 -- "$staging"
  task="${HOSTBACKUP_TASK_ID:-import-$top.log}"
  log_file="$LBP_LOGDIR/$task"
  prepare_log_file "$log_file" append
  archive_hash="$(sha256sum "$archive" | awk '{print $1}')"
  task_state_write "$task" running extracting "$log_file" "$$" ""
  trap 'status=$?; rm -rf --one-file-system "$staging" 2>/dev/null || true; if [ "${HOSTBACKUP_IMPORT_CLEANUP:-0}" = "1" ]; then if [ "$status" -eq 0 ]; then rm -f -- "$archive"; else quarantine_import_archive "$archive" 2>/dev/null || rm -f -- "$archive"; fi; fi; if [ "$status" -ne 0 ]; then task_state_write "$task" failed failed "$log_file" "$$" "$status" || true; fi' EXIT
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
  write_backup_marker "$extracted" "$top"
  printf '%s  %s\n' "$archive_hash" "$(basename "$archive")" > "$extracted/import-source.sha256"
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
  log_file="$LBP_LOGDIR/$task_id"
  prepare_log_file "$log_file" truncate
  archive="$(claim_staged_import_archive "$archive")"
  log "Import queued from $archive" >> "$log_file"
  archive_size="$(stat -c '%s' "$archive" 2>/dev/null || echo 0)"
  free_bytes="$(df -PB1 "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  [ "${free_bytes:-0}" -gt $((archive_size + 268435456)) ] || { rm -f "$archive"; echo "Not enough staging space for import." >&2; exit 20; }
  if ! pid="$(launch_background "$task_id" "$log_file" env HOSTBACKUP_IMPORT_CLEANUP=1 HOSTBACKUP_TASK_ID="$task_id" "$0" import "$archive")"; then
    rm -f -- "$archive"
    echo "Import process could not be launched." >&2
    exit 14
  fi
  [ -n "$pid" ] || { rm -f "$archive"; echo "Import process could not be launched." >&2; exit 14; }
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
  archive="$root/$backup_id.tar.gz"
  trash="$(strict_child_path "$root" "$root/.trash-$backup_id-$(date +%s)-$$")" || { echo "Unsafe trash path." >&2; exit 7; }
  mv -- "$target" "$trash"
  rm -rf --one-file-system -- "$trash"
  rm -f -- "$archive" "$archive.sha256" "$archive.json"
}

restore_plan() {
  local backup_id="$1"
  local root target
  require_backup_id "$backup_id"
  root="$(backup_root)"
  verify_backup_target "$root" false
  target="$(safe_backup_target "$root" "$backup_id")"
  cat <<EOF
Restore-Plan fuer Backup $backup_id

Quelle:
 $target/$( [ -f "$target/rootfs.tar" ] && printf rootfs.tar || printf rootfs/ )

Ziel:
 /

Dieses Restore schreibt das gesicherte Root-Dateisystem auf dieses System zurueck.

Dabei werden unter anderem wiederhergestellt:
- Systemdateien
- LoxBerry-Konfigurationen
- Docker-Daten
- Dienste und Anwendungen
- Benutzer-, Rechte- und Besitzinformationen
- Hardlinks und symbolische Links

Laufzeit-Verzeichnisse wie /proc, /sys, /dev und /run werden nicht ueberschrieben.

Wichtige Hinweise:
- Fuer die sicherste und vollstaendigste Wiederherstellung wird ein Restore aus einem Rescue-/Offline-System empfohlen.
- Vor einem Online-Restore sollten Docker-Container und zusaetzliche Dienste beendet werden.
- Pruefe vor dem Restore die Datei manifest.json des Backups.
- Ein Restore kann bestehende Systemdaten ueberschreiben.
- Waehrend des Restores sollte das System nicht ausgeschaltet werden.

Restore-Befehl:
ALLOW_RESTORE=1 $0 restore $backup_id
EOF
}

restore_excludes() {
  local root="$1" target="$2" output="$3" mountpoint
  {
    printf '%s\n' /proc /sys /dev /run /tmp /lost+found
    printf '%s\n' "$root" "$target" "$LBP_CONFIGDIR" "$LBP_DATADIR" "$LBP_LOGDIR" "$ROOT_STATE_DIR"
    while IFS= read -r mountpoint; do
      [ -n "$mountpoint" ] && [ "$mountpoint" != "/" ] || continue
      printf '%s\n' "$mountpoint"
    done < <(findmnt -rn -o TARGET 2>/dev/null)
  } | awk 'NF && !seen[$0]++' > "$output"
}

restore_cleanup_on_exit() {
  local status="$1" state_dir="$2" log_file="$3" task="$4" restarted="$5"
  local failed=0
  if [ "$restarted" != "true" ] && [ -d "$state_dir" ]; then
    start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file" || failed=1
  fi
  if [ "$status" -ne 0 ]; then
    task_state_write "$task" failed "$([ "$failed" -eq 0 ] && printf failed || printf cleanup_failed)" "$log_file" "$$" "$status" || true
  fi
  rm -rf -- "$state_dir" 2>/dev/null || true
  return "$failed"
}

restore_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1" degraded_confirmation="${2:-false}"
  local root target exclude_file state_dir restore_dest mode storage_format task restarted=false
  local log_file rsync_status dry_status
  local -a rsync_opts=() metadata_opts=() tar_opts=()
  require_backup_id "$backup_id"
  [ "${ALLOW_RESTORE:-}" = "1" ] || { echo "Set ALLOW_RESTORE=1 to run restore." >&2; exit 8; }
  root="$(backup_root)"
  verify_backup_target "$root" false
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" shared
  target="$(restore_eligibility "$backup_id" "$degraded_confirmation")"
  restore_dest="${HOSTBACKUP_RESTORE_DEST:-/}"
  restore_dest="$(canonicalize_path "$restore_dest")" || { echo "Restore destination must be absolute." >&2; exit 7; }
  [ -d "$restore_dest" ] && [ ! -L "$restore_dest" ] || { echo "Restore destination is unsafe." >&2; exit 7; }
  mode="$(manifest_field "$target/manifest.json" metadata.mode)"
  storage_format="$(manifest_field "$target/manifest.json" backup.storage_format)"
  if [ "$storage_format" = "portable-tar" ]; then
    command -v tar >/dev/null 2>&1 || { echo "tar is required." >&2; exit 3; }
  else
    command -v rsync >/dev/null 2>&1 || { echo "rsync is required." >&2; exit 3; }
  fi
  state_dir="$(mktemp -d "$LBP_DATADIR/restore-state-$backup_id.XXXXXX")"
  exclude_file="$state_dir/restore-excludes.txt"
  restore_excludes "$root" "$target" "$exclude_file"
  log_file="$LBP_LOGDIR/restore-$backup_id.log"
  task="restore-$backup_id.log"
  prepare_log_file "$log_file" truncate
  task_state_write "$task" running preflight "$log_file" "$$" ""
  trap 'restore_cleanup_on_exit "$?" "$state_dir" "$log_file" "$task" "$restarted"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  log "Starting restore $backup_id" | tee -a "$log_file"
  log "Restoring from $target to $restore_dest" | tee -a "$log_file"
  log "Exclude rules: $exclude_file" | tee -a "$log_file"
  task_state_write "$task" running stopping_services "$log_file" "$$" ""
  stop_backup_targets "$state_dir" 2>&1 | tee -a "$log_file"
  while IFS= read -r opt; do
    rsync_opts+=("$opt")
  done < <(rsync_live_options)
  if [ "$storage_format" = "portable-tar" ]; then
    while IFS= read -r opt; do tar_opts+=("$opt"); done < <(tar_metadata_options)
    task_state_write "$task" running planning "$log_file" "$$" ""
    tar -tf "$target/rootfs.tar" > "$state_dir/restore-plan.txt"
    task_state_write "$task" running restoring "$log_file" "$$" ""
    set +e
    tar "${tar_opts[@]}" --same-owner --same-permissions --delay-directory-restore -C "$restore_dest" -xpf "$target/rootfs.tar" 2>&1 | tee -a "$log_file"
    rsync_status=${PIPESTATUS[0]}
    set -e
  else
    while IFS= read -r opt; do metadata_opts+=("$opt"); done < <(rsync_metadata_options "$mode" restore)
    log "Creating rsync dry-run restore plan" | tee -a "$log_file"
    task_state_write "$task" running planning "$log_file" "$$" ""
    set +e
    rsync "${metadata_opts[@]}" --one-file-system --delete --dry-run --itemize-changes --exclude-from="$exclude_file" "$target/rootfs/" "$restore_dest/" > "$state_dir/restore-plan.txt" 2>> "$log_file"
    dry_status=$?
    set -e
    [ "$dry_status" -eq 0 ] || { log "Restore dry-run failed with status $dry_status" | tee -a "$log_file"; exit "$dry_status"; }
    grep -F "$target" "$exclude_file" >/dev/null || { echo "Restore source is not protected by excludes." >&2; exit 18; }
    log "rsync restore live output follows" | tee -a "$log_file"
    task_state_write "$task" running restoring "$log_file" "$$" ""
    set +e
    rsync "${metadata_opts[@]}" --one-file-system --delete "${rsync_opts[@]}" --exclude-from="$exclude_file" "$target/rootfs/" "$restore_dest/" 2>&1 | tee -a "$log_file"
    rsync_status=${PIPESTATUS[0]}
    set -e
  fi
  log "restore copy finished with status $rsync_status" | tee -a "$log_file"
  if [ "$rsync_status" -eq 0 ]; then
    task_state_write "$task" running restarting_services "$log_file" "$$" ""
    start_backup_targets_if_needed "$state_dir" 2>&1 | tee -a "$log_file"
    restarted=true
    log "Restore $backup_id finished" | tee -a "$log_file"
    task_state_write "$task" finished complete "$log_file" "$$" 0
    rm -rf -- "$state_dir"
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
  local backup_id="$1" degraded_confirmation="${2:-false}"
  local log_file task pid
  require_backup_id "$backup_id"
  acquire_operation_lock exclusive
  acquire_backup_lock "$backup_id" shared
  restore_eligibility "$backup_id" "$degraded_confirmation" >/dev/null
  log_file="$LBP_LOGDIR/restore-$backup_id.launch.log"
  prepare_log_file "$log_file" truncate
  task="restore-$backup_id.log"
  pid="$(launch_background "$task" "$log_file" env ALLOW_RESTORE=1 "$0" restore "$backup_id" "$degraded_confirmation")"
  [ -n "$pid" ] || { echo "Restore process could not be launched." >&2; exit 14; }
  printf '%s\n' "$backup_id"
}

prune_old_backups() {
  local keep root path backup_id safe trash
  keep="$(json_get_number keep_backups)"
  [ -n "$keep" ] || keep=0
  [ "$keep" -gt 0 ] || return 0
  root="$(backup_root)"
  verify_backup_target "$root" true
  acquire_operation_lock exclusive
  perl -MJSON::PP -MTime::Piece -e '
    my ($root, $keep, $now) = @ARGV;
    opendir(my $dh, $root) or exit 0;
    my (@complete, @expired);
    while (defined(my $name = readdir($dh))) {
      next if $name =~ /^\./;
      next if $name !~ /^[A-Za-z0-9._-]+$/;
      my $path = "$root/$name";
      next if !-d $path;
      my $manifest = "$path/manifest.json";
      next if !-r $manifest;
      open(my $fh, "<", $manifest) or next;
      local $/;
      my $data = eval { decode_json(<$fh>) } || {};
      my $status = $data->{status} || "";
      my $validation_status = "";
      if (open(my $vh, "<", "$path/backup-validation.json")) {
        local $/;
        my $validation = eval { decode_json(<$vh>) } || {};
        $validation_status = $validation->{status} || "";
      }
      my @st = stat($path);
      next if !@st;
      my $time = 0 + $st[9];
      if (($data->{finished_at} || "") =~ /^\d{4}-\d{2}-\d{2}T/) {
        my $parsed = eval { Time::Piece->strptime($data->{finished_at}, "%Y-%m-%dT%H:%M:%S%z")->epoch };
        $time = $parsed if $parsed;
      }
      if (($status eq "complete" && $validation_status eq "ok") || ($status eq "complete_with_warnings" && $validation_status eq "warning")) {
        push @complete, [$time, $path];
      } elsif ($status =~ /^(failed|cleanup_failed|stopped)$/ && $time < $now - 7*86400) {
        push @expired, $path;
      } elsif ($status eq "running" && $time < $now - 2*86400) {
        push @expired, $path;
      }
    }
    @complete = sort { $b->[0] <=> $a->[0] } @complete;
    for my $idx ($keep .. $#complete) {
      push @expired, $complete[$idx]->[1];
    }
    print $_, "\0" for @expired;
  ' "$root" "$keep" "$(date +%s)" | while IFS= read -r -d '' path; do
    backup_id="$(basename -- "$path")"
    safe="$(safe_backup_target "$root" "$backup_id")" || continue
    trash="$(strict_child_path "$root" "$root/.trash-$backup_id-$(date +%s)-$$")" || continue
    mv -- "$safe" "$trash"
    rm -rf --one-file-system -- "$trash"
    rm -f -- "$root/$backup_id.tar.gz" "$root/$backup_id.tar.gz.sha256" "$root/$backup_id.tar.gz.json"
  done
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
  tasks                  List task logs as JSON
  task-log TASK [LINES]  Print recent task log lines
  task-status TASK [N]   Print task status and recent log as JSON
  stop BACKUP_ID         Stop a running backup and restart stopped services/containers
  list                   List backups as JSON
  export BACKUP_ID       Create/export BACKUP_ID.tar.gz
  start-export BACKUP_ID Create/export BACKUP_ID.tar.gz in the background
  export-info BACKUP_ID  Show export archive status as JSON
  delete-export BACKUP_ID Delete the export archive for BACKUP_ID
  import ARCHIVE.tar.gz   Import an exported backup archive
  start-import ARCHIVE.tar.gz Import an exported backup archive in the background
  move BACKUP_ID DIR      Move a backup and its export archive to DIR
  browse BACKUP_ID [PATH] List files inside a backup as JSON
  cat-file BACKUP_ID PATH Print one file from a backup
  delete BACKUP_ID       Delete a backup
  restore-plan BACKUP_ID Show restore instructions
  restore BACKUP_ID      Restore backup, requires ALLOW_RESTORE=1
  start-restore BACKUP_ID [confirm-degraded] Restore backup in the background
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
  stop-targets) discover_stop_targets ;;
  save-config) shift; save_config "${1:-}" "${2:-}" "${3:-false}" "${4:-false}" "${5:-10}" "${6:-false}" "${7:-daily}" "${8:-02:00}" "${9:-0}" "${10:-1}" "${11:-*}" "${12:-0}" "${13:-1}" "${14:-}" "${15:-}" "${16:-false}" "${17:-full}" "${18:-}" "${19:-false}" "${20:-}" "${21:-true}" "${22:-true}" "${23:-true}" "${24:-true}" "${25:-native-strict}" ;;
  install-schedule) install_schedule ;;
  schedule-run) schedule_run ;;
  tasks) list_tasks ;;
  task-log) shift; show_task_log "${1:?TASK required}" "${2:-300}" ;;
  task-status) shift; task_status "${1:?TASK required}" "${2:-400}" ;;
  stop) shift; stop_backup "${1:?BACKUP_ID required}" ;;
  list) list_backups ;;
  export) shift; export_backup "${1:?BACKUP_ID required}" ;;
  start-export) shift; start_export "${1:?BACKUP_ID required}" ;;
  export-info) shift; export_info "${1:?BACKUP_ID required}" ;;
  delete-export) shift; delete_export "${1:?BACKUP_ID required}" ;;
  import) shift; import_backup "${1:?ARCHIVE required}" ;;
  start-import) shift; start_import "${1:?ARCHIVE required}" ;;
  move) shift; move_backup "${1:?BACKUP_ID required}" "${2:?DIR required}" ;;
  browse) shift; browse_backup "${1:?BACKUP_ID required}" "${2:-}" ;;
  cat-file) shift; cat_backup_file "${1:?BACKUP_ID required}" "${2:?PATH required}" ;;
  delete) shift; delete_backup "${1:?BACKUP_ID required}" ;;
  restore-plan) shift; restore_plan "${1:?BACKUP_ID required}" ;;
  restore) shift; restore_backup "${1:?BACKUP_ID required}" "${2:-false}" ;;
  start-restore) shift; start_restore "${1:?BACKUP_ID required}" "${2:-false}" ;;
  *) usage; exit 1 ;;
esac
