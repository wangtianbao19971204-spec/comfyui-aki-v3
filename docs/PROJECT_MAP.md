# 项目地图与归属

本机运行根目录：`G:\ComfyUI-aki-v3`。维护仓：`G:\ComfyUI-aki-v3\maintenance\comfyui`。Windows 路径不区分大小写，不能在同一父目录再建一个与现有 `ComfyUI` 同名的 `comfyui`，所以维护仓单独放在 maintenance 下。

表中“实际源路径”是最初捕获/最终部署的运行位置；今后开发权威位置为主仓 `snapshot/runtime/<相对路径>`，不是继续编辑那两个运行 Git。真实库分片在 `snapshot/library`；数据库结构、索引、触发器与迁移在 `database`。旧 Git 全图在当前仓历史中以归档合并保留，映射见 `docs/history`，不形成另一套活动工作分支。

| 范围 | 实际源路径（相对运行根） | 本仓库管理方式 |
|---|---|---|
| ComfyUI 本体 | `ComfyUI/` | 源码快照、上游 URL/提交、依赖版本；不复制嵌套 .git |
| 权威整合插件 | `ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/` | 统一包与 5 个 modules 的当前源码，不仅依赖各自旧 Git 跟踪名单 |
| 前端 UI | 统一包 `web/` | 主题、图标、工作台、资料检索、目标写入、运行控制 |
| 常用控制台 | 统一包 `modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/` | 导航、区域定位、控件与子图原参数映射 |
| 正式 UAP | `ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json` | 完整原文件，包含所有内嵌子图/连线/模式，不另拆一套失联子流程 |
| 权威 UAP 模板 | `production_tools/templates/UAP统一生产工作台_v2.json` | 与正式文件分别保留、分别核对哈希 |
| 其他个人流与历史流 | `ComfyUI/user/default/workflows/*.json` | 全部保留；不把历史流默认为当前构建源或已通过验收 |
| 冻结模板 | `production_tools/templates/` | 原样保存，允许与个人副本不同，不强行同步覆盖 |
| 启动与白名单 | `production_tools/profiles.json`、`launch.py`、根目录启动 CMD | 配置与脚本版本化；当前 live 服务身份另查，不能从旧文档的插件数量推断 |
| 权威共享资料 | 统一包 WeiLin 模块 `user_data/prompt_selector/` | 6 个当前主文件分片；data、默认资料、语义投影、关联、同步日志、归属说明 |
| Tag / 历史数据库 | 同一 WeiLin 模块 `user_data/userdatas_zh_CN_*.db` | backup API → SQL 分片；分组、词条、个人字段、修订、历史均保留 |
| 预览原图与缩略图 | `prompt_selector/preview`、`preview_thumbnails` | 外部媒体清单，不进 Git；不能视作可随意删除的缓存 |
| 模型 | `ComfyUI/models` 及生产插件内权重 | 路径/大小/mtime 清单及工作流引用关系；权重本体留在外部 |
| 网页/法典导入 | `benchmark_reports/source_update_flow` | 当前门禁脚本与说明；其他历史批次数据仍留在原目录 |
| 角色数据集维护 | `character_lora_forge/` | 当前维护源码；角色项目、图片、审核输出和私密配置外置引用 |
| Anima 训练维护 | `anima_lora_forge/` | Forge 源码与实际存在的 SD-Trainer/SD-Scripts 本地源码；不恢复现场已删除的上游文件、不携带权重与环境 |
| 独立 Qwen 实验服务 | `qwen21_lab/` | 当前维护入口及实际使用的独立源码；不是生产 8188 服务，也不代表已通过冷启动验收 |
| 根辅助工具 | `scripts/`、`tools/`、`remote_llm_guard/` | 公开可维护代码；远端鉴权从仓外 JSON 读取，二进制服务环境/模型不入库 |
| 其他安装插件 | `ComfyUI/custom_nodes/` | 受审查源码补迁；被捕获不等于启用，不变更 production 白名单 |
| 验收与已知问题 | 当前 part_refinement_pipeline STATE 指向的收据 | 当前 UI、工作流与推理证据分开保存，不互相替代 |

## 当前流程边界

UAP 保留九个工作分支：Anima 原版、Anima 2.9B、Krea2 生产，Krea2 编辑、裁剪精修、透明抠图、左右扩图、二倍和四倍超分工具。

两套 Anima 的细化次序：手 → 脚 → 原有区域标准/快速互斥支路 → 脸 → 眼 → 可选 1.5× 二放。工作台只显示/编辑原节点和子图，不额外生成一套隐形采样参数。细化与二放默认关闭；头发、四肢、人体、服装、独立皮肤细化不新增。独立 08/09 超分工具不是主流程自动续段。

工作台五模块：WeiLin 共享资料、Anima 选择器、Gallery/UAP、LoRA Manager、custom-scripts 补全。外层旧同名目录是兼容入口或历史副本；实际归属以统一包 `modules.json` 和当前服务注册为准。

## 捕获范围不是全部磁盘镜像

首版只捕获 production 插件；工作区整理补入其他已安装插件和独立维护项目的受审查源码，但**没有启用这些插件或改变生产配置**。代码归属不等于运行白名单。Python 前端分发包、CUDA、下载模型、LoRA Manager 的大型 Civitai 缓存、图库缓存、源网页原件、训练项目和历史 benchmark 媒体仍为外部资源。迁移前根据实际用途补齐，不可声称仅 clone 即可完全复现整台机器。

运行旧 Git 退休后的记录见 `governance/retired-git.json`，新历史映射见 `docs/history/`。真实目录与归档布局见 [WORKSPACE.md](WORKSPACE.md)。实际活动来源由主仓受审查文件清单确定，不能把仓外旧 benchmark 副本当成同名组件的新权威。
