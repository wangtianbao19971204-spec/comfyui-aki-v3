"""Offline GUI argument-boundary regressions; no GUI, network or GPU process."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
RUNTIME = REPOSITORY / "snapshot/runtime"
ADAPTER = RUNTIME / "production_tools/huishi_adapter/runtime_start.py"
spec = importlib.util.spec_from_file_location("tested_huishi_runtime", ADAPTER)
runtime_start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_start)


class HuishiRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="huishi-runtime-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.names = ["ComfyUI-Unified-Prompt-Workbench", "ComfyUI-Anima-2.9B-loraPatch"]
        self.config = self.root / "production_tools/profiles.json"
        self.config.parent.mkdir()
        self.write_profile(self.names)
        for name in self.names:
            (self.root / "ComfyUI/custom_nodes" / name).mkdir(parents=True)
        self.environment = {runtime_start.PROFILE_ENV: "production", "GUI_DEVICE_SETTING": "kept"}

    def write_profile(self, names):
        self.config.write_text(json.dumps({"production": names}), encoding="utf-8")

    def assert_rejected_without_changes(self, arguments, environment=None):
        environment = dict(self.environment if environment is None else environment)
        before_arguments, before_environment = list(arguments), dict(environment)
        with self.assertRaises(runtime_start.StartupPolicyError):
            runtime_start.apply_gui_profile(self.root, arguments, environment)
        self.assertEqual(arguments, before_arguments)
        self.assertEqual(environment, before_environment)

    def test_unmarked_launch_performs_no_profile_or_root_io(self):
        arguments = ["main.py", "--listen", "0.0.0.0", "--user-directory", "original"]
        environment = {"UNRELATED": "kept"}
        before = list(arguments), dict(environment)
        with patch.object(runtime_start.Path, "read_text", side_effect=AssertionError("profile read")), \
             patch.object(runtime_start.Path, "is_dir", side_effect=AssertionError("root inspected")):
            self.assertFalse(runtime_start.apply_gui_profile("nonexistent", arguments, environment))
        self.assertEqual((arguments, environment), before)

    def test_gui_memory_device_preview_and_future_options_are_preserved(self):
        original = ["main.py", "--reserve-vram", "4", "--preview-method", "auto", "--cuda-malloc",
                    "--cuda-device", "0", "--disable-pinned-memory", "--future-sampling-choice", "value"]
        arguments = list(original)
        self.assertTrue(runtime_start.apply_gui_profile(self.root, arguments, self.environment))
        self.assertEqual(arguments[:len(original)], original)
        self.assertEqual(arguments[len(original):], ["--listen", "127.0.0.1", "--port", "8188",
                         "--disable-auto-launch", "--disable-all-custom-nodes",
                         "--whitelist-custom-nodes", *self.names])
        self.assertEqual(self.environment, {"GUI_DEVICE_SETTING": "kept"})

    def test_equivalent_controlled_arguments_are_normalized_once(self):
        arguments = ["main.py", "--listen=127.0.0.1", "--port", "8188", "--disable-auto-launch",
                     "--disable-all-custom-nodes", "--whitelist-custom-nodes", *reversed(self.names),
                     "--reserve-vram", "4"]
        runtime_start.apply_gui_profile(self.root, arguments, self.environment)
        self.assertEqual(arguments[:3], ["main.py", "--reserve-vram", "4"])
        for flag in runtime_start._CONTROLLED - {"--auto-launch"}:
            self.assertEqual(arguments.count(flag), 1)

    def test_gui_automatic_browser_choice_is_preserved_once(self):
        arguments = ["main.py", "--auto-launch", "--auto-launch", "--preview-method", "auto"]
        runtime_start.apply_gui_profile(self.root, arguments, self.environment)
        self.assertEqual(arguments.count("--auto-launch"), 1)
        self.assertNotIn("--disable-auto-launch", arguments)
        self.assertEqual(arguments[:3], ["main.py", "--preview-method", "auto"])

    def test_nonproduction_or_empty_markers_are_rejected_before_io(self):
        for marker in ["", "legacy", "maintenance", "Production"]:
            with self.subTest(marker=marker), patch.object(runtime_start.Path, "read_text", side_effect=AssertionError("profile read")):
                self.assert_rejected_without_changes(["main.py"], {runtime_start.PROFILE_ENV: marker})

    def test_listen_port_and_auto_launch_conflicts_are_rejected(self):
        for tail in [["--listen"], ["--listen", "0.0.0.0"], ["--listen=::"],
                     ["--port=8190"], ["--port", "invalid"], ["--port"], ["--auto-launch=false"],
                     ["--auto-launch", "--disable-auto-launch"],
                     ["--disable-all-custom-nodes=false"], ["--disable-auto-launch=false"], ["--"]]:
            with self.subTest(tail=tail):
                self.assert_rejected_without_changes(["main.py", *tail])

    def test_structure_and_profile_redirects_are_rejected_in_both_forms(self):
        for flag in runtime_start._REDIRECTS:
            for tail in [[flag, "example"], [flag + "=example"]]:
                with self.subTest(tail=tail):
                    self.assert_rejected_without_changes(["main.py", *tail])

    def test_argparse_abbreviations_cannot_bypass_boundary(self):
        for tail in [["--user-dir", "example"], ["--database", "example"],
                     ["--white", *self.names], ["--enable-man"], ["--lis", "0.0.0.0"]]:
            with self.subTest(tail=tail):
                self.assert_rejected_without_changes(["main.py", *tail])

    def test_plugin_expansion_omission_and_manager_are_rejected(self):
        for tail in [["--whitelist-custom-nodes", *self.names, "ComfyUI-Manager"],
                     ["--whitelist-custom-nodes", self.names[0]], ["--whitelist-custom-nodes"],
                     ["--enable-manager"], ["--enable-manager-legacy-ui"],
                     ["--enable-all-custom-nodes"], ["--disable-whitelist-custom-nodes"]]:
            with self.subTest(tail=tail):
                self.assert_rejected_without_changes(["main.py", *tail])

    def test_bad_profiles_or_missing_plugins_fail_without_partial_changes(self):
        for names in [[], ["../foreign"], ["foreign/name"], ["x", "X"], [1], "not-a-list", ["missing"]]:
            with self.subTest(names=names):
                self.write_profile(names)
                self.assert_rejected_without_changes(["main.py", "--reserve-vram", "4"])
        self.config.write_text("not valid json", encoding="utf-8")
        self.assert_rejected_without_changes(["main.py"])
        self.config.unlink()
        self.assert_rejected_without_changes(["main.py"])

    def test_actual_core_parser_accepts_current_production_and_preserves_gui_values(self):
        names = json.loads((RUNTIME / "production_tools/profiles.json").read_text(encoding="utf-8"))["production"]
        self.write_profile(names)
        for name in names:
            (self.root / "ComfyUI/custom_nodes" / name).mkdir(parents=True, exist_ok=True)
        arguments = ["main.py", "--reserve-vram", "4", "--preview-method", "auto",
                     "--cuda-malloc", "--cuda-device", "0", "--windows-standalone-build"]
        runtime_start.apply_gui_profile(self.root, arguments, self.environment)
        # The actual CLI module has only standard-library dependencies. A tiny
        # options module enables parsing without importing main or GPU code.
        comfy = ModuleType("comfy")
        options = ModuleType("comfy.options")
        options.args_parsing = True
        comfy.options = options
        cli_spec = importlib.util.spec_from_file_location("offline_comfy_cli_args", RUNTIME / "ComfyUI/comfy/cli_args.py")
        cli = importlib.util.module_from_spec(cli_spec)
        with patch.dict(sys.modules, {"comfy": comfy, "comfy.options": options}), patch.object(sys, "argv", arguments):
            cli_spec.loader.exec_module(cli)
        self.assertEqual(cli.args.whitelist_custom_nodes, names)
        self.assertTrue(cli.args.disable_all_custom_nodes)
        self.assertEqual((cli.args.listen, cli.args.port), ("127.0.0.1", 8188))
        self.assertFalse(cli.args.auto_launch)
        self.assertEqual(cli.args.reserve_vram, 4)
        self.assertEqual(cli.args.preview_method.value, "auto")
        self.assertTrue(cli.args.cuda_malloc)
        self.assertEqual(cli.args.cuda_device, "0")
        self.assertIsNone(cli.args.user_directory)
        self.assertIsNone(cli.args.base_directory)

    def _main_prefix(self):
        source = (RUNTIME / "ComfyUI/main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        boundary = next(index for index, node in enumerate(tree.body)
                        if isinstance(node, ast.Import) and any(alias.name == "comfy.options" for alias in node.names))
        self.assertGreater(boundary, 0)
        return compile(ast.Module(body=tree.body[:boundary], type_ignores=[]), "offline-main-prefix", "exec")

    def test_main_injects_profile_before_any_cli_or_gpu_import(self):
        target = self.root / "production_tools/huishi_adapter/runtime_start.py"
        target.parent.mkdir()
        shutil.copyfile(ADAPTER, target)
        arguments = ["main.py", "--reserve-vram", "4"]
        namespace = {"__name__": "__main__", "__file__": str(self.root / "ComfyUI/main.py")}
        with patch.dict(os.environ, self.environment, clear=True), patch.object(sys, "argv", arguments):
            exec(self._main_prefix(), namespace)
            self.assertNotIn(runtime_start.PROFILE_ENV, os.environ)
        self.assertEqual(arguments[:3], ["main.py", "--reserve-vram", "4"])
        self.assertIn("--disable-all-custom-nodes", arguments)

    def test_main_unmarked_does_not_attempt_adapter_import(self):
        namespace = {"__name__": "__main__", "__file__": "missing-main.py"}
        arguments = ["main.py", "--original-option"]
        with patch.dict(os.environ, {"UNRELATED": "kept"}, clear=True), \
             patch.object(sys, "argv", arguments), \
             patch.object(importlib.util, "spec_from_file_location", side_effect=AssertionError("adapter loaded")):
            exec(self._main_prefix(), namespace)
            self.assertEqual(dict(os.environ), {"UNRELATED": "kept"})
        self.assertEqual(arguments, ["main.py", "--original-option"])

    def test_main_check_failure_exits_before_cli_import(self):
        target = self.root / "production_tools/huishi_adapter/runtime_start.py"
        target.parent.mkdir()
        shutil.copyfile(ADAPTER, target)
        namespace = {"__name__": "__main__", "__file__": str(self.root / "ComfyUI/main.py")}
        with patch.dict(os.environ, self.environment, clear=True), \
             patch.object(sys, "argv", ["main.py", "--user-directory", "foreign"]):
            with self.assertRaisesRegex(SystemExit, "绘世受控启动检查失败"):
                exec(self._main_prefix(), namespace)

    def test_main_unexpected_failure_does_not_echo_error_arguments(self):
        target = self.root / "production_tools/huishi_adapter/runtime_start.py"
        target.parent.mkdir()
        target.write_text("raise ValueError('fixture-sensitive-argument-do-not-echo')\n", encoding="utf-8")
        namespace = {"__name__": "__main__", "__file__": str(self.root / "ComfyUI/main.py")}
        with patch.dict(os.environ, self.environment, clear=True), patch.object(sys, "argv", ["main.py"]):
            with self.assertRaises(SystemExit) as captured:
                exec(self._main_prefix(), namespace)
        message = str(captured.exception)
        self.assertIn("ValueError", message)
        self.assertNotIn("fixture-sensitive-argument-do-not-echo", message)

    def test_entry_filters_complete_remote_contract_and_inherited_probe_keys(self):
        compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        if not compiler.is_file():
            self.skipTest("Windows .NET Framework compiler unavailable")
        # Read only the declared remote environment contract; do not import or
        # invoke its wake/heartbeat orchestration or load a private config.
        remote_tree = ast.parse((RUNTIME / "remote_llm_guard/launcher.py").read_text(encoding="utf-8"))
        declaration = next(node for node in remote_tree.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == "ENVIRONMENT_KEYS" for target in node.targets))
        remote_keys = sorted(ast.literal_eval(declaration.value))
        filtered = remote_keys + ["HUISHI_ADAPTER_EMPTY_PROBE", "HUISHI_ADAPTER_READ_PROBE",
                                 "HUISHI_ADAPTER_INIT_ORIGINAL_FIRST", "HUISHI_UNKNOWN_FUTURE_PROBE",
                                 "AKI_HUISHI_PROFILE", "AKI_HUISHI_FUTURE_FLAG", "DOTNET_STARTUP_HOOKS",
                                 "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_PAT", "AWS_SECRET_ACCESS_KEY",
                                 "AWS_ACCESS_KEY_ID", "HTTP_AUTHORIZATION", "APP_COOKIE"]
        retained = ["PATH", "CUDA_VISIBLE_DEVICES", "TOKENIZERS_PARALLELISM", "GUI_DEVICE_SETTING"]
        strings = lambda values: ", ".join(json.dumps(value) for value in values)
        runner = self.root / "EntryEnvironmentProbe.cs"
        runner.write_text("""using System;
