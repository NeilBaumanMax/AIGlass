param([string]$Source = '.tools/nanomuse', [string]$Proxy = '')
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location $project
$revision = '09850259cab00d27af83786f00faa09b5d8494bf'
$checkout = [IO.Path]::GetFullPath($(if ([IO.Path]::IsPathRooted($Source)) { $Source } else { Join-Path $project $Source }))
$python = @('.runtime/python.exe', '.venv/Scripts/python.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { $python = (Get-Command python -ErrorAction Stop).Source }
$python = (Resolve-Path -LiteralPath $python).Path
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE)" }
}
$gitArgs = @()
if ($Proxy) { $gitArgs = @('-c', "http.proxy=$Proxy") }
if (-not (Test-Path -LiteralPath $checkout)) {
    Run git ($gitArgs + @('clone', '--filter=blob:none', '--sparse', 'https://github.com/nano-muse/nanoMuse.git', $checkout))
    Run git ($gitArgs + @('-C', $checkout, 'fetch', '--depth=1', 'origin', $revision))
    Run git @('-C', $checkout, 'checkout', '--detach', $revision)
}
Run git ($gitArgs + @('-C', $checkout, 'sparse-checkout', 'add', 'docs', 'nanomuse', 'config', 'harness', 'scripts', 'tests/fixtures',
    'android/src/android/app/src/main/assets/nanomuse', 'android/src/android/app/src/test/resources', 'android/src/ios/NanoMuse/Resources'))
Run $python @('scripts/prepare-nanomuse.py', $checkout)
Push-Location (Join-Path $checkout 'harness/dsh-nanomuse')
try {
    Run pnpm @('install', '--frozen-lockfile', '--ignore-scripts')
    Run pnpm @('build')
    Run pnpm @('typecheck')
    Run pnpm @('test')
} finally { Pop-Location }
Push-Location (Join-Path $checkout 'harness/desktop')
try {
    Run npm @('ci', '--ignore-scripts', '--no-audit', '--no-fund')
    # Upstream's staging script replaces only its dedicated dsh output directory.
    $stage = [IO.Path]::GetFullPath((Join-Path (Get-Location) 'dsh'))
    if ($stage -ne (Join-Path $checkout 'harness/desktop/dsh').Replace('/', '\')) { throw 'Unexpected staging path' }
    Run node @('scripts/prepare-dsh.mjs')
    if ($Proxy) {
        $env:ELECTRON_GET_USE_PROXY = '1'
        $env:GLOBAL_AGENT_HTTP_PROXY = $Proxy
        $env:GLOBAL_AGENT_HTTPS_PROXY = $Proxy
    }
    Run node @('node_modules/electron/install.js')
    Run npm @('run', 'build')
} finally { Pop-Location }
Write-Output 'Build complete. Run scripts/start-nanomuse.ps1, using the same -Source if specified.'
