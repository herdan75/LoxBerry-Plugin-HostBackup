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
LOCK_FILE="/var/lock/${PLUGIN_FOLDER}.lock"

mkdir -p "$LBP_CONFIGDIR" "$LBP_DATADIR" "$LBP_LOGDIR"

if [ ! -f "$CONFIG_FILE" ]; then
  cat > "$CONFIG_FILE" <<'JSON'
{
  "backup_root": "",
  "backup_mode": "full",
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
fi

json_get_string() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or exit 0;
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) } || {};
    my $value = $cfg->{$key};
    print $value if defined $value && !ref($value);
  ' "$CONFIG_FILE" "$key"
}

json_get_bool() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or exit 0;
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) } || {};
    print(($cfg->{$key} ? "true" : "false"));
  ' "$CONFIG_FILE" "$key"
}

json_get_number() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or exit 0;
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) } || {};
    my $value = $cfg->{$key};
    print $value if defined $value && $value =~ /^\d+$/;
  ' "$CONFIG_FILE" "$key"
}

json_get_array_lines() {
  local key="$1"
  perl -MJSON::PP -e '
    my ($file, $key) = @ARGV;
    open my $fh, "<", $file or exit 0;
    local $/;
    my $json = <$fh>;
    my $cfg = eval { decode_json($json) } || {};
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
    my $cfg = eval { decode_json(<$fh>) } || {};
    $cfg->{backup_root} //= "";
    $cfg->{backup_mode} = "full" unless ($cfg->{backup_mode} || "") =~ /^(full|snapshot)$/;
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
    print JSON::PP->new->ascii->pretty->canonical->encode($cfg);
  ' "$CONFIG_FILE"
}

save_config() {
  require_root_for_write
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

  perl -MJSON::PP -e '
    my ($file, $backup_root, $excludes_text, $stop_docker, $create_export, $keep_backups, $schedule_enabled, $schedule_mode, $schedule_time, $schedule_weekday, $schedule_monthday, $schedule_months, $schedule_weekdays, $schedule_monthdays, $pre_hook, $post_hook, $root_permission_ack, $backup_mode, $stop_targets_text, $mail_notify_enabled, $mail_notify_to, $mail_notify_success, $mail_notify_failure, $mail_notify_stopped, $mail_notify_restore) = @ARGV;
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
    };
    open my $fh, ">", $file or die "Cannot write config: $!";
    print $fh JSON::PP->new->ascii->pretty->canonical->encode($cfg);
  ' "$CONFIG_FILE" "$backup_root" "$excludes_text" "$stop_docker" "$create_export" "$keep_backups" "$schedule_enabled" "$schedule_mode" "$schedule_time" "$schedule_weekday" "$schedule_monthday" "$schedule_months" "$schedule_weekdays" "$schedule_monthdays" "$pre_hook" "$post_hook" "$root_permission_ack" "$backup_mode" "$stop_targets" "$mail_notify_enabled" "$mail_notify_to" "$mail_notify_success" "$mail_notify_failure" "$mail_notify_stopped" "$mail_notify_restore"
  install_schedule
}

json_escape() {
  perl -MJSON::PP -e 'print encode_json($ARGV[0] // "")' "$1"
}

backup_root() {
  local configured
  configured="$(json_get_string backup_root)"
  if [ -n "$configured" ]; then
    printf '%s\n' "$configured"
  else
    printf '%s\n' "$LBP_DATADIR/backups"
  fi
}

