// Conservative GUI child-process contract. This validates invocation shapes,
// not the behavior of installed packages; dependency installation is no sandbox.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

public static class ProcessPolicy
{
    // Preserve ArgumentList token boundaries before using the native command-line gate.
    public static string QuoteArguments(IEnumerable<string> arguments)
    {
        var quoted = new List<string>();
        foreach (string argument in arguments)
        {
            if (argument == null || argument.IndexOf('\0') >= 0) Deny();
            var value = new StringBuilder("\"");
            int slashes = 0;
            foreach (char ch in argument)
            {
                if (ch == '\\') { slashes++; continue; }
                value.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
                slashes = 0;
                value.Append(ch);
            }
            value.Append('\\', slashes * 2);
            value.Append('"');
            quoted.Add(value.ToString());
        }
        return String.Join(" ", quoted);
    }
    private static readonly Regex BarePackage = new Regex(@"\A[A-Za-z0-9][A-Za-z0-9._-]*\z", RegexOptions.CultureInvariant);
    private static readonly HashSet<string> Common = new HashSet<string>(StringComparer.Ordinal)
    { "--disable-pip-version-check", "--no-color", "--isolated", "-q", "--quiet", "-v", "--verbose" };

    // Both Process.Start and native CreateProcess must call this before launch.
    // Native command lines may include argv[0]; managed Arguments normally don't.
    public static void Protect(string runtimeRoot, string application, string commandLine)
    {
        Protect(runtimeRoot, application, commandLine, null, false);
    }

    public static void Protect(string runtimeRoot, string application, string commandLine,
                               string workingDirectory, bool reviewedPipEnvironment)
    {
        string root = Absolute(runtimeRoot);
        var args = Parse(commandLine ?? "");
        string executable = Unquote(application);
        if (String.IsNullOrWhiteSpace(executable))
        {
            if (args.Count == 0) Deny();
            executable = args[0];
            args.RemoveAt(0);
        }
        else if (args.Count != 0 && SameAbsolute(args[0], executable)) args.RemoveAt(0);
        // GUI dependency discovery needs the bundled Git version, never a
        // repository/config operation. Keep the exact executable paths bound.
        foreach (string git in new[] { Path.Combine(root, "git", "mingw64", "bin", "git.exe"), Path.Combine(root, "git", "cmd", "git.exe") })
            if (SameAbsolute(executable, git))
            {
                RejectLinks(git);
                if (args.Count == 1 && (args[0] == "--version" || args[0] == "version")) return;
                Deny();
            }
        string python = Path.Combine(root, "python", "python.exe");
        if (!SameAbsolute(executable, python)) Deny();
        RejectLinks(python);
        if (args.Count == 1 && (args[0] == "-V" || args[0] == "--version")) return;
        // Pinned GUI's exact architecture/release probe: only inspect Python's
        // built-in version/word size and exit. No files or environment are read.
        if (args.Count == 2 && args[0] == "-c" && args[1] == "import sys,os;os._exit(0 if sys.hexversion&255==240 and sys.maxsize>2**32 else 1)") return;
        if (args.Count == 2 && args[0] == "-c" && args[1] == "import sys;sys.stdout.write('\\n'+'\\n'.join(sys.path)+'\\n\\n')") return;
        if (args.Count >= 6 && args[0] == "-I" && args[1] == "-m" && args[2] == "pip"
            && args[3] == "--isolated" && args[4] == "--disable-pip-version-check")
        {
            string pipDirectory = Path.Combine(root, "python");
            if (!reviewedPipEnvironment || !SameAbsolute(workingDirectory, pipDirectory)) Deny();
            RejectLinks(pipDirectory);
            ValidatePip(args.Skip(5).ToArray());
            return;
        }
        int start = 0;
        while (start < args.Count && (args[start] == "-u" || args[start] == "-U" || args[start] == "-s" || args[start] == "-B")) start++;
        if (start < args.Count && args[start] == "--") start++;
        if (start >= args.Count) Deny();
        string main = Path.Combine(root, "ComfyUI", "main.py");
        if (SameAbsolute(args[start], main))
        {
            RejectLinks(main);
            return; // runtime_start validates the actual main invocation/options.
        }
        if (args[start] == "main.py" || args[start] == "./main.py" || args[start] == ".\\main.py")
        {
            string directory = String.IsNullOrEmpty(workingDirectory) ? Environment.CurrentDirectory : workingDirectory;
            string comfyDirectory = Path.Combine(root, "ComfyUI");
            if (!SameAbsolute(directory, comfyDirectory)) Deny();
            RejectLinks(comfyDirectory);
            RejectLinks(main);
            return;
        }
        Deny(); // Native/default pip and all other Python entrypoints fail closed.
    }

