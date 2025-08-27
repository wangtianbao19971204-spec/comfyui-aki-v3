import os
import re
import gc
import numpy as np
from typing import Tuple
from PIL import Image
import torch
from transformers import LlavaForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from aiohttp import web
from server import PromptServer


DEBUG_MODE = False

def debug_print(*args, **kwargs):
    if DEBUG_MODE:
        print(*args, **kwargs)


_MODEL_CACHE = {}


DEFAULT_MODEL_ID = os.getenv(
    "JOYCAPTION_MODEL",
    "fancyfeast/llama-joycaption-beta-one-hf-llava",
)


# --- Presets / Extras files (editable by users) ------------------------------
# prompts.txt: one preset per line; headers start with "--"; comments start with "//"
#   "Label: actual prompt text"   OR   "actual prompt text" (label inferred)
PROMPTS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "prompts.txt"))
EXTRAS_FILE  = os.path.abspath(os.path.join(os.path.dirname(__file__), "extras.txt"))

_PH_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _load_presets():
    """
    Returns ONLY selectable strings for the dropdown (no headers), to avoid
    UI crashes with Combo widget. Also returns mapping and placeholders meta.
    """
    selectable, mapping, headers, meta = [], {}, [], {}
    if not os.path.exists(PROMPTS_FILE):
        return (["(none)"], {}, [], {})

    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("--"):
                headers.append(str(line))
                continue

            if ":" in line:
                label, prompt_text = line.split(":", 1)
                label = str(label).strip()
                prompt_text = str(prompt_text).strip()
            else:
                prompt_text = str(line)
                label = (prompt_text[:24] + "…") if len(prompt_text) > 24 else prompt_text

            # ensure strings
            label = str(label)
            prompt_text = str(prompt_text)

            selectable.append(label)
            mapping[label] = prompt_text
            meta[label] = {"placeholders": sorted(set(_PH_RE.findall(prompt_text)))}

    if not selectable:
        selectable = ["(none)"]
    return (selectable, mapping, headers, meta)


def _load_extras():
    items = []
    if not os.path.exists(EXTRAS_FILE):
        return items
    with open(EXTRAS_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("--"):
                items.append({"label": line, "header": True})
                continue
            if ":" in line:
                label, text = line.split(":", 1)
                items.append({"label": str(label).strip(), "text": str(text).strip(), "header": False})
            else:
                text = str(line)
                label = (text[:24] + "…") if len(text) > 24 else text
                items.append({"label": label, "text": text, "header": False})
    return items


def _tensor_to_pil(image_tensor) -> Image.Image:
    if getattr(image_tensor, "ndim", None) != 4:
        raise ValueError(f"Expected 4D image tensor [B,H,W,C], got {getattr(image_tensor, 'shape', None)}")
    x = image_tensor[0].detach().cpu().numpy()
    x = (np.clip(x, 0.0, 1.0) * 255).astype(np.uint8)
    if x.shape[-1] == 4:
        x = x[..., :3]
    return Image.fromarray(x, mode="RGB")


def clear_model_cache():
    global _MODEL_CACHE
    for key, (model, processor) in list(_MODEL_CACHE.items()):
        try:
            if hasattr(model, 'cpu'):
                model.cpu()
            del model
            del processor
            debug_print(f"[OlmJoyCaption] Cleared cached model: {key}")
        except Exception as e:
            debug_print(f"[OlmJoyCaption] Error clearing model {key}: {e}")
    _MODEL_CACHE.clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        debug_print("[OlmJoyCaption] CUDA cache cleared")


def get_model_cache_info():
    if not _MODEL_CACHE:
        return "No models currently cached"
    info = [f"  - {key}" for key in _MODEL_CACHE.keys()]
    return f"Currently cached models ({len(_MODEL_CACHE)}):\n" + "\n".join(info)


class OlmJoyCaption:
    @classmethod
    def INPUT_TYPES(cls):
        selectable, _, _, _ = _load_presets()
        default_choice = selectable[0] if selectable else "(none)"
        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": "", "placeholder": "Optional guidance…"}),
            },
            "optional": {
                "preset_prompt": (selectable, {"default": default_choice}),
                "model_id": ("STRING", {"default": DEFAULT_MODEL_ID}),
                "load_8bit": ("BOOLEAN", {"default": False}),
                "load_4bit": ("BOOLEAN", {"default": False}),
                "max_new_tokens": ("INT", {"default": 128, "min": 8, "max": 1024}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.5, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.95, "min": 0.1, "max": 1.0, "step": 0.01}),
                "unload_after": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption",)
    FUNCTION = "run"
    CATEGORY = "Text/Captioning"


    def _get_model_and_processor(self, model_id: str, load_8bit: bool, load_4bit: bool):
        key = f"{model_id}_{'8bit' if load_8bit else ''}{'4bit' if load_4bit else ''}"
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32

        quantization_config = None
        if device == "cuda" and (load_4bit or load_8bit):
            if load_4bit:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    llm_int8_skip_modules=["vision_tower", "multi_modal_projector"],
                )
                debug_print("[OlmJoyCaption] Loading model in 4-bit (skipping vision components).")
            elif load_8bit:
                quantization_config = BitsAndBytesConfig(
                    load_in_8bit=True,
                    llm_int8_skip_modules=["vision_tower", "multi_modal_projector"],
                )
                debug_print("[OlmJoyCaption] Loading model in 8-bit (skipping vision components).")

        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model = LlavaForConditionalGeneration.from_pretrained(
            model_id,
            trust_remote_code=True,
            torch_dtype=dtype,
            device_map="auto" if device == "cuda" else None,
            quantization_config=quantization_config,
            low_cpu_mem_usage=True,
        )

        if device == "cpu":
            model = model.to(device)  # type: ignore

        _MODEL_CACHE[key] = (model, processor)
        return model, processor


    def run(
        self,
        image: torch.Tensor,
        prompt: str,
        model_id: str = DEFAULT_MODEL_ID,
        load_8bit: bool = False,
        load_4bit: bool = False,
        max_new_tokens: int = 128,
        temperature: float = 0.2,
        top_p: float = 0.95,
        unload_after: bool = False,
        preset_prompt: str | None = None,
    ) -> Tuple[str]:
        debug_print("[OlmJoyCaption] Begin captioning.")
        debug_print("[OlmJoyCaption] Using model:", model_id)
        debug_print("[OlmJoyCaption] max_new_tokens:", max_new_tokens)
        debug_print("[OlmJoyCaption] temperature:", temperature)
        debug_print("[OlmJoyCaption] top_p:", top_p)
        debug_print("[OlmJoyCaption] unload_after:", unload_after)

        if load_4bit:
            load_8bit = False

        model, processor = self._get_model_and_processor(model_id, load_8bit, load_4bit)
        pil = _tensor_to_pil(image)

        user_prompt = prompt.strip() or "Describe this image in rich, precise detail."
        debug_print("[OlmJoyCaption] user_prompt:", user_prompt)

        convo = [{"role": "user", "content": user_prompt}]
        convo_string = processor.apply_chat_template(convo, tokenize=False, add_generation_prompt=True)
        debug_print("[OlmJoyCaption] convo_string:", convo_string)

        inputs = processor(text=[convo_string], images=[pil], return_tensors="pt")

        for k, v in inputs.items():
            if hasattr(v, "to"):
                if k == "pixel_values":
                    if load_4bit or load_8bit:
                        inputs[k] = v.to(model.device, dtype=torch.float16 if torch.cuda.is_available() else torch.float32)
                    else:
                        inputs[k] = v.to(model.device, dtype=model.dtype)
                else:
                    inputs[k] = v.to(model.device)

        with torch.inference_mode():
            out_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=(temperature > 0),
                temperature=temperature,
                top_p=top_p,
                pad_token_id=processor.tokenizer.eos_token_id,
                use_cache=True,
            )

        input_token_len = inputs["input_ids"].shape[1]
        caption_ids = out_ids[0][input_token_len:]
        caption = processor.tokenizer.decode(caption_ids, skip_special_tokens=True).strip() or "(empty caption)"

        if unload_after:
            debug_print("[OlmJoyCaption] Unloading model as requested...")
            clear_model_cache()

        return (caption,)


