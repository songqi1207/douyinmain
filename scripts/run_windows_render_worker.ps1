param(
    [string]$EnvFile,
    [string]$ListenHost,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Worker virtual environment does not exist: $python"
}

if (-not $EnvFile) {
    $EnvFile = Join-Path $repoRoot ".env.render-worker"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Worker configuration does not exist: $EnvFile"
}

Get-Content -LiteralPath $EnvFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
        return
    }
    $name, $value = $line.Split("=", 2)
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
}

if (-not $ListenHost) {
    $ListenHost = if ($env:WINDOWS_RENDER_HOST) { $env:WINDOWS_RENDER_HOST } else { "127.0.0.1" }
}
if ($Port -le 0) {
    $Port = if ($env:WINDOWS_RENDER_PORT) { [int]$env:WINDOWS_RENDER_PORT } else { 8765 }
}

$logDir = Join-Path $env:LOCALAPPDATA "DouyinRenderWorker\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir ("worker-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

Set-Location -LiteralPath $repoRoot
& $python -m uvicorn windows_render_worker:app --host $ListenHost --port $Port *>> $logPath
exit $LASTEXITCODE
