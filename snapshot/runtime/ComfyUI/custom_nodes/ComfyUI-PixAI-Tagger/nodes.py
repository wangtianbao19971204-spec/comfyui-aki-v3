import gc
import json
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from transformers import pipeline

import comfy.model_management as mm
import comfy.utils
import folder_paths


MODEL_DIR = Path(folder_paths.models_dir) / "taggers" / "pixai-tagger-v1.0"
CATEGORIES = ("character", "general", "copyright", "style", "meta", "rating")


def format_tags(results, categories, exclude_tags, replace_underscore, trailing_comma):
    # Match both Danbooru underscores and the human-readable spelling.
    excluded = {tag.strip().replace("_", " ").casefold() for tag in exclude_tags.split(",")}
    tags = []
    for category in categories:
        for tag, score in sorted(results[category].items(), key=lambda item: (-item[1], item[0])):
            if tag.replace("_", " ").casefold() in excluded:
                continue
            text = tag.replace("_", " ") if replace_underscore else tag
            tags.append(text.replace("(", "\\(").replace(")", "\\)"))
    return ", ".join(tags) + (", " if tags and trailing_comma else "")


class PixAITagger:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE",),
            "model": (["pixai-tagger-v1.0"],),
            "threshold": ("FLOAT", {"default": 0.17, "min": 0.0, "max": 1.0, "step": 0.01}),
            "character_threshold": ("FLOAT", {"default": 0.27, "min": 0.0, "max": 1.0, "step": 0.01}),
            "replace_underscore": ("BOOLEAN", {"default": True}),
            "trailing_comma": ("BOOLEAN", {"default": False}),
            "exclude_tags": ("STRING", {"default": ""}),
        }, "optional": {
            "categories": ("STRING", {"default": "character,general", "tooltip": "Comma-separated output categories: character, general, copyright, style, meta, rating. JSON always includes all six."}),
            "style_threshold": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01}),
            "copyright_threshold": ("FLOAT", {"default": 0.24, "min": 0.0, "max": 1.0, "step": 0.01}),
            "meta_threshold": ("FLOAT", {"default": 0.17, "min": 0.0, "max": 1.0, "step": 0.01}),
            "rating_threshold": ("FLOAT", {"default": 0.41, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("tags", "scores_json")
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "tag"
    OUTPUT_NODE = True
    CATEGORY = "image/tagging"
    DESCRIPTION = "Local PixAI Tagger v1.0. Six categories, 30,877 labels. Releases its model after each batch."

    def tag(self, image, model="pixai-tagger-v1.0", threshold=0.17, character_threshold=0.27,
            replace_underscore=True, trailing_comma=False, exclude_tags="",
            categories="character,general", style_threshold=0.15,
            copyright_threshold=0.24, meta_threshold=0.17, rating_threshold=0.41):
        if model != "pixai-tagger-v1.0":
            raise ValueError("Unsupported PixAI Tagger model: " + model)
        selected = list(dict.fromkeys(part.strip() for part in categories.split(",") if part.strip()))
        if not selected or any(part not in CATEGORIES for part in selected):
            raise ValueError("Select categories from: " + ", ".join(CATEGORIES))
        for filename in ("config.json", "preprocessor_config.json", "tagger_pipeline.py", "model.safetensors"):
            if not (MODEL_DIR / filename).is_file():
                raise FileNotFoundError(f"PixAI Tagger model file missing: {MODEL_DIR / filename}")
        thresholds = {"general": threshold, "character": character_threshold,
                      "style": style_threshold, "copyright": copyright_threshold,
                      "meta": meta_threshold, "rating": rating_threshold}
        device = mm.get_torch_device()
        dtype = torch.bfloat16 if mm.should_use_bf16(device) else torch.float32
        mm.free_memory(4 * 1024**3, device)
        tagger = None
        tags, scores = [], []
        try:
            tagger = pipeline(model=str(MODEL_DIR), image_processor=str(MODEL_DIR),
                              trust_remote_code=True, device=device, dtype=dtype, use_fast=False,
                              model_kwargs={"local_files_only": True})
            progress = comfy.utils.ProgressBar(image.shape[0])
            for tensor in image:
                mm.throw_exception_if_processing_interrupted()
                pixels = np.clip(tensor.cpu().numpy() * 255, 0, 255).astype(np.uint8)
                result = tagger(Image.fromarray(pixels), threshold=thresholds)["results"]
                tags.append(format_tags(result, selected, exclude_tags, replace_underscore, trailing_comma))
                scores.append(json.dumps(result, ensure_ascii=False))
                progress.update(1)
        finally:
            del tagger
            gc.collect()
            mm.soft_empty_cache()
        return {"ui": {"tags": tags}, "result": (tags, scores)}
