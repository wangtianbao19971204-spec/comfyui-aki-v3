from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from character_forge.matrix import build_jobs, stable_seed
from character_forge.workflow import build_prompt_graph, dependency_closure


class MatrixTests(unittest.TestCase):
    def test_seed_is_stable(self) -> None:
        self.assertEqual(stable_seed(10, "job-a"), stable_seed(10, "job-a"))
        self.assertNotEqual(stable_seed(10, "job-a"), stable_seed(10, "job-b"))

    def test_matrix_expands_styles(self) -> None:
        config = {
            "identity": {
                "positive_prompt": "same person",
                "negative_prompt": "wrong person",
            },
            "generation": {
                "quality_prompt": "best quality",
                "negative_prompt": "bad",
                "base_seed": 10,
                "width": 832,
                "height": 1216,
                "default_style": "clean",
                "default_reference_id": "master",
                "reference_strength": 0.5,
                "styles": {
                    "clean": {"prompt": "clean", "tier": "anchor"},
                    "paint": {"prompt": "paint", "tier": "stress"},
                },
                "batches": [
                    {
                        "id": "front",
                        "count": 2,
                        "styles": ["clean", "paint"],
                        "view": "front view",
                    }
                ],
            },
        }
        jobs = build_jobs(config)
        self.assertEqual(len(jobs), 4)
        self.assertTrue(all("same person" in job["positive"] for job in jobs))


class WorkflowTests(unittest.TestCase):
    def test_dependency_closure(self) -> None:
        graph = {
            "1": {"inputs": {}, "class_type": "Source"},
            "2": {"inputs": {"x": ["1", 0]}, "class_type": "Middle"},
            "3": {"inputs": {"x": ["2", 0]}, "class_type": "Output"},
            "99": {"inputs": {}, "class_type": "Unused"},
        }
        result = dependency_closure(graph, "3")
        self.assertEqual(set(result), {"1", "2", "3"})

    def test_prompt_patch_and_reference_injection(self) -> None:
        graph = {
            "2": {"inputs": {"unet_name": "old"}, "class_type": "UNETLoader"},
            "6": {"inputs": {"text": "neg"}, "class_type": "CLIPTextEncode"},
            "107": {"inputs": {"positive": "pos"}, "class_type": "WeiLinPromptUI"},
            "167": {"inputs": {}, "class_type": "ModelSamplingAuraFlow"},
            "384": {"inputs": {"text": ""}, "class_type": "Lora"},
            "385": {"inputs": {"text": ""}, "class_type": "Lora"},
            "390": {"inputs": {"text": ""}, "class_type": "Lora"},
            "510": {
                "inputs": {"input_03": ["167", 0]},
                "class_type": "DazzleSwitch",
            },
            "519": {
                "inputs": {"width": 1, "height": 1},
                "class_type": "EmptyLatentImage",
            },
            "542": {"inputs": {"seed": 1}, "class_type": "easy seed"},
            "12": {"inputs": {}, "class_type": "VAEDecode"},
            "13": {
                "inputs": {"images": ["12", 0]},
                "class_type": "PreviewImage",
            },
        }
        config = {
            "comfyui": {
                "bindings": {
                    "positive": {"node": "107", "input": "positive"},
                    "negative": {"node": "6", "input": "text"},
                    "seed": {"node": "542", "input": "seed"},
                    "width": {"node": "519", "input": "width"},
                    "height": {"node": "519", "input": "height"},
                    "model": {"node": "2", "input": "unet_name"},
                    "lora_anchor": {"node": "384", "input": "text"},
                    "lora_style": {"node": "385", "input": "text"},
                    "lora_character": {"node": "390", "input": "text"},
                    "output": {"node": "13"},
                },
                "reference_control": {
                    "model_source_node": "167",
                    "switch_node": "510",
                    "lllite_name": "ref.safetensors",
                },
            },
            "generation": {
                "unet_name": "new",
                "anchor_loras": "a",
                "character_loras": "c",
                "styles": {"clean": {"loras": "s"}},
            },
        }
        job = {
            "positive": "new pos",
            "negative": "new neg",
            "seed": 123,
            "width": 832,
            "height": 1216,
            "style_id": "clean",
            "reference_strength": 0.5,
        }
        with tempfile.TemporaryDirectory() as folder:
            template = Path(folder) / "template.json"
            template.write_text(
                json.dumps({"graph": graph}),
                encoding="utf-8",
            )
            result = build_prompt_graph(
                template,
                config,
                job,
                filename_prefix="test/out",
                reference_filename="refs/master.png",
            )
        self.assertEqual(result["107"]["inputs"]["positive"], "new pos")
        self.assertEqual(result["13"]["class_type"], "SaveImage")
        self.assertEqual(result["510"]["inputs"]["input_02"], ["900003", 0])
        self.assertEqual(result["900003"]["class_type"], "AnimaLLLiteApply")


if __name__ == "__main__":
    unittest.main()
