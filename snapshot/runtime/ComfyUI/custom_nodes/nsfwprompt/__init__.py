from .NSFWPromptSelector_LocalMerged import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

try:
    from .NSFWPromptSelector_LocalMerged import WEB_DIRECTORY
except Exception:
    WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
