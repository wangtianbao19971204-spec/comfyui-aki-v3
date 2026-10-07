# 私密与外部状态：公开格式示例

这三个文件只说明本地运行实例的组成，不含真实凭据、数据库、图片或模型。完整运行实例由主 Git 的已审查提交、匹配的依赖环境、本机私密配置、外部资源及应用最新数据共同组成。外部资料区不单独上传，也不是第二个开发 Git。

- [`external-plan.example.json`](external-plan.example.json) 使用 `scripts/external_state.py` 的实际计划格式，演示四个类别。根路径、目录名和资源身份都是占位；先在仓外另存副本，替换 `roots` 及实际需要的精确 `source`/`target`，再运行工具。占位目录不能当作现有配置或可用模型。
- [`instance-record.example.json`](instance-record.example.json) 说明如何一起登记 Git 提交、快照哈希、外部清单指纹、环境及验收状态。它不是生产加载器或导入器接口，也不是 `external_state.py` 的输入。真实实例记录保存到自己的仓外目录。

## 四类计划怎样处理

| 类别 | 本例动作 | 恢复含义 |
|---|---|---|
| `private_config` | `copy` | 小型远端 LLM 私密 JSON 复制到全新的私密 overlay；不读取或输出 token 原值 |
| `mutable_db` | `sqlite_backup` | 对 Gallery 当前辅助词库作 SQLite 一致备份；保留当前业务数据和历史 |
| `mutable_cache` | `reference` | 登记插件缓存目录；可重建性须由该插件确认，不自动复制或清理 |
| `external_asset` | `reference` | 登记完整资源目录；此操作不提供权重、逐文件哈希或图片备份 |

`target` 是新 overlay 内的相对路径，原计划并不把 overlay 自动合入运行树。远端 LLM 配置的正确位置是 `COMFYUI_EXTERNAL_ROOT/private-config/remote-llm/config.json`；不能放到运行区的 `remote_llm_guard/config.json` 来代替。SQLite 的同名 `target` 可以表达“取最新私密数据库”与“取 Git SQL 检查点”的来源选择，但工具不会覆盖任何已有文件。已有正式库、预览绑定及用户记录始终保留；Git 中的检查点和本例占位不覆盖它们。

## 凭据与环境变量

远端 LLM 的可复制格式见 [`remote-llm.config.example.json`](../../snapshot/runtime/remote_llm_guard/remote-llm.config.example.json)，使用方式见[远端 LLM](../../docs/REMOTE_LLM.md)。只在仓外的真实 JSON 中填写 `environment.AUTODL_TOKEN`、`environment.LEASE_SECRET` 等字段；示例中的尖括号字符串不能作为凭据使用。该 launcher 将允许的键交给相应子进程，绘世进程不继承这些私密键。

`COMFYUI_EXTERNAL_ROOT` 只指定仓外资料根，不会替其他插件自动填入 API key。各插件仍按自己的配置接口处理鉴权。用于隔离验收的 `LORA_MANAGER_SETTINGS_DIR` 应只设置在验证子进程中，不指向正式配置/缓存。不要把 token 拼到下载网址、命令行或公开记录，也不要执行 `.env` 文件来加载凭据。

在自己的终端按实际根路径设置，例如：

```powershell
$env:COMFYUI_EXTERNAL_ROOT = '<你的仓外资料根的绝对路径>'
```

先按[开始使用](../../docs/GETTING_STARTED.md)选择 `$comfyPython`，再在主仓运行以下步骤。所有计划、输出及 overlay 都必须位于仓外，overlay 必须尚不存在：

```powershell
$comfyExternalPlan = '<仓外审查后的计划.json绝对路径>'
$comfyExternalManifest = '<全新的仓外清单.json绝对路径>'
$comfyPrivateOverlay = '<尚不存在的新私密overlay目录绝对路径>'
& $comfyPython -X utf8 -B scripts\external_state.py inventory --plan $comfyExternalPlan --out $comfyExternalManifest
if ($LASTEXITCODE -ne 0) { throw 'External inventory failed' }
& $comfyPython -X utf8 -B scripts\external_state.py verify-dry-run --manifest $comfyExternalManifest --dest $comfyPrivateOverlay
if ($LASTEXITCODE -ne 0) { throw 'External state verification failed' }
& $comfyPython -X utf8 -B scripts\external_state.py materialize --manifest $comfyExternalManifest --dest $comfyPrivateOverlay
if ($LASTEXITCODE -ne 0) { throw 'Retain the partial overlay and review the failure' }
```

这些工具不启动服务、不下载模型、不把 overlay 部署到生产。`reference` 仍是未复制的外部引用，回执的 `complete_runtime_restored` 始终为 `false`；取得源码、资料物化、私密 overlay、依赖冷装与真实工作流验收分别核对。

## 模型与图片对应关系

网上资源的实际来源页、版本/文件身份、上游原名和现行放置路径在[模型来源清单](../../docs/MODEL_SOURCES.md)。使用 `current_path`，不存在该字段时才使用 `path`，同时恢复匹配版本的完整目录配套。四份自训成品必须另备份原权重；下载网址和训练代码不能重建已经完成的权重。

图片关系沿用 [`annotations.example.json`](../external-assets/annotations.example.json)：记录 ID、来源 ID、原图、缩略图及主预览作为一组保存；SVG 只是文档预览，不替换正式 PNG/JPEG 或写入正式库。训练图与同名 caption、来源输入、选择记录也一起保留。[外部资源说明](../../docs/EXTERNAL_ASSETS.md)列出放置位置，[恢复方法](../../docs/RESTORE.md)说明源码物化和正式数据保护。

## 更新记录

- 2026-10-07：增加四类别工具计划与完整实例登记样例，明确私密根、token 子进程环境、最新库来源选择、图片绑定及仅引用资源的未恢复边界；不包含真实私密资料。
