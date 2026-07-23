param(
    [Parameter(Mandatory = $true)]
    [string]$DraftName,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [Parameter(Mandatory = $true)]
    [string]$JianyingExe,
    [int]$TimeoutSeconds = 1800
)

$ErrorActionPreference = "Stop"
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = [System.IO.Path]::GetDirectoryName($OutputPath)
$outputName = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class JianyingNative {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
"@

function Get-JianyingProcess {
    Get-Process | Where-Object {
        $_.ProcessName -match '^(JianyingPro|CapCut)$' -and $_.MainWindowHandle -ne 0
    } | Sort-Object StartTime | Select-Object -Last 1
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

$process = Get-JianyingProcess
if (-not $process) {
    Start-Process -FilePath $JianyingExe -WorkingDirectory ([System.IO.Path]::GetDirectoryName($JianyingExe))
}

$deadline = (Get-Date).AddSeconds([Math]::Min(60, $TimeoutSeconds))
while (-not $process -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    $process = Get-JianyingProcess
}
if (-not $process) {
    throw "剪映启动超时"
}

[JianyingNative]::ShowWindow($process.MainWindowHandle, 9) | Out-Null
[JianyingNative]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
Start-Sleep -Seconds 2

$draftPattern = [regex]::Escape($DraftName)
$draft = Wait-Element $process.Id {
    $_.Current.Name -match $draftPattern -and
    $_.Current.ControlType.ProgrammaticName -notmatch 'Edit'
} ([Math]::Min(90, $TimeoutSeconds)) "草稿卡片“$DraftName”"
Invoke-Element $draft -DoubleClick

$exportButton = Wait-Element $process.Id {
    $_.Current.Name -match '^\s*(导出|Export)\s*$' -and
    $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
} ([Math]::Min(120, $TimeoutSeconds)) "编辑页导出按钮"
Invoke-Element $exportButton
Start-Sleep -Seconds 2

$edits = @(Get-VisibleElements $process.Id | Where-Object {
    $_.Current.ControlType.ProgrammaticName -match 'Edit'
})
$nameEdit = $edits | Where-Object {
    ($_.Current.Name + " " + $_.Current.AutomationId) -match '(作品名称|文件名称|视频名称|标题|file.?name|title|name)'
} | Select-Object -First 1
$pathEdit = $edits | Where-Object {
    ($_.Current.Name + " " + $_.Current.AutomationId) -match '(保存至|保存位置|输出|路径|目录|文件夹|location|folder|path)'
} | Select-Object -First 1

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

if ($pathEdit) {
    if (-not (Set-ElementValue $pathEdit $outputDirectory)) {
        throw "无法填写剪映导出目录"
    }
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
}

$confirm = Get-VisibleElements $process.Id | Where-Object {
    $_.Current.Name -match '^\s*(导出|Export)\s*$' -and
    $_.Current.ControlType.ProgrammaticName -match '(Button|Text|Custom)'
} | Select-Object -Last 1
if (-not $confirm) {
    throw "没有找到剪映导出确认按钮"
}
Invoke-Element $confirm

$fileDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastSize = -1L
$stable = 0
while ((Get-Date) -lt $fileDeadline) {
    if (Test-Path -LiteralPath $OutputPath -PathType Leaf) {
        $size = (Get-Item -LiteralPath $OutputPath).Length
        if ($size -gt 0 -and $size -eq $lastSize) {
            $stable += 1
            if ($stable -ge 3) {
                [pscustomobject]@{
                    status = "success"
                    draft_name = $DraftName
                    output_path = $OutputPath
                    size_bytes = $size
                } | ConvertTo-Json -Compress
                exit 0
            }
        }
        else {
            $stable = 0
        }
        $lastSize = $size
    }
    Start-Sleep -Seconds 1
}
throw "剪映导出超时，未生成目标 MP4：$OutputPath"
