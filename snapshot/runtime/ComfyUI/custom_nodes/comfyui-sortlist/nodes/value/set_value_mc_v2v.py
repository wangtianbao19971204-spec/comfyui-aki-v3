class SetValueForMC_V2V:
    """
    Set configuration values for MC V2V workflow.
    Same as Set Value For MC but with license_key field.
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
                "license_key": ("STRING", {
                    "default": "",
                    "multiline": False,
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("path_origin", "path_folder", "save_videos", "prompt", "license_key")
    FUNCTION = "set_values"
    CATEGORY = "comfyui-sortlist"

    def set_values(self, **kwargs):
        return (kwargs["Đường dẫn video"], kwargs["Thư mục audio"], kwargs["Thư mục kết quả"], kwargs["Prompt"], kwargs["license_key"])


NODE_CLASS_MAPPINGS = {
    "Set Value For MC V2V": SetValueForMC_V2V,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value For MC V2V": "Set Value For MC V2V",
}
