# V53 多站排行与分类浏览交付说明

交付日期：2026-07-19  
插件：`ComfyUI-Danbooru-Gallery-V50-GalleryOnly`  
验证环境：ComfyUI `0.27.1`、前端 `1.45.20`、Python `3.13.11`

## 1. 交付结论

V53 已完成并通过交付门禁。原有 GalleryOnly 节点、搜索、卡片、提示词/网址输出、设置和本地收藏仍保留；新增能力驱动的浏览导航、四站排行、分类、统一游标分页、稳定错误合同和可回滚功能开关。

当前默认开启稳定 V2 路由、新 UI 和四个 Provider。实验性/近似能力与未实现的 legacy shadow 路径默认关闭，并在配置错误时 fail closed。

## 2. 终极备份与恢复

修改前完整备份位于：

`G:\ComfyUI-aki-v3\_codex_backups\ComfyUI-Danbooru-Gallery-V50-GalleryOnly_PRE_V53_20260719_122851`

其中包括：

- `original/`：原目录逐文件副本，271 个文件、19,932,044 字节。
- `original.zip`：便携压缩包，SHA-256 `02B7D40F2015DE6E965E1700C58CE1CC214723774DED40FFA61F0ED4C2735AC2`。
- `manifest.sha256.csv`：原文件逐项长度和 SHA-256；复制件与源目录核验一致。
- `RESTORE.md`：恢复步骤。

备份包含修改前的本地配置，可能含用户凭据，只应私下保存。完整恢复时先停止 ComfyUI，再严格按 `RESTORE.md` 用 `original/` 替换当前插件目录；不要把备份上传到公共仓库。

## 3. 用户可见变化

- 一级导航：`浏览 / 搜索 / 收藏`。
- 浏览子页：`最新 / 排行 / 分类`。
- 排行指标、周期、分类类型、收藏可用性按当前站点能力动态显示，站点不支持的选项直接禁用或隐藏。
- 每个节点保存自己的 source、mode、查询草稿、游标页和滚动位置；多节点互不覆盖。
- 切站、切模式或修改条件会中止旧请求，只有 request ID 与 query key 同时匹配的最新响应能提交。
- 旧 feature endpoint 缺失或新 UI 被关闭时，保留可用的旧来源/搜索路径。

## 4. 四站能力矩阵

| 站点 | 最新 | 排行 | 可过滤分类 | 收藏 |
|---|---|---|---|---|
| Danbooru | 官方 posts | Popular 日/周/月；收藏数、评分总榜 | general、artist、copyright、character、meta | 本地收藏可用 |
| Gelbooru | 官方 DAPI | 评分总榜 | 累计热门 tag | 不支持；周期近似榜默认关闭 |
| Yande.re | post JSON | 日期范围 + 评分排序：日/周/月/年 | tag、related tag | 不支持；能力标为 provisional |
| Civitai | 官方 `/api/v1/images` Newest | Reactions、Comments：日/周/月/年/总时段 | model、model version、creator、base model | 本地收藏可用 |

Civitai 的 `model_taxonomy` 可列出名称，但公开图片 API 的 `tags` 过滤需要数值 ID，因此它不会被伪装成可过滤分类；已知数值 image tag ID 可以过滤但无法从当前公开列表自动发现。`Collected` 和公开自由文本搜索仍关闭。

## 5. 后端/API

新增只读路由：

- `GET /danbooru_gallery/features`
- `GET /danbooru_gallery/v2/providers`
- `GET /danbooru_gallery/v2/browse`
- `GET /danbooru_gallery/v2/facets`
- `GET /danbooru_gallery/v2/autocomplete`

V2 响应统一携带 schema version、request ID、client request ID、query key、items、pageInfo、applied、warnings、provenance 和稳定 error envelope。未知站点、能力不支持、认证失败、限流、上游失败、游标过期、服务繁忙等情况不会再混成普通空数组。

Provider 运行时使用 4 线程专用池、非阻塞并发预算、single-flight，以及 browse/facets/autocomplete 的 2 秒成功 LRU（最多 64 项）。失败不缓存；配置认证后关闭成功 TTL 缓存，避免账号切换读到旧数据。

## 6. 安全修复

- 日志和异常统一脱敏 Authorization、Cookie、API key、token 和带认证 URL。
- 图片提示词远程读取使用按用途固定 host allowlist，只允许 HTTPS、公网 DNS/IP 和受控重定向。
- 重定向跨源时剥离凭据；不使用共享 cookie jar。
- 测试 fixture 仅在显式环境开关下启用，且只接受 loopback；非 loopback 请求 403 fail closed。
- 测试配置必须是 `tests/.runtime` 下的绝对路径并带 schema version，生产进程不能被任意 JSON 重定向。

## 7. 功能开关与回滚

生产 `config.json` 可使用顶层 `feature_flags`（也兼容 `gallery_v53_feature_flags`）：

