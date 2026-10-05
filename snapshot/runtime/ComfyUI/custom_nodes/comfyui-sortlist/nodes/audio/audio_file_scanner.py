"""
Audio File Scanner Node for ComfyUI
Quét thư mục và trả về danh sách đầy đủ path của các file âm thanh (MP3, WAV...).
"""

import os
import glob
import re


AUDIO_EXTENSIONS = {
    "mp3":  [".mp3"],
    "all":  [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".ac3"],
}


class AudioFileScanner:
    """
    Quét thư mục và trả về list đầy đủ path của các file âm thanh.

    - folder_path  : đường dẫn thư mục cần quét
    - audio_type   : "mp3" (chỉ .mp3) hoặc "all" (tất cả định dạng âm thanh)
    - sort_method  : cách sắp xếp kết quả
    - recursive    : có quét thư mục con hay không
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn thư mục, ví dụ: C:/audio hoặc /content/audio",
                    "tooltip": "Đường dẫn tuyệt đối đến thư mục cần quét",
                }),
                "audio_type": (["mp3", "all"], {
                    "default": "mp3",
                    "tooltip": (
                        "mp3: chỉ quét .mp3\n"
                        "all: .mp3 .wav .flac .aac .m4a .ogg .opus .wma .aiff .ac3"
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
    Quét thư mục và trả về danh sách đầy đủ path của file âm thanh.

    Output:
    - file_paths : list các đường dẫn tuyệt đối (STRING list)
    - count      : tổng số file tìm thấy (INT)
    """

    def scan(self, folder_path: str, audio_type: str = "mp3",
             sort_method: str = "numerical", recursive: bool = False):

        folder_path = folder_path.strip().strip('"').strip("'")

        if not folder_path or not os.path.isdir(folder_path):
            print(f"[AudioFileScanner] Thư mục không tồn tại: '{folder_path}'")
            return ([], 0)

        extensions = AUDIO_EXTENSIONS.get(audio_type, AUDIO_EXTENSIONS["mp3"])

        # Thu thập file
        found = []
        if recursive:
            for root, _, files in os.walk(folder_path):
                for fname in files:
                    if os.path.splitext(fname)[1].lower() in extensions:
                        found.append(os.path.join(root, fname))
        else:
            for ext in extensions:
                found.extend(glob.glob(os.path.join(folder_path, f"*{ext}")))
                found.extend(glob.glob(os.path.join(folder_path, f"*{ext.upper()}")))
            found = list(dict.fromkeys(found))  # loại trùng

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
            f"[AudioFileScanner] folder='{folder_path}' "
            f"type={audio_type} recursive={recursive} "
            f"→ {len(found)} files found"
        )

        return (found, len(found))


# Node registration
NODE_CLASS_MAPPINGS = {
    "AudioFileScanner": AudioFileScanner,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AudioFileScanner": "Audio File Scanner 🎵",
}
