import os
import subprocess

class VideoAudioConcat:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "audio_source_path": ("STRING", {"default": ""}),
                # Thêm input folder lưu và tên file output
                "output_dir": ("STRING", {"default": ""}),
                "output_filename": ("STRING", {"default": "output.mp4"})
            }
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_fullpath",)
    FUNCTION = "run"
    CATEGORY = "video"

    def run(self, video_path, audio_source_path, output_dir, output_filename):
        video_path = video_path.strip()
        audio_source_path = audio_source_path.strip()
        output_dir = output_dir.strip()
        output_filename = output_filename.strip()

        if not os.path.isfile(video_path):
            return (f"Error: video file not found → {video_path}",)
        if not os.path.isfile(audio_source_path):
            return (f"Error: audio source file not found → {audio_source_path}",)

        # Nếu không có output_dir, dùng current dir
        if output_dir == "":
            output_dir = "."

        os.makedirs(output_dir, exist_ok=True)
        out_full = os.path.join(output_dir, output_filename)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-i", audio_source_path,
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            out_full
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='ignore')
            return (f"FFmpeg failed: {err}",)

        return (out_full,)
        
NODE_CLASS_MAPPINGS = {
    "video_audio_concat": VideoAudioConcat
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "video_audio_concat": "Video Audio Concat from URL"
}