using System.Diagnostics;
public static class EntryEnvironmentProbe {
    public static int Main() {
        var start = new ProcessStartInfo(\"never-executed.exe\");
        start.UseShellExecute = false;
        start.EnvironmentVariables.Clear();
        string[] removed = new [] { REMOVED };
        string[] kept = new [] { RETAINED };
        foreach (string key in removed) start.EnvironmentVariables[key] = \"fixture-sensitive-do-not-echo\";
        foreach (string key in kept) start.EnvironmentVariables[key] = \"fixture-kept\";
        start.EnvironmentVariables[\"openai_api_key\"] = \"fixture-sensitive-do-not-echo\";
        Environment.SetEnvironmentVariable(\"HUISHI_UNKNOWN_FUTURE_PROBE\", \"parent-kept\");
        HuishiEntry.SanitizeChildEnvironment(start);
        foreach (string key in removed) if (start.EnvironmentVariables.ContainsKey(key)) return 11;
        foreach (string key in kept) if (start.EnvironmentVariables[key] != \"fixture-kept\") return 12;
        if (start.EnvironmentVariables.ContainsKey(\"openai_api_key\")) return 13;
        if (Environment.GetEnvironmentVariable(\"HUISHI_UNKNOWN_FUTURE_PROBE\") != \"parent-kept\") return 14;
        Console.WriteLine(\"environment-boundary-ok\");
        return 0;
    }
}
""".replace("REMOVED", strings(filtered)).replace("RETAINED", strings(retained)), encoding="utf-8")
        executable = self.root / "EntryEnvironmentProbe.exe"
        flags = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        build = subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64",
                                "/main:EntryEnvironmentProbe", "/reference:System.Web.Extensions.dll",
                                "/reference:System.Windows.Forms.dll", "/out:" + str(executable),
                                str(RUNTIME / "production_tools/huishi_adapter/Entry.cs"), str(runner)],
                               capture_output=True, text=True, timeout=30, **flags)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        probe = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15, **flags)
        self.assertEqual(probe.returncode, 0, "Environment boundary probe failed")
        self.assertEqual(probe.stdout.strip(), "environment-boundary-ok")
        self.assertEqual(probe.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