```json
{
  "feature_flags": {
    "v2_routes_enabled": true,
    "gallery_new_ui_enabled": true,
    "provider_danbooru_v2": true,
    "provider_gelbooru_v2": true,
    "provider_yandere_v2": true,
    "provider_civitai_v2": true,
    "gelbooru_approx_rank_enabled": false,
    "yandere_html_popular_experimental": false,
    "civitai_experimental_web": false
  }
}
```

回滚优先级：

1. 只关闭故障站点的 `provider_<site>_v2`，其它站不受影响。
2. 设置 `gallery_new_ui_enabled=false`，保留 V2 后端但前端回到旧 UI。
3. 同时关闭所有 Provider、新 UI，再设置 `v2_routes_enabled=false`；此时 `/v2/*` 返回 404，旧接口继续工作。
4. 若需完整字节级恢复，停止 ComfyUI 后使用终极备份的 `original/`。

不允许开启 `legacy_posts_via_v2_*`：该 shadow 路径没有在 V53 实现，配置会 fail closed，而不是静默改变旧 `/posts` 行为。

## 8. 自动核验结果

| 门禁 | 结果 |
|---|---|
| Python pytest | 113/113 PASS |
| Node 前端/runner 测试 | 16/16 PASS |
| JavaScript 语法 | 46 个文件 PASS |
| Python compileall | PASS |
| PowerShell runner 语法 | PASS |
| ComfyUI quick import | PASS；19 个模块、22 个节点 |
| 四站 fixture API | 29/29 PASS；四站均跟随 nextCursor，第二页 pageKey 不同且终止 |
| `gallery_new_ui_enabled=false` | 29/29 PASS，清理 PASS |
| `v2_routes_enabled=false` | 1/1 PASS；V2 404，清理 PASS |
| 四站 live smoke | 19 PASS、3 ENV_BLOCKED |
| 浏览器真实 UI | 稳定 test ID、卡片、Gelbooru 分类/排行、Danbooru 切站/排行、双节点状态均 PASS；插件错误 0 |

live smoke 结果：Danbooru、Yande.re 的最新/排行/分类均返回数据；Civitai 最新/排行/分类请求成功，其中分类出现合法空结果；Gelbooru 的三个 live case 在当前环境返回 `auth_invalid` 401，因此只记为 `ENV_BLOCKED`，没有冒充 live verified。fixture、合同和浏览器门禁不受此环境凭据问题影响。

## 9. 证据位置

- 最终稳定 fixture：`tests/.runtime/20260719-142539-57ec97d0/manifest.json`（29 PASS）。
- 新 UI 回滚：`tests/.runtime/20260719-142716-017ae07d/manifest.json`（29 PASS）。
- V2 路由回滚：`tests/.runtime/20260719-142637-c434f639/manifest.json`（1 PASS）。
- 四站 live：`tests/.runtime/20260719-135628-03a1e016/manifest.json`（19 PASS、3 ENV_BLOCKED）。
- 浏览器投影证据：`tests/.runtime/browser-20260719-135753-49c1be48/browser-evidence.json`。
- 浏览器截图：`tests/.runtime/browser-20260719-135753-49c1be48/browser-ranking-ui.png`。
- 浏览器进程清理：`tests/.runtime/browser-20260719-135753-49c1be48/browser-cleanup.json`。
- 最终汇总：`tests/.runtime/V53_FINAL_DELIVERY_20260719.json`。

所有 runner manifest 均记录 `state=PASS`、`cleanupState=PASS`、启动 PID 已退出、端口已释放、受保护的原配置/日志状态未改变。运行证据位于 `.gitignore` 覆盖的本地目录，不应直接提交。

交付结束后，用户原 ComfyUI 已按原参数恢复到 `127.0.0.1:8188`；本次恢复进程 PID 为 `31000`，端口归属、`/system_stats`、feature endpoint 和 `DanbooruGalleryNode` 均核验通过。

## 10. 已知限制

- Gelbooru live 需要当前环境可用的 API 凭据；本次 401 未被掩盖为代码成功。
- Gelbooru 日/周/月近似榜保持关闭；Yande.re HTML Popular 和 Civitai 实验网页路径保持关闭。
- Yande.re 周期榜基于公开 date range + score order，能力明确标为 provisional，不宣称站内独立 Popular 榜。
- Civitai 分类可能合法为空；深分页必须沿 `nextCursor`，超过公开 offset 限制会返回 `pagination_limit`。
- 本地收藏不是站点公开收藏 API；Gelbooru/Yande.re 明确不提供该标签。

## 11. 公开 API 依据

- Danbooru：<https://danbooru.donmai.us/wiki_pages/help%3Aapi>
- Gelbooru DAPI：<https://gelbooru.com/index.php?page=help&topic=dapi>
- Yande.re JSON posts：<https://yande.re/post.json>
- Civitai 官方 REST API 参考：<https://github.com/civitai/civitai/wiki/REST-API-Reference>

最终签字：稳定能力、回滚门禁、真实 ComfyUI 加载、浏览器交互、进程清理和备份恢复链均已核验；环境阻断项已单列，未被误报为通过。
