class MaxFramesByResolution:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "resolution": ("INT", {"default": 720, "min": 240, "max": 4320, "step": 8}),
            }
        }

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("max_frames",)
    FUNCTION = "get_max_frames"
    CATEGORY = "sortlist"

    def get_max_frames(self, resolution: int):
        # Mức an toàn cho WanVideo Sampler trên RTX 6000 96GB VRAM
        mapping = {
            480: 489,
            720: 257
        }
        
        if resolution in mapping:
            return (mapping[resolution],)
        
        # Ước lượng cho các độ phân giải khác dựa trên tỷ lệ diện tích
        ratio = (720.0 / resolution) ** 2
        raw_max = 257 * ratio
        
        # Làm tròn xuống bộ số của 4n+1
        n = int((raw_max - 1) / 4)
        max_frames = max(1, 4 * n + 1)
        
        return (max_frames,)


NODE_CLASS_MAPPINGS = {
    "MaxFramesByResolution": MaxFramesByResolution,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MaxFramesByResolution": "Max Frames By Resolution (RTX 6000)"
}
