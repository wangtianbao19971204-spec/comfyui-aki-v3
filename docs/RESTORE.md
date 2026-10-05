# 恢复与迁移

## Git bundle 恢复

仅使用新验收回执列出的 `comfyui-public-ready-20261005.bundle`（后续版本用各自回执命名），校验 SHA 后执行。旧 `comfyui.bundle` 含历史凭证，只能私有归档，不能公开复用。

```powershell
git clone -c core.longpaths=true .\comfyui-public-ready-20261005.bundle .\comfyui
git -C .\comfyui fsck --full
cd .\comfyui
python -X utf8 -B scripts\snapshot.py verify
python -X utf8 -B scripts\security_guard.py --all-history
git config --local core.hooksPath .githooks
```

克隆产生的 origin 只是本地 bundle 路径，不是在线远端。首次仓库使用专用维护作者标识，不修改用户全局 Git 身份；后续提交可以配置你自己的 repo-local user.name/user.email。

Windows 必须在初次检出前使用上面的 `-c core.longpaths=true`：整合插件目录较深，较长的父目录可能触发 `Filename too long`。该选项只设置新克隆仓库，不修改全局 Git 或系统注册表。已有仓库可用 `git config --local core.longpaths true`；失败的半成品克隆不要当作验收通过，也不要直接向生产恢复缺失文件。

## 只向全新目录物化

```powershell
python -X utf8 -B scripts\snapshot.py materialize --dest G:\comfyui-restored-20261005
```

目标目录必须不存在。工具拒绝直接写回 manifest 原运行根、原 ComfyUI 树和 snapshot 内部。它不会启动服务、执行模型或覆盖现有文件。

- 普通源码/工作流：逐文件 SHA-256 一致。
- 上游 `.gitattributes` 在 Git 内以 `.gitattributes.upstream` 保存原字节，物化时恢复原名称，避免嵌套换行规则改写快照。原 `.gitignore` 保留。
- 大型 JSON：按清单合并 .part，恢复原始编码/换行/字节并核对整文件 SHA。
- SQLite：从已校验 SQL 分片新建数据库，核对 integrity_check、全部表行数和完整逻辑 SQL 哈希。数据库二进制页布局可不同，不宣称 .db 字节相同。
- 生成 `RESTORE_RECEIPT.json`。临时合并的 `.restore.sql` 保留在物化目录供检查；它不是线上数据库。

## 物化后还需要什么

1. 按 environment.json 准备 Python、ComfyUI 前端分发包、Torch/CUDA 和插件依赖。该文件是已装版本清单，不是经过新机器冷装验收的锁文件，不要无审核整批安装或降级。
2. 从原备份另行恢复完整模型目录及插件内权重，包含 config/tokenizer/processor 等伴随文件。
3. 另行恢复 preview 与 preview_thumbnails，保持同名和相对路径，核对 library_media 清单。清单不是图片副本。
4. 在新环境安全补齐 excluded_private_configs 中的机器/认证配置。不得把现用真实 key 写进 Git。
5. 若需要当前 production 配置之外的旧插件、视频节点、训练 Forge、源网页原件或历史回滚媒资，从原环境单独迁移。本仓库记录上游但不保证这些全部打包。
6. 静态检查工作流节点/模型引用和 profile；修复缺失必须保留工作流原意，不自动启用旁路分支或换底模。
7. 用独立端口、隔离数据做启动/浏览器/中性样例验收；明确通过范围后再决定正式切换，不能直接覆盖正在运行的 8188。

## 不是完整灾备镜像

本 bundle 可还原管理范围内的代码、保存工作流、提示词 JSON 和三库逻辑数据。模型、预览、认证、Python/CUDA 运行环境与旧历史媒资需要独立备份。建议把这些外部资源与 bundle 一起离线存放，并分别记录校验值；不要把“Git 可克隆”误认为“全部数据已异地备份”。
