# 仓外私密状态与大资源

公开 Git 不存 API key、登录配置、插件缓存凭证、数据库二进制、权重或原图。真实提示词的受审查文本导出不等同于凭证，不需因此清空。主仓源码与仓外状态分别维护，不能通过私密 `.py`、`.bat`、`.ps1` 等覆盖公开源码来恢复旧 key。

`scripts/external_state.py` 是离线清单与私密 overlay 工具，不部署、不启动服务、不联网。计划、实际机器路径、生成清单和回执均写在主仓之外。本机统一根由 `COMFYUI_EXTERNAL_ROOT` 约定；未设置时使用运行根同级的 `ComfyUI-local`。

## 数据角色

| category | 作用 | 允许动作 |
|---|---|---|
| `private_config` | 明确命名的插件鉴权/本机配置 | 小文件 `copy` 或 `reference` |
| `mutable_db` | 应用最新 SQLite 状态；不是 Git 旧检查点 | `reference` 或 `sqlite_backup` |
| `mutable_cache` | 可重建但可能带 key 的缓存 | 小型非可执行文件 `copy` 或 `reference` |
| `external_asset` | 模型、预览、图片等大资源 | 仅 `reference` |

本轮在线数据库、模型和预览仍保持原位置，使用 `reference`。小型配置可机械备份到 `private-config/`，但不是应用自动同步的第二份权威；应用修改后需重新登记/备份。

2026-10-07 模型分类命名已在运行区实施，具体权重位置改按来源目录的 `current_path` 恢复；上述保持原位置是建仓时的历史基线。分类后的仓外组合清单已重新 inventory 为 `external-runtime-model-standardization-20261007-01.json`，365 项登记并切换本机 current，旧清单保留。此刷新只记录现行边界，不复制模型或预览，也不覆盖在线数据库；实际摘要与命名验收见[标准化收据](receipts/model_standardization_20261007.json)。

最新清单入口为仓外 `manifests/external-runtime-current.json`；本轮计划为 `plans/external-runtime-plan-v7.json`，清单为 `external-runtime-privacy-completeness-20261007-01.json`，398 项。它绑定当前公共 manifest 与当时的外部指纹；每次主仓 manifest 或现场配置变化后均须重新 inventory，不能因为文件名带 current 就跳过指纹验证。历史 v5／v6 及其 365／364 项登记保留原时间点身份。

本轮把 `ComfyUI/models` 的一条整目录引用拆为 35 条模型子目录引用，将已入 Git 的 11 份架构 YAML 从外部范围精确分离；其余 363 条原登记保留。只改放置清单并保存旧 current，不复制权重／私密配置或替换数据库，也不放宽公开源码与外部 overlay 不得互相覆盖的保护。细节见[本轮复核](technical/changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)。

这些新增资源的可移植相对路径、角色和用途存于 [支持文件契约](../governance/runtime-support.json)；真实数据库指纹仍只存仓外。新增项全为 reference，不生成权重副本或数据库备份。

2026-10-07 上传内容复核后，easy-use 随附 ChatGLM 分词词汇已转为受审查 Git 支持文件；Gallery 辅助词典另外增加一致备份的全量 SQL 检查点，最新在线状态仍由 `mutable_db` 记录。v5 和上述“没有数据库备份”描述属于补齐前历史，不适用于本次 Gallery 的私有一致备份。变更 manifest 后须生成新仓外计划／清单，不能把旧 current 的指纹仍称当前。补齐范围见 [内容复核](receipts/github_content_reconciliation_20261007.json)。

上一轮已实际生成仓外 v6 计划和 `external-runtime-content-reconciliation-20261007-01.json`，364 项登记；其 current 现由上述 v7 核验结果取代，旧清单继续保留。减少一项只因分词词汇由外部资源转为 Git 支持文件，没有删除资源；其余 reference 仍非备份，未复制模型或用户图片。

