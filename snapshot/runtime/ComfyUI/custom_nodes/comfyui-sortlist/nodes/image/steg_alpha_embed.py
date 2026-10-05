import numpy as np
import torch

class StegAlphaEmbed:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "data_string": ("STRING", {"default": "secret-data"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_out",)
    FUNCTION = "embed"
    CATEGORY = "custom/steganography"

    def embed(self, image, data_string):
        # Chuyển Tensor -> numpy float32 0..1
        np_img = np.asarray(image, dtype=np.float32)

        # Nếu có batch [B,H,W,C] thì lấy ảnh đầu tiên
        if np_img.ndim == 4:
            np_img = np_img[0]

        # Chuẩn hoá nếu >1.0
        if np_img.max() > 1.0 + 1e-3:
            np_img = np_img / 255.0

        # Convert string → bits
        data_bytes = data_string.encode("utf-8")
        data_bits = []
        for b in data_bytes:
            for i in range(8):
                data_bits.append((b >> (7 - i)) & 1)

        # Thêm marker kết thúc
        data_bits.extend([0] * 16)

        H, W, C = np_img.shape

        if C == 3:
            alpha = np.ones((H, W, 1), dtype=np.float32)
            np_img = np.concatenate([np_img, alpha], axis=2)
        elif C < 3:
            raise Exception("Image must have RGB at least.")

        total_pixels = H * W
        if len(data_bits) > total_pixels:
            raise Exception("Data too large for alpha channel")

        # Embed LSB
        alpha_ch = np_img[:, :, 3]
        alpha_u8 = (alpha_ch * 255).astype(np.uint8).flatten()

        for i, bit in enumerate(data_bits):
            alpha_u8[i] = (alpha_u8[i] & 0b11111110) | bit

        np_img[:, :, 3] = (alpha_u8.reshape(H, W) / 255.0)

        # >>> SỬA CHỖ NÀY <<<  
        # Trả về TENSOR đúng định dạng ComfyUI [1,H,W,C]
        out_tensor = torch.from_numpy(np_img).unsqueeze(0).float()

        return (out_tensor,)


NODE_CLASS_MAPPINGS = {
    "steg_alpha_embed": StegAlphaEmbed
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "steg_alpha_embed": "Steganography: Embed String in Alpha"
}
