# Git 历史公开迁移说明

本次迁移保留全部本地提交的可追溯关系，但不会把已确认的历史凭证带进公开对象库。

| 来源 | 原提交数 | 公开提交数 | 保持原 SHA | 因清除凭证而重写 |
|---|---:|---:|---:|---:|
| ComfyUI 本体 | 10,844 | 10,844 | 10,458 | 386 |
| Unified Prompt Workbench | 2 | 2 | 2 | 0 |
| 首版维护基线 | 1 | 1 | 0 | 1 |

本体原有 refs 可达 10,551 个提交，另外 293 个提交只被本地 reflog 保留。额外历史没有丢弃，已由 67 个恢复 tips 完整覆盖；没有完全脱离 refs 和 reflog 的本地 commit。全体本体提交共有 754 个无后继 tips，可作为聚合归档提交的父节点集合，不需要将 757 个旧远端 refs 变为日常工作分支。

本体 197 个 tags 均保留映射，其中 196 个 lightweight、1 个 annotated。唯一 annotated tag `v0.0.2` 原对象 `bb775157355f7bfd93f3a89deeb5904153365ba1` 不受清洗影响，原签名/注释对象字节保持不变。建议在最终仓库命名为 `legacy/core/tags/*`。

## 清洗边界

- 本体历史：`comfy_extras/nodes_api.py` 曾写入硬编码 API key。只在已确认 blob 中将该值替换为 `REDACTED_API_KEY`，没有删除整个文件或实验分支。
- 首版维护基线：两个旧插件源码 blob 共 3 处嵌入同一 GitCode access token。只清空 token 值，其余内容逐字节保留。
- 原始密钥不进入映射、报告、命令行或终端输出；没有联网验证其有效性。
- 作者、提交者、时间、消息及父节点顺序全部验证保持。重写后的 113 个原签名提交已移除失效的签名头；其原始有效性不能继续声称保留。原始完整签名及对象仍在单独私有归档内。
- 首版维护提交 `c1d1d8707a1d334bd6ffa3a991f973032769ecf8` 的公开映射为 `e724311869c31940ea11b930f4d01f25d16ea6f5`。旧 `maintenance-v1-20261005` tag 也必须指向此公开映射，不能继续引用原密钥祖先。
- 历史快照内的原采集 manifest/验收收据不伪造改写为“当时已脱敏”。它们记录原采集事实，不再是脱敏历史树的字节还原校验；当前维护 HEAD 应重新生成准确清单。

## 验证与证据

三个隔离公开镜像均通过 `git fsck --full --strict`。独立结构验证逐提交比较了消息、非签名元数据、映射后的父节点顺序和所有变化树，确认仅允许的 3 个旧 blob 发生清洗，原凭证 blob 在公开镜像的整个对象数据库中不存在。

可公开的机器映射文件：`core-public-map.json`、`workbench-public-map.json`、`main-public-map.json`。每个文件含全部 old→new commit 映射、原 ref→公开对象映射、恢复 tips、清洗范围及签名变更说明。对应 `*-public-verify.json` 为实际结构核验回执。

原始三个 `.git` 已完整逐文件复制并核对 SHA-256，保留全部 refs、objects 和 reflogs。它们位于维护仓之外的 `maintenance/private-archives/legacy-history-20261005/`，只作为私有恢复材料，绝不可上传或直接制作公开 bundle。

独立凭证扫描是另一个发布门禁；结构核验不能替代内容扫描。公开前还需重新扫描最终合并后的全部可达历史。

## 安全导入方式

以隔离镜像作为**本地来源**，不要再从两个原运行仓或私有归档直接向最终公开仓 fetch。

本体可用如下 refspec 导入最终安全暂存仓，随后通过聚合归档提交保留可达性：

```text
+refs/heads/*:refs/import/core/heads/*
+refs/remotes/*:refs/import/core/remotes/*
+refs/archive-recovered/*:refs/import/core/recovered/*
+refs/tags/*:refs/tags/legacy/core/tags/*
```

使用 `git fetch --no-tags <public-core.git> <这些refspec>`，可以保留所有对象而不新增 757 个活动 branch。聚合提交分组每个最多 64 个 parents，并以映射中的全部 `all_graph_tips` 为覆盖集合；最终主提交保留当前维护 tree，以脱敏维护基线作为第一 parent，再连接聚合归档。所有临时 `refs/import/*` 删除前，先证明全部 10,844+2 个公开 legacy commits 均为最终主分支祖先；197 个 prefixed tags 另行核对。

应从这些安全镜像构建新的主 Git 数据库，再恢复当前未提交工作树的维护改动。仅重指向旧 `.git` 的 main 会在旧 tag/reflog/不可达对象内留下历史凭证；原始 `.git` 已有私有备份，无需将这些旧对象继续混进公开交付材料。

当前隔离镜像 HEAD：

```text
public-core.git       cc0fc21fea7a6a82f568362b15b7fbd713b419c1
public-workbench.git  cc3bc63d55843f94b79f4e16042e03eccbfcc56e
public-main.git       e724311869c31940ea11b930f4d01f25d16ea6f5
```

历史最大 blob：本体 9,497,554 bytes，Workbench 32,035,901 bytes；两个旧仓所有本地对象中均无超过 50 MiB 或 100 MiB 的 blob。
