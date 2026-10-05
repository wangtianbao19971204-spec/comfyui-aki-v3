import os
import shutil


class CollectFiles:
    """
    Lọc các dòng chứa pattern từ string list multiline,
    rồi copy các file đó vào thư mục đích.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "String list (multiline)",
                }),
                "pattern": ("STRING", {
                    "default": ".mp4",
                    "multiline": False,
                    "placeholder": "Pattern lọc, ví dụ: .mp4",
                }),
                "exclude": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Pattern loại trừ, ví dụ: audio.mp4",
                }),
                "dest_folder": ("STRING", {
                    "default": "/content/ComfyUI/output/I2V",
                    "multiline": False,
                    "placeholder": "Thư mục đích",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("result",)
    FUNCTION = "collect"
    CATEGORY = "comfyui-sortlist"

    def collect(self, text, pattern, exclude, dest_folder):
        os.makedirs(dest_folder, exist_ok=True)

        # Đệ quy flatten mọi cấu trúc lồng nhau để lấy tất cả string
        def flatten(obj):
            results = []
            if isinstance(obj, str):
                for line in obj.strip().split("\n"):
                    line = line.strip().strip('",\'')
                    if line:
                        results.append(line)
            elif isinstance(obj, (list, tuple)):
                for item in obj:
                    results.extend(flatten(item))
            return results

        lines = flatten(text)
        matched = []
        for line in lines:
            clean = line.strip().strip('",').strip("'")
            if pattern in clean and os.path.isfile(clean):
                # Loại trừ nếu exclude pattern khớp
                if exclude and exclude in clean:
                    continue
                matched.append(clean)

        # Move từng file vào thư mục đích
        moved = []
        for src in matched:
            basename = os.path.basename(src)
            dest = os.path.join(dest_folder, basename)
            # Xử lý trùng tên
            if os.path.exists(dest):
                name, ext = os.path.splitext(basename)
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.join(dest_folder, f"{name}_{counter}{ext}")
                    counter += 1
            shutil.move(src, dest)
            moved.append(dest)

        result = "\n".join(moved) if moved else "Không tìm thấy file nào khớp pattern"
        return (result,)


NODE_CLASS_MAPPINGS = {
    "CollectFiles": CollectFiles,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CollectFiles": "Collect Files",
}
