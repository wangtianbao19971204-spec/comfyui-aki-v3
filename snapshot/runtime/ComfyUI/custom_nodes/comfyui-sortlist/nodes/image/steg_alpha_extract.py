import numpy as np
import torch

class StegAlphaExtract:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("data_string",)
    FUNCTION = "extract"
    CATEGORY = "custom/steganography"

    def extract(self, image):
        # image có thể là torch.Tensor hoặc numpy -> convert về numpy
        if isinstance(image, torch.Tensor):
            np_img = image.detach().cpu().numpy()
        else:
            np_img = np.asarray(image)

        # Nếu có batch [B,H,W,C] -> lấy ảnh đầu tiên
        if np_img.ndim == 4:
            np_img = np_img[0]

        # Phải là H x W x C
        if np_img.ndim != 3:
            return ("<invalid image: not HxWxC>",)

        H, W, C = np_img.shape

        # Cần có alpha channel
        if C < 4:
            return ("<image has no alpha channel>",)

        # Lấy kênh alpha
        alpha = np_img[:, :, 3]

        # Nếu alpha float 0..1 -> convert sang uint8 0..255
        if alpha.dtype != np.uint8:
            alpha_u8 = (np.clip(alpha * 255.0, 0, 255).astype(np.uint8))
        else:
            alpha_u8 = alpha

        flat_alpha = alpha_u8.flatten()

        # Lấy LSB thành bit
        bits = []
        for a in flat_alpha:
            bits.append(a & 1)

        # bits -> bytes
        bytes_out = []
        for i in range(0, len(bits), 8):
            byte = 0
            for j in range(8):
                if i + j >= len(bits):
                    break
                byte = (byte << 1) | bits[i + j]

            # 0 = marker kết thúc (do embed thêm 16 bit 0)
            if byte == 0:
                break

            bytes_out.append(byte)

        try:
            decoded = bytes(bytes_out).decode("utf-8")
        except Exception:
            decoded = "<decode error>"

        return (decoded,)


NODE_CLASS_MAPPINGS = {
    "steg_alpha_extract": StegAlphaExtract
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "steg_alpha_extract": "Steganography: Extract String From Alpha"
}
