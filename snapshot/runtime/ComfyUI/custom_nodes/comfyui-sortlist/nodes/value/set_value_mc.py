class SetValueForMC:
    """
    Set configuration values for MC workflow.
    4 string fields for common paths and settings.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Đường dẫn video": ("STRING", {
                    "default": "/content/drive/MyDrive/audio/1.mp4",
                    "multiline": False,
                }),
                "Thư mục audio": ("STRING", {
                    "default": "/content/drive/MyDrive/audio",
                    "multiline": False,
                }),
                "Thư mục kết quả": ("STRING", {
                    "default": "/content/drive/MyDrive/output/videos",
                    "multiline": False,
                }),
                "Prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("path_origin", "path_folder", "save_videos", "prompt")
    FUNCTION = "set_values"
    CATEGORY = "comfyui-sortlist"

    def set_values(self, **kwargs):
        return (kwargs["Đường dẫn video"], kwargs["Thư mục audio"], kwargs["Thư mục kết quả"], kwargs["Prompt"])


NODE_CLASS_MAPPINGS = {
    "Set Value For MC": SetValueForMC,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value For MC": "Set Value For MC",
}
