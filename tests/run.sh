#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash -n \
  bin/hostbackup.sh \
  bin/hostbackup-sudo.sh \
  bin/restore-hostbackup.sh \
  postinstall.sh \
  uninstall/uninstall.sh \
  package.sh \
  tests/run.sh

python3 -m py_compile bin/validate-import-archive.py tests/test_archive_validator.py tests/test_web_security.py
python3 -m unittest discover -s tests -p 'test_*.py' -v

perl_lib="$ROOT/tests/perl"
if ! perl -MCGI -e 1 >/dev/null 2>&1; then
  perl_lib="$ROOT/tests/perl-stub:$perl_lib"
fi
PERL5LIB="$perl_lib${PERL5LIB:+:$PERL5LIB}" perl -c webfrontend/htmlauth/index.cgi

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
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
