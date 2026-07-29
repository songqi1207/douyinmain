param(
    [Parameter(Mandatory = $true)]
    [string]$DraftName,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [Parameter(Mandatory = $true)]
    [string]$JianyingExe,
    [string]$LogPath = "",
    [int]$TimeoutSeconds = 1800,
    [int]$NoOutputTimeoutSeconds = 210,
    [switch]$RestartExisting
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = [System.IO.Path]::GetDirectoryName($OutputPath)
$outputName = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

function Write-Stage([string]$Stage, [string]$Details = "") {
    $suffix = if ($Details) { " $Details" } else { "" }
    $message = "jianying_automation_stage stage=$Stage$suffix"
    Write-Output $message
    if ($LogPath) {
        try {
            $resolvedLogPath = [System.IO.Path]::GetFullPath($LogPath)
            [System.IO.Directory]::CreateDirectory(
                [System.IO.Path]::GetDirectoryName($resolvedLogPath)
            ) | Out-Null
            $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss,fff")
            [System.IO.File]::AppendAllText(
                $resolvedLogPath,
                "$timestamp INFO $message$([Environment]::NewLine)",
                $utf8
            )
        }
        catch {
            # Logging must never interrupt a user's video export.
        }
    }
}

Write-Stage "automation_started" "timeout_seconds=$TimeoutSeconds"

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
$fullDescriptionProperty = [System.Windows.Automation.AutomationProperty]::LookupById(30159)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class JianyingNative {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
}
"@

function Get-FullDescription($Element) {
    try {
        $value = $Element.GetCurrentPropertyValue($fullDescriptionProperty)
        if ($value -and $value -ne [System.Windows.Automation.AutomationElement]::NotSupported) {
            return [string]$value
        }
    }
    catch {}
    return ""
}

function Get-JianyingProcess {
    $candidates = @(Get-Process | Where-Object {
        $_.ProcessName -match '^(JianyingPro|CapCut)$' -and $_.MainWindowHandle -ne 0
    })
    $preferred = @($candidates | Where-Object {
        try {
            $window = [System.Windows.Automation.AutomationElement]::FromHandle($_.MainWindowHandle)
            $window -and $window.Current.ClassName -match '(HomePage|MainWindow)'
        }
        catch {
            $false
        }
    })
    if ($preferred.Count -gt 0) {
        return $preferred | Sort-Object StartTime | Select-Object -Last 1
    }
    return $candidates | Sort-Object StartTime | Select-Object -Last 1
}

function Get-ProcessRoots([int]$ProcessId) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty,
        $ProcessId
    )
    return [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        $condition
    )
}

function Get-VisibleElements([int]$ProcessId) {
    $items = New-Object System.Collections.Generic.List[object]
    foreach ($root in (Get-ProcessRoots $ProcessId)) {
        try {
            foreach ($element in $root.FindAll(
                [System.Windows.Automation.TreeScope]::Subtree,
                [System.Windows.Automation.Condition]::TrueCondition
            )) {
                if (-not $element.Current.IsOffscreen -and $element.Current.IsEnabled) {
                    $items.Add($element)
                }
            }
        }
        catch {
            # Jianying frequently replaces transient Chromium/Qt elements.
        }
    }
    return $items
}

function Wait-Element([int]$ProcessId, [scriptblock]$Selector, [int]$Seconds, [string]$Description) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $match = Get-VisibleElements $ProcessId | Where-Object $Selector | Select-Object -First 1
        if ($match) {
            return $match
        }
        Start-Sleep -Milliseconds 500
    }
    throw "等待剪映界面元素超时：$Description"
}

function Write-VisibleElementSnapshot([int]$ProcessId) {
    $written = 0
    foreach ($element in (Get-VisibleElements $ProcessId)) {
        $name = ([string]$element.Current.Name).Replace("`r", " ").Replace("`n", " ").Trim()
        $description = (Get-FullDescription $element).Replace("`r", " ").Replace("`n", " ").Trim()
        if (-not $name -and -not $description) {
            continue
        }
        if ($name.Length -gt 120) {
            $name = $name.Substring(0, 120)
        }
        if ($description.Length -gt 180) {
            $description = $description.Substring(0, 180)
        }
        Write-Stage "ui_element" "type=$($element.Current.ControlType.ProgrammaticName) class=$($element.Current.ClassName) name=$name description=$description"
        $written += 1
        if ($written -ge 80) {
            break
        }
    }
    Write-Stage "ui_snapshot_finished" "elements=$written"
}

