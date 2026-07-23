param(
    [switch]$InstallLegacyExporter,
    [switch]$SkipScheduledTask
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$configPath = Join-Path $repoRoot ".env.render-worker"
$configExample = Join-Path $repoRoot ".env.render-worker.example"

Set-Location -LiteralPath $repoRoot
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv $venvRoot
}

& $python -m pip install --disable-pip-version-check --upgrade pip
& $python -m pip install --disable-pip-version-check -r (Join-Path $repoRoot "requirements.txt")
if ($InstallLegacyExporter) {
    & $python -m pip install --disable-pip-version-check "pyJianYingDraft" "uiautomation>=2"
}

if (-not (Test-Path -LiteralPath $configPath)) {
    Copy-Item -LiteralPath $configExample -Destination $configPath
    Write-Output "Created configuration: $configPath"
}

if (-not $SkipScheduledTask) {
    $taskName = "Douyin Windows Render Worker"
    $runner = Join-Path $repoRoot "scripts\run_windows_render_worker.ps1"
    $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $repoRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output "Registered interactive logon task: $taskName"
}

Write-Output "Next: edit $configPath, keep the render account logged on, then run:"
Write-Output "powershell -ExecutionPolicy Bypass -File scripts\run_windows_render_worker.ps1"
