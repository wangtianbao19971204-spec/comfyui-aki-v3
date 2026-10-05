"""
Folder File Scanner Node for ComfyUI
Quét thư mục và trả về danh sách đầy đủ path của các file ảnh hoặc video.
"""

import os
import glob
import re


IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"]
VIDEO_EXTENSIONS = [".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv", ".flv"]


class FolderFileScanner:
    """
    Quét thư mục và trả về list đầy đủ path của các file ảnh hoặc video.

    - folder_path : đường dẫn thư mục cần quét
    - file_type   : "image" (.jpg .jpeg .png .webp .bmp .gif .tiff)
                   hoặc "video" (.mp4 .avi .mov .mkv .webm .wmv .flv)
    - sort_method : cách sắp xếp kết quả
    - recursive   : có quét thư mục con hay không
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn thư mục, ví dụ: C:/videos hoặc /content/input",
                    "tooltip": "Đường dẫn tuyệt đối đến thư mục cần quét",
                }),
                "file_type": (["image", "video"], {
                    "default": "image",
                    "tooltip": (
                        "image: .jpg .jpeg .png .webp .bmp .gif .tiff\n"
                        "video: .mp4 .avi .mov .mkv .webm .wmv .flv"
                    ),
                }),
            },
            "optional": {
                "sort_method": (["numerical", "alphabetical", "modified_time"], {
                    "default": "numerical",
                    "tooltip": "Cách sắp xếp: theo số, tên, hoặc thời gian sửa đổi",
                }),
                "recursive": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "True = quét cả thư mục con",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("file_paths", "count")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "scan"
    CATEGORY = "utils"
    DESCRIPTION = """
    Quét thư mục và trả về danh sách đầy đủ path.

    Output:
    - file_paths : list các đường dẫn tuyệt đối (STRING list)
    - count      : tổng số file tìm thấy (INT)
    """

    def scan(self, folder_path: str, file_type: str,
             sort_method: str = "numerical", recursive: bool = False):

        folder_path = folder_path.strip().strip('"').strip("'")

        if not folder_path or not os.path.isdir(folder_path):
            print(f"[FolderFileScanner] Thư mục không tồn tại: '{folder_path}'")
            return ([], 0)

        # Chọn đuôi file theo loại
        if file_type == "image":
            extensions = IMAGE_EXTENSIONS
        else:
            extensions = VIDEO_EXTENSIONS

        # Thu thập file
        found = []
        if recursive:
            for root, _, files in os.walk(folder_path):
                for fname in files:
                    if os.path.splitext(fname)[1].lower() in extensions:
                        found.append(os.path.join(root, fname))
        else:
            for ext in extensions:
                # glob không phân biệt hoa thường trên mọi OS
                found.extend(glob.glob(os.path.join(folder_path, f"*{ext}")))
                found.extend(glob.glob(os.path.join(folder_path, f"*{ext.upper()}")))
            # Loại trùng (do glob chạy 2 lần thường/hoa)
            found = list(dict.fromkeys(found))

        # Sắp xếp
        def extract_number(path):
            nums = re.findall(r'\d+', os.path.basename(path))
            return int(nums[0]) if nums else 0

        if sort_method == "numerical":
            found.sort(key=extract_number)
        elif sort_method == "alphabetical":
            found.sort(key=lambda p: os.path.basename(p).lower())
        elif sort_method == "modified_time":
            found.sort(key=os.path.getmtime)

        print(
            f"[FolderFileScanner] folder='{folder_path}' "
            f"type={file_type} recursive={recursive} "
            f"→ {len(found)} files found"
        )

        return (found, len(found))


# Node registration
NODE_CLASS_MAPPINGS = {
    "FolderFileScanner": FolderFileScanner,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FolderFileScanner": "Folder File Scanner 📂",
}
