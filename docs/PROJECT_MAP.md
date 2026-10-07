# 项目地图与源码归属

ComfyUI 相关修改的唯一开发入口是 `maintenance/comfyui/`，本机为 `G:\ComfyUI-aki-v3\maintenance\comfyui`。本体、插件、工作流、资料与维护工具都从主仓对应文件开发和提交。

## 仓内结构

| 目录 | 管理内容 |
|---|---|
| [snapshot/runtime/](../snapshot/runtime/) | 本体、插件、工作流及维护／训练工具的受审查源码 |
| [snapshot/library/](../snapshot/library/) | 真实提示词正文、Tag、个人字段和历史的文本／SQL 检查点 |
| [snapshot/inventory/](../snapshot/inventory/)、[manifest.json](../snapshot/manifest.json) | 外部资源引用、来源与受管理文件身份；引用不等于资源备份 |
| [database/](../database/) | 数据库契约、结构、迁移与格式样例 |
| [scripts/](../scripts/)、[.githooks/](../.githooks/) | 主仓维护、校验、发布与提交检查 |
| [tests/](../tests/)、[examples/](../examples/) | 隔离回归与公开格式／标注示例 |
| [governance/](../governance/)、[docs/](README.md) | 归属登记、版本约定、技术说明与验收收据 |

## 源码与正式流程入口

下表路径相对运行根；其唯一维护副本为 `snapshot/runtime/<相对路径>`。`WB` 表示 `ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/`。

| 范围 | 路径或入口 |
|---|---|
| 本体与安装插件 | `ComfyUI/`、`ComfyUI/custom_nodes/`；见[装配与启动](technical/runtime/core.md) |
| 工作台与五模块 | `WB/web/`、`WB/modules/`、[modules.json](../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json) |
| 正式 UAP | [ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json](../snapshot/runtime/ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json) |
| 权威模板 | [production_tools/templates/UAP统一生产工作台_v2.json](../snapshot/runtime/production_tools/templates/UAP统一生产工作台_v2.json) |
| 个人／历史工作流与冻结模板 | `ComfyUI/user/default/workflows/`、`production_tools/templates/`；分别保留，不自动互相覆盖 |
| 启动与白名单 | `production_tools/profiles.json`、`production_tools/launch.py`、运行根启动 CMD |
| 网页桥接、PixAI 与资料导入 | [网页接入](technical/runtime/browser-import.md)、[PixAI](technical/runtime/pixai.md)、`benchmark_reports/source_update_flow/` |
| 数据集与训练 | `character_lora_forge/`、`anima_lora_forge/`；见[训练工具](technical/training/README.md) |
| 独立服务与辅助工具 | `qwen21_lab/`、`scripts/`、`tools/`、`remote_llm_guard/`；见[独立服务](technical/runtime/independent-services.md) |

五模块为 WeiLin 共享资料、Anima 选择器、Gallery/UAP、LoRA Manager、Custom Scripts；装配以 `WB/modules.json` 为准。外层旧同名目录的兼容／历史身份不形成第二套开发权威；源码收录也不等于生产启用。

UAP 九分支为 Anima 原版、Anima 2.9B、Krea2 生产、Krea2 编辑、裁剪精修、透明抠图、左右扩图、独立二倍与四倍超分。内嵌子图、细化次序、二放和验收边界见[工作流说明](technical/runtime/workflows.md)。

本轮另补入 22 份模型架构 YAML、训练器采样示例和一份 WanVideo 的 Qwen 架构配置，按精确路径维护；它们不含权重。12 份旧技术／QA 原件保留在历史归档，范围及实际验收见[完整性复核](technical/changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)。

## 真实资料与 Git 检查点

`W` 表示 `WB/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/`；`G` 表示 `WB/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/`。

| 运行资料来源 | Git 中的对应内容 |
|---|---|
| `W/user_data/prompt_selector/` | [snapshot/library/json/](../snapshot/library/json/)：data、default、semantic_projection、shared_pairs、shared_sync_log 和 STORE_OWNER 六份主文件 |
| `W/user_data/userdatas_zh_CN_*.db` | [snapshot/library/sql/](../snapshot/library/sql/)：Tag、翻译／热度与历史三库的一致 SQL 导出 |
| `G/py/shared/data/tags_cache.db` | [gallery_tags_cache.db/](../snapshot/library/sql/gallery_tags_cache.db/)：独立词典、翻译、别名与导入历史，不能按文件名视为可丢弃缓存 |
| `W/random_tag/` | [random_templates/](../snapshot/library/random_templates/)：经审查的随机提示词模板 |
| `ComfyUI/custom_nodes/nsfwprompt/` 的登记资料 | [legacy_selector/](../snapshot/library/legacy_selector/)：旧独立选择器正文与编辑历史 |
| `ComfyUI/user/default/prompt-assistant/` 的五份明确资料 | `snapshot/library/prompt_assistant/{rules,tags,config}/` 原字节分片；[范围及状态](technical/changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)，不收鉴权配置，缺失不重建 |

详细实现与资料身份见[资料库档案](technical/library/README.md)和[数据库契约](DATABASE.md)。Git 分片是实际内容检查点；应用最新资料可能更新，旧检查点不得覆盖在线库。图片与缩略图另按外部资源保存。

## 运行区与仓外私有资料

运行区 `G:\ComfyUI-aki-v3` 是部署目标。完整实例由已部署的主仓文件，以及私密配置、模型／LoRA、媒体、依赖环境和最新运行数据共同组成；分支、主线与部署范围分别登记。

Git clone 取得源码与文字检查点；图库、模型／LoRA、Python/CUDA、最新 DB/WAL 和历史档案仍按外置层准备。外置层不统称隐私；鉴权及敏感历史单独保护，模型和环境主要受资源体积与安装需求约束。

仓外根 `G:\ComfyUI-local` 保管私密配置、机器清单、旧 Git 原件、备份与回滚材料。模型与图片可以仍在原运行路径，以仓外引用登记；路径引用不是备份，clone 不等于完成还原或冷启动。

边界和操作见[工作区](WORKSPACE.md)、[仓外状态](EXTERNAL_STATE.md)、[资源与示例](EXTERNAL_ASSETS.md)。历史追溯见[旧 Git](history/README.md)和[技术原件](technical/archive/README.md)；按功能查找[技术总索引](technical/README.md)，当前限制查[已知问题](KNOWN_ISSUES.md)。
