# 快照目录说明

`snapshot/` 保存主仓实际管理的内容。运行源码、真实资料、资源登记和历史验收分别存放，按 [manifest.json](../snapshot/manifest.json) 核对身份与哈希。

这是 Git 的源码与文字检查点，不是整机镜像。运行区图库、模型／LoRA、Python/CUDA、最新在线 DB/WAL、鉴权及历史档案按[外置组合](../examples/private-state/README.md)另行准备；模型和环境外置主要受资源体积与安装需求约束，不能一概叫隐私。

## 四个子目录

| 目录 | 保存什么 | 怎么读和维护 |
|---|---|---|
| `runtime/` | 本体、插件、工作流、启动与训练工具源码 | 在主仓对应文件修改；功能归属查[项目地图](PROJECT_MAP.md) |
| `library/` | 真实提示词/SQL 检查点、随机模板及旧选择器资料 | 通过受审查导出维护；使用恢复工具合并分片，保留原 ID 与历史 |
| `inventory/` | 模型来源、历史盘点、依赖环境及媒体清单 | 登记资源身份；权重、图片和依赖安装包另行准备 |
| `evidence/` | 捕获时保存的 UI、工作流和推理验收记录 | 按时间和范围读取，不用旧回执推断当前在线状态 |

## runtime：按功能找源码

| 路径 | 用途 | 详细说明 |
|---|---|---|
| `ComfyUI/` | 本体和已捕获插件 | [本体与装配](technical/runtime/core.md) |
| `ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/` | 工作台和五个整合模块 | [工作台](technical/runtime/workbench.md) · [选择器](technical/library/selectors.md) |
| `ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/` | 五站油猴脚本与工作台接收桥接 | [网页接入](technical/runtime/browser-import.md) |
| `ComfyUI/user/default/workflows/` | 保存的完整工作流与内嵌子图 | [工作流](technical/runtime/workflows.md) |
| `production_tools/` | 启动白名单、权威模板与构建/校验工具 | [工作流](technical/runtime/workflows.md) · [本体](technical/runtime/core.md) |
| `character_lora_forge/` | 角色金图与训练数据维护工具 | [数据 Forge](technical/training/data-forge.md) |
| `anima_lora_forge/` | Anima 训练与评估工具、训练器源码 | [LoRA Forge](technical/training/lora-forge.md) |
| `qwen21_lab/`、`tools/` | 独立实验服务和辅助工具 | [独立服务](technical/runtime/independent-services.md) |
| `remote_llm_guard/` | 从仓外配置读取鉴权的启动封装 | [远端 LLM](technical/operations/remote-llm.md) |
| `benchmark_reports/source_update_flow/` | 资料导入与增量更新门禁 | [资料导入](technical/library/web-import.md) |

同名旧插件和历史脚本的存在不代表当前启用。找唯一实现时沿[机器目录](technical/catalog.json)的 `implementation` 与 `watch` 定位。

本轮补入 22 份模型架构 YAML、289 字节训练器采样示例和一份 WanVideo 的 Qwen 架构配置；权重仍外置。[补齐说明](technical/changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)记录范围，不代表已收录权重或已部署生产。

## library：真实资料与分片

| 路径 | 内容 |
|---|---|
| `json/` | 六份共享提示词/关联/语义投影等原文件的字节分片 |
| `sql/` | 三个主库及 Gallery 辅助词库的完整逻辑 SQL 检查点 |
| `random_templates/` | 经审查的随机提示词模板 |
| `legacy_selector/` | 旧独立选择器正文和编辑历史，保留独立身份 |
| `prompt_assistant/` | 固定五份规则／预设／标签／选用状态的原字节 chunks，共 214,283 字节；不包含鉴权 `config/config.json`，缺失不重建 |

这些资料是实际内容，不是虚构示例。不要手工拼改 `.part`，也不要把旧检查点直接覆盖在线库。Gallery 的恢复另有明确 FTS5 重建规则；详见[资料库技术入口](technical/library/README.md)和[恢复指南](RESTORE.md)。

## inventory：来源与位置

| 文件 | 读法 |
|---|---|
| [model_sources.json](../snapshot/inventory/model_sources.json) | 模型/LoRA 公开网址、版本/文件身份、原名和现行 `current_path`；无该字段才用 `path` |
| [models.json](../snapshot/inventory/models.json) | 捕获时的模型盘点，保留历史身份；不代替现行安装路径 |
| [workflow_models.json](../snapshot/inventory/workflow_models.json) | 捕获时的工作流资源引用，用于追溯 |
| [environment.json](../snapshot/inventory/environment.json) | 已安装版本记录；不是经过新机冷装验收的锁文件 |
| [library_media.jsonl](../snapshot/inventory/library_media.jsonl) | 预览原图/缩略图的路径、大小和时间；不包含图片本体 |
| [upstreams.json](../snapshot/inventory/upstreams.json) | 本体/插件的上游身份和捕获范围 |

维护模型先读[下载来源](MODEL_SOURCES.md)与[分类命名](MODEL_NAMING.md)，AI 读取对应 JSON。摘要为 `null` 表示未核验，网址也不保证当前可下载。

快照目录内的所有载荷都受完整性清单约束，因此这份导航放在 `docs/`。新增说明不自动成为运行部署文件；更新源码清单仍按[日常维护](MAINTENANCE.md)执行。
