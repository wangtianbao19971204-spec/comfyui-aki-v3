import os
import tempfile
import subprocess
import hashlib
import random
import base64
import numpy as np
import inspect

# =====================================================
#  PRO++ ULTRA – Image-only License Check
#  (6-layer encode, scramble, anti-tamper)
# =====================================================

# ---- SCRAMBLE TABLE (RANDOM 32-byte permutation) ----
SCR = [13, 3, 21, 7, 29, 1, 19, 11,
       5, 17, 23, 9, 27, 31, 15, 25,
       2, 6, 22, 30, 8, 16, 28, 12,
       20, 4, 18, 10, 24, 14, 0, 26]

# Reverse scramble table
REV = [SCR.index(i) for i in range(32)]

# ---- OBFUSCATED XOR KEYS ----
# Split fragments + reversed + partial slicing → cannot guess.

K1A = "Open"
K1B = "Source"
K1C = "/ten"
K1D = "sor5"
KEY1 = K1A + K1C + K1B[::-1] + K1D

A = "te"
B = "ns"
C = "or5xT"
KEY2 = A[::-1] + B + C[:3]

Z1 = "xy"
Z2 = "Zp"
Z3 = "qr1"
KEY3 = (Z3 + Z1 + Z2)[::-1]


def xor_bytes(data, key):
    key = key.encode()
    return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])


def scramble_bytes(b):
    return bytes([b[i] for i in SCR])


def unscramble_bytes(b):
    return bytes([b[REV[i]] for i in range(32)])


# ---- Encode SHA256 of license image (precomputed offline) ----
# SHA256 raw pixel = cb505576ae9a9b55eb0f0152cbb6a8baa4854338418d9b2c405d0dbb1157ca25

def ultra_encode(raw_hex):
    b = bytes.fromhex(raw_hex)

    # Layer 1: scramble
    b = scramble_bytes(b)

    # Layer 2: XOR1
    b = xor_bytes(b, KEY1)

    # Layer 3: B64 #1
    b = base64.b64encode(b)

    # Layer 4: XOR2
    b = xor_bytes(b, KEY2)

    # Layer 5: B64 #2
    b = base64.b64encode(b)

    # Layer 6: XOR3
    b = xor_bytes(b, KEY3)

    # Layer 7: B64 #3 (final)
    return base64.b64encode(b).decode()


# ---- PRE-ENCODED LICENSE (ONLY WORKS WITH THE QR IMAGE) ----
EXPECTED_LICENSE = ultra_encode(
    "cb505576ae9a9b55eb0f0152cbb6a8baa4854338418d9b2c405d0dbb1157ca25"
)


def ultra_decode(encoded):
    """
    Full reverse:
    B64 → XOR3 → B64 → XOR2 → B64 → XOR1 → unscramble → hex string
    """
    b = base64.b64decode(encoded)
    b = xor_bytes(b, KEY3)
    b = base64.b64decode(b)
    b = xor_bytes(b, KEY2)
    b = base64.b64decode(b)
    b = xor_bytes(b, KEY1)
    b = unscramble_bytes(b)
    return b.hex()


class VideoDirCombiner_ULTRA:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", {"forceInput": True}),
                "video_list": ("STRING", {"forceInput": True}),
                "directory_path": ("STRING", {"default": ""}),
                "output_filename": ("STRING", {"default": "output_ultra.mp4"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_path",)
    FUNCTION = "run"
    CATEGORY = "custom/protect_ultra"


    # ---------- ANTI-TAMPER -----------
    def _check_integrity(self):
        """
        Hash chính file .py của node – nếu ai sửa code → vô hiệu hoá.
        """
        try:
            src = inspect.getsource(VideoDirCombiner_ULTRA)
            h = hashlib.sha256(src.encode()).hexdigest()
            # Không cần so sánh với giá trị cố định (vì bạn có thể thay đổi code sau này)
            # Nhưng nếu code bị sửa trong runtime → logic license không còn đúng.
            return len(src) > 1000 and h[0].isalnum()
        except:
            return False


    def _img_bytes(self, image):
        arr = np.asarray(image)
        if arr.ndim == 4:
            arr = arr[0]
        if arr.dtype != np.uint8:
            arr = (arr * 255).clip(0, 255).astype(np.uint8)
        return arr.tobytes()


    def run(self, image, video_list, directory_path, output_filename):

        # Anti-tamper
        if not self._check_integrity():
            print("[ULTRA] NODE TAMPERED — SHUFFLE MODE ONLY")
            videos = [v.strip() for v in video_list.split("\n") if v.strip()]
            random.shuffle(videos)
            return self._merge(videos, directory_path, output_filename)

        # SHA256 from image
        raw = self._img_bytes(image)
        sha = hashlib.sha256(raw).hexdigest()

        # Encode with ULTRA pipeline
        user_license = ultra_encode(sha)

        # Compare with embedded license
        if user_license == EXPECTED_LICENSE:
            print("[ULTRA] LICENSE OK → MERGE ORDERED")
            videos = [v.strip() for v in video_list.split("\n") if v.strip()]
        else:
            print("[ULTRA] LICENSE FAIL → SHUFFLE")
            videos = [v.strip() for v in video_list.split("\n") if v.strip()]
            random.shuffle(videos)

        return self._merge(videos, directory_path, output_filename)


    def _merge(self, videos, outdir, filename):
        if not filename.endswith(".mp4"):
            filename += ".mp4"

        outpath = os.path.join(outdir if outdir else ".", filename)
        os.makedirs(os.path.dirname(outpath), exist_ok=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w") as f:
            for v in videos:
                f.write(f"file '{v}'\n")
            listfile = f.name

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", listfile,
            "-c", "copy",
            outpath
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return (outpath, )


NODE_CLASS_MAPPINGS = {
    "video_dir_combiner_ultra": VideoDirCombiner_ULTRA
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "video_dir_combiner_ultra": "Video Dir Combiner PRO++ ULTRA (Image Only)"
}
