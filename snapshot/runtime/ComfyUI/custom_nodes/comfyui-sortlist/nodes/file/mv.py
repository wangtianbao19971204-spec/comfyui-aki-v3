import os
import shutil

class MoveFile:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "source_path": ("STRING", {"default": ""}),
                "target_dir": ("STRING", {"default": ""})
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_path",)
    FUNCTION = "run"
    CATEGORY = "file"

    def run(self, source_path, target_dir):
        source_path = source_path.strip()
        target_dir = target_dir.strip()

        if not os.path.isfile(source_path):
            return (f"Error: Source file not found → {source_path}",)

        os.makedirs(target_dir, exist_ok=True)

        filename = os.path.basename(source_path)
        name, ext = os.path.splitext(filename)
        new_path = os.path.join(target_dir, filename)

        # Nếu file đã tồn tại, thêm hậu tố _1, _2, _3...
        counter = 1
        while os.path.exists(new_path):
            new_path = os.path.join(target_dir, f"{name}_{counter}{ext}")
            counter += 1

        try:
            shutil.move(source_path, new_path)
        except Exception as e:
            return (f"Move failed: {e}",)

        return (new_path,)


NODE_CLASS_MAPPINGS = {
    "move_file": MoveFile
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "move_file": "Move File (mv)"
}