require_allowed_backup_root() {
  local root="$1"
  case "$root" in
    /|/proc|/proc/*|/sys|/sys/*|/dev|/dev/*|/run|/run/*|/tmp|/tmp/*)
      echo "Backup target must not be /, /proc, /sys, /dev, /run or /tmp." >&2
      exit 14
      ;;
  esac
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
  local root probe fs_type source available_mb backup_mode status message linux_fs
  root="$(backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  case "$root" in
    /|/proc|/proc/*|/sys|/sys/*|/dev|/dev/*|/run|/run/*|/tmp|/tmp/*)
      cat <<EOF
{
  "kind": "backup-target",
  "status": "error",
  "backup_root": $(json_escape "$root"),
  "probe_path": $(json_escape "$root"),
  "fs_type": "blocked",
  "source": "blocked",
  "available_mb": 0,
  "message": "Backup-Ziel darf nicht /, /proc, /sys, /dev, /run oder /tmp sein."
}
EOF
      return 0
      ;;
  esac
  probe="$root"
  while [ ! -e "$probe" ] && [ "$probe" != "/" ]; do
    probe="$(dirname "$probe")"
  done
  [ -e "$probe" ] || probe="/"

  fs_type="$(findmnt -no FSTYPE -T "$probe" 2>/dev/null | head -n 1)"
  source="$(findmnt -no SOURCE -T "$probe" 2>/dev/null | head -n 1)"
  available_mb="$(df -Pm "$probe" 2>/dev/null | awk 'NR==2 {print $4}')"
  [ -n "$fs_type" ] || fs_type="unknown"
  [ -n "$source" ] || source="unknown"
  [ -n "$available_mb" ] || available_mb=0

  linux_fs=false
  if printf '%s\n' "$fs_type" | grep -Eq '^(ext2|ext3|ext4|xfs|btrfs)$'; then
    linux_fs=true
  fi

  status="ok"
  message="Backup-Ziel nutzt ein geeignetes Linux-Dateisystem. ext4 ist fuer dieses Plugin in der Praxis meist deutlich schneller als NTFS/FUSE und besonders fuer inkrementelle Snapshots empfohlen."
  if [ "$backup_mode" = "snapshot" ] && [ "$linux_fs" != "true" ]; then
    status="warning"
    message="Inkrementelle Snapshots verwenden Hardlinks. Fuer Geschwindigkeit, zuverlaessige Speicherersparnis und Linux-Rechte wird ext4, xfs oder btrfs empfohlen. NTFS/FUSE ist bei vielen kleinen Dateien oft deutlich langsamer und kann Hardlinks/Metadaten eingeschraenkt abbilden."
  elif [ "$linux_fs" != "true" ]; then
    status="warning"
    message="Das Backup-Ziel ist kein typisches Linux-Dateisystem. Fuer Geschwindigkeit, volle Linux-Rechte, Besitzer, Hardlinks und spaetere inkrementelle Snapshots wird ext4, xfs oder btrfs empfohlen. NTFS/FUSE kann dieses Backup deutlich verlangsamen."
  fi

  cat <<EOF
{
  "kind": "backup-target",
  "status": $(json_escape "$status"),
  "backup_root": $(json_escape "$root"),
  "probe_path": $(json_escape "$probe"),
  "fs_type": $(json_escape "$fs_type"),
  "source": $(json_escape "$source"),
  "available_mb": $available_mb,
  "linux_filesystem": $linux_fs,
  "backup_mode": $(json_escape "$backup_mode"),
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
    start_backup
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
  start_backup
}

log() {
  local msg="$1"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$msg"
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

rsync_supports_info() {
  rsync --help 2>/dev/null | grep -q -- '--info='
}

rsync_live_options() {
  if rsync_supports_info; then
    printf '%s\n' '--info=progress2,stats2'
    printf '%s\n' '--human-readable'
  else
    printf '%s\n' '--progress'
  fi
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

  if command -v dpkg-query >/dev/null 2>&1; then
    dpkg-query -W -f='${binary:Package}\t${Version}\n' > "$package_file" 2>/dev/null || true
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl list-unit-files --type=service --no-pager > "$services_file" 2>/dev/null || true
  fi
  mount > "$mounts_file" 2>/dev/null || true

  perl -MJSON::PP -e '
    my ($manifest, $backup_id, $status, $started_at, $finished_at, $size, $files, $os, $arch, $lbver, $backup_mode) = @ARGV;
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
      schema_version => 1,
      backup_id => $backup_id,
      status => $status,
      started_at => $started_at,
      finished_at => $finished_at,
      size_bytes => 0 + $size,
      files_count => 0 + $files,
      backup => {
        mode => $backup_mode,
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
    open my $fh, ">", $manifest or die "Cannot write $manifest: $!";
    print $fh JSON::PP->new->ascii->pretty->canonical->encode($data);
  ' "$manifest" "$backup_id" "$status" "$started_at" "$finished_at" "$size_bytes" "$files_count" "$(host_os_pretty)" "$(host_arch)" "$(loxberry_version)" "$(json_get_string backup_mode)"

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
$root
EOF
  json_get_array_lines rsync_extra_excludes
}

run_hook() {
  local hook="$1"
  if validate_hook "$hook"; then
    "$hook"
  fi
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
    dbus.service|polkit.service|systemd-*.service|udev.service|systemd-udevd.service) return 0 ;;
    systemd-logind.service|systemd-journald.service|systemd-timesyncd.service) return 0 ;;
    getty@*.service|serial-getty@*.service|user@*.service) return 0 ;;
    networking.service|NetworkManager.service|systemd-networkd.service|systemd-resolved.service) return 0 ;;
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
  local tmp unit load active sub description group name image status
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
      while read -r unit load active sub description; do
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
    local state_dir="$1"
    local id name
    docker ps --format '{{.ID}}\t{{.Names}}' > "$state_dir/docker-running-containers.tsv" 2>/dev/null || true
    awk '{print $1}' "$state_dir/docker-running-containers.tsv" > "$state_dir/docker-running-containers.txt" 2>/dev/null || true
    if [ -s "$state_dir/docker-running-containers.tsv" ]; then
      log "Docker containers running before backup:"
      while IFS="$(printf '\t')" read -r id name; do
        [ -n "$id" ] || continue
        log "  $name ($id)"
      done < "$state_dir/docker-running-containers.tsv"
      while IFS="$(printf '\t')" read -r id name; do
        [ -n "$id" ] || continue
        log "Stopping Docker container $name ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker stop -t 30 "$id" || log "WARNING: Could not stop Docker container $name ($id)"
        else
          docker stop -t 30 "$id" || log "WARNING: Could not stop Docker container $name ($id)"
        fi
      done < "$state_dir/docker-running-containers.tsv"
    else
      log "No running Docker containers found before backup"
    fi
  fi
}

stop_selected_systemd_targets() {
  local state_dir="$1"
  local targets_file="$2"
  local unit
  [ -s "$targets_file" ] || return 0
  command -v systemctl >/dev/null 2>&1 || return 0
  while IFS="$(printf '\t')" read -r type unit; do
    [ "$type" = "systemd" ] || continue
    [ -n "$unit" ] || continue
    protected_systemd_service "$unit" && { log "Skipping protected systemd service $unit"; continue; }
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
      printf '%s\n' "$unit" >> "$state_dir/systemd-running-services.txt"
      log "Stopping systemd service $unit"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 systemctl stop "$unit" || log "WARNING: Could not stop systemd service $unit"
      else
        systemctl stop "$unit" || log "WARNING: Could not stop systemd service $unit"
      fi
    else
      log "Systemd service $unit is not running; nothing to stop"
    fi
  done < "$targets_file"
}

stop_selected_docker_targets() {
  local state_dir="$1"
  local targets_file="$2"
  local type name id running
  [ -s "$targets_file" ] || return 0
  command -v docker >/dev/null 2>&1 || return 0
  while IFS="$(printf '\t')" read -r type name; do
    [ "$type" = "docker" ] || continue
    [ -n "$name" ] || continue
    running="$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)"
    if [ "$running" = "true" ]; then
      id="$(docker inspect --format '{{.Id}}' "$name" 2>/dev/null | cut -c1-12)"
      printf '%s\t%s\n' "${id:-$name}" "$name" >> "$state_dir/docker-running-containers.tsv"
      printf '%s\n' "${id:-$name}" >> "$state_dir/docker-running-containers.txt"
      log "Stopping Docker container $name (${id:-unknown})"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 docker stop -t 30 "$name" || log "WARNING: Could not stop Docker container $name"
      else
        docker stop -t 30 "$name" || log "WARNING: Could not stop Docker container $name"
      fi
    else
      log "Docker container $name is not running; nothing to stop"
    fi
  done < "$targets_file"
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
  local id name source_file
  if command -v docker >/dev/null 2>&1; then
    if [ -s "$state_tsv" ]; then
      source_file="$state_tsv"
      while IFS="$(printf '\t')" read -r id name; do
        [ -n "$id" ] || continue
        log "Starting Docker container $name ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker start "$id" || log "WARNING: Could not start Docker container $name ($id)"
        else
          docker start "$id" || log "WARNING: Could not start Docker container $name ($id)"
        fi
      done < "$source_file"
    elif [ -s "$state_file" ]; then
      while IFS= read -r id; do
        [ -n "$id" ] || continue
        name="$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')"
        log "Starting Docker container ${name:-unknown} ($id)"
        if command -v timeout >/dev/null 2>&1; then
          timeout 45 docker start "$id" || log "WARNING: Could not start Docker container ${name:-unknown} ($id)"
        else
          docker start "$id" || log "WARNING: Could not start Docker container ${name:-unknown} ($id)"
        fi
      done < "$state_file"
    else
      log "No Docker container state file found for restart"
    fi
  fi
}

start_systemd_if_needed() {
  local state_dir="$1"
  local state_file="$state_dir/systemd-running-services.txt"
  local unit
  if command -v systemctl >/dev/null 2>&1 && [ -s "$state_file" ]; then
    tac "$state_file" 2>/dev/null | while IFS= read -r unit; do
      [ -n "$unit" ] || continue
      log "Starting systemd service $unit"
      if command -v timeout >/dev/null 2>&1; then
        timeout 45 systemctl start "$unit" || log "WARNING: Could not start systemd service $unit"
      else
        systemctl start "$unit" || log "WARNING: Could not start systemd service $unit"
      fi
    done
  fi
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
  log_restart_targets "$state_dir"
  start_docker_if_needed "$state_dir"
  start_systemd_if_needed "$state_dir"
}

backup_cleanup_on_exit() {
  local status="$1"
  local state_dir="$2"
  local log_file="$3"
  local already_restarted="$4"

  [ "$already_restarted" = "true" ] && return 0
  [ -n "$state_dir" ] && [ -d "$state_dir" ] || return 0

  if [ -s "$state_dir/docker-running-containers.tsv" ] || [ -s "$state_dir/docker-running-containers.txt" ] || [ -s "$state_dir/systemd-running-services.txt" ]; then
    if [ -n "$log_file" ]; then
      log "Cleanup: restarting services and Docker containers after interrupted backup (exit status $status)" | tee -a "$log_file" || true
      start_backup_targets_if_needed "$state_dir" | tee -a "$log_file" || true
    else
      log "Cleanup: restarting services and Docker containers after interrupted backup (exit status $status)" || true
      start_backup_targets_if_needed "$state_dir" || true
    fi
  fi
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
  find "$path/rootfs" -xdev -type f 2>/dev/null | wc -l | tr -d ' '
}

validate_completed_backup() {
  local target="$1"
  local backup_mode="$2"
  local previous_backup="${3:-}"
  local size_bytes="${4:-0}"
  local files_count="${5:-0}"
  local validation_file="$target/backup-validation.json"
  local status="ok"
  local manifest_ok rootfs_ok etc_ok loxberry_ok varlib_ok mntdocker_ok hardlink_ok size_ok files_ok
  local hardlink_value="not_checked"

  [ -r "$target/manifest.json" ] && manifest_ok=true || manifest_ok=false
  [ -d "$target/rootfs" ] && rootfs_ok=true || rootfs_ok=false
  [ -d "$target/rootfs/etc" ] && etc_ok=true || etc_ok=false
  [ -d "$target/rootfs/opt/loxberry" ] && loxberry_ok=true || loxberry_ok=false
  [ -d "$target/rootfs/var/lib" ] && varlib_ok=true || varlib_ok=false
  [ -d "$target/rootfs/mnt/docker" ] && mntdocker_ok=true || mntdocker_ok=false
  [ "${size_bytes:-0}" -ge 104857600 ] && size_ok=true || size_ok=false
  [ "${files_count:-0}" -ge 100 ] && files_ok=true || files_ok=false

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
  elif [ "$varlib_ok" != "true" ] || [ "$size_ok" != "true" ] || [ "$files_ok" != "true" ] || [ "$hardlink_ok" != "true" ]; then
    status="warning"
  fi

  perl -MJSON::PP -e '
    my ($file, $status, $manifest_ok, $rootfs_ok, $etc_ok, $loxberry_ok, $varlib_ok, $mntdocker_ok, $hardlink_ok, $hardlink_value, $size_ok, $files_ok, $size_bytes, $files_count) = @ARGV;
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
      ],
    };
    open my $fh, ">", $file or die "Cannot write validation: $!";
    print $fh JSON::PP->new->ascii->canonical->pretty->encode($data);
  ' "$validation_file" "$status" "$manifest_ok" "$rootfs_ok" "$etc_ok" "$loxberry_ok" "$varlib_ok" "$mntdocker_ok" "$hardlink_ok" "$hardlink_value" "$size_ok" "$files_ok" "$size_bytes" "$files_count"

  log "Backup validation status: $status"
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
  find "$root" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f %p\n' 2>/dev/null \
    | sort -rn \
    | while read -r _time id path; do
      [ "$id" != "$current_id" ] || continue
      [ -d "$path/rootfs" ] || continue
      if [ -r "$path/manifest.json" ]; then
        perl -MJSON::PP -e '
          local $/;
          open my $fh, "<", $ARGV[0] or exit 1;
          my $data = eval { decode_json(<$fh>) } || {};
          exit(($data->{status} || "") eq "complete" ? 0 : 1);
        ' "$path/manifest.json" || continue
      fi
      printf '%s\n' "$path"
      break
    done
}

preflight_backup() {
  local root available_mb docker_available docker_running excludes_count status warnings_json checks_json rsync_available target_writable backup_mode fs_type
  require_root_permission_ack
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  mkdir -p "$root"
  available_mb="$(df -Pm "$root" 2>/dev/null | awk 'NR==2 {print $4}')"
  fs_type="$(findmnt -no FSTYPE -T "$root" 2>/dev/null | head -n 1)"
  [ -n "$available_mb" ] || available_mb=0
  rsync_available=false
  command -v rsync >/dev/null 2>&1 && rsync_available=true
  target_writable=false
  [ -w "$root" ] && target_writable=true
  docker_available=false
  docker_running=0
  if command -v docker >/dev/null 2>&1; then
    docker_available=true
    docker_running="$(docker ps -q 2>/dev/null | wc -l | tr -d ' ')"
  fi
  excludes_count="$(backup_excludes "$root" | wc -l | tr -d ' ')"
  status="ok"
  warnings_json="[]"
  if [ "$rsync_available" != "true" ] || [ "$target_writable" != "true" ]; then
    status="error"
    warnings_json='["Pflichtcheck fehlgeschlagen: rsync oder Schreibzugriff fehlt."]'
  elif [ "$available_mb" -lt 1024 ]; then
    status="warning"
    warnings_json='["Backup-Ziel hat weniger als 1 GB freien Speicher."]'
  elif [ "$backup_mode" = "snapshot" ] && ! printf '%s\n' "$fs_type" | grep -Eq '^(ext2|ext3|ext4|xfs|btrfs)$'; then
    status="warning"
    warnings_json='["Snapshot-Backups verwenden Hardlinks. Fuer zuverlaessige Speicherersparnis wird ein Linux-Dateisystem wie ext4 empfohlen."]'
  elif [ "$docker_running" -gt 0 ] && [ "$(json_get_bool stop_docker_before_backup)" != "true" ] && [ "$(selected_docker_stop_count)" -eq 0 ]; then
    status="warning"
    warnings_json='["Docker-Container laufen. Fuer konsistente Datenbanken ggf. einzelne Container in den Stop-Zielen auswaehlen oder Hooks konfigurieren."]'
  fi
  checks_json="$(cat <<EOF
[
  {"name":"rsync verfuegbar","ok":$rsync_available},
  {"name":"Backup-Ziel beschreibbar","ok":$target_writable},
  {"name":"Backup-Modus","ok":true,"value":"$backup_mode"},
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
  "checks": $checks_json
}
EOF
}

preflight_restore() {
  local backup_id="$1"
  local root target status warnings_json backup_arch host_arch_value backup_status rsync_available
  require_root_permission_ack
  require_backup_id "$backup_id"
  root="$(backup_root)"
  target="$root/$backup_id"
  [ -d "$target/rootfs" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  host_arch_value="$(host_arch)"
  rsync_available=false
  command -v rsync >/dev/null 2>&1 && rsync_available=true
  backup_arch="$(perl -MJSON::PP -e 'local $/; open my $fh,"<",$ARGV[0] or exit 0; my $d=eval{decode_json(<$fh>)}||{}; print $d->{host}{architecture} // "";' "$target/manifest.json" 2>/dev/null || true)"
  backup_status="$(perl -MJSON::PP -e 'local $/; open my $fh,"<",$ARGV[0] or exit 0; my $d=eval{decode_json(<$fh>)}||{}; print $d->{status} // "";' "$target/manifest.json" 2>/dev/null || true)"
  status="ok"
  warnings_json="[]"
  if [ "$rsync_available" != "true" ]; then
    status="error"
    warnings_json='["Pflichtcheck fehlgeschlagen: rsync fehlt."]'
  elif [ "$backup_status" != "complete" ]; then
    status="warning"
    warnings_json='["Backup ist nicht als complete markiert."]'
  elif [ -n "$backup_arch" ] && [ "$backup_arch" != "$host_arch_value" ]; then
    status="warning"
    warnings_json='["Backup-Architektur unterscheidet sich vom Zielsystem."]'
  fi
  cat <<EOF
{
  "kind": "restore",
  "status": "$status",
  "backup_id": $(json_escape "$backup_id"),
  "backup_path": $(json_escape "$target"),
  "warnings": $warnings_json,
  "checks": [
    {"name":"rsync verfuegbar","ok":$rsync_available},
    {"name":"Backup rootfs vorhanden","ok":$([ -d "$target/rootfs" ] && echo true || echo false)},
    {"name":"Backup vollstaendig","ok":$([ "$backup_status" = "complete" ] && echo true || echo false),"value":$(json_escape "$backup_status")},
    {"name":"Architektur passend","ok":$([ -z "$backup_arch" ] || [ "$backup_arch" = "$host_arch_value" ] && echo true || echo false),"value":$(json_escape "$backup_arch -> $host_arch_value")}
  ]
}
EOF
}

create_backup() {
  require_root_for_write
  require_root_permission_ack
  command -v rsync >/dev/null 2>&1 || { echo "rsync is required." >&2; exit 3; }

  local root backup_id target rootfs log_file started finished size files exclude_file backup_mode previous_backup restart_done
  root="$(backup_root)"
  backup_mode="$(json_get_string backup_mode)"
  [ "$backup_mode" = "snapshot" ] || backup_mode="full"
  require_allowed_backup_root "$root"
  mkdir -p "$root"
  backup_id="${1:-$(date '+%Y%m%d-%H%M%S')}"
  backup_id="$(printf '%s' "$backup_id" | tr -cd 'A-Za-z0-9._-')"
  require_backup_id "$backup_id"
  target="$root/$backup_id"
  rootfs="$target/rootfs"
  log_file="$LBP_LOGDIR/backup-$backup_id.log"
  exclude_file="$target/rsync-excludes.txt"

  exec 9>"$LOCK_FILE"
  flock -n 9 || { echo "Another backup is already running." >&2; exit 5; }

  if [ -e "$target" ]; then
    echo "Backup already exists: $backup_id" >&2
    exit 4
  fi

  mkdir -p "$rootfs"
  started="$(date -Iseconds)"
  backup_excludes "$root" > "$exclude_file"
  write_manifest "$target" "$backup_id" "running" "$started" "" 0 0

  local pre_hook post_hook
  pre_hook="$(json_get_string pre_backup_hook)"
  post_hook="$(json_get_string post_backup_hook)"

  log "Starting backup $backup_id" | tee -a "$log_file"
  log "Backup mode: $backup_mode" | tee -a "$log_file"
  log "Backup target: $target" | tee -a "$log_file"
  log "Root filesystem copy target: $rootfs" | tee -a "$log_file"
  log "Exclude rules written to: $exclude_file" | tee -a "$log_file"
  log "Running pre-backup hook if configured" | tee -a "$log_file"
  run_hook "$pre_hook" | tee -a "$log_file" || true
  log "Stopping selected services and Docker containers if configured" | tee -a "$log_file"
  restart_done="false"
  trap 'backup_cleanup_on_exit "$?" "$target" "$log_file" "$restart_done"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  stop_backup_targets "$target" | tee -a "$log_file" || true

  local rsync_opts=()
  while IFS= read -r opt; do
    rsync_opts+=("$opt")
  done < <(rsync_live_options)

  if [ "$backup_mode" = "snapshot" ]; then
    previous_backup="$(latest_complete_backup "$root" "$backup_id")"
    if [ -n "$previous_backup" ] && [ -d "$previous_backup/rootfs" ]; then
      rsync_opts+=(--link-dest="$previous_backup/rootfs")
      log "Snapshot reference: $previous_backup/rootfs" | tee -a "$log_file"
    else
      log "No complete previous backup found. Creating first snapshot as full copy." | tee -a "$log_file"
    fi
  fi

  log "Starting rsync copy from / to $rootfs" | tee -a "$log_file"
  log "rsync live output follows. Large files or slow USB storage can keep one line active for a while." | tee -a "$log_file"
  set +e
  rsync -aAXH --numeric-ids --delete "${rsync_opts[@]}" --exclude-from="$exclude_file" / "$rootfs/" 2>&1 | tee -a "$log_file"
  local rsync_status=${PIPESTATUS[0]}
  set -e
  log "rsync finished with status $rsync_status" | tee -a "$log_file"

  log "Starting services and Docker containers again if they were stopped" | tee -a "$log_file"
  start_backup_targets_if_needed "$target" | tee -a "$log_file" || true
  restart_done="true"
  trap - EXIT HUP INT TERM
  log "Running post-backup hook if configured" | tee -a "$log_file"
  run_hook "$post_hook" | tee -a "$log_file" || true

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

  if [ "$(json_get_bool create_export_after_backup)" = "true" ]; then
    log "Creating export archive for $backup_id" | tee -a "$log_file"
    set +e
    export_backup "$backup_id" 2>&1 | tee -a "$log_file"
    local export_status=${PIPESTATUS[0]}
    set -e
    if [ "$export_status" -ne 0 ]; then
      finished="$(date -Iseconds)"
      write_manifest "$target" "$backup_id" "failed" "$started" "$finished" "$size" "$files"
      log "Backup $backup_id failed while creating export archive" | tee -a "$log_file"
      notify_hostbackup "failure" 3 "LoxBerry Host Backup fehlgeschlagen" "Backup $backup_id ist beim Erstellen des Export-Archivs fehlgeschlagen." "$log_file"
      exit "$export_status"
    fi
  fi

  finished="$(date -Iseconds)"
  size="$(calculate_size "$target")"
  files="$(calculate_files "$target")"
  write_manifest "$target" "$backup_id" "complete" "$started" "$finished" "$size" "$files"

  log "Checking completed backup" | tee -a "$log_file"
  validate_completed_backup "$target" "$backup_mode" "${previous_backup:-}" "$size" "$files" | tee -a "$log_file" || true

  log "Applying backup retention policy" | tee -a "$log_file"
  prune_old_backups

  log "Backup $backup_id finished" | tee -a "$log_file"
  notify_hostbackup "success" 6 "LoxBerry Host Backup erfolgreich" "Backup $backup_id wurde erfolgreich abgeschlossen. Groesse: $size Bytes, Dateien: $files." "$log_file"
  printf '%s\n' "$backup_id"
}

start_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id log_file
  backup_id="${1:-$(date '+%Y%m%d-%H%M%S')}"
  backup_id="$(printf '%s' "$backup_id" | tr -cd 'A-Za-z0-9._-')"
  require_backup_id "$backup_id"
  log_file="$LBP_LOGDIR/backup-$backup_id.launch.log"
  nohup "$0" backup "$backup_id" > "$log_file" 2>&1 &
  printf '%s\n' "$backup_id"
}

stop_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1"
  local root target log_file pids child_pids all_pids started finished size files
  require_backup_id "$backup_id"
  root="$(backup_root)"
  target="$root/$backup_id"
  log_file="$LBP_LOGDIR/backup-$backup_id.log"
  mkdir -p "$target"

  log "Stop requested for backup $backup_id" | tee -a "$log_file"

  pids="$(pgrep -f "$0 backup $backup_id" 2>/dev/null || true)"
  child_pids=""
  if [ -n "$pids" ]; then
    child_pids="$(for pid in $pids; do pgrep -P "$pid" 2>/dev/null || true; done | sort -u)"
  fi
  all_pids="$(printf '%s\n%s\n' "$child_pids" "$pids" | awk 'NF && !seen[$0]++')"

  if [ -n "$all_pids" ]; then
    log "Stopping backup processes: $(printf '%s' "$all_pids" | tr '\n' ' ')" | tee -a "$log_file"
    printf '%s\n' "$all_pids" | xargs -r kill -TERM
    sleep 3
    printf '%s\n' "$all_pids" | while IFS= read -r pid; do
      [ -n "$pid" ] || continue
      if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
      fi
    done
  else
    log "No running backup process found for $backup_id" | tee -a "$log_file"
  fi

  log "Restarting services and Docker containers stopped by this backup if needed" | tee -a "$log_file"
  start_backup_targets_if_needed "$target" | tee -a "$log_file" || true
  started="$(manifest_started_at "$target")"
  [ -n "$started" ] || started="$(date -Iseconds)"
  finished="$(date -Iseconds)"
  size="$(calculate_size "$target")"
  files="$(calculate_files "$target")"
  write_manifest "$target" "$backup_id" "stopped" "$started" "$finished" "$size" "$files"
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
    if [ -r "$path" ]; then
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
        my @st = stat($path);
        next unless @st;
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
  [ -r "$path" ] || { echo "Task log not found: $task" >&2; exit 14; }
  tail -n "$lines" "$path"
}

task_status() {
  local task="$1"
  local lines="${2:-400}"
  local max_bytes path size mtime state content_b64 recent_log
  path="$(task_log_path "$task")"
  [ -r "$path" ] || { echo "Task log not found: $task" >&2; exit 14; }
  max_bytes=32768
  size="$(stat -c '%s' "$path" 2>/dev/null || echo 0)"
  mtime="$(stat -c '%Y' "$path" 2>/dev/null || echo 0)"
  state="running"
  recent_log="$(tail -c 65536 "$path" 2>/dev/null || true)"
  if printf '%s\n' "$recent_log" | grep -qE ' (Backup|Restore|Export|Import) .* (finished|completed)$'; then
    state="finished"
  elif printf '%s\n' "$recent_log" | grep -qE ' (Backup|Restore|Export|Import) .* failed'; then
    state="failed"
  elif printf '%s\n' "$recent_log" | grep -qE ' Backup .* stopped by user$'; then
    state="stopped"
  elif [ "$(( $(date +%s) - mtime ))" -gt 300 ]; then
    state="stale"
  fi
  content_b64="$(tail -c "$max_bytes" "$path" | tail -n "$lines" | base64 -w 0)"
  cat <<EOF
{
  "task": $(json_escape "$task"),
  "state": $(json_escape "$state"),
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
  mkdir -p "$root"
  while IFS= read -r dir; do
    dirs+=("$dir")
  done < <(log_dirs)
  perl -MJSON::PP -e '
    my ($root, @log_dirs) = @ARGV;
    sub log_summary {
      my ($id) = @_;
      my %summary;
      my $max_tail = 262144;
      for my $dir (@log_dirs) {
        my $path = "$dir/backup-$id.log";
        next unless -r $path;
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
        next unless -r $path;
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
      next unless -d $dir;
      my $manifest = "$dir/manifest.json";
      my $validation = "$dir/backup-validation.json";
      my $data = {};
      if (-r $manifest) {
        local $/;
        open my $fh, "<", $manifest;
        $data = eval { decode_json(<$fh>) } || {};
      }
      if (-r $validation) {
        local $/;
        open my $vh, "<", $validation;
        $data->{validation} = eval { decode_json(<$vh>) } || {};
      }
      my $archive = "$root/$entry.tar.gz";
      my @tmp_archives = glob("$archive.tmp.*");
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
      $data->{export_file} = -f $archive ? $archive : undef;
      if (@tmp_archives) {
        $data->{export_status} = "running";
        $data->{export_size_bytes} = 0;
        $data->{export_mtime} = 0;
        $data->{export_message} = -f $archive
          ? "Export wird neu erstellt. Das bisherige Archiv bleibt bis zum Abschluss erhalten."
          : "Export wird erstellt";
      } elsif (-f $archive) {
        my @ast = stat($archive);
        $data->{export_status} = "available";
        $data->{export_size_bytes} = 0 + ($ast[7] || 0);
        $data->{export_mtime} = 0 + ($ast[9] || 0);
        $data->{export_message} = "Export vorhanden und bereit zum Download";
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
  ' "$root" "${dirs[@]}"
}

export_backup() {
  local backup_id="$1"
  local root target archive tmp lock_file
  require_backup_id "$backup_id"
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  target="$root/$backup_id"
  archive="$root/$backup_id.tar.gz"
  tmp="$archive.tmp.$$"
  lock_file="$root/.export-$backup_id.lock"
  [ -d "$target" ] || { log "Export $backup_id failed: backup not found"; echo "Backup not found: $backup_id" >&2; exit 6; }
  if [ ! -d "$target/rootfs" ]; then
    log "Export $backup_id failed: rootfs not found"
    echo "Backup rootfs not found: $backup_id" >&2
    exit 6
  fi
  exec 8>"$lock_file"
  flock -n 8 || { log "Export $backup_id failed: already running"; echo "Export already running: $backup_id" >&2; exit 5; }
  rm -f "$tmp"
  log "Starting export $backup_id"
  if ! run_with_heartbeat "Export $backup_id" tar -C "$root" -czf "$tmp" -- "$backup_id"; then
    rm -f "$tmp"
    log "Export $backup_id failed during archive creation"
    exit 15
  fi
  if ! tar -tzf "$tmp" >/dev/null 2>&1; then
    rm -f "$tmp"
    log "Export $backup_id failed integrity check"
    exit 16
  fi
  mv -f "$tmp" "$archive"
  log "Export $backup_id finished"
  printf '%s\n' "$archive"
}

export_info() {
  local backup_id="$1"
  local root target archive tmp_count status message size mtime
  require_backup_id "$backup_id"
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  target="$root/$backup_id"
  archive="$root/$backup_id.tar.gz"
  [ -d "$target" ] || { echo "Backup not found: $backup_id" >&2; exit 6; }
  tmp_count="$(find "$root" -maxdepth 1 -type f -name "$backup_id.tar.gz.tmp.*" 2>/dev/null | wc -l)"
  status="missing"
  message="Noch kein Exportarchiv vorhanden"
  size=0
  mtime=0
  if [ "${tmp_count:-0}" -gt 0 ]; then
    status="running"
    if [ -f "$archive" ]; then
      message="Export wird neu erstellt. Das bisherige Archiv bleibt bis zum Abschluss erhalten."
    else
      message="Export wird erstellt"
    fi
  elif [ -f "$archive" ]; then
    status="available"
    message="Export vorhanden und bereit zum Download"
    size="$(stat -c '%s' "$archive" 2>/dev/null || echo 0)"
    mtime="$(stat -c '%Y' "$archive" 2>/dev/null || echo 0)"
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
  local log_file
  require_backup_id "$backup_id"
  log_file="$LBP_LOGDIR/export-$backup_id.log"
  nohup "$0" export "$backup_id" > "$log_file" 2>&1 &
  printf 'export-%s.log\n' "$backup_id"
}

delete_export() {
  require_root_for_write
  local backup_id="$1"
  local root archive lock_file
  require_backup_id "$backup_id"
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  archive="$root/$backup_id.tar.gz"
  lock_file="$root/.export-$backup_id.lock"
  exec 8>"$lock_file"
  flock -n 8 || { echo "Export is currently running and cannot be deleted: $backup_id" >&2; exit 5; }
  rm -f "$archive" "$archive".tmp.*
}

import_backup() {
  require_root_for_write
  local archive="$1"
  local root top
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  mkdir -p "$root"
  [ -r "$archive" ] || { echo "Archive not readable: $archive" >&2; exit 9; }
  if [ "${HOSTBACKUP_IMPORT_CLEANUP:-0}" = "1" ]; then
    trap 'status=$?; if [ "$status" -ne 0 ]; then log "Import $archive failed"; fi; rm -f "$archive"' EXIT
  fi
  top="$(tar -tzf "$archive" | awk -F/ 'NF {print $1; exit}')"
  [ -n "$top" ] || { echo "Archive is empty." >&2; exit 10; }
  case "$top" in
    *[!A-Za-z0-9._-]*|.*|*..*) echo "Unsafe backup id in archive: $top" >&2; exit 11 ;;
  esac
  if tar -tzf "$archive" | awk -v top="$top" '
    $0 ~ /^/ {
      if ($0 ~ /^\// || $0 ~ /(^|\/)\.\.(\/|$)/) exit 1;
      if ($0 != top && index($0, top "/") != 1) exit 1;
    }
  '; then
    :
  else
    echo "Archive contains unsafe paths." >&2
    exit 11
  fi
  if [ -e "$root/$top" ]; then
    echo "Backup already exists: $top" >&2
    exit 4
  fi
  log "Starting import from $archive"
  if ! run_with_heartbeat "Import $top" tar -C "$root" --numeric-owner --same-owner --same-permissions -xzf "$archive"; then
    log "Import $top failed during archive extraction"
    exit 15
  fi
  [ -d "$root/$top/rootfs" ] || { echo "Imported archive does not contain a rootfs directory." >&2; exit 12; }
  if [ "${HOSTBACKUP_IMPORT_CLEANUP:-0}" = "1" ]; then
    rm -f "$archive"
    trap - EXIT
  fi
  log "Import $top finished"
  printf '%s\n' "$top"
}

require_staged_import_archive() {
  local archive="$1"
  local staging="$LBP_DATADIR/imports"
  local archive_real staging_real
  [ -r "$archive" ] || { echo "Archive not readable: $archive" >&2; exit 9; }
  mkdir -p "$staging"
  archive_real="$(readlink -f "$archive" 2>/dev/null || true)"
  staging_real="$(readlink -f "$staging" 2>/dev/null || true)"
  [ -n "$archive_real" ] || { echo "Archive path could not be resolved: $archive" >&2; exit 9; }
  [ -n "$staging_real" ] || { echo "Import staging directory could not be resolved: $staging" >&2; exit 9; }
  case "$archive_real" in
    "$staging_real"/*.tar.gz) printf '%s\n' "$archive_real" ;;
    *) echo "Background import requires a staged tar.gz archive in $staging_real." >&2; exit 13 ;;
  esac
}

start_import() {
  require_root_for_write
  local archive="$1"
  local task_id log_file
  archive="$(require_staged_import_archive "$archive")"
  task_id="import-$(date '+%Y%m%d-%H%M%S')-$$.log"
  log_file="$LBP_LOGDIR/$task_id"
  HOSTBACKUP_IMPORT_CLEANUP=1 nohup "$0" import "$archive" > "$log_file" 2>&1 &
  printf '%s\n' "$task_id"
}

move_backup() {
  require_root_for_write
  local backup_id="$1"
  local destination_root="$2"
  local root target archive destination
  require_backup_id "$backup_id"
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  target="$root/$backup_id"
  archive="$root/$backup_id.tar.gz"
  case "$destination_root" in
    /*) ;;
    *) echo "Destination must be an absolute path." >&2; exit 13 ;;
  esac
  [ -d "$target" ] || { echo "Backup not found: $backup_id" >&2; exit 6; }
  mkdir -p "$destination_root"
  destination="$destination_root/$backup_id"
  [ ! -e "$destination" ] || { echo "Destination already exists: $destination" >&2; exit 4; }
  mv "$target" "$destination"
  if [ -f "$archive" ]; then
    mv "$archive" "$destination_root/$backup_id.tar.gz"
  fi
  printf '%s\n' "$destination"
}

browse_backup() {
  local backup_id="$1"
  local rel_path="${2:-}"
  local root base
  require_backup_id "$backup_id"
  root="$(backup_root)"
  base="$root/$backup_id/rootfs"
  [ -d "$base" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  perl -MJSON::PP -MCwd=abs_path -MFile::Spec -e '
    my ($base, $rel) = @ARGV;
    $rel ||= "";
    die "Unsafe path\n" if $rel =~ m{(^/|(^|/)\.\.(/|$))};
    my $base_abs = abs_path($base) or die "Missing base\n";
    my $dir = File::Spec->catdir($base_abs, split m{/+}, $rel);
    my $dir_abs = abs_path($dir) or die "Missing path\n";
    die "Path escapes backup\n" unless index($dir_abs, $base_abs) == 0;
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
  base="$root/$backup_id/rootfs"
  [ -d "$base" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  perl -MCwd=abs_path -MFile::Spec -e '
    my ($base, $rel) = @ARGV;
    die "Unsafe path\n" if !$rel || $rel =~ m{(^/|(^|/)\.\.(/|$))};
    my $base_abs = abs_path($base) or die "Missing base\n";
    my $file = File::Spec->catfile($base_abs, split m{/+}, $rel);
    my $file_abs = abs_path($file) or die "Missing file\n";
    die "Path escapes backup\n" unless index($file_abs, $base_abs) == 0;
    die "Not a regular file\n" unless -f $file_abs;
    open my $fh, "<:raw", $file_abs or die "Cannot open file\n";
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
  local root target archive
  require_backup_id "$backup_id"
  root="$(backup_root)"
  require_allowed_backup_root "$root"
  target="$root/$backup_id"
  archive="$root/$backup_id.tar.gz"
  case "$target" in
    "$root"/*) ;;
    *) echo "Refusing unsafe path." >&2; exit 7 ;;
  esac
  [ -d "$target" ] || { echo "Backup not found: $backup_id" >&2; exit 6; }
  rm -rf --one-file-system "$target"
  rm -f "$archive"
}

restore_plan() {
  local backup_id="$1"
  local root target
  require_backup_id "$backup_id"
  root="$(backup_root)"
  target="$root/$backup_id"
  [ -d "$target/rootfs" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  cat <<EOF
Restore-Plan fuer Backup $backup_id

Quelle:
 $target/rootfs/

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

restore_backup() {
  require_root_for_write
  require_root_permission_ack
  local backup_id="$1"
  local root target exclude_file
  require_backup_id "$backup_id"
  [ "${ALLOW_RESTORE:-}" = "1" ] || { echo "Set ALLOW_RESTORE=1 to run restore." >&2; exit 8; }
  command -v rsync >/dev/null 2>&1 || { echo "rsync is required." >&2; exit 3; }
  root="$(backup_root)"
  target="$root/$backup_id"
  exclude_file="$target/rsync-excludes.txt"
  [ -d "$target/rootfs" ] || { echo "Backup rootfs not found: $backup_id" >&2; exit 6; }
  [ -f "$exclude_file" ] || backup_excludes "$root" > "$exclude_file"
  local log_file="$LBP_LOGDIR/restore-$backup_id.log"
  log "Starting restore $backup_id" | tee -a "$log_file"
  log "Restoring from $target/rootfs/ to /" | tee -a "$log_file"
  log "Exclude rules: $exclude_file" | tee -a "$log_file"
  local rsync_opts=()
  while IFS= read -r opt; do
    rsync_opts+=("$opt")
  done < <(rsync_live_options)
  log "rsync restore live output follows" | tee -a "$log_file"
  set +e
  rsync -aAXH --numeric-ids --delete "${rsync_opts[@]}" --exclude-from="$exclude_file" "$target/rootfs/" / 2>&1 | tee -a "$log_file"
  local rsync_status=${PIPESTATUS[0]}
  set -e
  log "rsync restore finished with status $rsync_status" | tee -a "$log_file"
  if [ "$rsync_status" -eq 0 ] || [ "$rsync_status" -eq 24 ]; then
    log "Restore $backup_id finished" | tee -a "$log_file"
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
  local backup_id="$1"
  local log_file
  require_backup_id "$backup_id"
  log_file="$LBP_LOGDIR/restore-$backup_id.launch.log"
  ALLOW_RESTORE=1 nohup "$0" restore "$backup_id" > "$log_file" 2>&1 &
  printf '%s\n' "$backup_id"
}

prune_old_backups() {
  local keep root
  keep="$(json_get_number keep_backups)"
  [ -n "$keep" ] || keep=0
  [ "$keep" -gt 0 ] || return 0
  root="$(backup_root)"
  [ -d "$root" ] || return 0
  perl -MJSON::PP -e '
    my ($root, $keep) = @ARGV;
    opendir(my $dh, $root) or exit 0;
    my @items;
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
      next if ($data->{status} || "") ne "complete";
      my @st = stat($path);
      next if !@st;
      push @items, [0 + $st[9], $path];
    }
    @items = sort { $b->[0] <=> $a->[0] } @items;
    for my $idx ($keep .. $#items) {
      print $items[$idx]->[1], "\0";
    }
  ' "$root" "$keep" | while IFS= read -r -d '' path; do
    rm -rf --one-file-system "$path"
    rm -f "$path.tar.gz"
  done
}

usage() {
  cat <<EOF
Usage: $0 ACTION [ARG]

Actions:
  backup [NAME]          Create a full host backup
  start [NAME]           Start a full host backup in the background
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
  start-restore BACKUP_ID Restore backup in the background
EOF
}

action="${1:-}"
case "$action" in
  backup) shift; create_backup "${1:-}" ;;
  start) shift; start_backup "${1:-}" ;;
  preflight-backup) preflight_backup ;;
  preflight-restore) shift; preflight_restore "${1:?BACKUP_ID required}" ;;
  config) show_config ;;
  target-info) backup_target_info ;;
  stop-targets) discover_stop_targets ;;
  save-config) shift; save_config "${1:-}" "${2:-}" "${3:-false}" "${4:-false}" "${5:-10}" "${6:-false}" "${7:-daily}" "${8:-02:00}" "${9:-0}" "${10:-1}" "${11:-*}" "${12:-0}" "${13:-1}" "${14:-}" "${15:-}" "${16:-false}" "${17:-full}" "${18:-}" "${19:-false}" "${20:-}" "${21:-true}" "${22:-true}" "${23:-true}" "${24:-true}" ;;
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
  restore) shift; restore_backup "${1:?BACKUP_ID required}" ;;
  start-restore) shift; start_restore "${1:?BACKUP_ID required}" ;;
  *) usage; exit 1 ;;
esac
