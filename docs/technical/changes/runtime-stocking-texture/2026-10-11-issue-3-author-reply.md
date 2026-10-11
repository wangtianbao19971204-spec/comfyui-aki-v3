# Issue #3 整改回复稿

状态：尚未发布。GitHub API 返回 403（当前令牌不能向作者仓库写评论），浏览器连接超时。以下正文已准备完成，不代表作者已经收到或认可。

---

感谢逐项评审。我们按 T0–T5 完成了独立适配仓的修订，并重新核对了测试与实际部署。适配层由我们维护，不向本仓 `main` 提交合并请求。

独立仓：[stocking-texture-comfyui](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui)。原 fork 已退出使用并删除，之前指向原 fork 的链接请以独立仓为准。

独立仓现已公开，可直接查看与克隆，无需协作者权限。GPU 整合仍在 PR #1 中，尚未合并；T0–T5 已在 main。

截至 2026-10-11 本次核对，上游 `main` 仍为 `e72a262bd917924bc82d45f19992344f2680a303`，与依赖 pin 一致。已逐文件比较原始 Git blob：29 份依赖在独立仓 main、PR、维护源和本机部署中共 116 项 SHA256 全部一致，保留 MIT 和 Silvermoong 署名。未读取或依赖上游 `.scratch/`、`AGENTS.md`、`docs/agents/`。

### T0：独立仓与固定依赖

提交：[24c255869ff71fe8d84efe67fce93dadb53e04ee](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/24c255869ff71fe8d84efe67fce93dadb53e04ee)。采用您允许的“固定版本拷贝 + 同步脚本”，根入口加载 `integrations/comfyui`，桥接指向 `upstream/stocking`；只接受完整提交 SHA，不自动跟随分支。README 写明安装、依赖、pin 和升级测试步骤。

实际执行了从 GitHub 全新克隆（Windows `core.autocrlf=true`），以及独立 ComfyUI 的 `/object_info`、`/prompt`、`/history/{prompt_id}` 和实页验收：3/3 节点注册；1/1 Studio → 两个 SaveImage 工作流成功，产出 RGB/RGBA 128×160；编辑器打开与 CPU/贴线开关可用。浮动引用 `main` 的同步负例在写入前被拒绝，检出保持 clean。

边界：测试使用新的 input/output/user/models/SQLite 目录、仅安装该插件，复用已有 Python 依赖及 ComfyUI 核心，输入为合成样例。这不是全新机器的依赖安装验证，也没有把隔离实例未装的 SAM/深度权重算作本轮测试通过。

### T1：最新上游、完整性与测试

提交：[f7776b0a16ade2028a17d2f5c6c6bf09ba955c73](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/f7776b0a16ade2028a17d2f5c6c6bf09ba955c73)。固定 `e72a262…`，清单基于原始 Git blob；前端替换锚点与原始文件哈希测试通过。

独立仓根目录执行：

```powershell
python -X utf8 -B -m unittest discover -s integrations/comfyui/tests -p "test_*.py" -v
node --test integrations/comfyui/tests/test_editor.cjs integrations/comfyui/tests/test_studio_editor.cjs
```

