# 把 Balatro 窗口恢复并置前台（验证后台节流假设）
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
}
"@
$p = Get-Process Balatro -ErrorAction Stop
$h = $p.MainWindowHandle
if ([W]::IsIconic($h)) { [void][W]::ShowWindow($h, 9) }  # SW_RESTORE
[void][W]::SetForegroundWindow($h)
Write-Output "window restored: $h"
