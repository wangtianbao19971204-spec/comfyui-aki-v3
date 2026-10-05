import os
import tempfile
import subprocess
import random
import requests
import hashlib
import socket
import time
import threading

LICENSE_SERVER = "https://license.xgroup-service.com/api/validate"
LICENSE_HEARTBEAT = "https://license.xgroup-service.com/api/heartbeat"
LICENSE_TIMEOUT = 5

_LICENSE_CACHE = {}
_SESSION_CACHE = {}
_CACHE_TTL_SECONDS = 300

_HEARTBEAT_THREADS = {}
_HEARTBEAT_LOCK = threading.Lock()
_HEARTBEAT_INTERVAL_SECONDS = 20


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def get_user_id() -> str:
    drive_path = "/content/drive/MyDrive"
    try:
        if os.path.exists(drive_path):
            st = os.stat(drive_path)
            raw = f"colab_drive:{st.st_dev}:{st.st_ino}"
            return _sha256_hex(raw)[:16]
    except Exception:
        pass

    try:
        home = os.path.expanduser("~")
        raw = f"local:{home}:{socket.gethostname()}"
        return _sha256_hex(raw)[:16]
    except Exception:
        return "local-user"


def get_or_create_session_id(license_key: str, user_id: str) -> str:
    k = f"{license_key.strip()}:{user_id}"
    if k in _SESSION_CACHE:
        return _SESSION_CACHE[k]
    sid = _sha256_hex(k + ":" + str(time.time()))[:16]
    _SESSION_CACHE[k] = sid
    return sid


def _ensure_heartbeat(cache_key: str, license_key: str, user_id: str, session_id: str):
    if not license_key or not user_id or not session_id:
        return

    with _HEARTBEAT_LOCK:
        if _HEARTBEAT_THREADS.get(cache_key):
            return
        _HEARTBEAT_THREADS[cache_key] = True

    def _loop():
        while True:
            try:
                requests.post(
                    LICENSE_HEARTBEAT,
                    json={"key": license_key, "user_id": user_id, "session_id": session_id},
                    timeout=LICENSE_TIMEOUT
                )
            except Exception:
                pass
            time.sleep(_HEARTBEAT_INTERVAL_SECONDS)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def check_license_shared(license_key: str, max_retries: int = 3) -> dict:
    license_key = (license_key or "").strip()
    if not license_key:
        return {"valid": False}

    user_id = get_user_id()
    cache_key = f"{license_key}:{user_id}"
    session_id = get_or_create_session_id(license_key, user_id)

    now = time.time()
    cached = _LICENSE_CACHE.get(cache_key)
    if cached and (now - cached["ts"] <= _CACHE_TTL_SECONDS):
        if cached.get("valid"):
            _ensure_heartbeat(cache_key, license_key, user_id, session_id)
        return {"valid": bool(cached.get("valid"))}


    valid = False
    for attempt in range(max_retries):
        try:
            r = requests.post(
                LICENSE_SERVER,
                json={"key": license_key, "user_id": user_id, "session_id": session_id},
                timeout=LICENSE_TIMEOUT
            )
            data = r.json() if r.content else {}
            valid = bool(data.get("valid"))
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.5)
            else:

                pass

    _LICENSE_CACHE[cache_key] = {"valid": valid, "ts": now}

    if valid:
        _ensure_heartbeat(cache_key, license_key, user_id, session_id)

    return {"valid": valid}


class VideoDirCombiner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "video_list": ("STRING", {"multiline": True}),
                "directory_path": ("STRING", {"default": ""}),
                "output_filename": ("STRING", {"default": "output.mp4"}),
                "license_key": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_path",)
    FUNCTION = "run"
    CATEGORY = "video"

    def _create_fake_video(self, output_dir, output_name, duration: int = 5):
        if not output_name.endswith(".mp4"):
            output_name += ".mp4"
        
        output_dir = output_dir if output_dir else "."
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_name)
        

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"color=c=black:s=640x480:d={duration}",
                    "-vf", f"geq=random(1)*255:random(1)*255:random(1)*255",
                    "-t", str(duration),
                    "-pix_fmt", "yuv420p",
                    output_path
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        except Exception:

            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"color=c=black:s=640x480:d={duration}",
                    "-t", str(duration),
                    output_path
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        
        return (output_path,)

    def _merge_videos(self, video_paths, output_dir, output_name):
        if not output_name.endswith(".mp4"):
            output_name += ".mp4"

        output_dir = output_dir if output_dir else "."
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_name)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for v in video_paths:
                f.write(f"file '{v}'\n")
            list_file = f.name

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                output_path
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        return (output_path,)

    def run(self, image, video_list, directory_path, output_filename, license_key):
        videos = [v.strip() for v in video_list.split("\n") if v.strip()]
        if not videos:
            raise ValueError("video_list is empty")

        license_result = check_license_shared(license_key, max_retries=3)
        if not license_result.get("valid"):
            return self._create_fake_video(directory_path, output_filename, duration=5)


        return self._merge_videos(videos, directory_path, output_filename)


NODE_CLASS_MAPPINGS = {
    "video_dir_combiner": VideoDirCombiner
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "video_dir_combiner": "Video Dir Combiner"
}
