# Снимает скриншоты настоящего окна консоли, в котором выполняется команда.
# Захватывается только это окно (PrintWindow), остальной рабочий стол в снимок не попадает.
#
#   powershell -File scripts\capture_terminal.ps1 -Command "<команда cmd>" -Out shot.png -Title "..."
#   ... -Out a.png,b.png -CaptureAt 60,200     # два снимка одного прогона: на 60-й и 200-й секунде
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [Parameter(Mandatory = $true)][string[]]$Out,
    [string]$Title = "lead-assistant",
    [string]$WorkDir = (Get-Location).Path,
    [int[]]$CaptureAt = @(10),
    [int]$Cols = 132,
    [int]$Lines = 46,
    # Остановить сервер модели, запущенный после начала съёмки. Включайте только если
    # одновременно нет других прогонов: сервер ищется по времени запуска.
    [switch]$StopModelServer
)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ConsoleShot {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

if ($Out.Count -ne $CaptureAt.Count) { throw "Out and CaptureAt must have the same number of items" }

$inner = "mode con: cols=$Cols lines=$Lines & chcp 65001 >nul & title $Title & cd /d `"$WorkDir`" & $Command"
$process = Start-Process -FilePath "conhost.exe" -ArgumentList "cmd.exe /k `"$inner`"" -PassThru
$owner = $null
$started = Get-Date
try {
    for ($index = 0; $index -lt $Out.Count; $index++) {
        $remaining = $CaptureAt[$index] - ((Get-Date) - $started).TotalSeconds
        if ($remaining -gt 0) { Start-Sleep -Seconds ([int][math]::Ceiling($remaining)) }
        # Окно консоли числится за клиентским процессом (cmd.exe), поэтому ищем его по заголовку.
        $owner = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" } | Select-Object -First 1
        if ($null -eq $owner) { throw "console window with title '$Title' not found" }
        $handle = $owner.MainWindowHandle

        $rect = New-Object ConsoleShot+RECT
        [void][ConsoleShot]::GetWindowRect($handle, [ref]$rect)
        $width = $rect.Right - $rect.Left
        $height = $rect.Bottom - $rect.Top
        $bitmap = New-Object System.Drawing.Bitmap $width, $height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $hdc = $graphics.GetHdc()
        $ok = [ConsoleShot]::PrintWindow($handle, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT
        $graphics.ReleaseHdc($hdc)
        $graphics.Dispose()
        $bitmap.Save($Out[$index], [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
        "saved=$($Out[$index]) size=${width}x${height} printwindow=$ok at=$([int]((Get-Date) - $started).TotalSeconds)s"
    }
}
finally {
    if ($null -ne $owner -and -not $owner.HasExited) { Stop-Process -Id $owner.Id -Force }
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    if ($StopModelServer) {
        Get-Process llama-server -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -ge $started } | Stop-Process -Force
    }
}
