class SetValueForMC_I2V:
    """
    Set configuration values for MC I2V workflow.
    Same as Set Value For MC but without path_origin and with license_key field.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
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

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("path_folder", "save_videos", "prompt", "license_key")
    FUNCTION = "set_values"
    CATEGORY = "comfyui-sortlist"

    def set_values(self, **kwargs):
        return (kwargs["Thư mục audio"], kwargs["Thư mục kết quả"], kwargs["Prompt"], kwargs["license_key"])


NODE_CLASS_MAPPINGS = {
    "Set Value For MC I2V": SetValueForMC_I2V,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value For MC I2V": "Set Value For MC I2V",
}
