#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash -n \
  bin/hostbackup.sh \
  bin/hostbackup-sudo.sh \
  bin/restore-hostbackup.sh \
  preroot.sh \
  postinstall.sh \
  postroot.sh \
  uninstall/uninstall.sh \
  package.sh \
  tests/run.sh

python3 -m py_compile bin/validate-import-archive.py tests/test_archive_validator.py tests/test_install_hooks.py tests/test_web_security.py
python3 -m unittest discover -s tests -p 'test_*.py' -v

perl_lib="$ROOT/tests/perl"
if ! perl -MCGI -e 1 >/dev/null 2>&1; then
  perl_lib="$ROOT/tests/perl-stub:$perl_lib"
fi
PERL5LIB="$perl_lib${PERL5LIB:+:$PERL5LIB}" perl -c webfrontend/htmlauth/index.cgi

tmp="$(mktemp -d)"
cleanup_tmp() {
  if [ "$(id -u)" -eq 0 ]; then
    rm -rf -- "$tmp"
  elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo -n rm -rf -- "$tmp"
  else
    rm -rf -- "$tmp"
  fi
}
trap cleanup_tmp EXIT

if command -v node >/dev/null 2>&1; then
  mkdir -p "$tmp/render-data"
  PERL5LIB="$perl_lib${PERL5LIB:+:$PERL5LIB}" \
  LBHOMEDIR="$tmp/lbh-render" \
  LBPDATADIR="$tmp/render-data" \
  REQUEST_METHOD=GET \
  QUERY_STRING='' \
  REMOTE_USER=hostbackup-test \
  REMOTE_ADDR=127.0.0.1 \
  HTTP_USER_AGENT=hostbackup-test \
    perl webfrontend/htmlauth/index.cgi 2>/dev/null \
    | python3 -c 'import re, sys; html = sys.stdin.read(); match = re.search(r"<script>\s*(.*?)\s*</script>", html, re.S); assert match, "rendered JavaScript missing"; sys.stdout.write(match.group(1))' \
    | node --check -
fi

mkdir -p "$tmp/config" "$tmp/data" "$tmp/log"
LBHOMEDIR="$tmp/lbh" \
LBPCONFIGDIR="$tmp/config" \
LBPDATADIR="$tmp/data" \
LBPLOGDIR="$tmp/log" \
  bash bin/hostbackup.sh config > "$tmp/config-output.json"
perl -MJSON::PP -e '
  local $/;
  my $cfg = decode_json(<STDIN>);
  die "metadata default missing\n" unless $cfg->{metadata_mode} eq "native-strict";
  die "import limit missing\n" unless $cfg->{import_max_size_mb} == 65536;
' < "$tmp/config-output.json"
LBHOMEDIR="$tmp/lbh" \
LBPCONFIGDIR="$tmp/config" \
LBPDATADIR="$tmp/data" \
LBPLOGDIR="$tmp/log" \
  bash bin/hostbackup.sh target-info > "$tmp/target-info-empty.json"
perl -MJSON::PP -e '
  local $/;
  my $target = decode_json(<STDIN>);
  die "empty target must be unconfigured\n" if $target->{configured};
  die "empty target must be informational\n" unless $target->{status} eq "info";
  die "empty target must not probe a filesystem\n" if length($target->{probe_path} || "");
' < "$tmp/target-info-empty.json"

mkdir -p "$tmp/base-config/plugins" "$tmp/base-data/plugins" "$tmp/base-log/plugins"
LBHOMEDIR="$tmp/lbh-base" \
LBPCONFIG="$tmp/base-config/plugins" \
LBPDATA="$tmp/base-data/plugins" \
LBPLOG="$tmp/base-log/plugins" \
  bash bin/hostbackup.sh config > "$tmp/base-env-config-output.json"
test -f "$tmp/base-config/plugins/loxberryhostbackup/config.json"
test -d "$tmp/base-data/plugins/loxberryhostbackup/root-state"
test -d "$tmp/base-log/plugins/loxberryhostbackup"
test ! -e "$tmp/base-config/plugins/config.json"

root_exec=()
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    root_exec=(sudo -n)
  else
    echo "Skipping root-owned reboot permission test (passwordless sudo unavailable)."
  fi
