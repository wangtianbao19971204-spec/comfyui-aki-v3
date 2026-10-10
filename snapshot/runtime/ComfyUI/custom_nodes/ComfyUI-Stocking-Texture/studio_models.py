"""Local SAM/depth inference. Bounded CPU caches; CUDA is borrowed only while idle."""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sys
import threading
import time

import cv2
import numpy as np

SAM_FILE = "sam_vit_b_01ec64.pth"
DEPTH_FOLDER = "Depth-Anything-V2-Small-hf"
DEPTH_REVISION = "5426e4f0f36572d16453bbda7a8389317b1bef99"
DEPTH_SHA256 = "3152477ce0d8d6978d76b995120de97cb5b928701fd0f817769f59e249a16b70"
SHORT_SIDE = 1036
_sam_lock = threading.Lock()
_depth_lock = threading.Lock()
_gpu_lock = threading.Lock()
_sam_cache = {}
_depth_cache = {}
_embeddings = OrderedDict()
MAX_EMBEDDINGS = 4
_GIB = 1024 ** 3


def _identity(*files):
    return tuple((str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in files)


def _device():
    import torch
    # ComfyUI has already configured CPU/CUDA before importing custom nodes. Do not
    # import its device manager here: standalone tests must not initialize a server.
    manager = sys.modules.get("comfy.model_management")
    if manager is not None:
        device = torch.device(manager.get_torch_device())
        return device if device.type == "cuda" else torch.device("cpu")
    return torch.device("cuda", torch.cuda.current_device()) if torch.cuda.is_available() else torch.device("cpu")


def _label(device):
    import torch
    return torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU"


def _prompt_queue():
    server = sys.modules.get("server")
    owner = getattr(getattr(server, "PromptServer", None), "instance", None)
    return getattr(owner, "prompt_queue", None)


@contextmanager
def _device_lease(required_bytes):
    """Keep prompt admission and this short GPU operation mutually exclusive.

    Disk loading/preprocessing happens before this lease. Never unload ComfyUI
    models. A CPU fallback runs after releasing both locks, including on OOM.
    """
    import torch
    device, reason = _device(), None
    acquired_queue = None
    acquired_gpu = False
    try:
        if device.type == "cuda":
            _gpu_lock.acquire()
            acquired_gpu = True
            queue = _prompt_queue()
            if queue is not None:
                if queue.mutex.acquire(blocking=False):
                    acquired_queue = queue
                    if queue.get_tasks_remaining():
                        reason = "comfy_busy"
                else:
                    reason = "comfy_busy"
            if reason is None:
                manager = sys.modules.get("comfy.model_management")
                free = (manager.get_free_memory(device) if manager is not None
                        else torch.cuda.mem_get_info(device)[0])
                reserve = manager.extra_reserved_memory() if manager is not None else _GIB // 2
                if free < required_bytes + reserve:
                    reason = "low_vram"
            if reason:
                device = torch.device("cpu")
        if device.type != "cuda":
            if acquired_queue is not None:
                acquired_queue.mutex.release()
                acquired_queue = None
            if acquired_gpu:
                _gpu_lock.release()
                acquired_gpu = False
        yield device, reason
    finally:
        if acquired_queue is not None:
            acquired_queue.mutex.release()
        if acquired_gpu:
            _gpu_lock.release()


@contextmanager
def _full_precision(device):
    import torch
    if device.type != "cuda":
        yield
        return
    # TF32 convolutions can visibly change depth around sharp edges. The GPU
    # lease prevents ComfyUI prompts from running while these global flags change.
    matmul, cudnn = torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32
    try:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        with torch.autocast(device_type="cuda", enabled=False):
            yield
    finally:
        torch.backends.cuda.matmul.allow_tf32 = matmul
        torch.backends.cudnn.allow_tf32 = cudnn


def _infer(model, operation, required_bytes, info):
    import torch
    oom = False
    with _device_lease(required_bytes) as (device, reason):
        try:
            with torch.inference_mode(), _full_precision(device):
                model.to(device)
                result = operation(device)
        except torch.cuda.OutOfMemoryError:
            if device.type != "cuda":
                raise
            oom = True
        finally:
            # Even a failed transfer/prediction must not pin a model in VRAM.
            model.to("cpu")
    if oom:
        device, reason = torch.device("cpu"), "cuda_oom"
        with torch.inference_mode():
            result = operation(device)
    info.update(device=_label(device), backend=str(device), fallback=reason)
    return result


def paths():
    import folder_paths
    root = Path(folder_paths.models_dir)
    known = folder_paths.folder_names_and_paths
    sam_roots = folder_paths.get_folder_paths("sams") if "sams" in known else []
    depth_roots = folder_paths.get_folder_paths("stocking_texture") if "stocking_texture" in known else []
    sam_candidates = [Path(p) / SAM_FILE for p in [*sam_roots, root / "sams"]]
    depth_candidates = [Path(p) / DEPTH_FOLDER for p in [*depth_roots, root / "stocking_texture"]]
    return {"sam": next((p for p in sam_candidates if p.is_file()), sam_candidates[-1]),
            "depth": next((p for p in depth_candidates if (p / "model.safetensors").is_file()), depth_candidates[-1])}


def available(model_paths):
    return {"sam": Path(model_paths["sam"]).is_file(),
            "depth": all((Path(model_paths["depth"]) / f).is_file()
                         for f in ("config.json", "preprocessor_config.json", "model.safetensors")),
            "device": _label(_device())}


def segment(art, x, y, model_paths, *, info=None):
    started = time.perf_counter()
    info = {} if info is None else info
    checkpoint = Path(model_paths["sam"])
    if not checkpoint.is_file():
        raise ValueError("缺少 SAM ViT-B：请放入 models/sams/sam_vit_b_01ec64.pth")
    # Optional model dependencies are imported only when the user requests inference.
    from segment_anything import SamPredictor, sam_model_registry
    art = np.ascontiguousarray(art)
    digest = (art.shape, art.dtype.str, hashlib.sha256(memoryview(art)).digest())
    with _sam_lock:
        key = _identity(checkpoint)
        info["model_cached"] = _sam_cache.get("key") == key
        if not info["model_cached"]:
            _sam_cache.clear()
            _embeddings.clear()
            model = sam_model_registry["vit_b"](checkpoint=str(checkpoint)).eval().cpu()
            _sam_cache.update(key=key, model=model)
        model = _sam_cache["model"]

        def predict(device):
            predictor = SamPredictor(model)
            embedding_key = (key, digest, str(device))
            cached = _embeddings.get(embedding_key)
            info["embedding_cached"] = cached is not None
            if cached is None:
                predictor.set_image(art)
                _embeddings[embedding_key] = (predictor.features.detach().to("cpu", copy=True),
                                              predictor.original_size, predictor.input_size)
                while len(_embeddings) > MAX_EMBEDDINGS:
                    _embeddings.popitem(last=False)
            else:
                features, predictor.original_size, predictor.input_size = cached
                predictor.features = features.to(device)
                predictor.is_image_set = True
                _embeddings.move_to_end(embedding_key)
            return predictor.predict(point_coords=np.array([[x, y]], np.float32),
                                     point_labels=np.array([1]), multimask_output=True)

        masks, scores, _ = _infer(model, predict, 3 * _GIB, info)
        order = np.argsort([m.sum() for m in masks], kind="stable")
        info["seconds"] = time.perf_counter() - started
        return [masks[i].copy() for i in order], [float(scores[i]) for i in order]


def estimate_depth(art, model_paths, *, info=None):
    started = time.perf_counter()
    info = {} if info is None else info
    path = Path(model_paths["depth"])
    if not available(model_paths)["depth"]:
        raise ValueError("缺少 Depth Anything V2 Small：请将模型放入 models/stocking_texture/Depth-Anything-V2-Small-hf")
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    with _depth_lock:
        key = _identity(*(path / f for f in ("config.json", "preprocessor_config.json", "model.safetensors")))
        info["model_cached"] = _depth_cache.get("key") == key
        if not info["model_cached"]:
            _depth_cache.clear()
            processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True, use_fast=False)
            model = AutoModelForDepthEstimation.from_pretrained(str(path), local_files_only=True).eval().cpu()
            _depth_cache.update(key=key, model=model, processor=processor)
        model, processor = _depth_cache["model"], _depth_cache["processor"]
        inputs = processor(images=np.array(art), return_tensors="pt",
                           size={"height": SHORT_SIDE, "width": SHORT_SIDE},
                           keep_aspect_ratio=True, ensure_multiple_of=14)

        def predict(device):
            output = model(**{k: v.to(device) for k, v in inputs.items()})
            return output.predicted_depth[0].float().cpu().numpy()

        prediction = _infer(model, predict, 3 * _GIB, info)
        info["seconds"] = time.perf_counter() - started
        return cv2.resize(prediction, (art.shape[1], art.shape[0]), interpolation=cv2.INTER_CUBIC).astype(np.float32)
