class SetValueForMC_I2V_V2:
    """
    Set configuration values for MC I2V V2 workflow.
    Fields: URL image, URL audio, Độ phân giải, THƯ MỤC lưu, Prompt mô tả cử động.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "URL image": ("STRING", {
                    "default": "",
                    "multiline": False,
                }),
                "URL audio": ("STRING", {
                    "default": "/content/drive/MyDrive/audio",
                    "multiline": False,
                }),
                "Độ phân giải": (["480p", "600p", "720p", "1080p"], {
                    "default": "720p",
                }),
                "THƯ MỤC lưu": ("STRING", {
                    "default": "/content/drive/MyDrive/output/videos",
                    "multiline": False,
                }),
                "Prompt mô tả cử động (tiếng việt/tiếng anh)": ("STRING", {
                    "default": "",
                    "multiline": True,
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING", "STRING")
    RETURN_NAMES = ("path_image", "path_audio", "resolution", "save_dir", "prompt")
    FUNCTION = "set_values"
    CATEGORY = "comfyui-sortlist"

    def set_values(self, **kwargs):
        resolution_map = {"480p": 480, "600p": 600, "720p": 720, "1080p": 1080}
        resolution_int = resolution_map[kwargs["Độ phân giải"]]
        return (
            kwargs["URL image"],
            kwargs["URL audio"],
            resolution_int,
            kwargs["THƯ MỤC lưu"],
            kwargs["Prompt mô tả cử động (tiếng việt/tiếng anh)"],
        )


NODE_CLASS_MAPPINGS = {
    "Set Value For MC I2V V2": SetValueForMC_I2V_V2,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value For MC I2V V2": "Set Value For MC I2V V2",
}
