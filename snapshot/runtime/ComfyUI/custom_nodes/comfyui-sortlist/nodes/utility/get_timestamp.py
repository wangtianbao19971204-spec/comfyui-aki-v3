from datetime import datetime


class GetTimestamp:
    """Get current timestamp for filename prefix."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "format": (["YYYY-MM-DD_HH-MM-SS", "YYYYMMDD_HHMMSS", "YYYY-MM-DD", "HH-MM-SS", "custom"], {
                    "default": "YYYY-MM-DD_HH-MM-SS"
                }),
            },
            "optional": {
                "prefix": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "video_",
                }),
                "custom_format": ("STRING", {
                    "default": "%Y-%m-%d_%H-%M-%S",
                    "multiline": False,
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("timestamp",)
    FUNCTION = "get_timestamp"
    CATEGORY = "comfyui-sortlist"

    def get_timestamp(self, format, prefix="", custom_format="%Y-%m-%d_%H-%M-%S"):
        now = datetime.now()
        
        if format == "YYYY-MM-DD_HH-MM-SS":
            result = now.strftime("%Y-%m-%d_%H-%M-%S")
        elif format == "YYYYMMDD_HHMMSS":
            result = now.strftime("%Y%m%d_%H%M%S")
        elif format == "YYYY-MM-DD":
            result = now.strftime("%Y-%m-%d")
        elif format == "HH-MM-SS":
            result = now.strftime("%H-%M-%S")
        elif format == "custom":
            result = now.strftime(custom_format)
        else:
            result = now.strftime("%Y-%m-%d_%H-%M-%S")
        
        return (prefix + result,)


NODE_CLASS_MAPPINGS = {
    "Get Timestamp": GetTimestamp,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Get Timestamp": "Get Timestamp",
}
