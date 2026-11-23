$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force .local/downloads/speexdsp, .tools/speexdsp | Out-Null
$url = 'https://repo.msys2.org/mingw/mingw64/mingw-w64-x86_64-speexdsp-1.2.1-2-any.pkg.tar.zst'
$archive = '.local/downloads/speexdsp.pkg.tar.zst'
$expectedHash = 'c34c5a5f3b3a947fe3c5d0108346964b5ac026e6143f987bdd9e5726d890a29c'
if (-not (Test-Path -LiteralPath $archive) -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
    Invoke-WebRequest $url -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'SpeexDSP package SHA256 mismatch'
}
tar -xf $archive -C .local/downloads/speexdsp
if ($LASTEXITCODE -ne 0) { throw 'Cannot extract SpeexDSP' }
$staged = (Resolve-Path -LiteralPath '.local/downloads/speexdsp').Path
$destination = (Resolve-Path -LiteralPath '.tools/speexdsp').Path
foreach ($file in Get-ChildItem -LiteralPath $staged -File -Recurse -Force) {
    $relative = $file.FullName.Substring($staged.Length + 1)
    $target = [IO.Path]::GetFullPath((Join-Path $destination $relative))
    if (-not $target.StartsWith($destination + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected SpeexDSP destination'
    }
    # A running backend holds the DLL open. Reuse identical verified files.
    if ((Test-Path -LiteralPath $target) -and (Get-FileHash -LiteralPath $target).Hash -eq (Get-FileHash -LiteralPath $file.FullName).Hash) { continue }
    New-Item -ItemType Directory -Force (Split-Path $target -Parent) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
}
Write-Host 'SpeexDSP installed. BSD license is under .tools/speexdsp/mingw64/share/licenses/speexdsp/.'
