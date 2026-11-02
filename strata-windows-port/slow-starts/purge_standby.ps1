# purge_standby.ps1 - empty Windows' standby list (the file cache), as RAMMap's "Empty Standby List" does.
# Needs an elevated (admin) token: it enables SeProfileSingleProcessPrivilege, then
# NtSetSystemInformation(SystemMemoryListInformation, MemoryPurgeStandbyList).
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Purge {
    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    struct TokPriv { public int Count; public long Luid; public int Attr; }
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool OpenProcessToken(IntPtr h, int access, out IntPtr tok);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool LookupPrivilegeValue(string host, string name, out long luid);
    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool AdjustTokenPrivileges(IntPtr tok, bool off, ref TokPriv np, int len, IntPtr prev, IntPtr rlen);
    [DllImport("kernel32.dll")]
    static extern IntPtr GetCurrentProcess();
    [DllImport("ntdll.dll")]
    static extern int NtSetSystemInformation(int cls, ref int info, int len);
    public static string Run() {
        IntPtr tok;
        if (!OpenProcessToken(GetCurrentProcess(), 0x28, out tok)) return "OpenProcessToken failed " + Marshal.GetLastWin32Error();
        TokPriv tp = new TokPriv { Count = 1, Attr = 2 };
        if (!LookupPrivilegeValue(null, "SeProfileSingleProcessPrivilege", out tp.Luid)) return "Lookup failed";
        AdjustTokenPrivileges(tok, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero);
        int err = Marshal.GetLastWin32Error();
        if (err != 0) return "privilege not held (error " + err + "): run elevated";
        int cmd = 4;                                   // MemoryPurgeStandbyList
        int st = NtSetSystemInformation(80, ref cmd, 4);
        return st == 0 ? "purged" : "NtSetSystemInformation status 0x" + st.ToString("X8");
    }
}
"@
function Standby { (Get-Counter "\Memory\Standby Cache Normal Priority Bytes","\Memory\Standby Cache Reserve Bytes","\Memory\Standby Cache Core Bytes").CounterSamples | Measure-Object CookedValue -Sum | % { "{0:N1}" -f ($_.Sum / 1GB) } }
$before = Standby
$r = [Purge]::Run()
"$r (standby GB $before -> $(Standby))"
