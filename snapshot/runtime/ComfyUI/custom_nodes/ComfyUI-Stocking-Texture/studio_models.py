"""On-demand CPU inference using local weights; never downloads or retains models."""
from pathlib import Path
import threading

import cv2
import numpy as np

SAM_FILE = "sam_vit_b_01ec64.pth"
DEPTH_FOLDER = "Depth-Anything-V2-Small-hf"
DEPTH_REVISION = "5426e4f0f36572d16453bbda7a8389317b1bef99"
DEPTH_SHA256 = "3152477ce0d8d6978d76b995120de97cb5b928701fd0f817769f59e249a16b70"
SHORT_SIDE = 1036
_inference_lock = threading.Lock()


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
            "device": "CPU"}


def segment(art, x, y, model_paths):
    checkpoint = Path(model_paths["sam"])
    if not checkpoint.is_file():
        raise ValueError("缺少 SAM ViT-B：请放入 models/sams/sam_vit_b_01ec64.pth")
    # Optional model dependencies are imported only when the user requests inference.
    from segment_anything import SamPredictor, sam_model_registry
    with _inference_lock:
        model = sam_model_registry["vit_b"](checkpoint=str(checkpoint)).eval()
        predictor = SamPredictor(model)
        predictor.set_image(np.ascontiguousarray(art))
        masks, scores, _ = predictor.predict(point_coords=np.array([[x, y]], np.float32),
                                              point_labels=np.array([1]), multimask_output=True)
        order = np.argsort([m.sum() for m in masks], kind="stable")
        return [masks[i].copy() for i in order], [float(scores[i]) for i in order]


def estimate_depth(art, model_paths):
    path = Path(model_paths["depth"])
    if not available(model_paths)["depth"]:
        raise ValueError("缺少 Depth Anything V2 Small：请将模型放入 models/stocking_texture/Depth-Anything-V2-Small-hf")
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    from transformers.pipelines import DepthEstimationPipeline
    with _inference_lock:
        processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True, use_fast=False)
        model = AutoModelForDepthEstimation.from_pretrained(str(path), local_files_only=True).eval()
        pipeline = DepthEstimationPipeline(model=model, image_processor=processor, framework="pt", device=-1)
        inputs = processor(images=np.array(art), return_tensors="pt",
                           size={"height": SHORT_SIDE, "width": SHORT_SIDE},
                           keep_aspect_ratio=True, ensure_multiple_of=14)
        inputs["target_size"] = tuple(art.shape[:2])
        prediction = pipeline.forward(inputs)["predicted_depth"][0].float().cpu().numpy()
        return cv2.resize(prediction, (art.shape[1], art.shape[0]), interpolation=cv2.INTER_CUBIC).astype(np.float32)
