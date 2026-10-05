# PixAI 图像反推标签

文档修订：2026-10-05.1。

## 实现入口

[nodes.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-PixAI-Tagger/nodes.py)提供后端加载/推理，[前端入口](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-PixAI-Tagger/web/pixai_tagger.js)负责交互，[原始说明](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-PixAI-Tagger/README.md)保存安装与用法。

当前使用 PixAI Tagger v1.0；旧 WD14 的禁用原件只作回滚参考，不恢复为日常路径。反推结果到提示词的目标写入仍受工作台真实输入/草稿区分约束。

## 模型边界

模型目录位于运行环境 `ComfyUI/models/taggers/pixai-tagger-v1.0/`，权重、config、processor 和上游模型代码须保持配套。权重仓外引用，Git 保留节点实现与放置说明。PixAI 各类阈值和标签集合不能套用 WD14 默认值。

## 验证

按当前 `/object_info` 注册、模型目录完整性、served 前端与节点源码哈希确认装载；实际反推需有单独图片与输出证据。UAP 图像生成时在线反推节点可被排除在执行目标闭包之外，不能因节点存在就认定每次会调用。

本轮只整理实现与档案，没有重新执行图片反推，也未下载模型。

## 更新记录

- 2026-10-02：现有项目将活动 WD14 路径替换为 PixAI，并保留禁用回滚副本。
- 2026-10-05：补充节点、前端、模型目录及验证边界的技术入口。
