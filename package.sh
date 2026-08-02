#!/bin/bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
if [ "$SCRIPT_DIR" = "$SCRIPT_PATH" ]; then
  SCRIPT_DIR="."
fi
ROOT="$(cd "$SCRIPT_DIR" && pwd)"
VERSION=""
while IFS='=' read -r key value; do
  if [ "$key" = "VERSION" ]; then
    VERSION="${value//$'\r'/}"
    VERSION="${VERSION//[[:space:]]/}"
    break
  fi
done < "$ROOT/plugin.cfg"
[ -n "$VERSION" ] || { echo "Cannot read VERSION from plugin.cfg" >&2; exit 1; }
ZIP_NAME="LoxBerryHostBackup_${VERSION}.zip"
OUTPUT_DIR="${HOSTBACKUP_PACKAGE_OUTPUT_DIR:-$ROOT}"
mkdir -p -- "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
ZIP_PATH="$OUTPUT_DIR/$ZIP_NAME"

rm -f "$ZIP_PATH"

cd "$ROOT"
zip -r "$ZIP_PATH" \
  bin \
  config \
  uninstall \
  webfrontend \
  icons \
  sudoers \
  docs \
  plugin.cfg \
  preroot.sh \
  postinstall.sh \
  postroot.sh \
  release.cfg \
  prerelease.cfg \
  README.md \
  CHANGELOG.md \
  LICENSE

printf '%s\n' "$ZIP_PATH"
