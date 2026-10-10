# UAP、子图、部位细化与二放

文档修订：2026-10-07.3。

## 唯一构建入口

[正式 UAP v2](../../../snapshot/runtime/ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json)与 [权威模板](../../../snapshot/runtime/production_tools/templates/UAP统一生产工作台_v2.json)各自保存并核对哈希。构建/校验用 [merge_unified_workflow.py](../../../snapshot/runtime/production_tools/merge_unified_workflow.py)、[validate_uap_workflow.py](../../../snapshot/runtime/production_tools/validate_uap_workflow.py)。子图内嵌在完整 JSON，不拆成丢失连线/模式的孤立备份。

九分支覆盖两套 Anima、Krea2 生产、Krea2 编辑、裁剪精修、透明抠图、左右扩图和二倍/四倍独立超分。独立旧流是历史快照，不承诺与 UAP 双向同步；构建工具默认权威模板，无参数拒绝写入，导出只允许全新候选。

## 网页提示词接入

网页提示词经[五站桥接](browser-import.md)进入工作台待采用区，核对后选择正向/负向目标，不需要在生成图中放置接收节点。正式 v2 与权威模板均移除了三处 `DanbooruBrowserImportV05` 及三处专用预览；Krea2 的纯接收分组和开关/导航引用也已清理。

两套 Anima 的 PixAI 图片反推保留：原图片输入、子图 UUID、对外字符串端口及预览节点保持，输出改接本地 PixAI 标签。保留其余提示词、LoRA、种子、参数、模式、位置和子图；历史独立流与 v1 不随本次清理改写，旧接收节点类仍为这些旧图兼容注册。

常规导出和现行校验递归拒绝旧接收节点，并检查内嵌连接、端口回指及分支/阶段引用。`--legacy-sources` 仅可导出历史实验候选，不能据此覆盖正式图。旧 `layout_uap_workbench.py` 的直接重建/覆盖入口已封闭，避免从旧独立流恢复接收部件与旧参数。

[专项测试](../../../snapshot/runtime/production_tools/test_uap_browser_retirement.py)与[清理收据](../../receipts/browser_workflow_retirement_20261006.json)记录结构和保持性验收。已完成本次 11 文件运行区部署，并从真实服务在新页面加载新版 UAP；291 节点、22 子图，未报告缺节点、旧接收器为零，见[运行区部署收据](../../receipts/browser_live_deployment_20261006.json)。此次未提交 GPU 任务，不能据此更新画质结论。

## 细化与参数链

两套 Anima 次序为手 → 脚 → 区域标准/快速互斥 → 脸 → 眼 → 可选 1.5× 分块二放。细化和二放继续默认关闭，由用户在工作台选择；不新增头发、四肢、人体、服装或独立皮肤支路。

检测器、分割器、裁剪/回贴、局部采样是不同职责；精确节点类型和参数以保存图为准，不把检测模型当成细化底模。常用 UI 直接映射子图原阈值、上下文、降噪、种子与模式；高级采样和缝补仍保留原控件。独立 08/09 超分不是主流程自动续段。

## 模型与数据契约

模型、编码器 type/文件、VAE 按已核对家族匹配；静态家族清单需要新增或同名替换模型后复核。LoRA 兼容与效果不能由底模家族校验代替。正式图和模板中的提示词、LoRA、种子、开关属于用户数据，UI 修复不得顺便改值。

## 现行原生执行验收

[native_workflow_acceptance.py](../../../scripts/native_workflow_acceptance.py)只接收 ComfyUI 正规 **Export (API)** 导出的节点字典，不自行编译 UI 子图，也不改导出节点、输入、模型、提示词或参数。先在独立 QA 图中绑定中性输入、固定种子与 `_codex_qa/final_acceptance_20261007/` 保存前缀，再从工作流名称菜单或 File 菜单导出；正式工作流与模板保持原件。

默认只读检查服务/运行文件，并把结果写入全新仓外目录。传入当前 PID、精确创建时间及输出 ID；PowerShell 中须把创建时间的小数字面量加引号，避免参数转换舍弃精度，不能放松身份断言。`--target` 可重复或用逗号指定多个阶段输出。只有显式 `--execute` 才提交一次目标依赖闭包，服务固定为 `127.0.0.1:8188`。工具核对解释器、工作目录、监听者与运行前后身份；首次队列非空即拒绝，过程中发现用户任务或身份漂移即停止，不取消任务、清队列、释放模型或重启。

