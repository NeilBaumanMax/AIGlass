param([string]$Serial)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$adb = Resolve-Path '.tools/platform-tools/adb.exe'
if (-not $Serial) {
    $devices = @(& $adb devices | Where-Object { $_ -match '^\S+\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
    if ($devices.Count -ne 1) { throw 'Connect exactly one board, or specify -Serial.' }
    $Serial = $devices[0]
}
function Invoke-Adb {
    & $adb -s $Serial @args
    if ($LASTEXITCODE -ne 0) { throw 'Camera deployment failed. Check board output above.' }
}
# This profile is separate from /userdata/rkipc.ini, which the vendor boot
# script overwrites. Never replace firmware, Wi-Fi settings or audio service.
Invoke-Adb shell 'test -f /oem/usr/share/rkipc-imx415-500w.ini'
Invoke-Adb shell 'test -x /oem/usr/bin/rkipc'
Invoke-Adb shell 'mkdir -p /userdata/aiglass'
Invoke-Adb shell 'if test -f /userdata/aiglass/camera.ini; then cp -p /userdata/aiglass/camera.ini /userdata/aiglass/camera.ini.bak; fi'
Invoke-Adb push device/camera_config.py /userdata/aiglass/camera_config.py
Invoke-Adb shell 'python3 /userdata/aiglass/camera_config.py /oem/usr/share/rkipc-imx415-500w.ini /userdata/aiglass/camera.ini'
Invoke-Adb shell 'chmod 600 /userdata/aiglass/camera.ini'
Invoke-Adb push device/S97aiglass-camera /etc/init.d/S97aiglass-camera
Invoke-Adb shell 'chmod 755 /etc/init.d/S97aiglass-camera; /etc/init.d/S97aiglass-camera start'
Write-Output 'IMX415 video service installed. Validate the real Wi-Fi RTSP stream and dashboard.'
Write-Output 'If an existing service was already running, restart it explicitly to apply a changed profile.'
