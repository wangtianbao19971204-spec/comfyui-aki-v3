# 本体、插件装配与启动

文档修订：2026-10-05.1。

## 职责与实现

[本体入口](../../../snapshot/runtime/ComfyUI/main.py)负责参数和服务启动，[节点加载](../../../snapshot/runtime/ComfyUI/nodes.py)负责注册。项目级启动入口为 [launch.py](../../../snapshot/runtime/production_tools/launch.py)，白名单在 [profiles.json](../../../snapshot/runtime/production_tools/profiles.json)，统一插件装配由 [统一包入口](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/__init__.py)与 [modules.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json)定义。

五模块覆盖共享资料、Anima 选择器、Gallery/UAP、LoRA Manager、Custom Scripts。外层同名旧目录不是第二套可独立修改的权威源码。production、lean、diagnostic、anima、krea 配置分别维护；不能因某插件没有在用后端节点就删除纯前端/服务插件。

## 数据与部署

本体/插件代码修改先进主 Git，seal 后产生只读部署计划，按精确文件部署。运行目录没有独立开发 Git；上游更新也先在主仓审核。API 配置、日志、缓存与模型不随源码覆盖，Python/Torch/CUDA 和前端分发包版本另有清单，不是假定已锁定的新机器安装环境。

## 验证与限制

[validate_profiles.py](../../../snapshot/runtime/production_tools/validate_profiles.py)、[validate_lean_profile.py](../../../snapshot/runtime/production_tools/validate_lean_profile.py)检查配置；[test_plugin_fusion.cjs](../../../snapshot/runtime/production_tools/test_plugin_fusion.cjs)检查融合。正式启动还应核对真实 PID/启动时间、8188 所有者、队列及 `/unified-workbench/status`；静态代码检查不能替代冷启动。

旧 `.git` 退休后的静态探测回退已审计，但不据此声称所有插件都完成重启验收。正在进行的 Anima Patch 部署可能改变白名单和服务身份，以它的最新回执为准。

## 更新记录

- 2026-10-05：接收并行 Anima 2.9B LoRA Patch 的三档白名单变更；仅补丁 7 文件与 profiles 有本次限定部署核对，不改其他工作流参数。具体证据见 [兼容层档案](../training/anima-compat.md)。

- 2026-10-05：统一维护入口、插件来源与启动边界；现有代码与私密/运行状态分离，原 Git 仅私有归档。