闭包拒绝未注册节点、外部 API/caption/下载/可执行脚本节点、网络/凭证输入与 QA 目录外输出；加载器选择器须匹配当前注册列表，QA 子目录输入按安全实际文件核验。唯一动态选择例外是已审查的 [DazzleSwitch.select](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-DazzleSwitch/py/node.py)：只允许 `(none)`、`(none connected)` 和导出内实际提供值的 `input_NN`；`mode` 等枚举仍严格核对，不因节点有 `VALIDATE_INPUTS` 就整体跳过校验。

[AnimaLLLiteApply_sdscripts](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-LLLite/nodes.py)名称中的 `sdscripts` 表示训练格式，已审实现只从本机 ControlNet 列表读取权重并在克隆模型中应用。工具仅对此精确类名豁免 `script` 子串误匹配，且只批准实时选择器中的字面 `.safetensors` 权重，不进入其非 safetensors 加载分支；相似类名以及 API、网络、输出节点限制仍照常检查。

执行目标只接受 SaveImage。依赖中的 [VRAMCleanup](../../../snapshot/runtime/ComfyUI/custom_nodes/comfyui_memory_cleanup/__init__.py)仅在两个 offload 字段严格为字面 `false` 时作透传例外，不能成为目标或启用释放。[WeiLinPromptUI](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/__init__.py)仅允许当前 QA 使用的纯文字路径：`auto_random` 严格为字面 `false`，`lora_str`、`temp_str`、`temp_lora_str`、`random_template` 四项明确为空，`positive` 及可选 `opt_text` 为非 JSON、无 `<wlr:` 的普通字面字符串，且不接 `opt_clip`、`opt_model`。链接文字可能在执行时产生 LoRA 标记，因此此例外不批准链接文字，也不能作为目标；其他输出节点继续拒绝。

完整成功 history 中的 UUID 与实际执行图须符合本次提交及当前后端的确定校验转换。[execution.validate_inputs](../../../snapshot/runtime/ComfyUI/execution.py)从指定输出目标开始，只沿 required/optional **枚举出的字段**递归；在实际访问的节点上解开声明字面输入的 `__value__` 包装，再按 `INT`、`FLOAT`、`STRING`、`BOOLEAN` 转换。动态 optional 字典可以在执行时接受更多连接，但枚举键为空时，这些连接不进入队列前校验遍历；整个执行依赖闭包中的未访问节点继续保留原提交对象。工具保存独立 `backend-validation-reference.json`、访问节点清单与逐字段转换记录，不改原导出、闭包或提交。history 与此参考作保留 JSON 类型的比较：允许实际访问且已声明的 FLOAT `7→7.0`，拒绝布尔 `false→0`、未知字段改写、边/节点/数值变化及后端 INT 转换后仍为浮点等异常。保留原导出字节、提交对象、完整 history/错误和目标图片 SHA、尺寸、颜色/透明度指标；节点内部临时 UI 预览保留在 history 中，不当作指定 QA 交付输出。超时或不确定提交不自动重试，先核对已记录的 prompt ID。每个新用例使用新证据目录，不能隐式覆盖或恢复旧运行。

[59 项隔离测试](../../../tests/test_native_workflow_acceptance.py)验证多目标闭包、联网/路径拒绝、身份/队列漂移、单次提交、成功 history 身份及确定校验转换参考、动态 optional 校验访问边界、原生 Windows 保存子目录、窄范围动态选择/关闭释放/纯文字依赖/本地 LLLite 模型契约及完整错误记录，全程不使用 GPU。实际出图结论仍需要本机每个用例的执行与人工画面检查；尺寸、RGBA 和执行成功不能证明裁剪/扩图接缝质量，未启用的分支不能凭结构检查称为已实测。

本轮首次 A1 smoke 后端在约 12.7 秒内成功，完整 history 没有执行错误；旧版参考却把 23 节点执行闭包全部预判为已校验，因三份 LoRA 堆的空列表包装而误报失败，顺序验收随即停止。只读比对确认后端实际声明字段遍历为 19 节点，三份堆仍是提交时的 `{"__value__":[]}`，种子数值与链接均未漂移。修复只收窄确定转换的适用节点范围；原失败收据、提交及 history 保留，另用保存 history 离线补充核对，不重投同一 GPU 任务，也不以此跳过其余用例或画面审查。

离线图片指标核对还发现 Windows 原生 SaveImage 的 history `subfolder` 使用反斜杠。仅这个响应字段在本地路径核对时转换为 `/`，仍执行完整相对路径、QA 前缀、实际输出根、文件存在与 symlink/junction 拒绝检查；不修改 history、导出或提交对象。`filename` 继续只接受单文件名，UNC、盘符、绝对路径、`..`、保留设备名与 QA 目录逃逸均拒绝。

