param(
    [string]$Server = "http://192.168.137.1:7860",
    [string]$Serial
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$adb = Resolve-Path ".tools/platform-tools/adb.exe"
if (-not (Test-Path .local/device-token)) { throw "Start the PC server once to create .local/device-token." }
$serverUri = [uri]$Server
if ($serverUri.Scheme -notin @('http', 'https') -or -not $serverUri.Host -or $serverUri.UserInfo -or $serverUri.Query) {
    throw "Server must be an HTTP(S) address without credentials or a query."
}
if (-not $Serial) {
    $devices = @(& $adb devices | Where-Object { $_ -match '^\S+\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
    if ($devices.Count -ne 1) { throw "Connect exactly one device or specify -Serial." }
    $Serial = $devices[0]
}
function Invoke-Adb {
    & $adb -s $Serial @args
    if ($LASTEXITCODE -ne 0) { throw "ADB operation failed." }
}
$config = @{server = $Server.TrimEnd('/'); token = (Get-Content .local/device-token -Raw).Trim()} | ConvertTo-Json -Compress
[IO.File]::WriteAllText((Join-Path (Get-Location) '.local/device-config.json'), $config, [Text.UTF8Encoding]::new($false))
Invoke-Adb shell 'if test -x /etc/init.d/S98aiglass; then /etc/init.d/S98aiglass stop; fi'
Invoke-Adb shell 'mkdir -p /userdata/aiglass'
Invoke-Adb push device/client.py /userdata/aiglass/client.py
Invoke-Adb push .local/device-config.json /userdata/aiglass/config.json
Invoke-Adb push device/S98aiglass /etc/init.d/S98aiglass
Invoke-Adb shell 'chmod 600 /userdata/aiglass/config.json; chmod 755 /etc/init.d/S98aiglass; /etc/init.d/S98aiglass start'
Write-Host "Audio client deployed. Check the read-only dashboard for connection and microphone status."