    // Only this managed path can establish the reviewed pip child environment.
    // No global environment is changed and validation precedes every mutation.
    public static bool NormalizeManagedPip(ProcessStartInfo info, string runtimeRoot)
    {
        if (info == null) return false;
        string root = Absolute(runtimeRoot);
        string python = Path.Combine(root, "python", "python.exe");
        if (!SameAbsolute(Unquote(info.FileName), python)) return false;
        var args = info.ArgumentList.Count != 0 ? info.ArgumentList.ToList() : Parse(info.Arguments ?? "");
        if (info.ArgumentList.Count != 0 && !String.IsNullOrEmpty(info.Arguments)) Deny();
        int start = 0;
        while (start < args.Count && (args[start] == "-u" || args[start] == "-U" || args[start] == "-s" || args[start] == "-B" || args[start] == "-I")) start++;
        if (start < args.Count && args[start] == "--") start++;
        if (start + 1 >= args.Count || args[start] != "-m" || args[start + 1] != "pip") return false;
        if (info.UseShellExecute || !String.IsNullOrEmpty(info.Verb)) Deny();
        RejectLinks(python);
        string directory = Path.Combine(root, "python");
        RejectLinks(directory);
        string[] operation = args.Skip(start + 2)
            .Where(a => a != "--isolated" && a != "--disable-pip-version-check").ToArray();
        ValidatePip(operation);
        var normalized = new[] { "-I", "-m", "pip", "--isolated", "--disable-pip-version-check" }.Concat(operation).ToArray();
        Protect(root, python, QuoteArguments(normalized), directory, true);
        var remove = info.Environment.Keys.Where(key => key.StartsWith("PIP_", StringComparison.OrdinalIgnoreCase)
            || key.StartsWith("PYTHON", StringComparison.OrdinalIgnoreCase)).ToArray();
        info.Arguments = "";
        info.ArgumentList.Clear();
        foreach (string token in normalized) info.ArgumentList.Add(token);
        foreach (string key in remove) info.Environment.Remove(key);
        // pip compares this with Windows os.devnull case-sensitively; use "nul".
        info.Environment["PIP_CONFIG_FILE"] = "nul";
        info.WorkingDirectory = directory;
        return true;
    }

