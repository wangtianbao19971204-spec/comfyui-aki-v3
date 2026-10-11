"""Load existing Anima controlnet files through ComfyUI's native model patch API."""
import os

import comfy.ldm.anima.lllite
import comfy.model_management
import comfy.model_patcher
import comfy.ops
import comfy.utils
import folder_paths


class AnimaLLLiteModelLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"lllite_name": ([name for name in
            folder_paths.get_filename_list("controlnet") if name.endswith(".safetensors")],)}}

    RETURN_TYPES = ("MODEL_PATCH",)
    FUNCTION = "load"
    CATEGORY = "model/loaders"

    def load(self, lllite_name):
        if lllite_name not in self.INPUT_TYPES()["required"]["lllite_name"][0]:
            raise ValueError("Choose an existing Anima LLLite safetensors file from controlnet.")
        native = comfy.ldm.anima.lllite.AnimaLLLite
        if (not getattr(native.apply, "_anima_compat_cnet_patch", False)
                or os.environ.get("ANIMA_COMPAT_CONTROLNET_REMAP", "1").strip().lower()
                in ("0", "off", "false", "no")):
            raise RuntimeError("Enable ComfyUI-Anima-LoRA-ControlNet-Patch before using this control workflow.")
        path = folder_paths.get_full_path_or_raise("controlnet", lllite_name)
        state, metadata = comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
        if "lllite_conditioning1.conv1.weight" not in state:
            raise ValueError("This file is not a named-key Anima LLLite checkpoint.")
        model = native(state, metadata, device=comfy.model_management.unet_offload_device(),
                       dtype=comfy.utils.weight_dtype(state), operations=comfy.ops.manual_cast)
        patcher = comfy.model_patcher.CoreModelPatcher(model,
            load_device=comfy.model_management.get_torch_device(),
            offload_device=comfy.model_management.unet_offload_device())
        model.load_state_dict(state, assign=patcher.is_dynamic())
        return (patcher,)
