Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after,
        int x, int y, int w, int h, uint flags);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
}
"@
$p = Get-Process Balatro -ErrorAction Stop
$h = $p.MainWindowHandle
[void][Win]::ShowWindow($h, 9)
$ok = [Win]::SetWindowPos($h, [IntPtr](-1), -700, 0, 640, 400, 0x40)
Write-Output "topmost corner: $ok"
$p.PriorityClass = 'High'
Write-Output "priority: $($p.PriorityClass)"
