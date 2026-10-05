# 日常维护流程

以下在 `maintenance/comfyui` 中执行；本机 Python 为 `../../python/python.exe`。另一台机器可以使用 Python 3.10+；在线 capture 另需 psutil。verify/materialize 不要求导入 Torch 或启动 ComfyUI。

## 1. 明确改哪里

先查 PROJECT_MAP 和最新收据。正式 UI 代码、资料数据、模型配置、工作流和旧历史流是不同维护范围。现有快照是基线，不自动同步实时目录。

改功能可以在维护分支的 `snapshot/runtime/` 对应源码中做，但这会使旧 manifest 校验失败，不能直接打成“已验收快照”bundle。先单独提交开发改动；经隔离测试、授权部署与现场验收后，重新 capture 并 adopt，才产生新的发布基线。发布到运行环境前必须另建候选、基线和回滚，不要把整个 snapshot/runtime 一次性覆盖到生产。修改提示词资料优先走现有工作台或审核过的迁移工具，随后重新 capture；不要直接编辑分片。工作流子图随原完整 JSON 一起维护。

## 2. 捕获已经确认的现场状态

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
& ..\..\python\python.exe -X utf8 -B scripts\repository.py adopt --candidate ..\comfyui-candidate-20261006
& ..\..\python\python.exe -X utf8 -B scripts\snapshot.py verify
git diff --stat
git add -- docs CHANGELOG.md
git add -f -- snapshot
git diff --cached --stat
git commit -m "Update accepted workflow and library snapshot"
```

adopt 只移动维护仓的快照：旧版本保留到 ignored `local/backups/时间`，不会写回生产。候选必须是本仓旁的 `comfyui-candidate-*` 普通目录。源码、数据修改范围不符时不要 adopt。更新 CHANGELOG 和对应验收说明，不把旧限制悄悄标为已修复。

源码内保留了上游 `.gitignore`，所以仅在完整校验/凭证扫描通过之后，对精确的 `snapshot` 路径使用 `git add -f`。不要对运行根或整个维护仓使用强制 add。bundle 工具会检查快照是否全部被 Git 跟踪，防止嵌套忽略规则造成静默遗漏。

## 4. 生成可移交 Git 文件

```powershell
& ..\..\python\python.exe -X utf8 -B scripts\repository.py bundle --out ..\comfyui-20261006.bundle
```

bundle 包含已提交的全部 refs/历史；不包含 ignored 文件、未提交内容、外部权重、媒体或密钥。工具要求干净工作树，核验 fsck、bundle 和 SHA-256，不接触远端。

## 5. 回退

维护仓可先建新分支查看旧 tag/commit；不要在有未保存修改时使用 hard reset。adopt 的前快照仍在 local/backups，可用于人工比对。

生产回退是另一项操作：先核对当前源文件哈希、队列、进程身份、数据库状态，再使用对应**同一批发布**的恢复材料。旧 benchmark 脚本常有写死的时间/PID/路径，不可直接运行。UI 的恢复文件不能拿来回滚后来的资料库变更。
