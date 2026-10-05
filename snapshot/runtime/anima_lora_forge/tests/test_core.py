from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from anima_lora_forge.core import (
    build_training_command,
    render_dataset_config,
    render_sd_trainer_job,
    scan_dataset,
)


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f00010401009b8c7f380000000049454e44"
    "ae426082"
)


class DatasetTests(unittest.TestCase):
    def test_scan_accepts_paired_triggered_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.png").write_bytes(PNG_1X1)
            (root / "one.txt").write_text(
                "rsrs_anima, red dress, standing", encoding="utf-8"
            )
            report = scan_dataset(root, "rsrs_anima")
        self.assertEqual(report["image_count"], 1)
        self.assertEqual(report["paired_count"], 1)
        self.assertEqual(report["missing_captions"], [])
        self.assertEqual(report["trigger_missing"], [])

    def test_scan_reports_missing_caption(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "one.png").write_bytes(PNG_1X1)
            report = scan_dataset(root, "trigger")
        self.assertEqual(report["missing_captions"], ["one"])


class ConfigTests(unittest.TestCase):
    def profile(self, root: Path) -> dict:
        return {
            "_project_root": str(root),
            "project_id": "test",
            "character_id": "test",
            "trigger_token": "token",
            "dataset_dir": "dataset",
            "models": {
                "dit": "dit.safetensors",
                "vae": "vae.safetensors",
                "text_encoder": "text.safetensors",
            },
            "trainer": {
                "root": "trainer",
                "script": "anima_train_network.py",
                "accelerate": ".venv/Scripts/accelerate.exe",
            },
            "training": {
                "network_dim": 32,
                "network_alpha": 16,
                "learning_rate": "2e-5",
                "optimizer_type": "AdamW",
                "lr_scheduler": "constant",
                "timestep_sampling": "sigmoid",
                "discrete_flow_shift": 1.0,
                "max_train_steps": 1000,
                "save_every_n_steps": 200,
                "resolution": 1024,
                "batch_size": 1,
            },
        }

    def test_dataset_config_preserves_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            text = render_dataset_config(self.profile(Path(folder)))
        self.assertIn("enable_bucket = true", text)
        self.assertIn("resolution = 1024", text)
        self.assertIn("num_repeats = 1", text)

    def test_command_freezes_to_unet_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = build_training_command(
                self.profile(root),
                root / "dataset.toml",
                root / "weights",
            )
        self.assertIn("networks.lora_anima", command)
        self.assertIn("--network_train_unet_only", command)
        self.assertIn("--pretrained_model_name_or_path", command)
        self.assertIn("--qwen3", command)
        self.assertIn("--vae", command)
        self.assertNotIn("--dit_path", command)
        self.assertIn("2e-5", command)
        self.assertIn("AdamW", command)
        self.assertIn("constant", command)

    def test_sd_trainer_learning_rate_is_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            job = render_sd_trainer_job(
                self.profile(root),
                root / "dataset",
                root / "weights",
                root / "logs",
            )
        self.assertIsInstance(job["learning_rate"], float)
        self.assertEqual(job["learning_rate"], 2e-5)

    def test_sd_trainer_disabled_preview_omits_sampling_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = self.profile(root)
            profile["evaluation"] = {
                "enable_preview": False,
                "preview_prompt": "must not leak",
                "sample_every_n_steps": 100,
            }
            job = render_sd_trainer_job(
                profile,
                root / "dataset",
                root / "weights",
                root / "logs",
            )
        self.assertFalse(job["enable_preview"])
        self.assertNotIn("positive_prompts", job)
        self.assertNotIn("sample_at_first", job)
        self.assertNotIn("sample_every_n_steps", job)

    def test_sd_trainer_enabled_preview_keeps_sampling_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = self.profile(root)
            profile["evaluation"] = {
                "enable_preview": True,
                "preview_prompt": "safe preview",
                "sample_every_n_steps": 100,
            }
            job = render_sd_trainer_job(
                profile,
                root / "dataset",
                root / "weights",
                root / "logs",
            )
        self.assertTrue(job["enable_preview"])
        self.assertEqual(job["positive_prompts"], "safe preview")
        self.assertTrue(job["sample_at_first"])
        self.assertEqual(job["sample_every_n_steps"], 100)


if __name__ == "__main__":
    unittest.main()
