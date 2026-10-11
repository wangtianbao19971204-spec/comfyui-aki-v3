# 作者 Issue #3 最终核对

核对日期：2026-10-11。来源为[作者评审](https://github.com/silvermoong/stocking-texture-tool/issues/3#issuecomment-6101011657)。再次读取远端后，作者评论仍更新于 2026-10-10T19:29:37Z，未新增任务；上游 main 仍为 `e72a262bd917924bc82d45f19992344f2680a303`。

T0–T5 的技术修改和要求的验证均已完成；原版测试有 52 项因作者未公开素材而跳过，不能算通过。这里是我方技术核对，不代表作者复审认可或 Issue 已关闭。没有代发评论。独立仓仍为私有，作者能否查看取决于仓库访问权限；删除旧 fork 后，原 Issue 中旧 fork 的链接已失效。

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

分别为 78 通过/0 失败/0 跳过（包含实际 CUDA），17 通过/0 失败/0 跳过。Windows 克隆使用 `git clone --no-local --branch feature/gpu-guides-lifecycle -c core.autocrlf=true`，原始上游 SHA 在该检出中再次通过。验收基于 `c4d1769cdc4677aa3add48c987ba045b848d0210`；追加的 `a5eb1d8ca65142103b3ec18d565b9ec9e7797a6a` 只改变示例工作流 Note。86 文件清单逐项比较确认全部运行代码和测试文件未变，复用这些测试结果，不伪称重新运行。

原版固定目录执行 `python -m pytest -q -ra -p no:cacheprovider`，313 通过、52 跳过、0 失败；52 项均缺少未公开 sample PNG/PSD。该日志属于 T1 同一 pin 的既有运行，本次核验 pin 后复用。未读取或依赖上游 `.scratch/`、`AGENTS.md`、`docs/agents/`。

专项命令为 `python -m unittest discover -s integrations/comfyui/tests -p test_issue3.py -v`（5 通过）、同命令替换 `test_retention.py`（4 通过）；`test_request_contract.py` 通过环境变量 `STOCKING_ADAPTER_SOURCE` 指向 T1 原始适配得到红灯，移除变量后为绿灯。上述子集已包含在最终 78 项，不相加计算总数。

维护源额外完成 5 项导出合同、当前工作流合同和 51 项显式 CPU HTTP 对照。详情见[初次 Issue 收据](../../../receipts/stocking_texture_issue3_20261011.json)、[GPU 整合收据](../../../receipts/stocking_independent_gpu_20261011.json)及[本次交付收据](../../../receipts/stocking_independent_delivery_20261011.json)。

## GPU 和实际界面的证据边界

三张真实图、每张六样式的 18 组 CPU 像素和求解字段与独立原版完全相同。GPU 各区域实际使用 CUDA，私有池使用量和保留量均回到 0；本批最大单通道误差 9/255，近黑油光 411 个通道超过 2/255。最大差异局部目视未见明显结构变化，不能推广为任意图片的误差保证；需要精确上游对照时选择 CPU。

导出插件在隔离 ComfyUI 实页完成 CPU/GPU 切换、真实 SAM 和深度 CUDA 推理、关闭/重开后重新点选加载 SAM、导航离开后模型与图像特征清空。导航前后采样相隔约 20 秒，小于 60 秒租约，已计算深度仍 ready。标签页隐藏未单独实测；没有把截断的 CDP 网络缓存作为 beacon 证明，也没有新做模型弱引用/RSS 回归。干净安装复用现有 Python 依赖和模型，不能称为裸机安装验证。

运行实例、当前工作流输出、旧 fork 删除与 PR 状态由本次交付收据单独记录。原始图片、截图、私有 Git 备份、数据库备份和完整请求保存在仓外；仓内只保存可审核摘要和 SHA256。
