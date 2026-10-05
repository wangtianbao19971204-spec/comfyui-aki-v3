import numpy as np
import torch

class StegRGBExtract:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"image": ("IMAGE",)},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("data_string",)
    FUNCTION = "extract"
    CATEGORY = "custom/steganography"

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

        flat = arr.reshape(-1, 3)

        bits = ""
        for pix in flat:
            for k in range(3):
                bits += str(pix[k] & 1)

        byte_list = []
        for i in range(0, len(bits), 8):
            byte = int(bits[i:i+8], 2)
            if byte == 0:
                break
            byte_list.append(byte)

        try:
            data = bytes(byte_list).decode("utf-8")
        except:
            data = "<decode error>"

        return (data,)
