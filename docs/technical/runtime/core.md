# 本体、插件装配与启动

文档修订：2026-10-11。


2026-10-11 更新：源码 production / diagnostic / anima 白名单用 `ComfyUI-Anima-LoRA-ControlNet-Patch` 替换旧 `ComfyUI-Anima-2.9B-loraPatch`，避免 LoRA 双重映射；其他启动参数保持。隔离 CPU 服务确认 LoRA 与原生 ControlNet 两个 hook 安装。新增原生权重加载器无需搬动模型；已完成限定部署与生产重启，见 [GPU/部署收据](../../receipts/anima_control_gpu_deployment_20261011.json)及 [兼容说明](../training/anima-compat.md)。

VNCCS 子图执行同步现按冒号路径定位节点，后端与上传 API 复用相同的安全文件名；修复重启后缓存失效时无法使用浏览器捕获的问题。实页证明前后端控制图逐像素一致，Python 备用渲染和 SAM3D 图片提取仍未认证。回归见 `test_vnccs_pose_sync.cjs` 与 `tests/test_vnccs_pose_sync.py`。原版 a1 实机轮进一步用无头真实前端捕获姿势并经同步／缓存接口上传，后端执行日志确认从缓存取用；仍属真实浏览器捕获路径，不改变上述备用渲染限制。

## 职责与实现

[本体入口](../../../snapshot/runtime/ComfyUI/main.py)负责参数和服务启动，[节点加载](../../../snapshot/runtime/ComfyUI/nodes.py)负责注册。项目级启动入口为 [launch.py](../../../snapshot/runtime/production_tools/launch.py)，白名单在 [profiles.json](../../../snapshot/runtime/production_tools/profiles.json)，统一插件装配由 [统一包入口](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/__init__.py)与 [modules.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json)定义。

五模块覆盖共享资料、Anima 选择器、Gallery/UAP、LoRA Manager、Custom Scripts。外层同名旧目录不是第二套可独立修改的权威源码。production、lean、diagnostic、anima、krea 配置分别维护；不能因某插件没有在用后端节点就删除纯前端/服务插件。

## 数据与部署

本体/插件代码修改先进主 Git，seal 后产生只读部署计划，按精确文件部署。运行目录没有独立开发 Git；上游更新也先在主仓审核。API 配置、日志、缓存与模型不随源码覆盖，Python/Torch/CUDA 和前端分发包版本另有清单，不是假定已锁定的新机器安装环境。

## 验证与限制

[validate_profiles.py](../../../snapshot/runtime/production_tools/validate_profiles.py)、[validate_lean_profile.py](../../../snapshot/runtime/production_tools/validate_lean_profile.py)检查配置；[test_plugin_fusion.cjs](../../../snapshot/runtime/production_tools/test_plugin_fusion.cjs)检查融合。正式启动还应核对真实 PID/启动时间、8188 所有者、队列及 `/unified-workbench/status`；静态代码检查不能替代冷启动。

`lean` 依赖检查只选择独立工具 04–09 和 99 释放流程；新增 10 部位细化需要 Impact-Pack、impact-subpack 与 rgthree，继续由生产配置检查，不能因其文件名前缀相同而扩大轻量配置范围。[5 项隔离回归](../../../snapshot/runtime/production_tools/test_validate_profiles.py)验证这一区别、现行主套件导航目标和编辑模板的来源绑定；不启动服务或提交任务。

旧 `.git` 退休后的静态探测回退已审计，但不据此声称所有插件都完成重启验收。Anima 2.9B LoRA Patch 已完成独立任务的限定部署与对照交接，见 [兼容层档案](../training/anima-compat.md)；其服务身份与 A/B 结果只代表记录时的现场和样本，后续操作仍须重新核对当前状态。

## 更新记录

- 2026-10-24：仓外历史归档退役后修正三份现行说明（`production_tools/README.md`、`资源维护入口.md`、`项目使用指南.md`）：`_archives/2026-09-28_workflow_cleanup` 的 207 项快照 payload 已按用户授权永久删除（无归档、无备份），仓外收据保留 manifest/operations/README 与 SHA-256 清单，`resource_archive.py` 对该归档的 verify/restore 不再可用。未写入运行区。见[仓外归档收据](../../receipts/external_archive_cleanup_20261024.json)。

