# ComfyUI 生产配置与工作流扩展

日常操作请先看 [项目使用指南](项目使用指南.md)；后续资料更新、预览生成和历史恢复请看 [资源维护入口](资源维护入口.md)。

原始生产扩展对应 `2026-09-06_plugin_optimization`。2026-09-28 已修复整合后的启动白名单：以 `ComfyUI-Unified-Prompt-Workbench` 替换五个空兼容入口，补齐嵌套子图依赖。配置与启动命令已离线校验，未据此声称各配置均已重新启动验收。现有个人工作流保留参数和布局，LLLite 节点做兼容迁移；新入口与冻结模板分开保存。

## 启动

- 双击根目录 `启动_ComfyUI_生产.cmd`：加载 25 个生产插件，使用 8188。
- 双击 `启动_ComfyUI_诊断.cmd`：在生产配置上增加开发诊断，共 26 个插件。
- 双击 `启动_ComfyUI_轻量.cmd`：只加载六条扩展工作流所需的 5 个插件，适合局部精修、抠图、扩图和超分；默认仍使用 8188，请先停止其他后端。
- 双击 `启动_ComfyUI_Anima.cmd`：仅加载 Anima 01–02 主套件所需的 17 个插件。
- 双击 `启动_ComfyUI_Krea2.cmd`：仅加载 Krea2 03 主套件所需的 16 个插件。
- 浏览器打开 `http://127.0.0.1:8188`。启动日志位于 `production_tools/logs`。
- Windows 中文环境已规避 bitsandbytes 的 Linux Gaudi 探测编码异常；若启动日志出现新的异常，应先保留对应日志再切换 profile。
- `停止_ComfyUI_生产.cmd` 只停止本工具启动且队列为空的后端，核对进程身份后才停止。
- 双击根目录 `绘世启动器.exe`，在原绘世界面点“一键启动”：本机已部署适配并核验工作台可用，保留原界面和生产白名单。资料库初始化可能需要数分钟，等日志出现服务地址后再访问页面。范围、回滚与验收限制见[绘世适配说明](../../../docs/technical/runtime/huishi-launcher.md)。

2026-10-03 日常生产入口现保留当前在线服务的显存参数：`--memory-mode original --preview-method auto --cuda-malloc --reserve-vram 4`，只切换插件白名单。下述 no-pin 连续切换记录为历史兼容性证据；需要时仍可手动使用 `--memory-mode no-pin`。关闭动态显存加载的备选方案在本机触发原生访问异常，未采用。兼容配置经过 Krea2、Anima 2.9B、双 LLLite、指令编辑和再次 Krea2 的连续切换验证。该有限回归不能保证无限时长运行无故障；异常后先停止继续排队，再释放显存或重启后端。

性能边界：关闭 pinned memory 后仍观察到 Krea2 大图约 207 秒、主环境 512×768 检查约 115 秒的慢例；隔离环境另有约 19–29 秒的通过记录。这些运行的资源状态和工作负载不完全相同，不能直接作为速度对比。单独限制 CUDA 设备的备选也出现约 228 秒慢例，因此没有设为默认。当前发布确认功能和有限连续运行通过，不承诺吞吐提升。遇到明显降速时先检查后台 GPU 占用，缩小尺寸和批量，再做独立性能定位。

维护或旧插件实验可显式运行：

```powershell
.\python\python.exe -X utf8 -B .\production_tools\launch.py maintenance
.\python\python.exe -X utf8 -B .\production_tools\launch.py legacy
```

维护配置只加载 Manager；legacy 加载 39 包，保留已知 LTXVideo 和 llama-cpp_vllm 导入问题，仅用于排查旧流。先停止占用 8188 的后端再切换配置。

## 工作流入口

现有四条 `生产套件_*.json` 仍是主入口。新增六条 `生产扩展_*.json`：

| 入口 | 用途 | 默认配置 |
|---|---|---|
| 04 Krea2 指令编辑 | 用自然语言改色、调整内容 | Identity Edit v1.2，8 步，CFG 1，fit，ref_boost 4 |
| 05 Anima 2.9 裁剪精修回贴 | 拖选局部、重绘、羽化、按坐标回贴 | 512×512，denoise 0.35，32 像素羽化 |
| 06 透明素材 | 抠图，保存含 Alpha 的 PNG | BiRefNet lite |
| 07 Anima 原版左右扩图 | 保留中心，生成左右延伸 | 左右各 128，inpainting LLLite |
| 08 二倍交付 | 内容保真的快速放大 | OmniSR 4× 后缩为 2× |
| 09 四倍素材 | 输出四倍尺寸素材 | OmniSR 4× |

