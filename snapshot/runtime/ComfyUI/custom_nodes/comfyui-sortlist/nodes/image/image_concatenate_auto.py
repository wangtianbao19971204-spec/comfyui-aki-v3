import torch
from comfy.utils import common_upscale


class ImageConcatenateAuto:
    """
    Nối 2 ảnh lại với nhau theo hướng tự động dựa vào tỉ lệ ảnh đầu vào:
      - Nếu W <= H (ảnh dọc / vuông): nối sang PHẢI (right)
      - Nếu W >  H (ảnh ngang):       nối xuống DƯỚI (down)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "match_image_size": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "direction")
    FUNCTION = "concatenate"
    CATEGORY = "sortlist"

    def concatenate(self, image1, image2, match_image_size):
        # Xác định hướng nối dựa vào kích thước của image1 (B, H, W, C)
        h1 = image1.shape[1]
        w1 = image1.shape[2]

        if w1 <= h1:
            direction = "right"
        else:
            direction = "down"

        # Đồng bộ batch size
        batch_size1 = image1.shape[0]
        batch_size2 = image2.shape[0]

        if batch_size1 != batch_size2:
            max_b = max(batch_size1, batch_size2)
            if batch_size1 < max_b:
                repeat = max_b - batch_size1
                image1 = torch.cat([image1, image1[-1:].repeat(repeat, 1, 1, 1)], dim=0)
            if batch_size2 < max_b:
                repeat = max_b - batch_size2
                image2 = torch.cat([image2, image2[-1:].repeat(repeat, 1, 1, 1)], dim=0)

        # Resize image2 để khớp với image1 nếu được yêu cầu
        if match_image_size:
            orig_h2 = image2.shape[1]
            orig_w2 = image2.shape[2]
            aspect = orig_w2 / orig_h2

            if direction in ("left", "right"):
                target_h = h1
                target_w = int(target_h * aspect)
            else:  # up / down
                target_w = w1
                target_h = int(target_w / aspect)

            img2_bchw = image2.movedim(-1, 1)
            img2_resized_bchw = common_upscale(img2_bchw, target_w, target_h, "lanczos", "disabled")
            image2 = img2_resized_bchw.movedim(1, -1)

        # Đồng bộ số kênh màu (C)
        c1 = image1.shape[-1]
        c2 = image2.shape[-1]
        if c1 != c2:
            if c1 < c2:
                pad = torch.ones((*image1.shape[:-1], c2 - c1), device=image1.device)
                image1 = torch.cat((image1, pad), dim=-1)
            else:
                pad = torch.ones((*image2.shape[:-1], c1 - c2), device=image2.device)
                image2 = torch.cat((image2, pad), dim=-1)

        # Thực hiện nối
        if direction == "right":
            out = torch.cat((image1, image2), dim=2)
        elif direction == "down":
            out = torch.cat((image1, image2), dim=1)
        elif direction == "left":
            out = torch.cat((image2, image1), dim=2)
        else:  # up
            out = torch.cat((image2, image1), dim=1)

        return (out, direction)


NODE_CLASS_MAPPINGS = {
    "ImageConcatenateAuto": ImageConcatenateAuto,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageConcatenateAuto": "Image Concatenate (Auto Direction)",
}