- 2026-10-11：K2 控制链维护工具整理：保留 `production_tools/keep_krea2_control_enabled.py`（分支模式表修正，用 `--write` 应用），移除仅用于比对的过渡脚本`production_tools/align_krea2_branch_modes.py`；两者都不改变运行逻辑，也不触碰权重。见[分支模式修复](../changes/runtime-workflows/2026-10-11-krea2-branch-mode-fix.md)。

- 2026-10-11：K2 分支模式表漂移修复：ranches[k2].modes 曾把 Depth 控制链与姿势工作室（1160/1161/1172/1149）记为静音，而文件里它们是启用态。前端 ctivateBranch 在切分支时按表写 mode，于是从别的分支切到 Krea2 后 Krea2ControlApply 被静音、DazzleSwitch 1187 在 priority 下静默回退到原始模型——控制消失且无报错。现把该链在表里改为启用（其余节点记录不变，预览类仍保持关闭），并同步节点自身 mode 防止再次漂移。见[分支模式修复](../changes/runtime-workflows/2026-10-11-krea2-branch-mode-fix.md)。

- 2026-10-11：K2 子图实例的遮罩控件整理：`upload` 端口两侧移除，遮罩下拉留在子图内部（保留原生预览与编辑器），实例收敛为 4 个接线输入与 3 个输出，节点卡不再显示文件控件；导出与实页渲染复核通过。见[子图化变更](../changes/runtime-workflows/2026-10-11-krea2-lineart-subgraph.md)。

- 2026-10-11：K2 线稿与控制链子图化：把参考预处理、线稿来源选择、擦除链与预览、姿势深度、来源选择与控制图编码整体放入子图 `K2 线稿与控制图`（23 节点），根级只留实例 `130163`（根节点 294→272）。定义由运行中前端自身的 `Convert to Subgraph` 生成并落地到正式工作流与模板；导出解析为 `1161.control_latent = ["130163:1159", 0]`，存盘重载后仍有效，运行区实页渲染通过。本体、插件与启动参数未动。见[子图化变更](../changes/runtime-workflows/2026-10-11-krea2-lineart-subgraph.md)。

- 2026-10-11：擦线子图化调查未获采用：按前端格式手写子图定义、以及用前端自身的 `convertToSubgraph` 生成定义，两种方式下"子图实例输出喂 `DazzleSwitch`"在导出阶段都解析不出该输入，开关静默回退，实测控制图不随遮罩变化。因此 Krea2 擦除链保持根级平铺，Anima 侧保留 `[05]` 子图内的实现；两个分支互不依赖。同时把 Anima 擦线子图的遮罩指回遮罩编辑器保存的 RGBA 文件（此前后指向无 alpha 的旧文件，是空操作）。六份源码已部署并重启为进程 49600，见[子图化调查](../changes/runtime-workflows/2026-10-11-krea2-erase-subgraph-investigation.md)。

- 2026-10-11：K2 擦线（擦除）修复只改工作流接线与一个节点的静音状态：`[05C7]` 擦线合成此前没有下游消费者，现把深度来源选择 `[05B6]` 的 `input_01` 接到它；`[05C2]` 遮罩输入解除静音并指回遮罩编辑器保存的 RGBA 文件。本体、插件与启动参数未动，未新增依赖。运行区按原命令行重启为进程 51716，注册缺失 0、队列为空，实页验收见[擦线修复](../changes/runtime-workflows/2026-10-11-krea2-erase-repair.md)。

- 2026-10-11：Krea2 默认底模由 Turbo 换为非蒸馏 `Krea2-Anime v2.0`（同批把该底模需要的步数/CFG/scheduler 写入 K2 采样节点），只改工作流与模板，本体、插件白名单与启动参数未动，两个底模都是库存既有资产、无下载或转换。运行区部署后按原命令行重启为进程 15244，注册缺失 0、队列为空。见[底模变更](../changes/runtime-workflows/2026-10-11-krea2-anime-default-base.md)。

- 2026-10-11：Krea2 深度来源选择只改工作流与模板，本体、插件白名单与启动参数未动；新增的 `[05B6]` 深度来源选择器使用已注册的 `DazzleSwitch`，姿势深度复用已安装的 `DepthAnythingV2Preprocessor`，不新增依赖。运行区未部署，隔离实例验证由[Krea2 变更](../changes/runtime-workflows/2026-10-11-krea2-pose-control.md)与[收据](../../receipts/krea2_pose_control_20261011.json)记录。

