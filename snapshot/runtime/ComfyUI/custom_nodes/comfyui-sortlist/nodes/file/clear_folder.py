import os
import shutil


class ClearFolder:
    """
    Delete all files and subdirectories inside a given folder.
    The folder itself is kept.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("result",)
    FUNCTION = "clear"
    CATEGORY = "comfyui-sortlist"
    OUTPUT_NODE = True

    def clear(self, folder_path):
        folder_path = folder_path.strip()

        if not folder_path:
            return ("⚠️ Chưa nhập đường dẫn thư mục.",)

        if not os.path.isdir(folder_path):
            return (f"⚠️ Không tìm thấy thư mục: {folder_path}",)

        count = 0
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                count += 1
            except Exception as e:
                print(f"[ClearFolder] Lỗi khi xoá {item_path}: {e}")

        return (f"✅ Đã xoá {count} mục trong {folder_path}",)


NODE_CLASS_MAPPINGS = {
    "Clear Folder": ClearFolder,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Clear Folder": "Clear Folder (rm -r *)",
}
