import gc
import torch
import comfy.model_management as mm


class ClearVRAMPassThrough:
    """
    Unloads all models from VRAM (same as WanVideo Sampler's internal clear),
    then passes the input through unchanged.

    Use case: WanVideo Sampler → VAE Decode → [this node] → VideoCombine
    After decode, WanVideo model + VAE are still in VRAM.
    This node evicts them so subsequent nodes have more VRAM headroom.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "any_input": ("*",),
            },
        }

    # Accept and return any type unchanged
    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("any_output",)
    FUNCTION = "clear_and_passthrough"
    CATEGORY = "utils"
    DESCRIPTION = "Unloads all models from VRAM, then passes input through unchanged. Insert after VAE Decode to free WanVideo/VAE VRAM before VideoCombine."

    def clear_and_passthrough(self, any_input):
        # 1. Unload all models from VRAM (same API used by ComfyUI internally)
        mm.unload_all_models()

        # 2. Soft empty CUDA cache — frees VRAM without affecting active tensors
        mm.soft_empty_cache()

        # 3. Hard empty PyTorch CUDA allocator cache (more aggressive than soft)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # 4. Python GC to collect any remaining Python-side references
        gc.collect()

        # 5. Pass input unchanged
        return (any_input,)


NODE_CLASS_MAPPINGS = {
    "ClearVRAMPassThrough": ClearVRAMPassThrough,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ClearVRAMPassThrough": "Clear VRAM (Pass Through)",
}