- 2026-10-11：原版 Anima 控制实机验收复用了同一批已部署插件代码：隔离实例里原生权重加载器按 28 层直接应用，VNCCS 注册与冒号路径同步正常，控制分支无需额外插件改动。该轮只部署四份 a1 工作流／模板并用原命令行重启，白名单、补丁与加载器保持；重启后注册缺失为零、队列为空。见[原版实机变更](../changes/runtime-workflows/2026-10-11-anima-original-gpu.md)。

- 2026-10-09：按用户的生产部署／实测请求，将丝袜纹理节点加入 production 白名单（25→26）；其余配置不变。原 GUI 和项目启动器都在启动时读取该清单，无需改本体或绘世适配。此次部署与真实图片验收以[丝袜纹理档案](stocking-texture.md)的现场收据为准。

- 2026-10-09：为原绘世 Python 子进程增加 opt-in 生产参数边界，普通入口不加载适配。精确 7 文件已按授权部署，原 GUI 启动及工作台实页通过本机验收；版本读取、管理范围与限制见[绘世说明](huishi-launcher.md)。不重建运行 Git、不改用户工作流或显存参数。

- 2026-10-07：补齐生产与 Qwen 独立本体各 11 份 `models/configs/*.yaml`，以及 WanVideo 的单份 Qwen 架构 JSON，保留原字节。这些是小型架构说明，模型权重仍外置。捕获／导入仅接纳精确路径，邻居、路径别名、链接和正文凭据继续拒绝；范围见[完整性复核](../changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)。不重启或启用相关节点。

- 2026-10-07：按运行区与主 Git 全量逐文件对照补齐插件遗漏的词表、分词器、系统提示词及 MakeHuman CC0 形体／骨架资源；精确接纳范围见 [支持文件登记](../../../governance/plugin-support-20261007.json)。这些配套文件属于插件功能，不能归为用户图片缓存或神经模型权重。捕获和再次捕获沿用受审查路径，所有新增字节继续接受凭证扫描；不启用插件、不改生产白名单或安装依赖。模型、鉴权、用户字体及许可敏感几何等仍按外部资料处理，详细范围和大小见 [内容复核](../../receipts/github_content_reconciliation_20261007.json)。

- 2026-10-07：全流程复核发现轻量配置误选新增 10 部位细化；依赖校验收窄至承诺的 04–09 工具与 99 释放，保留生产/诊断对 10 的检查。增加隔离回归，不改变插件白名单或启动参数。
- 2026-10-07：为实际 SAM 权重规范位置同步 6 份本体 blueprint 的加载选择器，保留上游下载名称／URL、图结构、参数与原模型内容；本次只验证路径与加载列表，不重启或执行 GPU 推理，见[标准化收据](../../receipts/model_standardization_20261007.json)。
- 2026-10-06：经用户明确请求，将网页桥接、UAP 清理与维护保护共 11 文件部署到运行区，保留启动参数重载后端。真实收件、正负方向采用/序列化/撤销、新版 UAP 实页加载与三份执行源码摘要通过；五模块就绪、队列为空、保护范围与数据库逻辑内容保持。Chrome 油猴安装、五站当前网页 GM 发送及生产整页刷新仍为单独边界，见[运行区部署收据](../../receipts/browser_live_deployment_20261006.json)。

- 2026-10-06：现行 UAP 图内旧网页接收部件退役；浏览器导入插件继续提供工作台收件接口与历史图兼容注册，装配/白名单沿用当前配置。新桥接与 UAP 清理需一并按范围部署；结构和用户参数保持性验收见[工作流说明](workflows.md)，后续运行区部署状态见[运行区部署收据](../../receipts/browser_live_deployment_20261006.json)。
- 2026-10-05：修正 Anima 补丁仍“正在进行”的过时表述；接手指向已归档的限定部署/对照证据，不扩大为全部插件或模型的冷启动验收。

- 2026-10-05：补入 rgthree 默认配置、源码/发布目录的 4 份 Tree-sitter WASM、GGUF 补丁与缺失第三方许可证；包括已收录但未启用的 Wan/Qwen/llama.cpp 配套声明。精确身份见 [补源回执](../../../governance/runtime-support-import.json)。不变更白名单、节点、默认参数或运行字节；许可证被保存不等于取得所有模型/数据的再分发许可。

- 2026-10-05：接收并行 Anima 2.9B LoRA Patch 的三档白名单变更；仅补丁 7 文件与 profiles 有本次限定部署核对，不改其他工作流参数。具体证据见 [兼容层档案](../training/anima-compat.md)。

- 2026-10-05：统一维护入口、插件来源与启动边界；现有代码与私密/运行状态分离，原 Git 仅私有归档。
