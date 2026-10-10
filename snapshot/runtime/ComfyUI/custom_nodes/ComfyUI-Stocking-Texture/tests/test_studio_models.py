"""Inference cache and GPU admission contracts; no weights or CUDA needed."""
import importlib
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import numpy as np
import torch

from test_nodes import PLUGIN

models = importlib.import_module(PLUGIN.__name__ + ".studio_models")


class FakeModel:
    def __init__(self):
        self.moves = []

    def eval(self):
        return self

    def cpu(self):
        return self.to("cpu")

    def to(self, device):
        self.moves.append(str(device))
        return self


class FakePredictor:
    encodes = 0

    def __init__(self, model):
        self.model = model
        self.is_image_set = False

    def set_image(self, art):
        type(self).encodes += 1
        self.features = torch.from_numpy(art.copy())
        self.original_size = self.input_size = art.shape[:2]
        self.is_image_set = True

    def predict(self, **kwargs):
        assert self.is_image_set
        base = self.features.numpy()[..., 0] > 0
        y, x = np.indices(self.original_size)
        return np.array([base | (x < 3), base, base | (x < 2)]), np.array([.8, .6, .7]), None


class CacheContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoint = Path(self.temp.name) / "sam.pth"
        self.checkpoint.write_bytes(b"test weights")
        self.paths = {"sam": self.checkpoint}
        models._sam_cache.clear()
        models._embeddings.clear()
        self.addCleanup(models._sam_cache.clear)
        self.addCleanup(models._embeddings.clear)
        FakePredictor.encodes = 0
        self.loader = mock.Mock(side_effect=lambda **kw: FakeModel())
        module = types.SimpleNamespace(SamPredictor=FakePredictor, sam_model_registry={"vit_b": self.loader})
        patch = mock.patch.dict(sys.modules, segment_anything=module)
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(models, "_device", return_value=torch.device("cpu"))
        patch.start(); self.addCleanup(patch.stop)

    def click(self, art):
        info = {}
        masks, scores = models.segment(art, 1, 1, self.paths, info=info)
        return masks, scores, info

    def test_repeat_image_reuses_cpu_features_and_keeps_candidate_order(self):
        art = np.zeros((8, 8, 3), np.uint8)
        one, scores, first = self.click(art)
        two, _, second = self.click(art.copy())
        self.assertEqual(FakePredictor.encodes, 1)
        self.assertEqual(self.loader.call_count, 1)
        self.assertFalse(first["embedding_cached"])
        self.assertTrue(second["embedding_cached"])
        self.assertTrue(second["model_cached"])
        self.assertEqual(second["backend"], "cpu")
        self.assertEqual(scores, [.6, .7, .8])
        self.assertEqual([int(m.sum()) for m in one], [0, 16, 24])
        np.testing.assert_array_equal(one, two)
        self.assertTrue(all(v[0].device.type == "cpu" for v in models._embeddings.values()))

    def test_image_contents_shape_and_checkpoint_changes_invalidate(self):
        art = np.zeros((8, 8, 3), np.uint8)
        self.click(art)
        art[0, 0] = 1
        self.assertFalse(self.click(art)[2]["embedding_cached"])
        self.assertFalse(self.click(art.reshape(4, 16, 3))[2]["embedding_cached"])
        self.checkpoint.write_bytes(b"replacement weights, different length")
        self.assertFalse(self.click(art)[2]["model_cached"])
        self.assertEqual(self.loader.call_count, 2)
        self.assertEqual(len(models._embeddings), 1)

    def test_cache_is_bounded_and_recent_image_survives(self):
        arts = [np.full((8, 8, 3), k, np.uint8) for k in range(models.MAX_EMBEDDINGS + 1)]
        for art in arts[:-1]:
            self.click(art)
        self.click(arts[0])
        self.click(arts[-1])
        self.assertEqual(len(models._embeddings), models.MAX_EMBEDDINGS)
        self.assertTrue(self.click(arts[0])[2]["embedding_cached"])
        self.assertFalse(self.click(arts[1])[2]["embedding_cached"])