fi

if [ "$(id -u)" -eq 0 ] || [ "${#root_exec[@]}" -gt 0 ]; then
  reboot_root="$tmp/reboot-permissions"
  mkdir -p "$reboot_root/home" "$reboot_root/data" "$reboot_root/log"
  "${root_exec[@]}" install -d -o root -g root -m 0755 "$reboot_root/config"
  "${root_exec[@]}" install -o root -g root -m 0600 config/config.json "$reboot_root/config/config.json"
  "${root_exec[@]}" perl -MJSON::PP -e '
    my ($path) = @ARGV;
    open my $in, "<", $path or die $!;
    local $/;
    my $cfg = decode_json(<$in>);
    close $in;
    $cfg->{keep_backups} = 3;
    open my $out, ">", $path or die $!;
    print $out JSON::PP->new->ascii->canonical->pretty->encode($cfg) or die $!;
    close $out or die $!;
  ' "$reboot_root/config/config.json"

  platform_uid="$(id -u)"
  platform_gid="$(id -g)"
  if [ "$platform_uid" -eq 0 ]; then
    platform_uid="$(id -u nobody 2>/dev/null || printf 65534)"
    platform_gid="$(id -g nobody 2>/dev/null || printf 65534)"
  fi
  "${root_exec[@]}" chown "$platform_uid:$platform_gid" "$reboot_root/log"
  "${root_exec[@]}" chmod 0755 "$reboot_root/log"

  "${root_exec[@]}" env \
    LBHOMEDIR="$reboot_root/home" \
    LBPCONFIGDIR="$reboot_root/config" \
    LBPDATADIR="$reboot_root/data" \
    LBPLOGDIR="$reboot_root/log" \
    bash "$ROOT/bin/hostbackup.sh" config > "$tmp/reboot-config-output.json"
  perl -MJSON::PP -e '
    local $/;
    my $cfg = decode_json(<STDIN>);
    die "saved configuration was not loaded after reboot\n" unless $cfg->{keep_backups} == 3;
  ' < "$tmp/reboot-config-output.json"
  test "$(stat -c '%u' "$reboot_root/log")" -eq "$platform_uid"
  test "$("${root_exec[@]}" stat -c '%u' "$reboot_root/data/root-state/logs")" -eq 0
  test "$("${root_exec[@]}" stat -c '%a' "$reboot_root/data/root-state/logs")" = 700
  "${root_exec[@]}" env \
    LBHOMEDIR="$reboot_root/home" \
    LBPCONFIGDIR="$reboot_root/config" \
    LBPDATADIR="$reboot_root/data" \
    LBPLOGDIR="$reboot_root/log" \
    bash "$ROOT/bin/hostbackup.sh" tasks > "$tmp/reboot-tasks-output.json"
  grep -Fxq '[]' "$tmp/reboot-tasks-output.json"
fi

printf 'do not read\n' > "$tmp/sentinel"
ln -s "$tmp/sentinel" "$tmp/log/backup-symlink.log"
if [ -L "$tmp/log/backup-symlink.log" ]; then
  LBHOMEDIR="$tmp/lbh" \
  LBPCONFIGDIR="$tmp/config" \
  LBPDATADIR="$tmp/data" \
  LBPLOGDIR="$tmp/log" \
    bash bin/hostbackup.sh tasks > "$tmp/tasks-output.json"
  if grep -Fq 'backup-symlink.log' "$tmp/tasks-output.json"; then
    echo "Task listing must ignore symlink logs" >&2
    exit 1
  fi
fi

grep -Fq '/usr/local/sbin/loxberryhostbackup-sudo *' sudoers/sudoers
if grep -Eq 'NOPASSWD:.*hostbackup\.sh' sudoers/sudoers; then
  echo "sudoers must not expose hostbackup.sh directly" >&2
  exit 1
fi
grep -Fq 'exec env -i' bin/hostbackup-sudo.sh
grep -Fq "printf '%s\\n' '-aHA'" bin/hostbackup.sh
grep -Fq 'O_NOFOLLOW' bin/hostbackup.sh
grep -Fq 'lock_file="$LOCK_DIR/export-$backup_id.lock"' bin/hostbackup.sh

echo "All HostBackup tests passed."
