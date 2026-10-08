// Additional startup hook for an EMPTY isolated vendor GUI copy only.
// It tests the real GUI archive callback after the adapter's first hook, then
// exits before the GUI entry point. No UI, Python, GPU or service is started.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

public static class StartupHook
{
    private static string Root, Output;
    private static readonly List<string> Stages = new List<string>();

    public static void Initialize()
    {
        int exit = 1;
        try
        {
            Root = Path.GetFullPath(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_ROOT") ?? "");
            Output = Path.GetFullPath(Environment.GetEnvironmentVariable("HUISHI_ARCHIVE_TEST_OUT") ?? "");
            string authority = Path.GetFullPath(Environment.GetEnvironmentVariable("HUISHI_MAINTENANCE_REPO") ?? "");
            string actualRuntime = Directory.GetParent(Directory.GetParent(authority).FullName).FullName;
            if (!Path.GetFileName(Root).StartsWith("archive-gui-", StringComparison.OrdinalIgnoreCase)
                || Within(Root, actualRuntime) || Within(actualRuntime, Root)
                || Output.StartsWith(Root + "\\", StringComparison.OrdinalIgnoreCase)
                || File.Exists(Path.Combine(Root, "python", "python.exe"))
                || File.Exists(Path.Combine(Root, "python", "pythonw.exe")))
                throw new InvalidOperationException("archive_probe_isolation_required");
            string models = Path.Combine(Root, "ComfyUI", "models");
            if (Directory.Exists(models) && Directory.EnumerateFileSystemEntries(models).Any())
                throw new InvalidOperationException("archive_probe_models_rejected");
            if (!Directory.Exists(Output)) throw new InvalidOperationException("archive_probe_output_missing");
            var assembly = Assembly.GetEntryAssembly();
            if (Environment.GetEnvironmentVariable("HUISHI_ARCHIVE_TEST_MODE") == "inspect")
            {
                var reports = new List<object>();
                foreach (string name in new[] { "InterpreterMethod", "EventMethod", "StubMethod", "WrapperMethod", "InfoMethod" })
                {
                    var type = Type(assembly, name);
                    reports.Add(new { type = type.FullName,
                        constructors = type.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
                            .Select(c => c.ToString()).ToArray(),
                        methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                            .Select(m => m.ToString()).ToArray() });
                }
                Write(new { mode = "metadata-only", reports, production_deployed = false });
            }
            else
            {
                RunArchive(assembly, false);
                RunArchive(assembly, true);
                Write(new { mode = "real-vendor-archive-callback", checks = Stages.ToArray(), production_deployed = false,
                    ui_started = false, python_started = false, service_started = false });
            }
            exit = 0;
        }
        catch (Exception exception)
        {
            try
            {
                var types = new List<string>();
                for (var current = exception; current != null; current = current.InnerException) types.Add(current.GetType().Name);
                string rule = exception.Message.StartsWith("archive_probe_", StringComparison.Ordinal) ? exception.Message : null;
                Write(new { mode = "failed", stages = Stages.ToArray(), exception_types = types.ToArray(), rule, production_deployed = false });
            }
            catch { }
        }
        finally { Environment.Exit(exit); }
    }

    private static bool Within(string path, string root)
    {
        return path.Equals(root, StringComparison.OrdinalIgnoreCase)
            || path.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
    }

    private static void RunArchive(Assembly assembly, bool protectedTarget)
    {
        string label = protectedTarget ? "protected" : "allowed";
        Stages.Add(label + "-prepare");
        string zip = Path.Combine(Output, label + ".7z");
        WriteStored7z(zip, protectedTarget ? "fixture.py" : "fixture.txt");
        string destination = protectedTarget
            ? Path.Combine(Root, "ComfyUI", "custom_nodes", "archive-guard-fixture") : Path.Combine(Output, "allowed-output");
        Directory.CreateDirectory(destination);
        string output = Path.Combine(destination, protectedTarget ? "fixture.py" : "fixture.txt");
        if (File.Exists(output)) throw new InvalidOperationException("archive_probe_existing_target_rejected");
        var inArchive = Type(assembly, "WrapperMethod");
        var factory = Type(assembly, "EventMethod").GetMethod("ManageManager", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        var createArguments = new object[] { new Guid("23170F69-40C1-278A-1000-000110070000"),
            new Guid("23170F69-40C1-278A-0000-000600600000"), null };
        int createResult = Convert.ToInt32(factory.Invoke(null, createArguments));
        Stages.Add(label + "-native-factory-result-" + createResult.ToString());
        if (createResult != 0 || createArguments[2] == null) throw new InvalidOperationException("archive_probe_factory_failed");
        Stages.Add(label + "-native-created");
        object native = createArguments[2];
        using var input = new FileStream(zip, FileMode.Open, FileAccess.Read);
        object inputStream = Activator.CreateInstance(Type(assembly, "StubMethod"), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null, new object[] { input, false }, null);
        var open = inArchive.GetMethod("SetNotificationTemplate");
        var openArgs = new object[] { inputStream, (ulong)0, null };
        object openResult = open.Invoke(native, openArgs);
        if (openResult != null && Convert.ToInt32(openResult) != 0) throw new InvalidOperationException("archive_probe_open_failed");
        Stages.Add(label + "-native-opened");
        if (Convert.ToUInt32(inArchive.GetMethod("InsertNotificationTemplate").Invoke(native, null)) != 1)
            throw new InvalidOperationException("archive_probe_item_count_mismatch");
        object callback = Activator.CreateInstance(Type(assembly, "InterpreterMethod"), BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null, new object[] { native, destination }, null);
        bool rejected = false;
        string[] callbackErrors = Array.Empty<string>();
        try
        {
            var extract = inArchive.GetMethod("InstantiateNotificationTemplate");
            object result = extract.Invoke(native, new object[] { null, UInt32.MaxValue, 0, callback });
            rejected = result != null && Convert.ToInt32(result) != 0;
            callbackErrors = ((IEnumerable<Exception>)callback.GetType().GetMethod("CollectParameter").Invoke(callback, null))
                .Select(error => error.GetType().Name).ToArray();
        }
        catch (TargetInvocationException) { rejected = true; }
        finally
        {
            (callback as IDisposable)?.Dispose();
            inArchive.GetMethod("Close").Invoke(native, null);
            if (Marshal.IsComObject(native)) Marshal.FinalReleaseComObject(native);
        }
        if (protectedTarget)
        {
            if (File.Exists(output)) throw new InvalidOperationException("archive_probe_protected_file_written");
            if (!rejected && callbackErrors.Length == 0) throw new InvalidOperationException("archive_probe_rejection_not_observed");
            Stages.Add("protected-output-absent");
            foreach (string error in callbackErrors) Stages.Add("protected-callback-exception-" + error);
        }
        else
        {
            if (rejected || !File.Exists(output) || File.ReadAllText(output) != "archive-fixture")
                throw new InvalidOperationException("archive_probe_allowed_output_missing");
            Stages.Add("allowed-output-extracted");
        }
    }

    private static void WriteStored7z(string path, string name)
    {
        // One file using the standard 7z Copy coder; no external compressor or
        // archive executable is needed. Every integer fits the one-byte form.
        byte[] data = Encoding.UTF8.GetBytes("archive-fixture");
        byte[] fileName = Encoding.Unicode.GetBytes(name + "\0");
        using var headerStream = new MemoryStream();
        using (var header = new BinaryWriter(headerStream, Encoding.UTF8, true))
        {
            header.Write(new byte[] { 1, 4, 6, 0, 1, 9, (byte)data.Length, 0,
                7, 11, 1, 0, 1, 1, 0, 12, (byte)data.Length, 0, 0,
                5, 1, 17, (byte)(fileName.Length + 1), 0 });
            header.Write(fileName);
            header.Write(new byte[] { 0, 0 });
        }
        byte[] nextHeader = headerStream.ToArray();
        using var startStream = new MemoryStream();
        using (var start = new BinaryWriter(startStream, Encoding.UTF8, true))
        {
            start.Write((ulong)data.Length);
            start.Write((ulong)nextHeader.Length);
            start.Write(Crc32(nextHeader));
        }
        byte[] startHeader = startStream.ToArray();
        using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write);
        using var writer = new BinaryWriter(output);
        writer.Write(new byte[] { 0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c, 0, 4 });
        writer.Write(Crc32(startHeader));
        writer.Write(startHeader);
        writer.Write(data);
        writer.Write(nextHeader);
    }

    private static uint Crc32(byte[] data)
    {
        uint crc = UInt32.MaxValue;
        foreach (byte value in data)
        {
            crc ^= value;
            for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0U : 0xedb88320U);
        }
        return ~crc;
    }

    private static Type Type(Assembly assembly, string name)
    {
        return assembly.GetType("StableDiffusionWebUILauncher.Internal." + name, true);
    }

    private static void Write(object report)
    {
        File.WriteAllText(Path.Combine(Output, "archive-report.json"), JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    }
}
