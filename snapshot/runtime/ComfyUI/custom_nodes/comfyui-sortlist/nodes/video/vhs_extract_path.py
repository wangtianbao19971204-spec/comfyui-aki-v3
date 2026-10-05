"""
Extract video path from VHS_FILENAMES output.
"""

class VHS_ExtractVideoPath:
    """
    Extracts the video (.mp4) path from VHS_VideoCombine output (VHS_FILENAMES).
    VHS_FILENAMES format: (bool, [png_path, mp4_path, audio_mp4_path, ...])
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "filenames": ("VHS_FILENAMES",),
            },
            "optional": {
                "file_type": (["mp4", "png", "audio_mp4", "all"], {"default": "mp4"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_path", "all_paths")
    FUNCTION = "extract"
    CATEGORY = "SortList/Video"

    def extract(self, filenames, file_type="mp4"):
        # VHS_FILENAMES is a tuple: (bool, [list of paths])
        if not filenames or len(filenames) < 2:
            return ("", "")
        
        paths = filenames[1] if isinstance(filenames[1], list) else []
        
        all_paths = "\n".join(paths) if paths else ""
        
        if file_type == "all":
            return (all_paths, all_paths)
        
        # Find the requested file type
        result_path = ""
        for p in paths:
            p_lower = p.lower()
            if file_type == "mp4" and p_lower.endswith(".mp4") and "-audio" not in p_lower:
                result_path = p
                break
            elif file_type == "png" and p_lower.endswith(".png"):
                result_path = p
                break
            elif file_type == "audio_mp4" and p_lower.endswith(".mp4") and "-audio" in p_lower:
                result_path = p
                break
        
        return (result_path, all_paths)


NODE_CLASS_MAPPINGS = {
    "VHS_ExtractVideoPath": VHS_ExtractVideoPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VHS_ExtractVideoPath": "Extract Video Path from VHS_FILENAMES",
}
