# 丝袜纹理样例

这里是虚构的 128×160 布料区域引导，不含真实人物图片或作者样图。

- [guides.example.json](guides.example.json)：一个左侧矩形部位、两条弯曲横纹走向线；坐标单位为像素。
- [workflow_api.example.json](workflow_api.example.json)：LoadImage → 引导编辑 → 渲染 → 成品／透明图层／问题标记保存的 API 工作流。请在自己的 ComfyUI input 中放一张 128×160 图片，改 LoadImage 文件名后使用。

API 工作流直接提交其对象为 `/prompt` 请求的 `prompt` 值。它不包含用户图库路径、模型或鉴权。换尺寸需同时更新多边形、走向点和参考宽高；不把旧引导自动套到新图。

日常交互从节点菜单搜索“丝袜纹理”，接图后先运行引导节点以获得预览，打开编辑器、保存，再执行渲染。详细蒙版语义和限制见[技术说明](../../docs/technical/runtime/stocking-texture.md)。
