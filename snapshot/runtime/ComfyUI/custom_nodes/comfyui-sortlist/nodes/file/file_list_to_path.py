class FileListToFilePath:
    """
    Convert file list (xử lí cùng lúc) to file path (xử lí từng file).
    Giống Image List to Image Batch nhưng cho file paths.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file_paths": ("STRING",),
            }
        }

    INPUT_IS_LIST = True
    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("file_path", "count")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "convert"
    CATEGORY = "comfyui-sortlist"

    def convert(self, file_paths):
        # Filter out empty strings
        paths = [p for p in file_paths if p and p.strip()]
        return (paths, len(paths))


NODE_CLASS_MAPPINGS = {
    "File List To File Path": FileListToFilePath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "File List To File Path": "File List to File Path",
}
