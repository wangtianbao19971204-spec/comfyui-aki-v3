# 安全、隐私与分发

本仓库已在 GitHub 创建 [comfyui-aki-v3 私有仓](https://github.com/wangtianbao19971204-spec/comfyui-aki-v3)。2026-10-07 当前阶段为空仓，本地尚未配置在线远端或首次上传；公开目标的许可与个人信息边界仍须核对。用户已明确允许保留真实提示词、收藏、备注和历史；这不包括 API key、访问令牌、登录会话、插件配置/缓存中的鉴权资料，也不授予第三方内容再分发许可。

## 不入库

- API key、Cookie、访问/刷新 token、私钥、登录会话、认证头。
- 运行中的 .db/.sqlite/WAL/SHM；文字资料数据库仅以一致 SQL 导出入库。
- 模型大权重、Python/虚拟环境、node_modules、缓存、生成图、预览媒体、训练数据和整套历史备份。
- 机器私有 settings/providers/config 文件，具体排除路径在 `snapshot/inventory/excluded_private_configs.json`。

扫描只输出类型、路径、对象 ID 和摘要，不输出凭证值。WeiLin 的个人 `init.json` 整份排除，迁移时安全补齐；caption 插件 `models_cache.json` 即使当前只有模型名，也从当前版本移除并禁止再次捕获。库导出只接受已审查三库和明确登记的 Gallery 辅助词典，不自动导出新增 auth/provider/cache 数据库。Gallery 的词典、译文与导入历史经逐字段和全载荷审查后作 SQL 检查点，不豁免其他缓存。分词器、模型架构和界面语言配置按明确路径保留，仍参加扫描。

## 自动门禁与例外

```powershell
python -X utf8 -B scripts/security_guard.py --staged
python -X utf8 -B scripts/security_guard.py --all-history --report local/security-audit/pre-publication.json
git config --local core.hooksPath .githooks
```

`--staged` 读整个 index 的 Git 对象，不以工作树中的“已删密钥”冒充 staged 安全；`--all-history` 遍历所有可达提交、tag、blob 和历史路径别名，含已删除文件。扫描还检查提交/tag 消息、压缩载荷、source-map 转义和 JSON/SQL 分片边界；遇到不支持/损坏压缩格式会失败，不静默跳过。报告检查扫描前后 refs/index 是否漂移。`--audit-content-only` 只供旧上游调查，不是公开门禁。

少量已人工核对的虚构安全测试和历史无密钥模型名缓存按精确路径、完整 SHA 放行；不豁免整个 tests、插件、历史分支或库目录。新增/变化字节需重新核对。源码 `seal` / `snapshot verify` 以完整性和基础扫描为主，**不能代替这项全历史安全门禁**。

本地 pre-commit 强制 index 门禁，pre-push 强制全历史门禁；bundle 工具也内置全历史门禁。GitHub CI 对新推送/PR 跑工具测试、快照、数据库契约和全部可达历史扫描。新 clone 不会自动启用 hooks，须执行上面的 repo-local 配置。

### 本地暂存快检缓存

pre-commit 使用 `--staged --cache-staged`；`--staged` 单独运行仍完全不使用缓存。缓存只在该工作树的 Git 管理目录保存 `comfyui-staged-scan-v1.json`，内容只有身份/规则/内容摘要，没有文件正文、分片首尾或凭证值。只在整次检查成功且 refs/index/规则稳定后写入，原子替换；拒绝链接/硬链接，损坏或失效时完整重扫。

命中仍读取 Git 对象全部字节，核对 SHA、大小、所有路径、当前 manifest 顺序及跨片边界。缓存只省略此前干净、未压缩、未使用审核例外对象的重复内容模式匹配；压缩包与所有审核例外每次重扫。实际检测器/缓存代码、Python 版本、规则、例外登记、路径别名或对象变化会失效。合法临时 `GIT_INDEX_FILE` 使用实际选定的 index，不读取编辑器未暂存内容。

摘要用于发现偶然损坏，不是对本机 Git 管理员的防篡改认证；管理员同样可以改 hooks。缓存不能提交、不能从别人的仓库导入为可信证据，不缓存未知来源的 PASS。**全历史、pre-push、release、bundle、CI 都不读该缓存**，也不提供以缓存替代公开门禁的开关。`scanned_bytes` 仍是实际读取字节，报告另外列出复用的内容扫描量，不把复用称为重新执行所有内容规则。

## 历史凭证处理与后续整理

旧本体实验分支发现 1 处硬编码 API key；维护首版的两份上游插件源码共 3 处旧 GitCode token。公开历史仅精确去除这些确认值，保留提交消息、作者/提交者时间、父链与全部本地 commits，old→new 映射在 `docs/history`。受影响签名不沿用为有效签名；原对象及签名只留在私有备份。

上述数字是早期 Core/Workbench 迁移阶段，不覆盖后续所有插件补迁。旧 `maintenance/private-archives/`、旧私有 bundle、克隆/还原及审计材料后来已按回执迁入本机仓外根 `G:\ComfyUI-local`，当前归属以 [WORKSPACE](WORKSPACE.md) 和对应移动日志为准，不能再按旧路径执行恢复命令。这些材料可能含原值，**一律不可整目录公开复制**。

后续仍只通过受审查 refs / 新 bundle 发布，不直接复制本机 `.git`，以免不可达对象或本地配置泄漏。public-v2 阶段没有回写生产；public-v3 后续明确窄部署了 9 份安全文件及根维护路由，范围见 [整理验收](ACCEPTANCE_WORKSPACE.md)。不要把阶段说明混成现在的部署状态。旧凭证是否有效没有联网测试；若属于自己控制的账户，应在供应方撤销/轮换，历史清洗不等于撤销。

规则扫描不是无遗漏证明；今后上传任何远端之前，仍需人工复核新增文件、SQL/个人资料以及全部 Git 历史。发现真实密钥时不要仅删工作树文件，应先停止发布、轮换密钥，再处理受影响历史。

训练技术归档内的 18 份历史参数中，`trigger_token` 经语义核对是 caption 身份触发词而非鉴权。`governance/training-trigger-reviews.json` 绑定精确完整归档路径和整文件 SHA-256，只移除 `literal_credential_assignment` 这一误报；强密钥格式、其他规则、路径别名和变更后的字节仍拒绝。暂存门禁读取 index 登记，全历史与打包读取 HEAD 登记；没有登记或未经确认不授予例外。这不是按目录、字段名或训练文件类型放行。

## 权限与许可证

上游许可证随源码保留，不给整仓套一个会覆盖第三方权利的统一新许可证。模型、第三方网页资料、图片与本地整合代码的授权分别管理。Git 私仓也不是对内容再分发权的自动授权。

所长法典相关 NovelAI-Tag 来源明确区分软件工具的 MIT 条款与法典正文、原分类、配图及汇编结构。用户允许保留真实提示词解决的是本地资料/隐私取舍，不能自动推导这些上游资料已获公开再分发授权；正式 GitHub 公开前须另核授权或另行确定公开数据范围。本轮不为此擅删真实库，也不上传任何内容。

现行目的地为上述 GitHub 私有仓；用户已持续授权按[日常维护](MAINTENANCE.md)在本地验收与上传门禁通过后推送工作分支并创建 PR。助手不自行合并、开启自动合并或直推日常修改到 `main`；首次空仓基线仍需用户核对范围后单独初始化。此授权不包括公开仓库、生产部署、外部模型调用或泄露仓外配置。本轮仅登记流程，没有上传或合并。

`.bundle` 是离线 Git 交接包，不是要提交到 GitHub 的普通文件。后续从主仓或 bundle 克隆后推送受审查的 `main` 和所需 tags；不要把整个 bundle、私有档案或 `maintenance` 文件夹作为网页上传内容。当前门禁将单个 Git blob 限制为 50 MiB；真实资料的可逆分片不是模型权重的分片上传渠道。

## 机器路径与公开范围

凭证门禁只判定凭证；机器绝对路径（本机运行根、Windows 用户目录）是另一类暴露面，需要单独衡量。本仓同时充当**本机维护记录**，因此本机文档与离线辅助脚本中会保留这些路径：WORKSPACE、MAINTENANCE、PROJECT_MAP 等页描述的就是本机布局，去掉反而降低可读性。它们不是凭证，也不能当作公共默认值——换机器时按运行根重新定位。

`scripts/workspace_audit.py` 只读统计这类暴露，输出文件名与计数、**不输出命中正文**，也不修改任何文件：

```powershell
python -X utf8 -B scripts/workspace_audit.py --out <仓外周报.json>
```

早一轮基线（2026-10-06）为 196 处 / 127 个受跟踪文件，全部是路径形态；分区计数与决议见 [工作区审计收据](receipts/workspace_audit_20261006.json)。这是历史时点；后续增补文档会改变计数，最新摘要见 [再次复核](receipts/reassurance_20261006.json)。路径统计的 `contains_credentials: false` 只描述该类匹配，不代替完整凭证扫描。**不为此改写历史技术归档**：那些原件的字节已登记在 `governance/technical-archive.json`，为一条非凭证细节破坏归档校验并不值得。若将来确实要脱敏，须另立计划、重新登记归档哈希，并同步 `docs/technical/archive` 的引用。

公开边界还包括被用户允许保留的真实提示词/个人资料、上游 Git 作者姓名/邮箱、本机路径及上游源码自带媒体。它们不会因“凭证零命中”自动消失，不能表述为没有任何个人信息或绝对不会泄漏隐私。2026-10-06 对当前 184 份源码媒体另作结构元数据检查，未检测到凭证、GPS、作者/所有者、设备序列号、邮箱或本机用户路径；未逐像素审查图片，也未对全部历史媒体重新解析元数据。模型、用户预览/生成图和大型缓存仍排除；源码界面资源、上游示例图片不能称为用户图片缓存。

本机对象库仍有不可达对象，完整历史门禁只覆盖受审查 refs 可达图。后续分发应生成清洁 bundle/新 clone 并核验，不能整份复制本机 `.git`、私密配置、旧原 Git 或仓外档案。结构元数据检查与凭证规则扫描均有明确范围，不是绝对无隐私信息的证明，也不替代第三方资料的公开许可核对。
