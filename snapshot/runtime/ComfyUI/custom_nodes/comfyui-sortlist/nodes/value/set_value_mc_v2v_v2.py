class SetValueForMC_V2V_V2:
    """
    Set configuration values for MC V2V V2 workflow.
    Includes: video path, audio path, resolution, output folder, Vietnamese motion prompt.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Đường dẫn video": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn file video (.mp4)",
                }),
                "Đường dẫn audio": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn file audio (.mp3/.wav)",
                }),
                "Độ phân giải": (["480p", "600p", "720p"], {
                    "default": "480p",
                    "tooltip": "480p = 480, 600p = 600, 720p = 720",
                }),
                "Đường dẫn thư mục lưu": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Thư mục lưu file output",
                }),
                "Prompt cử động tiếng việt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "Mô tả cử động bằng tiếng Việt",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING", "STRING")
    RETURN_NAMES = ("video_path", "audio_path", "resolution", "output_folder", "motion_prompt_vi")
    FUNCTION = "set_values"
    CATEGORY = "comfyui-sortlist"

    def set_values(self, **kwargs):
        resolution_map = {"480p": 480, "600p": 600, "720p": 720}
        resolution_int = resolution_map[kwargs["Độ phân giải"]]
        return (
            kwargs["Đường dẫn video"],
            kwargs["Đường dẫn audio"],
            resolution_int,
            kwargs["Đường dẫn thư mục lưu"],
            kwargs["Prompt cử động tiếng việt"],
        )


NODE_CLASS_MAPPINGS = {
    "Set Value For MC V2V V2": SetValueForMC_V2V_V2,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value For MC V2V V2": "Set Value For MC V2V V2",
}
