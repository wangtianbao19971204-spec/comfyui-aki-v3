import os
import glob


class ClearFolderByPattern:
    """
    Delete files in a folder matching a user-defined pattern.
    Example patterns: *.mp4, *.png, temp_*, *.log
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                }),
                "pattern": ("STRING", {
                    "default": "*",
                    "multiline": False,
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("result",)
    FUNCTION = "clear"
    CATEGORY = "comfyui-sortlist"
    OUTPUT_NODE = True

    def clear(self, folder_path, pattern):
        folder_path = folder_path.strip()
        pattern = pattern.strip()

        if not folder_path:
            return ("⚠️ Chưa nhập đường dẫn thư mục.",)

        if not os.path.isdir(folder_path):
            return (f"⚠️ Không tìm thấy thư mục: {folder_path}",)

        if not pattern:
            pattern = "*"

        matched = glob.glob(os.path.join(folder_path, pattern))
        count = 0
        for item_path in matched:
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    count += 1
            except Exception as e:
                print(f"[ClearFolderByPattern] Lỗi khi xoá {item_path}: {e}")

        return (f"✅ Đã xoá {count} file khớp pattern '{pattern}' trong {folder_path}",)


NODE_CLASS_MAPPINGS = {
    "Clear Folder By Pattern": ClearFolderByPattern,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Clear Folder By Pattern": "Clear Folder By Pattern",
}
