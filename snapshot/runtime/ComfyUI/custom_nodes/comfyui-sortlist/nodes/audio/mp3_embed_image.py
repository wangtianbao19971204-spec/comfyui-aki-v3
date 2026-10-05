import numpy as np
import torch


class MP3EmbedInImage:
    """Embed a string (file path/URL) into image RGB channels using LSB steganography."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "data_string": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "URL hoặc đường dẫn file",
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image_out",)
    FUNCTION = "embed"
    CATEGORY = "comfyui-sortlist"

    def embed(self, image, data_string):
        if not data_string:
            raise Exception("data_string is empty")

        # Convert string to bits
        data_bytes = data_string.encode("utf-8")
        bits = []
        for b in data_bytes:
            for i in range(8):
                bits.append((b >> (7 - i)) & 1)
        # Null terminator (16 zero bits)
        bits.extend([0] * 16)

        # Process image
        np_img = image.detach().cpu().numpy()
        if np_img.ndim == 4:
            np_img = np_img[0].copy()
        else:
            np_img = np_img.copy()

        if np_img.max() <= 1.0 + 1e-3:
            img_u8 = (np_img * 255).astype(np.uint8)
        else:
            img_u8 = np_img.astype(np.uint8)

        H, W, C = img_u8.shape
        if C < 3:
            raise Exception("Image must have at least RGB channels.")

        total_bits = H * W * 3
        if len(bits) > total_bits:
            raise Exception(
                f"String quá dài ({len(data_bytes)} bytes). "
                f"Ảnh {W}x{H} chứa tối đa {total_bits // 8} bytes."
            )

        # Embed LSB into RGB channels
        flat = img_u8[:, :, :3].reshape(-1)
        for i, bit in enumerate(bits):
            flat[i] = (flat[i] & 0b11111110) | bit

        img_u8[:, :, :3] = flat.reshape(H, W, 3)

        out = img_u8.astype(np.float32) / 255.0
        out_tensor = torch.from_numpy(out).unsqueeze(0).float()
        return (out_tensor,)


NODE_CLASS_MAPPINGS = {
    "MP3 Embed In Image": MP3EmbedInImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MP3 Embed In Image": "String Embed In Image (RGB)",
}
