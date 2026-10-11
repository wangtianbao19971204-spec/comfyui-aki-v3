# Stocking Texture for ComfyUI

在 ComfyUI 中使用 [Silvermoong 的 Stocking Texture Tool](https://github.com/silvermoong/stocking-texture-tool) 编辑器，为已有图片绘制织纹、引导与选区，然后保存成品及透明纹理图层。

这是独立维护的实验性宿主适配。核心算法、样式和编辑器归原项目贡献者；上游不负责本适配层维护。接入代码几乎全部由 AI 编程助手在用户指导下编写，需要人工审查。双方的 MIT 许可与原作者署名保留。

## 安装

将本仓库克隆或解压至 `ComfyUI/custom_nodes/stocking-texture-comfyui`，在运行 ComfyUI 的 Python 环境安装 `integrations/comfyui/requirements.txt`，然后重启 ComfyUI。请先移出其他提供同名 `StockingTexture*` 节点的插件副本，避免重复注册。

加载[独立工作流](integrations/comfyui/examples/stocking-repair.json)，打开完整编辑器，导入图片、修正选区、绘制走向并调整纹理，再“应用到节点”并执行工作流。工作流不需要扩散模型或工作台插件。SAM 与深度权重由用户另行准备，手绘选区不依赖这些权重。

## 固定依赖与升级

上游固定提交：`{{UPSTREAM_COMMIT}}`。原始 Git blob 的拷贝位于 `integrations/comfyui/upstream/stocking/`；[UPSTREAM.json](integrations/comfyui/UPSTREAM.json) 记录每个源文件的 SHA256。没有浮动引用，无需 submodule。`vendor/` 仅提供独立模块命名空间及本地 i18n 适配，不改原版源文件。

维护者升级时，先单独取得上游对象，再显式指定完整 SHA：

```text
git ls-remote https://github.com/silvermoong/stocking-texture-tool.git refs/heads/main
git clone --no-checkout https://github.com/silvermoong/stocking-texture-tool.git /path/to/upstream-objects
python integrations/comfyui/sync_upstream.py --repo /path/to/upstream-objects --commit FULL_40_CHARACTER_SHA
python -m unittest discover -s integrations/comfyui/tests -p "test_*.py"
node --test integrations/comfyui/tests/test_editor.cjs integrations/comfyui/tests/test_studio_editor.cjs
```

同步脚本只读取 `stocking/` 的已知源文件类型和 LICENSE，不读取上游开发材料，不启动原服务，不修改上游 checkout。升级须重新验证前端接入点、接口契约、干净 ComfyUI 安装和实际编辑效果，再发布新的固定版本。素材缺失导致的跳过单独报告。

更多[使用说明与限制](integrations/comfyui/README.md)、[模型来源](integrations/comfyui/MODEL_SOURCES.json)、[既有人工修正选区的展示](integrations/comfyui/SHOWCASE.md)。展示图属于注明版本的历史结果，不代替新版本验收。
