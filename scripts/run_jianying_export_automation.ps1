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
    [int]$ResourceWaitSeconds = 0,
    [double]$EditorExportXFromRightRatio = -1,
    [double]$EditorExportYFromTopRatio = -1,
    [double]$ExportConfirmXFromRightRatio = -1,
    [double]$ExportConfirmYFromBottomRatio = -1,
    [switch]$EnableOneClickEnhance,
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
    # Write directly to stdout so stage messages do not become function return
    # values when a helper function is assigned to a variable.
    [Console]::Out.WriteLine($message)
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
Add-Type -AssemblyName System.Drawing
$fullDescriptionProperty = [System.Windows.Automation.AutomationProperty]::LookupById(30159)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class JianyingNative {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public UIntPtr extraInfo;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT {
        public uint type;
        public MOUSEINPUT mi;
    }
    [DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint count, INPUT[] inputs, int size);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint flags);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT point);
    [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hWnd, ref POINT point);
}
"@
try {
    [JianyingNative]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null
}
catch {
    [JianyingNative]::SetProcessDPIAware() | Out-Null
}

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

function Get-JianyingPopupRoots([int]$ReferenceProcessId) {
    $items = New-Object System.Collections.Generic.List[object]
    foreach ($root in (Get-ProcessRoots $ReferenceProcessId)) {
        $items.Add($root)
    }

    # Jianying 11 can host marketing/SVIP dialogs in a separate helper
    # process. A ProcessId-only UIA lookup therefore misses the dialog even
    # though it visibly blocks the home page.
    try {
        $desktopRoots = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        foreach ($root in $desktopRoots) {
            $className = [string]$root.Current.ClassName
            if ($className -match '^(SplashDialog|LVInfoDialog)_QMLTYPE_' -or $className -match '^Jianying.*Popup') {
                $items.Add($root)
            }
        }
    }
    catch {
        # The regular same-process roots above remain usable when the desktop
        # tree changes while Jianying is opening or closing a dialog.
    }
    return $items
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

function Get-VisibleElementsUnder($Root) {
    $items = New-Object System.Collections.Generic.List[object]
    if (-not $Root) {
        return $items
    }
    try {
        foreach ($element in $Root.FindAll(
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

function Wait-EditorRoot([int]$ProcessId, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $lastDismiss = (Get-Date).AddSeconds(-10)
    while ((Get-Date) -lt $deadline) {
        $roots = @(Get-ProcessRoots $ProcessId)
        $homeRoot = $roots | Where-Object {
            $_.Current.ClassName -match 'HomePage' -and -not $_.Current.IsOffscreen
        } | Select-Object -First 1
        $root = $roots | Where-Object {
            $_.Current.ClassName -match 'MainWindow' -and -not $_.Current.IsOffscreen
        } | Select-Object -First 1
        if ($root -and -not $homeRoot) {
            return $root
        }
        if ((Get-Date) -ge $lastDismiss.AddSeconds(3)) {
            Dismiss-JianyingPopups $ProcessId | Out-Null
            $lastDismiss = Get-Date
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Get-FirstHomeProjectItem([int]$ProcessId) {
    return Get-VisibleElements $ProcessId | Where-Object {
        $_.Current.ClassName -match 'HomePageOpenProjectItem' -and
        $_.Current.ControlType.ProgrammaticName -match '(Group|Custom)'
    } | Sort-Object `
        @{Expression = {$_.Current.BoundingRectangle.Y}; Ascending = $true}, `
        @{Expression = {$_.Current.BoundingRectangle.X}; Ascending = $true} |
        Select-Object -First 1
}

function Invoke-HomeProjectItemByPoint($Element) {
    try {
        $elementProcess = Get-Process -Id $Element.Current.ProcessId -ErrorAction SilentlyContinue
        if ($elementProcess) {
            Set-JianyingForeground $elementProcess
        }
    }
    catch {}
    $rect = $Element.Current.BoundingRectangle
    if ($rect.Width -le 1 -or $rect.Height -le 1) {
        Invoke-Element $Element -DoubleClick
        return
    }
    $x = [int]($rect.X + ($rect.Width * 0.50))
    $y = [int]($rect.Y + ($rect.Height * 0.38))
    Write-Stage "draft_card_item_point_click" "class=$($Element.Current.ClassName) x=$x y=$y"
    Invoke-Point $x $y
    Start-Sleep -Milliseconds 150
    Invoke-Point $x $y
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

function Get-ElementText($Element) {
    try {
        $name = [string]$Element.Current.Name
        $description = Get-FullDescription $Element
        return "$name $description"
    }
    catch {
        return ""
    }
}

function Get-SubtreeText($Element, [int]$Limit = 120) {
    $parts = New-Object System.Collections.Generic.List[string]
    try {
        $rootText = Get-ElementText $Element
        if ($rootText.Trim()) {
            $parts.Add($rootText.Trim())
        }
        $count = 0
        foreach ($child in $Element.FindAll(
            [System.Windows.Automation.TreeScope]::Subtree,
            [System.Windows.Automation.Condition]::TrueCondition
        )) {
            $text = (Get-ElementText $child).Trim()
            if ($text) {
                $parts.Add($text)
            }
            $count += 1
            if ($count -ge $Limit) {
                break
            }
        }
    }
    catch {}
    return ($parts -join " ")
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
    $moved = [JianyingNative]::SetCursorPos($X, $Y)
    [JianyingNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [JianyingNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    $actual = New-Object JianyingNative+POINT
    [JianyingNative]::GetCursorPos([ref]$actual) | Out-Null
    Write-Stage "physical_click_sent" "requested_x=$X requested_y=$Y actual_x=$($actual.X) actual_y=$($actual.Y) cursor_moved=$moved"
}

function Invoke-SlowPoint([int]$X, [int]$Y) {
    $moved = [JianyingNative]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 180
    [JianyingNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 120
    [JianyingNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    $actual = New-Object JianyingNative+POINT
    [JianyingNative]::GetCursorPos([ref]$actual) | Out-Null
    Write-Stage "slow_physical_click_sent" "requested_x=$X requested_y=$Y actual_x=$($actual.X) actual_y=$($actual.Y) cursor_moved=$moved"
}

function Invoke-SendInputPoint([int]$X, [int]$Y) {
    $moved = [JianyingNative]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 180
    $down = New-Object JianyingNative+INPUT
    $down.type = 0
    $downMouse = New-Object JianyingNative+MOUSEINPUT
    $downMouse.dwFlags = 0x0002
    $down.mi = $downMouse
    $up = New-Object JianyingNative+INPUT
    $up.type = 0
    $upMouse = New-Object JianyingNative+MOUSEINPUT
    $upMouse.dwFlags = 0x0004
    $up.mi = $upMouse
    $inputs = New-Object 'JianyingNative+INPUT[]' 2
    $inputs[0] = $down
    $inputs[1] = $up
    $size = [System.Runtime.InteropServices.Marshal]::SizeOf([type][JianyingNative+INPUT])
    $sent = [JianyingNative]::SendInput(2, $inputs, $size)
    $errorCode = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
    Write-Stage "send_input_click_sent" "x=$X y=$Y events=$sent error=$errorCode cursor_moved=$moved"
}

function Invoke-ElementWindowMessagePoint($Element, [int]$X, [int]$Y) {
    if (-not $Element) {
        return $false
    }
    $handle = [IntPtr]$Element.Current.NativeWindowHandle
    if ($handle -eq [IntPtr]::Zero) {
        return $false
    }
    $clientPoint = New-Object JianyingNative+POINT
    $clientPoint.X = $X
    $clientPoint.Y = $Y
    if (-not [JianyingNative]::ScreenToClient($handle, [ref]$clientPoint)) {
        return $false
    }
    $packed = (($clientPoint.Y -band 0xFFFF) -shl 16) -bor ($clientPoint.X -band 0xFFFF)
    [JianyingNative]::PostMessage($handle, 0x0200, [IntPtr]::Zero, [IntPtr]$packed) | Out-Null
    [JianyingNative]::PostMessage($handle, 0x0201, [IntPtr]1, [IntPtr]$packed) | Out-Null
    Start-Sleep -Milliseconds 120
    [JianyingNative]::PostMessage($handle, 0x0202, [IntPtr]::Zero, [IntPtr]$packed) | Out-Null
    Write-Stage "export_window_message_click_sent" "handle=$handle screen_x=$X screen_y=$Y client_x=$($clientPoint.X) client_y=$($clientPoint.Y)"
    return $true
}

function Set-ElementWindowForeground($Element) {
    if (-not $Element) {
        return
    }
    try {
        $handle = [IntPtr]$Element.Current.NativeWindowHandle
        if ($handle -eq [IntPtr]::Zero) {
            return
        }
        [JianyingNative]::ShowWindow($handle, 9) | Out-Null
        [JianyingNative]::SetWindowPos($handle, [IntPtr](-1), 0, 0, 0, 0, 0x0001 -bor 0x0002 -bor 0x0040) | Out-Null
        Start-Sleep -Milliseconds 120
        $foreground = [JianyingNative]::SetForegroundWindow($handle)
        Start-Sleep -Milliseconds 350
        [JianyingNative]::SetWindowPos($handle, [IntPtr](-2), 0, 0, 0, 0, 0x0001 -bor 0x0002 -bor 0x0040) | Out-Null
        Write-Stage "export_dialog_foreground_requested" "handle=$handle result=$foreground"
    }
    catch {
        Write-Stage "export_dialog_foreground_failed" "error=$($_.Exception.Message)"
    }
}

function Test-ExportConfirmationAccepted([int]$ProcessId) {
    if (Test-Path -LiteralPath $OutputPath) {
        return $true
    }
    $currentRoot = Get-ExportDialogRoot $ProcessId
    if (-not $currentRoot) {
        return $true
    }
    try {
        $text = Get-SubtreeText $currentRoot 240
        return $text -match '(正在导出|导出中|导出成功|取消导出|剩余时间)'
    }
    catch {
        return $false
    }
}

function Wait-ExportConfirmationAccepted([int]$ProcessId, [int]$Milliseconds = 3500) {
    $deadline = (Get-Date).AddMilliseconds($Milliseconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-ExportConfirmationAccepted $ProcessId) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Invoke-ExportConfirmationReliably([int]$ProcessId, $ExportRoot, [int]$X, [int]$Y) {
    Set-ElementWindowForeground $ExportRoot

    $confirm = Get-VisibleElementsUnder $ExportRoot | Where-Object {
        $description = Get-FullDescription $_
        $rect = $_.Current.BoundingRectangle
        $centerY = $rect.Y + ($rect.Height / 2)
        ($description -match '(^|:)ExportOkBtn($|:)' -or
            ($_.Current.Name -match '^\s*(导出|Export)\s*$' -and
                $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)' -and
                $centerY -ge ($ExportRoot.Current.BoundingRectangle.Y + ($ExportRoot.Current.BoundingRectangle.Height * 0.55)))) -and
            $rect.Width -gt 20 -and $rect.Height -gt 15
    } | Sort-Object `
        @{Expression = {if ((Get-FullDescription $_) -match '(^|:)ExportOkBtn($|:)') { 1 } else { 0 }}; Descending = $true}, `
        @{Expression = {$_.Current.BoundingRectangle.Y}; Descending = $true} |
        Select-Object -First 1

    if ($confirm) {
        Write-Stage "export_confirm_attempt" "mode=control"
        $confirmRect = $confirm.Current.BoundingRectangle
        $X = [int]($confirmRect.X + ($confirmRect.Width / 2))
        $Y = [int]($confirmRect.Y + ($confirmRect.Height / 2))
        try {
            Invoke-Element $confirm
            if (Wait-ExportConfirmationAccepted $ProcessId 3500) {
                Write-Stage "export_confirm_accepted" "mode=control"
                return
            }
            Write-Stage "export_confirm_unverified" "mode=control action=retry_physical x=$X y=$Y"
        }
        catch {
            Write-Stage "export_confirm_control_failed" "error=$($_.Exception.Message)"
        }
    }

    Set-ElementWindowForeground $ExportRoot
    Write-Stage "export_confirm_attempt" "mode=slow_physical attempt=1 x=$X y=$Y"
    Invoke-SlowPoint $X $Y
    if (Wait-ExportConfirmationAccepted $ProcessId 4000) {
        Write-Stage "export_confirm_accepted" "mode=slow_physical attempt=1"
        return
    }
    Set-ElementWindowForeground $ExportRoot
    Write-Stage "export_confirm_attempt" "mode=send_input attempt=2 x=$X y=$Y"
    Invoke-SendInputPoint $X $Y
    if (Wait-ExportConfirmationAccepted $ProcessId 4000) {
        Write-Stage "export_confirm_accepted" "mode=send_input attempt=2"
        return
    }
    Set-ElementWindowForeground $ExportRoot
    Write-Stage "export_confirm_attempt" "mode=window_message attempt=3 x=$X y=$Y"
    Invoke-ElementWindowMessagePoint $ExportRoot $X $Y | Out-Null
    if (Wait-ExportConfirmationAccepted $ProcessId 4000) {
        Write-Stage "export_confirm_accepted" "mode=window_message attempt=3"
        return
    }
    Write-Stage "export_confirm_unverified" "mode=all_click_methods action=monitor_output x=$X y=$Y"
}

function Invoke-WindowMessagePoint($Process, [int]$X, [int]$Y) {
    $clientPoint = New-Object JianyingNative+POINT
    $clientPoint.X = $X
    $clientPoint.Y = $Y
    if (-not [JianyingNative]::ScreenToClient($Process.MainWindowHandle, [ref]$clientPoint)) {
        Write-Stage "window_click_skipped" "reason=screen_to_client_failed x=$X y=$Y"
        return
    }
    $packed = (($clientPoint.Y -band 0xFFFF) -shl 16) -bor ($clientPoint.X -band 0xFFFF)
    [JianyingNative]::PostMessage($Process.MainWindowHandle, 0x0200, [IntPtr]::Zero, [IntPtr]$packed) | Out-Null
    [JianyingNative]::PostMessage($Process.MainWindowHandle, 0x0201, [IntPtr]1, [IntPtr]$packed) | Out-Null
    Start-Sleep -Milliseconds 80
    [JianyingNative]::PostMessage($Process.MainWindowHandle, 0x0202, [IntPtr]::Zero, [IntPtr]$packed) | Out-Null
    Write-Stage "window_click_sent" "screen_x=$X screen_y=$Y client_x=$($clientPoint.X) client_y=$($clientPoint.Y)"
}

function Close-ExportSuccessDialogs([int]$ProcessId) {
    $closed = 0
    for ($attempt = 0; $attempt -lt 3; $attempt += 1) {
        $successDialog = Get-ProcessRoots $ProcessId | Where-Object {
            $text = Get-SubtreeText $_
            ($_.Current.ClassName -match 'ExportWindow|LVInfoDialog|Dialog|Popup' -or $_.Current.Name -match 'JianyingPro|导出') -and
            $text -match '导出成功|让更多人看到你的作品|查看草稿|发布'
        } | Select-Object -First 1
        if (-not $successDialog) {
            break
        }

        $closeButton = Get-VisibleElements $ProcessId | Where-Object {
            $text = (Get-ElementText $_).Trim()
            $text -match '^\s*(关闭|完成|知道了|Close|Done|OK)\s*$' -and
            $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
        } | Select-Object -Last 1
        if ($closeButton) {
            $name = ([string]$closeButton.Current.Name).Replace("`r", " ").Replace("`n", " ").Trim()
            Write-Stage "export_success_dialog_closed" "mode=button name=$name"
            Invoke-Element $closeButton
        }
        else {
            $rect = $successDialog.Current.BoundingRectangle
            $x = [int]($rect.Right - [Math]::Min(85, [Math]::Max(45, $rect.Width * 0.09)))
            $y = [int]($rect.Bottom - [Math]::Min(42, [Math]::Max(30, $rect.Height * 0.05)))
            Write-Stage "export_success_dialog_closed" "mode=coordinate x=$x y=$y"
            Invoke-Point $x $y
        }
        $closed += 1
        Start-Sleep -Milliseconds 800
    }
    return $closed
}

function Set-JianyingForeground($Process) {
    if (-not $Process -or $Process.MainWindowHandle -eq 0) {
        return
    }
    $handle = $Process.MainWindowHandle
    [JianyingNative]::ShowWindow($handle, 9) | Out-Null
    [JianyingNative]::SetWindowPos($handle, [IntPtr](-1), 0, 0, 0, 0, 0x0001 -bor 0x0002 -bor 0x0040) | Out-Null
    Start-Sleep -Milliseconds 120
    [JianyingNative]::SetForegroundWindow($handle) | Out-Null
    Start-Sleep -Milliseconds 250
    [JianyingNative]::SetWindowPos($handle, [IntPtr](-2), 0, 0, 0, 0, 0x0001 -bor 0x0002 -bor 0x0040) | Out-Null
}

function Get-WindowRect($Process) {
    Set-JianyingForeground $Process
    $rect = New-Object JianyingNative+RECT
    if (-not [JianyingNative]::GetWindowRect($Process.MainWindowHandle, [ref]$rect)) {
        throw "无法读取剪映窗口位置"
    }
    if ($rect.Left -lt -30000 -or $rect.Top -lt -30000 -or ($rect.Right -le $rect.Left) -or ($rect.Bottom -le $rect.Top)) {
        [JianyingNative]::ShowWindow($Process.MainWindowHandle, 3) | Out-Null
        [JianyingNative]::SetForegroundWindow($Process.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 500
        if (-not [JianyingNative]::GetWindowRect($Process.MainWindowHandle, [ref]$rect)) {
            throw "无法读取剪映窗口位置"
        }
    }
    return $rect
}

function Invoke-HomeDraftCardByCoordinate($Process) {
    $projectItem = Get-FirstHomeProjectItem $Process.Id
    if ($projectItem) {
        Invoke-HomeProjectItemByPoint $projectItem
        return
    }
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
    Set-JianyingForeground $Process
    [System.Windows.Forms.SendKeys]::SendWait("^e")
    $shortcutDeadline = (Get-Date).AddSeconds(3)
    while ((Get-Date) -lt $shortcutDeadline) {
        if (Get-ExportDialogRoot $Process.Id) {
            Write-Stage "editor_export_opened" "mode=shortcut"
            return
        }
        Start-Sleep -Milliseconds 300
    }

    $rect = Get-WindowRect $Process
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    # JianYing 11 editor screenshot: export center is about 89.5% width,
    # 2.1% height (roughly 1145,17 on a 1280x800 window).
    $hasCalibration = (
        $EditorExportXFromRightRatio -ge 0.01 -and $EditorExportXFromRightRatio -le 0.5 -and
        $EditorExportYFromTopRatio -ge 0.0 -and $EditorExportYFromTopRatio -le 0.25
    )
    $y = if ($hasCalibration) {
        [int]($rect.Top + ($height * $EditorExportYFromTopRatio))
    }
    else {
        [int]($rect.Top + [Math]::Min(30, [Math]::Max(18, $height * 0.023)))
    }
    $offsets = @(
        $(if ($hasCalibration) {
            $width * $EditorExportXFromRightRatio
        }
        else {
            [Math]::Min(210, [Math]::Max(115, $width * 0.105))
        })
    )
    if ($hasCalibration) {
        Write-Stage "editor_export_calibration_loaded" "x_from_right_ratio=$EditorExportXFromRightRatio y_from_top_ratio=$EditorExportYFromTopRatio"
    }
    $attempt = 0
    foreach ($offset in $offsets) {
        $attempt += 1
        $x = [int]($rect.Right - $offset)
        Write-Stage "editor_export_coordinate_click" "attempt=$attempt x=$x y=$y"
        Invoke-Point $x $y
        $clickDeadline = (Get-Date).AddSeconds(2)
        while ((Get-Date) -lt $clickDeadline) {
            if (Get-ExportDialogRoot $Process.Id) {
                Write-Stage "editor_export_opened" "mode=coordinate attempt=$attempt"
                return
            }
            Start-Sleep -Milliseconds 300
        }
        Write-Stage "editor_export_window_message_click" "attempt=$attempt x=$x y=$y"
        Invoke-WindowMessagePoint $Process $x $y
        $messageDeadline = (Get-Date).AddSeconds(3)
        while ((Get-Date) -lt $messageDeadline) {
            if (Get-ExportDialogRoot $Process.Id) {
                Write-Stage "editor_export_opened" "mode=window_message attempt=$attempt"
                return
            }
            Start-Sleep -Milliseconds 300
        }
    }
}

function Set-HomeDraftSearchByCoordinate($Process, [string]$Query) {
    if (-not $Query) {
        return
    }
    $rect = Get-WindowRect $Process
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $searchQuery = if ($Query -match '^[0-9A-Fa-f]{8}-') { $Query.Substring(0, 3) } else { $Query }
    # JianYing 11.2 local-drafts search icon is at about 79.5% width / 67.2% height.
    $x = [int]($rect.Left + ($width * 0.795))
    $y = [int]($rect.Top + ($height * 0.672))
    Write-Stage "draft_search_coordinate_click" "x=$x y=$y query=$searchQuery draft_name=$Query"
    Invoke-Point $x $y
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("^a")
    [System.Windows.Forms.SendKeys]::SendWait($searchQuery)
    Start-Sleep -Seconds 2
    Write-Stage "draft_search_applied" "query=$searchQuery draft_name=$Query"
}

function Get-ExportWindowRect([int]$ProcessId) {
    $activeProcess = Get-JianyingProcess
    $processIds = @($ProcessId)
    if ($activeProcess) {
        $processIds = @($activeProcess.Id, $ProcessId) | Select-Object -Unique
    }
    $exportWindow = $null
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        foreach ($candidateProcessId in $processIds) {
            $exportWindow = Get-ExportDialogRoot $candidateProcessId
            if ($exportWindow) {
                break
            }
        }
        if ($exportWindow) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if ($exportWindow) {
        return $exportWindow.Current.BoundingRectangle
    }
    throw "等待剪映导出弹窗超时"
}

function Get-ExportDialogRoot([int]$ProcessId) {
    function Test-RealExportDialog($Element) {
        try {
            $rect = $Element.Current.BoundingRectangle
            if ($rect.Width -lt 420 -or $rect.Height -lt 320) {
                return $false
            }
            $className = [string]$Element.Current.ClassName
            if ($className -match 'ExportWindow') {
                return $true
            }
            $dialogText = Get-SubtreeText $Element 180
            return $dialogText -match '(导出至|视频导出|音频导出|保存位置|分辨率|ExportPath|ExportOkBtn)'
        }
        catch {
            return $false
        }
    }

    $rootWindow = Get-ProcessRoots $ProcessId | Where-Object {
        ($_.Current.ClassName -match 'ExportWindow' -or
            ($_.Current.Name -match '^\s*导出' -and $_.Current.ClassName -notmatch 'HomePage')) -and
        (Test-RealExportDialog $_)
    } | Select-Object -First 1
    if ($rootWindow) {
        return $rootWindow
    }
    return Get-VisibleElements $ProcessId | Where-Object {
        ($_.Current.AutomationId -match 'ExportWindow_Container' -or
            $_.Current.ClassName -match '(^|_)Export(_|$)|Export_QMLTYPE' -or
            ($_.Current.Name -match '^\s*导出\s*$' -and
                $_.Current.ControlType.ProgrammaticName -match 'Window')) -and
        (Test-RealExportDialog $_)
    } | Sort-Object `
        @{Expression = {$_.Current.BoundingRectangle.Width * $_.Current.BoundingRectangle.Height}; Descending = $true} |
        Select-Object -First 1
}

function Wait-ExportDialogRoot([int]$ProcessId, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $root = Get-ExportDialogRoot $ProcessId
        if ($root) {
            return $root
        }
        Start-Sleep -Milliseconds 500
    }
    throw "等待剪映导出弹窗超时"
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

function Invoke-ExportDialogByCoordinate([int]$ProcessId) {
    $exportRoot = Get-ExportDialogRoot $ProcessId
    Set-ElementWindowForeground $exportRoot
    # Use the export dialog itself. Looking the window up again by process ID
    # can return Jianying's full editor window and produce a dangerous click
    # far away from the export confirmation button.
    $rect = $ExportRoot.Current.BoundingRectangle
    if ($rect.Width -lt 420 -or $rect.Height -lt 420) {
        throw "剪映导出窗口尺寸异常，已停止导出确认点击"
    }
    $confirmPoint = Get-ExportConfirmPoint $rect
    $confirmX = $confirmPoint.X
    $confirmY = $confirmPoint.Y
    # JianYing 11 does not expose the QML edit fields through UI Automation.
    # Clicking the apparent path field opens a folder picker and prevents the
    # final export click. Keep the dialog's existing title/path and click only
    # the bottom-right export button; output discovery covers default folders.
    Write-Stage "export_dialog_coordinate_confirm_only" "confirm_x=$confirmX confirm_y=$confirmY"
    Invoke-ExportConfirmationReliably $ProcessId $exportRoot $confirmX $confirmY
}

function Get-ExportConfirmPoint($Rect) {
    $width = [Math]::Max(1, $Rect.Right - $Rect.Left)
    $height = [Math]::Max(1, $Rect.Bottom - $Rect.Top)
    $hasCalibration = (
        $ExportConfirmXFromRightRatio -ge 0.01 -and $ExportConfirmXFromRightRatio -le 0.6 -and
        $ExportConfirmYFromBottomRatio -ge 0.0 -and $ExportConfirmYFromBottomRatio -le 0.35
    )
    if ($hasCalibration) {
        $x = [int]($Rect.Right - ($width * $ExportConfirmXFromRightRatio))
        $y = [int]($Rect.Bottom - ($height * $ExportConfirmYFromBottomRatio))
        Write-Stage "export_confirm_calibration_loaded" "x_from_right_ratio=$ExportConfirmXFromRightRatio y_from_bottom_ratio=$ExportConfirmYFromBottomRatio x=$x y=$y"
        return @{ X = $x; Y = $y; Calibrated = $true }
    }
    # JianYing 11 places blue "导出" immediately to the left of "取消".
    # On the 960x1080 export window its center is about (762, 1040).
    return @{
        X = [int]($Rect.Right - [Math]::Min(230, [Math]::Max(150, $width * 0.20)))
        Y = [int]($Rect.Bottom - [Math]::Min(48, [Math]::Max(34, $height * 0.038)))
        Calibrated = $false
    }
}

function Get-ScreenPointBrightness([int]$X, [int]$Y) {
    $bitmap = New-Object System.Drawing.Bitmap 1, 1
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen(
            $X,
            $Y,
            0,
            0,
            (New-Object System.Drawing.Size 1, 1),
            [System.Drawing.CopyPixelOperation]::SourceCopy
        )
        $color = $bitmap.GetPixel(0, 0)
        return [int](($color.R + $color.G + $color.B) / 3)
    }
    catch {
        return -1
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-OneClickEnhanceVisualState($Rect) {
    $width = [Math]::Max(1, $Rect.Right - $Rect.Left)
    $height = [Math]::Max(1, $Rect.Bottom - $Rect.Top)
    $leftX = [int]($Rect.Left + ($width * 0.931))
    $rightX = [int]($Rect.Left + ($width * 0.963))
    $sampleY = [int]($Rect.Top + ($height * 0.318))
    $leftBrightness = Get-ScreenPointBrightness $leftX $sampleY
    $rightBrightness = Get-ScreenPointBrightness $rightX $sampleY
    Write-Stage "one_click_enhance_visual_state" "left=$leftBrightness right=$rightBrightness y=$sampleY"
    if ($leftBrightness -lt 0 -or $rightBrightness -lt 0) {
        return "unknown"
    }
    if ($rightBrightness -ge ($leftBrightness + 18)) {
        return "on"
    }
    if ($leftBrightness -ge ($rightBrightness + 18)) {
        return "off"
    }
    return "unknown"
}

function Enable-OneClickEnhanceInDialog([int]$ProcessId, $ExportRoot) {
    $toggle = Get-VisibleElementsUnder $ExportRoot | Where-Object {
        ($_.Current.Name + " " + $_.Current.AutomationId + " " + (Get-FullDescription $_)) -match '(一键超清|智能超清|Enhance)'
    } | Select-Object -First 1
    if ($toggle) {
        try {
            $togglePattern = $null
            if ($toggle.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$togglePattern)) {
                if ($togglePattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) {
                    Write-Stage "one_click_enhance_enabled" "mode=toggle_pattern state=already_on"
                    return
                }
                $togglePattern.Toggle()
                Start-Sleep -Milliseconds 700
                if ($togglePattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) {
                    Write-Stage "one_click_enhance_enabled" "mode=toggle_pattern state=on"
                    return
                }
            }
        }
        catch {
            Write-Stage "one_click_enhance_control_failed" "error=$($_.Exception.Message)"
        }
    }

    # The process has both the editor and export-dialog top-level windows.
    # Coordinates must be derived from the already verified dialog root.
    $rect = $ExportRoot.Current.BoundingRectangle
    if ($rect.Width -lt 420 -or $rect.Height -lt 420) {
        throw "剪映导出窗口尺寸异常，已停止一键超清点击"
    }
    $width = [Math]::Max(1, $rect.Right - $rect.Left)
    $height = [Math]::Max(1, $rect.Bottom - $rect.Top)
    $toggleX = [int]($rect.Left + ($width * 0.947))
    $toggleY = [int]($rect.Top + ($height * 0.318))
    $before = Get-OneClickEnhanceVisualState $rect
    if ($before -eq "on") {
        Write-Stage "one_click_enhance_enabled" "mode=visual state=already_on x=$toggleX y=$toggleY"
        return
    }
    if ($before -ne "off") {
        Write-Stage "one_click_enhance_skipped" "reason=unknown_state action=continue_without_enhance"
        return
    }
    Write-Stage "one_click_enhance_click" "mode=coordinate state_before=$before x=$toggleX y=$toggleY"
    Set-ElementWindowForeground $ExportRoot
    Invoke-SlowPoint $toggleX $toggleY
    Start-Sleep -Milliseconds 900
    $after = Get-OneClickEnhanceVisualState $rect
    if ($after -eq "off") {
        Write-Stage "one_click_enhance_retry" "mode=send_input x=$toggleX y=$toggleY"
        Set-ElementWindowForeground $ExportRoot
        Invoke-SendInputPoint $toggleX $toggleY
        Start-Sleep -Milliseconds 900
        $after = Get-OneClickEnhanceVisualState $rect
    }
    if ($after -eq "off") {
        Write-Stage "one_click_enhance_retry" "mode=window_message x=$toggleX y=$toggleY"
        Set-ElementWindowForeground $ExportRoot
        Invoke-ElementWindowMessagePoint $ExportRoot $toggleX $toggleY | Out-Null
        Start-Sleep -Milliseconds 900
        $after = Get-OneClickEnhanceVisualState $rect
    }
    if ($after -eq "off") {
        Write-Stage "one_click_enhance_skipped" "reason=all_click_modes_rejected action=continue_without_enhance"
        return
    }
    if ($after -ne "on") {
        Write-Stage "one_click_enhance_skipped" "reason=unverified_state action=continue_without_enhance"
        return
    }
    Write-Stage "one_click_enhance_enabled" "mode=coordinate state_after=$after x=$toggleX y=$toggleY"
}

function Get-CandidateOutputPaths {
    $directories = @(
        $outputDirectory,
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Videos"),
        (Join-Path $env:USERPROFILE "OneDrive\Videos"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
        (Join-Path $env:USERPROFILE "Documents"),
        (Join-Path $env:USERPROFILE "OneDrive\Documents")
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

function Find-CandidateOutputFile([datetime]$WaitStartedAt) {
    $threshold = $WaitStartedAt.AddMinutes(-15)
    $directories = @(
        $outputDirectory,
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Videos"),
        (Join-Path $env:USERPROFILE "OneDrive\Videos"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
        (Join-Path $env:USERPROFILE "Documents"),
        (Join-Path $env:USERPROFILE "OneDrive\Documents")
    ) | Where-Object {
        $_ -and (Test-Path -LiteralPath $_ -PathType Container)
    } | Select-Object -Unique
    $names = @($outputName, $DraftName) | Where-Object { $_ } | Select-Object -Unique

    foreach ($candidate in (Get-CandidateOutputPaths)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $item = Get-Item -LiteralPath $candidate
        if ($item.LastWriteTime -ge $threshold) {
            return $item
        }
    }
    $matches = New-Object System.Collections.Generic.List[object]
    foreach ($directory in $directories) {
        foreach ($name in $names) {
            foreach ($item in (Get-ChildItem -LiteralPath $directory -Filter "$name*.mp4" -File -ErrorAction SilentlyContinue)) {
                if ($item.LastWriteTime -ge $threshold) {
                    $matches.Add($item)
                }
            }
        }
    }
    return $matches | Sort-Object LastWriteTime -Descending | Select-Object -First 1
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
            [JianyingNative]::SetWindowPos(
                $currentProcess.MainWindowHandle,
                [IntPtr](-2),
                0,
                0,
                0,
                0,
                0x0001 -bor 0x0002 -bor 0x0040
            ) | Out-Null
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
        $blockingDialog = Get-JianyingPopupRoots $ProcessId | Where-Object {
            $_.Current.ClassName -match 'LVInfoDialog|SplashDialog|Popup' -and
            $_.Current.ClassName -notmatch 'ExportWindow'
        } | Where-Object {
            $rect = $_.Current.BoundingRectangle
            $rect.Width -gt 200 -and $rect.Height -gt 120
        } | Select-Object -First 1
        if ($blockingDialog) {
            $rect = $blockingDialog.Current.BoundingRectangle
            $safeDismiss = @(Get-VisibleElementsUnder $blockingDialog) | Where-Object {
                $text = ($_.Current.Name + " " + (Get-FullDescription $_)).Trim()
                $text -match $dismissPattern -and
                $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
            } | Select-Object -First 1
            if ($safeDismiss) {
                $safeName = ([string]$safeDismiss.Current.Name).Replace("`r", " ").Replace("`n", " ").Trim()
                Write-Stage "popup_dismissed" "mode=safe_text name=$safeName class=$($blockingDialog.Current.ClassName)"
                Invoke-Element $safeDismiss
                $dismissed += 1
                Start-Sleep -Milliseconds 900
                continue
            }
            $handle = [IntPtr]$blockingDialog.Current.NativeWindowHandle
            if ($handle -ne [IntPtr]::Zero) {
                Write-Stage "popup_dismissed" "mode=window_close class=$($blockingDialog.Current.ClassName)"
                [JianyingNative]::PostMessage($handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
                $dismissed += 1
                Start-Sleep -Milliseconds 600
                $stillBlocking = Get-JianyingPopupRoots $ProcessId | Where-Object {
                    $_.Current.ClassName -eq $blockingDialog.Current.ClassName
                } | Select-Object -First 1
                if (-not $stillBlocking) {
                    continue
                }
                $x = [int]($rect.Right - [Math]::Min(230, [Math]::Max(80, $rect.Width * 0.33)))
                $y = [int]($rect.Bottom - [Math]::Min(55, [Math]::Max(35, $rect.Height * 0.12)))
                Write-Stage "popup_dismissed" "mode=blocking_dialog_click class=$($blockingDialog.Current.ClassName) x=$x y=$y"
                Invoke-Point $x $y
                [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
                Start-Sleep -Milliseconds 900
                continue
            }
        }
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
        $splash = Get-JianyingPopupRoots $ProcessId | Where-Object {
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

function Clear-HomeSearchFields([int]$ProcessId) {
    $cleared = 0
    foreach ($root in (Get-ProcessRoots $ProcessId)) {
        if ($root.Current.ClassName -notmatch 'HomePage') {
            continue
        }
        foreach ($edit in (Get-VisibleElementsUnder $root | Where-Object {
            $_.Current.ControlType.ProgrammaticName -match 'Edit'
        })) {
            $previous = ""
            try {
                $pattern = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                if ($pattern) {
                    $previous = [string]$pattern.Current.Value
                    if ($previous) {
                        $pattern.SetValue("")
                        $cleared += 1
                    }
                    continue
                }
            }
            catch {}
            try {
                $rect = $edit.Current.BoundingRectangle
                if ($rect.Width -gt 1 -and $rect.Height -gt 1) {
                    Invoke-Point ([int]($rect.X + $rect.Width / 2)) ([int]($rect.Y + $rect.Height / 2))
                    Start-Sleep -Milliseconds 100
                    [System.Windows.Forms.SendKeys]::SendWait("^a")
                    [System.Windows.Forms.SendKeys]::SendWait("{DELETE}")
                    $cleared += 1
                }
            }
            catch {}
        }
    }
    if ($cleared -gt 0) {
        Write-Stage "home_search_cleared" "fields=$cleared"
        Start-Sleep -Milliseconds 600
    }
    return $cleared
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

$deadline = (Get-Date).AddSeconds([Math]::Min(120, $TimeoutSeconds))
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
Set-JianyingForeground $process
Start-Sleep -Seconds 2
Dismiss-JianyingPopups $process.Id | Out-Null
Close-ExportSuccessDialogs $process.Id | Out-Null
Clear-HomeSearchFields $process.Id | Out-Null

Write-Stage "preparing_draft_home"
[System.Windows.Forms.SendKeys]::SendWait("{ESC}")
Start-Sleep -Milliseconds 500
Dismiss-JianyingPopups $process.Id | Out-Null
Close-ExportSuccessDialogs $process.Id | Out-Null
Clear-HomeSearchFields $process.Id | Out-Null
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
    Clear-HomeSearchFields $process.Id | Out-Null
}
[System.Windows.Forms.SendKeys]::SendWait("{F5}")
Write-Stage "draft_home_refreshed"
Start-Sleep -Seconds 3
Dismiss-JianyingPopups $process.Id | Out-Null
Clear-HomeSearchFields $process.Id | Out-Null

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
    Dismiss-JianyingPopups $process.Id | Out-Null
    Clear-HomeSearchFields $process.Id | Out-Null
    Set-HomeDraftSearchByCoordinate $process $DraftName
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
        Dismiss-JianyingPopups $process.Id | Out-Null
        Clear-HomeSearchFields $process.Id | Out-Null
        Start-Sleep -Milliseconds 400
        Set-HomeDraftSearchByCoordinate $process $DraftName
        $projectItem = Get-FirstHomeProjectItem $process.Id
        if ($projectItem) {
            $draft = $projectItem
            $coordinateDraftFallback = $false
            Write-Stage "draft_card_fallback_item" "class=$($projectItem.Current.ClassName)"
        }
        else {
            Invoke-HomeDraftCardByCoordinate $process
            Start-Sleep -Seconds 8
            $coordinateDraftFallback = $true
        }
    }
}
if ($draft) {
    $draftFullDescription = Get-FullDescription $draft
    if ($draft.Current.ClassName -match 'HomePageOpenProjectItem') {
        Invoke-HomeProjectItemByPoint $draft
        Write-Stage "draft_card_opened" "mode=uia_item"
    }
    elseif ($draftFullDescription -eq $draftDescription) {
        $draftParent = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($draft)
        if ($draftParent) {
            Invoke-Element $draftParent
        }
        else {
            Invoke-Element $draft
        }
        Write-Stage "draft_card_opened" "mode=uia"
    }
    else {
        Invoke-Element $draft -DoubleClick
        Write-Stage "draft_card_opened" "mode=uia"
    }
}
else {
    Write-Stage "draft_card_opened" "mode=coordinate"
}

$editorRootAfterOpen = Wait-EditorRoot $process.Id ([Math]::Min(180, $TimeoutSeconds))
if (-not $editorRootAfterOpen) {
    Write-Stage "draft_open_retry" "reason=editor_not_ready_after_open"
    $retryItem = Get-FirstHomeProjectItem $process.Id
    if ($retryItem) {
        Invoke-HomeProjectItemByPoint $retryItem
        $editorRootAfterOpen = Wait-EditorRoot $process.Id ([Math]::Min(180, $TimeoutSeconds))
    }
}
if (-not $editorRootAfterOpen) {
    throw "点击草稿卡片后没有进入剪映草稿编辑页"
}
Write-Stage "editor_ready" "class=$($editorRootAfterOpen.Current.ClassName)"
if ($ResourceWaitSeconds -gt 0) {
    Minimize-JianyingWindow $process "cloud_resource_sync"
    Write-Stage "cloud_resource_sync_wait_started" "seconds=$ResourceWaitSeconds"
    Start-Sleep -Seconds $ResourceWaitSeconds
    Write-Stage "cloud_resource_sync_wait_finished" "seconds=$ResourceWaitSeconds"
}

Write-Stage "waiting_for_editor_export_button"
$exportButton = $null
$exportRoot = $null
$process = Get-JianyingProcess
Set-JianyingForeground $process
try {
    $exportButton = Wait-Element $process.Id {
        ($_.Current.Name -match '^\s*(导出|Export)\s*$' -or
            (Get-FullDescription $_) -match 'MainWindowTitleBarExportBtn') -and
        $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
    } ([Math]::Min(15, $TimeoutSeconds)) "编辑页导出按钮"
}
catch {
    Write-Stage "editor_export_button_not_found"
    if ($coordinateDraftFallback -and -not $editorRootAfterOpen) {
        throw "坐标点击后没有进入剪映草稿编辑页"
    }
    Dismiss-JianyingPopups $process.Id | Out-Null
    $editorRoot = Wait-EditorRoot $process.Id 2
    if (-not $editorRoot) {
        Write-Stage "draft_open_retry" "reason=still_on_home"
        $retryItem = Get-FirstHomeProjectItem $process.Id
        if ($retryItem) {
            Invoke-HomeProjectItemByPoint $retryItem
        }
        $editorRoot = Wait-EditorRoot $process.Id ([Math]::Min(90, $TimeoutSeconds))
        if (-not $editorRoot) {
            throw "点击草稿卡片后没有进入剪映草稿编辑页"
        }
        Write-Stage "editor_ready_after_retry" "class=$($editorRoot.Current.ClassName)"
        try {
            $exportButton = Wait-Element $process.Id {
                ($_.Current.Name -match '^\s*(导出|Export)\s*$' -or
                    (Get-FullDescription $_) -match 'MainWindowTitleBarExportBtn') -and
                $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
            } ([Math]::Min(15, $TimeoutSeconds)) "编辑页导出按钮"
        }
        catch {
            Write-Stage "editor_export_button_not_exposed" "action=shortcut"
        }
    }
}
if ($exportButton) {
    $buttonRect = $exportButton.Current.BoundingRectangle
    if ($buttonRect.Width -gt 1 -and $buttonRect.Height -gt 1) {
        $buttonX = [int]($buttonRect.X + ($buttonRect.Width / 2))
        $buttonY = [int]($buttonRect.Y + ($buttonRect.Height / 2))
        Write-Stage "editor_export_control_point_click" "x=$buttonX y=$buttonY"
        Invoke-Point $buttonX $buttonY
    }
    else {
        Invoke-Element $exportButton
    }
    $controlClickDeadline = (Get-Date).AddSeconds(3)
    while ((Get-Date) -lt $controlClickDeadline) {
        $exportRoot = Get-ExportDialogRoot $process.Id
        if ($exportRoot) {
            Write-Stage "editor_export_opened" "mode=control_point"
            break
        }
        Start-Sleep -Milliseconds 300
    }
}
if (-not $exportRoot) {
    Write-Stage "editor_export_control_click_unverified" "action=shortcut_and_coordinate"
    Invoke-EditorExportByCoordinate $process
    $exportRoot = Get-ExportDialogRoot $process.Id
}
Write-Stage "export_dialog_opening"
Start-Sleep -Seconds 2
try {
    if (-not $exportRoot) {
        $exportRoot = Wait-ExportDialogRoot $process.Id 30
    }
    Write-Stage "export_dialog_root_ready" "class=$($exportRoot.Current.ClassName)"
}
catch {
    Write-Stage "export_dialog_root_not_found" "action=fail"
    throw "剪映导出弹窗未打开，已停止自动点击以避免误操作"
}

$dialogElements = if ($exportRoot) { Get-VisibleElementsUnder $exportRoot } else { @() }
$edits = @($dialogElements | Where-Object {
    $_.Current.ControlType.ProgrammaticName -match 'Edit'
})
$nameEdit = $edits | Where-Object {
    ($_.Current.Name + " " + $_.Current.AutomationId + " " + (Get-FullDescription $_)) -match '(作品名称|文件名称|视频名称|标题|file.?name|title|name|ExportName)'
} | Select-Object -First 1
$pathEdit = $edits | Where-Object {
    ($_.Current.Name + " " + $_.Current.AutomationId + " " + (Get-FullDescription $_)) -match '(保存至|保存位置|输出|路径|目录|文件夹|location|folder|path|ExportPath)'
} | Select-Object -First 1
Write-Stage "export_dialog_ready" "editable_fields=$($edits.Count)"

if ($EnableOneClickEnhance) {
    $NoOutputTimeoutSeconds = [Math]::Max($NoOutputTimeoutSeconds, 600)
    Enable-OneClickEnhanceInDialog $process.Id $exportRoot
    Write-Stage "one_click_enhance_wait_extended" "no_output_timeout_seconds=$NoOutputTimeoutSeconds"
}

if ($edits.Count -eq 0) {
    Invoke-ExportDialogByCoordinate $process.Id
    Write-Stage "export_confirmed" "mode=coordinate_confirm_only"
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

$exportRect = $exportRoot.Current.BoundingRectangle
$confirm = $dialogElements | Where-Object {
    $description = Get-FullDescription $_
    $rect = $_.Current.BoundingRectangle
    $centerY = $rect.Y + ($rect.Height / 2)
    $isExplicitConfirm = $description -match '(^|:)ExportOkBtn($|:)'
    $isBottomButton = (
        $_.Current.Name -match '^\s*(导出|Export)\s*$' -and
        $_.Current.ControlType.ProgrammaticName -match '(Button|Custom)' -and
        $rect.Width -gt 20 -and
        $rect.Height -gt 15 -and
        $centerY -ge ($exportRect.Y + ($exportRect.Height * 0.55))
    )
    $isExplicitConfirm -or $isBottomButton
} | Sort-Object `
    @{Expression = {if ((Get-FullDescription $_) -match '(^|:)ExportOkBtn($|:)') { 1 } else { 0 }}; Descending = $true}, `
    @{Expression = {$_.Current.BoundingRectangle.Y}; Descending = $true}, `
    @{Expression = {$_.Current.BoundingRectangle.X}; Descending = $true} |
    Select-Object -First 1
$confirmPoint = Get-ExportConfirmPoint $exportRect
$confirmX = $confirmPoint.X
$confirmY = $confirmPoint.Y
if ($confirm) {
    $confirmDescription = Get-FullDescription $confirm
    $confirmRect = $confirm.Current.BoundingRectangle
    Write-Stage "export_confirm_control_ready" "type=$($confirm.Current.ControlType.ProgrammaticName) x=$($confirmRect.X) y=$($confirmRect.Y) description=$confirmDescription"
}
Write-Stage "export_confirm_reliable_click" "x=$confirmX y=$confirmY calibrated=$($confirmPoint.Calibrated)"
Write-Stage "export_confirm_coordinate_click" "x=$confirmX y=$confirmY mode=verified_retry"
Invoke-ExportConfirmationReliably $process.Id $exportRoot $confirmX $confirmY
Write-Stage "export_confirmed" "mode=verified"
}

$fileDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
$noOutputDeadline = (Get-Date).AddSeconds([Math]::Min($TimeoutSeconds, [Math]::Max(30, $NoOutputTimeoutSeconds)))
$lastSize = -1L
$lastPath = ""
$stable = 0
$lastProgressLog = (Get-Date).AddSeconds(-15)
$waitStartedAt = (Get-Date).AddSeconds(-5)
$outputStarted = $false
$candidateOutputPaths = @(Get-CandidateOutputPaths)
Write-Stage "waiting_for_output_file"
while ((Get-Date) -lt $fileDeadline) {
    $source = Find-CandidateOutputFile $waitStartedAt
    if ($source) {
        if (-not $outputStarted) {
            $outputStarted = $true
            Minimize-JianyingWindow $process "output_started"
        }
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
                Close-ExportSuccessDialogs $process.Id | Out-Null
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
