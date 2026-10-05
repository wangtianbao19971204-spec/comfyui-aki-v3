class FixDimensions:
    """
    Fix width and height to be divisible by 16 (required for VAE/video models).
    Input: width, height (any value)
    Output: width, height (rounded to nearest multiple of 16)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {
                    "default": 512,
                    "min": 64,
                    "max": 8192,
                    "step": 1,
                }),
                "height": ("INT", {
                    "default": 512,
                    "min": 64,
                    "max": 8192,
                    "step": 1,
                }),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "fix"
    CATEGORY = "comfyui-sortlist"

    def fix(self, width, height):
        # Round DOWN to nearest multiple of 16
        fixed_width = (width // 16) * 16
        fixed_height = (height // 16) * 16
        
        # Ensure minimum of 64
        fixed_width = max(64, fixed_width)
        fixed_height = max(64, fixed_height)
        
        return (fixed_width, fixed_height)


NODE_CLASS_MAPPINGS = {
    "Fix Dimensions": FixDimensions,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Fix Dimensions": "Fix Dimensions (Div by 16)",
}
