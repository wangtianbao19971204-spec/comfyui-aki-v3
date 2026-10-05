import os
import torch
import numpy as np
from PIL import Image


class LoadImageFromPath:
    """Load an image from an absolute file path and output IMAGE tensor."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn file ảnh (.png/.jpg/.webp)",
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load"
    CATEGORY = "comfyui-sortlist"

    def load(self, image_path):
        image_path = image_path.strip().strip('"')
        if not image_path or not os.path.isfile(image_path):
            raise FileNotFoundError(f"File không tồn tại: {image_path}")

        img = Image.open(image_path).convert("RGB")
        img_np = np.array(img).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).unsqueeze(0)  # (1, H, W, 3)

        return (img_tensor,)


NODE_CLASS_MAPPINGS = {
    "LoadImageFromPath": LoadImageFromPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadImageFromPath": "Load Image From Path",
}
