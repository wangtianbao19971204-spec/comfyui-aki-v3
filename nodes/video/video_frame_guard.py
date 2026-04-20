import math
import subprocess
from typing import List, Optional, Tuple


MIN_VALID_FRAMES = 5


def _run_ffprobe_duration(path: str) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """
    Returns (duration_sec, fps, nb_frames) if available.
    Uses ffprobe (fast, no decoding).
    """
    dur = None
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        s = (r.stdout or "").strip()
        if s:
            dur = float(s)
    except Exception:
        dur = None

    fps = None
    nb_frames = None
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,r_frame_rate,nb_frames",
                "-of",
                "default=noprint_wrappers=1:nokey=0",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (r.stdout or "").strip().splitlines()

        kv = {}
        for line in out:
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()

        def parse_rate(x: str) -> Optional[float]:
            if not x:
                return None
            if "/" in x:
                a, b = x.split("/", 1)
                try:
                    a = float(a)
                    b = float(b)
                    if b != 0:
                        return a / b
                except Exception:
                    return None
            try:
                return float(x)
            except Exception:
                return None

        fps = parse_rate(kv.get("avg_frame_rate", "")) or parse_rate(kv.get("r_frame_rate", ""))

        nf = kv.get("nb_frames", "")
        if nf and nf.isdigit():
            nb_frames = int(nf)

    except Exception:
        fps = None
        nb_frames = None

    return dur, fps, nb_frames


def _split_paths(multiline: str) -> List[str]:
    if not multiline:
        return []

    lines = []
    for ln in multiline.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        lines.append(ln)
    return lines


class VHS_VideoFrameGuard:
    """
    Guard node: checks videos total frames (fps_used * duration) <= max_frames
    and filters out clips that are too short for downstream interpolation.
    Designed for lists of paths like Show Text output.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "paths": ("STRING", {"multiline": True, "default": ""}),
                "force_rate_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 0.1}),
                "max_frames": ("INT", {"default": 210, "min": 1, "max": 100000, "step": 1}),
                "raise_on_fail": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("all_ok", "valid_paths", "invalid_paths", "report")
    FUNCTION = "check"
    CATEGORY = "SortList/Video"

    def check(self, paths: str, force_rate_fps: float, max_frames: int, raise_on_fail: bool):
        path_list = _split_paths(paths)

        valid = []
        invalid = []
        report_lines = []
        all_ok = True
        over_limit = []

        for p in path_list:
            dur, fps_meta, nb_frames = _run_ffprobe_duration(p)

            fps_used = float(force_rate_fps) if force_rate_fps and float(force_rate_fps) > 0 else (fps_meta or 30.0)

            # Always calculate frames from force_rate_fps * duration_sec
            if dur is not None and dur > 0:
                est_frames = int(math.ceil(fps_used * dur))
            else:
                est_frames = max_frames + 1  # fail-safe: treat as too long

            too_short = est_frames < MIN_VALID_FRAMES
            over_max = est_frames > int(max_frames)
            ok = (not too_short) and (not over_max)

            if too_short:
                status = "SHORT"
            elif over_max:
                status = "OVER"
            else:
                status = "OK"

            report_lines.append(
                f"{status} | frames={est_frames} | fps_used={fps_used:.3f} | dur={f'{dur:.3f}' if dur is not None else 'NA'} | {p}"
            )

            if ok:
                valid.append(p)
                continue

            invalid.append(p)
            all_ok = False

            if over_max:
                over_limit.append(p)
                if not raise_on_fail:
                    valid.append(p)

        valid_s = "\n".join(valid)
        invalid_s = "\n".join(invalid)
        report_s = "\n".join(report_lines)

        if over_limit and raise_on_fail:
            raise Exception(
                f"[VideoFrameGuard] Found {len(over_limit)} video(s) over {max_frames} frames.\n"
                f"Set raise_on_fail=False if you want to continue.\n\n{invalid_s}"
            )

        return (all_ok, valid_s, invalid_s, report_s)


class VHS_VideoPickMinFrames:
    """
    Pick the video path with the lowest estimated frames from a list of valid paths.
    frames_est = ceil(duration_sec * fps_used)
    fps_used = force_rate_fps if > 0 else fps_from_metadata else 30
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "valid_paths": ("STRING", {"multiline": True, "default": ""}),
                "force_rate_fps": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 240.0, "step": 0.1}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("min_path", "min_frames_est", "report")
    FUNCTION = "pick"
    CATEGORY = "SortList/Video"

    def pick(self, valid_paths: str, force_rate_fps: float):
        paths = _split_paths(valid_paths)

        if not paths:
            return ("", 0, "No valid paths provided.")

        best_path = ""
        best_frames = None
        report_lines = []

        for p in paths:
            dur, fps_meta, nb_frames = _run_ffprobe_duration(p)

            fps_used = float(force_rate_fps) if force_rate_fps and float(force_rate_fps) > 0 else (fps_meta or 30.0)

            # Prefer duration-based estimate; fallback nb_frames; fallback huge (fail-safe)
            if dur is not None and dur > 0:
                frames_est = int(math.ceil(dur * fps_used))
            elif nb_frames is not None:
                frames_est = int(nb_frames)
            else:
                frames_est = 10**9

            report_lines.append(
                f"frames_est={frames_est} | fps_used={fps_used:.3f} | dur={dur if dur is not None else 'NA'} | {p}"
            )

            if best_frames is None or frames_est < best_frames:
                best_frames = frames_est
                best_path = p

        if best_frames is None:
            return ("", 0, "Failed to evaluate any video.")

        return (best_path, int(best_frames), "\n".join(report_lines))
