# 网页提示词 → 统一工作台

## 唯一来源与使用方式

新版 [aki_tags_bridge.user.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/aki_tags_bridge.user.js) 来自用户从实际油猴脚本提供的 v2.8 原件，保留原名称和 `aki-tags-bridge` namespace；脚本版本单独升为 2.9，不递增维护包版本。原件保存在仓外私有档案，摘要登记在[本次收据](../../receipts/browser_bridge_20261006.json)。仓内旧 Danbooru v0.5 脚本保留兼容历史，不是五站脚本的更新来源。

支持五类站点：Danbooru、Civitai（含 civitai.red）、PixAI、yande.re、Gelbooru。选择当前作品后，点击小按钮发送；按 Shift 点击可核对或修改正负提示词。提取不足时用选中文字或手工填写，错误说明不会被当作提示词发送。自然语言和提示词权重保留原文；Booru 分类按 artist、copyright、character、general 合并，meta 默认排除。

工作台收到后进入**待采用列表**，正负向各为独立分段，保留来源和不可变原文。随后在原有待用区核对完整字段、选择正向或负向目标，追加或确认替换，并可撤销。接收不自动写入工作流、不提交生成；网页携带的模型、LoRA、种子、采样参数也不会自动修改本地流程。

## 安装、更新和回退

1. 先按主仓[维护流程](../../MAINTENANCE.md)验证并精确部署下列后端和前端源码；保留运行文件原哈希、队列/服务身份和回滚副本。仓库保存/提交本身不表示线上生效。后端需按受保护流程重新加载才注册新接口；不直接启动 `snapshot/runtime`。
2. 打开油猴里现有的 **Aki D/C/PixAI/Yande/Gelbooru Tags Bridge**，用新版文件完整替换代码并保存，保持名称与 namespace。只启用一份五站桥接脚本；先前 Danbooru 单站脚本若还启用，也应停用以免重复按钮/发送。
3. 默认发送地址为本机 `127.0.0.1:8188`。使用其他本机端口时通过脚本提供的设置入口调整；仅允许 loopback 主机和有效端口，不支持局域网/远程 ComfyUI。
4. 重新载入源网站页面，使收窄的详情捕获开始工作；切换图片后每次点击重新核对当前作品。C/P 私密作品、未公开生成信息或网站结构变化时，请使用预览编辑，不依赖上一张缓存。
5. 打开 ComfyUI 页面，发送一条小样例。网页“服务已保存”只表示进入本机收件暂存；以工作台待采用区实际出现正负分段为接收验收，再明确采用到目标。不要只看发送提示就判断已应用。

回退分别处理浏览器脚本与本次部署文件：油猴替换回仓外保存的 v2.8 原件；源码回到本次修改前的主仓提交并按相同部署范围恢复。新收件库、现有资料库、工作流和后续编辑不由代码回退自动覆盖。尚未执行的安装、部署和回退都不能写成已完成。

## 实现、数据与隐私边界

| 部分 | 唯一实现 |
|---|---|
| 五站提取、小按钮与匿名本机投递 | [aki_tags_bridge.user.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/aki_tags_bridge.user.js) |
| 校验、本机保护、持久收件、领取与确认、旧节点兼容 | [danbooru_browser_import.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/danbooru_browser_import.py) |
| 页面事件、断线恢复和接收确认 | [browser_import.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/browser_import.js)、[workbench_shell.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench_shell.js) |
| 正负草稿、原文、编辑与既有写入/撤销 | [pending_prompts.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/pending_prompts.js)、[prompt_target.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/prompt_target.js) |
| 外部 SQLite 格式和升级契约 | [database/browser-import/README.md](../../../database/browser-import/README.md) |

新 POST `/unified-workbench/browser-import` 只接受六个字段：`positive`、`negative`、`source_url`、`title`、`post_id`、`image_url`；不接纳原网络 JSON、debug、资源配置、Cookie 或认证字段。请求限 256 KiB，正文上限正向 65,536 / 负向 16,384 个 Unicode 字符。来源仅允许五站公开作品地址；拒绝认证地址并去掉额外 query/hash，Gelbooru 只保留定位作品必须的 `page=post&s=view&id`。图片链接是可选引用，脚本不下载图片、不建立图片缓存。

新 API 同时检查真实 loopback 连接、字面本机 Host 和存在时的精确同源 Origin；匿名 GM 请求可不带 Origin。返回 `no-store`，不授予跨源读取权限。旧 GET 读取新工作台内容时也执行相同保护，避免从兼容入口读取新稿。既有旧数据协议保留，不把原端点的历史 CORS 行为声称为全面安全改造。

