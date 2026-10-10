"""One full-editor node; existing Guides/Render workflows remain supported."""
from pathlib import Path
import hashlib
import uuid

import numpy as np
from PIL import Image
import torch

from .nodes import depth_array, image_array
from .studio import Studio
from . import studio_models as models
from . import studio_store as store


class StockingTextureStudio:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_json": ("STRING", {"default": "{}", "multiline": True,
                              "dynamicPrompts": False, "tooltip": "由完整编辑器保存，无需手工填写"})},
                "optional": {"image": ("IMAGE",), "depth": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "IMAGE", "STRING")
    RETURN_NAMES = ("成品", "仅丝袜透明图层", "图层透明度", "问题标记", "处理说明")
    FUNCTION = "render"
    CATEGORY = "image/丝袜纹理"
    OUTPUT_NODE = True
    DESCRIPTION = "接图后运行一次并打开完整编辑器，或直接导入 PNG/JPG/PSD。支持六样式、SAM、画笔、预设、深度、分屏预览和 PSD 导出。应用到节点后运行输出。"

    def render(self, project_json="{}", image=None, depth=None):
        import folder_paths
        project = store.parse_project(project_json)
        array = image_array(image) if image is not None else None
        if array is not None and len(array) != 1:
            raise ValueError("完整编辑器一次处理一张图；批量处理请使用原有引导/渲染节点")
        art = np.round(array[0, ..., :3] * 255).astype(np.uint8) if array is not None else None
        root = Path(folder_paths.get_input_directory()) / "stocking_studio/assets"
        # Node execution reads the self-contained annotations, not another editor's live session.
        preferences = store.Preferences(Path(folder_paths.get_user_directory()) / "default/stocking_texture")
        studio = Studio(root, preferences, models.paths(), project, art=art)
        try:
            if studio.doc is None:
                raise ValueError("请连接原图后运行，或点击完整编辑器导入图片/PSD")
            if depth is not None and studio.depth_enabled:
                studio.doc.disparity = depth_array(depth, 1, studio.doc.h, studio.doc.w, "近处较亮")[0]
                studio.depth_status = "ready"
            # The first run only supplies the editor image; drawing by hand must
            # remain available even on machines without the optional models.
            if not project:
                studio.depth_enabled = False
            rgb, layer, check, report = studio.outputs()
            output = rgb.astype(np.float32) / 255
            if array is not None and array.shape[-1] == 4:
                output = np.dstack((output, array[0, ..., 3]))
            if not project:
                studio.depth_enabled = True
                report["message"] = "请打开完整编辑器，应用编辑后重新运行节点"
            saved = studio.project_data()
            temp = Path(folder_paths.get_temp_directory())
            temp.mkdir(parents=True, exist_ok=True)
            name = f"stocking_studio_{uuid.uuid4().hex}.png"
            Image.fromarray(rgb).save(temp / name)
            result = (torch.from_numpy(output[None]), torch.from_numpy(layer[None].astype(np.float32) / 255),
                      torch.from_numpy(layer[None, ..., 3].astype(np.float32) / 255),
                      torch.from_numpy(check[None].astype(np.float32) / 255), store.dumps(report))
            return {"ui": {"images": [{"filename": name, "subfolder": "", "type": "temp"}],
                           "stocking_studio": [{"project": saved,
                             "source_hash": hashlib.sha256(project_json.encode("utf-8")).hexdigest()}]}, "result": result}
        finally:
            studio.close()
