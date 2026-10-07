# 维护包版本与显式发布

这里的 SemVer 只标识统一 **comfyui 维护包**，不修改 ComfyUI 本体、插件、模型、数据库 schema 或它们的上游版本。`governance/version.json` 是唯一计数器；初始 `0.0.0 / unreleased-baseline` 表示尚未开始正式维护包编号，不代表当前 ComfyUI 软件版本，也不宣称已有 `comfyui-v0.0.0` 发布。

旧 `maintenance-v1-20261005` 与 `maintenance-public-v2-20261005` 标签是实际保留的历史标签。`public-v3` 是旧交付包/文档名称，不因此补造一个曾经存在的正式 SemVer 标签；旧标签和历史内容不改写。

## 自动递增的边界

普通开发只维护 Unreleased 变更和对应技术档案，不在每次保存、seal、提交或测试后自动加版本。完成同一逻辑变更、相关测试和文档后，先按[分支/PR 流程](MAINTENANCE.md)由用户接受源码，再从同步后的干净 `main` 建立显式 `release/` 分支准备发布：

| 指定类型 | 自动计算 | 适用范围 |
|---|---|---|
| `patch` | `1.2.3 → 1.2.4` | 向后兼容修复 |
| `minor` | `1.2.3 → 1.3.0` | 向后兼容功能 |
| `major` | `1.2.3 → 2.0.0` | 不兼容维护接口/恢复契约，需要明确评审 |

第一次正式编号可显式 `--bump minor` 得到 `0.1.0`，或经评审用 `--bump major` 得到 `1.0.0`。是否已准备或发行，以实际 version.json、版本说明和对应 annotated tag 为准，不从此说明页推断。工具不猜测语义类型，不修改第三方版本，不隐式 commit/push/tag，也不部署或回滚生产。

## 1. 准备受审查说明与回滚引用

在仓外写一个 UTF-8 JSON，计算它的 SHA-256。它是待审核材料，不要写真实凭证或机器私有路径。示意结构如下；提交 ID 和摘要必须替换成实际已核对的值：

```json
{
  "schema": 1,
  "summary": "本次维护包的实际变更",
  "components": ["workbench"],
  "changes": ["变更内容、原因和兼容性影响"],
  "tests": ["实际运行的测试及对应收据标识；未测范围必须说明"],
  "rollback": {
    "target_commit": "<40位维护仓提交ID>",
    "receipt_id": "reviewed-recovery-plan",
    "receipt_sha256": "<64位仓外回滚材料回执SHA256>",
    "scope": ["仅本次明确列出的源码；实际备份清单由回执绑定"],
    "limitations": ["不覆盖当前数据库、配置或后续用户资料；线上回退另行授权"]
  }
}
```

回滚目标必须是源版本的祖先，并含维护仓 `snapshot/manifest.json`，不能误选导入的上游历史。工具会读取指定仓外回执并核对其真实字节摘要；公开说明只保留 ID/摘要，不复制私密回执正文。摘要核对只证明这份回执存在且匹配，**不是已经执行回滚、检验全部备份内容或建立加密备份**。`tests` 是人工审查记录，不会把文字描述变成自动化测试证据。

## 2. 显式 prepare，不自动提交

先确认没有同范围活动修改者；在已同步并通过相关验收的源码提交上创建 `release/<本次版本或名称>` 分支。命令要求显式预期分支、精确预期 HEAD、精确当前版本，以及无已暂存/未暂存/未跟踪修改的工作树。`--expected-branch` 必须是当前实际检出的合法 `release/` 分支，不能是 `main`，也不隐式猜测分支。`technical_catalog.py check` 必须通过。

```powershell
python -X utf8 -B scripts/release.py status
# 先将下面的分支名、版本与所有占位值替换为实际已审查值：
git switch -c release/comfyui-vX.Y.Z
python -X utf8 -B scripts/release.py prepare --expected-branch release/comfyui-vX.Y.Z --expected-head <当前40位HEAD> --expected-version <当前X.Y.Z> --bump <patch或minor或major> --notes <仓外已审说明.json> --review-sha256 <说明文件SHA256> --rollback-receipt <仓外回滚材料回执.json>
```

prepare 自动计算下一版本，只写 `governance/version.json` 与新的 `docs/releases/comfyui-vX.Y.Z.json`，不改 CHANGELOG 或源码。它绑定显式 release 分支和源码 HEAD，返回实际 `preparation_branch`；要求声明和回执摘要准确，拒绝秘密、链接输入、覆盖旧记录、分支/HEAD 切换和并行漂移；旧版本说明不可覆盖。其专用锁仅协调遵守该协议的发布者，不能阻止其他应用编辑文件；发现外部变化会失败，不会吞并其他人的内容。

