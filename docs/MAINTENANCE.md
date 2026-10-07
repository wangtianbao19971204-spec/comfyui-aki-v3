# 日常维护流程

以下在本主仓根目录执行；本机 Python 为 `../../python/python.exe`。另一台机器可以使用 Python 3.10+；在线 capture 另需 psutil。verify/materialize 不要求导入 Torch 或启动 ComfyUI。

首次克隆、解释器选择、hooks 和后续主仓更新，先按[开始使用](GETTING_STARTED.md)执行。本页 PowerShell 命令沿用当前终端已核验的 `$comfyPython` 完整路径；带 `G:\` 的运行/输出目录是原机器示例，换机器使用实际路径。克隆后不直接启动 `snapshot/runtime`，先按[恢复方法](RESTORE.md)物化和补齐环境。

## 日常最短路径

1. `& $comfyPython -X utf8 -B scripts/maintain.py status`：看当前 Git、未提交改动、最后本地标签、hooks 与已登记的备份回执。它不检查在线服务，不把旧部署收据当当前状态；备份验收记录与当前代码/资料覆盖情况分别显示。
2. 从已同步的 `main` 创建本地工作分支，改对应源码、运行相关测试；同一功能沿用现行技术 MD，只补一条“改什么／为什么／验证与限制”的短记录。不要复制整套交付文档。
3. 精确 `git add -- <本次文件>` 后运行 `& $comfyPython -X utf8 -B scripts/maintain.py check-staged`，再明确提交。检查针对 **index**，不会把编辑器里未暂存的修复当成已入库；源码修改仍需下面的 seal/专项验证。
4. 相关本地验收和上传门禁通过后，推送本次分支并创建 PR，附变更、测试和限制；用户允许合并后再同步本地 `main`。需要部署时按下面流程做精确比较、回滚准备和真实验收；需要正式维护版本时再走 VERSIONING。普通代码修改不顺手刷新整套资料库。

`& $comfyPython -X utf8 -B scripts/maintain.py history` 默认只看最近 10 条 first-parent 主线；完整上游/旧仓历史仍在，不删、不改写。备份与保留规则可运行 `& $comfyPython -X utf8 -B scripts/maintain.py backup-policy` 查看。

提交快检首次需完整扫描暂存区；后续仍逐字节读取并计算 SHA，重新检查所有路径、当前分片顺序和跨片边界，只复用干净、未压缩、未使用审核例外的对象内容扫描。代码、规则、例外、对象或路径变化会使相应缓存失效；损坏回退全扫。`check-staged --fresh` 显式不用缓存。pre-push、正式发布、bundle 和 CI 仍完整扫描历史。缓存不替代测试、seal、快照校验或发布门禁，细节见 [安全说明](SECURITY.md)。

多个任务并行时优先使用同一主 Git 的临时独立工作树，各自上传分支并创建 PR，最终由用户允许合入 `main`；它们不是第二个权威仓。共用的运行服务、数据、manifest 和最终合入窗口仍需协调。当前任务不要擅自收走别人的暂存内容。

## GitHub 分支与用户合并流程

目的地固定为 [comfyui-aki-v3](https://github.com/wangtianbao19971204-spec/comfyui-aki-v3)，当前公开，可匿名拉取；推送仍需相应权限。唯一开发来源仍是本地主仓；GitHub 保存受审查分支、PR 和用户接受的主线。2026-10-07 的公开操作依据本轮用户明确指令，授权声明与实际可见性见[公开访问记录](technical/changes/operations-source-of-truth/2026-10-07-public-access.md)。

1. 首次上传：先核对内容、体积、资料/许可边界，再单独建立已审查的 `main` 基线及必要维护标签。2026-10-07 用户查看补齐后的上传预览后要求本地与线上一致，本次初始化使用已有 `main=bf6ac443cd8c7d1a87a5e12bb67142baf3dfeeb7`；补齐和实例组合说明上传 `fix/github-content-coverage-20261007`，以 PR 等待用户允许合并。精确推送 main、该分支和四个维护标签：`comfyui-v0.1.0`、`comfyui-v0.2.0`、`maintenance-v1-20261005`、`maintenance-public-v2-20261005`。不把功能分支直接初始化为 main，不镜像本机 legacy refs 或私有档案。上传是否成功以实际远端 refs 和仓外回执为准。
2. 后续开发：先保留已有改动，在干净 `main` 按[后续更新](GETTING_STARTED.md)执行 `fetch`/`merge --ff-only`；再用 `git switch -c <本次工作分支>` 创建分支。通常使用 `fix/`、`feature/`、`docs/`，版本准备使用 `release/`。不在运行区、插件旧目录或另一份本机 clone 开发。
3. 本地通过：运行与变更相关的测试、必要隔离 UI/工作流验收；源码按需 seal，资料/模型引用按专项说明核对。精确暂存并执行 `maintain.py check-staged`，提交应绑定实际测试范围与收据。失败或必要项目未覆盖时先修复，不把 CI 或结构检查当作 GPU/物理 IME 验收。
4. 上传分支：用户已持续授权通过本地验收与完整上传门禁后的日常分支推送和 PR 创建，无需每次再询问上传许可。核对 origin 是上述目的地，确认提交和工作树状态，使用 `git push -u origin <本次工作分支>`；保留 pre-push 的全历史门禁，不使用 `--mirror`、`--all`、`--force` 或跳过 hooks，也不直推日常改动到 `main`。有新修改时重做受影响验收。
5. 创建 PR：目标为 `main`，说明具体问题、变化、实际测试、未测限制及需要的回滚/部署范围；报告并附上 PR 链接。GitHub 的 `Maintenance integrity` CI 通过后仍由用户决定合并；助手不自行合并、不启用自动合并。默认由用户在 GitHub 手动合并；用户另行明确指定某个 PR 的合并操作时，按该次授权处理。
6. 合并后：在干净本地 `main` 再 `fetch`/`merge --ff-only origin/main`，核对合并结果并保留必要分支/历史。合并不自动加维护版本、打标签、公开仓库或部署运行区；生产切换仍需明确范围、保护与现场验收。

2026-10-07 用户明确委托助手合并本轮 [PR #1](https://github.com/wangtianbao19971204-spec/comfyui-aki-v3/pull/1)并统一主线；本轮按该次授权执行。后续 PR 仍沿用上述用户允许合并流程。

本地 hooks 现有功能是技术说明、完整性与凭证门禁，**不是远端主线保护**。另核 GitHub 当前可见性、权限/套餐并配置、验证要求 PR 与必要 CI 的保护规则；尚未实际配置前不能宣称服务器已防直推。使用用户同一账号创建的 PR 不能由作者批准自己的 review，单人流程不设置会阻塞自己的“必须 1 个 approving review”；由用户实际决定 Merge。官方：[分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[PR review](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/reviewing-proposed-changes-in-a-pull-request)。

### 两端一致性的核验

一致性检查比较同名分支，不要求尚未批准的工作分支与 main 内容相同。远端 URL 必须是上述无凭据地址；不要把 PAT 写在 origin 或脚本中。在干净主仓、上传完成后执行：

```powershell
$comfyPublishedBranch = 'fix/github-content-coverage-20261007' # 后续换成本次已上传分支
$comfyOriginUrl = git remote get-url origin
if ($LASTEXITCODE -ne 0 -or $comfyOriginUrl -ne 'https://github.com/wangtianbao19971204-spec/comfyui-aki-v3.git') { throw 'Unexpected origin' }
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed' }
foreach ($comfyRefBranch in @('main', $comfyPublishedBranch)) {
    $comfyLocalCommit = git rev-parse "refs/heads/$comfyRefBranch"
    if ($LASTEXITCODE -ne 0) { throw 'Missing local branch' }
    $comfyRemoteCommit = git rev-parse "refs/remotes/origin/$comfyRefBranch"
    if ($LASTEXITCODE -ne 0 -or $comfyLocalCommit -ne $comfyRemoteCommit) { throw 'Local and remote branch differ' }
}
```

首次多个 refs 使用原子推送；失败时保留失败回执并重新查远端，不静默改成部分上传、不强推。标签需同时核对 tag 对象号与 peeled commit。验收只覆盖明确上传的维护 refs，历史标签仍本地保存；GitHub 内容不含仓外原件。PR 状态、CI、是否合并和实际运行部署另行核实。完整实例的记录模板见[私有状态示例](../examples/private-state/README.md)。

## 1. 只在主仓开发

先查 PROJECT_MAP 和最新收据。正式 UI 代码、资料数据、模型配置、工作流和旧历史流是不同维护范围。现有快照是基线，不自动同步实时目录。

技术接手从 [分层入口](technical/README.md) 开始；每个功能有实现、数据、测试、示例、验收范围与日期式短更新记录。改动时同步对应 MD 或功能 changes 记录，新增功能补 `catalog.json` 的非空示例清单；治理、外部资源样例、库分片和资源登记也参加归属/说明检查。历史技术归档不直接执行，也不与部署源码竞争权威。并行任务先协调共享清单与 Git index/refs，不能仅凭工作树一时干净认定另一任务已结束。

所有 ComfyUI 相关代码、工作流、提示词库、数据库、加载器和维护工具均以本仓为唯一修改/提交入口。运行区所有旧 Git（本体、插件、工作台、训练依赖）均不再继续开发提交。功能改动在 `snapshot/runtime/` 对应源码中做，工作流子图随完整 JSON 维护；数据库结构/索引/触发器及迁移记录在 `database/`。不要直接手改资料分片，资料内容通过受审查工具导出后核验 ID、正文、个人字段与来源绑定。

```powershell
git config --local core.hooksPath .githooks
git config --local core.longpaths true
& $comfyPython -X utf8 -B scripts\project.py status
# 在 snapshot/runtime 中完成已授权的代码修改和专项测试，然后：
& $comfyPython -X utf8 -B scripts\project.py seal --note "本次修改说明"
& $comfyPython -X utf8 -B scripts\project.py deploy-plan --runtime G:\ComfyUI-aki-v3
```

`seal` 只重建普通源码清单，不重新认可被任意改写的 JSON/SQL；它保留旧 manifest 于 ignored local/source-seals，并明确标记 `live_deployed=false`、清空当前现场验收字段。旧 evidence 仍是历史凭据。`deploy-plan` 只读，未 seal 的源码会拒绝出计划，删除条目列为需审核候选，不会删除运行文件。

部署需要另建隔离候选、测试、线上基线和回滚，按明确范围写回后现场验收；不要一次覆盖整个 snapshot/runtime。工作台日常产生的资料记录仍由应用写入运行库，但任何相关代码/迁移脚本只能在主 Git 维护。完成真实部署后才允许第 2–3 步回收现场资料/验收基线。

## 2. 捕获已经确认的现场状态（不是日常反向同步）

关闭其他资料编辑操作，确认无同范围活动锁、队列为空。服务可以继续运行；采集工具不会停止服务，SQLite 通过在线 backup API 读取。

```powershell
& $comfyPython -X utf8 -B scripts\snapshot.py capture --runtime G:\ComfyUI-aki-v3 --out ..\comfyui-candidate-20261006
& $comfyPython -X utf8 -B scripts\repository.py compare --candidate ..\comfyui-candidate-20261006
```

日期/目录由本次实际日期替换。目标必须全新，禁止覆盖已有快照。source、library、数据库主文件/WAL 或服务身份漂移会失败；失败目录仅作为未完成候选，不可提交为已接受版本。先核对错误，再使用另一个新目录重试。SQLite backup 保证单库一致；各库和 JSON 不是共同事务，仍需安静的采集窗口。

服务停机维护时可以显式加 `--offline`，这会跳过队列与 readiness 门禁；必须在记录中标注未作在线核对，不能当作线上验收。

## 3. 接纳与提交

先提交或单独保存仓库已有改动。检查新增/删除/变化列表、metadata_* 中的模型/依赖/证据变化和凭证扫描，按风险运行源码测试、隔离 UI 与必要的中性样例推理。只读快照检查不能替代功能验收。

```powershell
& $comfyPython -X utf8 -B scripts\repository.py adopt --candidate ..\comfyui-candidate-20261006 --purpose accepted-deployment --review-sha256 "compare返回的review_sha256"
& $comfyPython -X utf8 -B scripts\snapshot.py verify
git diff --stat
git add -- docs CHANGELOG.md
git add -f -- snapshot
git diff --cached --stat
git commit -m "Update accepted workflow and library snapshot"
```

adopt 只移动维护仓的快照：旧版本保留到 ignored `local/backups/时间`，不会写回生产。候选必须是本仓旁的 `comfyui-candidate-*` 普通目录。`review_sha256` 绑定新旧 manifest，变化后须重新 review；`--purpose` 必须为已验收部署 `accepted-deployment`，或明确恢复/迁移 `recovery-migration`。源码、数据范围不符时不要 adopt，更不能把旧运行源码覆盖尚未部署的新主仓修改。更新 CHANGELOG 和验收说明，不把旧限制悄悄标为已修复。

当前 adopt 还要求新旧 manifest 的 `source_root` 完全相同，`recovery-migration` 也不豁免。其他机器改用不同运行根后的 capture/adopt 会被拒绝；保留候选另行评审迁移，不通过手改路径放宽门禁。源码编辑/seal 与显式 `deploy-plan --runtime` 的比较仍可在该机唯一主仓进行。

源码内保留了上游 `.gitignore`，所以仅在完整校验/凭证扫描通过之后，对精确的 `snapshot` 路径使用 `git add -f`。不要对运行根或整个维护仓使用强制 add。bundle 工具会检查快照是否全部被 Git 跟踪，防止嵌套忽略规则造成静默遗漏。

## 4. 生成可移交 Git 文件

需要正式维护版本时，先遵循 [VERSIONING](VERSIONING.md) 完成受审查的 prepare、显式提交与本地 tag，再执行打包。普通开发不自动递增版本；维护版本不替代本体/插件版本。标签、包、部署和实际功能验收分别记录，不能从一个动作推断其他动作完成。

```powershell
& $comfyPython -X utf8 -B scripts\repository.py bundle --out G:\ComfyUI-local\releases\comfyui-20261006.bundle
```

bundle 包含已提交的全部 refs/可达历史；不包含 ignored 文件、未提交内容、外部权重和媒体。工具要求干净工作树、快照完整性和完整历史凭证/资源门禁通过，再核验 fsck、bundle、refs 稳定性和 SHA-256，不接触远端。不能用 `--audit-content-only` 代替公开门禁，也不能绕过 hooks 发布。

每次在新目录 clone bundle（Windows 用 `git clone -c core.longpaths=true`），再做 snapshot verify、全历史凭证检查与所需离线还原。公开时仅推经过核验的主仓 refs；禁止整目录打包本机 `.git`、local、private-archives、旧克隆/还原目录或首版旧 bundle。日常上传遵循本页 GitHub 分支/PR 流程，首次初始化和公开许可仍须分别核对。

## 5. 回退

维护仓可先建新分支查看旧 tag/commit；不要在有未保存修改时使用 hard reset。adopt 的前快照仍在 local/backups，可用于人工比对。

生产回退是另一项操作：先核对当前源文件哈希、队列、进程身份、数据库状态，再使用对应**同一批发布**的恢复材料。旧 benchmark 脚本常有写死的时间/PID/路径，不可直接运行。UI 的恢复文件不能拿来回滚后来的资料库变更。

## 6. 备份与保留规则（不是执行回执）

唯一规则表为 [retention-policy.json](../governance/retention-policy.json)。它保持 `rules-only`，不保存本机实际备份目的地，也不执行备份/清理。规则中的 `independent_backup_verified: false` 只表示规则本身不作验收，不能拿它否认另有已验收的手动备份。

### 登记与查看实际备份

真实路径和验收回执只在仓外。对已验收的关键资料备份，在本仓的 Git 本地配置登记索引（不改全局配置、不提交私密路径）：

```powershell
$comfyBackupIndex = '<仓外已验收回执索引的绝对路径>' # 先替换为实际路径
git config --local comfyui.backupIndex $comfyBackupIndex
& $comfyPython -X utf8 -B scripts/maintain.py status
# 临时检查另一份索引，不改变已登记的索引：
& $comfyPython -X utf8 -B scripts/maintain.py status --backup-index $comfyBackupIndex --json
```

索引沿用手动关键备份的 schema 1：`main_git`、`backup_root`、`final_receipt`、`final_receipt_sha256`、`batch_id` 和已验收状态。解析器核对主仓归属、最终回执 SHA、绑定的阶段回执/清单 SHA、来源提交、数据库完整性记录、跨物理磁盘记录及配套副本回执；所有列入清单的有效载荷只核对存在、大小和普通文件身份。它不调用复制/恢复或在线数据库，不打开配置和数据库正文。

- 未登记：显示“无法判定”，不声称没有备份。换机器或新 clone 需重新登记本机索引。
- 无法访问或损坏：显示不可访问/核验失败，不降级采用旧副本或仅相信文件名和 `pass` 字段。
- 回执链有效：显示资料备份时间、源码版本/提交、资料数量和排除范围。HEAD 不同或有未提交修改时，明确不覆盖当前完整工作树。
- `--json` 的 `recorded_acceptance` 与 `receipt_chain_verified` 只描述记录及其摘要；`payload_sha256_rechecked`、`physical_disks_rechecked`、`live_data_freshness_checked` 保持 false。原固定 `independent_backup_verified` 状态字段已由这些精确字段替代，保留规则的同名字段不变。

快查不是重新逐字节验收、当前权限/磁盘拓扑复检、冷启动或备份之后资料的实时同步证明。哈希绑定也不是对可同时修改索引和回执的本机管理员的防伪认证。复制出去的历史失败回执可以保留，但成功数据必须由最终回执精确指定；不自动删除旧候选，不建立定时任务。若以后备份格式变化，应升级解析与测试，不能放宽校验后直接显示通过。

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
