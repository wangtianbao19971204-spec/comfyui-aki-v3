"""
WanAnimate Frame Window Size Calculator
Tinh frame_window_size (x) toi uu tu tong so frame.

Cong thuc WanAnimate DUNG:
  output_frames = 1 + n * (x - 1)

  Giai thich: moi window chong lap 1 frame voi window truoc (refert_num=1),
  nen stride thuc te = x - 1 (khong phai x).
  WanAnimate tu tinh n = ceil((total_frames - 1) / (x - 1)).

Wan VAE yeu cau:  x = 4k+1  (k=0,1,2,...) => {1,5,9,13,...,117,121}
Rang buoc:        x <= 121  (x_max = 121)

Thuat toan tim x toi uu (it frame thua nhat):
  Voi moi x hop le trong [min_window_size, X_MAX]:
    stride = x - 1
    n = ceil((total_frames - 1) / stride)
    output = 1 + n * stride
    waste = output - total_frames
  => chon x cho waste nho nhat.

Vi du (total=453, min_window_size=77 mac dinh):
  x=77  -> stride=76, n=ceil(452/76)=6 -> output=1+6*76=457  (waste=4)  <- TOT
  x=113 -> stride=112, n=ceil(452/112)=5 -> output=1+5*112=561 (waste=108) <- Lang phi!

Node 2 (WanTrimFrames): cat bo frame thua, giu lai dung total_frames frame.
"""
import math
# torch imported lazily inside WanTrimFrames.trim() to allow standalone testing


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_4k1(n: int) -> int:
    """Tìm số nhỏ nhất dạng 4k+1 mà >= n.
       Dãy: 1, 5, 9, 13, ..., 89, 93, 97, 101, ...
    """
    if n <= 1:
        return 1
    # k = ceil((n-1)/4)
    k = (n - 2) // 4 + 1   # equivalent to ceil((n-1)/4) for n >= 2
    return 4 * k + 1


# ── Node 1: WanFrameWindowSize ────────────────────────────────────────────────