prepare 不运行昂贵的全历史扫描，**不表示发布验收通过**。人工复核生成说明、技术档案和 Unreleased 后，在同一 release 分支更新 CHANGELOG、暂存精确文件并提交；完成本地验收及上传门禁，推送分支并创建目标为 `main` 的 PR，由用户允许合并。prepare 之后若又改源码，不能直接给旧准备结果打标签，必须重新审查准备流程。

说明记录 `base_commit`（待发布源码提交），不把尚不存在的“自身提交 SHA”写进自身内容。最终发布提交由随后生成的 annotated tag 与仓外交付收据绑定，避免自引用哈希循环。

## 3. 独立显式 tag

用户合并版本 PR 后，按[后续更新](GETTING_STARTED.md)将干净本地 `main` fast-forward 到远端结果，再显式执行 tag。PR 应保留 prepare 所绑定的源码提交作为主线祖先；若同时改变源码、合并后主线产生别的功能差异或源码祖先关系失效，旧准备结果拒绝发行，重新准备/审查。工具不调用 GitHub API 判断批准记录，用户授权由工作流程保证，不能把 tag 成功当作已经取得合并授权。

```powershell
python -X utf8 -B scripts/release.py tag --expected-head <已提交发布说明后的40位HEAD> --expected-version <X.Y.Z>
```

此命令再次要求干净 `main`、一致版本/说明/清单和预期 HEAD；源提交之后只允许本次版本文件、对应发布说明及 CHANGELOG 变化。随后运行技术档案检查、快照验证、**完整** `security_guard.run` 全历史正文与名称门禁，以及 `git fsck --full --strict`。没有 content-only/names-only 替代选项。

通过后使用原子 compare-and-create 创建 `comfyui-vX.Y.Z` annotated 本地标签，绑定发布提交、源提交、说明摘要和 manifest 摘要。不会覆盖/移动已有标签，也不会 commit 或 push。HEAD 在门禁期间或创建瞬间变化会拒绝；若标签创建后另一个程序才改变现场，工具明确报告“标签已创建但后验现场漂移”，保留标签待审，不冒称完整成功。

`version.json` 的 `prepared` 表示发布元数据已经准备，不是线上状态。成功标签是该版本本地发行身份；下次 prepare 要求前次版本标签已经显式建立。没有标签时不可悄悄继续递增。Git 管理员仍可绕过工具或禁用 hooks，因此本地约定不等同于远端受保护分支。

## 4. 包、部署与回退分别记录

标签不等于包、GitHub 发布或生产部署。之后仍需 `repository.py bundle` 的完整门禁、冻结包 SHA、fresh clone 的 snapshot/fsck/对象检查和需要的隔离物化验收；日常分支上传按持续授权执行，正式标签/发行、公开和生产切换须各自明确授权。每份正式回执应绑定版本、精确提交/tag、manifest、说明摘要、包摘要、实际验收、外部资源限制和回滚材料 ID。

若复用刚完成的完整正文扫描，必须证明两份克隆的 refs 语义/包头 refs、全部可达对象 OID/type/size、全部存储对象恰好可达、文件树、manifest、扫描器和例外 registry 完全一致，并在最终 clone 新跑名称门禁、snapshot verify、strict fsck。任一差异不得复用；必须重新全量扫描或拒绝不一致包。回执明确“复用扫描”，不得称为第二次正文扫描；中止的重复扫描不得计作 PASS。

生产回退记录应另写本批次的目标/当前提交、精确文件清单、操作前后哈希、真实备份位置的仓外引用、数据库与用户资料的处理限制和实际结果。代码回退不是数据库回退；发布版本号也不倒减。尚未执行的回退只能记为计划，不能写“已回滚”。本工具只审查回滚引用，不执行或自动登记一次实际生产回退。

## 私密目录不是第二个 Git

当前 `G:\ComfyUI-local` 是普通仓外资料目录，不是统一私有 Git；其中的退休 Git、验证 clone 和 bundle 不使根目录自动获得版本管理。没有在此流程建立凭证加密、自动同步或异地备份。NTFS 访问权限、加密方案、密钥托管、保留周期和恢复演练需要独立设计与验收，不能从“private-config”目录名推断已经加密。