## 验证与剩余问题

热门流程比较保留为 [当时研究报告](../archive/civitai_workflow_study/报告-Civitai近三月热门工作流人体部件与NSFW细化分析.md)、[检测器到细化器链](../archive/civitai_workflow_study/检测器到细化器数据流.json)和 [逐流程明细](../archive/civitai_workflow_study/逐工作流明细.json)。它们不是持续更新的实时热度榜。原始 4.55 MB 元数据与其他大输入仅登记外部位置。

维护实现备份包括 [组件目录生成器](../archive/benchmark_reports/2026-10-04_full_workflow_review/build_component_catalog.py)、[整改结构测试](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workflow_product_repair/test_structure.py)、[交互测试](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workflow_product_repair/test_candidate.cjs)和 [真实执行验收实现](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_native_e2e_acceptance/acceptance.py)。这些是当时路径/fixture 的历史实现；重用必须先适配到隔离环境，不能直接向生产队列运行。

[产品整改回执](../../../snapshot/evidence/20261005_workflow_product_repair/FINAL_DELIVERY.json)区分结构/保持性、浏览器和 GPU；[真实执行报告](../../../snapshot/evidence/20261005_native_e2e_acceptance/REPORT.txt)是另一轮有限样例。现存 ext05 背景矩形/横带、ext07 扩图接缝问题见 [已知问题](../../KNOWN_ISSUES.md)。区域分支不能以结构检查冒充已实跑，单种子结果也不保证所有风格/遮挡/LoRA。

本轮[完整验收收据](../../receipts/final_workflow_acceptance_20261007.json)记录 23 现行图静态通过、27 文件精确部署及 15 次后端成功。最初 12 用例中 Krea2 smoke/full 与 04 编辑全黑；同一服务在空队列保护下清除模型与执行缓存后，三个相同闭包补测恢复有效画面，但根因未分离，混合模型运行稳定性尚未通过。Anima 两套完整输出与 Krea2 补测为准确 1.5×，透明图及独立 2×/4×有效；扩图接缝、裁剪融合和细化部位隔离限制仍保留，不能写全项画质通过。未实跑区域标准／快速分支。

## 未通过项的补充核验

[补充收据](../../receipts/workflow_failure_verification_20261007.json)记录 24 次真实后端成功、73 张指定输出（含空蒙版）。正规 UI 导出、闭包／history 核对、遥测与人工画面审查分别绑定证据；本轮仅核验，未修改或部署正式生成图、提示词、种子、模型、LoRA、参数与默认开关。

Krea2 按 A1 完整→A29 完整→首次 K2 做三组对照：保留前序状态、K2 前仅卸载模型、K2 前联合卸载模型并清执行缓存。三组 K2 的原 35 节点 smoke 闭包相同，编码／采样／解码均新执行，对应 RGB 像素逐像素相同；显存峰值／最低空闲分别为 31589／599、31558／630、31553／635 MiB。原顺序 A1 smoke/full→A29 smoke/full→K2 smoke/full→04 编辑复跑也有效，其中前六闭包精确相同，04 仅保存前缀与旧黑 smoke 导出不同，生成节点／边／参数相同。原顺序 K2 smoke 最低空闲 458 MiB，但日志无显式 OOM/CUDA 失败。初轮黑图未复现，根因尚未知，不能把先卸载模型认证为已解决根因。

所有对照组开始前都做联合清理，未复原初轮未测的分配器状态。当前 `/free` 的 `free_memory=true` 路径会联合卸载并 reset，`false/true` 不是独立 cache-only 组；HTTP 200 只表示已排队，完成另核。NVML 为全设备采样，cudaMallocAsync 的 Torch reserved 不是可用显存容量；18 条 `0 models unloaded.` 是 INFO，原两条 invalid-cast 警告仍保留。模型卸载与缓存清理分开记录，不从后续成功倒推旧黑图原因，也不认证长期混合模型稳定性。

A29 手阶段：原手部 YOLO 检测框已经纳入画面左侧裸脚区，SAM 后蒙版仍覆盖脚；旧脚区变化全部位于蒙版加羽化支持内，定位为真实误检。原 A1 脸→眼链在 A29 正脸基图上补测，两阶段分别有局部变化，身体／背景保持；这是独立正例，不是重新生成 A1 正脸全流程。修脸前参考眼蒙版只作空间对照。05/07 仅纠正私有 QA 的参考内容提示词并保存实际蒙版、采样后解码与最终复合图：05 框外零变化，结构通过但无缝融合质量未认证；07 核心像素保留而接缝／路面断续仍失败，接缝已在最终复合前出现，尚未分离采样／VAE／LLLite 原因。

