import numpy as np
import hashlib


class ImageToSHA256:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("sha256",)
    FUNCTION = "get_sha256"
    CATEGORY = "custom/utils"

    def _image_to_uint8_bytes(self, image):
        """
        Chuẩn hóa tensor ComfyUI -> raw pixel uint8 để hash.
        """
        arr = np.asarray(image)

        # Nếu tensor dạng [B, H, W, C] → lấy [H, W, C]
        if arr.ndim == 4:
            arr = arr[0]

        # float → uint8
        if arr.dtype != np.uint8:
            arr = (np.clip(arr * 255.0, 0, 255).astype(np.uint8))

        return arr.tobytes()

    def get_sha256(self, image):
        raw_bytes = self._image_to_uint8_bytes(image)
        sha = hashlib.sha256(raw_bytes).hexdigest()

        print(f"[ImageToSHA256] SHA256 = {sha}")
        return (sha, )


NODE_CLASS_MAPPINGS = {
    "image_to_sha256": ImageToSHA256
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "image_to_sha256": "Image to SHA256"
}
