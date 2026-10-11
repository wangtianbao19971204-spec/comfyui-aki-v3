from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .native_loader import AnimaLLLiteModelLoader

NODE_CLASS_MAPPINGS["AnimaLLLiteModelLoader"] = AnimaLLLiteModelLoader
NODE_DISPLAY_NAME_MAPPINGS["AnimaLLLiteModelLoader"] = "Load Anima LLLite (controlnet folder)"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
