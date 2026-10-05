import os
import glob
import re


class FileListLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn thư mục chứa file mp3",
                }),
                "sort_method": (["numerical", "alphabetical", "modified_time"], {
                    "default": "numerical",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("file_paths", "count")
    FUNCTION = "run"
    CATEGORY = "comfyui-sortlist"
    OUTPUT_IS_LIST = (True, False)

    def run(self, folder_path, sort_method):
        if not folder_path or not os.path.isdir(folder_path):
            return ([], 0)

        files = glob.glob(os.path.join(folder_path, "*.mp3"))

        if sort_method == "numerical":
            def extract_number(f):
                nums = re.findall(r'\d+', os.path.basename(f))
                return int(nums[0]) if nums else 0
            files.sort(key=extract_number)
        elif sort_method == "alphabetical":
            files.sort(key=lambda f: os.path.basename(f).lower())
        elif sort_method == "modified_time":
            files.sort(key=os.path.getmtime)

        return (files, len(files))


NODE_CLASS_MAPPINGS = {
    "File List Loader": FileListLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "File List Loader": "File List Loader (MP3)",
}