class DeviceContracts(unittest.TestCase):
    def setUp(self):
        self.queue = types.SimpleNamespace(mutex=threading.RLock(), get_tasks_remaining=lambda: 0)
        self.manager = types.SimpleNamespace(get_torch_device=lambda: torch.device("cuda:0"),
            get_free_memory=lambda device: 8 * models._GIB, extra_reserved_memory=lambda: models._GIB)
        for patch in (mock.patch.dict(sys.modules, {"comfy.model_management": self.manager}),
                      mock.patch.object(models, "_prompt_queue", return_value=self.queue),
                      mock.patch.object(models, "_label", side_effect=lambda d: "CPU" if d.type == "cpu" else "test GPU")):
            patch.start(); self.addCleanup(patch.stop)

    def queue_available(self):
        result = []
        def check():
            acquired = self.queue.mutex.acquire(blocking=False)
            result.append(acquired)
            if acquired:
                self.queue.mutex.release()
        thread = threading.Thread(target=check)
        thread.start(); thread.join(2)
        self.assertFalse(thread.is_alive())
        return result[0]

    def test_idle_gpu_lease_prevents_prompt_start_and_releases_afterwards(self):
        with models._device_lease(2 * models._GIB) as (device, reason):
            self.assertEqual(str(device), "cuda:0")
            self.assertIsNone(reason)
            self.assertFalse(self.queue_available())
        self.assertTrue(self.queue_available())
        self.assertFalse(models._gpu_lock.locked())

    def test_busy_queue_and_low_vram_run_on_cpu_without_holding_locks(self):
        for reason in ("comfy_busy", "low_vram"):
            with self.subTest(reason=reason):
                self.queue.get_tasks_remaining = lambda: int(reason == "comfy_busy")
                self.manager.get_free_memory = lambda device: models._GIB
                with models._device_lease(2 * models._GIB) as (device, fallback):
                    self.assertEqual(device.type, "cpu")
                    self.assertEqual(fallback, reason)
                    self.assertTrue(self.queue_available())
                    self.assertFalse(models._gpu_lock.locked())

    def test_comfy_cpu_setting_is_respected(self):
        self.manager.get_torch_device = lambda: torch.device("cpu")
        with models._device_lease(2 * models._GIB) as (device, reason):
            self.assertEqual(device.type, "cpu")
            self.assertIsNone(reason)
            self.assertTrue(self.queue_available())

    def test_success_and_unexpected_error_both_offload(self):
        model, info = FakeModel(), {}
        result = models._infer(model, lambda device: 42, models._GIB, info)
        self.assertEqual(result, 42)
        self.assertEqual(info["backend"], "cuda:0")
        self.assertEqual(model.moves, ["cuda:0", "cpu"])
        with self.assertRaisesRegex(ValueError, "bug"):
            models._infer(model, mock.Mock(side_effect=ValueError("bug")), models._GIB, {})
        self.assertEqual(model.moves[-1], "cpu")
        self.assertTrue(self.queue_available())
        self.assertFalse(models._gpu_lock.locked())

    def test_oom_retry_is_cpu_and_has_no_gpu_or_queue_lease(self):
        calls, info, model = [], {}, FakeModel()
        def operation(device):
            calls.append(device.type)
            if device.type == "cuda":
                raise torch.cuda.OutOfMemoryError("simulated")
            self.assertTrue(self.queue_available())
            self.assertFalse(models._gpu_lock.locked())
            return 17
        self.assertEqual(models._infer(model, operation, models._GIB, info), 17)
        self.assertEqual(calls, ["cuda", "cpu"])
        self.assertEqual(info["fallback"], "cuda_oom")
        self.assertEqual(info["device"], "CPU")
        self.assertEqual(model.moves, ["cuda:0", "cpu"])

    def test_partial_gpu_transfer_oom_offloads_before_retry(self):
        model, info = FakeModel(), {}
        model.to = mock.Mock(side_effect=[torch.cuda.OutOfMemoryError("transfer"), model])
        operation = mock.Mock(return_value=19)
        self.assertEqual(models._infer(model, operation, models._GIB, info), 19)
        self.assertEqual(operation.call_args.args[0].type, "cpu")
        self.assertEqual(model.to.call_args.args[0], "cpu")
        self.assertTrue(self.queue_available())

    def test_fp32_flags_are_scoped_to_inference_even_when_it_fails(self):
        previous = torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32
        def operation(device):
            self.assertFalse(torch.backends.cuda.matmul.allow_tf32)
            self.assertFalse(torch.backends.cudnn.allow_tf32)
            raise ValueError("inference failed")
        with self.assertRaisesRegex(ValueError, "inference failed"):
            models._infer(FakeModel(), operation, models._GIB, {})
        self.assertEqual((torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32), previous)


class DepthContracts(unittest.TestCase):
    def test_local_model_processor_reuse_and_config_invalidation(self):
        class Model(FakeModel):
            def __call__(self, pixel_values):
                return types.SimpleNamespace(predicted_depth=pixel_values[:, 0])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
                (root / name).write_bytes(b"fixture")
            processor = mock.Mock(return_value={"pixel_values": torch.ones((1, 3, 8, 8))})
            processor_loader = mock.Mock(return_value=processor)
            model_loader = mock.Mock(side_effect=lambda *args, **kwargs: Model())
            module = types.SimpleNamespace(AutoImageProcessor=types.SimpleNamespace(from_pretrained=processor_loader),
                AutoModelForDepthEstimation=types.SimpleNamespace(from_pretrained=model_loader))
            models._depth_cache.clear()
            self.addCleanup(models._depth_cache.clear)
            with mock.patch.dict(sys.modules, transformers=module), \
                    mock.patch.object(models, "_device", return_value=torch.device("cpu")):
                art, paths = np.zeros((8, 8, 3), np.uint8), {"depth": root, "sam": root / "absent"}
                for k in range(2):
                    info = {}
                    depth = models.estimate_depth(art, paths, info=info)
                    np.testing.assert_array_equal(depth, np.ones((8, 8), np.float32))
                    self.assertEqual(info["model_cached"], k == 1)
                self.assertEqual(model_loader.call_count, 1)
                self.assertTrue(model_loader.call_args.kwargs["local_files_only"])
                self.assertTrue(processor_loader.call_args.kwargs["local_files_only"])
                (root / "preprocessor_config.json").write_bytes(b"changed fixture")
                models.estimate_depth(art, paths)
                self.assertEqual(model_loader.call_count, 2)


if __name__ == "__main__":
    unittest.main()