class WanFrameWindowSize:
    """
    Tính frame_window_size (x) cho WanAnimate:
      • x phải có dạng 4k+1  (yêu cầu của Wan VAE)
      • x <= 121  (x_max = 121)
      • Công thức ĐÚNG: output = 1 + n * (x - 1)   [stride = x-1 do overlap 1 frame]
      • WanAnimate tự tính n = ceil((total_frames - 1) / (x - 1))
      • Tìm x trong [min_window_size, X_MAX] cho ít frame thừa nhất
    """

    X_MAX = 121  # max valid 4k+1 <= 121 (4*30+1=121)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_frames": ("INT", {
                    "default": 81,
                    "min": 1,
                    "max": 99999,
                    "step": 1,
                    "tooltip": "Tổng số frame của video input",
                }),
                "min_window_size": ("INT", {
                    "default": 93,
                    "min": 5,
                    "max": 121,
                    "step": 4,
                    "tooltip": (
                        "Window size nho nhat (4k+1). Default=93.\n"
                        "Khuyen nghi: 93-113 cho chat luong WanAnimate tot nhat."
                    ),
                }),
                "max_window_size": ("INT", {
                    "default": 113,
                    "min": 5,
                    "max": 121,
                    "step": 4,
                    "tooltip": (
                        "Window size lon nhat (4k+1). Default=113.\n"
                        "Window nho hon 90 => chat luong kem.\n"
                        "Window lon hon 114 => lang phi frames nhieu."
                    ),
                }),
            },
        }

    RETURN_TYPES  = ("INT", "INT", "INT", "INT")
    RETURN_NAMES  = ("frame_window_size", "output_frames", "frame_diff", "n_used")
    FUNCTION      = "calculate"
    CATEGORY      = "utils"
    DESCRIPTION   = (
        "Tinh frame_window_size (x = 4k+1) toi uu cho WanAnimate.\n"
        "Cong thuc dung: output = 1 + n*(x-1)  (stride = x-1, overlap 1 frame).\n"
        "Tim x trong [min_window_size, max_window_size] cho it frame thua nhat.\n"
        "Khuyen nghi: 93 <= x <= 113 cho chat luong tot.\n"
        "frame_diff = output_frames - total_frames (so frame thua can trim)."
    )

    def calculate(self, total_frames: int, min_window_size: int = 93, max_window_size: int = 113):
        # Special case: 1 frame
        if total_frames <= 1:
            print("[WanFrameWindow] total=1 -> x=1, n=1")
            return (1, 2, 1, 1)

        # Special case: total_frames fits in 1 window even below min_window_size
        # Use next 4k+1 >= total_frames (1 window, output = x >= total_frames)
        x_single = _next_4k1(total_frames)
        if x_single <= self.X_MAX and x_single < min_window_size:
            # Video short enough: 1 window with smallest valid x
            output = x_single          # = 1 + 1*(x_single - 1) = x_single
            diff   = output - total_frames
            print(f"[WanFrameWindow] total={total_frames} -> n=1 (short video)"
                  f" -> x={x_single} (4*{(x_single-1)//4}+1), output={output} (diff={diff:+d})")
            return (x_single, output, diff, 1)

        # Normalise min_window_size to the nearest valid 4k+1 >= min_window_size
        min_k = math.ceil((min_window_size - 1) / 4)
        min_k = max(1, min_k)   # x >= 5

        # Core algorithm:
        # WanAnimate formula: output = 1 + n * (x - 1)  [stride = x-1, 1-frame overlap]
        # WanAnimate computes n internally: n = ceil((total_frames - 1) / (x - 1))
        # => output = 1 + ceil((total_frames - 1) / (x-1)) * (x-1)
        # Search all valid x in [min_window_size, X_MAX] and pick the one with least waste.
        best_x = best_output = best_diff = best_n = None

        # Clamp max_window_size to a valid 4k+1 <= X_MAX
        max_k = min(30, (max_window_size - 1) // 4)   # largest k so that 4k+1 <= max_window_size
        if max_k < min_k:
            max_k = min_k  # safety: ensure at least one candidate

        for k in range(min_k, max_k + 1):  # x = 4k+1, within [min_window_size, max_window_size]
            x = 4 * k + 1
            if x > self.X_MAX:
                break
            stride = x - 1
            n = math.ceil((total_frames - 1) / stride)
            output = 1 + n * stride
            diff = output - total_frames    # always >= 0

            if best_diff is None or diff < best_diff:
                best_diff   = diff
                best_x      = x
                best_output = output
                best_n      = n

            if diff == 0:
                break   # perfect fit — can't do better

        # Fallback: no valid x found (e.g. constraints too tight)
        if best_x is None:
            x_fb = 4 * max_k + 1
            best_x = x_fb
            best_n = math.ceil((total_frames - 1) / (x_fb - 1))
            best_output = 1 + best_n * (x_fb - 1)
            best_diff = best_output - total_frames

        print(
            f"[WanFrameWindow] total={total_frames}"
            f" -> n={best_n}, x={best_x} (4*{(best_x-1)//4}+1)"
            f" -> output={best_output} (diff={best_diff:+d}, trim {best_diff} frames)"
        )
        return (best_x, best_output, best_diff, best_n)


# ── Node 2: WanTrimFrames ─────────────────────────────────────────────────────

class WanTrimFrames:
    """
    Cắt bỏ frame thừa ở cuối, giữ lại đúng total_frames frame đầu tiên.

    WanVideo sampling tạo ra output_frames = x*n+1 frames, nhưng video gốc
    chỉ có total_frames frames. Node này trả về đúng total_frames frame
    (frame 0 → frame total_frames-1), loại bỏ frame thừa ở cuối.

    Ví dụ:
      x=93, n=4 → output = 93*4+1 = 373 frames
      total_frames = 357
      → giữ lại frame 0–356, loại frame 357–372 (16 frame cuối)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {
                    "tooltip": "Batch ảnh từ WanVideo decode (shape: [F, H, W, C])",
                }),
                "total_frames": ("INT", {
                    "default": 81,
                    "min": 1,
                    "max": 99999,
                    "step": 1,
                    "tooltip": "Số frame gốc cần giữ lại (từ WanFrameWindowSize → output_frames hoặc total_frames gốc)",
                }),
            },
        }

    RETURN_TYPES  = ("IMAGE", "INT")
    RETURN_NAMES  = ("images", "frames_kept")
    FUNCTION      = "trim"
    CATEGORY      = "utils"
    DESCRIPTION   = (
        "Giữ lại đúng total_frames frame đầu (frame 0 → total_frames-1).\n"
        "Loại bỏ frame dư ở cuối do WanVideo sampling tạo thêm.\n"
        "Dùng sau WanVideo Decode kết hợp với WanFrameWindowSize."
    )

    def trim(self, images, total_frames: int):
        """
        images: torch.Tensor shape [F, H, W, C]  (lazy import)
        total_frames: số frame cần giữ
        """
        import torch  # lazy — only loaded inside ComfyUI environment
        F = images.shape[0]

        if total_frames >= F:
            # Không cần trim (hoặc video ngắn hơn dự kiến)
            print(
                f"[WanTrimFrames] total_frames={total_frames} >= available={F}"
                f" → giữ nguyên {F} frame"
            )
            return (images, F)

        trimmed = images[:total_frames]
        removed = F - total_frames

        print(
            f"[WanTrimFrames] {F} → {total_frames} frame"
            f" (loại bỏ {removed} frame cuối: frame {total_frames}–{F-1})"
        )

        return (trimmed, total_frames)


# ── Registration ──────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "WanFrameWindowSize": WanFrameWindowSize,
    "WanTrimFrames":      WanTrimFrames,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanFrameWindowSize": "Wan Frame Window Size 🎞️",
    "WanTrimFrames":      "Wan Trim Frames ✂️",
}


# ── Standalone test (python wan_frame_window.py) ──────────────────────────────
if __name__ == "__main__":
    node = WanFrameWindowSize()
    tests = [
        1, 2, 5, 10, 81, 97, 98, 99, 101, 102,
        357, 373, 388, 389, 453, 561, 700, 1000, 5000,
    ]
    print(f"{'total':>6} | {'x':>4} {'n':>4} {'output':>7} {'waste':>6}  check (formula: 1+n*(x-1))")
    print("-" * 65)
    for tf in tests:
        x, out, diff, n = node.calculate(tf, min_window_size=77)
        # verify: output = 1 + n*(x-1) >= total, x is 4k+1, x<=121
        expected_out = 1 + n * (x - 1)
        ok = "OK" if (x == 4*((x-1)//4)+1 and x <= 121 and out >= tf and out == expected_out) else "FAIL"
        print(f"{tf:>6} | {x:>4} {n:>4} {out:>7} {diff:>+6}  {ok} x=4*{(x-1)//4}+1")
    print()
    print("Bug reproduction (old formula x*n+1 vs correct 1+n*(x-1)):")
    tf = 453; x, out, diff, n = node.calculate(tf, min_window_size=77)
    print(f"  total={tf}: x={x}, n={n}, output(correct)={out}, waste={diff}")
    print(f"  Old bug: x=113,n=4 -> old_formula=113*4+1=453, actual=1+5*112=561 (waste=108)")
