from .nodes import PixAITagger

NODE_CLASS_MAPPINGS = {"PixAITagger": PixAITagger}
NODE_DISPLAY_NAME_MAPPINGS = {"PixAITagger": "PixAI Tagger v1.0"}
WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
