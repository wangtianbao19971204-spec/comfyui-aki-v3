# Stocking Texture Tool · ComfyUI 接入

把 [Silvermoong 的丝袜纹理工具](https://github.com/silvermoong/stocking-texture-tool)接入 ComfyUI：在完整编辑器中选区、修边、切分、画走向，再运行独立工作流，保存成品和透明纹理图层。

> **AI 编写说明：** 本分支新增的 ComfyUI 接入几乎全部由 AI 编程助手在用户指导下编写，已做下述测试，仍需人工审查。原算法、编辑器、纹理样式及原版功能归 Silvermoong 与原项目贡献者，保留 MIT 许可。本分支是实验性提案，尚未获原作者认可或合并。

**[安装与使用](integrations/comfyui/README.md#install-and-try) · [独立工作流](integrations/comfyui/examples/stocking-repair.json) · [改动对比](https://github.com/wangtianbao19971204-spec/stocking-texture-tool/compare/6c0c620d1bfa6a2c2691cb2313e928d9c7244ee5...feat/comfyui-integration) · [English](README.en.md)**

## 这个分支新增了什么

- **完整编辑器进入 ComfyUI：** 复用六种样式、SAM 选区、画笔/橡皮、走向/隔开线、弯腿修正、预设、PSD 及实时预览；这些原版能力通过新的宿主适配提供。
- **独立修复工作流：** `StockingTextureStudio → 两个 SaveImage`，分别保存成品与 RGBA 图层。可单独使用，无需 UAP、扩散模型或放大节点。
- **ComfyUI 数据与交互适配：** 浏览器导入/下载、按用户保存草稿与预设、应用到节点及工作流恢复。另保留引导/渲染节点，支持批量与软蒙版。

## 给原作者与审查者

| 审查内容 | 入口与范围 |
|---|---|
| 新增实现 | [`integrations/comfyui/`](integrations/comfyui/) 与根目录 [`__init__.py`](__init__.py)；`stocking/` 算法及静态界面文件未改动 |
| 安装和差异 | [接入说明](integrations/comfyui/README.md)；SAM/深度权重须自行放置，插件不会自动下载 |
| 验证结果 | [测试说明](integrations/comfyui/README.md#review-and-tests)：40 项 Python、17 项前端、18 组弯腿对照通过；此前完成 51 项 HTTP 检查与 54 组真实图对照 |
| 验证边界 | 原版测试 114 通过、51 因作者私有样图缺失跳过；真实图对照不代表 SAM 自动选区总是正确。测试图与权重不随分支分发 |

对照基于上游 `6c0c620`（2026-10-10 验证），相同输入/选区/引导/参数且暗部适配关闭时与原版一致。交叉腿可能需手动修边；近黑纹理、过密淡出与试验性油光仍有原版限制。详细边界与复现命令见接入说明。

ComfyUI 使用者请从上面的安装入口开始；下方 `install.bat` 等步骤属于原独立软件。

---

## 原版项目说明

以下原版说明、演示图片和署名保留；图片展示原作者软件，不作为本 fork 新增功能的测试证据。

