class RemoveFirstLine:
    """
    Loại bỏ dòng đầu tiên trong danh sách (text multiline).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_list": ("STRING", {
                    "default": "",
                    "multiline": True,
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("result",)
    FUNCTION = "run"
    CATEGORY = "comfyui-sortlist"

    def run(self, text_list):
        lines = text_list.strip().splitlines()
        if len(lines) <= 1:
            return ("",)
        result = "\n".join(lines[1:])
        return (result,)


NODE_CLASS_MAPPINGS = {
    "RemoveFirstLine": RemoveFirstLine,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RemoveFirstLine": "Remove First Line",
}