function Invoke-Element($Element, [switch]$DoubleClick) {
    try {
        $pattern = $Element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        if ($pattern -and -not $DoubleClick) {
            $pattern.Invoke()
            return
        }
    }
    catch {}

    $rect = $Element.Current.BoundingRectangle
    if ($rect.Width -le 1 -or $rect.Height -le 1) {
        throw "剪映控件没有可点击区域：$($Element.Current.Name)"
    }
    $x = [int]($rect.X + ($rect.Width / 2))
    $y = [int]($rect.Y + ($rect.Height / 2))
    [JianyingNative]::SetCursorPos($x, $y) | Out-Null
    [JianyingNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [JianyingNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    if ($DoubleClick) {
        Start-Sleep -Milliseconds 120
        [JianyingNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
        [JianyingNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    }
}

function Invoke-Point([int]$X, [int]$Y) {
    [JianyingNative]::SetCursorPos($X, $Y) | Out-Null
    [JianyingNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [JianyingNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

function Get-WindowRect($Process) {
    $rect = New-Object JianyingNative+RECT
    if (-not [JianyingNative]::GetWindowRect($Process.MainWindowHandle, [ref]$rect)) {
        throw "无法读取剪映窗口位置"
    }
    return $rect
}

function Invoke-HomeDraftCardByCoordinate($Process) {
    $rect = Get-WindowRect $Process
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $x = [int]($rect.Left + ($width * 0.255))
    $y = [int]($rect.Top + ($height * 0.775))
    Write-Stage "draft_card_coordinate_click" "x=$x y=$y"
    Invoke-Point $x $y
    Start-Sleep -Milliseconds 150
    Invoke-Point $x $y
}

function Invoke-EditorExportByCoordinate($Process) {
    Write-Stage "editor_export_shortcut" "key=ctrl+e"
    [System.Windows.Forms.SendKeys]::SendWait("^e")
}

function Get-ExportWindowRect([int]$ProcessId) {
    $exportWindow = Get-ProcessRoots $ProcessId | Where-Object {
        $_.Current.ClassName -match 'ExportWindow' -or $_.Current.Name -match '^\s*导出'
    } | Select-Object -First 1
    if ($exportWindow) {
        return $exportWindow.Current.BoundingRectangle
    }
    $process = Get-Process -Id $ProcessId -ErrorAction Stop
    return Get-WindowRect $process
}

function Set-TextByCoordinate([int]$X, [int]$Y, [string]$Value) {
    Invoke-Point $X $Y
    Start-Sleep -Milliseconds 200
    [System.Windows.Forms.Clipboard]::SetText($Value)
    [System.Windows.Forms.SendKeys]::SendWait("^a")
    Start-Sleep -Milliseconds 80
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    Start-Sleep -Milliseconds 250
}

function Invoke-ExportDialogByCoordinate([int]$ProcessId, [string]$Name, [string]$Directory) {
    $rect = Get-ExportWindowRect $ProcessId
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $nameX = [int]($rect.Left + ($width * 0.80))
    $nameY = [int]($rect.Top + ($height * 0.14))
    $pathX = [int]($rect.Left + ($width * 0.80))
    $pathY = [int]($rect.Top + ($height * 0.195))
    # The bottom-right row is usually "Export" followed by "Cancel". Click the
    # left button, not the rightmost button.
    $confirmX = [int]($rect.Right - [Math]::Min(170, [Math]::Max(135, $width * 0.20)))
    $confirmY = [int]($rect.Bottom - [Math]::Min(50, [Math]::Max(38, $height * 0.05)))
    Write-Stage "export_dialog_coordinate_fields" "name_x=$nameX name_y=$nameY path_x=$pathX path_y=$pathY confirm_x=$confirmX confirm_y=$confirmY"
    Set-TextByCoordinate $nameX $nameY $Name
    Set-TextByCoordinate $pathX $pathY $Directory
    Invoke-Point $confirmX $confirmY
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
}

function Get-CandidateOutputPaths {
    $directories = @(
        $outputDirectory,
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Videos"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "Documents")
    )
    $names = @($outputName, $DraftName) | Where-Object { $_ } | Select-Object -Unique
    $paths = New-Object System.Collections.Generic.List[string]
    $paths.Add($OutputPath)
    foreach ($directory in $directories) {
        if (-not $directory -or -not (Test-Path -LiteralPath $directory -PathType Container)) {
            continue
        }
        foreach ($name in $names) {
            $paths.Add((Join-Path $directory "$name.mp4"))
        }
    }
    return $paths | Select-Object -Unique
}

function Minimize-JianyingWindow {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$Reason
    )
    if (-not $Process) {
        return
    }
    try {
        $currentProcess = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
        if ($currentProcess -and $currentProcess.MainWindowHandle -ne 0) {
            [JianyingNative]::ShowWindow($currentProcess.MainWindowHandle, 6) | Out-Null
            Write-Stage "jianying_minimized" "reason=$Reason"
        }
    }
    catch {
        Write-Stage "jianying_minimize_failed" "reason=$Reason error=$($_.Exception.Message)"
    }
}

function Dismiss-JianyingPopups([int]$ProcessId) {
    $dismissPattern = '(放弃福利|暂不|以后再说|取消|跳过|我知道了|知道了|Not now|Later|Skip|Cancel)'
    $dismissed = 0
    for ($attempt = 0; $attempt -lt 4; $attempt += 1) {
        $draftListProblem = Get-ProcessRoots $ProcessId | Where-Object {
            ($_.Current.Name + " " + (Get-FullDescription $_)) -match '草稿列表异常|草稿丢失'
        } | Select-Object -First 1
        if ($draftListProblem) {
            $confirm = Get-VisibleElements $ProcessId | Where-Object {
                (($_.Current.Name + " " + (Get-FullDescription $_)) -match '^\s*(确认|确定|OK)\s*$') -and
                $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
            } | Select-Object -First 1
            if ($confirm) {
                Write-Stage "popup_dismissed" "name=draft_list_problem_confirm"
                Invoke-Element $confirm
                $dismissed += 1
                Start-Sleep -Milliseconds 900
                continue
            }
        }
        $splash = Get-ProcessRoots $ProcessId | Where-Object {
            $_.Current.ClassName -match 'SplashDialog|Dialog|Popup' -or
            $_.Current.Name -match 'JianyingPro'
        } | Where-Object {
            $rect = $_.Current.BoundingRectangle
            $rect.Width -gt 200 -and $rect.Height -gt 120 -and $rect.Width -lt 1400 -and $rect.Height -lt 1000
        } | Select-Object -First 1
        if ($splash) {
            $rect = $splash.Current.BoundingRectangle
            # Jianying marketing dialogs sometimes expose only the top-level
            # SplashDialog. The safe-dismiss button is near the lower-right,
            # left of the brightly colored purchase button.
            $x = [int]($rect.Right - [Math]::Min(230, [Math]::Max(80, $rect.Width * 0.33)))
            $y = [int]($rect.Bottom - [Math]::Min(55, [Math]::Max(35, $rect.Height * 0.12)))
            Write-Stage "popup_dismissed" "mode=splash_click class=$($splash.Current.ClassName) x=$x y=$y"
            Invoke-Point $x $y
            $dismissed += 1
            Start-Sleep -Milliseconds 900
            continue
        }
        $target = Get-VisibleElements $ProcessId | Where-Object {
            $text = ($_.Current.Name + " " + (Get-FullDescription $_)).Trim()
            $text -match $dismissPattern -and
            $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
        } | Select-Object -First 1
        if (-not $target) {
            if ($attempt -eq 0) {
                [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
                Start-Sleep -Milliseconds 300
                continue
            }
            break
        }
        $name = ([string]$target.Current.Name).Replace("`r", " ").Replace("`n", " ").Trim()
        Write-Stage "popup_dismissed" "name=$name"
        Invoke-Element $target
        $dismissed += 1
        Start-Sleep -Milliseconds 700
    }
    return $dismissed
}

function Set-ElementValue($Element, [string]$Value) {
    try {
        $pattern = $Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        if ($pattern -and -not $pattern.Current.IsReadOnly) {
            $pattern.SetValue($Value)
            return $true
        }
    }
    catch {}
    return $false
}

if (-not (Test-Path -LiteralPath $JianyingExe -PathType Leaf)) {
    throw "剪映程序不存在：$JianyingExe"
}

$jianyingVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($JianyingExe).FileVersion
$jianyingVersion = ([string]$jianyingVersion).Replace(" ", "_")
$startedJianying = $false
Write-Stage "jianying_version_detected" "version=$jianyingVersion"
$process = Get-JianyingProcess
if ($RestartExisting -and $process) {
    Write-Stage "restarting_existing_jianying" "process_id=$($process.Id)"
    try {
        $process.CloseMainWindow() | Out-Null
        $closeDeadline = (Get-Date).AddSeconds(8)
        while (-not $process.HasExited -and (Get-Date) -lt $closeDeadline) {
            Start-Sleep -Milliseconds 250
            $process.Refresh()
        }
    }
    catch {}
    foreach ($remaining in @(Get-Process -Name "JianyingPro", "CapCut" -ErrorAction SilentlyContinue)) {
        try {
            Stop-Process -Id $remaining.Id -Force -ErrorAction Stop
        }
        catch {}
    }
    Start-Sleep -Seconds 2
    $process = $null
    Write-Stage "existing_jianying_stopped"
}
if (-not $process) {
    Write-Stage "starting_jianying" "accessibility=forced"
    Start-Process `
        -FilePath $JianyingExe `
        -ArgumentList @("--force-renderer-accessibility", "--enable-accessibility") `
        -WorkingDirectory ([System.IO.Path]::GetDirectoryName($JianyingExe))
    $startedJianying = $true
}
else {
    Write-Stage "using_existing_jianying" "process_id=$($process.Id)"
}

$deadline = (Get-Date).AddSeconds([Math]::Min(60, $TimeoutSeconds))
while (-not $process -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    $process = Get-JianyingProcess
}
if (-not $process) {
    Write-Stage "failed" "reason=jianying_start_timeout"
    throw "剪映启动超时"
}

try {
    $windowElement = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    $windowClass = [string]$windowElement.Current.ClassName
}
catch {
    $windowClass = ""
}
Write-Stage "jianying_window_ready" "process_id=$($process.Id) class=$windowClass"
[JianyingNative]::ShowWindow($process.MainWindowHandle, 3) | Out-Null
[JianyingNative]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
Start-Sleep -Seconds 2
Dismiss-JianyingPopups $process.Id | Out-Null

Write-Stage "preparing_draft_home"
[System.Windows.Forms.SendKeys]::SendWait("{ESC}")
Start-Sleep -Milliseconds 500
Dismiss-JianyingPopups $process.Id | Out-Null
$openEditorExport = Get-VisibleElements $process.Id | Where-Object {
    ($_.Current.Name -match '^\s*(导出|Export)\s*$' -or
        (Get-FullDescription $_) -match 'MainWindowTitleBarExportBtn') -and
    $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
} | Select-Object -First 1
if ($openEditorExport) {
    Write-Stage "editor_already_open"
    throw "剪映当前停留在草稿编辑页，请先返回本地草稿首页后重试"
}
$localDrafts = Get-VisibleElements $process.Id | Where-Object {
    $_.Current.Name -match '^\s*(本地草稿|草稿|Local drafts?)\s*$' -and
    $_.Current.ControlType.ProgrammaticName -match '(Button|Text|TabItem|Custom)'
} | Select-Object -First 1
if ($localDrafts) {
    Invoke-Element $localDrafts
    Write-Stage "local_drafts_selected"
    Start-Sleep -Seconds 1
}
[System.Windows.Forms.SendKeys]::SendWait("{F5}")
Write-Stage "draft_home_refreshed"
Start-Sleep -Seconds 3
Dismiss-JianyingPopups $process.Id | Out-Null

$treeDeadline = (Get-Date).AddSeconds(8)
$treeElements = @()
$coordinateDraftFallback = $false
while ((Get-Date) -lt $treeDeadline) {
    $treeElements = @(Get-VisibleElements $process.Id)
    if ($treeElements.Count -gt 1) {
        break
    }
    Start-Sleep -Milliseconds 500
}
Write-Stage "ui_tree_probed" "elements=$($treeElements.Count) started_by_helper=$startedJianying version=$jianyingVersion"
if ($treeElements.Count -le 1) {
    Write-VisibleElementSnapshot $process.Id
    $action = if ($startedJianying) { "coordinate_fallback" } else { "restart_with_helper" }
    Write-Stage "ui_tree_unavailable" "action=$action version=$jianyingVersion"
    if (-not $startedJianying) {
        throw "剪映未向 Windows UI Automation 开放内部控件（版本：$jianyingVersion）"
    }
    $coordinateDraftFallback = $true
}

$draftPattern = [regex]::Escape($DraftName)
$draftDescription = "HomePageDraftTitle:$DraftName"
Write-Stage "waiting_for_draft_card"
$draft = $null
if ($coordinateDraftFallback) {
    Invoke-HomeDraftCardByCoordinate $process
    Start-Sleep -Seconds 8
}
else {
    try {
        $draft = Wait-Element $process.Id {
            ((Get-FullDescription $_) -eq $draftDescription) -or
            ($_.Current.Name -match $draftPattern -and
                $_.Current.ControlType.ProgrammaticName -notmatch 'Edit')
        } ([Math]::Min(90, $TimeoutSeconds)) "草稿卡片“$DraftName”"
    }
    catch {
        Write-Stage "draft_card_not_found"
        Write-VisibleElementSnapshot $process.Id
        Invoke-HomeDraftCardByCoordinate $process
        Start-Sleep -Seconds 8
        $coordinateDraftFallback = $true
    }
}
if ($draft) {
    $draftFullDescription = Get-FullDescription $draft
    if ($draftFullDescription -eq $draftDescription) {
        $draftParent = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($draft)
        if ($draftParent) {
            Invoke-Element $draftParent
        }
        else {
            Invoke-Element $draft
        }
    }
    else {
        Invoke-Element $draft -DoubleClick
    }
    Write-Stage "draft_card_opened" "mode=uia"
}
else {
    Write-Stage "draft_card_opened" "mode=coordinate"
}

Write-Stage "waiting_for_editor_export_button"
$exportButton = $null
if ($coordinateDraftFallback) {
    $process = Get-JianyingProcess
    Invoke-EditorExportByCoordinate $process
    Start-Sleep -Seconds 2
}
else {
    try {
        $exportButton = Wait-Element $process.Id {
            ($_.Current.Name -match '^\s*(导出|Export)\s*$' -or
                (Get-FullDescription $_) -match 'MainWindowTitleBarExportBtn') -and
            $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
        } ([Math]::Min(120, $TimeoutSeconds)) "编辑页导出按钮"
    }
    catch {
        Write-Stage "editor_export_button_not_found"
        $process = Get-JianyingProcess
        Invoke-EditorExportByCoordinate $process
        Start-Sleep -Seconds 2
    }
}
if ($exportButton) {
    Invoke-Element $exportButton
}
Write-Stage "export_dialog_opening"
Start-Sleep -Seconds 2

$edits = @(Get-VisibleElements $process.Id | Where-Object {
    $_.Current.ControlType.ProgrammaticName -match 'Edit'
})
$nameEdit = $edits | Where-Object {
    ($_.Current.Name + " " + $_.Current.AutomationId + " " + (Get-FullDescription $_)) -match '(作品名称|文件名称|视频名称|标题|file.?name|title|name|ExportName)'
} | Select-Object -First 1
$pathEdit = $edits | Where-Object {
    ($_.Current.Name + " " + $_.Current.AutomationId + " " + (Get-FullDescription $_)) -match '(保存至|保存位置|输出|路径|目录|文件夹|location|folder|path|ExportPath)'
} | Select-Object -First 1
Write-Stage "export_dialog_ready" "editable_fields=$($edits.Count)"

if ($edits.Count -eq 0) {
    Invoke-ExportDialogByCoordinate $process.Id $outputName $outputDirectory
    Write-Stage "export_confirmed" "mode=coordinate"
    Minimize-JianyingWindow $process "export_wait"
}
else {
if (-not $nameEdit) {
    # In some Jianying builds the only editable field in the export dialog is
    # the work name. Avoid guessing when there are multiple unknown fields.
    if ($edits.Count -eq 1) {
        $nameEdit = $edits[0]
    }
    else {
        throw "当前剪映版本未暴露可识别的[作品名称]输入框；请运行 inspect_jianying_ui.ps1 获取控件树"
    }
}
if (-not (Set-ElementValue $nameEdit $outputName)) {
    throw "无法填写剪映导出作品名称"
}
Write-Stage "output_name_set"

if ($pathEdit) {
    if (-not (Set-ElementValue $pathEdit $outputDirectory)) {
        throw "无法填写剪映导出目录"
    }
    Write-Stage "output_directory_set" "mode=field"
}
else {
    $browse = Get-VisibleElements $process.Id | Where-Object {
        $_.Current.Name -match '(浏览|更改|选择文件夹|Browse|Change|Choose)' -and
        $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
    } | Select-Object -Last 1
    if (-not $browse) {
        throw "当前剪映版本未暴露可识别的[保存位置]控件；请运行 inspect_jianying_ui.ps1 获取控件树"
    }
    Invoke-Element $browse
    Start-Sleep -Seconds 1
    [System.Windows.Forms.Clipboard]::SetText($outputDirectory)
    [System.Windows.Forms.SendKeys]::SendWait("^l")
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Start-Sleep -Seconds 1
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Start-Sleep -Seconds 1
    Write-Stage "output_directory_set" "mode=folder_dialog"
}

$confirm = Get-VisibleElements $process.Id | Where-Object {
    ($_.Current.Name -match '^\s*(导出|Export)\s*$' -or
        (Get-FullDescription $_) -match 'ExportOkBtn') -and
    $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
} | Select-Object -Last 1
if (-not $confirm) {
    throw "没有找到剪映导出确认按钮"
}
Invoke-Element $confirm
Write-Stage "export_confirmed"
Minimize-JianyingWindow $process "export_wait"
}

$fileDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
$noOutputDeadline = (Get-Date).AddSeconds([Math]::Min($TimeoutSeconds, [Math]::Max(30, $NoOutputTimeoutSeconds)))
$lastSize = -1L
$lastPath = ""
$stable = 0
$lastProgressLog = (Get-Date).AddSeconds(-15)
$waitStartedAt = (Get-Date).AddSeconds(-5)
$candidateOutputPaths = @(Get-CandidateOutputPaths)
Write-Stage "waiting_for_output_file"
while ((Get-Date) -lt $fileDeadline) {
    $source = $null
    foreach ($candidate in $candidateOutputPaths) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $item = Get-Item -LiteralPath $candidate
        if ($item.LastWriteTime -lt $waitStartedAt) {
            continue
        }
        $source = $item
        break
    }
    if ($source) {
        $sourcePath = [System.IO.Path]::GetFullPath($source.FullName)
        $size = $source.Length
        if ((Get-Date) -ge $lastProgressLog.AddSeconds(15)) {
            Write-Stage "output_file_growing" "path=$sourcePath size_bytes=$size"
            $lastProgressLog = Get-Date
        }
        if ($sourcePath -ne $lastPath) {
            $stable = 0
        }
        elseif ($size -gt 0 -and $size -eq $lastSize) {
            $stable += 1
            if ($stable -ge 3) {
                if ($sourcePath -ne $OutputPath) {
                    if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
                        Remove-Item -LiteralPath $OutputPath -Force
                    }
                    Move-Item -LiteralPath $sourcePath -Destination $OutputPath -Force
                    Write-Stage "output_file_moved" "from=$sourcePath to=$OutputPath"
                }
                $finalSize = (Get-Item -LiteralPath $OutputPath).Length
                Minimize-JianyingWindow $process "completed"
                Write-Stage "export_completed" "size_bytes=$finalSize"
                [pscustomobject]@{
                    status = "success"
                    draft_name = $DraftName
                    output_path = $OutputPath
                    size_bytes = $finalSize
                } | ConvertTo-Json -Compress
                exit 0
            }
        }
        else {
            $stable = 0
        }
        $lastSize = $size
        $lastPath = $sourcePath
    }
    elseif ((Get-Date) -ge $noOutputDeadline) {
        Write-Stage "output_file_not_started" "wait_seconds=$NoOutputTimeoutSeconds"
        break
    }
    Start-Sleep -Seconds 1
}
Write-Stage "failed" "reason=output_file_timeout"
throw "剪映导出超时，未生成目标 MP4：$OutputPath"
