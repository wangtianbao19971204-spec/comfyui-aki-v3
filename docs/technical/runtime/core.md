# 本体、插件装配与启动

文档修订：2026-10-06.1。

## 职责与实现

[本体入口](../../../snapshot/runtime/ComfyUI/main.py)负责参数和服务启动，[节点加载](../../../snapshot/runtime/ComfyUI/nodes.py)负责注册。项目级启动入口为 [launch.py](../../../snapshot/runtime/production_tools/launch.py)，白名单在 [profiles.json](../../../snapshot/runtime/production_tools/profiles.json)，统一插件装配由 [统一包入口](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/__init__.py)与 [modules.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json)定义。

五模块覆盖共享资料、Anima 选择器、Gallery/UAP、LoRA Manager、Custom Scripts。外层同名旧目录不是第二套可独立修改的权威源码。production、lean、diagnostic、anima、krea 配置分别维护；不能因某插件没有在用后端节点就删除纯前端/服务插件。

## 数据与部署

本体/插件代码修改先进主 Git，seal 后产生只读部署计划，按精确文件部署。运行目录没有独立开发 Git；上游更新也先在主仓审核。API 配置、日志、缓存与模型不随源码覆盖，Python/Torch/CUDA 和前端分发包版本另有清单，不是假定已锁定的新机器安装环境。

## 验证与限制

[validate_profiles.py](../../../snapshot/runtime/production_tools/validate_profiles.py)、[validate_lean_profile.py](../../../snapshot/runtime/production_tools/validate_lean_profile.py)检查配置；[test_plugin_fusion.cjs](../../../snapshot/runtime/production_tools/test_plugin_fusion.cjs)检查融合。正式启动还应核对真实 PID/启动时间、8188 所有者、队列及 `/unified-workbench/status`；静态代码检查不能替代冷启动。

旧 `.git` 退休后的静态探测回退已审计，但不据此声称所有插件都完成重启验收。Anima 2.9B LoRA Patch 已完成独立任务的限定部署与对照交接，见 [兼容层档案](../training/anima-compat.md)；其服务身份与 A/B 结果只代表记录时的现场和样本，后续操作仍须重新核对当前状态。

## 更新记录

- 2026-10-06：现行 UAP 图内旧网页接收部件退役；浏览器导入插件继续提供工作台收件接口与历史图兼容注册，装配/白名单沿用当前配置。新桥接与 UAP 清理需一并按范围部署；结构和用户参数保持性验收见[工作流说明](workflows.md)，本次主仓修改尚未部署。
- 2026-10-05：修正 Anima 补丁仍“正在进行”的过时表述；接手指向已归档的限定部署/对照证据，不扩大为全部插件或模型的冷启动验收。

- 2026-10-05：补入 rgthree 默认配置、源码/发布目录的 4 份 Tree-sitter WASM、GGUF 补丁与缺失第三方许可证；包括已收录但未启用的 Wan/Qwen/llama.cpp 配套声明。精确身份见 [补源回执](../../../governance/runtime-support-import.json)。不变更白名单、节点、默认参数或运行字节；许可证被保存不等于取得所有模型/数据的再分发许可。

- 2026-10-05：接收并行 Anima 2.9B LoRA Patch 的三档白名单变更；仅补丁 7 文件与 profiles 有本次限定部署核对，不改其他工作流参数。具体证据见 [兼容层档案](../training/anima-compat.md)。

- 2026-10-05：统一维护入口、插件来源与启动边界；现有代码与私密/运行状态分离，原 Git 仅私有归档。
