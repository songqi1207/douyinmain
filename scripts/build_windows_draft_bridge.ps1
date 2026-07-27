$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

python -m pip install --disable-pip-version-check "pyinstaller==6.15.0" "uiautomation==2.0.29"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Windows helper build dependencies (exit code $LASTEXITCODE)"
}

python -m PyInstaller --noconfirm --clean AIVideoCreator.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed to build the Windows helper (exit code $LASTEXITCODE)"
}

$exe = Join-Path $repoRoot "dist\AIVideoCreator.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build completed without expected executable: $exe"
}
$file = Get-Item -LiteralPath $exe
Write-Output "Built: $($file.FullName)"
Write-Output "Bytes: $($file.Length)"
