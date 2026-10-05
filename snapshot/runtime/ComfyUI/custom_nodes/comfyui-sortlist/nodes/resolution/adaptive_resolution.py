"""
Adaptive Resolution Node for ComfyUI
Auto-determines output resolution based on minimum input dimension
"""

class AdaptiveResolution:
    """
    Automatically scales resolution based on input dimensions.
    
    Logic:
    - If min(width, height) <= 720 → Output: 720, batch_size: 7
    - If min(width, height) > 720  → Output: 1080, batch_size: 2
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {
                    "default": 512,
                    "min": 64,
                    "max": 8192,
                    "step": 8,
                    "tooltip": "Input width"
                }),
                "height": ("INT", {
                    "default": 512,
                    "min": 64,
                    "max": 8192,
                    "step": 8,
                    "tooltip": "Input height"
                }),
            },
        }
    
    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("resolution", "batch_size")
    FUNCTION = "calculate_resolution"
    CATEGORY = "utils"
    DESCRIPTION = """
    Automatically determines output resolution and batch size based on input dimensions.
    
    Rules:
    - min(w,h) ≤ 720 → 720p output, batch_size=7
    - min(w,h) > 720 → 1080p output, batch_size=2
    """
    
    def calculate_resolution(self, width, height):
        """
        Calculate output resolution and batch size based on minimum dimension.
        
        Args:
            width: Input width
            height: Input height
            
        Returns:
            tuple: (resolution, batch_size)
                - resolution: 720 or 1080
                - batch_size: 8 for 720p, 3 for 1080p
        """
        min_dimension = min(width, height)
        
        if min_dimension <= 720:
            output_resolution = 720
            batch_size = 7
        else:
            output_resolution = 1080
            batch_size = 2
        
        return (output_resolution, batch_size)


# Node registration
NODE_CLASS_MAPPINGS = {
    "AdaptiveResolution": AdaptiveResolution,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AdaptiveResolution": "Adaptive Resolution 📐",
}