    private static void ValidatePip(string[] args)
    {
        int start = 0;
        while (start < args.Length && Common.Contains(args[start])) start++;
        if (start >= args.Length) Deny();
        string operation = args[start++];
        if (operation == "--version" && start == args.Length) return;
        if (operation == "check")
        {
            if (args.Skip(start).All(a => Common.Contains(a))) return;
            Deny();
        }
        if (operation == "show")
        {
            bool package = false;
            for (int i = start; i < args.Length; i++)
            {
                if (Common.Contains(args[i]) || args[i] == "--files" || args[i] == "-f") continue;
                if (!BarePackage.IsMatch(args[i])) Deny();
                package = true;
            }
            if (package) return;
            Deny();
        }
        if (operation == "list" || operation == "freeze")
        {
            var flags = operation == "list"
                ? new HashSet<string>(new[] { "--editable", "--local", "--user", "--not-required", "--include-editable", "--exclude-editable" }, StringComparer.Ordinal)
                : new HashSet<string>(new[] { "--all", "--local", "--user", "--exclude-editable" }, StringComparer.Ordinal);
            for (int i = start; i < args.Length; i++)
            {
                string arg = args[i];
                if (Common.Contains(arg) || flags.Contains(arg)) continue;
                if (arg == "--exclude")
                {
                    if (++i >= args.Length || !BarePackage.IsMatch(args[i])) Deny();
                    continue;
                }
                if (arg.StartsWith("--exclude=", StringComparison.Ordinal) && BarePackage.IsMatch(arg.Substring(10))) continue;
                if (operation == "list")
                {
                    string format = null;
                    if (arg.StartsWith("--format=", StringComparison.Ordinal)) format = arg.Substring(9);
                    else if (arg == "--format" && ++i < args.Length) format = args[i];
                    if (format == "columns" || format == "freeze" || format == "json") continue;
                }
                Deny();
            }
            return;
        }
        Deny(); // Package mutations, network lookups and unknown flags need separate review.
    }

    private static string Unquote(string value)
    {
        if (value == null) return null;
        value = value.Trim();
        if (value.Length >= 2 && value[0] == '"' && value[value.Length - 1] == '"') value = value.Substring(1, value.Length - 2);
        if (value.IndexOf('"') >= 0 || value.IndexOf('\0') >= 0) Deny();
        return value;
    }

    private static bool SameAbsolute(string left, string right)
    {
        try
        {
            return Path.IsPathFullyQualified(left) && Path.IsPathFullyQualified(right)
                && String.Equals(Absolute(left), Absolute(right), StringComparison.OrdinalIgnoreCase);
        }
        catch (ArgumentException) { return false; }
        catch (NotSupportedException) { return false; }
    }

    private static string Absolute(string value)
    {
        if (String.IsNullOrWhiteSpace(value) || !Path.IsPathFullyQualified(value) || value.StartsWith("\\\\", StringComparison.Ordinal)
            || value.IndexOf('\0') >= 0) Deny();
        string path = Path.GetFullPath(value).TrimEnd('\\', '/');
        if (path.Substring(Path.GetPathRoot(path).Length).IndexOf(':') >= 0) Deny();
        return path;
    }

    private static void RejectLinks(string path)
    {
        while (!String.IsNullOrEmpty(path))
        {
            if ((File.Exists(path) || Directory.Exists(path)) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) Deny();
            path = Path.GetDirectoryName(path);
        }
    }

    // Windows argument quoting, including escaped quotes/backslashes. Shell
    // metacharacters receive no interpretation because shell hosts are refused.
    private static List<string> Parse(string line)
    {
        if (line.Length > 32767 || line.IndexOf('\0') >= 0) Deny();
        var args = new List<string>();
        int i = 0;
        while (i < line.Length)
        {
            while (i < line.Length && Char.IsWhiteSpace(line[i])) i++;
            if (i == line.Length) break;
            var value = new StringBuilder();
            bool quoted = false;
            while (i < line.Length && (quoted || !Char.IsWhiteSpace(line[i])))
            {
                int slash = 0;
                while (i < line.Length && line[i] == '\\') { slash++; i++; }
                if (i < line.Length && line[i] == '"')
                {
                    value.Append('\\', slash / 2);
                    if ((slash & 1) != 0) { value.Append('"'); i++; }
                    else if (quoted && i + 1 < line.Length && line[i + 1] == '"') { value.Append('"'); i += 2; }
                    else { quoted = !quoted; i++; }
                    continue;
                }
                value.Append('\\', slash);
                if (i < line.Length && (quoted || !Char.IsWhiteSpace(line[i]))) value.Append(line[i++]);
            }
            if (quoted) Deny();
            args.Add(value.ToString());
            if (args.Count > 1024) Deny();
        }
        return args;
    }

    private static void Deny()
    {
        throw new InvalidOperationException("huishi_adapter_process_requires_reviewed_runtime_or_environment_command");
    }
}
