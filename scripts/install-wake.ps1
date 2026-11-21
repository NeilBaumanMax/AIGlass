$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$modelName = 'sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
New-Item -ItemType Directory -Force .local, models | Out-Null
$archive = Join-Path (Get-Location) '.local/edith-kws.tar.bz2'
$expectedHash = '68447F4FBC67E70EEE3A93961F36E81E98F47AEF73CE7E7CA00885C6CD3616A6'
if (-not (Test-Path $archive) -or (Get-FileHash $archive -Algorithm SHA256).Hash -ne $expectedHash) {
    Invoke-WebRequest -Uri "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/$modelName.tar.bz2" -OutFile $archive
}
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Wake model checksum mismatch.' }
tar -xf $archive -C models
if ($LASTEXITCODE -ne 0) { throw 'Wake model extraction failed.' }
Write-Host 'Edith phoneme keyword model installed.'
