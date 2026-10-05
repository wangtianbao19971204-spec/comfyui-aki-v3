# 日常维护流程

以下在 `maintenance/comfyui` 中执行；本机 Python 为 `../../python/python.exe`。另一台机器可以使用 Python 3.10+；在线 capture 另需 psutil。verify/materialize 不要求导入 Torch 或启动 ComfyUI。

## 日常最短路径

1. `python -X utf8 -B scripts/maintain.py status`：看当前 Git、未提交改动、最后本地标签和 hooks。它不检查在线服务，不把旧部署收据当当前状态，也不冒称已有异盘备份。
2. 改对应源码、运行相关测试；同一功能沿用现行技术 MD，只补一条“改什么／为什么／验证与限制”的短记录。不要复制整套交付文档。
3. 精确 `git add -- <本次文件>` 后运行 `python -X utf8 -B scripts/maintain.py check-staged`，再明确提交。检查针对 **index**，不会把编辑器里未暂存的修复当成已入库；源码修改仍需下面的 seal/专项验证。
4. 需要部署时按下面流程做精确比较、回滚准备和真实验收；需要正式维护版本时再走 VERSIONING。普通代码修改不顺手刷新整套资料库。

`python -X utf8 -B scripts/maintain.py history` 默认只看最近 10 条 first-parent 主线；完整上游/旧仓历史仍在，不删、不改写。备份与保留规则可运行 `python -X utf8 -B scripts/maintain.py backup-policy` 查看。

提交快检首次需完整扫描暂存区；后续仍逐字节读取并计算 SHA，重新检查所有路径、当前分片顺序和跨片边界，只复用干净、未压缩、未使用审核例外的对象内容扫描。代码、规则、例外、对象或路径变化会使相应缓存失效；损坏回退全扫。`check-staged --fresh` 显式不用缓存。pre-push、正式发布、bundle 和 CI 仍完整扫描历史。缓存不替代测试、seal、快照校验或发布门禁，细节见 [安全说明](SECURITY.md)。

多个任务并行时优先使用同一主 Git 的临时独立工作树，最后协调合入 `main`；它们不是第二个权威仓。共用的运行服务、数据、manifest 和最终合入窗口仍需协调。当前任务不要擅自收走别人的暂存内容。

## 1. 只在主仓开发

先查 PROJECT_MAP 和最新收据。正式 UI 代码、资料数据、模型配置、工作流和旧历史流是不同维护范围。现有快照是基线，不自动同步实时目录。

技术接手从 [分层入口](technical/README.md) 开始；每个功能有实现、数据、测试、验收范围与日期式短更新记录。改动时同步对应 MD 或功能 changes 记录，新增功能补 `catalog.json`。历史技术归档不直接执行，也不与部署源码竞争权威。并行任务先协调共享清单与 Git index/refs，不能仅凭工作树一时干净认定另一任务已结束。

所有 ComfyUI 相关代码、工作流、提示词库、数据库、加载器和维护工具均以本仓为唯一修改/提交入口。运行区所有旧 Git（本体、插件、工作台、训练依赖）均不再继续开发提交。功能改动在 `snapshot/runtime/` 对应源码中做，工作流子图随完整 JSON 维护；数据库结构/索引/触发器及迁移记录在 `database/`。不要直接手改资料分片，资料内容通过受审查工具导出后核验 ID、正文、个人字段与来源绑定。

```powershell
git config --local core.hooksPath .githooks
git config --local core.longpaths true
& ..\..\python\python.exe -X utf8 -B scripts\project.py status
# 在 snapshot/runtime 中完成已授权的代码修改和专项测试，然后：
& ..\..\python\python.exe -X utf8 -B scripts\project.py seal --note "本次修改说明"
& ..\..\python\python.exe -X utf8 -B scripts\project.py deploy-plan --runtime G:\ComfyUI-aki-v3
```

`seal` 只重建普通源码清单，不重新认可被任意改写的 JSON/SQL；它保留旧 manifest 于 ignored local/source-seals，并明确标记 `live_deployed=false`、清空当前现场验收字段。旧 evidence 仍是历史凭据。`deploy-plan` 只读，未 seal 的源码会拒绝出计划，删除条目列为需审核候选，不会删除运行文件。

部署需要另建隔离候选、测试、线上基线和回滚，按明确范围写回后现场验收；不要一次覆盖整个 snapshot/runtime。工作台日常产生的资料记录仍由应用写入运行库，但任何相关代码/迁移脚本只能在主 Git 维护。完成真实部署后才允许第 2–3 步回收现场资料/验收基线。

## 2. 捕获已经确认的现场状态（不是日常反向同步）

关闭其他资料编辑操作，确认无同范围活动锁、队列为空。服务可以继续运行；采集工具不会停止服务，SQLite 通过在线 backup API 读取。

```powershell
& ..\..\python\python.exe -X utf8 -B scripts\snapshot.py capture --runtime G:\ComfyUI-aki-v3 --out ..\comfyui-candidate-20261006
& ..\..\python\python.exe -X utf8 -B scripts\repository.py compare --candidate ..\comfyui-candidate-20261006
```

日期/目录由本次实际日期替换。目标必须全新，禁止覆盖已有快照。source、library、数据库主文件/WAL 或服务身份漂移会失败；失败目录仅作为未完成候选，不可提交为已接受版本。先核对错误，再使用另一个新目录重试。SQLite backup 保证单库一致；各库和 JSON 不是共同事务，仍需安静的采集窗口。

