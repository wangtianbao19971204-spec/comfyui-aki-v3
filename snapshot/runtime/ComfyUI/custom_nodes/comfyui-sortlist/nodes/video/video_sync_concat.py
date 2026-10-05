import torch
from comfy.utils import common_upscale
import math


class VideoSyncConcatenate:
    """
    Gộp 2 video (batch ảnh) thành 1 video ghép cạnh nhau hoặc trên dưới,
    đồng bộ theo thời gian thực:
      - 1 giây video A hiện đúng cùng lúc với 1 giây video B
      - Video ngắn hơn sẽ được đệm khung đen (black frame) cho đến khi video dài hơn kết thúc
      - Tự động chọn hướng nối: W <= H → right, W > H → down
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images_a":  ("IMAGE",),
                "fps_a":     ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 0.01}),
                "images_b":  ("IMAGE",),
                "fps_b":     ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 0.01}),
                "output_fps": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("image", "frame_count", "fps", "info")
    FUNCTION = "sync_concat"
    CATEGORY = "sortlist"

    def _resize_to_match(self, src: torch.Tensor, target_h: int, target_w: int) -> torch.Tensor:
        """Resize một frame (1, H, W, C) về kích thước mục tiêu."""
        bchw = src.movedim(-1, 1)          # (1, C, H, W)
        resized = common_upscale(bchw, target_w, target_h, "lanczos", "disabled")
        return resized.movedim(1, -1)      # (1, H, W, C)

    def sync_concat(self, images_a, images_b, fps_a, fps_b, output_fps):
        n_a = images_a.shape[0]
        n_b = images_b.shape[0]

        dur_a = n_a / fps_a   # giây
        dur_b = n_b / fps_b   # giây
        max_dur = max(dur_a, dur_b)

        total_frames = math.ceil(max_dur * output_fps)

        # Kích thước gốc của mỗi video
        h_a, w_a = images_a.shape[1], images_a.shape[2]
        h_b, w_b = images_b.shape[1], images_b.shape[2]
        c_a = images_a.shape[3]
        c_b = images_b.shape[3]

        # Xác định hướng ghép dựa trên video A
        if w_a <= h_a:
            direction = "right"  # dọc / vuông -> ghép ngang
        else:
            direction = "down"   # ngang -> ghép dọc

        # Resize video B về cùng H/W với video A (match_image_size logic)
        if direction in ("right", "left"):
            target_h_b = h_a
            orig_ar_b = w_b / h_b
            target_w_b = int(target_h_b * orig_ar_b)
        else:
            target_w_b = w_a
            orig_ar_b = w_b / h_b
            target_h_b = int(target_w_b / orig_ar_b)

        # Chuẩn bị khung đen (black) cho từng video
        black_a = torch.zeros((1, h_a, w_a, c_a), dtype=images_a.dtype)
        black_b = torch.zeros((1, target_h_b, target_w_b, max(c_a, c_b)), dtype=images_b.dtype)

        def get_frame_a(idx):
            if idx >= n_a:
                return black_a
            return images_a[idx:idx+1]

        def get_frame_b(idx):
            if idx >= n_b:
                return black_b
            # Resize frame B để khớp với hướng ghép
            frame = images_b[idx:idx+1]
            frame = self._resize_to_match(frame, target_h_b, target_w_b)
            return frame

        # Đồng bộ số kênh (nếu A=3 channels, B=4 channels thì pad A)
        def normalize_channels(fa, fb):
            ca = fa.shape[-1]
            cb = fb.shape[-1]
            if ca == cb:
                return fa, fb
            if ca < cb:
                pad = torch.ones((*fa.shape[:-1], cb - ca), dtype=fa.dtype, device=fa.device)
                fa = torch.cat((fa, pad), dim=-1)
            else:
                pad = torch.ones((*fb.shape[:-1], ca - cb), dtype=fb.dtype, device=fb.device)
                fb = torch.cat((fb, pad), dim=-1)
            return fa, fb

        out_frames = []
        for i in range(total_frames):
            t = i / output_fps

            # Index trong mỗi video
            idx_a = min(int(t * fps_a), n_a)   # n_a = out-of-range → black
            idx_b = min(int(t * fps_b), n_b)   # n_b = out-of-range → black

            fa = get_frame_a(idx_a)
            fb = get_frame_b(idx_b)
            fa, fb = normalize_channels(fa, fb)

            if direction == "right":
                frame = torch.cat((fa, fb), dim=2)   # nối theo W
            elif direction == "left":
                frame = torch.cat((fb, fa), dim=2)
            elif direction == "down":
                frame = torch.cat((fa, fb), dim=1)   # nối theo H
            else:  # up
                frame = torch.cat((fb, fa), dim=1)

            out_frames.append(frame)

        result = torch.cat(out_frames, dim=0)

        info = (
            f"Direction: {direction} | "
            f"A: {n_a}f @ {fps_a}fps = {dur_a:.2f}s | "
            f"B: {n_b}f @ {fps_b}fps = {dur_b:.2f}s | "
            f"Output: {total_frames}f @ {output_fps}fps = {max_dur:.2f}s"
        )

        return (result, total_frames, output_fps, info)


NODE_CLASS_MAPPINGS = {
    "VideoSyncConcatenate": VideoSyncConcatenate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoSyncConcatenate": "Video Sync Concatenate (Side by Side)",
}
