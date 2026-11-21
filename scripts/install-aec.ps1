$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force .local, .tools/speexdsp | Out-Null
$url = 'https://repo.msys2.org/mingw/mingw64/mingw-w64-x86_64-speexdsp-1.2.1-2-any.pkg.tar.zst'
Invoke-WebRequest $url -OutFile .local/speexdsp.pkg.tar.zst
if ((Get-FileHash .local/speexdsp.pkg.tar.zst -Algorithm SHA256).Hash -ne 'c34c5a5f3b3a947fe3c5d0108346964b5ac026e6143f987bdd9e5726d890a29c') {
    throw 'SpeexDSP package SHA256 mismatch'
}
tar -xf .local/speexdsp.pkg.tar.zst -C .tools/speexdsp
if ($LASTEXITCODE -ne 0) { throw 'Cannot extract SpeexDSP' }
Write-Host 'SpeexDSP installed. BSD license is under .tools/speexdsp/mingw64/share/licenses/speexdsp/.'