服务停机维护时可以显式加 `--offline`，这会跳过队列与 readiness 门禁；必须在记录中标注未作在线核对，不能当作线上验收。

## 3. 接纳与提交

先提交或单独保存仓库已有改动。检查新增/删除/变化列表、metadata_* 中的模型/依赖/证据变化和凭证扫描，按风险运行源码测试、隔离 UI 与必要的中性样例推理。只读快照检查不能替代功能验收。

```powershell
& ..\..\python\python.exe -X utf8 -B scripts\repository.py adopt --candidate ..\comfyui-candidate-20261006 --purpose accepted-deployment --review-sha256 "compare返回的review_sha256"
& ..\..\python\python.exe -X utf8 -B scripts\snapshot.py verify
git diff --stat
git add -- docs CHANGELOG.md
git add -f -- snapshot
git diff --cached --stat
git commit -m "Update accepted workflow and library snapshot"
```

adopt 只移动维护仓的快照：旧版本保留到 ignored `local/backups/时间`，不会写回生产。候选必须是本仓旁的 `comfyui-candidate-*` 普通目录。`review_sha256` 绑定新旧 manifest，变化后须重新 review；`--purpose` 必须为已验收部署 `accepted-deployment`，或明确恢复/迁移 `recovery-migration`。源码、数据范围不符时不要 adopt，更不能把旧运行源码覆盖尚未部署的新主仓修改。更新 CHANGELOG 和验收说明，不把旧限制悄悄标为已修复。

源码内保留了上游 `.gitignore`，所以仅在完整校验/凭证扫描通过之后，对精确的 `snapshot` 路径使用 `git add -f`。不要对运行根或整个维护仓使用强制 add。bundle 工具会检查快照是否全部被 Git 跟踪，防止嵌套忽略规则造成静默遗漏。

## 4. 生成可移交 Git 文件

需要正式维护版本时，先遵循 [VERSIONING](VERSIONING.md) 完成受审查的 prepare、显式提交与本地 tag，再执行打包。普通开发不自动递增版本；维护版本不替代本体/插件版本。标签、包、部署和实际功能验收分别记录，不能从一个动作推断其他动作完成。

```powershell
& ..\..\python\python.exe -X utf8 -B scripts\repository.py bundle --out G:\ComfyUI-local\releases\comfyui-20261006.bundle
```

bundle 包含已提交的全部 refs/可达历史；不包含 ignored 文件、未提交内容、外部权重和媒体。工具要求干净工作树、快照完整性和完整历史凭证/资源门禁通过，再核验 fsck、bundle、refs 稳定性和 SHA-256，不接触远端。不能用 `--audit-content-only` 代替公开门禁，也不能绕过 hooks 发布。

每次在新目录 clone bundle（Windows 用 `git clone -c core.longpaths=true`），再做 snapshot verify、全历史凭证检查与所需离线还原。公开时仅推经过核验的主仓 refs；禁止整目录打包本机 `.git`、local、private-archives、旧克隆/还原目录或首版旧 bundle。GitHub 目的地仍须用户明确指定。

## 5. 回退

维护仓可先建新分支查看旧 tag/commit；不要在有未保存修改时使用 hard reset。adopt 的前快照仍在 local/backups，可用于人工比对。

生产回退是另一项操作：先核对当前源文件哈希、队列、进程身份、数据库状态，再使用对应**同一批发布**的恢复材料。旧 benchmark 脚本常有写死的时间/PID/路径，不可直接运行。UI 的恢复文件不能拿来回滚后来的资料库变更。

## 6. 备份与保留规则（不是执行回执）

唯一规则表为 [retention-policy.json](../governance/retention-policy.json)。目前 `rules-only`、备份目的地未设、无自动备份/清理任务；显示这些规则不代表已经创建副本或验收恢复。

| 内容 | 目标保留规则 |
|---|---|
| 原始 Git／迁移映射／唯一技术原件 | 一套完整、验证过的原始档案长期保留；本轮不删除其他副本 |
| 正式 bundle | 至少最近 3 个已验证版本；首个可恢复基线及被恢复链引用的版本额外保留 |
| 部署前备份 | 至少 3 个已验收版本且不少于 30 天；当前回滚依赖和未解决问题的原件继续保留 |
| 最新数据库 | 建议每日和导入/迁移前，用 backup API；7 日、4 周、6 月检查点，最新已验证及仍被引用者不淘汰 |
| 私密配置 | 变更后／部署前备份，至少 3 个已验证版本；仓外受控访问，离机副本加密 |
| 自训 LoRA／训练集／唯一源图与预览绑定 | 完成可接受版本后独立备份，不按缓存清理 |
| 临时验证树／失败候选 | 至少保留最近 2 代且不少于 30 天；结束、无使用者和恢复引用后才可列审核候选 |

以上是最低目标，不是自动删除阈值。真实备份先确认另一物理磁盘/独立介质、容量、权限及加密方式；不同盘符也不自动证明不同物理磁盘。多库与 JSON 应安排安静窗口，保留 ID、来源与个人字段；不在线覆盖 DB/WAL。

任何清理须列精确路径、查活动使用者与恢复引用、验证替代副本、生成审核摘要，优先可恢复移动并留收据。不得跟随 junction 删除目标；引用清单、同盘归档和旧 bundle 都不能当作新副本。模型、预览、原始数据与整个运行根不进入自动清理名单。
