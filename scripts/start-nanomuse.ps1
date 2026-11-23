param([string]$Source = '.tools/nanomuse', [string]$InstalledApp = '')
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location $project
$checkout = if ($InstalledApp) { '' } else { (Resolve-Path -LiteralPath $Source).Path }
$desktop = if ($InstalledApp) { (Resolve-Path -LiteralPath $InstalledApp).Path } else { Join-Path $checkout 'harness/desktop' }
$electron = if ($InstalledApp) { Join-Path $desktop 'nanomuse-desktop.exe' } else { Join-Path $desktop 'node_modules/electron/dist/electron.exe' }
if (-not (Test-Path -LiteralPath $electron)) { throw 'Build nanoMuse first; see docs/nanoMuse接入.md' }
$plugin = if ($InstalledApp) { 'resources/dsh/node_modules/dsh-nanomuse/lib/edith-bridge.js' } else { 'dsh/node_modules/dsh-nanomuse/lib/edith-bridge.js' }
if (-not (Test-Path -LiteralPath (Join-Path $desktop $plugin))) {
    throw 'The desktop does not contain the Edith bridge. Run setup-nanomuse.ps1.'
}
New-Item -ItemType Directory -Force (Join-Path $project '.local') | Out-Null
$tokenPath = Join-Path $project '.local/nanomuse-token'
if (-not (Test-Path -LiteralPath $tokenPath)) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [IO.File]::WriteAllText($tokenPath, [Convert]::ToBase64String($bytes))
}
$env:EDITH_BRIDGE_TOKEN_FILE = $tokenPath
if ($InstalledApp) {
    # The installed app's own home and Chromium profile already contain the login.
    if ($env:NANOMUSE_DESKTOP_HOME -eq (Join-Path $project '.local/nanomuse-desktop')) {
        Remove-Item Env:NANOMUSE_DESKTOP_HOME -ErrorAction SilentlyContinue
    }
} else {
    $env:NANOMUSE_DESKTOP_HOME = Join-Path $project '.local/nanomuse-desktop'
}
# A dedicated profile preserves any separately installed nanoMuse desktop.
# Electron is the interactive app the user signs in to; do not hide its window.
$browserProfile = Join-Path $project '.local/nanomuse-browser'
if ($InstalledApp) {
    $process = Start-Process -FilePath $electron -WorkingDirectory $desktop -PassThru
} else {
    $process = Start-Process -FilePath $electron -ArgumentList @('"' + $desktop + '"', '--user-data-dir="' + $browserProfile + '"') -WorkingDirectory $desktop -PassThru
}
if ($process.WaitForExit(1500)) { throw 'nanoMuse exited during launch; check the desktop log before continuing.' }
Write-Output 'nanoMuse desktop launched. Sign in and bind the phone in the app.'
