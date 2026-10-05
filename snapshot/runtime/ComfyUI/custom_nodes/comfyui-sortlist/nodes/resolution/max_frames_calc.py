# max_frames_calc.py
# Node to calculate max frames supported based on resolution
# Reference: 1280x720 = 921,600 pixels → 489 max frames (4n+1 pattern)

REFERENCE_PIXELS = 1280 * 720   # 921,600
REFERENCE_FRAMES = 489

class MaxFramesCalculator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width":  ("INT", {"default": 1280, "min": 64, "max": 8192, "step": 8}),
                "height": ("INT", {"default": 720,  "min": 64, "max": 8192, "step": 8}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("max_frames", "safe_frames")
    FUNCTION = "calc"
    CATEGORY = "utils"

    def calc(self, width: int, height: int):
        pixels = width * height
        ratio = REFERENCE_PIXELS / pixels
        raw_max = REFERENCE_FRAMES * ratio

        # Round down to nearest 4n+1 (1, 5, 9, 13, ..., 489, ...)
        n = int((raw_max - 1) / 4)
        max_frames = 4 * n + 1

        # Safe frames: one step below max (buffer)
        safe_frames = max_frames - 4 if max_frames > 1 else 1

        return (max_frames, safe_frames)


NODE_CLASS_MAPPINGS = {
    "MaxFramesCalculator": MaxFramesCalculator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MaxFramesCalculator": "Max Frames Calculator (by Resolution)",
}
