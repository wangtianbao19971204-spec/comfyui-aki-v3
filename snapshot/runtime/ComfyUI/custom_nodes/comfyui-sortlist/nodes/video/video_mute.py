import os
import subprocess

class VideoMuteFromURL:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "output_dir": ("STRING", {"default": ""}),
                "output_filename": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("muted_video_path",)
    FUNCTION = "run"
    CATEGORY = "video"

    def run(self, video_path, output_dir, output_filename):
        video_path = video_path.strip()
        output_dir = output_dir.strip()
        output_filename = output_filename.strip()

        if not os.path.isfile(video_path):
            return (f"ERROR: File not found → {video_path}",)

        if output_dir == "":
            output_dir = os.path.dirname(video_path)

        os.makedirs(output_dir, exist_ok=True)

        # Auto-generate output filename if empty
        if output_filename == "":
            base = os.path.basename(video_path)
            name, ext = os.path.splitext(base)
            output_filename = f"{name}_muted{ext}"

        out_full = os.path.join(output_dir, output_filename)

        # FFmpeg command: remove audio
        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-c:v", "copy",
            "-an",               # remove audio
            out_full
        ]

        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="ignore")
            return (f"FFmpeg failed: {err}",)

        return (out_full,)


NODE_CLASS_MAPPINGS = {
    "video_mute_from_url": VideoMuteFromURL
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "video_mute_from_url": "Video Mute (Remove Audio) from URL"
}
