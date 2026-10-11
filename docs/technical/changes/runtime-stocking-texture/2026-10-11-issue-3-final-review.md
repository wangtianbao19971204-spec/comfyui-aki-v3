# 作者 Issue #3 最终核对

核对日期：2026-10-11。来源为[作者评审](https://github.com/silvermoong/stocking-texture-tool/issues/3#issuecomment-6101011657)。再次读取远端后，作者评论仍更新于 2026-10-10T19:29:37Z，未新增任务；上游 main 仍为 `e72a262bd917924bc82d45f19992344f2680a303`。

T0–T5 的技术修改通过我方核对；原版测试有 52 项因作者未公开素材而跳过，不能算通过。后续完整复核发现本机部署漏了测试目录：4 份旧测试、5 份缺失，运行区原始哈希测试实际失败。这个遗漏现已按九文件范围补齐并重新测试通过，不能用此前维护源/独立仓的绿灯代替当时运行目录的结果。完整复核及补齐证据见[补齐收据](../../../receipts/stocking_test_repair_20261011.json)。这里不代表作者复审认可或 Issue 已关闭。

本机测试补齐前后均为同一服务进程，未重启、未操作数据库；49 份受保护工作流/草稿/素材哈希和九文件以外的插件内容不变。78 份跟踪插件文件现与维护源一致。四份旧测试有原字节备份，五份新增文件登记了原先不存在的状态；回滚仅恢复/归档这九份测试，不能覆盖后续用户数据。首次准备在读取审计中“缺失文件”记录时中止，尚未写运行目录；修正准备脚本后使用新证据目录完成部署，失败准备原件保留。

用户明确选择将独立插件仓公开，已完成可见性切换和未登录读取验证；没有授予作者写权限。公开前对全部可达历史执行完整安全门禁，138 对象/129 blobs、0 发现，三张展示图与已批准清单匹配且无嵌入私有元数据。该检查不等于对所有秘密的绝对证明。作者现在可直接读取 T0–T5 和 PR #1；删除旧 fork 后原 Issue 中的旧链接已失效。

Issue 回帖尚未成功：GitHub API 返回 403 `Resource not accessible by personal access token`，当前令牌没有作者仓的评论写权限，网页控制连续超时。[完整回复稿](2026-10-11-issue-3-author-reply.md)已备好，逐项给出提交 SHA、命令、结果和未完成边界。访问、回帖、作者认可状态分别记录，不把仓库公开当作作者复审通过。

## 逐项证据

下表提交均在[独立插件仓](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui)保留，每项一个提交。GPU 整合和当前工作流说明采用后续提交，不改写六项修订历史。

| 作者要求 | 独立仓提交 | 验证和结果 | 证据 |
|---|---|---|---|
| T0 独立仓、固定依赖、保留 MIT/署名 | [24c2558](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/24c255869ff71fe8d84efe67fce93dadb53e04ee) | 使用作者允许的固定拷贝加同步脚本；29 份依赖原始字节校验通过。全新隔离 ComfyUI 注册 3 个节点 | `SOURCE.json`、`T0-CLEAN-INSTALL.json`、最终独立检出测试 |
| T1 工作开始时最新 main、锚点和上游测试 | [f7776b0](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/f7776b0a16ade2028a17d2f5c6c6bf09ba955c73) | 固定 e72a262；本次再次查询仍一致。最终插件 78 Python、17 前端通过；原版 313 通过、52 跳过、0 失败 | `T1-upstream-tests.log`、`DIST-PYTHON.log`、`DIST-FRONTEND.log` |
| T2 seams / snap 透传、默认值与非法输入 | [9ef82b1](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/9ef82b1c92379d546eaba2558b76f3601ddb75d0) | 5 项 HTTP 测试通过：填缝新增 180 像素；吸附几何/像素等于上游且区别于关闭；非法值 400 | `T2-tests.log`；隔离实页吸附开关请求记录 |
| T3 上游新增字段必须报错、回退红/恢复绿 | [4d8a746](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/4d8a746bd3ea44c4030c2ab9fb872f64fa932a43) | AST 合同覆盖 19 路由；T1 旧适配 1 失败，明确列出 3 个 seams/snap 漏项；恢复后 1 通过；提交正文含命令和红绿结果 | `T3-RED-GREEN.json` 及提交正文 |
| T4 过期导出/草稿清理，保留打开会话与素材 | [e7244b9](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/e7244b9543bfffce41be4a7dbed07f84ef9cd793) | 4 项通过；默认 7 天，可配置，0 禁用；打开/重开老草稿保留，assets 不自动删除，README 有路径与清理说明 | `T4-tests.log`、`test_retention.py` |
| T5 pin 派生 ping、Windows LF、iframe 说明 | [3322903](https://github.com/wangtianbao19971204-spec/stocking-texture-comfyui/commit/33229038de31b9bf5f4a89e1df8f681372529aa8) | `core.autocrlf=true` 全新检出 78 Python、17 前端通过，0 跳过，包含原始 blob SHA/ping；README 明确同源 iframe 不构成安全沙箱 | `DISTRIBUTION-VALIDATED.json`、`DIST-PYTHON.log`、`DIST-FRONTEND.log` |

## 命令和数量

在独立插件根目录执行的最终组合版本验证：

```powershell
$env:STOCKING_TEST_CUDA='1'
python -X utf8 -B -m unittest discover -s integrations/comfyui/tests -p "test_*.py"
node --test integrations/comfyui/tests/test_editor.cjs integrations/comfyui/tests/test_studio_editor.cjs
```

本次完整复核从 GitHub 新克隆 main `fc51080924c2adb862008486af1e293fdf6aa141` 与 PR `a5eb1d8ca65142103b3ec18d565b9ec9e7797a6a`，均使用 Windows `core.autocrlf=true`。main 为 67 Python、17 前端通过；PR 为 78 Python（实际 CUDA）、17 前端通过，均 0 失败/0 跳过，含原始上游哈希。测试目录补齐后在运行插件目录执行 `python -X utf8 -B -m unittest discover -s tests -p "test_*.py" -v` 和相应 `node --test tests/test_editor.cjs tests/test_studio_editor.cjs`，再次取得 78/17，0 失败/0 跳过；原先失败的单独哈希测试现 1 通过。

本次完整复核在原版固定目录重新执行 `python -X utf8 -B -m pytest -q -ra -p no:cacheprovider`，313 通过、52 跳过、0 失败；52 项均缺少未公开 sample PNG/PSD，另有 28 条现有 Pillow 弃用警告。未读取或依赖上游 `.scratch/`、`AGENTS.md`、`docs/agents/`。新隔离数据目录仅安装独立插件：3 个节点注册、一次 Studio → 两个 SaveImage 成功（128×160 RGB/RGBA），实页编辑器/CPU/贴线开关通过；复用既有 Python/核心及合成输入，不是裸机依赖安装。

专项命令为 `python -m unittest discover -s integrations/comfyui/tests -p test_issue3.py -v`（当前 6 项：T2 的 5 项加 T5 ping）、同命令替换 `test_retention.py`（4 项）；这些子集在本次完整集均通过。`test_request_contract.py` 本次再次通过环境变量 `STOCKING_ADAPTER_SOURCE` 指向 T1 原始适配得到预期 1 失败，移除变量后 1 通过。上述子集已包含在最终 78 项，不相加计算总数。

维护源额外完成 5 项导出合同、当前工作流合同和 51 项显式 CPU HTTP 对照。详情见[初次 Issue 收据](../../../receipts/stocking_texture_issue3_20261011.json)、[GPU 整合收据](../../../receipts/stocking_independent_gpu_20261011.json)及[本次交付收据](../../../receipts/stocking_independent_delivery_20261011.json)。

## GPU 和实际界面的证据边界

三张真实图、每张六样式的 18 组 CPU 像素和求解字段与独立原版完全相同。GPU 各区域实际使用 CUDA，私有池使用量和保留量均回到 0；本批最大单通道误差 9/255，近黑油光 411 个通道超过 2/255。最大差异局部目视未见明显结构变化，不能推广为任意图片的误差保证；需要精确上游对照时选择 CPU。

导出插件在隔离 ComfyUI 实页完成 CPU/GPU 切换、真实 SAM 和深度 CUDA 推理、关闭/重开后重新点选加载 SAM、导航离开后模型与图像特征清空。导航前后采样相隔约 20 秒，小于 60 秒租约，已计算深度仍 ready。标签页隐藏未单独实测；没有把截断的 CDP 网络缓存作为 beacon 证明，也没有新做模型弱引用/RSS 回归。干净安装复用现有 Python 依赖和模型，不能称为裸机安装验证。

运行实例、当前工作流输出、旧 fork 删除与 PR 状态由本次交付收据单独记录。原始图片、截图、私有 Git 备份、数据库备份和完整请求保存在仓外；仓内只保存可审核摘要和 SHA256。