先替换输入图、修改提示词，再运行。示例输入 `optimization_reference.png` 是本地验收生成图。所有新入口默认固定 seed，方便复现；批量候选时把采样器“生成后控制”切为 randomize，再使用队列批次数量。先跑 1 张确认方向，再跑 4 张候选。

### UAP 统一生产工作台

`ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json` 已更新为视觉操作优化版。日常提示词、尺寸采样和最终预览集中在首屏，辅助工具按工作阶段分组。顶部导航支持分支选择、阶段定位、细分工具选择和上一步 / 下一步；QGN 罗盘与原快捷键继续保留。

选择分支用于浏览，点击“启用此分支”切换执行状态；切换保留各分支原有可选与旁路状态。SW / FX 开关只控制所属分支。主生产链、参数和子图保持原样。

集中式常用控制台的正负提示词、尺寸种子、采样参数、LoRA 选择与强度、出图模式、工具/细化开关直接同步原节点。现行权威为唯一主 Git 中的完整 UAP v2 与模板；修改、校验和新候选导出从主仓 `docs/technical/runtime/workflows.md` 开始。`layout_uap_workbench.py` 的旧覆盖入口已经封闭，不再用独立旧流重建当前图；历史布局和验收记录仅供追溯。操作说明见 `production_tools/UAP统一工作台说明.md`。

裁剪入口先运行一次取得预览，再拖选需要精修的区域。crop_right / crop_bottom 是边缘内缩量，回贴使用解析后的 left / top 和真实宽高。选区尺寸使用 64 的倍数。窗口重新打开后，裁剪框的前端属性与后端数值保持同步。

透明 PNG 应在支持透明度的软件或棋盘背景上检查；部分图片预览器会直接显示透明像素中保留的 RGB，看起来仍有背景。验收样例约 62% 像素为透明区域。

## 已确认的限制

- 现有两份 LLLite 权重针对原版 Anima，不能直接应用于 40 层 Anima 2.9B。2.9B 的 SW 控制分支保持关闭并有说明；需要控制时，先用原版生成，再用 2.9B 低降噪精修。
- Krea2 Turbo 编辑适合改色、添加、重绘；强删除使用 Raw 配方并另做验证。本版没有为删除任务切换你的主模型。
- 扩图已验证中心保留区域像素不变，但接缝、透视和延伸内容仍需逐张检查。
- BiRefNet lite 已实测可用。RMBG 内的可选 SAM3 实现缺 triton，生产现有原生 SAM3 与该可选实现不同，不以此宣称原生 SAM3 不可用。
- 历史验收未发送外部 API 请求；不据此宣称在线反推已通过。现行图片标签反推为本地 PixAI Tagger，WD14 仅保留禁用回滚档案。JoyCaption、视频和 LLM 扩展未穷举所有分支或模型。
- 不为旧 LLM / 视频插件降级 Torch。aisuite、torchscale 等旧依赖冲突保留在诊断记录，生产通过插件分组避免混用。

## 模板与个人副本

`production_tools/templates` 是本版冻结模板。个人调整仍保存在 `ComfyUI/user/default/workflows`，修改前可从模板另存一份。历史 `build_production_workflows*.py` 留作旧版生成记录，不能直接覆盖现用个人工作流；本次扩展的生成器和迁移脚本在下方报告目录。版本清单记录每个发布文件的 SHA-256。

## 批量结果检查

复用现有 Character LoRA Forge 的技术检查和页面生成，不新增评分插件，也不上传图片：

```powershell
.\python\python.exe -X utf8 -B .\production_tools\batch_review.py --input .\ComfyUI\output\production_extensions --output .\benchmark_reports\my_batch_review_01
```

打开生成的 `review.html`，逐张勾选，导出 `selected.csv`。技术分只反映曝光、边缘和尺寸，不代表角色一致性或编辑正确性。训练数据入库仍走现有 Forge 流程。

## 低资源维护

需要判断生产白名单是否还能缩小时，先运行纯静态节点盘点，不启动模型：

```powershell
.\python\python.exe -X utf8 -B .\production_tools\analyze_workflow_dependencies.py
```

