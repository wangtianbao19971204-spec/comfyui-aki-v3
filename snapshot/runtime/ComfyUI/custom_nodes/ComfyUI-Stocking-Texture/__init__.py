"""丝袜纹理的独立编辑与后处理节点。

只注册节点和本地前端；不启动服务、不下载模型、不安装依赖。
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .studio_nodes import StockingTextureStudio

NODE_CLASS_MAPPINGS["StockingTextureStudio"] = StockingTextureStudio
NODE_DISPLAY_NAME_MAPPINGS["StockingTextureStudio"] = "丝袜纹理 · 完整编辑器"

try:
    from server import PromptServer
except ModuleNotFoundError as exc:
    if exc.name != "server":
        raise
else:
    from .studio_api import register_routes
    register_routes(PromptServer.instance)

WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
