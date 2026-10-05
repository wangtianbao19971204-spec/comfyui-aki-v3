import numpy as np
import torch


class MP3ExtractFromImage:
    """Extract embedded string (file path/URL) from image RGB channels (LSB steganography)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("data_string",)
    FUNCTION = "extract"
    CATEGORY = "comfyui-sortlist"

    def extract(self, image):
        arr = image.detach().cpu().numpy()
        if arr.ndim == 4:
            arr = arr[0]

        if arr.max() <= 1.0:
            arr = (arr * 255).astype(np.uint8)
        else:
            arr = arr.astype(np.uint8)

        H, W, C = arr.shape
        if C < 3:
            return ("<invalid image: not RGB>",)

        flat = arr[:, :, :3].reshape(-1)

        # Read bits and decode bytes until null terminator (2 consecutive zero bytes)
        bits = ""
        byte_list = []
        zero_count = 0
        for idx in range(len(flat)):
            bits += str(flat[idx] & 1)
            if len(bits) == 8:
                byte_val = int(bits, 2)
                if byte_val == 0:
                    zero_count += 1
                    if zero_count >= 2:
                        break
                else:
                    # If we had one zero before a non-zero, add it back
                    if zero_count > 0:
                        byte_list.append(0)
                        zero_count = 0
                    byte_list.append(byte_val)
                bits = ""

        try:
            data = bytes(byte_list).decode("utf-8")
        except:
            data = "<decode error>"

        return (data,)


NODE_CLASS_MAPPINGS = {
    "MP3 Extract From Image": MP3ExtractFromImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MP3 Extract From Image": "String Extract From Image (RGB)",
}
