"""Verify OlmJoyCaption VRAM pre-eviction, disk-offload guard, and ComfyUI interrupt hooks."""
from __future__ import annotations

import contextlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Olm-JoyCaption/olm_joycaption.py"
)


class InterruptError(RuntimeError):
    pass


def _load_joycaption_with_stubs(
    *,
    free_vram_bytes: int = 2 * (1024 ** 3),
    hf_device_map: dict | None = None,
    interrupt_on_step: int | None = None,
):
    calls = {
        "unload_all_models": 0,
        "soft_empty_cache": 0,
        "cuda_empty_cache": 0,
        "generate_steps": 0,
        "interrupted": False,
    }

    class FakeTensor:
        ndim = 4
        shape = (1, 8, 8, 3)

        def __getitem__(self, _idx):
            return self

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return FakeArray()

        def to(self, *_args, **_kwargs):
            return self

    class FakeArray:
        shape = (8, 8, 3)

        def __mul__(self, _other):
            return self

        def astype(self, _dtype):
            return self

    fake_np = types.ModuleType("numpy")
    fake_np.uint8 = "uint8"
    fake_np.clip = lambda arr, _lo, _hi: arr

    fake_pil = types.ModuleType("PIL")
    fake_pil_image = types.ModuleType("PIL.Image")
    fake_pil_image.Image = object
    fake_pil_image.fromarray = lambda arr, mode="RGB": ("pil", mode)
    fake_pil.Image = fake_pil_image

    fake_torch = types.ModuleType("torch")
    fake_torch.Tensor = FakeTensor
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"
    fake_torch.device = lambda name: f"device:{name}"
    fake_torch.inference_mode = contextlib.nullcontext

    def _cuda_empty():
        calls["cuda_empty_cache"] += 1

    fake_torch.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        empty_cache=_cuda_empty,
    )

    class StoppingCriteria:
        pass

    class StoppingCriteriaList(list):
        pass

    class FakeTokenizer:
        eos_token_id = 2

        def decode(self, token_ids, skip_special_tokens=True):
            return " ".join(f"tok{t}" for t in token_ids)

    class FakeProcessor:
        tokenizer = FakeTokenizer()

        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return cls()

        def apply_chat_template(self, convo, tokenize=False, add_generation_prompt=True):
            return convo[0]["content"]

        def __call__(self, text, images, return_tensors="pt"):
            class InputIds:
                shape = (1, 2)

                def to(self, *_a, **_kw):
                    return self

            return {"input_ids": InputIds(), "pixel_values": FakeTensor()}

    class FakeModel:
        device = "cuda:0"
        dtype = "float16"

        def __init__(self):
            self.hf_device_map = dict(hf_device_map or {"model": 0})

        def cpu(self):
            return self

        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return cls()

        def generate(self, **kwargs):
            criteria = kwargs.get("stopping_criteria") or []
            max_new = kwargs.get("max_new_tokens", 4)
            generated = [10, 11]
            for step in range(1, min(max_new, 5) + 1):
                calls["generate_steps"] += 1
                if interrupt_on_step is not None and step >= interrupt_on_step:
                    calls["interrupted"] = True
                generated.append(100 + step)
                if any(c(generated, None) for c in criteria):
                    break
            return [generated]

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.LlavaForConditionalGeneration = FakeModel
    fake_transformers.AutoProcessor = FakeProcessor
    fake_transformers.BitsAndBytesConfig = lambda **kw: kw
    fake_transformers.StoppingCriteria = StoppingCriteria
    fake_transformers.StoppingCriteriaList = StoppingCriteriaList

    fake_aiohttp = types.ModuleType("aiohttp")
    fake_aiohttp.web = types.SimpleNamespace(json_response=lambda data: data)

    fake_server = types.ModuleType("server")
    fake_server.PromptServer = None

    fake_mm = types.ModuleType("comfy.model_management")
    fake_mm.get_torch_device = lambda: "cuda:0"
    fake_mm.get_free_memory = lambda _dev: free_vram_bytes

    def _unload_all():
        calls["unload_all_models"] += 1

    def _soft_empty():
        calls["soft_empty_cache"] += 1

    def _throw_if_interrupted():
        if calls["interrupted"]:
            raise InterruptError("ComfyUI processing interrupted")

    fake_mm.unload_all_models = _unload_all
    fake_mm.soft_empty_cache = _soft_empty
    fake_mm.processing_interrupted = lambda: calls["interrupted"]
    fake_mm.throw_exception_if_processing_interrupted = _throw_if_interrupted

    fake_comfy = types.ModuleType("comfy")
    fake_comfy.model_management = fake_mm

    stubs = {
        "numpy": fake_np,
        "PIL": fake_pil,
        "PIL.Image": fake_pil_image,
        "torch": fake_torch,
        "transformers": fake_transformers,
        "aiohttp": fake_aiohttp,
        "server": fake_server,
        "comfy": fake_comfy,
        "comfy.model_management": fake_mm,
    }
    spec = importlib.util.spec_from_file_location("_test_olm_joycaption", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module, calls, FakeTensor()


class OlmJoyCaptionGuardTests(unittest.TestCase):
    def test_low_vram_triggers_comfy_model_unload_before_loading(self):
        module, calls, image = _load_joycaption_with_stubs(
            free_vram_bytes=2 * (1024 ** 3),
            hf_device_map={"vision_tower": 0, "language_model": 0},
        )
        node = module.OlmJoyCaption()
        (caption,) = node.run(image=image, prompt="tag this", max_new_tokens=3, unload_after=True)
        self.assertEqual(calls["unload_all_models"], 1)
        self.assertEqual(calls["soft_empty_cache"], 1)
        self.assertIn("tok101", caption)
        self.assertEqual(len(module._MODEL_CACHE), 0)

    def test_disk_offload_device_map_is_rejected_immediately(self):
        module, calls, image = _load_joycaption_with_stubs(
            free_vram_bytes=1 * (1024 ** 3),
            hf_device_map={"vision_tower": 0, "language_model.layers.20": "disk"},
        )
        node = module.OlmJoyCaption()
        with self.assertRaisesRegex(RuntimeError, "磁盘卸载"):
            node.run(image=image, prompt="tag this", max_new_tokens=3)
        self.assertEqual(calls["unload_all_models"], 1)
        self.assertEqual(len(module._MODEL_CACHE), 0)

    def test_comfy_interrupt_stops_generation_early_and_honors_unload_after(self):
        module, calls, image = _load_joycaption_with_stubs(
            free_vram_bytes=24 * (1024 ** 3),
            hf_device_map={"model": 0},
            interrupt_on_step=2,
        )
        node = module.OlmJoyCaption()
        with self.assertRaises(InterruptError):
            node.run(image=image, prompt="tag this", max_new_tokens=10, unload_after=True)
        self.assertEqual(calls["unload_all_models"], 0)
        self.assertEqual(calls["generate_steps"], 2)
        self.assertEqual(len(module._MODEL_CACHE), 0)


if __name__ == "__main__":
    unittest.main()
