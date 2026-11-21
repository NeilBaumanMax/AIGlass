param([string]$Glasses, [int]$Port = 7860)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = @(".runtime/python.exe", ".venv/Scripts/python.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { throw "Install the Python environment described in README.md first." }
$params = @("app.py", "--port", $Port)
if ($Glasses) { $params += @("--glasses", $Glasses) }
& (Resolve-Path $python) @params
exit $LASTEXITCODE
