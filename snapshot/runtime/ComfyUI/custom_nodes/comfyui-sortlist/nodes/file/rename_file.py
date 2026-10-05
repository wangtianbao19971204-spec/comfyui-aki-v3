import os

any_type = ("*", {})

class RenameFileNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "input_file_path": (any_type,),
                "new_file_name": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_file_path",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "rename"
    CATEGORY = "HuyL3/File"

    def rename(self, input_file_path, new_file_name):
        new_file_name = new_file_name.strip()

        # Normalize input to list
        if isinstance(input_file_path, str):
            # Single path or multiline string
            paths = [p.strip() for p in input_file_path.strip().splitlines() if p.strip()]
        elif isinstance(input_file_path, (list, tuple)):
            # Already a list
            paths = []
            for p in input_file_path:
                if isinstance(p, str):
                    for line in p.strip().splitlines():
                        if line.strip():
                            paths.append(line.strip())
                else:
                    paths.append(str(p).strip())
        else:
            paths = [str(input_file_path).strip()]

        results = []
        for i, file_path in enumerate(paths):
            if not os.path.isfile(file_path):
                results.append(f"ERROR: File not found → {file_path}")
                continue

            dir_path = os.path.dirname(file_path)
            old_name = os.path.basename(file_path)
            _, old_ext = os.path.splitext(old_name)

            # Generate name: abc → abc_00001, abc_00002, ...
            if len(paths) > 1:
                padded_index = str(i + 1).zfill(5)
                current_name = f"{new_file_name}_{padded_index}"
            else:
                current_name = new_file_name

            # Keep original extension if new name has none
            if "." not in current_name:
                current_name = current_name + old_ext

            new_path = os.path.join(dir_path, current_name)

            try:
                os.rename(file_path, new_path)
                results.append(new_path)
            except Exception as e:
                results.append(f"ERROR: Rename failed → {e}")

        return (results,)


NODE_CLASS_MAPPINGS = {
    "rename_file": RenameFileNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "rename_file": "Rename File"
}
