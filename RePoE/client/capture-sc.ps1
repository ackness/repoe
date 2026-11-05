<#
.SYNOPSIS
  Copy the China (Tencent) PoE2 client files needed for one official-text capture, and print hashes.
.DESCRIPTION
  Read-only on the client. Close the game AND the launcher first (an update rewrites the index and bundles).
  Copies Bundles2\_.index.bin, every Bundles2\Folders\data\** bundle (all Data/ tables and stat descriptions
  that live in data-folder bundles, ~30 MB), and the explicit extra bundles below (Tiny.* and one metadata
  bundle that the 2026-11-05 index uses for needed tables). Writes capture.json (paths, bytes, SHA-256,
  timestamps, exe version info) and SHA256SUMS next to the copies.
  The extra list comes from the index sha256 1fa59396...1e578. After a client update the Linux side
  re-locates every needed path in the NEW index; if it names a bundle that is not here, rerun with
  -Extra 'Tiny.VX.1.bundle.bin', ... (paths relative to Bundles2).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File capture-sc.ps1 -ClientRoot 'D:\WeGameApps\PoE2' -OutRoot 'E:\poe2-capture'
#>
param(
  [Parameter(Mandatory = $true)][string]$ClientRoot,
  [Parameter(Mandatory = $true)][string]$OutRoot,
  [string[]]$Extra = @()
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

$ExtraBundles = @(
    'Folders/metadata/alternateskillgraphs.bundle.bin',
    'Tiny.V0.1.bundle.bin',
    'Tiny.V3.1.bundle.bin',
    'Tiny.V4.2.bundle.bin',
    'Tiny.V5.1.bundle.bin',
    'Tiny.VB.1.bundle.bin',
    'Tiny.VC.1.bundle.bin',
    'Tiny.VE.1.bundle.bin'
) + $Extra

function Get-Ident([string]$path, [string]$rel) {
  $item = Get-Item -LiteralPath $path
  [ordered]@{
    path      = $rel -replace '\\', '/'
    bytes     = $item.Length
    sha256    = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    mtime_utc = $item.LastWriteTimeUtc.ToString('o')
  }
}

$bundles2 = Join-Path $ClientRoot 'Bundles2'
$indexPath = Join-Path $bundles2 '_.index.bin'
if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) { throw "not found: $indexPath" }
$running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PathOfExile*' }
if ($running) { throw "close the game first: $($running.ProcessName -join ', ')" }

# Relative paths to copy: _.index.bin, all data-folder bundles, explicit extras.
$rels = New-Object System.Collections.Generic.List[string]
$rels.Add('_.index.bin')
$dataDir = Join-Path $bundles2 'Folders/data'
Get-ChildItem -LiteralPath $dataDir -Recurse -File -Filter '*.bundle.bin' | Sort-Object FullName | ForEach-Object {
  $rels.Add(($_.FullName.Substring($bundles2.Length + 1) -replace '\\', '/'))
}
foreach ($e in $ExtraBundles) { $e = $e -replace '\\', '/'; if (-not $rels.Contains($e)) { $rels.Add($e) } }
$missing = @($rels | Where-Object { -not (Test-Path -LiteralPath (Join-Path $bundles2 $_) -PathType Leaf) })
if ($missing.Count) { throw "missing in client: $($missing -join ', ')" }

$before = Get-Ident $indexPath '_.index.bin'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out = Join-Path $OutRoot "sc-capture-$stamp"
if (Test-Path -LiteralPath $out) { throw "exists: $out" }
New-Item -ItemType Directory -Path $out | Out-Null

$files = @()
foreach ($rel in $rels) {
  $src = Join-Path $bundles2 $rel
  $dst = Join-Path (Join-Path $out 'Bundles2') $rel
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
  [System.IO.File]::Copy($src, $dst, $false)
  $s = Get-Ident $src $rel
  $d = Get-Ident $dst $rel
  if ($s.sha256 -ne $d.sha256 -or $s.bytes -ne $d.bytes) { throw "copy mismatch: $rel" }
  $files += $d
  Write-Host ('{0}  {1,11}  {2}' -f $d.sha256, $d.bytes, $d.path)
}

# The index must be unchanged from start to end (no update ran during the copy).
$after = Get-Ident $indexPath '_.index.bin'
if ($after.sha256 -ne $before.sha256 -or $after.mtime_utc -ne $before.mtime_utc) {
  throw 'the client index changed during the copy; close the launcher and run again'
}

$exe = @(Get-ChildItem -LiteralPath $ClientRoot -File -Filter 'PathOfExile*.exe' | ForEach-Object {
  $v = $_.VersionInfo
  [ordered]@{ name = $_.Name; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant();
              file_version = $v.FileVersion; product_version = $v.ProductVersion; mtime_utc = $_.LastWriteTimeUtc.ToString('o') }
})

$capture = [ordered]@{
  schema          = 'pobr-sc-client-capture/v1'
  realm_declared  = 'china'
  captured_utc    = $stamp
  client_root     = $ClientRoot
  index           = $before
  executables     = $exe
  files           = $files
  total_bytes     = [int64]0
  script_sha256   = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
foreach ($f in $files) { $capture.total_bytes += $f.bytes }
$json = $capture | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $out 'capture.json'), $json + "`n", (New-Object System.Text.UTF8Encoding $false))
$sums = ($files | ForEach-Object { '{0}  Bundles2/{1}' -f $_.sha256, $_.path }) -join "`n"
[System.IO.File]::WriteAllText((Join-Path $out 'SHA256SUMS'), $sums + "`n", (New-Object System.Text.UTF8Encoding $false))

Write-Host ''
Write-Host ("index  {0}  {1} bytes" -f $before.sha256, $before.bytes)
Write-Host ("files  {0}  total {1:N0} bytes" -f $files.Count, $capture.total_bytes)
Write-Host ("capture.json sha256 {0}" -f (Get-FileHash -LiteralPath (Join-Path $out 'capture.json') -Algorithm SHA256).Hash.ToLowerInvariant())
Write-Host "send the folder: $out"
