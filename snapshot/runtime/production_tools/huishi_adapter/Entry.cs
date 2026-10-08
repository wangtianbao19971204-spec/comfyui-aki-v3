// Local transparent entry: run the preserved vendor bootstrap and its original GUI.
// Build with the existing .NET Framework compiler. No shell or console window.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public static class HuishiEntry
{
    private static readonly HashSet<string> PrivateEnvironmentKeys = new HashSet<string>(new [] {
        // Keep this set aligned with remote_llm_guard/launcher.py ENVIRONMENT_KEYS.
        "AUTODL_TOKEN", "AUTODL_INSTANCE_UUID", "AUTODL_START_COMMAND",
        "COMFY_URL", "LEASE_HEALTH_URL", "LEASE_HEARTBEAT_URL", "LEASE_SECRET",
        "CHECK_INTERVAL_SECONDS", "LOCAL_HEARTBEAT_LOG_PATH",
        "AUTODL_MAX_WAIT_SECONDS", "AUTODL_RETRY_SECONDS", "AUTODL_SSH_HOST",
        "AUTODL_SSH_PORT", "AUTODL_SSH_USER", "AUTODL_SSH_KEY",
        "AUTODL_SSH_START_COMMAND", "AUTODL_SSH_FALLBACK_AFTER_ATTEMPTS",
        "DOTNET_STARTUP_HOOKS", "TOKEN", "SECRET", "PASSWORD", "API_KEY",
        "GITHUB_PAT", "AUTHORIZATION", "HTTP_AUTHORIZATION", "COOKIE", "COOKIES"
    }, StringComparer.OrdinalIgnoreCase);

    internal static void SanitizeChildEnvironment(ProcessStartInfo start)
    {
        // Inspect names only. Values and the parent environment are never logged
        // or changed. Retain ordinary PATH, CUDA and user GUI environment keys.
        var remove = new List<string>();
        foreach (string key in start.EnvironmentVariables.Keys)
        {
            string name = key.ToUpperInvariant();
            bool sensitive = PrivateEnvironmentKeys.Contains(name)
                || name.StartsWith("HUISHI_", StringComparison.Ordinal)
                || name.StartsWith("AKI_HUISHI_", StringComparison.Ordinal);
            foreach (string suffix in new [] {
                "_TOKEN", "_SECRET", "_PASSWORD", "_PASSWD", "_API_KEY",
                "_ACCESS_KEY", "_ACCESS_KEY_ID", "_PRIVATE_KEY", "_CREDENTIAL",
                "_CREDENTIALS", "_COOKIE", "_COOKIES", "_JWT"
            })
                if (name.EndsWith(suffix, StringComparison.Ordinal)) sensitive = true;
            if (sensitive) remove.Add(key);
        }
        foreach (string key in remove) start.EnvironmentVariables.Remove(key);
    }

    private static string Hash(string path)
    {
        NoLinks(path);
        using (var input = File.OpenRead(path))
        using (var sha = SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
    }
    private static void NoLinks(string path)
    {
        string current = Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(current))
        {
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("linked_path");
            current = Path.GetDirectoryName(current);
        }
    }
    private static string Value(Dictionary<string, object> data, string key)
    {
        object value;
        if (!data.TryGetValue(key, out value) || !(value is string) || String.IsNullOrWhiteSpace((string)value))
            throw new InvalidOperationException("missing_configuration");
        return (string)value;
    }
    private static void Check(string path, string digest)
    {
        if (digest.Length != 64 || !String.Equals(Hash(path), digest, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("pinned_file_changed");
    }
    [STAThread]
    public static int Main()
    {
        try
        {
            string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            NoLinks(root);
            string settings = Path.Combine(root, "production_tools", "huishi_adapter", "entry.local.json");
            NoLinks(settings);
            if (new FileInfo(settings).Length > 32768) throw new InvalidOperationException("configuration_size");
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(settings, Encoding.UTF8));
            var keys = new HashSet<string>(new [] { "mode", "maintenance_repo", "hook", "hook_sha256", "harmony_sha256", "core_baseline", "main_sha256", "runtime_start_sha256", "log" });
            if (data.Count != keys.Count) throw new InvalidOperationException("configuration_fields");
            foreach (string key in data.Keys) if (!keys.Contains(key)) throw new InvalidOperationException("configuration_fields");
            string mode = Value(data, "mode");
            if (mode != "managed" && mode != "isolation") throw new InvalidOperationException("configuration_mode");
            string original = Path.Combine(root, "绘世启动器原版.exe");
            Check(original, "8652f7a83144b8faa18a5b5d0c75444e4da2004933b645a9636e9b4ae914229e");
            string hook = Path.GetFullPath(Value(data, "hook"));
            Check(hook, Value(data, "hook_sha256"));
            Check(Path.Combine(Path.GetDirectoryName(hook), "0Harmony.dll"), Value(data, "harmony_sha256"));
            string mainRepo = Path.GetFullPath(Value(data, "maintenance_repo"));
            NoLinks(mainRepo);
            if (mode == "managed" && !String.Equals(mainRepo, Path.Combine(root, "maintenance", "comfyui"), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("sole_repository_required");
            var start = new ProcessStartInfo(original);
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            // Dedicated child dictionary: do not change system or parent environment.
            SanitizeChildEnvironment(start);
            start.EnvironmentVariables["DOTNET_STARTUP_HOOKS"] = hook;
            start.EnvironmentVariables["HUISHI_ADAPTER_ROOT"] = root;
            start.EnvironmentVariables["HUISHI_MAINTENANCE_REPO"] = mainRepo;
            start.EnvironmentVariables["HUISHI_CORE_BASELINE"] = Value(data, "core_baseline");
            start.EnvironmentVariables["HUISHI_ADAPTER_LOG"] = Value(data, "log");
            start.EnvironmentVariables["HUISHI_ADAPTER_MODE"] = mode;
            // Managed mode has its own reviewed module-initialization path.
            // Only the explicit empty isolation mode uses this diagnostic flag.
            if (mode == "isolation") start.EnvironmentVariables["HUISHI_ADAPTER_INIT_ORIGINAL_FIRST"] = "1";
            start.EnvironmentVariables["HUISHI_MAIN_SHA256"] = Value(data, "main_sha256");
            start.EnvironmentVariables["HUISHI_RUNTIME_START_SHA256"] = Value(data, "runtime_start_sha256");
            if (mode == "managed") start.EnvironmentVariables["AKI_HUISHI_PROFILE"] = "production";
            else start.EnvironmentVariables.Remove("AKI_HUISHI_PROFILE");
            using (var child = Process.Start(start)) if (child == null) throw new InvalidOperationException("bootstrap_not_started");
            return 0;
        }
        catch
        {
            MessageBox.Show("绘世入口校验失败，尚未启动。请检查同批适配文件与回滚收据；不要恢复旧 Git。", "绘世主仓适配", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 78;
        }
    }
}
