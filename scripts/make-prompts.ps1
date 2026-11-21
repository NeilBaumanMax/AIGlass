$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = @(".runtime/python.exe", ".venv/Scripts/python.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) { throw "Install the Python environment described in README.md first." }
$python = Resolve-Path $python
$prompts = (& $python -c "import json; from speech import PROMPTS; print(json.dumps(PROMPTS))") | ConvertFrom-Json
New-Item -ItemType Directory -Force .local/prompts | Out-Null
$speaker = New-Object -ComObject SAPI.SpVoice
$voice = @($speaker.GetVoices() | Where-Object { $_.GetDescription() -like '*Huihui*' })[0]
if (-not $voice) { throw "Windows Chinese Huihui voice is required to build local prompts." }
$speaker.Voice = $voice
foreach ($entry in $prompts.PSObject.Properties) {
    $file = New-Object -ComObject SAPI.SpFileStream
    $file.Format.Type = 22
    try {
        $file.Open((Join-Path (Get-Location) ('.local/prompts/' + $entry.Name + '.wav')), 3)
        $speaker.AudioOutputStream = $file
        [void]$speaker.Speak($entry.Value)
    } finally {
        $file.Close()
    }
}
