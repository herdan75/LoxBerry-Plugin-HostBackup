$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginCfg = Get-Content (Join-Path $root "plugin.cfg")
$versionLine = $pluginCfg | Where-Object { $_ -match '^VERSION=' } | Select-Object -First 1
if (-not $versionLine) {
  throw "Cannot read VERSION from plugin.cfg"
}
$version = ($versionLine -replace '^VERSION=', '').Trim()
$zip = Join-Path $root "LoxBerryHostBackup_$version.zip"

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
