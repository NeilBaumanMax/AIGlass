param([string]$Source = '.tools/nanomuse')
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location $project
$checkout = (Resolve-Path -LiteralPath $Source).Path
$desktop = Join-Path $checkout 'harness/desktop'
$electron = Join-Path $desktop 'node_modules/electron/dist/electron.exe'
if (-not (Test-Path -LiteralPath $electron)) { throw 'Build nanoMuse first; see docs/nanoMuse接入.md' }
if (-not (Test-Path -LiteralPath (Join-Path $desktop 'dsh/node_modules/dsh-nanomuse/lib/edith-bridge.js'))) {
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
$env:NANOMUSE_DESKTOP_HOME = Join-Path $project '.local/nanomuse-desktop'
# A dedicated profile preserves any separately installed nanoMuse desktop.
# Electron is the interactive app the user signs in to; do not hide its window.
Start-Process -FilePath $electron -ArgumentList @('"' + $desktop + '"') -WorkingDirectory $desktop
Write-Output 'nanoMuse desktop launched. Sign in and bind the phone in the app.'
