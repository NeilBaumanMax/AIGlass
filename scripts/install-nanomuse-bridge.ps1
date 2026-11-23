param(
    [Parameter(Mandatory=$true)][string]$AppRoot,
    [string]$Source = '.tools/nanomuse'
)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location $project
$appDir = (Resolve-Path -LiteralPath $AppRoot).Path
$exe = Join-Path $appDir 'nanomuse-desktop.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'AppRoot must contain nanomuse-desktop.exe' }
$running = @(Get-Process nanomuse-desktop -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe })
if ($running.Count) { throw 'Quit this nanoMuse through its menu first; closing the window may leave it in the tray.' }
$checkout = (Resolve-Path -LiteralPath $Source).Path
$built = Join-Path $checkout 'harness/desktop/dsh/node_modules/dsh-nanomuse'
$target = Join-Path $appDir 'resources/dsh/node_modules/dsh-nanomuse'
$new = Get-Content -LiteralPath (Join-Path $built 'package.json') -Raw | ConvertFrom-Json
$old = Get-Content -LiteralPath (Join-Path $target 'package.json') -Raw | ConvertFrom-Json
if ($new.version -ne '1.0.9' -or $old.version -ne $new.version) { throw 'Desktop plugin version mismatch; review before installing.' }
foreach ($peer in $new.peerDependencies.PSObject.Properties) {
    $declared = $old.peerDependencies.($peer.Name)
    if ($declared -and $declared -ne $peer.Value) { throw "Harness dependency mismatch: $($peer.Name)" }
    # A release may omit an explicit peer that is already installed transitively.
    # Verify the actual package version instead of treating a missing declaration as compatibility.
    $dependency = Join-Path $appDir ('resources/dsh/node_modules/' + $peer.Name + '/package.json')
    $actual = (Get-Content -LiteralPath $dependency -Raw | ConvertFrom-Json).version
    if ($actual -ne $peer.Value.TrimStart('~')) { throw "Installed Harness package version mismatch: $($peer.Name)" }
}
if (-not (Test-Path -LiteralPath (Join-Path $built 'lib/edith-bridge.js'))) { throw 'Build the Edith plugin first.' }
$backup = Join-Path $project ('.local/nanomuse-backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Force $backup | Out-Null
Copy-Item -LiteralPath $target -Destination (Join-Path $backup 'dsh-nanomuse') -Recurse
# Preserve the installation, user profile, account, other packages and old chunks.
# The complete compiled plugin is copied; package imports select the new chunk names.
foreach ($entry in Get-ChildItem -LiteralPath $built -Force) {
    Copy-Item -LiteralPath $entry.FullName -Destination $target -Recurse -Force
}
@{app_root=$appDir; backup=$backup; version=$new.version} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $project '.local/nanomuse-install.json') -Encoding utf8
Write-Output "Desktop plugin installed; original plugin backup: $backup"
Write-Output 'Launch with scripts/start-nanomuse.ps1 -InstalledApp <AppRoot> to enable the bridge and reuse the existing login.'
