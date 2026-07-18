$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

python -m pip install --disable-pip-version-check "pyinstaller==6.15.0"
python -m PyInstaller --noconfirm --clean DouyinDraftBridge.spec

$exe = Join-Path $repoRoot "dist\DouyinDraftBridge.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build completed without expected executable: $exe"
}
$file = Get-Item -LiteralPath $exe
Write-Output "Built: $($file.FullName)"
Write-Output "Bytes: $($file.Length)"
