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

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$rootPrefix = (Get-Item -LiteralPath $root).FullName.TrimEnd('\') + '\'
$archive = [System.IO.Compression.ZipFile]::Open($zip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
  foreach ($item in $items) {
    $path = Join-Path $root $item
    if (Test-Path -LiteralPath $path -PathType Container) {
      Get-ChildItem -LiteralPath $path -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($rootPrefix.Length).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $_.FullName, $relative, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
      }
    } else {
      $fullPath = (Get-Item -LiteralPath $path).FullName
      $relative = $fullPath.Substring($rootPrefix.Length).Replace('\', '/')
      [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $path, $relative, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
  }
} finally {
  $archive.Dispose()
}

Get-Item $zip