- main `fc51080924c2adb862008486af1e293fdf6aa141`：Python **67 通过 / 0 失败 / 0 跳过**；前端 **17 / 0 / 0**。
- [PR #1](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/pull/1) `a5eb1d8ca65142103b3ec18d565b9ec9e7797a6a`（含后续 GPU/设备切换/缓存释放）：先设置 `$env:STOCKING_TEST_CUDA='1'`，同命令 Python **78 / 0 / 0**（含真实 CUDA）；前端 **17 / 0 / 0**。PR 尚未合并。
- 固定的原版测试目录执行 `python -X utf8 -B -m pytest -q -ra -p no:cacheprovider`：**313 通过 / 0 失败 / 52 跳过**。52 项均缺作者未公开的 `sample.png` / `sample-guides.psd`，未计入通过；另有 28 条现有 Pillow 弃用警告。

### T2：三条 seams / snap 路径

提交：[9ef82b1c92379d546eaba2558b76f3601ddb75d0](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/9ef82b1c92379d546eaba2558b76f3601ddb75d0)。`segment`、`segment/select`、`dividers` 均已转发并严格校验，默认行为保持上游一致。

命令为上述完整 Python 测试；其中 `test_issue3.py` 当前 **6 通过 / 0 失败 / 0 跳过**，包含 T2 的 5 项及 T5 的 ping 项。可单独运行：

```powershell
python -X utf8 -B -m unittest discover -s integrations/comfyui/tests -p test_issue3.py -v
```

填缝 True/False/缺省与原版逐像素一致，True 相比关闭增加 180 个蒙版像素；正 snap 的几何与像素等于原版且区别于 0；非法类型、非有限数和越界值返回 400。请求测试使用受控分割蒙版以隔离接口行为，不将它描述为这三条 HTTP 测试中重新跑了真实 SAM 模型。

### T3：新增请求字段必须报错

提交：[4d8a746bd3ea44c4030c2ab9fb872f64fa932a43](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/4d8a746bd3ea44c4030c2ab9fb872f64fa932a43)。AST 合同检查上游请求体模型及 19 条路由；本地打开/系统保存对话框/指定服务器导出路径有逐项豁免原因。

```powershell
python -X utf8 -B -m unittest discover -s integrations/comfyui/tests -p test_request_contract.py -v
```

通过 `STOCKING_ADAPTER_SOURCE` 指向 T1 提交的原始 `studio_api.py`，该命令得到预期红灯：**0 通过 / 1 失败 / 0 跳过**，列出 3 个 seams/snap 漏项；移除该变量使用当前适配后：**1 通过 / 0 失败 / 0 跳过**。提交正文保留红绿命令和结果，本次完整复核也重新执行了两次。

### T4：临时文件保留策略

提交：[e7244b9543bfffce41be4a7dbed07f84ef9cd793](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/e7244b9543bfffce41be4a7dbed07f84ef9cd793)。创建会话时清理过期且未被引用的 drafts/exports；默认 7 天，`STOCKING_STUDIO_RETENTION_DAYS` 可配置，0 禁用。保护打开中的草稿/下载及正在重开的旧草稿；assets 不自动删除。README 写明路径、保留策略和核对工作流引用后的手动归档方式。

```powershell
python -X utf8 -B -m unittest discover -s integrations/comfyui/tests -p test_retention.py -v
```

完整测试集中的此子集：**4 通过 / 0 失败 / 0 跳过**，包含过期/新文件、打开/重开、非法配置和 assets 字节保持。

### T5：ping、Windows 换行与 iframe 说明

提交：[33229038de31b9bf5f4a89e1df8f681372529aa8](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/33229038de31b9bf5f4a89e1df8f681372529aa8)。ping 从 `UPSTREAM.json` 派生；`.gitattributes` 固定文本 LF、二进制单列；两份 README 明确同源 iframe 不构成不可信代码的安全沙箱。

```powershell
git clone --no-local --branch feature/gpu-guides-lifecycle -c core.autocrlf=true https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui.git
# 进入检出目录后，运行 T1 的 Python/前端命令，CUDA 环境启用 STOCKING_TEST_CUDA=1。
```

该全新检出 **78 Python / 17 前端通过，0 失败、0 跳过**，包含原始哈希与 ping 合同；新隔离服务实际返回 `comfy-studio-e72a262bd917` 及完整 SHA。

### 本机补漏与尚未完成的边界

完整复核还发现我们部署时漏同步了测试目录：4 份旧测试、5 份缺失。运行区旧哈希测试确实失败（仍查旧 vendor 路径），没有将它当成通过。现已只同步这 9 份受审查测试，本机重新运行同一哈希测试 **1/0/0**，完整 Python **78/0/0**（实际 CUDA）、前端 **17/0/0**；78 份跟踪文件与维护源一致，49 份受保护资料哈希不变，服务未重启。运行实现本身没有发现回退。

上面的专项子集均包含在全套数量内，不重复累加。此前真实图 CPU 与原版的 18 组比较完全一致；GPU 是近似求解，已测样例最大单通道误差 9/255，不能推广为任意图片保证。此次测试目录补齐未重复所有真实模型/画质验收。

目前不能宣称 52 项私有素材测试通过、裸机安装完成、GitHub CI 通过或作者复审认可。欢迎依据这些提交和命令继续复审；后续适配升级与维护由我们负责。
