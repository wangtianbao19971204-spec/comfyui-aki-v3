// Meaningful isolation tests: no GUI, Python, model or service is launched.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;

public static class AdapterTests
{
    private static int passed;
    private static void Assert(bool condition, string name)
    {
        if (!condition) throw new InvalidOperationException("assertion_failed:" + name);
        passed++; Console.WriteLine("PASS " + name);
    }
    private static void Blocked(Action action, string name)
    {
        try { action(); }
        catch (Exception error)
        {
            while (error is TargetInvocationException && error.InnerException != null) error = error.InnerException;
            Assert(error is InvalidOperationException && (error.Message.Contains("主仓") || error.Message.Contains("isolation_child_process_blocked")), name);
            return;
        }
        throw new InvalidOperationException("write_not_blocked:" + name);
    }
    public static int Main(string[] args)
    {
        try
        {
            // Paths are task-private command inputs, not public config or log output.
            string root = Path.GetFullPath(args[0]), repo = Path.GetFullPath(args[1]);
            string hookPath = Path.GetFullPath(args[2]), gitLibrary = Path.GetFullPath(args[3]);
            if (Directory.Exists(root)) throw new InvalidOperationException("new_isolation_required");
            Directory.CreateDirectory(Path.Combine(root, "ComfyUI"));
            string core = Path.Combine(root, "ComfyUI"), source = Path.Combine(core, "main.py");
            File.WriteAllText(source, "unchanged fixture");
            string adapterSource = Path.Combine(root, "production_tools", "huishi_adapter", "runtime_start.py");
            Directory.CreateDirectory(Path.GetDirectoryName(adapterSource));
            File.WriteAllText(adapterSource, "unchanged adapter fixture");
            string entry = Path.Combine(root, "绘世启动器.exe");
            File.WriteAllText(entry, "unchanged entry fixture");
            Environment.SetEnvironmentVariable("HUISHI_ADAPTER_ROOT", root);
            Environment.SetEnvironmentVariable("HUISHI_MAINTENANCE_REPO", repo);
            Environment.SetEnvironmentVariable("HUISHI_ADAPTER_LOG", Path.Combine(Directory.GetParent(root).FullName, "adapter-tests.log"));
            Environment.SetEnvironmentVariable("HUISHI_CORE_BASELINE", "cc0fc21fea7a6a82f568362b15b7fbd713b419c1");
            Environment.SetEnvironmentVariable("HUISHI_ADAPTER_MODE", null);
            Environment.SetEnvironmentVariable("HUISHI_ADAPTER_INIT_ORIGINAL_FIRST", "1");
            Assembly.LoadFrom(gitLibrary);
            Assembly.LoadFrom(Path.Combine(Path.GetDirectoryName(hookPath), "0Harmony.dll"));
            var hook = Assembly.LoadFrom(hookPath);
            hook.GetType("StartupHook").GetMethod("Initialize").Invoke(null, null);
            object[] dependencyResult = { null };
            var dependencyGuard = hook.GetType("AdapterCore").GetMethod("AutomaticDependenciesPrefix", BindingFlags.NonPublic | BindingFlags.Static);
            Assert(!(bool)dependencyGuard.Invoke(null, dependencyResult), "manual-dependency-original-not-run");
            var task = (System.Threading.Tasks.Task)dependencyResult[0];
            Assert(task.IsFaulted && task.Exception.InnerException is InvalidOperationException, "manual-dependency-not-fake-success");
            var git = AppDomain.CurrentDomain.GetAssemblies().Single(a => a.GetName().Name == "LibGit2Sharp");
            var repositoryType = git.GetType("LibGit2Sharp.Repository");
            var mapped = Activator.CreateInstance(repositoryType, new object[] { core });
            try
            {
                object head = repositoryType.GetProperty("Head").GetValue(mapped);
                object tip = head.GetType().GetProperty("Tip").GetValue(head);
                Assert((string)tip.GetType().GetProperty("Sha").GetValue(tip) == "cc0fc21fea7a6a82f568362b15b7fbd713b419c1", "real-baseline-mapping");
                object config = repositoryType.GetProperty("Config").GetValue(mapped);
                var set = config.GetType().GetMethods().Single(m => m.Name == "Set" && m.IsGenericMethodDefinition && m.GetParameters().Length == 2).MakeGenericMethod(typeof(string));
                Blocked(() => set.Invoke(config, new object[] { "aki.fixture", "no-write" }), "git-configuration");
                object rebase = repositoryType.GetProperty("Rebase").GetValue(mapped);
                Blocked(() => rebase.GetType().GetMethod("Abort", Type.EmptyTypes).Invoke(rebase, null), "git-rebase-abort");
                object stash = repositoryType.GetProperty("Stashes").GetValue(mapped);
                Blocked(() => stash.GetType().GetMethod("Pop", new[] { typeof(int) }).Invoke(stash, new object[] { 0 }), "git-stash-pop");
            }
            finally { ((IDisposable)mapped).Dispose(); }
            Blocked(() => File.WriteAllText(source, "changed"), "write-all-text");
            Blocked(() => File.AppendAllText(source, "changed"), "append-source");
            Blocked(() => { using var stream = new FileStream(source, FileMode.Open, FileAccess.ReadWrite); }, "file-stream-readwrite");
            Blocked(() => { using var stream = File.OpenHandle(source, FileMode.Open, FileAccess.ReadWrite); }, "open-handle-readwrite");
            Blocked(() => File.Delete(source), "delete-source");
            Blocked(() => File.Delete(adapterSource), "adapter-source-delete");
            Blocked(() => Directory.Delete(Path.Combine(root, "production_tools"), true), "adapter-ancestor-delete");
            Blocked(() => File.WriteAllText(entry, "changed"), "entry-source-write");
            Blocked(() => Directory.CreateDirectory(Path.Combine(core, ".git")), "no-second-git");
            Blocked(() => Directory.Delete(core, true), "delete-core");
            Blocked(() => Directory.Move(core, core + "-moved"), "move-core");
            Blocked(() => Process.Start(new ProcessStartInfo("never-executed-fixture.exe")), "child-process-isolation");
            using (var stream = new FileStream(source, FileMode.Open, FileAccess.Read)) Assert(stream.Length == 17, "readonly-source-stream");
            string mutable = Path.Combine(core, "output", "fixture.txt");
            Directory.CreateDirectory(Path.GetDirectoryName(mutable));
            File.WriteAllText(mutable, "mutable fixture");
            Assert(File.ReadAllText(mutable) == "mutable fixture", "output-writes-allowed");
            string external = Path.Combine(Directory.GetParent(root).FullName, "external-fixture.txt");
            File.WriteAllText(external, "copy fixture");
            Blocked(() => File.Copy(external, source, true), "copy-destination-source");
            Blocked(() => File.Move(external, source, true), "move-destination-source");
            Assert(File.ReadAllText(source) == "unchanged fixture", "source-bytes-preserved");
            Console.WriteLine(JsonSerializer.Serialize(new { pass = true, tests = passed, service_started = false }));
            return 0;
        }
        catch (Exception error)
        {
            while (error is TargetInvocationException && error.InnerException != null) error = error.InnerException;
            Console.WriteLine("FAILED " + error.GetType().Name);
            if (error is InvalidOperationException && error.Message.StartsWith("assertion_failed:", StringComparison.Ordinal)) Console.WriteLine(error.Message);
            return 1;
        }
    }
}
