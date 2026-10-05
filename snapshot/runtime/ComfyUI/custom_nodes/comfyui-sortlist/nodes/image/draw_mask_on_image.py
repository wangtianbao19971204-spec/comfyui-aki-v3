import torch
import torch.nn.functional as F
from tqdm import tqdm


class DrawMaskOnImageOptional:
    """Draw Mask On Image - phiên bản với image và mask optional.
    Nếu chỉ có image (không mask) → output = input image.
    Nếu có cả image + mask → hoạt động bình thường như KJNodes DrawMaskOnImage.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "color": ("STRING", {
                    "default": "0, 0, 0",
                    "tooltip": "Color as RGB/RGBA values in range 0-255 or 0.0-1.0, separated by commas. Ex: 255, 0, 0, 128"
                }),
            },
            "optional": {
                "image": ("IMAGE", ),
                "mask": ("MASK", ),
                "device": (["cpu", "gpu"], {
                    "default": "cpu",
                    "tooltip": "Device to use for processing"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE", )
    RETURN_NAMES = ("images",)
    FUNCTION = "apply"
    CATEGORY = "HuyL3/masking"
    DESCRIPTION = "Applies masks to images with Alpha Blending. Image and mask are optional - if only image is provided, returns it unchanged."

    def apply(self, color, image=None, mask=None, device="cpu"):
        # If no image provided, return empty
        if image is None:
            return (torch.zeros((1, 64, 64, 3), dtype=torch.float32),)

        # If no mask provided, pass through image unchanged
        if mask is None:
            return (image,)

        B, H, W, C = image.shape
        BM, HM, WM = mask.shape

        try:
            import comfy.model_management
            processing_device = comfy.model_management.get_torch_device() if device == "gpu" else torch.device("cpu")
        except ImportError:
            processing_device = torch.device("cpu")

        in_masks = mask.clone().to(processing_device)
        in_images = image.clone().to(processing_device)

        # Resize mask if dimensions don't match
        if HM != H or WM != W:
            in_masks = F.interpolate(mask.unsqueeze(1), size=(H, W), mode='nearest-exact').squeeze(1)

        # Handle batch size mismatch
        if B > BM:
            in_masks = in_masks.repeat((B + BM - 1) // BM, 1, 1)[:B]
        elif BM > B:
            in_masks = in_masks[:B]

        output_images = []

        # Parse Color String
        color = color.strip()
        color_values = []

        if color.startswith('#'):
            hex_color = color.lstrip('#')
            if len(hex_color) == 3:
                color_values = [int(c*2, 16) / 255.0 for c in hex_color]
            elif len(hex_color) == 4:
                color_values = [int(c*2, 16) / 255.0 for c in hex_color]
            elif len(hex_color) == 6:
                color_values = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
            elif len(hex_color) == 8:
                color_values = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4, 6)]
            else:
                raise ValueError(f"Invalid hex color format: {color}")
        else:
            for x in color.split(","):
                val = float(x.strip())
                color_values.append(val / 255.0 if val > 1.0 else val)

        rgb = color_values[:3]
        alpha_val = color_values[3] if len(color_values) == 4 else 1.0

        fill_color = torch.tensor(rgb, dtype=torch.float32, device=processing_device)

        for i in tqdm(range(B), desc="DrawMaskOnImage batch"):
            curr_mask = in_masks[i]
            img_idx = min(i, B - 1)
            curr_image = in_images[img_idx]

            blend_factor = curr_mask.unsqueeze(-1) * alpha_val
            img_channels = curr_image.shape[-1]

            if img_channels == 4:
                img_rgb = curr_image[..., :3]
                img_a = curr_image[..., 3:]
                out_rgb = img_rgb * (1 - blend_factor) + fill_color * blend_factor
                out_a = torch.maximum(img_a, blend_factor)
                masked_image = torch.cat((out_rgb, out_a), dim=-1)
            else:
                masked_image = curr_image * (1 - blend_factor) + fill_color * blend_factor
            output_images.append(masked_image)

        if not output_images:
            return (torch.zeros((0, H, W, C), dtype=image.dtype),)

        out_tensor = torch.stack(output_images, dim=0).cpu()
        return (out_tensor, )


NODE_CLASS_MAPPINGS = {
    "DrawMaskOnImageOptional": DrawMaskOnImageOptional,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DrawMaskOnImageOptional": "Draw Mask On Image (Optional)",
}
