"""
Split MP3 V2 Node for ComfyUI
Cß║»t file MP3 th├ánh c├íc ─æoß║ín tß╗æi ─æa 3 ph├║t.
- Nß║┐u file < 3 ph├║t: kh├┤ng cß║»t, trß║ú vß╗ü file gß╗æc
- Nß║┐u file >= 3 ph├║t: cß║»t th├ánh c├íc ─æoß║ín 3 ph├║t, ─æoß║ín cuß╗æi l├á phß║ºn d╞░
"""

import os
import subprocess
import json
import math


MAX_DURATION_SEC = 180  # 3 ph├║t = 180 gi├óy


class SplitMP3V2Node:
    """
    Cß║»t file MP3 th├ánh c├íc ─æoß║ín tß╗æi ─æa 3 ph├║t (180 gi├óy).

    Rules:
    - duration <= 180s : kh├┤ng cß║»t, output = [file gß╗æc]
    - duration >  180s : cß║»t th├ánh [0-180s], [180-360s], ..., [phß║ºn d╞░]

    Output: list ─æß║ºy ─æß╗º path c├íc file ─æ├ú cß║»t + tß╗òng sß╗æ file.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mp3_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "─É╞░ß╗¥ng dß║½n file MP3",
                    "tooltip": "─É╞░ß╗¥ng dß║½n tuyß╗çt ─æß╗æi ─æß║┐n file .mp3",
                }),
                "output_folder": ("STRING", {
                    "default": "/content/ComfyUI/output/mp3_split",
                    "multiline": False,
                    "placeholder": "Th╞░ mß╗Ñc l╞░u file output",
                    "tooltip": "Th╞░ mß╗Ñc l╞░u c├íc file sau khi cß║»t",
                }),
            },
            "optional": {
                "max_minutes": ("FLOAT", {
                    "default": 3.0,
                    "min": 0.5,
                    "max": 60.0,
                    "step": 0.5,
                    "tooltip": "─Éß╗Ö d├ái tß╗æi ─æa mß╗ùi ─æoß║ín (ph├║t). Mß║╖c ─æß╗ïnh 3 ph├║t.",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("file_paths", "count")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "split"
    CATEGORY = "utils"
    DESCRIPTION = """
    Cß║»t file MP3 th├ánh tß╗½ng ─æoß║ín tß╗æi ─æa N ph├║t (mß║╖c ─æß╗ïnh 3 ph├║t).

    - Nß║┐u duration <= max_minutes: kh├┤ng cß║»t, trß║ú vß╗ü file gß╗æc
    - Nß║┐u duration >  max_minutes: cß║»t th├ánh nhiß╗üu ─æoß║ín, ─æoß║ín cuß╗æi = phß║ºn d╞░

    Output:
    - file_paths : STRING hiß╗ân thß╗ï tß║Ñt cß║ú path (mß╗ùi file 1 d├▓ng)
    - count      : tß╗òng sß╗æ file output (INT)
    """

    def _get_duration(self, mp3_path: str) -> float:
        """Lß║Ñy ─æß╗Ö d├ái file MP3 bß║▒ng ffprobe (gi├óy)."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            mp3_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"[SplitMP3V2] ffprobe lß╗ùi: {result.stderr}")
        info = json.loads(result.stdout)
        return float(info["format"]["duration"])

    def _run_ffmpeg(self, input_path: str, start: float, duration: float, output_path: str) -> bool:
        """Cß║»t 1 ─æoß║ín bß║▒ng ffmpeg, trß║ú vß╗ü True nß║┐u th├ánh c├┤ng."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ss", f"{start:.3f}",
            "-t",  f"{duration:.3f}",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[SplitMP3V2] ΓÜá∩╕Å ffmpeg lß╗ùi: {result.stderr[-300:]}")
            return False
        return True

    def split(self, mp3_path: str, output_folder: str, max_minutes: float = 3.0):
        mp3_path = mp3_path.strip().strip('"').strip("'")

        if not mp3_path or not os.path.isfile(mp3_path):
            raise FileNotFoundError(f"[SplitMP3V2] File kh├┤ng tß╗ôn tß║íi: '{mp3_path}'")

        max_sec = max_minutes * 60.0

        # Lß║Ñy ─æß╗Ö d├ái file gß╗æc
        duration = self._get_duration(mp3_path)
        base_name = os.path.splitext(os.path.basename(mp3_path))[0]

        print(
            f"[SplitMP3V2] {base_name}.mp3 | duration={duration:.1f}s "
            f"| max={max_sec:.0f}s ({max_minutes}min)"
        )

        # Nß║┐u file ngß║»n h╞ín hoß║╖c bß║▒ng giß╗¢i hß║ín ΓåÆ kh├┤ng cß║»t
        if duration <= max_sec:
            print(f"[SplitMP3V2] Γ£à Kh├┤ng cß║»t (duration <= {max_minutes} ph├║t), trß║ú vß╗ü file gß╗æc.")
            return ([mp3_path], 1)

        # T├¡nh c├íc segment
        num_full = int(duration // max_sec)
        remainder = duration - num_full * max_sec

        segments = []
        for i in range(num_full):
            segments.append((i * max_sec, max_sec))
        if remainder > 0.5:  # bß╗Å qua nß║┐u qu├í ngß║»n (<0.5s)
            segments.append((num_full * max_sec, remainder))

        print(f"[SplitMP3V2] Cß║»t th├ánh {len(segments)} ─æoß║ín...")

        # Tß║ío th╞░ mß╗Ñc output
        os.makedirs(output_folder, exist_ok=True)

        # Thß╗▒c hiß╗çn cß║»t
        output_files = []
        for idx, (start, dur) in enumerate(segments, start=1):
            out_file = os.path.join(output_folder, f"{base_name}_{idx:03d}.mp3")
            success = self._run_ffmpeg(mp3_path, start, dur, out_file)
            if success:
                output_files.append(out_file)
                print(f"[SplitMP3V2]   [{idx:03d}] {start:.1f}s ΓåÆ {start+dur:.1f}s ΓåÆ {out_file}")
            else:
                print(f"[SplitMP3V2]   [{idx:03d}] Γ¥î Cß║»t thß║Ñt bß║íi")

        print(f"[SplitMP3V2] Γ£à Xong: {len(output_files)}/{len(segments)} file")
        return (output_files, len(output_files))


# Node registration
NODE_CLASS_MAPPINGS = {
    "SplitMP3V2": SplitMP3V2Node,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SplitMP3V2": "Split MP3 V2 (3min segments) Γ£é∩╕Å",
}
