from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest
from unittest import mock

import torch

from mikazuki.anima_backend.lycoris_patch import patch_lokr_dora_bf16_forward


class FakeLokrModule:
    def __init__(self):
        self.module_dropout = 0.0
        self.training = True
        self.bypass_mode = False
        self.multiplier = 1
        self.shape = (2, 2)
        self.scalar = torch.tensor(1.0)
        self.wd = True
        self.kw_dict = {}
        self.seen_dtype = None

    def org_forward(self, x, *args, **kwargs):
        return torch.zeros_like(x)

    def _current_weight(self):
        return torch.zeros(2, 2, dtype=torch.bfloat16)

    def get_weight(self, shape):
        return torch.ones(shape, dtype=torch.bfloat16)

    def apply_weight_decompose(self, weight, multiplier):
        return weight.float()

    def op(self, x, delta_weight, bias, **kwargs):
        self.seen_dtype = delta_weight.dtype
        return x @ delta_weight


class AnimaLycorisPatchTests(unittest.TestCase):
    def test_patch_casts_lokr_dora_delta_weight_to_input_dtype(self):
        fake_module = SimpleNamespace(LokrModule=FakeLokrModule)
        with mock.patch("mikazuki.anima_backend.lycoris_patch._lycoris_lora_version", return_value="3.3.0"), \
            mock.patch("importlib.import_module", return_value=fake_module):
            self.assertTrue(patch_lokr_dora_bf16_forward())

        module = FakeLokrModule()
        x = torch.ones(2, 2, dtype=torch.bfloat16)
        y = module.forward(x)

        self.assertEqual(module.seen_dtype, torch.bfloat16)
        self.assertEqual(y.dtype, torch.bfloat16)

    def tearDown(self):
        sys.modules.pop("lycoris.modules.lokr", None)


if __name__ == "__main__":
    unittest.main()
