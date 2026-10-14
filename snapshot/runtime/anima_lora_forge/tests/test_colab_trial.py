"""CPU coverage of payload privacy, remote command and archive trust boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import types
import unittest
from unittest import mock
import zipfile

from PIL import Image

SPEC = importlib.util.spec_from_file_location("colab_trial", Path(__file__).resolve().parents[1] / "tools/colab_trial.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


def model_manifest(blocks=28):
    return {"expected_num_blocks": blocks, "files": [
        {"role": role, "path": "models/" + role + ".safetensors", "url": "https://huggingface.co/example/public/resolve/pinned/" + role + ".safetensors", "sha256": "a" * 64}
        for role in ("dit", "vae", "qwen3")
    ]}


class ColabTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.dataset = self.root / "dataset"
        self.sources.mkdir()
        self.dataset.mkdir()
        for relative in ("anima_train_network.py", "train_network.py", "library/anima_utils.py", "library/utils.py", "networks/lora_anima.py", "LICENSE.md"):
            path = self.sources / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# reviewed source\ndef infer_anima_num_blocks():\n    pass\n", encoding="utf-8")
        for relative in trial.CONFIG_FILES - {"configs/t5_old/spiece.model"}:
            path = self.sources / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        self.spiece = self.root / "spiece.model"
        self.spiece.write_bytes(b"pure-sentencepiece-fixture")
        Image.new("RGB", (64, 96), "red").save(self.dataset / "approved.png")
        (self.dataset / "approved.txt").write_text("ni9x26char, adult, fully clothed", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def build(self, name="package", **kwargs):
        return trial.build_package(self.dataset, "ni9x26char", self.root / name, "ni_colab_trial", model_manifest(),
                                   source_root=self.sources, tokenizer_files={"configs/t5_old/spiece.model": self.spiece}, **kwargs)

    def test_payload_contains_only_reviewed_source_pure_files_and_pairs(self):
        private = [".git/config", "cache/auth.json", "library/__pycache__/cache.py", "env/site.py", "models/private.safetensors", "assets/config.json", "tests/secret.py", "private.py.txt"]
        for relative in private:
            path = self.sources / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("PRIVATE_MARKER", encoding="utf-8")
        (self.dataset / "credentials.json").write_text("PRIVATE_MARKER", encoding="utf-8")
        before = {path.name: trial.sha256(path) for path in self.dataset.iterdir()}
        receipt = self.build(steps=75, seed=261012)
        payload = self.root / "package" / receipt["payload"]
        with zipfile.ZipFile(payload) as bundle:
            names = bundle.namelist()
            self.assertIn("trainer/LICENSE.md", names)
            self.assertIn("trainer/configs/t5_old/spiece.model", names)
            self.assertIn("dataset/approved.txt", names)
            self.assertFalse(any("PRIVATE_MARKER" in bundle.read(name).decode("utf-8", errors="ignore") for name in names))
            config = json.loads(bundle.read("trial_config.json"))
            self.assertEqual(config["seed"], 261012)
            self.assertNotIn(str(self.root), bundle.read("trial_config.json").decode())
        self.assertEqual(before, {path.name: trial.sha256(path) for path in self.dataset.iterdir()})
        self.assertFalse(receipt["local_training_started"])
        self.assertFalse(receipt["network_upload_started"])
        manifest = trial.safe_extract_payload(payload, self.root / "extracted", receipt["payload_sha256"])
        self.assertEqual(len(manifest["files"]) + 1, len(names))

    def test_notebook_has_clean_cells_and_no_drive_or_local_paths(self):
        receipt = self.build()
        notebook = json.loads((self.root / "package" / receipt["notebook"]).read_text(encoding="utf-8"))
        self.assertEqual(notebook["nbformat"], 4)
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                compile("".join(cell["source"]), "notebook_cell", "exec")
        source = json.dumps(notebook)
        self.assertNotIn(str(self.root), source)
        self.assertNotIn("drive.mount", source)
        self.assertIn(receipt["payload_sha256"], source)

    def test_venv_success_installs_only_into_target_venv(self):
        venv = Path("/content/anima_trial/ni_colab_trial/venv")
        with mock.patch("subprocess.run") as run:
            python, used_host_pip = trial.create_colab_venv("/usr/bin/python3", venv)
        self.assertEqual(python, venv / "bin/python")
        self.assertFalse(used_host_pip)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["/usr/bin/python3", "-m", "venv", str(venv)])
        self.assertEqual(commands[1][:4], [str(python), "-m", "pip", "--isolated"])
        self.assertIn("https://pypi.org/simple", commands[1])
        self.assertEqual(len(commands), 2)

    def test_ensurepip_failure_bootstraps_target_venv_without_global_install(self):
        venv = Path("/content/anima_trial/ni_colab_trial/venv")
        failure = subprocess.CalledProcessError(1, ["python", "-m", "venv"], stderr="ensurepip unavailable")
        with mock.patch("subprocess.run", side_effect=[failure, None, None]) as run:
            python, used_host_pip = trial.create_colab_venv("/usr/bin/python3", venv)
        self.assertTrue(used_host_pip)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[1], ["/usr/bin/python3", "-m", "venv", "--without-pip", str(venv)])
        self.assertEqual(commands[2][:6], ["/usr/bin/python3", "-m", "pip", "--isolated", "--python", str(python)])
        self.assertIn("https://pypi.org/simple", commands[2])
        self.assertTrue(all(call.kwargs.get("check") for call in run.call_args_list))

    def test_broken_venv_fallback_propagates_failure_without_install(self):
        failure = subprocess.CalledProcessError(1, ["python", "-m", "venv"])
        with mock.patch("subprocess.run", side_effect=[failure, failure]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                trial.create_colab_venv("/usr/bin/python3", Path("/content/anima_trial/trial/venv"))
        self.assertEqual(run.call_count, 2)
        self.assertFalse(any("install" in call.args[0] for call in run.call_args_list))

    def test_remote_command_preserves_baseline_and_has_no_preview(self):
        config = {"run_id": "ni_colab_trial", "steps": 75, "seed": 261012, "qwen_image_vae_2d": False, "models": model_manifest()}
        command = trial.build_training_args(Path("/content/anima_trial/ni_colab_trial"), config)
        self.assertEqual(command[command.index("--seed") + 1], "261012")
        self.assertEqual(command[command.index("--max_train_steps") + 1], "75")
        self.assertEqual(command[command.index("--save_every_n_steps") + 1], "25")
        self.assertEqual(command[command.index("--network_dim") + 1], "32")
        self.assertIn("--save_state_on_train_end", command)
        self.assertIn("--network_train_unet_only", command)
        self.assertNotIn("--qwen_image_vae_2d", command)
        self.assertFalse(any("sample" in value for value in command))
        config["qwen_image_vae_2d"] = True
        self.assertIn("--qwen_image_vae_2d", trial.build_training_args(Path("/content/trial"), config))

    def test_model_depth_is_explicit_for_original_and_29(self):
        for blocks in (28, 40):
            self.assertEqual(trial.validate_model_manifest(model_manifest(blocks))["expected_num_blocks"], blocks)
        with self.assertRaises(ValueError):
            trial.validate_model_manifest(model_manifest(999))

    def test_model_manifest_rejects_private_paths_and_auth(self):
        # Assemble rejected synthetic URLs at runtime; source contains no
        # complete authentication URL or credential-shaped query fixture.
        userinfo_url = "".join(("https://", "user", ":", "password", "@", "huggingface.co/example"))
        query_url = "https://huggingface.co/example?" + "=".join(("token", "private"))
        mutations = [
            ("path", "C:/private/model.safetensors"), ("path", "models/../private.safetensors"),
            ("url", userinfo_url), ("url", query_url),
            ("sha256", "unpinned"), ("role", "unknown"),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                manifest = model_manifest()
                manifest["files"][0][field] = value
                with self.assertRaises(ValueError):
                    trial.validate_model_manifest(manifest)

    def test_missing_or_wrong_caption_stops_before_output(self):
        (self.dataset / "approved.txt").write_text("other, caption", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / "package").exists())

    def test_missing_pure_tokenizer_is_a_hard_error(self):
        with self.assertRaises(ValueError):
            trial.build_package(self.dataset, "ni9x26char", self.root / "package", "ni_colab_trial", model_manifest(), source_root=self.sources)

    def test_duplicate_images_rejected(self):
        (self.dataset / "second.png").write_bytes((self.dataset / "approved.png").read_bytes())
        (self.dataset / "second.txt").write_text("ni9x26char, caption", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build()

    def test_existing_output_not_overwritten(self):
        self.build()
        with self.assertRaises(FileExistsError):
            self.build()

    def malicious_bundle(self, names, content=b"payload", manifest_hash=None, symlink=False):
        archive = self.root / "malicious.zip"
        entries = [{"path": name, "bytes": len(content), "sha256": manifest_hash or hashlib.sha256(content).hexdigest()} for name in names]
        with zipfile.ZipFile(archive, "w") as bundle:
            for name in names:
                info = zipfile.ZipInfo(name)
                if symlink:
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                bundle.writestr(info, content)
            bundle.writestr("payload_manifest.json", json.dumps({"files": entries}))
        return archive

    def test_zip_traversal_rejected_before_writing(self):
        for name in ("../escape", "/absolute", "C:/drive", "folder\\escape", "folder/./name", "folder//name"):
            with self.subTest(name=name):
                archive = self.malicious_bundle([name])
                with self.assertRaises(ValueError):
                    trial.safe_extract_payload(archive, self.root / "extract", trial.sha256(archive))
                self.assertFalse((self.root / "extract").exists())

    def test_zip_symlink_duplicate_and_hash_tampering_rejected(self):
        for names, extra in ((["link"], {"symlink": True}), (["file", "FILE"], {}), (["file"], {"manifest_hash": "b" * 64})):
            archive = self.malicious_bundle(names, **extra)
            with self.assertRaises(ValueError):
                trial.safe_extract_payload(archive, self.root / "extract", trial.sha256(archive))
            self.assertFalse((self.root / "extract").exists())

    def test_wrong_archive_hash_rejected_before_writing(self):
        archive = self.malicious_bundle(["file"])
        with self.assertRaises(ValueError):
            trial.safe_extract_payload(archive, self.root / "extract", "c" * 64)
        self.assertFalse((self.root / "extract").exists())

    def test_checkpoint_header_validation_and_hash(self):
        path = self.root / "valid.safetensors"
        header = json.dumps({"tensor": {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]}, "__metadata__": {"ss_steps": "75"}}).encode()
        path.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
        record = trial.checkpoint_record(path, self.root)
        self.assertEqual(record["tensor_count"], 1)
        self.assertEqual(record["sha256"], trial.sha256(path))
        path.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            trial.checkpoint_record(path, self.root)

    def test_remote_commands_refuse_this_local_workspace(self):
        with self.assertRaises(RuntimeError):
            trial.require_colab(self.root)

    def run_fake_remote_entry(self, finite=True):
        """Exercise actual instrumentation without importing torch or using GPU."""
        counters = {"optimizer": 0, "logging": 0, "synchronize": 0}
        class Optimizer:
            def step(self, *args, **kwargs):
                counters["optimizer"] += 1
                return "original-step-result"
        class Dataset:
            def new_cache_latents(self):
                return "original-cache-result"
        class Trainer:
            def process_batch(self, *args, **kwargs):
                return 0.25
            def cache_text_encoder_outputs_if_needed(self):
                return "original-text-cache-result"
            def step_logging(self, accelerator, values, global_step, epoch):
                counters["logging"] += 1
                return "original-log-result"
            def train(self, args):
                assert Dataset().new_cache_latents() == "original-cache-result"
                assert self.cache_text_encoder_outputs_if_needed() == "original-text-cache-result"
                for step in (1, 2):
                    assert self.process_batch() == 0.25
                    assert Optimizer().step() == "original-step-result"
                    assert self.step_logging(None, {"loss/current": 0.25, "loss/average": 0.25}, step, 1) == "original-log-result"
        def synchronize():
            counters["synchronize"] += 1
        fake_torch = types.ModuleType("torch")
        fake_torch.optim = types.SimpleNamespace(AdamW=Optimizer)
        fake_torch.cuda = types.SimpleNamespace(reset_peak_memory_stats=lambda: None, synchronize=synchronize,
                                               max_memory_allocated=lambda: 100, memory_allocated=lambda: 50)
        fake_torch.set_num_threads = lambda count: None
        fake_torch.isfinite = lambda loss: types.SimpleNamespace(all=lambda: finite)
        fake_entry = types.ModuleType("anima_train_network")
        fake_entry.AnimaNetworkTrainer = Trainer
        fake_entry.setup_parser = lambda: types.SimpleNamespace(parse_args=lambda command: command)
        fake_library = types.ModuleType("library")
        fake_library.train_util = types.SimpleNamespace(DatasetGroup=Dataset, verify_command_line_training_args=lambda args: None,
                                                        read_config_from_file=lambda args, parser: args)
        config = {"run_id": "ni_colab_trial", "steps": 50, "seed": 261012, "qwen_image_vae_2d": False, "models": model_manifest()}
        (self.root / "trial_config.json").write_text(json.dumps(config), encoding="utf-8")
        (self.root / "output").mkdir()
        with mock.patch.object(trial, "require_colab", side_effect=lambda path: path), mock.patch.dict(
                "sys.modules", {"torch": fake_torch, "anima_train_network": fake_entry, "library": fake_library}):
            old_path = list(__import__("sys").path)
            try:
                if finite:
                    trial.remote_entry(self.root)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Non-finite"):
                        trial.remote_entry(self.root)
            finally:
                __import__("sys").path[:] = old_path
        events = [json.loads(line) for line in (self.root / "output/telemetry.jsonl").read_text().splitlines()]
        return counters, events

    def test_gradient_timer_preserves_original_calls_and_records_updates(self):
        counters, events = self.run_fake_remote_entry()
        self.assertEqual(counters, {"optimizer": 2, "logging": 2, "synchronize": 2})
        updates = [event for event in events if event["event"] == "gradient_update"]
        self.assertEqual(len(updates), 2)
        self.assertTrue(all(event["seconds"] >= 0 for event in updates))
        self.assertEqual([event["step"] for event in events if event["event"] == "step"], [1, 2])
        self.assertEqual(len([event for event in events if event["event"] == "latent_cache"]), 1)
        self.assertEqual(len([event for event in events if event["event"] == "text_cache"]), 1)

    def test_nonfinite_loss_stops_before_optimizer_and_preserves_final_event(self):
        counters, events = self.run_fake_remote_entry(finite=False)
        self.assertEqual(counters["optimizer"], 0)
        self.assertEqual(counters["logging"], 0)
        self.assertEqual(events[-1]["event"], "entry_end")


if __name__ == "__main__":
    unittest.main()
