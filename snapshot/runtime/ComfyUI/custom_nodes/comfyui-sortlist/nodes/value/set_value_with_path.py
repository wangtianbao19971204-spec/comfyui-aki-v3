class SetValueWithPath:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Thứ tự hiển thị đúng như bạn yêu cầu
                "Tách mask": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Tách mask",
                }),
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
                "Đường dẫn video gốc": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn video gốc",
                }),
                "License_key": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "License_key",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "Tách mask",
        "Tên file cần lưu",
        "Thư mục lưu video kết quả",
        "Đường dẫn video gốc",
        "License_key",
    )
    FUNCTION = "run"
    CATEGORY = "comfyui-sortlist"

    def run(self, **kwargs):
        mask_prompt = kwargs.get("Tách mask", "") or ""
        file_name = kwargs.get("Tên file cần lưu", "") or ""
        save_path = kwargs.get("Thư mục lưu video kết quả", "") or ""
        convert_path = kwargs.get("Đường dẫn video gốc", "") or ""
        license_key = kwargs.get("License_key", "") or ""

        return (mask_prompt, file_name, save_path, convert_path, license_key)


NODE_CLASS_MAPPINGS = {
    "Set Value With Path": SetValueWithPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Set Value With Path": "Set Value With Path",
}
