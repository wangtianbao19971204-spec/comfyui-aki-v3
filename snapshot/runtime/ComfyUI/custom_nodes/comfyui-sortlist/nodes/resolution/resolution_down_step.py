# resolution_down_step.py
# Maps a resolution value down one step:
# 720 -> 480, 1080 -> 720

RESOLUTION_MAP = {
    720: 480,
    1080: 720,
}

class ResolutionDownStep:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "resolution": ("INT", {"default": 720, "min": 1, "max": 99999}),
            }
        }

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("resolution_down",)
    FUNCTION = "execute"
    CATEGORY = "HuyL3/Utilities"

    def execute(self, resolution: int):
        result = RESOLUTION_MAP.get(resolution, resolution)
        return (result,)


NODE_CLASS_MAPPINGS = {
    "ResolutionDownStep": ResolutionDownStep,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ResolutionDownStep": "Resolution Down Step (720→480, 1080→720)",
}
