// Keep the original Huishi GUI with the sole maintenance Git as its read source.
// Managed mode pins the installed vendor build and constrains child invocations;
// isolation mode rejects all child processes. Neither mode creates a runtime Git.
// API guards are not a process sandbox. Build against .NET 6 and Harmony 2.3.3.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using HarmonyLib;
using LibGit2Sharp;

internal class StartupHook
{
    public static void Initialize()
    {
        // The original bootstrap has AssemblyEntryName=Launcher and lacks the
        // GUI dependency graph. Preserve the hook for its actual GUI child.
        if (String.Equals(Assembly.GetEntryAssembly().GetName().Name, "Launcher", StringComparison.Ordinal))
            return;

        // Hooks belong to this GUI process, never to Python, Git, or its tools.
        Environment.SetEnvironmentVariable("DOTNET_STARTUP_HOOKS", null);
        string phase = "dependency-loading";
        try
        {
            if (String.Equals(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_EMPTY_PROBE"), "1", StringComparison.Ordinal))
            {
                // Presence-only A/B: no Harmony, LibGit2Sharp, AdapterCore, Git
                // access, or repository mapping is permitted in this branch.
                HookIsolation.PrepareEmptyCopy();
                HookIsolation.Trace("empty-probe-not-for-production", "StartupHook.present;no-adapter-or-git-access");
                return;
            }
            bool managed = String.Equals(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_MODE"), "managed", StringComparison.Ordinal);
            if (managed || String.Equals(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_INIT_ORIGINAL_FIRST"), "1", StringComparison.Ordinal))
            {
                phase = "original-module-initialization";
                if (managed) HookIsolation.PrepareManaged(); else HookIsolation.PrepareEmptyCopy();
                HookIsolation.Trace("mode", managed ? "managed-original-gui" : "original-module-first-isolation-experiment");
                // The protected GUI module must finish its own initialization
                // before any Harmony or dependency-bearing AdapterCore is touched.
                RuntimeHelpers.RunModuleConstructor(Assembly.GetEntryAssembly().ManifestModule.ModuleHandle);
                HookIsolation.Trace("phase", "original-module-first-complete");
                phase = "dependency-loading-after-original-module";
            }
            // No LibGit2Sharp or Harmony type is referenced by this bootstrap
            // method. Load Harmony before the non-inlined dependency-bearing core.
            string hookDirectory = Path.GetDirectoryName(typeof(StartupHook).Assembly.Location);
            Assembly.LoadFrom(Path.Combine(hookDirectory, "0Harmony.dll"));
            AdapterCore.Initialize();
        }
        catch (Exception ex)
        {
            try { HookIsolation.Trace("fatal-" + phase, ex.GetType().Name); } catch { }
            Console.Error.WriteLine("Huishi adapter dependency loading failed; original GUI was not allowed to continue.");
            Environment.Exit(78);
        }
    }
}

// BCL-only checks intentionally remain separate from AdapterCore: presence-only
// probes and original module initialization must not load Git/Harmony dependencies.
internal static class HookIsolation
{
    private static string LogPath;

    internal static void PrepareManaged()
    {
        string root = LocalPath(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_ROOT"));
        string maintenance = LocalPath(Environment.GetEnvironmentVariable("HUISHI_MAINTENANCE_REPO"));
        if (!String.Equals(maintenance, Path.Combine(root, "maintenance", "comfyui"), StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("adapter_managed_requires_sole_repository");
        RejectLinks(root); RejectLinks(maintenance);
        VerifyHash(Assembly.GetEntryAssembly().Location, "c6b569a1c7f00be362512ed4047a43ff20945baa47d1e2898ccbc052df2bfc2e");
        VerifyHash(Path.Combine(root, ".launcher", "LibGit2Sharp.dll"), "3ca98bc5046b42f8583e1d9265943a9ba791086e81d669a5f271307f8271b143");
        VerifyHash(Path.Combine(root, "ComfyUI", "main.py"), Environment.GetEnvironmentVariable("HUISHI_MAIN_SHA256"));
        VerifyHash(Path.Combine(root, "production_tools", "huishi_adapter", "runtime_start.py"), Environment.GetEnvironmentVariable("HUISHI_RUNTIME_START_SHA256"));
        LogPath = LocalPath(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_LOG"));
        if (Inside(LogPath, root) || !Directory.Exists(Path.GetDirectoryName(LogPath)))
            throw new InvalidOperationException("adapter_managed_log_must_be_external");
        RejectLinks(LogPath);
    }

    private static void VerifyHash(string path, string expected)
    {
        if (expected == null || expected.Length != 64 || expected.Any(c => !Uri.IsHexDigit(c)))
            throw new InvalidOperationException("adapter_required_digest_missing");
        RejectLinks(path);
        using var input = File.OpenRead(path);
        using var sha = SHA256.Create();
        string actual = Convert.ToHexString(sha.ComputeHash(input));
        if (!String.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("adapter_pinned_file_changed");
    }

    internal static void PrepareEmptyCopy()
    {
        string root = LocalPath(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_ROOT"));
        // This is a path-boundary check only. No .git file, object, configuration,
        // or repository is opened by the empty-presence probe.
        string maintenance = LocalPath(Environment.GetEnvironmentVariable("HUISHI_MAINTENANCE_REPO"));
        var maintenanceDirectory = new DirectoryInfo(maintenance).Parent;
        if (maintenanceDirectory == null || maintenanceDirectory.Parent == null
            || !String.Equals(maintenanceDirectory.Name, "maintenance", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("adapter_empty_probe_requires_maintenance_layout");
        string actualRuntime = LocalPath(maintenanceDirectory.Parent.FullName);
        if (Inside(root, actualRuntime) || Inside(actualRuntime, root))
            throw new InvalidOperationException("adapter_empty_probe_runtime_boundary_invalid");
        RejectLinks(root);
        string core = Path.Combine(root, "ComfyUI");
        RejectLinks(core);
        if (!Directory.Exists(core) || !File.Exists(Path.Combine(core, "main.py"))
            || File.Exists(Path.Combine(root, "python", "python.exe"))
            || File.Exists(Path.Combine(root, "python", "pythonw.exe")))
            throw new InvalidOperationException("adapter_empty_probe_service_environment_rejected");
        string models = Path.Combine(core, "models");
        if (Directory.Exists(models))
        {
            RejectLinks(models);
            if (Directory.EnumerateFileSystemEntries(models).Any())
                throw new InvalidOperationException("adapter_empty_probe_model_resources_rejected");
        }
        string configuredLog = Environment.GetEnvironmentVariable("HUISHI_ADAPTER_LOG");
        LogPath = LocalPath(String.IsNullOrEmpty(configuredLog)
            ? Path.Combine(Directory.GetParent(root).FullName, "ComfyUI-local", "validation", "huishi-launcher-adapter.log")
            : configuredLog);
        if (Inside(LogPath, root) || Inside(LogPath, actualRuntime))
            throw new InvalidOperationException("adapter_empty_probe_log_must_be_external");
        RejectLinks(LogPath);
        if (!Directory.Exists(Path.GetDirectoryName(LogPath)))
            throw new InvalidOperationException("adapter_empty_probe_log_parent_missing");
    }

    private static string LocalPath(string value)
    {
        if (String.IsNullOrWhiteSpace(value) || !Path.IsPathFullyQualified(value)
            || value.StartsWith("\\\\", StringComparison.Ordinal) || value.Contains("\0"))
            throw new InvalidOperationException("adapter_empty_probe_requires_local_absolute_paths");
        string result = Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (result.Length <= Path.GetPathRoot(value).TrimEnd(Path.DirectorySeparatorChar).Length)
            throw new InvalidOperationException("adapter_empty_probe_drive_root_rejected");
        return result;
    }

    private static bool Inside(string path, string root)
    {
        return String.Equals(path, root, StringComparison.OrdinalIgnoreCase)
            || path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    private static void RejectLinks(string path)
    {
        string current = path;
        while (!String.IsNullOrEmpty(current))
        {
            if ((File.Exists(current) || Directory.Exists(current))
                && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("adapter_empty_probe_linked_path_rejected");
            current = Path.GetDirectoryName(current);
        }
    }

    internal static void Trace(string operation, string fixedLabel)
    {
        if (LogPath == null) return;
        File.AppendAllText(LogPath, DateTimeOffset.UtcNow.ToString("O") + "\t" + operation + "\t" + fixedLabel + "\n", new UTF8Encoding(false));
    }
}

internal static class AdapterCore
{
    private sealed class CoreMapping { }
    private static readonly object LogLock = new object();
    private static readonly ConditionalWeakTable<Repository, CoreMapping> MappedRepositories =
        new ConditionalWeakTable<Repository, CoreMapping>();
    private static readonly HashSet<MethodBase> Installed = new HashSet<MethodBase>();
    private static string CorePath;
    private static string CoreGitPath;
    private static string MaintenancePath;
    private static string MaintenanceGitPath;
    private static string LogPath;
    private static Repository BaselineRepository;
    private static Commit BaselineCommit;
    private static FieldInfo BranchRepositoryField;
    private static FieldInfo InformationRepositoryField;
    private static string Stage = "configuring";
    private static bool Managed;
    private static string RuntimeRoot;
    private static readonly HashSet<string> ProtectedSources = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    [MethodImpl(MethodImplOptions.NoInlining)]
    public static void Initialize()
    {
        AppDomain.CurrentDomain.UnhandledException += delegate(object sender, UnhandledExceptionEventArgs args)
        {
            try { Log("unhandled-" + Stage, args.ExceptionObject == null ? "null" : args.ExceptionObject.GetType().Name); }
            catch { }
        };
        AppDomain.CurrentDomain.ProcessExit += delegate
        {
            try { Log("process-exit", Stage); } catch { }
        };
        try
        {
            string root = RequiredPath("HUISHI_ADAPTER_ROOT");
            RuntimeRoot = root;
            Managed = String.Equals(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_MODE"), "managed", StringComparison.Ordinal);
            MaintenancePath = RequiredPath("HUISHI_MAINTENANCE_REPO");
            CorePath = Normalize(Path.Combine(root, "ComfyUI"));
            CoreGitPath = Normalize(Path.Combine(CorePath, ".git"));
            MaintenanceGitPath = Normalize(Path.Combine(MaintenancePath, ".git"));
            using (var manifest = JsonDocument.Parse(File.ReadAllText(Path.Combine(MaintenancePath, "snapshot", "manifest.json"))))
                foreach (var row in manifest.RootElement.GetProperty("files").EnumerateArray())
                    if (row.GetProperty("kind").GetString() == "file")
                    {
                        string relative = row.GetProperty("source").GetString();
                        string target = Normalize(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
                        if (!Within(target, root)) throw new InvalidOperationException("adapter_manifest_path_escape");
                        ProtectedSources.Add(target);
                    }
            string configuredLog = Environment.GetEnvironmentVariable("HUISHI_ADAPTER_LOG");
            LogPath = Normalize(string.IsNullOrEmpty(configuredLog)
                ? Path.Combine(Directory.GetParent(root).FullName, "ComfyUI-local", "validation", "huishi-launcher-adapter.log")
                : configuredLog);
            if (Within(LogPath, root) || Within(LogPath, MaintenancePath))
                throw new InvalidOperationException("adapter_log_must_be_external");
            RejectLinks(LogPath);
            if (!Directory.Exists(Path.GetDirectoryName(LogPath)))
                throw new InvalidOperationException("adapter_log_parent_missing");
            if (!Directory.Exists(CorePath) || !File.Exists(Path.Combine(CorePath, "main.py"))
                || !Directory.Exists(MaintenanceGitPath) || Within(MaintenancePath, CorePath)
                || Directory.Exists(CoreGitPath) || File.Exists(CoreGitPath))
                throw new InvalidOperationException("adapter_roots_invalid");
            RejectLinks(CorePath);
            RejectLinks(MaintenanceGitPath);
            bool readProbe = String.Equals(Environment.GetEnvironmentVariable("HUISHI_ADAPTER_READ_PROBE"), "1", StringComparison.Ordinal);
            if (readProbe)
            {
                RequireEmptyIsolationProbe(root);
                Log("mode", "read-probe-not-for-production;git-writes-blocked");
            }
            else
            {
                Log("mode", Managed ? "managed-reviewed-child-contract;git-writes-blocked" : "isolation-all-child-processes-and-git-writes-blocked");
            }

            string baseline = Environment.GetEnvironmentVariable("HUISHI_CORE_BASELINE");
            if (baseline == null || baseline.Length != 40 || baseline.Any(c => !Uri.IsHexDigit(c)))
                throw new InvalidOperationException("adapter_baseline_invalid");
            // Validate a real historical Commit before any constructor mapping is installed.
            BaselineRepository = new Repository(MaintenancePath);
            BaselineCommit = BaselineRepository.Lookup(baseline) as Commit;
            if (BaselineCommit == null || !String.Equals(BaselineCommit.Sha, baseline, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("adapter_baseline_commit_missing");
            // Resolve the values while the owning repository is retained for GUI lifetime.
            string verifiedMessage = BaselineCommit.Message;
            DateTimeOffset verifiedDate = BaselineCommit.Author.When;
            BranchRepositoryField = typeof(Branch).GetField("repo", BindingFlags.Instance | BindingFlags.NonPublic);
            InformationRepositoryField = typeof(RepositoryInformation).GetField("repo", BindingFlags.Instance | BindingFlags.NonPublic);
            if (BranchRepositoryField == null || InformationRepositoryField == null)
                throw new InvalidOperationException("adapter_git_dependency_changed");

            Stage = "installing";
            var harmony = new Harmony("aki.huishi.isolation.git-adapter.v1");
            if (!readProbe)
                InstallProcessGuards(harmony);
            // Even an empty GUI can fetch or modify config merely by opening a
            // page, so read-probe must retain guards on the actual maintenance Git.
            InstallGitWriteGuards(harmony);
            InstallSourceWriteGuards(harmony);
            if (String.Equals(Assembly.GetEntryAssembly().GetName().Name, "StableDiffusionWebUILauncher", StringComparison.Ordinal))
            {
                int nativeCount = NativeGuards.Install(harmony, Assembly.GetEntryAssembly(), ProtectPath, ProtectNativeProcess, Log);
                if (nativeCount != 7) throw new InvalidOperationException("adapter_gui_native_contract_changed");
                if (Managed) InstallAutomaticDependencyGuard(harmony);
            }
            Install(harmony, RequiredMethod(typeof(Repository), "IsValid", typeof(string)), "IsValidPrefix");
            Install(harmony, RequiredMethod(typeof(Repository), "Discover", typeof(string)), "DiscoverPrefix");
            Install(harmony, typeof(Repository).GetConstructor(new[] { typeof(string) }), "ConstructorPrefix", "ConstructorPostfix", "ConstructorFinalizer");
            Install(harmony, typeof(Repository).GetConstructor(new[] { typeof(string), typeof(RepositoryOptions) }), "ConstructorPrefix", "ConstructorPostfix", "ConstructorFinalizer");
            Install(harmony, typeof(Branch).GetProperty("Tip").GetMethod, "BranchTipPrefix");
            Install(harmony, typeof(RepositoryInformation).GetProperty("WorkingDirectory").GetMethod, "WorkingDirectoryPrefix");
            if (!readProbe)
                Install(harmony, RequiredMethod(typeof(Directory), "Exists", typeof(string)), "DirectoryExistsPrefix");
            Stage = "ready";
            if (!Managed) InspectGuiContracts();
            Log("ready", readProbe
                ? "read-probe-not-for-production;baseline-verified;no-bcl-guards;git-writes-blocked"
                : Managed ? "baseline-verified;reviewed-child-contract;git-writes-blocked" : "baseline-verified;all-child-processes-blocked;git-writes-blocked");
        }
        catch (Exception ex)
        {
            FailClosed(ex);
        }
    }

    private static void RequireEmptyIsolationProbe(string root)
    {
        // This diagnostic mode deliberately omits BCL/process guards. It may
        // only observe an empty core copy outside the actual runtime hierarchy.
        var repositoryDirectory = new DirectoryInfo(MaintenancePath);
        var maintenanceDirectory = repositoryDirectory.Parent;
        if (maintenanceDirectory == null || maintenanceDirectory.Parent == null
            || !String.Equals(maintenanceDirectory.Name, "maintenance", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("adapter_probe_requires_registered_maintenance_layout");
        string actualRuntime = Normalize(maintenanceDirectory.Parent.FullName);
        if (Within(root, actualRuntime) || Within(actualRuntime, root)
            || File.Exists(Path.Combine(root, "python", "python.exe"))
            || File.Exists(Path.Combine(root, "python", "pythonw.exe")))
            throw new InvalidOperationException("adapter_probe_requires_empty_isolation_runtime");
        string models = Path.Combine(CorePath, "models");
        if (Directory.Exists(models))
        {
            RejectLinks(models);
            if (Directory.EnumerateFileSystemEntries(models).Any())
                throw new InvalidOperationException("adapter_probe_models_must_be_absent_or_empty");
        }
    }

    private static void FailClosed(Exception ex)
    {
        // Fixed names only: a caught exception message may contain a private path/value.
        try { Log("fatal", ex.GetType().Name); } catch { }
        if (Regex.IsMatch(ex.Message ?? "", "^(native_guard|adapter)_[a-z_]+$"))
            try { Log("fatal-rule", ex.Message); } catch { }
        Console.Error.WriteLine("Huishi adapter initialization failed; original GUI was not allowed to continue.");
        Environment.Exit(78);
    }

    private static string RequiredPath(string name)
    {
        string value = Environment.GetEnvironmentVariable(name);
        if (String.IsNullOrWhiteSpace(value)) throw new InvalidOperationException("adapter_path_missing");
        string path = Normalize(value);
        RejectLinks(path);
        return path;
    }

    private static string Normalize(string path)
    {
        if (String.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path)
            || path.StartsWith("\\\\", StringComparison.Ordinal) || path.Contains("\0"))
            throw new InvalidOperationException("adapter_path_must_be_local_absolute");
        string normalized = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (normalized.Length <= Path.GetPathRoot(path).TrimEnd(Path.DirectorySeparatorChar).Length)
            throw new InvalidOperationException("adapter_drive_root_rejected");
        return normalized;
    }

    private static void RejectLinks(string path)
    {
        string current = path;
        while (!String.IsNullOrEmpty(current))
        {
            // Directory.Exists may be the GUI's virtual .git probe. Attributes
            // remain the physical filesystem authority for link rejection.
            try
            {
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("adapter_linked_path_rejected");
            }
            catch (FileNotFoundException) { }
            catch (DirectoryNotFoundException) { }
            current = Path.GetDirectoryName(current);
        }
    }

    private static bool Within(string path, string root)
    {
        return String.Equals(path, root, StringComparison.OrdinalIgnoreCase)
            || path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
    }

    private static bool IsCore(string path)
    {
        try
        {
            if (String.IsNullOrEmpty(path) || !Path.IsPathFullyQualified(path)) return false;
            string full = Normalize(path);
            return String.Equals(full, CorePath, StringComparison.OrdinalIgnoreCase)
                || String.Equals(full, CoreGitPath, StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private static MethodInfo RequiredMethod(Type type, string name, params Type[] arguments)
    {
        return type.GetMethod(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance,
            null, arguments, null) ?? throw new MissingMethodException(type.FullName, name);
    }

    private static void Install(Harmony harmony, MethodBase target, string prefix, string postfix = null, string finalizer = null)
    {
        if (target == null || target.ContainsGenericParameters) throw new InvalidOperationException("adapter_patch_target_invalid");
        if (!Installed.Add(target)) return;
        var before = prefix == null ? null : new HarmonyMethod(typeof(AdapterCore), prefix);
        var after = postfix == null ? null : new HarmonyMethod(typeof(AdapterCore), postfix);
        var onException = finalizer == null ? null : new HarmonyMethod(typeof(AdapterCore), finalizer);
        if (harmony.Patch(target, prefix: before, postfix: after, finalizer: onException) == null)
            throw new InvalidOperationException("adapter_patch_install_failed");
        Log("patch", target.DeclaringType.FullName + "." + target.Name);
    }

    private static void InstallProcessGuards(Harmony harmony)
    {
        var starts = typeof(Process).GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Where(m => m.Name == "Start").ToArray();
        if (starts.Length == 0) throw new InvalidOperationException("adapter_process_guards_missing");
        foreach (var start in starts) Install(harmony, start, "ProcessStartPrefix");
    }

    private static void InstallGitWriteGuards(Harmony harmony)
    {
        // These types are the pinned 0.28 dependency's source/object/ref/config mutators.
        var types = new HashSet<string>(StringComparer.Ordinal) {
            "Repository", "RepositoryExtensions", "Commands", "Network", "Configuration", "Index",
            "ObjectDatabase", "BranchCollection", "BranchUpdater", "ReferenceCollection", "RemoteCollection",
            "RemoteUpdater", "TagCollection", "NoteCollection", "StashCollection", "SubmoduleCollection",
            "WorktreeCollection", "Worktree", "Rebase", "RebaseOperation", "RebaseOperationImpl", "PackBuilder", "ReflogCollection"
        };
        string[] verbs = { "Add", "Set", "Unset", "Remove", "Update", "Rename", "Delete", "Write", "Move",
            "Commit", "Create", "Init", "Clone", "Checkout", "Fetch", "Pull", "Push", "Reset", "Rebase",
            "Merge", "Revert", "CherryPick", "Apply", "Stage", "Unstage", "Stash", "Prune", "Rewrite", "Abort", "Continue", "Finish", "set_",
            "Clear", "Replace", "Pop", "Lock", "Unlock", "Run", "Start", "CompleteRebase", "NextRebaseStep", "EnsureHasLog", "Pack", "InternalPack", "TryStage", "Archive" };
        int guarded = 0;
        foreach (var type in typeof(Repository).Assembly.GetTypes().Where(t => t.Namespace == "LibGit2Sharp" && types.Contains(t.Name)))
        {
            foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                if (!verbs.Any(v => method.Name.StartsWith(v, StringComparison.Ordinal)) || method.GetMethodBody() == null) continue;
                // Init only assembles read-only configuration handles; Committish
                // resolves a commit expression. Neither writes source or Git state.
                if ((type == typeof(Configuration) && method.Name == "Init")
                    || (type == typeof(RepositoryExtensions)
                        && (method.Name == "Committish" || method.Name == "Committishes"))) continue;
                if (!method.IsGenericMethodDefinition)
                {
                    Install(harmony, method, "GitWritePrefix");
                    guarded++;
                    continue;
                }
                // Configuration accepts only these concrete value types. Git object/ref
                // generic helpers are closed over the concrete dependency classes.
                Type[] closures = type == typeof(Configuration)
                    ? new[] { typeof(string), typeof(bool), typeof(int), typeof(long) }
                    : typeof(Repository).Assembly.GetTypes().Where(t => !t.ContainsGenericParameters
                        && (typeof(GitObject).IsAssignableFrom(t) || typeof(Reference).IsAssignableFrom(t))).ToArray();
                bool closed = false;
                foreach (var closure in closures)
                {
                    MethodInfo concrete;
                    try { concrete = method.MakeGenericMethod(closure); }
                    catch (ArgumentException) { continue; }
                    Install(harmony, concrete, "GitWritePrefix");
                    guarded++;
                    closed = true;
                }
                if (!closed) throw new InvalidOperationException("adapter_generic_write_guard_missing");
            }
        }
        if (guarded == 0) throw new InvalidOperationException("adapter_git_write_guards_missing");
        Log("write-guards", guarded.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    private static bool IsValidPrefix(string __0, ref bool __result)
    {
        if (!IsCore(__0)) return true;
        Log("read-map", "Repository.IsValid");
        __result = true;
        return false;
    }

    private static bool DiscoverPrefix(string __0, ref string __result)
    {
        if (!IsCore(__0)) return true;
        Log("read-map", "Repository.Discover");
        __result = MaintenanceGitPath + Path.DirectorySeparatorChar;
        return false;
    }

    private static void ConstructorPrefix(object[] __args, ref bool __state)
    {
        // Harmony writes __args back after the prefix. Mixing it with ref __0
        // lets a stale __args[0] overwrite the mapped ref argument, so use one
        // mutation channel for both Repository constructors and their chain.
        string supplied = __args.Length > 0 ? __args[0] as string : null;
        __state = IsCore(supplied);
        bool maintenanceInput = false;
        try
        {
            maintenanceInput = supplied != null && String.Equals(Normalize(supplied), MaintenancePath, StringComparison.OrdinalIgnoreCase);
        }
        catch { }
        Log("ctor-input", __state ? "core" : maintenanceInput ? "maintenance-chain" : "other-unmapped");
        if (!__state) return;
        if (__args.Length > 1 && __args[1] is RepositoryOptions options
            && (options.WorkingDirectoryPath != null || options.IndexPath != null || options.Identity != null))
            throw new InvalidOperationException("huishi_adapter_repository_options_blocked");
        Log("read-map", "Repository.ctor");
        __args[0] = MaintenancePath;
        if (!String.Equals(__args[0] as string, MaintenancePath, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("huishi_adapter_constructor_argument_mapping_failed");
        Log("ctor-argument", "maintenance-mapping-staged");
    }

    private static void ConstructorPostfix(Repository __instance, bool __state)
    {
        if (!__state)
        {
            Log("ctor-complete", "unmapped-or-inner-chain");
            return;
        }
        if (__instance == null || !String.Equals(Normalize(__instance.Info.Path), MaintenanceGitPath, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("huishi_adapter_constructor_opened_unexpected_repository");
        MappedRepositories.GetValue(__instance, ignored => new CoreMapping());
        Log("ctor-complete", "maintenance-repository-verified");
    }

    private static Exception ConstructorFinalizer(Exception __exception, MethodBase __originalMethod, bool __state)
    {
        if (__exception == null) return null;
        try
        {
            Log(__state ? "ctor-failed-mapped" : "ctor-failed-unmapped", __exception.GetType().Name);
            Exception inner = __exception.InnerException;
            int depth = 0;
            while (inner != null && depth++ < 4)
            {
                Log("ctor-inner-exception", inner.GetType().Name);
                inner = inner.InnerException;
            }
            var frames = new StackTrace(__exception, false).GetFrames();
            if (frames != null)
            {
                foreach (var frame in frames.Take(12))
                {
                    var method = frame.GetMethod();
                    if (method != null && method.DeclaringType != null
                        && method.DeclaringType.FullName.StartsWith("LibGit2Sharp", StringComparison.Ordinal))
                        Log("ctor-stack-method", method.DeclaringType.FullName + "." + method.Name);
                }
            }
        }
        catch { }
        // Diagnostics never suppress or replace the actual repository failure.
        return __exception;
    }

    private static bool BranchTipPrefix(Branch __instance, ref Commit __result)
    {
        var repository = BranchRepositoryField.GetValue(__instance) as Repository;
        if (repository == null || !MappedRepositories.TryGetValue(repository, out _)) return true;
        Log("read-map", "Branch.Tip.real-core-baseline");
        __result = BaselineCommit;
        return false;
    }

    private static bool WorkingDirectoryPrefix(RepositoryInformation __instance, ref string __result)
    {
        var repository = InformationRepositoryField.GetValue(__instance) as Repository;
        if (repository == null || !MappedRepositories.TryGetValue(repository, out _)) return true;
        __result = CorePath + Path.DirectorySeparatorChar;
        return false;
    }

    private static bool DirectoryExistsPrefix(string __0, ref bool __result)
    {
        try
        {
            if (String.IsNullOrEmpty(__0) || !Path.IsPathFullyQualified(__0)
                || !String.Equals(Normalize(__0), CoreGitPath, StringComparison.OrdinalIgnoreCase)) return true;
            Log("read-map", "Directory.Exists.core-git-probe-only");
            __result = true;
            return false;
        }
        catch { return true; }
    }

    private static void GitWritePrefix(MethodBase __originalMethod)
    {
        Log("blocked-git-write", __originalMethod.DeclaringType.FullName + "." + __originalMethod.Name);
        throw new InvalidOperationException("源码更新请到 maintenance/comfyui 主仓完成分支、测试与 PR；此处为运行目录。版本列表使用已保存的本地资料。");
    }

    private static void InstallSourceWriteGuards(Harmony harmony)
    {
        string[] fileMethods = { "WriteAll", "AppendAll", "Create", "OpenWrite", "Delete", "Move", "Copy", "Replace", "Open", "OpenHandle", "Set", "Encrypt", "Decrypt" };
        foreach (var method in typeof(File).GetMethods(BindingFlags.Public | BindingFlags.Static))
            if (fileMethods.Any(n => method.Name.StartsWith(n, StringComparison.Ordinal)) && method.GetMethodBody() != null)
                Install(harmony, method, "FileWritePrefix");
        foreach (var constructor in typeof(FileStream).GetConstructors())
            if (constructor.GetParameters().FirstOrDefault()?.ParameterType == typeof(string))
                Install(harmony, constructor, "FileStreamPrefix");
        foreach (var method in typeof(Directory).GetMethods(BindingFlags.Public | BindingFlags.Static))
            if ((new[] { "Delete", "Move", "CreateDirectory", "CreateSymbolicLink" }.Contains(method.Name) || method.Name.StartsWith("Set", StringComparison.Ordinal)) && method.GetMethodBody() != null)
                Install(harmony, method, "DirectoryWritePrefix");
        foreach (var type in new[] { typeof(FileInfo), typeof(DirectoryInfo), typeof(FileSystemInfo) })
            foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
                if ((new[] { "Delete", "MoveTo", "Replace", "CopyTo", "Create", "CreateText", "AppendText", "CreateSubdirectory", "CreateAsSymbolicLink", "Open", "OpenWrite", "Encrypt", "Decrypt" }.Contains(method.Name) || method.Name.StartsWith("set_", StringComparison.Ordinal)) && method.GetMethodBody() != null)
                    Install(harmony, method, "FileSystemInfoPrefix");
    }

    private static bool IsProtected(string path, bool directory = false)
    {
        string full = Normalize(Path.GetFullPath(path));
        RejectLinks(full);
        if (full.Substring(Path.GetPathRoot(full).Length).Contains(':')) throw new InvalidOperationException("主仓保护拒绝文件流别名。");
        if (directory && (Within(CorePath, full) || Within(MaintenancePath, full))) return true;
        if (ProtectedSources.Contains(full)) return true;
        string adapter = Path.Combine(RuntimeRoot, "production_tools", "huishi_adapter");
        if (Within(full, adapter) || (directory && Within(adapter, full))) return true;
        if (new[] { "绘世启动器.exe", "绘世启动器原版.exe" }.Any(n => String.Equals(full, Path.Combine(RuntimeRoot, n), StringComparison.OrdinalIgnoreCase))) return true;
        if (Within(full, MaintenancePath)) return true;
        if (Within(full, RuntimeRoot) && full.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar).Any(p => p.Equals(".git", StringComparison.OrdinalIgnoreCase))) return true;
        if (!Within(full, CorePath)) return false;
        string relative = Path.GetRelativePath(CorePath, full).Replace('\\', '/');
        if (new[] { "input", "output", "temp", "user", "models" }.Any(p => relative.Equals(p, StringComparison.OrdinalIgnoreCase) || relative.StartsWith(p + "/", StringComparison.OrdinalIgnoreCase))) return false;
        if (directory) return true;
        string extension = Path.GetExtension(full).ToLowerInvariant();
        return new[] { ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".css", ".scss", ".html", ".dll", ".exe", ".wasm", ".sh", ".bat", ".cmd", ".ps1" }.Contains(extension)
            || new[] { "requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "uv.lock", "setup.cfg", "setup.py", "install.py" }.Contains(Path.GetFileName(full).ToLowerInvariant());
    }

    private static void ProtectPath(string path, bool directory = false)
    {
        if (String.IsNullOrWhiteSpace(path) || !IsProtected(path, directory)) return;
        Log("blocked-source-write", directory ? "directory" : "file");
        throw new InvalidOperationException("此处源码由唯一主仓维护，请先在 maintenance/comfyui 开发、验收，再按范围部署。");
    }

    private static bool WritesStream(object[] args)
    {
        var explicitAccess = args.FirstOrDefault(a => a is FileAccess);
        if (explicitAccess != null) return (FileAccess)explicitAccess != FileAccess.Read;
        var options = args.FirstOrDefault(a => a is FileStreamOptions) as FileStreamOptions;
        if (options != null) return options.Access != FileAccess.Read;
        return true; // FileMode-only Open uses ReadWrite; creation is also a write.
    }

    private static void FileStreamPrefix(object[] __args)
    {
        if (WritesStream(__args)) ProtectPath((string)__args[0]);
    }

    private static void FileWritePrefix(MethodBase __originalMethod, object[] __args)
    {
        string name = __originalMethod.Name;
        if ((name == "Open" || name == "OpenHandle") && !WritesStream(__args)) return;
        if (__args.Length == 0 || !(__args[0] is string)) return;
        if (name == "Copy") { if (__args.Length > 1) ProtectPath(__args[1] as string); return; }
        ProtectPath(__args[0] as string);
        if (name == "Move" || name == "Replace")
            foreach (var path in __args.Skip(1).OfType<string>()) ProtectPath(path);
    }

    private static void DirectoryWritePrefix(MethodBase __originalMethod, object[] __args)
    {
        foreach (string path in __args.OfType<string>())
            if (__originalMethod.Name == "CreateDirectory")
            {
                string full = Path.GetFullPath(path);
                if (Within(full, MaintenancePath) || (Within(full, RuntimeRoot) && full.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar).Any(p => p.Equals(".git", StringComparison.OrdinalIgnoreCase)))) ProtectPath(path, true);
            }
            else ProtectPath(path, true);
    }

    private static void FileSystemInfoPrefix(MethodBase __originalMethod, FileSystemInfo __instance, object[] __args)
    {
        string name = __originalMethod.Name;
        if (name == "Open" && !WritesStream(__args)) return;
        bool directory = __instance is DirectoryInfo;
        if (name != "CopyTo") ProtectPath(__instance.FullName, directory);
        foreach (string target in __args.OfType<string>())
            if (name == "MoveTo" || name == "CopyTo" || name == "Replace" || name == "CreateAsSymbolicLink" || name == "CreateSubdirectory")
                ProtectPath(Path.IsPathFullyQualified(target) ? target : Path.Combine(directory ? __instance.FullName : Environment.CurrentDirectory, target), directory);
    }

    private static void InstallAutomaticDependencyGuard(Harmony harmony)
    {
        // The pinned GUI rewrites requirements.txt during each launch. Defer
        // that automatic maintenance before it touches files or invokes pip.
        var type = Assembly.GetEntryAssembly().GetType("StableDiffusionWebUILauncher.Internal.ObjectAccount", true);
        var method = type.GetMethod("ValidateAndInstallRequirements", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
            null, Type.EmptyTypes, null);
        if (method == null || method.ReturnType != typeof(Task) || method.GetMethodBody() == null)
            throw new InvalidOperationException("adapter_gui_dependency_contract_changed");
        Install(harmony, method, "AutomaticDependenciesPrefix");
    }

    private static bool AutomaticDependenciesPrefix(ref Task __result)
    {
        bool launch = (new StackTrace(false).GetFrames() ?? Array.Empty<StackFrame>()).Any(frame =>
        {
            var caller = frame.GetMethod();
            return caller?.DeclaringType?.Assembly == Assembly.GetEntryAssembly()
                && caller.DeclaringType.FullName == "StableDiffusionWebUILauncher.Internal.ParserProperty+<LaunchAsync>d__16"
                && caller.Name == "MoveNext";
        });
        if (launch)
        {
            Log("automatic-dependency-maintenance-deferred", "use-existing-reviewed-environment");
            __result = Task.CompletedTask;
        }
        else
        {
            Log("blocked-dependency-maintenance", "explicit-or-unknown-entry");
            __result = Task.FromException(new InvalidOperationException("环境安装与源码依赖清单更新请先在 maintenance/comfyui 主仓验收，再按范围实施；启动继续使用已部署环境。"));
        }
        return false;
    }

    private static void InspectGuiContracts()
    {
        // Metadata only: no settings, field values, source bytes or arguments.
        var names = new HashSet<string>(StringComparer.Ordinal) {
            "StartProcess", "ToArgs", "ToEnv", "InstallCoreRequirements",
            "InstallExtensionRequirements", "ValidateAndInstallRequirements", "FetchUpdate"
        };
        foreach (var type in Assembly.GetEntryAssembly().GetTypes())
            foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly))
                if (names.Contains(method.Name))
                {
                    var body = method.GetMethodBody();
                    Log("gui-contract", type.FullName + "." + method.Name + ":" + method.ReturnType.FullName + "(" +
                        String.Join(",", method.GetParameters().Select(p => p.ParameterType.FullName)) + ");il=" +
                        (body == null ? "absent" : body.GetILAsByteArray().Length.ToString()));
                }
    }

    private static void ProcessStartPrefix(MethodBase __originalMethod, object __instance, object[] __args)
    {
        if (Managed)
        {
            var info = __args.OfType<ProcessStartInfo>().FirstOrDefault() ?? (__instance as Process)?.StartInfo;
            bool reviewedPip = info != null && ProcessPolicy.NormalizeManagedPip(info, RuntimeRoot);
            string executable = info?.FileName ?? __args.OfType<string>().FirstOrDefault() ?? "";
            string command = info?.Arguments ?? String.Join(" ", __args.OfType<string>().Skip(1));
            if (info != null && info.ArgumentList.Count != 0) command = ProcessPolicy.QuoteArguments(info.ArgumentList);
            ProtectProcess(executable, command, info?.WorkingDirectory, reviewedPip);
            return;
        }
        // No argument, executable, command line, environment, or credential is logged.
        Log("blocked-child-process", __originalMethod.DeclaringType.FullName + "." + __originalMethod.Name);
        foreach (var frame in (new StackTrace(false).GetFrames() ?? Array.Empty<StackFrame>()).Take(16))
        {
            var method = frame.GetMethod();
            if (method?.DeclaringType?.Assembly == Assembly.GetEntryAssembly())
                Log("child-process-caller", method.DeclaringType.FullName + "." + method.Name);
        }
        throw new InvalidOperationException("huishi_adapter_isolation_child_process_blocked");
    }

    private static void ProtectNativeProcess(string executable, string command, string directory)
    {
        // Opaque native environment blocks are never inspected or trusted for pip.
        ProtectProcess(executable, command, directory, false);
    }

    private static void ProtectProcess(string executable, string command, string directory, bool reviewedPip)
    {
        if (!Managed) throw new InvalidOperationException("huishi_adapter_isolation_child_process_blocked");
        try { ProcessPolicy.Protect(RuntimeRoot, executable, command, directory, reviewedPip); }
        catch (InvalidOperationException)
        {
            Log("blocked-child-process", "unreviewed-invocation");
            throw new InvalidOperationException("此管理命令需走 maintenance/comfyui 主仓验收；绘世保留受控启动和已审查的环境管理命令。");
        }
    }

    private static void Log(string operation, string label)
    {
        if (LogPath == null) return;
        lock (LogLock)
            File.AppendAllText(LogPath, DateTimeOffset.UtcNow.ToString("O") + "\t" + operation + "\t" + label + "\n", new UTF8Encoding(false));
    }
}
