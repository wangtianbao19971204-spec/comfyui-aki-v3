import unittest

from mikazuki.utils import train_utils


class TrainUtilsPreviewGateTests(unittest.TestCase):
    def test_disabled_preview_generates_from_strict_preview_signals(self):
        config = {
            "enable_preview": False,
            "positive_prompts": "1girl, solo",
            "negative_prompts": "lowres",
            "sample_width": 1024,
            "sample_height": 1024,
            "sample_cfg": 4.5,
            "sample_seed": 42,
            "sample_steps": 40,
            "sample_sampler": "euler",
            "randomly_choice_prompt": False,
            "sample_at_first": True,
            "sample_every_n_epochs": 1,
            "sample_every_n_steps": 10,
            "prompt_file": "",
            "train_data_dir": "./train",
        }

        train_utils.ensure_enable_preview_flag(config)

        self.assertTrue(train_utils.should_generate_sample_prompts(config))
        self.assertEqual(config["enable_preview"], True)
        self.assertEqual(config["train_data_dir"], "./train")

    def test_disabled_preview_does_not_generate_from_non_signal_preview_fields(self):
        config = {
            "enable_preview": False,
            "sample_sampler": "euler",
            "sample_at_first": True,
            "sample_width": 1024,
            "sample_height": 1024,
            "sample_cfg": 4.5,
            "sample_seed": 42,
            "sample_steps": 40,
            "randomly_choice_prompt": False,
            "prompt_file": "",
            "train_data_dir": "./train",
        }

        self.assertFalse(train_utils.should_generate_sample_prompts(config))
        train_utils.strip_disabled_preview_fields(config)

        for key in train_utils.PREVIEW_UI_FIELDS:
            self.assertNotIn(key, config)
        self.assertEqual(config["enable_preview"], False)
        self.assertEqual(config["train_data_dir"], "./train")

    def test_enabled_preview_generates_from_ui_prompt_fields(self):
        config = {
            "enable_preview": "true",
            "positive_prompts": "1girl, solo",
            "negative_prompts": "lowres",
            "sample_width": 1024,
            "sample_height": 1024,
            "sample_cfg": 4.5,
            "sample_steps": 40,
            "sample_seed": 42,
            "sample_sampler": "euler",
            "train_data_dir": "./train",
        }

        self.assertTrue(train_utils.should_generate_sample_prompts(config))
        line = train_utils.build_sample_prompt_line(
            config["positive_prompts"],
            config["negative_prompts"],
            width=config["sample_width"],
            height=config["sample_height"],
            cfg=config["sample_cfg"],
            steps=config["sample_steps"],
            seed=config["sample_seed"],
            sampler=config["sample_sampler"],
        )
        self.assertIn("--w 1024", line)
        self.assertIn("--h 1024", line)
        self.assertIn("--l 4.5", line)
        self.assertIn("--s 40", line)
        self.assertIn("--d 42", line)
        self.assertIn("--ss euler", line)

    def test_explicit_prompt_file_generates_even_without_preview_toggle(self):
        config = {
            "enable_preview": False,
            "prompt_file": "E:/prompts.txt",
            "train_data_dir": "./train",
        }

        self.assertTrue(train_utils.should_generate_sample_prompts(config))

    def test_explicit_sample_prompts_generates_even_without_preview_toggle(self):
        config = {
            "enable_preview": False,
            "sample_prompts": "E:/prompts.txt",
            "train_data_dir": "./train",
        }

        self.assertTrue(train_utils.should_generate_sample_prompts(config))

    def test_sampling_interval_signal_generates_without_preview_toggle(self):
        for key in ("sample_every_n_epochs", "sample_every_n_steps"):
            with self.subTest(key=key):
                config = {
                    "enable_preview": False,
                    key: 1,
                    "train_data_dir": "./train",
                }

                train_utils.ensure_enable_preview_flag(config)

                self.assertTrue(train_utils.should_generate_sample_prompts(config))
                self.assertEqual(config["enable_preview"], True)

    def test_zero_or_empty_sampling_interval_does_not_enable_preview(self):
        for value in (0, "0", "", None):
            with self.subTest(value=value):
                config = {
                    "enable_preview": False,
                    "sample_every_n_epochs": value,
                    "sample_sampler": "euler",
                }

                train_utils.ensure_enable_preview_flag(config)

                self.assertFalse(train_utils.should_generate_sample_prompts(config))
                self.assertEqual(config["enable_preview"], False)


if __name__ == "__main__":
    unittest.main()
