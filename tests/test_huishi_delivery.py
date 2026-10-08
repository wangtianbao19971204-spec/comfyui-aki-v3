"""Synthetic private-packet regressions; no vendor GUI, service, DB or GPU."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "snapshot/runtime/production_tools/huishi_adapter/prepare.py"
spec = importlib.util.spec_from_file_location("tested_huishi_delivery", SOURCE)
delivery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = delivery
spec.loader.exec_module(delivery)


class HuishiDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="huishi-packet-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "runtime"
        self.repo = self.root / "maintenance/comfyui"
        self.sources = self.repo / "snapshot/runtime"
        self.build = self.base / "hook-build"
        self.entry = self.base / "entry-build/绘世启动器.exe"
        self.out = self.base / "new-packet"
        self.vendor = {role: ("fixture-" + role).encode() for role in delivery.VENDOR_FILES}
        self.pins = delivery.VendorPins(**{role: delivery.digest(data) for role, data in self.vendor.items()})
        for role, relative in delivery.VENDOR_FILES.items():
            self.put(self.root / relative, self.vendor[role])
        self.put(self.root / "ComfyUI/main.py", b"before-main\n")
        self.put(self.sources / "ComfyUI/main.py", b"after-main\n")
        for name in ("runtime_start.py", "StartupHook.cs", "NativeGuards.cs", "ProcessPolicy.cs", "Entry.cs"):
            self.put(self.sources / delivery.ADAPTER / name, ("after-" + name).encode())
        self.put(self.build / delivery.HOOK_NAME, b"fixture-hook-build")
        self.put(self.build / "0Harmony.dll", b"fixture-harmony")
        self.put(self.entry, b"fixture-transparent-entry")
        self.build_receipt = {
            "source_sha256": {name: delivery.digest((self.sources / delivery.ADAPTER / name).read_bytes())
                              for name in ("StartupHook.cs", "NativeGuards.cs", "ProcessPolicy.cs")},
            "dependency_sha256": {"0Harmony.dll": delivery.digest(b"fixture-harmony"),
                                  "LibGit2Sharp.dll": self.pins.libgit},
            "assembly_sha256": delivery.digest(b"fixture-hook-build"),
            "runtime_target": "net6.0", "deployed": False}
        self.write_build_receipt()
        self.entry_receipt = {
            "source_sha256": {"Entry.cs": delivery.digest((self.sources / delivery.ADAPTER / "Entry.cs").read_bytes())},
            "executable_sha256": delivery.digest(b"fixture-transparent-entry"),
            "runtime_target": "net48", "deployed": False}
        self.put(self.entry.parent / "build.receipt.json", json.dumps(self.entry_receipt).encode())

    @staticmethod
    def put(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_build_receipt(self):
        self.put(self.build / "build.receipt.json", json.dumps(self.build_receipt).encode())

    def prepare(self, **kwargs):
        return delivery.prepare_packet(self.repo, self.root, self.build, self.entry,
                                       kwargs.pop("output", self.out), _pins=self.pins, **kwargs)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_default_plan_does_not_create_output_or_modify_runtime(self):
        before = self.snapshot()
        receipt = self.prepare()
        self.assertFalse(receipt["prepared"])
        self.assertFalse(receipt["runtime_written"])
        self.assertFalse(self.out.exists())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(receipt["targets"]), 7)

    def test_packet_exact_candidates_rollback_missing_and_private_settings(self):
        before = self.snapshot()
        receipt = self.prepare(write=True)
        self.assertTrue(receipt["prepared"])
        self.assertFalse(receipt["deployed"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual((self.out / "before/绘世启动器.exe").read_bytes(), self.vendor["bootstrap"])
        self.assertEqual((self.out / "after/绘世启动器原版.exe").read_bytes(), self.vendor["bootstrap"])
        self.assertEqual((self.out / "before/ComfyUI/main.py").read_bytes(), b"before-main\n")
        for item in receipt["targets"]:
            relative = item["target"]
            candidate = (self.out / "after" / relative).read_bytes()
            self.assertEqual(delivery.digest(candidate), item["after"]["sha256"])
            self.assertEqual(len(candidate), item["after"]["size"])
            if item["before"]["missing"]:
                self.assertFalse((self.out / "before" / relative).exists())
            else:
                original = (self.out / "before" / relative).read_bytes()
                self.assertEqual(delivery.digest(original), item["before"]["sha256"])
        settings = json.loads((self.out / "after" / delivery.ADAPTER / "entry.local.json").read_bytes())
        self.assertEqual(settings["mode"], "managed")
        self.assertEqual(settings["maintenance_repo"], str(self.repo))
        self.assertEqual(settings["main_sha256"], delivery.digest(b"after-main\n"))
        self.assertTrue(Path(settings["log"]).is_relative_to(self.out))
        self.assertTrue((self.out / "ROLLBACK.md").is_file())

    def test_existing_runtime_start_preserves_exact_rollback_bytes(self):
        self.put(self.root / delivery.ADAPTER / "runtime_start.py", b"previous-helper\r\n")
        self.prepare(write=True)
        self.assertEqual((self.out / "before" / delivery.ADAPTER / "runtime_start.py").read_bytes(),
                         b"previous-helper\r\n")

    def test_default_vendor_pins_cannot_be_overridden_in_cli(self):
        with self.assertRaises(delivery.DeliveryError):
            delivery.prepare_packet(self.repo, self.root, self.build, self.entry, self.out)
        with patch.object(sys, "stderr", io.StringIO()), self.assertRaises(SystemExit) as exit_info:
            delivery.main(["--repository", str(self.repo), "--runtime", str(self.root),
                "--hook-build", str(self.build), "--entry-executable", str(self.entry),
                "--output", str(self.out), "--pins", "fixture"])
        self.assertEqual(exit_info.exception.code, 2)

    def test_vendor_drift_is_rejected_before_output_created(self):
        for role, relative in delivery.VENDOR_FILES.items():
            with self.subTest(role=role):
                self.put(self.root / relative, b"different vendor version")
                with self.assertRaises(delivery.DeliveryError):
                    self.prepare(write=True)
                self.assertFalse(self.out.exists())
                self.put(self.root / relative, self.vendor[role])

    def test_build_source_hash_includes_native_guard(self):
        self.put(self.sources / delivery.ADAPTER / "NativeGuards.cs", b"changed-native-source")
        with self.assertRaisesRegex(delivery.DeliveryError, "sources differ"):
            self.prepare(write=True)
        self.assertFalse(self.out.exists())

    def test_hook_and_harmony_build_drift_are_rejected(self):
        for name in (delivery.HOOK_NAME, "0Harmony.dll"):
            with self.subTest(name=name):
                path = self.build / name
                original = path.read_bytes()
                path.write_bytes(b"changed-binary")
                with self.assertRaises(delivery.DeliveryError):
                    self.prepare(write=True)
                path.write_bytes(original)
        self.assertFalse(self.out.exists())

    def test_entry_build_source_and_executable_drift_are_rejected(self):
        source = self.sources / delivery.ADAPTER / "Entry.cs"
        original = source.read_bytes()
        source.write_bytes(b"changed-entry-source")
        with self.assertRaisesRegex(delivery.DeliveryError, "Entry build source differs"):
            self.prepare(write=True)
        source.write_bytes(original)
        self.entry.write_bytes(b"changed-entry-executable")
        with self.assertRaisesRegex(delivery.DeliveryError, "Entry bytes differ"):
            self.prepare(write=True)
        self.assertFalse(self.out.exists())

    def test_existing_output_is_never_reused_or_deleted(self):
        self.out.mkdir()
        sentinel = self.out / "keep.txt"
        sentinel.write_bytes(b"retained")
        with self.assertRaises(delivery.DeliveryError):
            self.prepare(write=True)
        self.assertEqual(sentinel.read_bytes(), b"retained")

    def test_output_inside_runtime_repository_or_build_is_rejected(self):
        for parent in (self.root, self.repo, self.build):
            with self.subTest(parent=parent):
                with self.assertRaises(delivery.DeliveryError):
                    self.prepare(output=parent / "forbidden-new-packet", write=True)
                self.assertFalse((parent / "forbidden-new-packet").exists())

    def test_preserved_original_or_config_is_refused_without_reading_body(self):
        original_open = Path.open
        forbidden = [self.root / "绘世启动器原版.exe", self.root / delivery.ADAPTER / "entry.local.json"]
        for path in forbidden:
            with self.subTest(path=path):
                self.put(path, b"private-do-not-read")
                def guarded_open(item, *args, **kwargs):
                    if item == path:
                        raise AssertionError("private body was read")
                    return original_open(item, *args, **kwargs)
                with patch.object(Path, "open", guarded_open), self.assertRaises(delivery.DeliveryError):
                    self.prepare(write=True)
                path.unlink()
        self.assertFalse(self.out.exists())

    def test_linked_target_is_rejected(self):
        target = self.root / "ComfyUI/main.py"
        saved = self.base / "saved-main.py"
        target.rename(saved)
        try:
            target.symlink_to(saved)
        except OSError:
            self.skipTest("Symlink creation is not available on this host")
        with self.assertRaises(delivery.DeliveryError):
            self.prepare(write=True)
        self.assertFalse(self.out.exists())

    def test_hardlinked_build_input_is_rejected(self):
        alias = self.base / "hook-hardlink.dll"
        os.link(self.build / delivery.HOOK_NAME, alias)
        with self.assertRaises(delivery.DeliveryError):
            self.prepare(write=True)
        self.assertFalse(self.out.exists())

    def test_repo_layout_and_relative_paths_are_rejected(self):
        with self.assertRaises(delivery.DeliveryError):
            delivery.prepare_packet(self.base, self.root, self.build, self.entry, self.out, _pins=self.pins)
        with self.assertRaises(delivery.DeliveryError):
            delivery.prepare_packet(Path("relative"), self.root, self.build, self.entry, self.out, _pins=self.pins)

    def test_runtime_git_is_rejected_without_reading_its_contents(self):
        git = self.root / "ComfyUI/.git"
        git.mkdir()
        self.put(git / "config", b"private retired config")
        with self.assertRaisesRegex(delivery.DeliveryError, "runtime Git remains"):
            self.prepare(write=True)
        self.assertFalse(self.out.exists())

    def test_drift_between_individual_reads_is_rejected(self):
        original_read = delivery._read
        changed = False
        def drifting_read(path, identities):
            nonlocal changed
            data = original_read(path, identities)
            if path == self.root / "ComfyUI/main.py" and not changed:
                changed = True
                (self.root / "绘世启动器.exe").write_bytes(b"changed-after-vendor-inspection")
            return data
        with patch.object(delivery, "_read", drifting_read), self.assertRaisesRegex(
                delivery.DeliveryError, "changed during packet"):
            self.prepare(write=True)
        self.assertFalse(self.out.exists())

    def test_database_and_auth_files_are_never_read(self):
        secrets = {self.root / "user.db", self.root / "config/auth.json"}
        for path in secrets:
            self.put(path, b"private sentinel")
        original_open = Path.open
        def guarded_open(item, *args, **kwargs):
            if item in secrets:
                raise AssertionError("private state was read")
            return original_open(item, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            receipt = self.prepare(write=True)
        self.assertFalse(receipt["database_read"])
        self.assertFalse(receipt["service_started"])


if __name__ == "__main__":
    unittest.main()
