# 解除 Balatro 的 EcoQoS 节流 + 提升高优先级
Add-Type @"
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

public class Boost {
    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_POWER_THROTTLING_STATE {
        public uint Version;
        public ulong ControlMask;
        public ulong StateMask;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetProcessInformation(IntPtr hProcess,
        int ProcessInformationClass, ref PROCESS_POWER_THROTTLING_STATE info, int size);

    public static string BoostProcess(string name) {
        var procs = Process.GetProcessesByName(name);
        if (procs.Length == 0) return "no process";
        var results = new System.Collections.Generic.List<string>();
        foreach (var p in procs) {
            try {
                p.PriorityClass = ProcessPriorityClass.High;
            } catch (Exception e) { results.Add("prio fail: " + e.Message); }
            try {
                var s = new PROCESS_POWER_THROTTLING_STATE();
                s.Version = 1;
                s.ControlMask = 1;   // PROCESS_POWER_THROTTLING_EXECUTION_SPEED
                s.StateMask = 0;     // 0 = 禁用节流(全速)
                bool ok = SetProcessInformation(p.Handle, 4, ref s,
                    System.Runtime.InteropServices.Marshal.SizeOf(s));
                results.Add((ok ? "eco-off ok" : "eco-off fail") + " prio=" + p.PriorityClass);
            } catch (Exception e) { results.Add("eco err: " + e.Message); }
        }
        return string.Join("; ", results);
    }
}
"@
[Boost]::BoostProcess("Balatro")
