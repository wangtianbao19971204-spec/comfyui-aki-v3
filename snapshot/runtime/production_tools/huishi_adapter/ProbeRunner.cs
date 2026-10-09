// Isolated GUI experiment only. The hook rejects all child processes and Git writes.
using System;
using System.Diagnostics;
using System.IO;
using System.Text.Json;

public static class ProbeRunner
{
    public static int Main()
    {
        try
        {
            var directory = AppContext.BaseDirectory;
            using var settings = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "probe-settings.json")));
            var data = settings.RootElement;
            var root = Path.GetFullPath(data.GetProperty("root").GetString());
            var hook = Path.GetFullPath(data.GetProperty("hook").GetString());
            var authority = Path.GetFullPath(data.GetProperty("maintenance_repo").GetString());
            var log = Path.GetFullPath(data.GetProperty("log").GetString());
            var bootstrap = data.TryGetProperty("bootstrap_entry", out var useBootstrap) && useBootstrap.GetBoolean();
            var executable = bootstrap ? Path.Combine(root, "绘世启动器.exe") : Path.Combine(root, ".launcher", "StableDiffusionWebUILauncher.exe");
            var start = new ProcessStartInfo(executable);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.RedirectStandardError = true;
            start.RedirectStandardOutput = true;
            foreach (var key in new string[] { "AUTODL_TOKEN", "AUTODL_INSTANCE_UUID", "LEASE_SECRET", "LEASE_HEALTH_URL", "LEASE_HEARTBEAT_URL", "DOTNET_STARTUP_HOOKS" })
                start.Environment.Remove(key);
            if (!data.TryGetProperty("enable_adapter", out var enabled) || enabled.GetBoolean())
                start.Environment["DOTNET_STARTUP_HOOKS"] = hook;
            start.Environment["HUISHI_ADAPTER_ROOT"] = root;
            start.Environment["HUISHI_MAINTENANCE_REPO"] = authority;
            start.Environment["HUISHI_CORE_BASELINE"] = data.GetProperty("core_baseline").GetString();
            start.Environment["HUISHI_ADAPTER_LOG"] = log;
            if (data.TryGetProperty("read_probe", out var readProbe) && readProbe.GetBoolean())
                start.Environment["HUISHI_ADAPTER_READ_PROBE"] = "1";
            if (data.TryGetProperty("empty_probe", out var emptyProbe) && emptyProbe.GetBoolean())
                start.Environment["HUISHI_ADAPTER_EMPTY_PROBE"] = "1";
            if (data.TryGetProperty("initialize_original_first", out var originalFirst) && originalFirst.GetBoolean())
                start.Environment["HUISHI_ADAPTER_INIT_ORIGINAL_FIRST"] = "1";
            using var child = Process.Start(start);
            if (child == null) return 2;
            File.WriteAllText(Path.Combine(directory, "probe-process.json"), JsonSerializer.Serialize(new { pid = child.Id, started_at = DateTime.UtcNow, isolated = true }));
            if (child.WaitForExit(5000))
            {
                File.WriteAllText(Path.Combine(directory, "probe-exit.json"), JsonSerializer.Serialize(new { exit_code = child.ExitCode }));
                File.WriteAllText(Path.Combine(directory, "probe-stderr.txt"), child.StandardError.ReadToEnd());
                File.WriteAllText(Path.Combine(directory, "probe-stdout.txt"), child.StandardOutput.ReadToEnd());
            }
            return 0;
        }
        catch (Exception error)
        {
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "probe-error.txt"), error.GetType().FullName);
            return 1;
        }
    }
}
