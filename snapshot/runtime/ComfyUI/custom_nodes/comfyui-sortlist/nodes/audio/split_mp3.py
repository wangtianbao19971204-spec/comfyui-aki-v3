import os
import subprocess
import json
import math


class SplitMP3Node:
    """
    Cắt file MP3 thành nhiều đoạn theo quy tắc:
    - Nếu < 7 phút (420s): cắt thành 2 file bằng nhau
    - Nếu >= 7 phút: cắt thành các file 7 phút, file cuối là phần dư
    Output được lưu vào /content/ComfyUI/output/mp3_list
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mp3_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "Đường dẫn file MP3",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_folder",)
    OUTPUT_IS_LIST = (False,)
    FUNCTION = "split"
    CATEGORY = "comfyui-sortlist"

    def _get_duration(self, mp3_path):
        """Lấy độ dài file MP3 bằng ffprobe (giây)."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            mp3_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe lỗi: {result.stderr}")
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])

    def split(self, mp3_path):
        mp3_path = mp3_path.strip().strip('"')

        if not mp3_path or not os.path.isfile(mp3_path):
            raise FileNotFoundError(f"File không tồn tại: {mp3_path}")

        # Thư mục output cố định
        output_dir = "/content/ComfyUI/output/mp3_list"
        os.makedirs(output_dir, exist_ok=True)

        # Lấy tên file gốc (không có extension)
        base_name = os.path.splitext(os.path.basename(mp3_path))[0]

        # Lấy độ dài
        duration = self._get_duration(mp3_path)
        threshold = 270  # 4 phút 30 giây = 270 giây



        if duration < threshold:
            # < 7 phút → cắt thành 2 phần bằng nhau
            half = duration / 2
            segments = [
                (0, half),
                (half, duration - half),
            ]

        else:
            # >= 7 phút → cắt mỗi file 7 phút (420s)
            segment_duration = threshold
            num_full = int(duration // segment_duration)
            remainder = duration - num_full * segment_duration

            segments = []
            for i in range(num_full):
                start = i * segment_duration
                segments.append((start, segment_duration))

            if remainder > 0.5:  # bỏ qua nếu quá ngắn (<0.5s)
                segments.append((num_full * segment_duration, remainder))



        # Tạo file 1 giây đầu tiên (preview)
        preview_file = os.path.join(output_dir, f"{base_name}_001.mp3")
        cmd = [
            "ffmpeg", "-y",
            "-i", mp3_path,
            "-ss", "0",
            "-t", "1",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            preview_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output_files = []
        if result.returncode == 0:
            output_files.append(preview_file)

        # Thực hiện cắt các segment chính (bắt đầu từ _002)
        for idx, (start, dur) in enumerate(segments, start=2):
            out_file = os.path.join(output_dir, f"{base_name}_{idx:03d}.mp3")
            cmd = [
                "ffmpeg", "-y",
                "-i", mp3_path,
                "-ss", str(start),
                "-t", str(dur),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                out_file,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[SplitMP3] ⚠️ Lỗi cắt phần {idx}: {result.stderr[-200:]}")
            else:
                output_files.append(out_file)

        return (output_dir,)


NODE_CLASS_MAPPINGS = {
    "SplitMP3": SplitMP3Node,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SplitMP3": "Split MP3 (7min segments)",
}
