$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$zip = Join-Path $root "LoxBerryHostBackup_0.1.0.zip"

if (Test-Path $zip) {
  Remove-Item -LiteralPath $zip
}

$items = @(
  "bin",
  "config",
  "uninstall",
  "webfrontend",
  "icons",
  "sudoers",
  "plugin.cfg",
  "postinstall.sh",
  "release.cfg",
  "prerelease.cfg",
  "README.md",
  "CHANGELOG.md",
  "LICENSE"
)

Compress-Archive -Path ($items | ForEach-Object { Join-Path $root $_ }) -DestinationPath $zip
Get-Item $zip