未确认接收的服务暂存最多 32 条，满时明确拒绝新发送，不覆盖较早稿。浏览器存好待用草稿并确认接收后，该条退出服务收件队列；确认接收不等于用户采用，32 条限制不针对浏览器里尚未采用的草稿。暂存库位于 `COMFYUI_EXTERNAL_ROOT/mutable-data/browser-import/inbox.sqlite3`；默认部署路径使用运行根同级的仓外资料根。源码检查树无法安全推断仓外路径时要求显式配置。库正文及运行实例不进入 Git；收件不是正式提示词库，也不是资料备份。

GET 列出未确认收件；`/claim` 以接收 UUID、页面接收者 UUID 和短租约原子领取；`/ack` 在浏览器待用草稿确实存好后确认；`/release` 用于本地草稿保存失败。页面事件、初始化和重连共用串行处理，服务级领取协调 `localhost` / `127.0.0.1` 或不同标签页。确认后的最近 128 个接收 ID 用于幂等，记录不含无限历史正文。

浏览器会话存储和服务确认不是共同事务。确认失败会保留本页草稿并作有限重试；未确认租约过期可以由其他页面接收，不能宣称跨浏览器永久“绝对一次”。关闭页面、清空会话存储、清理仓外收件库均可能损失临时稿；重要内容应明确保存到正式提示词库。不会静默用最新一条替代整个未读队列。

## 样例与验收

[虚构五站请求样例](../../../examples/browser-import/payloads.example.json)标注 canonical 来源地址、正负方向、可选图片引用及未携带数据。所有样例均为虚构，不含用户作品或原图。

- 用户脚本隔离适配样例：[test_userscript.cjs](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/tests/test_userscript.cjs)。
- 后端隔离 API/安全/暂存样例：[test_workbench_bridge.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/tests/test_workbench_bridge.py)。
- 草稿/写入方向/撤销：[test_browser_pending.cjs](../../../snapshot/runtime/production_tools/test_browser_pending.cjs)。
- 接收者/确认/恢复：[test_browser_receiver.cjs](../../../snapshot/runtime/production_tools/test_browser_receiver.cjs)。
- 本机实际 HTTP + 实际前端模块的隔离实页：[test_browser_bridge_server.py](../../../snapshot/runtime/production_tools/test_browser_bridge_server.py)、[browser_bridge_fixture.html](../../../snapshot/runtime/production_tools/browser_bridge_fixture.html)。需指定全新仓外 `--external-root` 和非生产 `--port`；不导入或控制生产 ComfyUI。

在主仓根目录复核时，沿用[开始使用](../../GETTING_STARTED.md)中的 `$comfyPython`，另将已安装的 Node.js 完整路径保存为 `$comfyNode`。后端测试和实页需该 Python 环境已有 `aiohttp`；不需要加载模型或启动生产服务。

```powershell
& $comfyNode snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/tests/test_userscript.cjs
& $comfyPython -X utf8 -B snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/tests/test_workbench_bridge.py
& $comfyNode snapshot/runtime/production_tools/test_browser_pending.cjs
& $comfyNode snapshot/runtime/production_tools/test_browser_receiver.cjs

# 全新临时目录；先确认示例端口没有被使用，切勿选择生产端口。
$bridgeFixtureRoot = Join-Path $env:TEMP ('comfy-browser-bridge-' + [guid]::NewGuid().ToString('N'))
& $comfyPython -X utf8 -B snapshot/runtime/production_tools/test_browser_bridge_server.py --external-root $bridgeFixtureRoot --port 18766
```

实页服务启动后，打开它输出的 `/fixture` 地址：发送样例，核对正负待用稿、明确采用后的目标值、撤销及刷新后编辑保留。完成后用 Ctrl+C 停止该隔离服务；其中的临时稿不是生产资料。

以上验证不等于网站当前 DOM/登录态全覆盖，也不证明新版已安装到用户 Chrome。当前浏览器控制扩展的官方商店条目拒绝下载；脚本原件由用户从浏览器提供。最终通过项、实际文件摘要、未验收项与运行保护核验，以本次收据为准。

## 更新记录

- 2026-10-06：以用户提供的 v2.8 五站原件为依据制作轻量 2.9；收窄网络数据保留，修复旧 lastPayload/跨作品缓存回退，接入工作台正负待采用、仓外有界暂存及领取确认。验证与部署/安装边界见[收据](../../receipts/browser_bridge_20261006.json)。
