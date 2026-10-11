# Stocking Texture Tool · ComfyUI 接入

在 ComfyUI 中使用 [Silvermoong 的丝袜纹理工具](https://github.com/silvermoong/stocking-texture-tool)：打开完整编辑器，修正选区、画走向、调纹理，再运行独立工作流，保存成品与透明纹理图层。

**[安装与使用](integrations/comfyui/README.md#install-and-try) · [独立工作流](integrations/comfyui/examples/stocking-repair.json) · [完整示例与参数](integrations/comfyui/SHOWCASE.md) · [English](README.en.md)**

- 复用原版六种样式、SAM 选区、画笔/橡皮、走向/隔开线、预设、PSD 和实时预览。
- `StockingTextureStudio → 两个 SaveImage`，分别输出成品和 RGBA 图层；可独立使用，无需 UAP、扩散模型或放大节点。
- 已同步作者 **`f74c8ac` 的摩尔纹开关、强度/面积控制及新版油光**（2026-10-10 核对）。摩尔纹默认关闭，开启时需要深度。
- 新增 **CPU/GPU 选择，默认 GPU**：加速点选、深度和走向求解；离开最后一个编辑页面后释放专用模型与图像特征缓存，保留草稿和已算好的深度。

## 实际输出

**原图 → 修正后的完整选区（双腿分开）→ 插件成品**。交叉腿包含前景袜内足部，分区沿真实遮挡边界修正。油光密度 75、手动强度 35；暗部适配、亮点与摩尔纹关闭。

![ComfyUI 交叉腿油光：原图、完整选区和真实输出](integrations/comfyui/docs/images/black-crossed-before-mask-after.png)

此工程已在实际编辑器中“应用到节点”，经过 SaveImage 保存、工作流重载和再次执行。另有[白袜弯腿、近黑站姿的完整对照与参数](integrations/comfyui/SHOWCASE.md)。选区经过手工修边，不表示 SAM 能自动完成同样的选择；油光仍为试验效果。

## 给原作者与审查者

| 内容 | 入口与范围 |
|---|---|
| 改了什么 | 新增 [`integrations/comfyui/`](integrations/comfyui/) 与根 [`__init__.py`](__init__.py)；直接复用 `stocking/` 文件，可选 GPU 求解实现在接入目录 |
| 代码对比 | [相对 `f74c8ac` 的全部差异](https://github.com/wangtianbao19971204-spec/stocking-texture-tool/compare/f74c8ac0190ec43b2cdfcb13db86f35a83283311...feat/comfyui-integration) |
| 如何验证 | [分日期测试与复现](integrations/comfyui/README.md#review-and-tests)：本轮 65 项 Python、2 项 CUDA、17 项前端通过；CPU/GPU 六种样式最大差 2/255。此前摩尔纹与弯腿验收另列 |
| 已知限制 | SAM 复杂姿势仍需修边；GPU 首次初始化较慢，依赖缺失或资源忙时回退 CPU；近黑织纹较弱；模型需自行放置。三张展示图保持原样，不附原始工程或权重 |

> **作者归属与 AI 说明：** 核心算法、编辑器、样式及原版功能归 Silvermoong 与原项目贡献者，保留 MIT 许可。新增接入几乎全部由 AI 编程助手在用户指导下编写。本 fork 独立维护，不作为向原仓提交的 PR，也不声称获得原作者认可。像素对照只说明受测范围的兼容性，不保证任意图片的选区或画质。

ComfyUI 使用者请从上面的安装入口开始；下方 `install.bat` 等步骤属于原独立软件。

---

## 原版项目说明

以下原版说明、演示图片和署名完整保留；图片展示原作者软件。
