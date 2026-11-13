# 视觉截图脚本（人工查看用，不含自动断言）
# 用法：先启动 launcher.py（全屏或 --windowed），再在 PowerShell 中运行本脚本。
# 注意：下列鼠标坐标在 1920x1080 全屏环境下录制，其他分辨率需自行调整。
# 截图输出到脚本同级的 screenshots\，该目录已在 .gitignore 中排除。
Add-Type @"
using System; using System.Runtime.InteropServices;
public class CapG {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte sc, uint f, UIntPtr e);
}
"@
[CapG]::SetProcessDPIAware() | Out-Null
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$SW = [System.Windows.Forms.SystemInformation]::VirtualScreen.Width
$SH = [System.Windows.Forms.SystemInformation]::VirtualScreen.Height
$OutDir = Join-Path $PSScriptRoot 'screenshots'
if (-not (Test-Path -LiteralPath $OutDir)) {
  New-Item -ItemType Directory -Path $OutDir | Out-Null
}

$p = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'ERROR: launcher window not found'; exit 1 }
[void][CapG]::ShowWindow($p.MainWindowHandle, 9)
Start-Sleep -Milliseconds 400
[CapG]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
[void][CapG]::SetForegroundWindow($p.MainWindowHandle)
[CapG]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 900

function MoveTo($x, $y) {
  $nx = [int]([double]$x * 65536 / $SW)
  $ny = [int]([double]$y * 65536 / $SH)
  [CapG]::mouse_event(0x8001, [uint32]$nx, [uint32]$ny, 0, [UIntPtr]::Zero)
}

function Click {
  [CapG]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 120
  [CapG]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
}

function RightClick {
  [CapG]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 120
  [CapG]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
}

function Shot($name) {
  $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap([int]$b.Width, [int]$b.Height)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen([int]$b.Left, [int]$b.Top, 0, 0, $bmp.Size)
  $bmp.Save((Join-Path $OutDir $name), [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Output ("saved " + $name)
}

# 1) 悬停（缩放/晕染/阴影/焦点联动）
MoveTo 560 700
Start-Sleep -Milliseconds 700
Shot 'shot1-hover.png'

# 2) 管理模式（卡片随机相位抖动 + × 角标）
MoveTo 198 974
Start-Sleep -Milliseconds 250
Click
Start-Sleep -Milliseconds 900
Shot 'shot2-edit-mode.png'

# 3) 管理模式点第一张卡的 × → 移除
MoveTo 504 600
Start-Sleep -Milliseconds 250
Click
Start-Sleep -Milliseconds 1200
Shot 'shot3-after-remove.png'

# 4) 退出管理 + 右键空白处深色菜单
MoveTo 198 974
Start-Sleep -Milliseconds 250
Click
Start-Sleep -Milliseconds 400
MoveTo 800 800
Start-Sleep -Milliseconds 250
RightClick
Start-Sleep -Milliseconds 800
Shot 'shot4-context-menu.png'
