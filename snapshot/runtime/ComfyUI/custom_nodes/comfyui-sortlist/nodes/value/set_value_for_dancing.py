class SetValueForDancingMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Enable Mask": ("BOOLEAN", {
                    "default": True,
                }),
                "Enable Background": ("BOOLEAN", {
                    "default": True,
                }),
                "Enable Upscale": ("BOOLEAN", {
                    "default": False,
                }),
                "Prompt Tách Mask": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Prompt Tách Mask",
                }),
                "THƯ MỤC hình ảnh nhảy": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "THƯ MỤC hình ảnh nhảy",
                }),
                "THƯ MỤC videos nhảy": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "THƯ MỤC videos nhảy",
                }),
                "THƯ MỤC lưu": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "THƯ MỤC lưu",
                }),
            }
        }

    RETURN_TYPES = ("BOOLEAN", "BOOLEAN", "BOOLEAN", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "Enable Mask",
        "Enable Background",
        "Enable Upscale",
        "Prompt Tách Mask",
        "THƯ MỤC hình ảnh nhảy",
        "THƯ MỤC videos nhảy",
        "THƯ MỤC lưu",
    )
    FUNCTION = "run"
    CATEGORY = "comfyui-sortlist"

    def run(self, **kwargs):
        enable_mask = kwargs.get("Enable Mask", True)
        enable_bg = kwargs.get("Enable Background", True)
        enable_upscale = kwargs.get("Enable Upscale", False)
        mask_prompt = kwargs.get("Prompt Tách Mask", "") or ""
        images_dir = kwargs.get("THƯ MỤC hình ảnh nhảy", "") or ""
        videos_dir = kwargs.get("THƯ MỤC videos nhảy", "") or ""
        save_path = kwargs.get("THƯ MỤC lưu", "") or ""

        return (enable_mask, enable_bg, enable_upscale, mask_prompt, images_dir, videos_dir, save_path)


class SetValueForDancingNoneMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Tên file cần lưu": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Tên file cần lưu",
                }),
                "Thư mục lưu video kết quả": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Thư mục lưu video kết quả",
                }),
                "Đường dẫn thư mục videos": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn thư mục videos",
                }),
                "Đường dẫn thư mục hình ảnh": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn thư mục hình ảnh",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "Tên file cần lưu",
        "Thư mục lưu video kết quả",
        "Đường dẫn thư mục videos",
        "Đường dẫn thư mục hình ảnh",
    )
    FUNCTION = "run"
    CATEGORY = "comfyui-sortlist"

    def run(self, **kwargs):
        file_name = kwargs.get("Tên file cần lưu", "") or ""
        save_path = kwargs.get("Thư mục lưu video kết quả", "") or ""
        videos_dir = kwargs.get("Đường dẫn thư mục videos", "") or ""
        images_dir = kwargs.get("Đường dẫn thư mục hình ảnh", "") or ""

        return (file_name, save_path, videos_dir, images_dir)


NODE_CLASS_MAPPINGS = {
    "Set Value For Dancing Mask": SetValueForDancingMask,
    "Set Value For Dancing None Mask": SetValueForDancingNoneMask,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value For Dancing Mask": "Set Value For Dancing Mask",
    "Set Value For Dancing None Mask": "Set Value For Dancing None Mask",
}