区域 A1/A29 标准／快速四组通过正规 UI 开关与各自导出实际执行，所选 16 个 child 节点无缓存；四蒙版全空、最终 RGB 与输入相同，仅认证真实 no-hit 检测／透传路径。有命中重绘和画质仍未覆盖。内建手工蒙版编辑器已实际打开、载图并取消；画笔保存往返未测，旧 Impact 自动 SAM 编辑器仍因缺失依赖未修复。各项剩余边界继续在[已知问题](../../KNOWN_ISSUES.md)维护。

## 更新记录

- 2026-10-10：新增[独立丝袜纹理修复工作流](../changes/runtime-workflows/2026-10-10-stocking-repair.md)，任务入口与精修同级、排在放大之前。单独标签页导入/编辑/应用后保存成品与透明图层；原 UAP 九分支和历史图保持。正常加载服务接入、空项目拦截与旧图往返保持有专项回归和实页证据。

- 2026-10-07：完成初轮未通过项的独立补充核验并保存对照、原顺序、实际检测蒙版与局部修复证据；Krea2 未复现黑图但不认证 OOM 根因，定位手框误检，区分脸眼正例、裁剪结构、扩图画质失败与区域 no-hit。正式生成图／源码未改动，资料与模型保全另核，旧失败和回滚材料保留；本次不重新部署或递增版本，见[补充收据](../../receipts/workflow_failure_verification_20261007.json)。

- 2026-10-07：将原生 UI API 导出后的受保护验收流程纳入现行主仓，增加多目标依赖闭包、固定 loopback 服务身份和队列保护、QA SaveImage 路径约束、成功 history 校验转换参考门禁及完整执行证据；59 项隔离回归通过。DazzleSwitch 动态选择、关闭的 VRAMCleanup 透传、WeiLin 无 LoRA/随机的纯文字路径及精确类名 AnimaLLLite 的本地 safetensors 加载只按已审查字段契约放行；history 类型核对仅对实际声明字段遍历中的节点采用后端确定转换，拒绝其余对象漂移及布尔/数值偷换。首次 A1 后端成功但参考范围过宽的误判及原证据保留，补充核对为离线重审而非重跑；原生 Windows history 子目录仅转换响应分隔符再接受完整路径门禁。默认 preflight 不提交任务，真实 GPU 验收由显式逐用例执行和现场收据另行确认。
- 2026-10-07：全流程复核补齐冻结 04 编辑模板中遗漏的 Identity Edit v1.2 规范 LoRA 路径；修正主套件 01–03 正式/模板共六处失效的快速导航分组名称。每份 JSON 仅改一个已审查字段，保持节点、连线、模式、强度及其余用户参数；[隔离回归](../../../snapshot/runtime/production_tools/test_validate_profiles.py)检查全部主套件导航目标和编辑模型的现行来源身份。历史独立流和 v1 的缺失资源继续保留参考边界。
- 2026-10-07：同步保存工作流／生产模板中的现存 LoRA、底模及 SAM 路径，包括 UAP 模型家族契约的字典键。候选逐项满足只修改精确引用、图与节点／连线结构保持、推理参数／提示词不变；下载 name／URL 留原身份，历史缺失资源不补造。规范放置见[分类命名](../../MODEL_NAMING.md)，实测边界见[标准化收据](../../receipts/model_standardization_20261007.json)。已打开的旧图需重新打开更新后的保存文件，本次不追加 GPU 验收。
- 2026-10-06：经用户明确请求，将网页桥接、UAP 清理与维护保护共 11 文件部署到运行区，保留启动参数重载后端。真实收件、正负方向采用/序列化/撤销、新版 UAP 实页加载与三份执行源码摘要通过；五模块就绪、队列为空、保护范围与数据库逻辑内容保持。Chrome 油猴安装、五站当前网页 GM 发送及生产整页刷新仍为单独边界，见[运行区部署收据](../../receipts/browser_live_deployment_20261006.json)。

- 2026-10-06：网页接收迁至工作台待采用区，清理正式 v2/权威模板的三处旧接收路径，保留 PixAI 反推接口与原用户参数；补递归结构门禁并封闭历史布局覆盖入口。
- 2026-10-05：明确九分支、内嵌子图与实际细化顺序，修正阶段对比/镜像描述、提交目标及窄屏交互；保持用户参数和默认关闭策略。
