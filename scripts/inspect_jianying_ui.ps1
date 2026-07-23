param(
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $env:LOCALAPPDATA "DouyinRenderWorker\diagnostics"
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path

$process = Get-Process | Where-Object {
    $_.ProcessName -match '^(JianyingPro|CapCut)$' -and $_.MainWindowHandle -ne 0
} | Select-Object -First 1
if (-not $process) {
    throw "Jianying/CapCut main window was not found. Open Jianying on its draft list page first."
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing

$root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
if (-not $root) {
    throw "Unable to attach Windows UI Automation to Jianying."
}

$condition = [System.Windows.Automation.Condition]::TrueCondition
$elements = $root.FindAll([System.Windows.Automation.TreeScope]::Subtree, $condition)
$records = New-Object System.Collections.Generic.List[object]
foreach ($element in $elements) {
    try {
        $rect = $element.Current.BoundingRectangle
        $records.Add([pscustomobject]@{
            name = [string]$element.Current.Name
            automation_id = [string]$element.Current.AutomationId
            class_name = [string]$element.Current.ClassName
            control_type = [string]$element.Current.ControlType.ProgrammaticName
            enabled = [bool]$element.Current.IsEnabled
            offscreen = [bool]$element.Current.IsOffscreen
            x = [double]$rect.X
            y = [double]$rect.Y
            width = [double]$rect.Width
            height = [double]$rect.Height
        })
    }
    catch {
        # Jianying may destroy transient elements while the tree is inspected.
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$jsonPath = Join-Path $OutputDirectory "jianying-ui-$stamp.json"
[pscustomobject]@{
    captured_at = (Get-Date).ToString("o")
    process_id = $process.Id
    process_path = $process.Path
    window_title = $root.Current.Name
    element_count = $records.Count
    elements = $records
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$windowRect = $root.Current.BoundingRectangle
if ($windowRect.Width -gt 0 -and $windowRect.Height -gt 0) {
    $bitmap = New-Object System.Drawing.Bitmap([int]$windowRect.Width, [int]$windowRect.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen(
            [int]$windowRect.X,
            [int]$windowRect.Y,
            0,
            0,
            $bitmap.Size,
            [System.Drawing.CopyPixelOperation]::SourceCopy
        )
        $imagePath = Join-Path $OutputDirectory "jianying-window-$stamp.png"
        $bitmap.Save($imagePath, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

[pscustomobject]@{
    status = "captured"
    element_count = $records.Count
    ui_json = $jsonPath
    screenshot = $imagePath
} | ConvertTo-Json -Compress
