# Position Balatro window at left side of screen for demo recording
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int w, int h, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
}
"@
$p = Get-Process Balatro -ErrorAction Stop
$h = $p.MainWindowHandle
[Win32]::ShowWindow($h, 9) | Out-Null   # SW_RESTORE
# HWND_TOPMOST=-1; SWP flags: 0x0040 no-size? use 0x0000 (move+size)
[Win32]::SetWindowPos($h, [IntPtr](-1), 8, 120, 880, 620, 0x0010) | Out-Null
Write-Output ("game window at 8,120 880x620 topmost")
