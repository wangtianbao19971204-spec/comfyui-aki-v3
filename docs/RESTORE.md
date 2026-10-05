# 恢复与迁移

## Git bundle 恢复

仅使用随包交付回执确认通过的版本；包名、维护版本号、精确提交、manifest SHA、包 SHA 和隔离还原结果必须属于同一轮。当前交付目标为 `comfyui-v0.2.0-20261005.bundle`，对应 `comfyui-v0.2.0-20261005.delivery.json`；以该回执实际存在且 `pass: true` 为最终交付依据，文档中的目标名本身不是验收证明。后续发行沿用这一命名方式，替换为对应版本的实际文件名。

`comfyui-public-v3-20261005.bundle` 只覆盖 `f1e61294` 历史检查点，不包含后续 Anima 补丁、技术补档、维护命令及支持文件补录。它和旧验证目录保持历史身份，不充当最新版；旧 `comfyui.bundle` 含历史凭证，只能私有归档，不能公开复用。

```powershell
$comfyDelivery = Get-Content -LiteralPath .\comfyui-v0.2.0-20261005.delivery.json -Raw | ConvertFrom-Json
if ($comfyDelivery.pass -ne $true) { throw 'Delivery is not accepted' }
$comfyBundle = Join-Path (Get-Location) $comfyDelivery.bundle.filename
if ((Get-FileHash -LiteralPath $comfyBundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $comfyDelivery.bundle.sha256) { throw 'Bundle SHA256 mismatch' }
git clone -c core.longpaths=true -- $comfyBundle .\comfyui
if ($LASTEXITCODE -ne 0) { throw 'Clone failed; retain the partial directory for inspection' }
if ((git -C .\comfyui rev-parse HEAD).Trim() -ne $comfyDelivery.commit) { throw 'Restored commit differs from delivery receipt' }
git -C .\comfyui fsck --full
cd .\comfyui
python -X utf8 -B scripts\snapshot.py verify
python -X utf8 -B scripts\security_guard.py --all-history
git config --local core.hooksPath .githooks
```

克隆产生的 origin 只是本地 bundle 路径，不是在线远端。首次仓库使用专用维护作者标识，不修改用户全局 Git 身份；后续提交可以配置你自己的 repo-local user.name/user.email。

随包回执与包一样保存在仓外，完整详细证据见其 `evidence_id`。回执必须由实际结束的门禁和还原生成；未完成的 `prepared` 元数据、单独的 tag 或旧还原回执都不能替代。文档、版本说明先冻结并提交，最终 SHA/提交/验收结果写在仓外，避免为了把“本包最终 SHA”塞进本包而出现自引用或打包后再次改源码。

Windows 必须在初次检出前使用上面的 `-c core.longpaths=true`：整合插件目录较深，较长的父目录可能触发 `Filename too long`。该选项只设置新克隆仓库，不修改全局 Git 或系统注册表。已有仓库可用 `git config --local core.longpaths true`；失败的半成品克隆不要当作验收通过，也不要直接向生产恢复缺失文件。

## 只向全新目录物化

```powershell
python -X utf8 -B scripts\snapshot.py materialize --dest G:\ComfyUI-local\validation\comfyui-restored-v0.2.0-new
```

目标目录必须不存在。工具拒绝直接写回 manifest 原运行根、原 ComfyUI 树和 snapshot 内部。它不会启动服务、执行模型或覆盖现有文件。

每轮使用全新目录，不重用上例中已经存在的目标。验收须从本轮 bundle 的新 clone 中执行，并核对还原回执的 manifest SHA 与随包回执一致；主仓本地文件校验通过不等于交付包已经可还原。

- 普通源码/工作流：逐文件 SHA-256 一致。
- 上游 `.gitattributes` 在 Git 内以 `.gitattributes.upstream` 保存原字节，物化时恢复原名称，避免嵌套换行规则改写快照。原 `.gitignore` 保留。
- 大型 JSON：按清单合并 .part，恢复原始编码/换行/字节并核对整文件 SHA。
- SQLite：从已校验 SQL 分片新建数据库，核对 integrity_check、全部表行数和完整逻辑 SQL 哈希。数据库二进制页布局可不同，不宣称 .db 字节相同。
- 生成 `RESTORE_RECEIPT.json`。临时合并的 `.restore.sql` 保留在物化目录供检查；它不是线上数据库。

## 物化后还需要什么

1. 按 environment.json 准备 Python、ComfyUI 前端分发包、Torch/CUDA 和插件依赖。该文件是已装版本清单，不是经过新机器冷装验收的锁文件，不要无审核整批安装或降级。
2. 从原备份另行恢复完整模型目录及插件内权重，包含 config/tokenizer/processor 等伴随文件。
3. 另行恢复 preview 与 preview_thumbnails，保持同名和相对路径，核对 library_media 清单。清单不是图片副本。
4. 根据仓外 `external-runtime` 清单安全补齐机器/认证配置，初版 `excluded_private_configs` 不是完整的后续清单。API key 不写进 Git；远端 LLM 启动器配置放在仓外 `private-config/remote-llm/config.json`。详见 EXTERNAL_STATE.md。
5. 已补迁的插件、两套 Forge、Qwen Lab 与训练依赖源码以 manifest 和 PROJECT_MAP 为准；它们的模型、数据集、输出、依赖二进制及历史媒体仍需单独迁移。旧私有 Git、源网页原件和回滚材料仅供审查/恢复，不重新启用为开发来源。
6. 静态检查工作流节点/模型引用和 profile；修复缺失必须保留工作流原意，不自动启用旁路分支或换底模。
7. 用独立端口、隔离数据做启动/浏览器/中性样例验收；明确通过范围后再决定正式切换，不能直接覆盖正在运行的 8188。

## 不是完整灾备镜像

本 bundle 可还原管理范围内的代码、保存工作流、提示词 JSON 和三库逻辑数据。模型、预览、认证、Python/CUDA 运行环境与旧历史媒资需要独立备份。建议把这些外部资源与 bundle 一起离线存放，并分别记录校验值；不要把“Git 可克隆”误认为“全部数据已异地备份”。