if PromptServer is not None:

    @PromptServer.instance.routes.get("/olm/api/joycaption/prompts")
    async def get_joycaption_prompts(request):
        try:
            selectable, mapping, headers, meta = _load_presets()
            extras = _load_extras()
            return web.json_response({
                "status": "success",
                "options": selectable,
                "mapping": mapping,
                "meta": meta,
                "extras": extras,
                "files": {
                    "prompts": PROMPTS_FILE,
                    "extras": EXTRAS_FILE if os.path.exists(EXTRAS_FILE) else None,
                },
            })
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)})


    @PromptServer.instance.routes.post("/olm/api/joycaption/clear_cache")
    async def clear_joycaption_cache(request):
        try:
            cache_info = get_model_cache_info()
            clear_model_cache()
            return web.json_response({
                "status": "success",
                "message": "JoyCaption model cache cleared successfully!",
                "previous_cache": cache_info,
                "freed_models": len(_MODEL_CACHE) if _MODEL_CACHE else 0
            })
        except Exception as e:
            debug_print(f"[OlmJoyCaption] Error in cache clear endpoint: {e}")
            return web.json_response({"status": "error", "message": f"Failed to clear cache: {str(e)}"})


    @PromptServer.instance.routes.get("/olm/api/joycaption/cache_status")
    async def get_joycaption_cache_status(request):
        try:
            cache_info = get_model_cache_info()
            return web.json_response({
                "status": "success",
                "cache_info": cache_info,
                "cached_models_count": len(_MODEL_CACHE)
            })
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)})



class OlmTextDisplay:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True, "forceInput": True, "dynamicPrompts": True}),
            },
            "optional": {
            },
        }


    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "display_text"
    CATEGORY = "Text/Captioning"
    OUTPUT_NODE = True


    def display_text(self, text: str):
        return {
            "ui": { "text": text },
            "result": (text, )
        }



NODE_CLASS_MAPPINGS = {
    "OlmJoyCaption": OlmJoyCaption,
    "OlmTextDisplay": OlmTextDisplay,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "OlmJoyCaption": "Olm JoyCaption",
    "OlmTextDisplay": "Olm Text Display",
}


WEB_DIRECTORY = "./web"