结果写入 `benchmark_reports/2026-09-06_plugin_optimization/workflow_node_inventory.json`，记录工作流实际使用的节点、频次和当前服务器注册情况。该盘点不会自动移除插件；只有结合个人工作流和插件导入依赖复核后，才调整 `profiles.json`，调整后再做一次结构检查。

轻量入口只覆盖 `生产扩展_04` 到 `生产扩展_09`，不包含生产套件 01–03 的标签、画廊、LoRA 管理及姿态辅助节点；Anima/Krea2 专用入口分别覆盖主套件 01–02 和 03。需要全部个人旧流时继续使用生产入口。非 8188 端口会使用独立 SQLite 文件，避免测试实例锁住生产数据库。

## 证据与恢复

完整记录：`benchmark_reports/2026-09-06_plugin_optimization`，包含原始备份、迁移记录、API、history、输出、显存采样、像素检查、失败案例和发布清单。

恢复从唯一主仓的 `docs/RESTORE.md` 与 `docs/MAINTENANCE.md` 开始，先核对当前部署摘要、队列、服务身份和同批回滚材料。历史 benchmark 的 `rollback.py` 含固定路径及旧文件集合，不能直接执行；先比较当前状态，再按明确范围恢复，避免覆盖后来修改和更新的在线资料。旧原件继续保留。

上游依据：[LLLite 节点改名](https://github.com/kohya-ss/ComfyUI-Anima-LLLite)、[Krea2 Identity Edit 权重](https://huggingface.co/conradlocke/krea2-identity-edit)、[HostBuffer 已知问题与维护者说明](https://github.com/Comfy-Org/ComfyUI/issues/15255)。本机结论以报告中的实际回归结果为准。

## 启动配置复核

当前白名单以 `profiles.json` 为准。旧插件处置表属于整合前记录；Gallery、WeiLin、Anima 选择器、LoRA Manager 和 custom-scripts 的功能统一由 `ComfyUI-Unified-Prompt-Workbench` 加载，外层同名目录仅保留兼容路径。TB 多模型反推仍是独立插件。

`validate_profiles.py --inventory <resources_plugins_audit.json>` 可用捕获的节点注册表检查七种启动配置及嵌套子图依赖，全程不启动服务、不排队生图。最新结果在 `benchmark_reports/2026-09-28_workflow_ui/overnight_optimization/profiles_after_validation.json`。

生产/诊断配置覆盖主套件、扩展、UAP 和当前 Anima/Krea2 推荐入口；旧 `▶▷Krea2-高清生图优化流(整合).json` 仍缺 `GetImageSize+`、`SimpleMathDual+`、`LoaderGGUF`，保留作参考，不列入通过范围。轻量配置只供局部扩展任务，保持 5 个插件，不加载完整工作台界面。

## 维护与历史快照

后续网页 / 法典资料更新、预览生成与回写、测试依赖和历史恢复，请从 [资源维护入口](资源维护入口.md) 开始。207 个旧快照已可恢复归档至 `_archives/2026-09-28_workflow_cleanup`，原目录留有恢复说明；没有删除资源或释放磁盘空间。

本次 production 配置的实际重启由主任务执行，最终状态与验收以 `benchmark_reports/2026-09-28_workflow_ui/overnight_optimization/profile_live_restart.json` 为准；离线配置通过不能替代这份线上收据。


## 2026-10-03 运行配置与连续出图

生产配置已重启实测：24 个后端插件模块、统一包 5/5 就绪。18 份已保存工作流和 3 个已打开工作流的已注册后端依赖都在白名单内；历史流缺模型/节点的具体状态见 `工作流状态表.md`。原完整启动方式保留，不卸载插件。

常用控制台「连续出图 · 显存释放」提供“出图后卸载模型”勾选开关：选中时每张完成后卸载模型并清缓存，不选时保留模型。UAP v2 全部分支、生产套件 01–03 和扩展 04–09 默认不选。需要现在释放时使用立即释放按钮 / 专用 99 释放工作流；立即释放会先核对队列，并作用于整个后端。

性能小样本：固定模型/提示词/种子，768×512、30 步；确认复用模型的 3 次为 5.094、5.627、9.033 秒，每张释放的 2 次为 23.242、14.296 秒；共 8 次输出像素一致。不能据此推广所有模型、尺寸或承诺固定加速率。完整 API、history、遥测和回退见 `benchmark_reports/2026-10-03_runtime_phase2/`。
