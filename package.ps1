$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginCfg = Get-Content (Join-Path $root "plugin.cfg")
$versionLine = $pluginCfg | Where-Object { $_ -match '^VERSION=' } | Select-Object -First 1
if (-not $versionLine) {
  throw "Cannot read VERSION from plugin.cfg"
}
$version = ($versionLine -replace '^VERSION=', '').Trim()
$outputDir = if ($env:HOSTBACKUP_PACKAGE_OUTPUT_DIR) { $env:HOSTBACKUP_PACKAGE_OUTPUT_DIR } else { $root }
$outputDir = [System.IO.Path]::GetFullPath($outputDir)
[System.IO.Directory]::CreateDirectory($outputDir) | Out-Null
$zip = Join-Path $outputDir "LoxBerryHostBackup_$version.zip"

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
  "docs",
  "plugin.cfg",
  "preroot.sh",
  "postinstall.sh",
  "postroot.sh",
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
      Get-ChildItem -LiteralPath $path -Recurse -File |
        Where-Object { $_.Extension -notin @('.pyc', '.pyo') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]' } |
        ForEach-Object {
        $relative = $_.FullName.Substring($rootPrefix.Length).Replace('\', '/')
        $entry = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $_.FullName, $relative, [System.IO.Compression.CompressionLevel]::Optimal)
        $entry.ExternalAttributes = if ($relative -match '(\.sh|\.cgi|\.py)$') { -2115174400 } else { -2119958528 }
      }
    } else {
      $fullPath = (Get-Item -LiteralPath $path).FullName
      $relative = $fullPath.Substring($rootPrefix.Length).Replace('\', '/')
      $entry = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $path, $relative, [System.IO.Compression.CompressionLevel]::Optimal)
      $entry.ExternalAttributes = if ($relative -match '(\.sh|\.cgi|\.py)$') { -2115174400 } else { -2119958528 }
    }
  }
} finally {
  $archive.Dispose()
}

Get-Item $zip
