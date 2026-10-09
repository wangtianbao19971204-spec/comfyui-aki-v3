// Console-only isolation fixture. Uses real Windows APIs only on a new empty
// test directory. The single allowed CreateProcess test names a nonexistent
// executable; no child process, GPU job, GUI or production service is started.
using System;
using System.IO;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using HarmonyLib;

public static class NativeFixture
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct StartupInfo
    {
        public int Size;
        public string Reserved;
        public string Desktop;
        public string Title;
        public uint X, Y, XSize, YSize, XCountChars, YCountChars, FillAttribute, Flags;
        public short ShowWindow, Reserved2Size;
        public IntPtr Reserved2, StdInput, StdOutput, StdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct ProcessInfo
    {
        public IntPtr Process, Thread;
        public uint ProcessId, ThreadId;
    }

    [DllImport("kernel32", EntryPoint = "MoveFileExW", CharSet = CharSet.Ansi, SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool MoveFileEx([MarshalAs(UnmanagedType.LPWStr)] string source,
        [MarshalAs(UnmanagedType.LPWStr)] string destination, uint flags);

    [DllImport("kernel32", EntryPoint = "CreateHardLinkW", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateHardLink(string destination, string source, IntPtr attributes);

    [DllImport("kernel32", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateProcess(string application, StringBuilder commandLine,
        IntPtr processAttributes, IntPtr threadAttributes, [MarshalAs(UnmanagedType.Bool)] bool inherit,
        uint flags, IntPtr environment, string directory, [In, Out] ref StartupInfo startup, out ProcessInfo info);

    [DllImport("kernel32", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern unsafe bool CreateProcessPointer(string application, StringBuilder commandLine,
        IntPtr processAttributes, IntPtr threadAttributes, [MarshalAs(UnmanagedType.Bool)] bool inherit,
        uint flags, char* environment, string directory, [In, Out] ref StartupInfo startup, out ProcessInfo info);

    [DllImport("advapi32", EntryPoint = "CreateProcessAsUserW", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateProcessAsUser(IntPtr token, string application, string commandLine,
        IntPtr processAttributes, IntPtr threadAttributes, [MarshalAs(UnmanagedType.Bool)] bool inherit,
        uint flags, IntPtr environment, string directory, [In, Out] ref StartupInfo startup, out ProcessInfo info);

    [DllImport("ntdll", EntryPoint = "NtCreateFile", ExactSpelling = true)]
    public static extern int NtCreateFile(out IntPtr handle, uint access, IntPtr attributes, IntPtr ioStatus,
        IntPtr allocationSize, uint fileAttributes, uint share, uint disposition, uint options, IntPtr ea, uint eaSize);
}

public static class NativeGuardsTests
{
    private static string Root, Protected, MissingExecutable;
    private static int Checks, ProcessPolicyCalls, Logs;

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 1) throw new InvalidOperationException("fixture_new_output_required");
            Root = Path.GetFullPath(args[0]);
            string runtime = @"G:\ComfyUI-aki-v3";
            if (Root.Equals(runtime, StringComparison.OrdinalIgnoreCase)
                || Root.StartsWith(runtime + "\\", StringComparison.OrdinalIgnoreCase)
                || Directory.Exists(Root) || File.Exists(Root))
                throw new InvalidOperationException("fixture_existing_or_production_path_rejected");
            Directory.CreateDirectory(Root);
            Protected = Path.Combine(Root, "protected");
            Directory.CreateDirectory(Protected);
            MissingExecutable = Path.Combine(Root, "fixture-does-not-exist.exe");
            int count = NativeGuards.Install(new Harmony("huishi.nativeguard.fixture"), typeof(NativeFixture).Assembly,
                ProtectPath, ProtectProcess, FixedLog);
            Check(count == 6 && Logs == 6, "installed-native-guards");
            Run();
            Console.WriteLine("PASS native-guards checks=" + Checks + ";actual-child-processes=0;nt-handle-api=blocked");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("FAIL native-guards " + exception.GetType().Name);
            // Fixed method names identify the failing fixture without paths,
            // command lines, environment values or native argument contents.
            foreach (var frame in new System.Diagnostics.StackTrace(exception, false).GetFrames() ?? Array.Empty<System.Diagnostics.StackFrame>())
            {
                var method = frame.GetMethod();
                if (method?.DeclaringType != null)
                    Console.Error.WriteLine(method.DeclaringType.FullName + "." + method.Name);
            }
            return 1;
        }
    }

    private static void Check(bool condition, string fixedLabel)
    {
        if (!condition) throw new InvalidOperationException(fixedLabel);
        Checks++;
        Console.WriteLine("check " + fixedLabel);
    }

    private static void ProtectPath(string path, bool directory)
    {
        if (path == null) return;
        string full = Path.GetFullPath(path);
        bool containsProtected = directory && Protected.StartsWith(full.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
        if (full.Equals(Protected, StringComparison.OrdinalIgnoreCase)
            || full.StartsWith(Protected + "\\", StringComparison.OrdinalIgnoreCase) || containsProtected)
            throw new InvalidOperationException("fixture_path_blocked");
    }

    private static void ProtectProcess(string application, string command, string directory)
    {
        ProcessPolicyCalls++;
        if (application != MissingExecutable || command != null || directory != Root)
            throw new InvalidOperationException("fixture_process_blocked");
        if (File.Exists(MissingExecutable)) throw new InvalidOperationException("fixture_executable_unexpectedly_exists");
    }

    private static void FixedLog(string operation, string label)
    {
        if (operation != "native-guard-installed" && operation != "blocked-native-write")
            throw new InvalidOperationException("fixture_unknown_log_operation");
        if (label.IndexOf('\\') >= 0 || label.IndexOf('/') >= 0 || label.IndexOf(':') >= 0)
            throw new InvalidOperationException("fixture_nonfixed_log_rejected");
        Logs++;
    }

    private static void Denied(Action call, string label)
    {
        bool denied = false;
        try { call(); } catch (InvalidOperationException) { denied = true; }
        Check(denied, label);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static unsafe void Run()
    {
        string source = Path.Combine(Root, "unicode-测试-source.txt");
        string destination = Path.Combine(Root, "unicode-测试-destination.txt");
        File.WriteAllText(source, "fixture");
        Check(NativeFixture.MoveFileEx(source, destination, 0), "allowed-native-rename");
        Check(File.ReadAllText(destination) == "fixture" && !File.Exists(source), "unicode-marshalling-preserved");
        string protectedFile = Path.Combine(Protected, "source.py");
        File.WriteAllText(protectedFile, "protected-fixture");
        Denied(() => NativeFixture.MoveFileEx(protectedFile, source, 0), "protected-move-source-denied");
        Denied(() => NativeFixture.MoveFileEx(destination, protectedFile, 1), "protected-move-destination-denied");
        Denied(() => NativeFixture.MoveFileEx(Protected, Path.Combine(Root, "moved-folder"), 0), "protected-directory-move-denied");
        Check(File.ReadAllText(protectedFile) == "protected-fixture" && File.Exists(destination), "protected-move-no-side-effects");
        string link = Path.Combine(Root, "hardlink.txt");
        Check(NativeFixture.CreateHardLink(link, destination, IntPtr.Zero), "allowed-native-hardlink");
        Check(File.ReadAllText(link) == "fixture", "native-hardlink-content");
        Denied(() => NativeFixture.CreateHardLink(Path.Combine(Root, "source-alias.txt"), protectedFile, IntPtr.Zero), "protected-hardlink-source-denied");
        Denied(() => NativeFixture.CreateHardLink(Path.Combine(Protected, "destination.txt"), destination, IntPtr.Zero), "protected-hardlink-destination-denied");
        Check(!File.Exists(Path.Combine(Root, "source-alias.txt")) && !File.Exists(Path.Combine(Protected, "destination.txt")), "protected-hardlink-no-side-effects");
        bool moveFailed = !NativeFixture.MoveFileEx(Path.Combine(Root, "missing.txt"), source, 0);
        int nativeError = Marshal.GetLastPInvokeError();
        Console.WriteLine("fixture-native-error=" + nativeError);
        Check(moveFailed, "native-failure-return-preserved");
        Check(nativeError == 2 || nativeError == 3, "native-last-error-preserved");
        var startup = new NativeFixture.StartupInfo { Size = Marshal.SizeOf<NativeFixture.StartupInfo>() };
        NativeFixture.ProcessInfo info;
        bool created = NativeFixture.CreateProcess(MissingExecutable, null, IntPtr.Zero, IntPtr.Zero, false,
            0, IntPtr.Zero, Root, ref startup, out info);
        Check(!created && info.Process == IntPtr.Zero && info.Thread == IntPtr.Zero && startup.Size == Marshal.SizeOf<NativeFixture.StartupInfo>(),
            "native-ref-out-marshalling-preserved");
        bool pointerCreated = NativeFixture.CreateProcessPointer(MissingExecutable, null, IntPtr.Zero, IntPtr.Zero, false,
            0, null, Root, ref startup, out info);
        Check(!pointerCreated && info.Process == IntPtr.Zero && info.Thread == IntPtr.Zero,
            "opaque-environment-pointer-marshalling-preserved");
        Denied(() => NativeFixture.CreateProcess("git.exe", new StringBuilder("git pull"), IntPtr.Zero, IntPtr.Zero, false,
            0, IntPtr.Zero, Root, ref startup, out info), "direct-native-git-denied");
        Denied(() => NativeFixture.CreateProcess("cmd.exe", new StringBuilder("cmd /c git pull"), IntPtr.Zero, IntPtr.Zero, false,
            0, IntPtr.Zero, Root, ref startup, out info), "native-shell-git-policy-denied");
        Denied(() => NativeFixture.CreateProcess(null, new StringBuilder("git.exe pull"), IntPtr.Zero, IntPtr.Zero, false,
            0, IntPtr.Zero, Root, ref startup, out info), "nullable-application-still-uses-policy");
        Denied(() => NativeFixture.CreateProcessPointer(MissingExecutable, new StringBuilder("cmd /c git pull"), IntPtr.Zero, IntPtr.Zero, false,
            0, (char*)1, Root, ref startup, out info), "pointer-process-denied-before-native-environment-access");
        Denied(() => NativeFixture.CreateProcessAsUser(IntPtr.Zero, "matsu.exe", "matsu update", IntPtr.Zero, IntPtr.Zero, false,
            0, IntPtr.Zero, Root, ref startup, out info), "native-as-user-policy-denied");
        Check(ProcessPolicyCalls == 7, "all-native-process-variants-use-policy");
        IntPtr handle = new IntPtr(123);
        Denied(() => NativeFixture.NtCreateFile(out handle, 0, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 0, 0, 0, 0, IntPtr.Zero, 0),
            "opaque-native-file-api-denied");
        Check(handle == new IntPtr(123), "denied-out-argument-untouched");
    }
}
