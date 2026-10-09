// Pure policy tests. No process is launched; only child environment dictionaries change.
using System;
using System.Diagnostics;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

public static class ProcessPolicyTests
{
    private static int Checks;
    public static int Main()
    {
        try
        {
            string root = Path.Combine(Path.GetTempPath(), "huishi-policy-fixture");
            string py = Path.Combine(root, "python", "python.exe");
            string main = Path.Combine(root, "ComfyUI", "main.py");
            Allow(root, py, "-V", "python-version");
            Allow(root, py, "--version", "python-long-version");
            string releaseProbe = "import sys,os;os._exit(0 if sys.hexversion&255==240 and sys.maxsize>2**32 else 1)";
            Allow(root, py, ProcessPolicy.QuoteArguments(new[] { "-c", releaseProbe }), "exact-gui-release-probe");
            Deny(root, py, ProcessPolicy.QuoteArguments(new[] { "-c", releaseProbe + ";open('main.py','w')" }), "modified-gui-release-probe");
            string pathProbe = "import sys;sys.stdout.write('\\n'+'\\n'.join(sys.path)+'\\n\\n')";
            Allow(root, py, ProcessPolicy.QuoteArguments(new[] { "-c", pathProbe }), "exact-gui-sys-path-probe");
            Deny(root, py, ProcessPolicy.QuoteArguments(new[] { "-c", pathProbe + ";open('main.py','w')" }), "modified-gui-sys-path-probe");
            Allow(root, py, "-u \"" + main + "\" --port 8188", "main-with-normal-args");
            Allow(root, py, "-U \"" + main + "\"", "legacy-unbuffered-flag-preserved");
            Allow(root, null, "\"" + py + "\" -u \"" + main + "\"", "native-null-app-parsed");
            Allow(root, py, "\"" + py + "\" \"" + main + "\"", "native-argv-zero-removed");
            string comfyDirectory = Path.Combine(root, "ComfyUI");
            ProcessPolicy.Protect(root, py, "-s -u main.py --port 8188", comfyDirectory, false);
            Checks++; Console.WriteLine("check relative-main-bound-to-runtime-cwd");
            DenyWithDirectory(root, py, "./main.py", Path.Combine(root, "python"), "relative-main-wrong-cwd");
            DenyWithDirectory(root, py, "../ComfyUI/main.py", comfyDirectory, "relative-main-traversal");
            Deny(root, py, "-m pip list --format=json", "default-pip-list-rejected");
            Deny(root, py, "-m pip show --files torch", "default-pip-show-rejected");
            Deny(root, py, "-m pip check", "default-pip-check-rejected");
            Deny(root, py, "-m pip freeze --all", "default-pip-freeze-rejected");
            Deny(root, py, "-m pip --version", "default-pip-version-rejected");
            ManagedAllow(root, py, "-m pip list --format=json", "managed-pip-list-json");
            ManagedAllow(root, py, "-m pip show --files torch", "managed-pip-show");
            ManagedAllow(root, py, "-m pip check", "managed-pip-check");
            ManagedAllow(root, py, "-m pip freeze --all", "managed-pip-freeze");
            ManagedAllow(root, py, "-m pip --version", "managed-pip-version");
            ManagedAllow(root, py, "-s -m pip --isolated --disable-pip-version-check list --local", "managed-existing-options-normalized");
            ManagedDeny(root, py, "-m pip install torch", "managed-pip-install-rejected");
            ManagedDeny(root, py, "-m pip uninstall torch", "managed-pip-uninstall-rejected");
            ManagedDeny(root, py, "-m pip list --outdated", "managed-pip-network-outdated-rejected");
            ManagedDeny(root, py, "-m pip list --uptodate", "managed-pip-network-uptodate-rejected");
            ManagedDeny(root, py, "-m pip list --log main.py", "managed-pip-log-write-rejected");
            ManagedDeny(root, py, "-m pip show https://example.invalid/torch", "managed-pip-url-rejected");
            ManagedDeny(root, py, "-m pip list -r requirements.txt", "managed-pip-requirements-rejected");
            string isolatedList = "-I -m pip --isolated --disable-pip-version-check list";
            Deny(root, py, isolatedList, "native-isolated-pip-still-rejected");
            DenyWithDirectory(root, py, isolatedList, comfyDirectory, "reviewed-pip-wrong-cwd", true);
            DenyWithDirectory(root, py, "-m pip list", Path.Combine(root, "python"), "reviewed-pip-missing-isolation", true);
            var argList = new ProcessStartInfo(py) { UseShellExecute = false };
            foreach (string value in new[] { "-m", "pip", "show", "torch" }) argList.ArgumentList.Add(value);
            if (!ProcessPolicy.NormalizeManagedPip(argList, root) || !argList.ArgumentList.SequenceEqual(new[] { "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "show", "torch" }))
                throw new InvalidOperationException("fixture-pip-argument-list-boundary-changed");
            Checks++; Console.WriteLine("check managed-pip-argument-list-normalized");
            var notPip = new ProcessStartInfo(py, "--version") { WorkingDirectory = comfyDirectory };
            if (ProcessPolicy.NormalizeManagedPip(notPip, root) || notPip.Arguments != "--version" || notPip.WorkingDirectory != comfyDirectory)
                throw new InvalidOperationException("fixture-non-pip-mutated");
            Checks++; Console.WriteLine("check non-pip-not-mutated");
            var notBound = new ProcessStartInfo("python.exe", "-m pip list") { WorkingDirectory = comfyDirectory };
            if (ProcessPolicy.NormalizeManagedPip(notBound, root) || notBound.Arguments != "-m pip list" || notBound.WorkingDirectory != comfyDirectory)
                throw new InvalidOperationException("fixture-unbound-python-mutated");
            Checks++; Console.WriteLine("check unbound-python-not-mutated");
            var shellPip = new ProcessStartInfo(py, "-m pip list") { UseShellExecute = true };
            bool shellRejected = false;
            try { ProcessPolicy.NormalizeManagedPip(shellPip, root); } catch (InvalidOperationException) { shellRejected = true; }
            if (!shellRejected || shellPip.Arguments != "-m pip list") throw new InvalidOperationException("fixture-shell-pip-mutated-or-permitted");
            Checks++; Console.WriteLine("check managed-pip-shell-rejected");
            Deny(root, py, "-m pip --isolated install -U torch==2.8.0 numpy>=1.24 --no-deps", "unverified-environment-install-blocked");
            Deny(root, py, "-m pip install package[extra,other]>=1.0,<2.0 --only-binary :all:", "unverified-environment-wheel-install-blocked");
            Deny(root, py, "-m pip uninstall -y old-package", "unverified-environment-uninstall-blocked");
            string gitBin = Path.Combine(root, "git", "mingw64", "bin", "git.exe");
            string gitCmd = Path.Combine(root, "git", "cmd", "git.exe");
            Allow(root, gitBin, "--version", "bundled-git-mingw-version");
            Allow(root, gitCmd, "version", "bundled-git-cmd-version");
            Allow(root, null, "\"" + gitBin + "\" --version", "native-bundled-git-version");
            Deny(root, gitBin, "pull", "bundled-git-update");
            Deny(root, gitCmd, "-C somewhere --version", "bundled-git-version-redirection");
            Deny(root, gitBin, "version --build-options", "bundled-git-extended-command");
            Deny(root, "cmd.exe", "/c git pull", "shell-git");
            Deny(root, "cmd.exe", "/c matsu update", "shell-matsu");
            Deny(root, "pwsh.exe", "-EncodedCommand AA==", "encoded-shell");
            Deny(root, "wscript.exe", "anything.vbs", "script-host");
            Deny(root, "git.exe", "pull", "direct-git");
            Deny(root, "matsu.exe", "update", "direct-matsu");
            Deny(root, "aria2c.exe", "https://example.invalid/model", "unknown-executable");
            Deny(root, "python.exe", "-V", "unbound-python");
            Deny(root, py, "-c \"open('main.py','w')\"", "python-code");
            Deny(root, py, "-m shutil", "arbitrary-python-module");
            Deny(root, py, "\"" + Path.Combine(root, "ComfyUI", "custom_nodes", "install.py") + "\"", "plugin-script");
            Deny(root, py, "-m pip install torch --target \"" + Path.Combine(root, "ComfyUI") + "\"", "pip-target");
            Deny(root, py, "-m pip install torch -twhatever", "pip-short-target");
            Deny(root, py, "-m pip install torch --prefix=anything", "pip-prefix");
            Deny(root, py, "-m pip install torch --root=anything", "pip-root");
            Deny(root, py, "-m pip install git+https://example.invalid/repo", "pip-git-url");
            Deny(root, py, "-m pip install torch@https://example.invalid/a.whl", "pip-direct-reference");
            Deny(root, py, "-m pip install -e .", "pip-editable");
            Deny(root, py, "-m pip install .", "pip-local-path");
            Deny(root, py, "-m pip install -r requirements.txt", "pip-requirements-file");
            Deny(root, py, "-m pip list --log main.py", "pip-read-command-log-output");
            Deny(root, py, "-m pip install torch --python other.exe", "pip-reexec-interpreter");
            Deny(root, py, "-m pip config set global.target somewhere", "pip-config-write");
            Deny(root, py, "-m pip install", "pip-empty-install");
            Deny(root, py, "\"unclosed", "unclosed-quote");
            Deny(root, null, "", "empty-native-process");
            string spacedRoot = Path.Combine(Path.GetTempPath(), "huishi policy fixture");
            string spacedPy = Path.Combine(spacedRoot, "python", "python.exe");
            string spacedMain = Path.Combine(spacedRoot, "ComfyUI", "main.py");
            Allow(spacedRoot, spacedPy, "\"" + spacedPy + "\" -u \"" + spacedMain + "\"", "spaces-native-argv");
            string[] tokens = { "", "import sys; print(sys.version)", "a\"b", "a\\\\b", "path with space\\", "\\\"" };
            var parsed = (List<string>)typeof(ProcessPolicy).GetMethod("Parse", BindingFlags.NonPublic | BindingFlags.Static).Invoke(null, new object[] { ProcessPolicy.QuoteArguments(tokens) });
            if (!parsed.SequenceEqual(tokens)) throw new InvalidOperationException("fixture-argument-boundary-changed");
            Checks++; Console.WriteLine("check argument-list-lossless-roundtrip");
            Allow(spacedRoot, spacedPy, ProcessPolicy.QuoteArguments(new[] { "-s", "-u", spacedMain }), "argument-list-main-preserved");
            Deny(root, py, ProcessPolicy.QuoteArguments(new[] { "-c", "import sys; print(sys.version)" }), "inline-probe-not-implicitly-permitted");
            Console.WriteLine("PASS process-policy checks=" + Checks + ";actual-child-processes=0");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("FAIL process-policy " + error.GetType().Name);
            return 1;
        }
    }

    private static void Allow(string root, string app, string args, string fixedLabel)
    {
        ProcessPolicy.Protect(root, app, args);
        Checks++;
        Console.WriteLine("check " + fixedLabel);
    }

    private static void Deny(string root, string app, string args, string fixedLabel)
    {
        bool rejected = false;
        try { ProcessPolicy.Protect(root, app, args); }
        catch (InvalidOperationException) { rejected = true; }
        if (!rejected) throw new InvalidOperationException("fixture-unexpected-permission");
        Checks++;
        Console.WriteLine("check " + fixedLabel);
    }

    private static void DenyWithDirectory(string root, string app, string args, string directory, string fixedLabel, bool reviewed = false)
    {
        bool rejected = false;
        try { ProcessPolicy.Protect(root, app, args, directory, reviewed); }
        catch (InvalidOperationException) { rejected = true; }
        if (!rejected) throw new InvalidOperationException("fixture-unexpected-directory-permission");
        Checks++; Console.WriteLine("check " + fixedLabel);
    }

    private static void ManagedAllow(string root, string py, string args, string fixedLabel)
    {
        string parentPythonPath = Environment.GetEnvironmentVariable("PYTHONPATH");
        string parentPipConfig = Environment.GetEnvironmentVariable("PIP_CONFIG_FILE");
        var info = new ProcessStartInfo(py, args) { UseShellExecute = false, WorkingDirectory = Path.Combine(root, "ComfyUI") };
        info.Environment["PIP_TARGET"] = "fixture-write-target";
        info.Environment["PIP_CONFIG_FILE"] = "fixture-config";
        info.Environment["PYTHONPATH"] = "fixture-module-target";
        info.Environment["pythonfixture"] = "fixture-python-option";
        info.Environment["HUISHI_TEST_KEEP"] = "fixture-retained";
        if (!ProcessPolicy.NormalizeManagedPip(info, root)) throw new InvalidOperationException("fixture-managed-pip-not-recognized");
        if (info.Arguments != "" || !info.ArgumentList.Take(5).SequenceEqual(new[] { "-I", "-m", "pip", "--isolated", "--disable-pip-version-check" })
            || info.ArgumentList.Count(a => a == "--isolated") != 1 || info.ArgumentList.Count(a => a == "--disable-pip-version-check") != 1
            || info.WorkingDirectory != Path.Combine(root, "python") || info.Environment["PIP_CONFIG_FILE"] != "nul"
            || info.Environment.Keys.Any(key => key.StartsWith("PYTHON", StringComparison.OrdinalIgnoreCase)
                || (key.StartsWith("PIP_", StringComparison.OrdinalIgnoreCase) && key != "PIP_CONFIG_FILE"))
            || info.Environment["HUISHI_TEST_KEEP"] != "fixture-retained")
            throw new InvalidOperationException("fixture-managed-pip-not-isolated");
        if (Environment.GetEnvironmentVariable("PYTHONPATH") != parentPythonPath || Environment.GetEnvironmentVariable("PIP_CONFIG_FILE") != parentPipConfig)
            throw new InvalidOperationException("fixture-parent-environment-changed");
        ProcessPolicy.Protect(root, py, ProcessPolicy.QuoteArguments(info.ArgumentList), info.WorkingDirectory, true);
        Checks++; Console.WriteLine("check " + fixedLabel);
    }

    private static void ManagedDeny(string root, string py, string args, string fixedLabel)
    {
        var info = new ProcessStartInfo(py, args) { UseShellExecute = false, WorkingDirectory = Path.Combine(root, "ComfyUI") };
        info.Environment["PIP_TARGET"] = "fixture-write-target";
        info.Environment["PYTHONPATH"] = "fixture-module-target";
        var before = info.Environment.OrderBy(pair => pair.Key, StringComparer.Ordinal).ToArray();
        bool rejected = false;
        try { ProcessPolicy.NormalizeManagedPip(info, root); } catch (InvalidOperationException) { rejected = true; }
        if (!rejected || info.Arguments != args || info.ArgumentList.Count != 0 || info.WorkingDirectory != Path.Combine(root, "ComfyUI")
            || !before.SequenceEqual(info.Environment.OrderBy(pair => pair.Key, StringComparer.Ordinal)))
            throw new InvalidOperationException("fixture-managed-pip-denial-mutated-or-permitted");
        Checks++; Console.WriteLine("check " + fixedLabel);
    }
}
