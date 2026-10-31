# 上游油光路径、仅纹理导出与界面大小同步

2026-10-31 将作者默认 main 的固定提交从 `204a1b8e36dabb0ca11aa3720113be17877fa245` 更新为 `c38be2fe1d3f0b9d768edc78f1ee35ebf6118186`，前进 5 个提交。31 份依赖原件、许可与 SHA256 由现有 `sync_upstream.py` 从 Git blob 更新（原 29 份，新增 `_glint_position.py`、`_oily_absorption.py`）；不启动上游桌面服务器，依赖与 SAM／深度算法未变。

## 本轮上游内容

- 油光高光路径稳定化：新增 `_glint_position`（把同一肢体上的两段互补观测沿真实走向接起来，边缘不再出现假影）与 `_oily_absorption`（按吸收模型修正遮挡边缘）。`oily.render_oily` 末尾增加可选参数，`Scene.oily_context` 取代原 `oily_maps` 的内部构造；被拒的候选会退回"路径不变"，不影响成图。
- 导出新增「仅纹理」：`export.KINDS` 增加 `texture`，`texture_layer` 以中性灰 128 输出 Linear Light 层（叠在原图上还原成品图，叠在重涂的丝袜上则铺同一层纹理，量化误差不超过 1 级）。导出的中间文件改用 `tempfile.mkstemp`，不再固定「导出中」文件名。
- 界面大小 100／115／125／150／175%：上游新增 `/api/ui-scale` 与 `settings.ui_scale`，首页把选择写成 CSS 变量 `--k`，`style.css` 以它缩放全部尺寸，供 2K／4K 屏文字偏小时使用。
- 引导导出与撤销：`Document.guides_token()`／`mark_guides_saved(token)` 让"已保存"对应真正写入文件的那一步；撤销上限丢弃或重做被新编辑覆盖后不再谎报已保存。区域名改为唯一（重名直接报错），撤销／重做再也到不了的区域与其求解缓存被回收，`guide_stroke_alpha()` 让无归属的走向也写进 PSD。
- 会话与本地接口校验：`solve_v` 在"隔开线遮掉全部走向采样"时返回 `None`（原先抛 `ZeroDivisionError`）；`label_regions` 区域图由 int8 改为 int16；会话格式升到 2（`masks-<uuid>.npz`，仍可读格式 1）；上游 server 增加 Host／Origin 防护（本地适配不启动该服务器，本轮不涉及）。

## 本地适配与修复

- `engine.solve_geometry`：上游把"隔开线遮住全部走向"从异常改为 `None`，与"本就没有可用走向"共用一个返回值。本地改为在求解失败且同时存在隔开线与走向时，去掉隔开线重解一次，据此区分两种情况，保留原有的「隔开线遮住走向约束」提示。只有落到该失败分支才会多做一次求解。
- 完整编辑器接入界面大小：取值由 `studio_store.UI_SCALES` 约束；`studio_assets.page` 把选择写进 `<html style="--k: …">`，非法存量值回落 100%；`studio_api` 新增 `POST /api/ui-scale`，其它方法返回 405，非法值返回 400 且不修改已存偏好。选择按 ComfyUI 用户存进既有 `preferences.json`，与界面语言同一处。
- 引导导出改用 `export.export` 返回的 `saved` 令牌调用 `mark_guides_saved`，写入期间发生的编辑仍算未保存。
- 「仅纹理」随 `export.KINDS` 自动进入本地导出白名单与浏览器下载路径，未新增服务器文件写入范围。
- `tests/test_request_contract.py` 登记新路由。新增 4 项测试：页面 `--k` 与回落、界面大小 HTTP 往返与非法值、仅纹理层符合 Linear Light 公式、无走向的部位不误报隔开线。

## 本轮验收

| 范围 | 实际结果 | 边界 |
|---|---|---|
| 插件 Python | 124 项通过，2 项显式 CUDA 验收跳过 | 跳过不计通过；新增 4 项，原有 120 项无回归 |
| 前端 | 17 项通过（11＋6） | 引导编辑器与完整编辑器编辑器模型 |
| 导出合同 | 6 项通过 | 导出白名单随 `UPSTREAM.json` 自动收录两份新原件 |
| 与固定上游逐像素对照 | 38 组夹具、912 个渲染用例全部通过，其中 456 项为开启暗部适配前与上游 Document／Scene 的有效区域逐像素相等 | 合成几何与配色控制样本；几何指纹 v／across／alpha 误差均为 0 |
| 隔离真实实例 | 8288 端口、CPU、独立 user／input／output／temp／数据库，仅白名单本插件；节点在 ComfyUI 执行器中真实出图（改动 12778 像素、RGBA 图层不透明），实页 `--k` 与 `/api/ui-scale` 100→150 生效并写入 `preferences.json`，5 类非法值均 400，「仅纹理」导出与 Linear Light 公式逐像素一致、还原误差 ≤1 | 合成样本，不是画面质量评审；未触碰 8188 生产实例 |
| 作者自带测试 | 568 通过、52 跳过、11 失败 | 失败全部落在作者新增的 `tests/test_glint_position.py`，详见下节 |

## 已知边界：作者自带测试的 11 项失败

11 项失败都是作者为新增高光路径模块写的自测，断言的是"两段轨迹应当被接起来"（期望 `fixed_sample_supported_candidate`），实测走到保守分支 `no_supported_transition_extent`；该分支在 `_glint_position.refine_curve` 内部被捕获并返回原路径，**不抛错、不影响出图**。本机 numpy 2.3.2／scipy 1.17.0，作者 `requirements.txt` 固定 numpy 2.5.3／scipy 1.18.1，判断为版本相关的几何阈值差异。本轮不为此升级整机科学计算依赖：ComfyUI 侧的版本由其自身约束决定，且依赖原件与作者提交逐字节一致，渲染结果仍与固定上游逐像素相同。

## 数据与回滚

源码入口为 `snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/`，本轮只改维护源码，未写运行区、未重启、未排队。两份新原件位于被 `.gitignore` 忽略的 `custom_nodes/` 下，已用显式 `git add -f` 纳入，避免新克隆缺文件导致 `oily` 导入失败。原始证据、隔离实例与渲染中间文件留在仓外，仓内只登记摘要与哈希，见[本轮收据](../../../receipts/stocking_upstream_sync_20261031.json)。
