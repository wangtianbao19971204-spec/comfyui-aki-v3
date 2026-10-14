# Stocking Texture for ComfyUI

在 ComfyUI 中使用 [Silvermoong 的 Stocking Texture Tool](https://github.com/silvermoong/stocking-texture-tool) 编辑器，为已有图片绘制织纹、引导与选区，然后保存成品及透明纹理图层。

这是独立维护的实验性宿主适配。核心算法、样式和编辑器归原项目贡献者；上游不负责本适配层维护。接入代码几乎全部由 AI 编程助手在用户指导下编写，需要人工审查。双方的 MIT 许可与原作者署名保留。

## 安装

将本仓库克隆或解压至 `ComfyUI/custom_nodes/stocking-texture-comfyui`，在运行 ComfyUI 的 Python 环境安装 `integrations/comfyui/requirements.txt`，然后重启 ComfyUI。请先移出其他提供同名 `StockingTexture*` 节点的插件副本，避免重复注册。

加载[独立工作流](integrations/comfyui/examples/stocking-repair.json)，打开完整编辑器，导入图片、修正选区、绘制走向并调整纹理，再“应用到节点”并执行工作流。工作流不需要扩散模型或工作台插件。SAM 与深度权重由用户另行准备，手绘选区不依赖这些权重。

## 计算设备与缓存

完整编辑器默认选择 GPU，也可在顶部切换到 CPU；设置控制 SAM 点选、内置深度和走向求解。走向的 CUDA 13 加速依赖见 [requirements-cuda13.txt](integrations/comfyui/requirements-cuda13.txt)，需在 ComfyUI 的 Python 环境安装匹配版本。依赖缺失、队列忙、显存不足或求解失败时自动回到 CPU，界面显示实际设备与回退原因。

离开或关闭最后一个活跃编辑页面后，释放插件缓存的 SAM、深度模型和图像特征；正在推理时延后到任务结束。草稿、已算好的深度和磁盘模型保持。框架分配器与 CUDA 上下文可能继续占用内存，不能以进程内存未归零判断模型未释放。

2026-10-11 整合验收：78 项 Python 测试（含实际 CUDA）、17 项前端测试、51 项 CPU HTTP 对照通过。三张真实图片的六种样式共 18 组，CPU 与固定上游逐像素一致；GPU 求解有浮点差异，本次样例最大单通道差异为 9/255，局部目视复核未见明显结构变化。需要精确对照上游时请选择 CPU。实页已验证设备切换、真实 SAM／深度推理、关闭重开和导航离开后回收缓存；这些结果不代表所有硬件、姿势和图片均已验收。

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

发布目录的 `.gitattributes` 固定文本文件为 LF，即使 Windows 开启 `core.autocrlf=true` 也能校验原始 SHA。编辑器 iframe 使用同源自有代码，同时允许 scripts 和 same-origin；它是界面嵌入方式，不构成不可信代码的安全沙箱。请按 ComfyUI 自身的认证与访问边界部署。

更多[使用说明与限制](integrations/comfyui/README.md)、[模型来源](integrations/comfyui/MODEL_SOURCES.json)、[既有人工修正选区的展示](integrations/comfyui/SHOWCASE.md)。展示图属于注明版本的历史结果，不代替新版本验收。
