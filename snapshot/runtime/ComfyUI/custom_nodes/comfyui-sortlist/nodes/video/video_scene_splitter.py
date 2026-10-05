import os
import cv2
import numpy as np
import tempfile
import subprocess

class VideoSceneSplitter:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video_frames": ("IMAGE", {"forceInput": True}),
                "prefix": ("STRING", {"default": "10001"}),
                "save_dir": ("STRING", {"default": "/content/ComfyUI/output/"}),
                "threshold": ("FLOAT", {"default": 28.0, "min": 1.0, "max": 200.0}),
                "min_scene_len": ("INT", {"default": 6, "min": 1, "max": 100})
            }
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_message",)
    FUNCTION = "run"
    CATEGORY = "video/split"

    # ----------------------------------------------------------
    # Convert tensor -> uint8 BGR frame for OpenCV
    # ----------------------------------------------------------
    def tensor_to_cv(self, t):
        arr = np.asarray(t)
        if arr.ndim == 4:
            arr = arr[0]

        if arr.dtype != np.uint8:
            arr = (arr * 255).clip(0, 255).astype(np.uint8)

        # Convert RGB → BGR (OpenCV format)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    # ----------------------------------------------------------
    # Write video segment using ffmpeg
    # ----------------------------------------------------------
    def write_video(self, frames, outpath, fps):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            list_file = f.name
            for frame in frames:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                cv2.imwrite(tmp.name, frame)
                f.write(f"file '{tmp.name}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-vsync", "vfr",
            "-pix_fmt", "yuv420p",
            outpath
        ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # ----------------------------------------------------------
    # Main
    # ----------------------------------------------------------
    def run(self, video_frames, prefix, save_dir, threshold, min_scene_len):

        frames = [self.tensor_to_cv(frm) for frm in video_frames]
        total = len(frames)

        if total < 2:
            return ("Không đủ frame để split",)

        os.makedirs(save_dir, exist_ok=True)

        hist_prev = None
        scene_idx = [0]

        # ----------------- SCENE DETECTION -----------------
        for i in range(total):
            hsv = cv2.cvtColor(frames[i], cv2.COLOR_BGR2HSV)
            hist_now = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
            hist_now = cv2.normalize(hist_now, None).flatten()

            if hist_prev is not None:
                diff = cv2.compareHist(hist_prev, hist_now, cv2.HISTCMP_BHATTACHARYYA)

                if diff * 100 > threshold and (i - scene_idx[-1]) >= min_scene_len:
                    scene_idx.append(i)

            hist_prev = hist_now

        scene_idx.append(total)

        # ----------------- CUT & SAVE -----------------
        count = 1
        for s in range(len(scene_idx) - 1):
            start = scene_idx[s]
            end = scene_idx[s + 1]

            seg = frames[start:end]
            outfile = os.path.join(save_dir, f"{prefix}-{count}.mp4")
            self.write_video(seg, outfile, fps=25)

            count += 1

        return (f"Cắt thành {count - 1} đoạn, lưu tại {save_dir}",)


NODE_CLASS_MAPPINGS = {
    "video_scene_splitter": VideoSceneSplitter
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "video_scene_splitter": "Video Scene Splitter"
}