2026-10-06 历史核验时，旧 current 清单有一份配置与三库 WAL 指纹变化，已保留旧清单并重新 inventory。当时清单为仓外 `manifests/external-runtime-recheck-20261006-01.json`；18 份 copy 小配置另外物化到新的私密备份目录，347 份 reference 仍只登记位置。该轮没有创建数据库备份或复制模型/图片，不能称完整实例已经备份或移机还原；它已由后续 current 取代。后续再次漂移仍须重新登记；摘要见 [复核收据](receipts/reassurance_20261006.json)。

## 使用与边界

完整的[公开组合示例](../examples/private-state/README.md)包含工具实际接受的 plan 格式和实例记录格式。将示例复制到自己的仓外 `plans/` 后，替换绝对根路径、选择实际存在的文件并运行 inventory；不要把真实配置、机器清单或输出再提交回 Git。示例不能代替自己的模型、图片或最新数据库。既有配置占位见[远端 LLM 配置](../snapshot/runtime/remote_llm_guard/remote-llm.config.example.json)，模型来源和图片绑定见[资源示例](../examples/external-assets/README.md)。

计划 JSON 为 `schema: 1`，包含 `roots`（仓外绝对本机根映射）与 `entries`。每项只允许 `id`、`root`、`source`、`target`、`category`、`action`，其中 source/target 必须为规范的 `/` 相对路径。不得包含密钥值。示意 entry：

```json
{
  "id": "example-plugin-config",
  "root": "runtime",
  "source": "ComfyUI/custom_nodes/example/config.json",
  "target": "ComfyUI/custom_nodes/example/config.json",
  "category": "private_config",
  "action": "copy"
}
```

```powershell
python scripts/external_state.py inventory --plan <仓外计划.json> --out <新仓外清单.json>
python scripts/external_state.py verify-dry-run --manifest <仓外清单.json> --dest <全新目录>
python scripts/external_state.py materialize --manifest <仓外清单.json> --dest <全新目录>
```

清单只记录路径、类别、动作、大小和校验值，不解析/输出文件内的凭证。即使没有凭证原值，实际路径和哈希清单也只作本地资料，不能整目录上传。工具拒绝路径穿越、大小写/Unicode 别名、ADS、链接/交接点/硬链接、重复目标、私密可执行载荷和公共源码覆盖。相同 target 唯一的选择例外是 `mutable_db` 对公共 `sqlite_sql` 检查点；它表达运行状态来源选择，不允许覆盖现存目标。

每个 copy 最多 8 MiB，总共最多 64 MiB；SQLite backup 最多 2 GiB，使用只读源连接和 backup API，检查 main/WAL 漂移及输出完整性。生产库持续写入可能让严格漂移门禁失败；不要因此关闭门禁或在线替换数据库，应另安排一致备份窗口。

`materialize` 只创建**新私密 overlay 目录**，不会覆盖公共还原目录，也不会自动把两棵树合成可运行环境。失败保留部分目录供核对，不清理/覆盖；需要重试时使用另一个新目标。Windows 上的文件创建模式不等同于 NTFS ACL，实际私密根须由维护者配置本机访问权限。

## 验收含义

- 小配置/SQLite 检查 SHA-256，数据库另登记 WAL；公共 manifest 变化或源状态变化均要求重新 inventory。
- 大型资产文件只核对路径与大小；目录引用不递归，标记 `directory_reference_only`，不保证内容哈希或所有资源齐全。
- `reference` 不复制文件、不创建 junction/symlink，回执保留 `unresolved_external_references`。
- 回执始终 `complete_runtime_restored: false`；源码快照仍须单独通过 `snapshot verify`。离线清单、私密 overlay 与真实启动/生图验收不能混同。

远端 LLM 启动器的本机配置另见 [REMOTE_LLM.md](REMOTE_LLM.md)；公开 BAT 和 helper 读取仓外 JSON，不把 JSON 或环境文件当脚本执行。
