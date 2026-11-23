param(
    [ValidateSet('All', 'Environment', 'Assets')][string]$Stage = 'All',
    [string]$PythonPath = '',
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $project
if ($Plan) {
    Write-Output "Project: $project"
    Write-Output "Stage: $Stage (plan only; no files or environments changed)"
    Write-Output 'Environment: Python 3.11 x64 -> .venv; torch 2.6.0 cu126; requirements.txt; pip check'
    Write-Output 'Assets: pinned WalkGuide submodule and weights; Vosk CN; KWS; SpeexDSP; local speech prompts'
    Write-Output 'Config: create .env from .env.example ONLY if absent'
    Write-Output 'Next: configure your Qwen key and nanoMuse; run scripts/check-env.py; start.ps1'
    return
}
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'This installer supports Windows x64 only.' }
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE). Correct the error and rerun this stage." }
}
foreach ($name in @('git', 'tar')) { Get-Command $name -ErrorAction Stop | Out-Null }
New-Item -ItemType Directory -Force .local, .local/downloads, .tools, models | Out-Null

if ($Stage -in @('All', 'Environment')) {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        if (Test-Path -LiteralPath '.venv') { throw '.venv exists without Python. Inspect it before choosing another environment; it will not be overwritten.' }
        $basePython = if ($PythonPath) { (Resolve-Path -LiteralPath $PythonPath).Path } else { 'py' }
        $baseArgs = if ($PythonPath) { @() } else { @('-3.11') }
        Run $basePython ($baseArgs + @('-c', 'import sys; assert sys.version_info[:2]==(3,11) and sys.maxsize>2**32, "Python 3.11 x64 required"'))
        Run $basePython ($baseArgs + @('-m', 'venv', '.venv'))
    }
    $interpreter = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
    Run $interpreter @('-c', 'import sys; assert sys.version_info[:2]==(3,11) and sys.maxsize>2**32, "Existing .venv must use Python 3.11 x64"')
    Run $interpreter @('-m', 'pip', 'install', '--upgrade', 'pip')
    Run $interpreter @('-m', 'pip', 'install', 'torch==2.6.0', '--index-url', 'https://download.pytorch.org/whl/cu126')
    Run $interpreter @('-m', 'pip', 'install', '-r', 'requirements.txt')
    Run $interpreter @('-m', 'pip', 'check')
    Run $interpreter @('-c', 'import torch; assert torch.cuda.is_available() and torch.version.cuda=="12.6", "CUDA 12.6 runtime / NVIDIA driver check failed"; print(torch.cuda.get_device_name(0))')
}
if ($Stage -in @('All', 'Assets')) {
    $interpreter = @('.venv/Scripts/python.exe', '.runtime/python.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $interpreter) { throw 'Run -Stage Environment first.' }
    $interpreter = (Resolve-Path -LiteralPath $interpreter).Path
    Run git @('submodule', 'update', '--init', '--recursive')
    Run $interpreter @('vendor/walkguide/setup_models.py')
    if (-not (Test-Path -LiteralPath 'models/vosk-model-small-cn-0.22/am/final.mdl')) {
        $archive = Join-Path $project '.local/downloads/vosk-model-small-cn-0.22.zip'
        Invoke-WebRequest -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip' -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $project 'models') -Force
    }
    & (Join-Path $PSScriptRoot 'install-wake.ps1')
    & (Join-Path $PSScriptRoot 'install-aec.ps1')
    & (Join-Path $PSScriptRoot 'make-prompts.ps1')
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Output 'Installation stage completed. Configure .env and nanoMuse; then run scripts/check-env.py. No server or device was started.'
