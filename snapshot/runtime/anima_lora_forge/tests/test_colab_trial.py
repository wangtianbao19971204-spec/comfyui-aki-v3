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

    def extract_package(self, **kwargs):
        receipt = self.build(**kwargs)
        workspace = self.root / receipt["run_id"]
        trial.safe_extract_payload(self.root / "package" / receipt["payload"], workspace, receipt["payload_sha256"])
        return workspace, receipt

    def fake_prepare_output(self, workspace, config):
        output = workspace / "output"
        output.mkdir()
        trial.write_json(output / "trial_config.json", config)
        (workspace / "dataset.toml").write_text("# prepared dataset", encoding="utf-8")
        (output / "dataset.toml").write_bytes((workspace / "dataset.toml").read_bytes())
        trial.write_json(output / "prepare_timing.json", {"dataset_config_sha256": trial.sha256(workspace / "dataset.toml")})
        return output

    def test_calibration_package_freezes400_save100_and_notebook_purpose(self):
        workspace, receipt = self.extract_package(mode="calibration", steps=400, seed=261012)
        config = trial.load_frozen_config(workspace)
        self.assertEqual(config["mode"], "calibration")
        self.assertEqual(config["scope"], "calibration-not-release")
        self.assertEqual(receipt["save_every_n_steps"], 100)
        command = trial.build_training_args(workspace, config)
        self.assertEqual(command[command.index("--max_train_steps") + 1], "400")
        self.assertEqual(command[command.index("--save_every_n_steps") + 1], "100")
        notebook = json.loads((self.root / "package" / receipt["notebook"]).read_text(encoding="utf-8"))
        self.assertIn("100/200/300/400", json.dumps(notebook, ensure_ascii=False))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "calibration_cell", "exec")

    def test_invalid_mode_step_combinations_stop_before_creating_package(self):
        for mode, steps in (("trial", 400), ("calibration", 50), ("calibration", 75), ("formal", 400)):
            with self.subTest(mode=mode, steps=steps):
                with self.assertRaises(ValueError):
                    self.build(mode=mode, steps=steps)
                self.assertFalse((self.root / "package").exists())

    def test_legacy_trial_policy_keeps_scope_and_save25(self):
        legacy = {"steps": 75, "scope": "pipeline-trial-not-release"}
        self.assertEqual(trial.validate_training_policy(legacy)["save_every_n_steps"], 25)
        with self.assertRaises(ValueError):
            trial.validate_training_policy({"mode": "calibration", "steps": 400})
        with self.assertRaises(ValueError):
            trial.validate_training_policy({"mode": "calibration", "steps": 400, "scope": "calibration-not-release", "save_every_n_steps": 25})

    def test_changed_frozen_config_cannot_convert_trial_to_calibration(self):
        workspace, receipt = self.extract_package()
        config_path = workspace / "trial_config.json"
        config = json.loads(config_path.read_text())
        config.update(mode="calibration", steps=400, save_every_n_steps=100, scope="calibration-not-release")
        trial.write_json(config_path, config)
        with self.assertRaisesRegex(ValueError, "Frozen payload input changed"):
            trial.load_frozen_config(workspace)

    def test_changed_dataset_or_run_id_is_rejected(self):
        workspace, receipt = self.extract_package()
        caption = workspace / "dataset/approved.txt"
        caption.write_text("ni9x26char, changed caption", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Frozen payload input changed"):
            trial.load_frozen_config(workspace)
        caption.write_bytes((self.dataset / "approved.txt").read_bytes())
        wrong_workspace = self.root / "different_run_id"
        workspace.rename(wrong_workspace)
        with self.assertRaisesRegex(ValueError, "run IDs differ"):
            trial.load_frozen_config(wrong_workspace)

    def test_prepared_config_change_stops_before_spawning_training(self):
        workspace, receipt = self.extract_package(mode="calibration", steps=400)
        config = trial.load_frozen_config(workspace)
        self.fake_prepare_output(workspace, {**config, "seed": 99})
        with mock.patch.object(trial, "require_colab", side_effect=lambda path: path), mock.patch("subprocess.Popen") as process:
            with self.assertRaisesRegex(ValueError, "Prepared config differs"):
                trial.remote_run(workspace)
        process.assert_not_called()

    def test_prepared_dataset_change_stops_before_spawning_training(self):
        workspace, receipt = self.extract_package(mode="calibration", steps=400)
        self.fake_prepare_output(workspace, trial.load_frozen_config(workspace))
        (workspace / "dataset.toml").write_text("# changed settings", encoding="utf-8")
        with mock.patch.object(trial, "require_colab", side_effect=lambda path: path), mock.patch("subprocess.Popen") as process:
            with self.assertRaisesRegex(ValueError, "dataset configuration changed"):
                trial.remote_run(workspace)
        process.assert_not_called()

    def run_fake_completed_calibration(self, omit_checkpoint=None):
        workspace, receipt = self.extract_package(mode="calibration", steps=400)
        output = self.fake_prepare_output(workspace, trial.load_frozen_config(workspace))
        weights = output / "weights"
        weights.mkdir()
        names = [f"ni_colab_trial-step{step:08d}.safetensors" for step in (100, 200, 300, 400)] + ["ni_colab_trial.safetensors"]
        header = json.dumps({"tensor": {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]}}).encode()
        for name in names:
            if name != omit_checkpoint:
                (weights / name).write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
        events = []
        for step in range(1, 401):
            events.extend(({"event": "step", "step": step, "loss": 0.25}, {"event": "gradient_update", "seconds": 0.5}))
        events.append({"event": "entry_end", "training_seconds": 210, "peak_allocated_vram_bytes": 100})
        (output / "telemetry.jsonl").write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
        process = types.SimpleNamespace(stdout=[], wait=lambda: 0)
        with mock.patch.object(trial, "require_colab", side_effect=lambda path: path), mock.patch("subprocess.Popen", return_value=process), mock.patch("builtins.print"):
            result = trial.remote_run(workspace)
        return result, json.loads((output / "training_receipt.json").read_text())

    def test_calibration_receipt_requires_all_saved_checkpoints(self):
        result, receipt = self.run_fake_completed_calibration("ni_colab_trial-step00000200.safetensors")
        self.assertEqual(result, 2)
        self.assertEqual(receipt["completed_steps"], 400)
        self.assertEqual(receipt["missing_checkpoints"], ["ni_colab_trial-step00000200.safetensors"])

    def test_completed_calibration_retains_quality_gate_and_mode_in_receipt(self):
        result, receipt = self.run_fake_completed_calibration()
        self.assertEqual(result, 0)
        self.assertEqual(receipt["mode"], "calibration")
        self.assertEqual(receipt["save_every_n_steps"], 100)
        self.assertEqual(receipt["checkpoint_count"], 5)
        self.assertEqual(receipt["quality_status"], "not-evaluated-calibration-only")

    def parent_resume_fixture(self, missing_state=None, saved_step=400, change_result_config=False):
        receipt = self.build(name="parent", mode="calibration", steps=400, seed=261012)
        payload = self.root / "parent" / receipt["payload"]
        with zipfile.ZipFile(payload) as bundle:
            config = json.loads(bundle.read("trial_config.json"))
        checkpoint_name = "weights/ni_colab_trial-step00000400.safetensors"
        header = json.dumps({"tensor": {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]},
                             "__metadata__": {"ss_steps": "400"}}).encode()
        checkpoint = struct.pack("<Q", len(header)) + header + b"\x00\x00"
        training = {"run_id": "ni_colab_trial", "return_code": 0, "completed_steps": 400,
                    "optimizer_updates": 400, "loss_observations": 400, "checkpoint_errors": [], "missing_checkpoints": [],
                    "checkpoints": [{"path": checkpoint_name, "sha256": hashlib.sha256(checkpoint).hexdigest(),
                                     "bytes": len(checkpoint), "metadata": {"ss_steps": "400"}}]}
        result_config = dict(config)
        if change_result_config:
            result_config["seed"] += 1
        results = self.root / "parent_results.zip"
        with zipfile.ZipFile(results, "x") as bundle:
            bundle.writestr("trial_config.json", json.dumps(result_config))
            bundle.writestr("training_receipt.json", json.dumps(training))
            bundle.writestr(checkpoint_name, checkpoint)
            for name in sorted(trial.RESUME_STATE_FILES):
                if name == missing_state:
                    continue
                data = json.dumps({"current_epoch": 4, "current_step": saved_step}).encode() if name == "train_state.json" else b"synthetic-owned-state-not-executable"
                bundle.writestr("weights/ni_colab_trial-step00000400-state/" + name, data)
        return {"payload": payload, "payload_digest": trial.sha256(payload), "results": results,
                "results_digest": trial.sha256(results), "step": 400}

    def build_continued(self, inputs, **kwargs):
        return trial.build_package(self.dataset, "ni9x26char", self.root / "continued", "ni_colab_continued", model_manifest(),
                                   source_root=self.sources, tokenizer_files={"configs/t5_old/spiece.model": self.spiece},
                                   mode="continuation", steps=1000, seed=261012, resume_inputs=inputs, **kwargs)

    def test_continuation_freezes_full_state_and_cumulative_target(self):
        inputs = self.parent_resume_fixture()
        (self.sources / "train_network.py").write_text("# reviewed counter fix\n", encoding="utf-8")
        receipt = self.build_continued(inputs)
        self.assertEqual((receipt["starting_step"], receipt["steps"], receipt["expected_new_updates"]), (400, 1000, 600))
        self.assertEqual(receipt["save_every_n_steps"], 200)
        workspace = self.root / "ni_colab_continued"
        trial.safe_extract_payload(self.root / "continued" / receipt["payload"], workspace, receipt["payload_sha256"])
        config = trial.load_frozen_config(workspace)
        command = trial.build_training_args(workspace, config)
        self.assertIn("--resume", command)
        self.assertIn("--skip_until_initial_step", command)
        self.assertNotIn("--initial_step", command)
        self.assertNotIn("--network_weights", command)
        self.assertEqual(command[command.index("--max_train_steps") + 1], "1000")
        self.assertEqual({entry["name"] for entry in config["resume"]["state_files"]}, trial.RESUME_STATE_FILES)
        notebook = json.loads((self.root / "continued" / receipt["notebook"]).read_text(encoding="utf-8"))
        self.assertIn("从400续至1000", str(notebook))
        self.assertIn("600/800/1000", str(notebook))
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "continuation_cell", "exec")

    def test_continuation_without_state_stops_before_package_creation(self):
        with self.assertRaisesRegex(ValueError, "requires approved parent"):
            self.build_continued(None)
        self.assertFalse((self.root / "continued").exists())

    def test_continuation_rejects_archive_digest_change(self):
        inputs = self.parent_resume_fixture()
        inputs["results_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "archive identity"):
            self.build_continued(inputs)
        self.assertFalse((self.root / "continued").exists())

    def test_continuation_requires_rng_and_saved_step(self):
        inputs = self.parent_resume_fixture(missing_state="random_states_0.pkl")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.build_continued(inputs)

    def test_continuation_rejects_wrong_state_step(self):
        inputs = self.parent_resume_fixture(saved_step=399)
        with self.assertRaisesRegex(ValueError, "wrong cumulative step"):
            self.build_continued(inputs)

    def test_continuation_parent_result_config_must_equal_frozen_payload(self):
        inputs = self.parent_resume_fixture(change_result_config=True)
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            self.build_continued(inputs)

    def test_continuation_rejects_changed_caption(self):
        inputs = self.parent_resume_fixture()
        (self.dataset / "approved.txt").write_text("ni9x26char, changed outfit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "preserve source data"):
            self.build_continued(inputs)

    def test_continuation_rejects_unrelated_trainer_change(self):
        inputs = self.parent_resume_fixture()
        (self.sources / "library/utils.py").write_text("# unrelated mutation", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "trainer difference"):
            self.build_continued(inputs)

    def test_continuation_rejects_changed_external_tokenizer(self):
        inputs = self.parent_resume_fixture()
        self.spiece.write_bytes(b"different-tokenizer")
        with self.assertRaisesRegex(ValueError, "tokenizer files differ"):
            self.build_continued(inputs)

    def test_resume_config_rejects_path_traversal_and_source_reuse(self):
        inputs = self.parent_resume_fixture()
        old, manifest, resume, content = trial.collect_resume_inputs(**inputs)
        config = {"run_id": "new_run", **trial.training_policy("continuation", 1000), "resume": resume}
        self.assertEqual(trial.validate_resume_config(config), 400)
        resume["state_dir"] = "resume/../../unrelated"
        with self.assertRaisesRegex(ValueError, "state path"):
            trial.validate_resume_config(config)

    def run_fake_completed_continuation(self, bad_sequence=False, missing_restore=False):
        inputs = self.parent_resume_fixture()
        package = self.build_continued(inputs)
        workspace = self.root / "ni_colab_continued"
        trial.safe_extract_payload(self.root / "continued" / package["payload"], workspace, package["payload_sha256"])
        output = self.fake_prepare_output(workspace, trial.load_frozen_config(workspace))
        weights = output / "weights"
        weights.mkdir()
        header = json.dumps({"tensor": {"dtype": "BF16", "shape": [1], "data_offsets": [0, 2]}}).encode()
        names = [f"ni_colab_continued-step{step:08d}.safetensors" for step in (600, 800, 1000)] + ["ni_colab_continued.safetensors"]
        for name in names:
            (weights / name).write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
        events = [] if missing_restore else [{"event": "resume_loaded", "starting_step": 400, "optimizer_step_min": 400, "optimizer_step_max": 400,
                                             "rng_restore_verified": True, "adamw_momentum_finite": True,
                                             "optimizer_state_count": 560, "scheduler_last_epochs": [400]}]
        sequence = list(range(401, 1001))
        if bad_sequence:
            sequence[0] = 402  # Same count and final label, but duplicate402 and missing401.
        for step in sequence:
            events.extend(({"event": "step", "step": step, "loss": 0.25}, {"event": "gradient_update", "seconds": 0.5}))
        events.append({"event": "entry_end", "training_seconds": 310, "peak_allocated_vram_bytes": 100})
        (output / "telemetry.jsonl").write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
        process = types.SimpleNamespace(stdout=[], wait=lambda: 0)
        with mock.patch.object(trial, "require_colab", side_effect=lambda path: path), mock.patch("subprocess.Popen", return_value=process), mock.patch("builtins.print"):
            result = trial.remote_run(workspace)
        return result, json.loads((output / "training_receipt.json").read_text())

    def test_completed_continuation_counts_only_new_updates(self):
        result, receipt = self.run_fake_completed_continuation()
        self.assertEqual(result, 0)
        self.assertEqual((receipt["completed_steps"], receipt["starting_step"], receipt["optimizer_updates"]), (1000, 400, 600))
        self.assertEqual(receipt["loss_observations"], 600)
        self.assertEqual(receipt["checkpoint_count"], 4)
        self.assertTrue(receipt["resume_verified"])
        self.assertAlmostEqual(receipt["steps_per_second_including_saves"], 600 / 310)

    def test_continuation_rejects_duplicate_step_with_correct_count_and_final_label(self):
        result, receipt = self.run_fake_completed_continuation(bad_sequence=True)
        self.assertEqual(result, 2)
        self.assertFalse(receipt["step_sequence_valid"])

    def test_continuation_rejects_unverified_optimizer_restore(self):
        result, receipt = self.run_fake_completed_continuation(missing_restore=True)
        self.assertEqual(result, 2)
        self.assertFalse(receipt["resume_verified"])

    def restored_optimizer_fixture(self, bad_momentum=False, scheduler_step=400, optimizer_step=400, learning_rate=2e-5):
        class Tensor:
            shape = (2, 3)
            def __init__(self, finite=True):
                self.finite = finite
        parameter = Tensor()
        state = {"step": optimizer_step, "exp_avg": Tensor(not bad_momentum), "exp_avg_sq": Tensor()}
        optimizer = types.SimpleNamespace(param_groups=[{"lr": learning_rate}], state={parameter: state})
        scheduler = types.SimpleNamespace(scheduler=types.SimpleNamespace(last_epoch=scheduler_step))
        accelerator = types.SimpleNamespace(_optimizers=[optimizer], _schedulers=[scheduler])
        torch_api = types.SimpleNamespace(isfinite=lambda value: types.SimpleNamespace(all=lambda: value.finite))
        return accelerator, torch_api

    def test_restore_gate_requires_actual_optimizer_scheduler_and_rng(self):
        accelerator, torch_api = self.restored_optimizer_fixture()
        def loader(accelerator, args):
            import logging
            logging.getLogger("accelerate.checkpointing").info("All random states loaded successfully")
        evidence = trial.restore_training_state(accelerator, None, loader, 400, torch_api, 1)
        self.assertTrue(evidence["rng_restore_verified"])
        self.assertEqual(evidence["scheduler_last_epochs"], [400])

    def test_restore_gate_rejects_accelerate_swallowed_rng_error(self):
        accelerator, torch_api = self.restored_optimizer_fixture()
        def loader(accelerator, args):
            import logging
            logging.getLogger("accelerate.checkpointing").info("Could not load random states")
        with self.assertRaisesRegex(RuntimeError, "Random state restoration failed"):
            trial.restore_training_state(accelerator, None, loader, 400, torch_api, 1)

    def test_restore_gate_rejects_bad_momentum_step_and_scheduler(self):
        def loader(accelerator, args):
            import logging
            logging.getLogger("accelerate.checkpointing").info("All random states loaded successfully")
        for options in ({"bad_momentum": True}, {"scheduler_step": 399}, {"optimizer_step": 0},
                        {"learning_rate": float("nan")}, {"learning_rate": float("inf")}, {"learning_rate": 1e-5}):
            with self.subTest(options=options):
                accelerator, torch_api = self.restored_optimizer_fixture(**options)
                with self.assertRaises(RuntimeError):
                    trial.restore_training_state(accelerator, None, loader, 400, torch_api, 1)

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
        workspace = self.root / "ni_colab_trial"
        workspace.mkdir()
        config_path = workspace / "trial_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        (workspace / "output").mkdir()
        trial.write_json(workspace / "payload_manifest.json", {"schema": 1, "run_id": "ni_colab_trial", "files": [
            {"path": "trial_config.json", "bytes": config_path.stat().st_size, "sha256": trial.sha256(config_path)}]})
        with mock.patch.object(trial, "require_colab", side_effect=lambda path: path), mock.patch.dict(
                "sys.modules", {"torch": fake_torch, "anima_train_network": fake_entry, "library": fake_library}):
            old_path = list(__import__("sys").path)
            try:
                if finite:
                    trial.remote_entry(workspace)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Non-finite"):
                        trial.remote_entry(workspace)
            finally:
                __import__("sys").path[:] = old_path
        events = [json.loads(line) for line in (workspace / "output/telemetry.jsonl").read_text().splitlines()]
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
