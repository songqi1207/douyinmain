param(
    [Parameter(Mandatory = $true)]
    [string]$DraftId,

    [Parameter(Mandatory = $true)]
    [string]$MiheExe,

    [int]$TimeoutSeconds = 35,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($DraftId -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$') {
    throw "Invalid Mihe draft ID: expected UUID v4"
}

$resolvedExe = (Resolve-Path -LiteralPath $MiheExe).Path
if ([System.IO.Path]::GetExtension($resolvedExe) -ne '.exe') {
    throw "Mihe executable must be an .exe file"
}

if ($DryRun) {
    [pscustomobject]@{
        status = "dry_run"
        draft_id = $DraftId.ToLowerInvariant()
        executable = $resolvedExe
    } | ConvertTo-Json -Compress
    exit 0
}

Set-Clipboard -Value $DraftId
$process = Start-Process -FilePath $resolvedExe -WorkingDirectory (Split-Path -Parent $resolvedExe) -PassThru

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$deadline = (Get-Date).AddSeconds([Math]::Max(5, $TimeoutSeconds))
$automationStatus = "manual_fallback"
$detail = "draft_id copied to clipboard"

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 350
    $process.Refresh()
    if ($process.HasExited) {
        throw "Mihe synchronizer exited before its window was ready"
    }
    if ($process.MainWindowHandle -eq 0) {
        continue
    }

    try {
        $root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
        if (-not $root) {
            continue
        }

        $editCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Edit
        )
        $edits = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
        $targetEdit = $null
        foreach ($edit in $edits) {
            $name = [string]$edit.Current.Name
            if ($name -match '(草稿|draft|输入)') {
                $targetEdit = $edit
                break
            }
        }
        if (-not $targetEdit -and $edits.Count -eq 1) {
            $targetEdit = $edits.Item(0)
        }
        if (-not $targetEdit) {
            continue
        }

        $valuePattern = $null
        if (-not $targetEdit.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$valuePattern)) {
            continue
        }
        if ($valuePattern.Current.IsReadOnly) {
            continue
        }
        $valuePattern.SetValue($DraftId)

        $buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Button
        )
        $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
        $targetButton = $null
        foreach ($button in $buttons) {
            $name = [string]$button.Current.Name
            if ($name -match '(创建剪映草稿|下载草稿|创建草稿)') {
                $targetButton = $button
                break
            }
        }
        if (-not $targetButton) {
            $automationStatus = "id_filled_button_not_found"
            $detail = "draft_id filled; click the create/download button manually"
            break
        }

        $invokePattern = $null
        if ($targetButton.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invokePattern)) {
            $invokePattern.Invoke()
            $automationStatus = "submitted"
            $detail = "draft_id filled and submit button invoked"
            break
        }
    }
    catch {
        $detail = $_.Exception.Message
    }
}

if ($automationStatus -eq "manual_fallback") {
    try {
        $shell = New-Object -ComObject WScript.Shell
        [void]$shell.AppActivate($process.Id)
    }
    catch {
        $detail = "draft_id copied; activate the Mihe window and paste manually"
    }
}

[pscustomobject]@{
    status = $automationStatus
    draft_id = $DraftId.ToLowerInvariant()
    executable = $resolvedExe
    process_id = $process.Id
    detail = $detail
} | ConvertTo-Json -Compress
