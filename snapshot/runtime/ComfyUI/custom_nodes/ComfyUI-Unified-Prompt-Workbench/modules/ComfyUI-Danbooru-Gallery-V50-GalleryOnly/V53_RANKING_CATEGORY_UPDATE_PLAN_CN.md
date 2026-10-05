# V53 排行与分类浏览完整更新、核验及 ComfyUI 交付计划

> 状态：执行就绪的更新计划；功能代码尚未开始修改。  
> 基线日期：2026-07-19。  
> 目标插件：`ComfyUI-Danbooru-Gallery-V50-GalleryOnly`。  
> 当前运行基线：ComfyUI `0.27.1`，Python `3.13.11`。

## 1. 更新目标

把当前依赖搜索框元标签的画廊，升级成按站点能力驱动的浏览器，提供：

1. `最新 / 排行 / 分类 / 搜索 / 收藏` 五种明确模式。
2. Danbooru、Gelbooru、Yande.re、Civitai 各自正确的排行语义。
3. 标签、角色、作品、画师，或 Civitai 模型、作者、模型标签等站点原生分类。
4. 明确区分 `原生排行 / 服务端区间排行 / 客户端近似 / 不支持`，不静默降级。
5. 可靠的游标或页码分页、取消请求、防止换站串页，以及可解释的错误状态。
6. 保留现有卡片、瀑布流、图片代理、提示词输出、收藏、翻译和旧工作流兼容性。
7. 在真实 ComfyUI 中完成可复现、可留证据、可回滚的交付测试。

首版只做“当前选定站点内排行”。四站的 score、reaction、收藏量不可直接比较，不建立未经校准的跨站总榜。后续若需要跨站流，采用轮询混排或站内百分位/RRF，并命名为“跨站推荐”。

## 2. 完成定义

满足以下全部条件才可认定 V53 交付完成：

- 四个 Provider 的能力声明与实际请求严格一致。
- UI 不再通过统一追加 `order:rank` 实现排行。
- Danbooru、Civitai 使用公开原生排行接口；Gelbooru、Yande.re 使用准确命名的站点可用方案。
- V2 中只有 `HTTP 2xx + error:null + items:[]` 才表示上游成功空结果；非 2xx envelope 即使为形状稳定而带 `items:[]`，仍由 `error` 表示失败。离线、鉴权、限流、上游错误、响应结构变化均可区分。旧裸数组 `/posts` 明确保留历史吞错语义，仅作为限期兼容接口，不纳入这条保证。
- 旧 `/danbooru_gallery/posts` 参数和裸数组返回保持兼容至少一个发布周期。
- 快速切换站点、模式、周期时，只有最后一次请求可以提交 UI。
- 多个 Gallery 节点互不覆盖状态，删除节点后不遗留请求、Observer 或全局监听。
- 默认尺寸 `780×938`、用户实测尺寸 `856×1220` 和窄宽 `480×900` 均无横向溢出。
- 安全测试确认不存在 SSRF、认证头外送、通过 HTTP 明文读取秘密或日志泄密。
- 离线自动测试和真实 ComfyUI 夹具测试必须通过；四站 live smoke 必须执行并记录。公网环境故障不判定为代码失败，但对应站点不得标记为“已完成 live 验证”。
- 可通过功能开关逐站退回旧实现，不需要反向破坏性数据库迁移。

## 3. 当前基线与已知阻塞

### 3.1 真实 ComfyUI 基线

2026-07-19 已在正在运行的 `http://127.0.0.1:8188` 完成只读/临时 UI 冒烟：

| 项目 | 基线结果 |
|---|---|
| ComfyUI 健康 | `/system_stats` 正常；版本 `0.27.1` |
| 节点注册 | `/object_info/DanbooruGalleryNode` 返回 200，显示名为 `D站画廊 (Danbooru Gallery)` |
| 插件设置路由 | `/danbooru_gallery/ui_settings` 与 `/language` 正常 |
| 节点添加 | 在隔离的空白工作流中可从节点库添加并显示完整 Gallery 控件 |
| 普通 Danbooru 列表 | 渲染 40 个卡片容器；抽样前 5 个中 4 个缩略图代理成功，1 个无可用 URL |
| 当前排行按钮 | 点击后搜索值变成 `order:rank`，不是结构化排行请求 |
| 当前排行渲染 | 生成 40 个卡片容器，但观测时成功缩略图数为 0，状态没有解释上游/数据原因 |
| 控件布局 | 实测控件区有 14 个直接子控件；`856px` 节点宽度下 `scrollWidth=900 > clientWidth=856` |
| Python 语法基线 | 目标插件 `py/` 执行 `compileall` 通过 |
| JavaScript 语法基线 | 递归检查 39 个 `.js` 文件，全部通过 `node --check` |
| Provider 自动测试 | 当前不存在，需要由 V53.0 建立 |
| 前端环境噪声 | 页面还有其它扩展的 preload/通知错误，交付时必须按本插件 URL/前缀过滤日志 |

ComfyUI 在低画布缩放（实测约 16%）会隐藏 DOM widget。浏览器验收必须先定位节点并把画布精确设为 100%，否则容易产生“控件不存在”的假失败。

### 3.2 四站接口基线

当前旧 `/posts` 冒烟结果：

| 站点 | HTTP | 结果 | 基线说明 |
|---|---:|---|---|
| Danbooru | 200 | 有数据 | 代理失败后可直连回退 |
| Gelbooru | 200 | `[]` | 上游代理失败，HTML fallback 另触发重复 `headers` 参数错误 |
| Yande.re | 200 | `[]` | 上游代理 `127.0.0.1:10081` 未监听 |
| Civitai | 200 | `[]` | `.red`、`.com` 和 fallback 都受无效代理影响 |

后三站的实际网络失败被转换成 200 空数组，证明“结构化错误”必须成为 V53 硬门禁。公网 live smoke 在修复/启用代理前不能作为唯一交付依据。

### 3.3 必须先处理的安全问题

1. `/danbooru_gallery/civitai_prompt` 接收任意 `image_url`，媒体提取路径缺少主机、DNS 和重定向复验。
2. `_civitai_request` 可能向非 Civitai URL 附带 Bearer；认证 API 请求与无凭据媒体下载必须拆开。
3. 多个 GET 设置接口会返回明文 Key、Cookie、Header 或完整设置。
4. 当前日志会记录带认证查询参数的上游 URL。基线测试已经确认日志中存在真实认证参数，计划文档和测试证据不得复制这些值。

安全补丁上线后，应清理或限制旧日志访问，并建议用户轮换已经进入日志的 Danbooru/Gelbooru 凭据。

## 4. 站点能力与产品语义

统一保真度枚举：

- `native`：官方公开 API 原生提供该排序语义；不自动声称它与网站 UI 或 dedicated Popular 完全等价。`basis` 进一步区分 `dedicated_popular_endpoint` 与 `official_metric_sort`。
- `server_derived`：公开官方接口按指定字段/时间窗排序，但不等于网站 Popular。
- `client_approx`：在有限候选集上本地计算，必须显示采样范围和覆盖度。
- `unsupported`：不发送请求，UI 隐藏或禁用并显示原因。

| 站点 | 排行 | 周期 | 分类/Facet | UI 名称 |
|---|---|---|---|---|
| Danbooru | `/explore/posts/popular.json` | 日、周、月 | general/artist/copyright/character/meta | `官方热门榜`，`native` |
| Danbooru | posts 按 favcount/score | 全部时间 | 同上 | `收藏总榜/分数总榜`，`server_derived` |
| Gelbooru | DAPI `sort:score:desc` | 全部时间 | Tag DAPI 累计高频标签；分类类型只声明实际可得项 | `总分榜`，`server_derived`；提示 score 约每日更新一次 |
| Gelbooru | 最近候选集本地按 score 排 | 日、周、月，可选 | 同上 | `近似周期分数榜`，`client_approx`，默认关闭 |
| Yande.re | `date:<range> order:score` | 日、周、月、年 | tag type 标注、按 type 的 related tags；不承诺按 type 枚举全部标签 | `区间分数榜（非站内 Popular）`；启用前完成 contract/live 验证，之后为 `server_derived` |
| Civitai | `Most Reactions` | 日、周、月、年、全部 | 已知 image tag ID 过滤；模型 taxonomy、base model、model/version、creator 分开浏览；V53 首版 media type 固定 image | `互动榜`，`native` |
| Civitai | `Most Comments` | 同上 | 同上 | `评论榜`，`native` |
| Civitai | `Most Collected` | 同上 | 同上 | 官方 public API contract/live 验证通过后为 `收藏榜`、`native`；验证前 `unsupported` |

约束：

- Gelbooru 没有可靠的公开周期 Popular JSON；近似榜必须显式开启并展示 coverage。
- Yande.re 的公开 API 方案不得称为官方 Popular；官方 HTML Popular 页面存在，但没有文档化的稳定 JSON API，因此 HTML 解析只能作为实验功能。
- Civitai native 排行固定使用 canonical host `https://civitai.com/api/v1/...`；`.red`、`multi-search`、tRPC、X-Meili/Cookie 路径不满足 native 契约，只能归入独立 `experimental_web` 能力。
- Civitai 公共 image API 不提供 Danbooru 式任意图片提示词分类，不能把模型 taxonomy 假装成角色/作品标签。
- `images?tags=<numeric IDs>` 只证明已知 image tag ID 可过滤；在公开发现链路验证前声明 `imageTagDiscovery=false`。模型列表/类型走 `/api/v1/models`，创作者走 `/api/v1/creators`，模型 taxonomy 独立标记，不能与图片 tag 共用一种 ID。
- 标签按 count 排序表示累计量，不应命名为“实时趋势”。
- 表中标注“启用前验证”的能力在 capability 初始快照中为 `provisional/unsupported`，不得仅凭当前私有实现或文档记忆提前开放 UI。

排行时间窗不是跨站同一种概念，统一返回 `periodSemantics`：Danbooru 为 `calendar_anchor`，Yande.re 为 `explicit_range`，Civitai 为 `rolling_current`，Gelbooru 近似榜为 `bounded_sample`。capabilities 同时声明 `supportsAnchorDate`；Civitai 不显示历史 anchor date 控件。

安全等级也按站点声明，不发送统一 rating 值：Danbooru/Gelbooru 为 `general|sensitive|questionable|explicit`，Yande.re 映射 `safe|questionable|explicit`，Civitai 优先使用 `browsingLevel`，`nsfw` 只作为兼容参数。

### 4.1 ProviderCapabilities 版本化契约

`/v2/providers` 返回 `schemaVersion`、静态 `features` 和运行态 `availability/auth/limits`。静态能力不能被“当前未登录”覆盖，运行态也不能把无凭据 Provider 宣称为可用。最小形状：

```json
{
  "schemaVersion": 1,
  "source": "civitai",
  "features": {
    "views": [
      {"id": "latest", "state": "supported", "reasonCode": null, "requiresAuth": false, "scope": "public_api"},
      {"id": "ranking", "state": "supported", "reasonCode": null, "requiresAuth": false, "scope": "public_api"},
      {"id": "category", "state": "supported", "reasonCode": null, "requiresAuth": false, "scope": "public_api"},
      {"id": "favorites", "state": "supported", "reasonCode": null, "requiresAuth": false, "scope": "local"},
      {"id": "search", "state": "unsupported", "reasonCode": "public_free_text_unavailable", "requiresAuth": false, "scope": "experimental_web"}
    ],
    "ranking": [{
      "metric": "reactions",
      "state": "supported",
      "reasonCode": null,
      "requiresAuth": false,
      "periods": ["day", "week", "month", "year", "all_time"],
      "fidelity": "native",
      "basis": "official_metric_sort",
      "periodSemantics": "rolling_current",
      "supportsAnchorDate": false
    }],
    "facets": [
      {"kind": "model", "state": "supported", "reasonCode": null, "requiresAuth": false},
      {"kind": "creator", "state": "supported", "reasonCode": null, "requiresAuth": false},
      {"kind": "model_taxonomy", "state": "supported", "reasonCode": null, "requiresAuth": false},
      {"kind": "known_image_tag_id", "state": "degraded", "reasonCode": "image_tag_discovery_unavailable", "requiresAuth": false}
    ],
    "compatibleFiltersByView": {
      "latest": ["safetyProfile", "model", "creator", "baseModel"],
      "ranking": ["safetyProfile", "model", "creator", "baseModel", "knownImageTagId"],
      "category": ["safetyProfile"],
      "favorites": ["safetyProfile"]
    },
    "pagination": {"kind": "opaque_cursor"},
    "safety": {"kind": "civitai_browsing_level"}
  },
  "availability": {"state": "available", "reason": null},
  "auth": {"required": false, "configured": false},
  "limits": {"maxPageSize": 200, "publishedRate": null}
}
```

feature `state` 固定为 `supported|provisional|degraded|unsupported`；非 supported 必须有稳定 `reasonCode`，需要登录的功能逐项声明 `requiresAuth`。前端只根据这些字段决定显示、禁用、徽章和提示，不能从 source 名称推断。

`GET /v2/facets` 请求固定为 `source/facet_kind/query/page_size/cursor/client_request_id/client_query_key`，其中 cursor 同样不透明。成功响应：

```json
{
  "requestId": "server-trace-id",
  "clientRequestId": "frontend-seq-id",
  "queryKey": "stable-client-query-key",
  "items": [{
    "id": "remote-or-normalized-id",
    "label": "Display name",
    "kind": "model",
    "category": null,
    "itemCount": 123,
    "countKind": "model_count",
    "state": "supported"
  }],
  "pageInfo": {"nextCursor": null, "pageKey": "opaque-page-key", "hasNext": false},
  "warnings": [],
  "error": null
}
```

Facet 错误复用 Browse 非 2xx envelope；unsupported facet 在发上游请求前返回稳定 reasonCode。

典型 limits：Danbooru posts 最大 200 且需处理账号等级/tag 数限制；Gelbooru/Yande 最大 100；Civitai 最大 200，并区分深分页 `pagination_limit` 与普通 rate limit。Yande 421 映射 throttle；未知官方每秒限额保持 `null`，不能猜值。

capabilities 缓存按 `schemaVersion + source + authScope`，静态部分可内置同版本安全兜底，运行态短 TTL。接口失败时只开放该 Provider 内置且明确支持的基础能力；例如 booru 可保留 latest/search，公共 Civitai 只保留 latest 和本地 favorites。排行/分类禁用并显示“能力信息加载失败”；过期运行态不得继续宣称认证可用。

## 5. 目标架构

### 5.1 后端目录

计划从当前大文件逐步抽离，旧入口暂不删除：

```text
py/danbooru_gallery/
  domain.py
  api_v2.py
  services/
    browse_service.py
    facet_service.py
  transport/
    http_client.py
    rate_limit.py
  providers/
    base.py
    danbooru.py
    gelbooru.py
    yandere.py
    civitai.py
  compatibility/
    legacy_posts.py
tests/
  fixtures/
  workflows/
  test_provider_capabilities.py
  test_provider_requests.py
  test_provider_normalization.py
  test_provider_pagination.py
  test_provider_failures.py
  test_security.py
  test_legacy_posts.py
```

Provider 最小接口：

```python
class GalleryProvider:
    def capabilities(self) -> ProviderCapabilities: ...
    async def browse(self, request: BrowseRequest) -> BrowseResult: ...
    async def list_facets(self, request: FacetRequest) -> FacetResult: ...
    async def autocomplete(self, request: AutocompleteRequest): ...
    async def get_post(self, post_id: str): ...
```

业务层不得继续散布 `if source == ...`；站点差异由 Provider 和 capabilities 承担。

### 5.2 V2 路由

新增：

```text
GET /danbooru_gallery/v2/providers
GET /danbooru_gallery/v2/browse
GET /danbooru_gallery/v2/facets
GET /danbooru_gallery/v2/autocomplete
```

`/v2/providers` 可带 `source`，也可一次返回四站静态能力。`/v2/browse` 参数：

```text
source
client_request_id
client_query_key
view=latest|ranking|category|search|favorites
query
metric
period
anchor_date
facet_kind
facet_id
safety_profile
page_size
cursor
allow_approx
```

`client_request_id` 每次请求唯一，服务端原样回显，作为前端提交结果的首要竞态门禁。`client_query_key` 是持久查询字段的稳定 hash：包含 source/view/query/metric/period/anchorDate/facetKind/facetId/safetyProfile/pageSize/allowApprox，不包含 cursor、刷新意图和 request id；服务端独立计算自身 cache key，不能把客户端 key 当安全边界。`pageKey` 由 queryKey + 当前 cursor 生成。

`facet_id` 是规范化 ID，显示名称由响应另行提供，避免 Civitai 数字 tag ID 与文本标签混用。`safety_profile` 由 Provider 显式映射到 booru rating 或 Civitai browsing level，禁止前端猜测。`cursor` 对前端是不透明字符串；Danbooru page、Gelbooru pid、Yande page 和 Civitai cursor 都编码在其中。响应只暴露 `nextCursor`，上一页由每节点、每 queryKey 的 cursor history 实现。

刷新按钮不得获得绕过缓存和限流的无条件 `force_refresh`。若保留强制刷新能力，只能作为受冷却、权限和 Provider budget 约束的内部选项；它不能绕过并发上限、Retry-After 或近似榜扫描预算。

统一成功响应：

```json
{
  "requestId": "opaque-id",
  "clientRequestId": "frontend-seq-id",
  "queryKey": "stable-client-query-key",
  "items": [],
  "pageInfo": {
    "nextCursor": null,
    "pageKey": "opaque-page-key",
    "hasNext": false
  },
  "ranking": {
    "requestedMetric": "reactions",
    "effectiveMetric": "Most Reactions",
    "period": "week",
    "fidelity": "native",
    "label": "互动榜",
    "basis": "official_metric_sort",
    "periodSemantics": "rolling_current",
    "coverage": null
  },
  "provenance": {
    "kind": "official_public_api",
    "endpoint": "civitai/images"
  },
  "applied": {
    "anchorDate": null,
    "timezone": null,
    "windowStart": null,
    "windowEnd": null,
    "requestTime": "2026-07-19T03:30:00Z",
    "upstreamPeriod": "Week",
    "safetyProfile": "general",
    "upstreamSafety": {"parameter": "browsingLevel", "value": 1}
  },
  "warnings": [],
  "error": null
}
```

上例是 Civitai rolling-current 响应，因此 anchor/range 为 null，只回显 requestTime、上游 period 和实际 safety 参数。Danbooru/Yande.re/Gelbooru 近似榜才按各自 periodSemantics 填 anchor、明确起止区间或 coverage。

错误对象必须包含稳定 code、HTTP 状态、是否可重试以及 `Retry-After`。建议 code：

```text
invalid_request
unsupported
auth_required
auth_invalid
rate_limited
pagination_limit
upstream_busy
upstream_timeout
forbidden
upstream_error
bad_gateway
challenge
schema_changed
network_unavailable
client_cancelled
```

非 2xx 也返回稳定、脱敏的 JSON envelope，例如：

```json
{
  "requestId": "server-trace-id",
  "clientRequestId": "frontend-seq-id",
  "queryKey": "stable-client-query-key",
  "items": [],
  "pageInfo": {
    "requestCursor": "opaque-attempted-cursor",
    "nextCursor": null,
    "pageKey": "opaque-page-key",
    "hasNext": null
  },
  "warnings": [],
  "error": {
    "code": "rate_limited",
    "httpStatus": 429,
    "retryable": true,
    "retryAfterSeconds": 2,
    "message": "上游暂时限流"
  }
}
```

有 `Retry-After` 时同时设置 HTTP header 和 `retryAfterSeconds`。Civitai 深分页 429 映射 `pagination_limit`，不能重试同一 page；只有从第一页取得的 nextCursor 链可继续。浏览器 fetch abort 与后端真正取消上游是两条断言：前端 abort 后必须拒绝旧响应提交；只有 transport 收到取消时服务端才记录 `client_cancelled`。

V2 路由严格使用正确的 4xx/429/502/503 和 error envelope。旧 `/posts` 保持裸数组及历史错误语义，默认继续调用旧函数；只有某站 Provider 完成并通过兼容快照后，才可通过该站兼容开关改为读取 V2 `items`。两类错误语义不得混为同一个验收断言。

为 Browse/Facet/Capabilities/Error 建立 JSON Schema（可选生成 OpenAPI），Provider 合同测试直接校验 schema，避免 Python 与前端各自演化字段。

### 5.3 统一 GalleryItem

保留当前卡片需要的 URL、尺寸、标签和提示词字段，同时保留原始互动指标，不再把 Civitai reactions、comments 混成一个含混 score：

```text
id, sourceSite, detailUrl
previewUrl, sampleUrl, fileUrl
width, height, mediaType, rating
tags{general,artist,copyright,character,meta,raw}
prompt, negativePrompt
metrics{score,favorites,reactions,comments,collected}
ranking{nativeMetric,nativeValue,displayPosition}
createdAt, rawVersion
```

`displayPosition` 只是当前结果流序号，不是站点官方全局名次；存在并列或缺少 nativeValue 时允许为 null，前端不得据此二次重排。

### 5.4 前端目录与状态

计划抽离：

```text
js/danbooru_gallery/
  api/gallery_api.js
  state/gallery_store.js
  state/request_coordinator.js
  components/browse_tabs.js
  components/ranking_controls.js
  components/facet_browser.js
  components/status_panel.js
```

状态拆成可序列化的持久查询状态和不入工作流的瞬时运行状态：

```js
{
  persisted: {
    schemaVersion: 2,
    activeSource,
    sourceDrafts: {
      danbooru: {
        mode: "latest|ranking|category|search|favorites",
        terms,
        facet: { kind, id, label },
        sort: { metric, period, anchorDate, allowApprox },
        filters: { safetyProfile },
        pageSize,
        viewMemory: { queryKey, scrollTop }
      }
    },
    outputSettings,
    legacyMigrationDone: true
  },
  runtime: {
    capabilities: { status, data, error, expiresAt },
    sessionsBySource: {
      danbooru: {
        "queryKey": {
          items,
          pages: [{ requestCursor, nextCursor, pageKey, items, scrollTop }],
          pageIndex,
          warnings,
          applied,
          initialError,
          loadMoreError
        }
      }
    },
    activeSession: { source, queryKey },
    requests: {
      capabilities: { controller, seq, clientRequestId, queryKey, status },
      browse: { controller, seq, clientRequestId, queryKey, status },
      facets: { controller, seq, clientRequestId, queryKey, status },
      autocomplete: { controller, seq, clientRequestId, queryKey, status }
    }
  }
}
```

前端硬性要求：

- 每个节点按 `capabilities/browse/facets/autocomplete` 建立四条独立 request lane，每条拥有自己的 `AbortController + requestSeq + clientRequestId + queryKey`；facet 搜索或补全不能取消正在加载的画廊。
- 某 lane 查询变化只 abort 该 lane，再生成新 clientRequestId/queryKey；只有 clientRequestId 和 queryKey 同时匹配该 lane active request 才可提交。切换 source 或删除节点时统一 abort 四条 lane。浏览器 fetch abort 后必须丢弃旧响应，但另行测试后端 transport 是否真的收到取消。
- `initialLoading` 与 `loadingMore` 分开；abort 不报错、不推进 cursor、不写缓存。下一页失败只写 `loadMoreError` 并保留已有 items/pages。
- 只信后端 `pageInfo`，不再用 40/100 或已渲染卡片数推算页码。
- 每个 source/queryKey 维护独立、有界 LRU 页面栈。首项 requestCursor=null；下一页成功后才 push；上一页读取历史 requestCursor 并恢复 scrollTop；重试不推进栈。切站保留该站 session，改变该站查询只新建/激活新 session；cursor 过期时显示“从第一页重新加载”，不猜测新 cursor。
- capabilities 是控件显隐、禁用和降级的唯一依据；接口失败时使用当前 Provider、同 schemaVersion 的内置最小能力兜底，不能套用跨站通用模式：booru 可保留 latest/search，公共 Civitai 只保留 latest 和本地 favorites；排行/分类 disabled + retry。
- 当前“类别”改名“输出标签”，与格式、网址、多选移入“输出设置”。
- 第一行是独立 tablist：来源 + `浏览/搜索/收藏`，其中恰有一个 selected；只有浏览 selected 时显示第二个 tablist `最新/排行/分类`，其中也恰有一个 selected。键盘左右键只在当前 tablist 内移动。
- active filters 使用 chip 展示；被忽略/降级的条件必须显示 warning。
- 每站保存独立 draft、viewMemory 和 runtime session，切站恢复对应 queryKey/scrollTop，且不得携带 `civitai:favorites`、`order:rank` 等 token。
- 节点序列化 widget 是查询/输出状态的唯一权威来源；localStorage 只保存语言、主题等全局纯 UI 偏好，不保存节点查询。
- 未保存工作流仍使用节点 widget 的内存状态；保存后随 workflow 持久化。克隆节点复制 persisted 查询/输出设置，但生成新 node instance id，并清空 runtime/pages/selection。旧 localStorage 仅在 widget 缺失且 `legacyMigrationDone` 未设置时导入一次，之后只读不写。
- reload 已保存工作流后，在 capability resolved 后恰好发起一次首屏请求；capability 和 browse 不允许重复初始化。
- `onRemoved` 必须 abort 请求、disconnect Intersection/ResizeObserver、destroy autocomplete/弹窗并移除仅属于本节点的监听；禁止用全局 selector 清理其它 Gallery 节点。
- 为 root/source/mode/sort/period/facet/grid/status/card/sentinel 增加稳定 `data-testid` 和必要 ARIA。
- 不继续扩大对已被 ComfyUI 标记废弃的 `/scripts/ui.js` 依赖；先抽兼容 DOM helper，再迁移到公开前端 API。

## 6. 分阶段实施与退出门禁

不得把以下阶段压成一次大提交。每阶段都要具备独立测试、功能开关和回滚点。

### V53.0：安全热修与基线冻结

实施：

- 冻结四站旧 `/posts` 典型查询、收藏、补全、图片代理快照。
- 对 `civitai_prompt`、`image_proxy` 及所有服务端 URL fetch 使用同一安全 transport：仅允许 Provider 明确列出的 HTTPS API/媒体主机，拒绝回环、私网、link-local、userinfo、混淆 IP 和非 HTTP(S)。
- 使用请求期内固定的已校验解析结果，避免“预检查一次、连接时再次解析”的 DNS rebinding 窗口；每次重定向重新校验，默认禁止跨主机重定向，并限制跳数。
- 限制响应 Content-Type、响应体/流大小、连接/读取总超时；媒体和元数据分别使用合理上限。
- 认证 API client 与无凭据 media client 分离；Bearer/Cookie 不随重定向转发，只允许注入明确 Civitai API origin。
- 所有凭据 GET 改为只返回 `hasAuth`/掩码状态；这里的安全目标是“禁止通过 HTTP 返回明文秘密”，并不假设现有本地配置已加密。
- 默认设置导出不包含 secrets。若保留含密钥备份，必须走独立显式流程，要求用户当次确认、loopback + ComfyUI auth/Origin/CSRF 限制，并返回 `Cache-Control: no-store`。
- 对 URL query、Authorization、Cookie、X-Meili 等日志统一脱敏。
- 修复 Civitai loose 正则中的异常控制字符。
- 建立 pytest 目录、fixture 规范和网络禁用 guard。
- 抽出统一路径解析器，允许测试配置把 config/log/db/cache/favorites/legacy-migration marker 全部重定向到唯一 test data root。fixture mode 若任何可写路径仍解析到插件共享目录、用户 8188 数据或 test root 之外，启动必须 fail closed。

退出门禁：

- SSRF、DNS rebinding、重定向绕过、超大/错误 Content-Type、Token 外送、HTTP 明文秘密读取和日志泄密测试全部通过。
- 旧功能快照没有非预期差异。
- `main.py --quick-test-for-ci` 能成功导入目标插件。

回滚：安全修复原则上不回滚；若影响媒体提示词，只允许临时关闭“远程图片提示词提取”，不能恢复任意 URL + Bearer 行为。

### V53.1：领域契约、V2 路由和兼容壳

实施：

- 新增 `BrowseRequest/Result`、`ProviderCapabilities/Error`、统一 item。
- 新增 `/v2/providers`、`/v2/browse`、`/v2/facets`。
- 先建立行为等价的 LegacyProvider adapter，使 V2 路由在新 Provider 未完成时仍可测试；旧 `/posts` 默认继续直接调用旧函数，只做低比例只读 shadow comparison。
- 某站新 Provider 通过合同和兼容快照后，才单独开启 `legacy_posts_via_v2_<site>`，由兼容壳读取 V2 items。
- 同步请求移出 aiohttp 事件循环，统一 async transport、超时和取消。
- 建立 host/account 并发上限、Retry-After、指数退避 + jitter；只重试幂等请求。
- 在领域契约中统一 opaque cursor/history；Civitai cursor stack 的具体实现放在 V53.2，但最小状态机和测试从本阶段开始。
- 移除全局 `__latest__` selection fallback，或至少按 workflowId/nodeId/sessionId 命名空间隔离，防止多个 Gallery 节点串 selection 状态。

退出门禁：

- V2 可以区分空结果与失败。
- LegacyProvider capability snapshot、V2 schema 和错误映射测试通过；尚未实现的新能力保持 provisional/unsupported。
- 30 秒模拟上游超时不阻塞其它 ComfyUI API。
- 旧 `/posts` 响应快照兼容。

回滚：关闭 `v2_routes_enabled` 停止暴露 V2；关闭对应 `legacy_posts_via_v2_<site>` 让旧接口回到旧函数。两者独立，不影响安全修复。

### V53.2：Danbooru 与 Civitai 原生排行

实施：

- Danbooru Popular 日/周/月、总收藏/总分数独立模式。
- Civitai `/api/v1/images` 的 Reactions/Comments + period；Collected 只有在公开 API contract 与 live 预检通过后才加入，否则保持 unsupported。
- Civitai 排行路径禁止调用 `search-new`、tRPC 或 cookie-based internal endpoint。
- 规范化 cursor；保存 Civitai cursor stack 以支持返回上一页。
- 官方返回顺序作为展示顺序，不做二次含混 rank/filter 重排。

退出门禁：

- 请求 golden tests 精确校验 path、enum、date/period、cursor。
- UI 展示的 metric、period、applied 和响应顺序一致。
- Civitai native rank 测试中 undocumented internal endpoint 调用数为 0。
- Collected capability 的启用提交必须同时包含官方 contract 证据和成功 fixture/live 请求证据。

回滚：分别关闭 `provider_danbooru_v2` 或 `provider_civitai_v2`。

### V53.3：Gelbooru 与 Yande.re 排行

实施：

- Gelbooru 全部时间总分榜使用 `sort:score:desc`，UI 提示 score 约每日更新一次。
- Gelbooru 可选周期近似榜先按 `sort:id:desc` 拉取受预算限制的近期候选，依据 created_at 到 cutoff 后再本地按 score 排；返回 pagesScanned、sampledItems、cutoffReached。缺少 created_at/score，或降级到缺字段的 HTML 时，该排行必须 unsupported。
- Yande.re 先用 fixture/live 验证确定日期窗 + `order:score`；通过后启用，UI 固定显示“非站内 Popular”。
- 更新 Gelbooru 四级 rating 为 general/sensitive/questionable/explicit；修复 HTML fallback 的 headers 参数冲突。
- 官方 Yande HTML Popular（无文档化稳定 JSON API）默认关闭，并独立标记实验来源。

退出门禁：

- `allowApprox=false` 时 Gelbooru 周期榜在发网前返回 unsupported。
- `allowApprox=true` 时 coverage 完整显示，预算到达后不会无限翻页。
- Yande 跨月、跨年、闰年日期窗 fixture 通过。

回滚：关闭对应 Provider；近似榜另有 `gelbooru_approx_rank_enabled` 开关。

### V53.4：分类、标签数据和补全

实施：

- Danbooru：general/artist/copyright/character/meta。
- Yande.re：对 `/tag.json` 结果做 0/1/3/4 类型标注，并提供按 type 的 related tags；`categoryListing=false`，除非未来有界本地扫描并显示 coverage。
- Gelbooru：Tag DAPI 累计高频/搜索；只显示实际有依据的分类类型。
- Civitai：`/api/v1/models` 枚举模型/类型/base model，`/api/v1/creators` 枚举作者，`/api/v1/tags` 只作为 model taxonomy 并独立分页；model version 从 models 响应或公开模型详情 resolver 枚举并建立 golden fixtures。已知 image tag ID 仅作过滤，image tag discovery 未验证前关闭。
- V53 首版 Civitai media type 固定 image；在视频卡片渲染、代理、选择输出和测试合同完成前不开放 video facet。
- 新增 `site_facets(site, taxonomy_kind, remote_id, name, category, item_count, count_kind, updated_at, aliases)`，唯一键 `(site, taxonomy_kind, remote_id)`；booru 无独立 ID 时使用规范化 name 作为 deterministic remote_id。`count_kind` 明确区分 post count、model count 等，禁止把 Civitai modelCount 写成 post_count。
- 增加数据库 schema version；迁移使用事务（含失败 rollback）、busy timeout/WAL 并发策略和迁移前备份，重复执行必须幂等，不能留下半迁移状态。
- 首次迁移把旧 `hot_tags` 复制为 `site='danbooru', taxonomy_kind='image_tag', count_kind='post_count'`。一个兼容发布周期内：旧代码继续读旧表；V2 新表优先、旧表 fallback；Danbooru 同步在同一事务中 dual-write 新旧表；其它站点只写新表。
- 自动补全请求始终携带 source，跨站同名 tag 不互相覆盖。

退出门禁：

- 迁移前后 Danbooru 补全快照一致。
- 迁移重复执行、故障注入、并发读取和 dual-write 一致性测试通过。
- 四站 facet 请求、类型映射、分页和空结果测试通过。
- Civitai 不出现伪造的 copyright/character 分类。

回滚：数据库只新增表和 schema version；关闭新 facet 服务后旧代码继续读旧表。Danbooru 在兼容期 dual-write，回滚不会丢失期间更新；不执行破坏性反向迁移。

### V53.5：前端模式、请求协调和分页

实施：

- 完成 Browse/Search/Favorites 及 Latest/Ranking/Category 导航。
- capabilities 驱动的 metric、period、rating、date、facet 控件。
- Request Coordinator、pageInfo 分页、加载更多兜底、重试状态。
- 每站/每节点状态隔离、旧 localStorage 一次性迁移。
- 设置新 data-testid、ARIA、只读无凭据 debug snapshot。
- 重新组织顶部控件，解决按钮墙和横向溢出。

退出门禁：

- 竞态、分页、双节点、reload、删除节点、错误状态和窄宽布局测试全部通过。
- 本插件过滤后的 console 无 uncaught/error。
- 旧工作流打开时节点类型、输出插槽和 selection payload 不变。

回滚：`gallery_new_ui_enabled=false` 回到旧 UI；V2 后端可以继续 shadow 运行。

### V53.6：缓存、性能、切流和正式交付

实施：

- 有界 LRU + TTL + single-flight；缓存键包含 provider、规范化请求、metric、period/periodSemantics、anchor/range、safetyProfile、facet ID、cursor、page size、schema 和匿名化 auth scope。
- 排行建议 TTL 3–5 分钟；facet/tag 30–60 分钟。401/403 不缓存，429 按 Retry-After 短暂抑制；认证变化立即失效。
- 新旧实现 shadow-call 只比较 ID 顺序、数量、耗时和错误类别，不重复下载图片；采用固定低采样率、共享缓存和共享 Provider budget，只允许 GET，不触发收藏、设置、同步等写操作。
- 分站点逐步切流；差异需分类为语义差异、网络差异或代码回归。

退出门禁：

- 并发同查询只产生一次上游请求。
- 前进、后退、末页、cursor 过期和账号切换无错页/串缓存。
- 真实 ComfyUI 交付矩阵和证据包完整。
- 功能开关回滚演练通过。

## 7. 自动核验流程

### 7.1 每次提交的快速门禁

```powershell
$py = 'G:\ComfyUI-aki-v3\python\python.exe'
$plugin = 'G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Danbooru-Gallery-V50-GalleryOnly'
$bundledNode = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$node = if ($env:DANBOORU_GALLERY_NODE_PATH) { $env:DANBOORU_GALLERY_NODE_PATH } `
        elseif (Test-Path -LiteralPath $bundledNode) { $bundledNode } `
        else { (Get-Command node -ErrorAction Stop).Source }

& $py -m compileall -q "$plugin\py"
& $py -m pytest "$plugin\tests" -q -m "not live"
Get-ChildItem "$plugin\js" -Recurse -Filter '*.js' | ForEach-Object {
  & $node --check $_.FullName
  if ($LASTEXITCODE -ne 0) { throw "JS syntax check failed: $($_.FullName)" }
}
```

把 `pytest>=9` 固定为开发/测试依赖，并在 pytest 配置中声明 `live`、`comfyui`、`security` markers。CI 默认通过 autouse socket guard 禁止公网，仅允许明确的 loopback；Provider 必须注入 mock transport。测试若检测到未声明的真实网络请求，应直接失败。

### 7.2 Provider 合同测试

每站至少包含：

- capability snapshot。
- 请求 URL/query golden test。
- 成功首/中/末页、空页。
- 响应归一化和字段缺失。
- Provider 实际支持的 page/pid/after_id/cursor 状态机，不把一种游标泛化到所有 view。
- 401、403、429、5xx、timeout、非 JSON、schema drift。
- Retry-After、取消、重试次数和并发上限。
- 日志、异常、artifact 中不存在 Key/Cookie/Authorization。

站点特有断言：

- Danbooru：day/week/month；year 在发网前 unsupported；只有普通 posts 默认 ID 顺序测试 a/b cursor，Popular 使用数字 page，score/favcount 不假定支持 a/b。
- Gelbooru：posts 首 UI 页映射 DAPI pid=0；HTML fallback 使用不同 cursor kind/缩略图 offset；累计 count 标签只做首屏或有界扫描并标 incomplete，不承诺 `after_id + orderby=count` 稳定全量分页；HTML/XML failure 不等于空结果。
- Yande.re：页码从 1 开始；日期窗起止包含性、时区、跨月/闰年；421 throttled；type 只用于标注/related，不测试未文档化 category listing。
- Civitai：所有 native 请求 host 必须为 `civitai.com/api/v1`；从第一页开始原样沿 metadata.nextCursor，不能从任意深页“转换”出 cursor；legacy 深页 429 返回 pagination_limit 并要求重启 cursor 链；499/503；native rank 禁止 `.red`、multi-search 和 internal endpoints。
- Rating/safety golden：Danbooru/Gelbooru 四级完整值，Yande s/q/e，Civitai browsingLevel；每个 view 测试 `compatibleFiltersByView`，不兼容过滤必须拒绝或带 warning 清除。

### 7.3 安全测试

- `127.0.0.1`、`::1`、RFC1918、link-local、十进制/十六进制 IP、userinfo、混淆 hostname。
- 公网域重定向到私网、DNS 解析变化、重定向循环。
- Bearer/Cookie 只出现在允许 origin，媒体 client 永远无认证头。
- 明文设置 GET、默认完整导出、日志 query、异常 repr 均不得包含秘密。
- 证据包脱敏扫描失败时禁止发布。

### 7.4 前端确定性测试矩阵

| ID | 场景 | 通过标准 |
|---|---|---|
| NAV-01 | 切换浏览/搜索/收藏、最新/排行/分类 | 父 tablist 恰有一个 active；浏览模式下子 tablist 也恰有一个 active；grid 不重复创建 |
| NAV-02 | D/C 保存不同 draft 后来回切换 | 各站恢复自身状态，无跨站 token |
| CAP-01 | 支持的 metric/period/facet | UI、请求、applied 完全一致 |
| CAP-02 | 不支持 date/rating/facet | 隐藏/禁用并显示原因，请求不携带字段 |
| CAP-03 | capabilities 超时/500 | 仅 Provider 内置最小能力可用（booru：latest/search；公共 Civitai：latest/本地 favorites）；排行/分类禁用且可重试 |
| RACE-01 | 延迟 D 请求后立即切 C | 浏览器 D fetch 被 abort/旧响应不可提交；另行记录后端 transport 是否收到取消；所有提交卡片来自 C |
| RACE-02 | 连续快速改 source/mode/period 五次 | 仅最后 queryKey 提交，最终 idle |
| RACE-03 | loadingMore 时切分类 | 旧页不 append，新模式从首 cursor 开始 |
| RACE-04 | browse 加载中同时搜索 facet/补全 | 四条 request lane 互不覆盖；切站/删节点才统一 abort |
| PAGE-01 | 首屏到末页 | 每个 cursor 只请求一次，hasNext=false 后停止 |
| PAGE-02 | 一页全被本地黑名单过滤 | 不误判末页，继续服从后端 pageInfo |
| PAGE-03 | 下一页 429/500 后 retry | 旧卡保留、cursor 不前移、不重复卡片 |
| PAGE-04 | 前进、上一页、cursor 过期 | 页面栈/scrollTop 恢复；过期时提示从第一页重启，不猜 cursor |
| STORE-01 | 操作后 reload/重开工作流 | 同节点恢复；capability resolved 后恰好一次首屏请求 |
| STORE-02 | 同工作流两个 Gallery 节点 | 状态、弹窗、请求完全隔离 |
| STORE-03 | 删除节点 A | B 正常；A 无残留请求和监听 |
| ERR-01 | empty/offline/401/429/5xx | 五种状态视觉和文案可区分 |
| A11Y-01 | 键盘切 tab/dropdown/facet | focus 可见，Enter/Space/Esc 正常 |
| LAYOUT-01 | 固定 viewport 1440×1000；节点 DOM widget 780×938、856×1220、480×900 | 对 `.danbooru-controls` 断言 scrollWidth<=clientWidth，关键模式控件可见 |
| LIFE-01 | 固定 ComfyUI canvas zoom 16%→100%、切工作流返回 | 100% 时 widget 可见且不重复初始化，状态恢复 |
| LOG-01 | 跑完完整矩阵 | 本插件 URL/前缀无 uncaught/error |

### 7.5 前端与真实 ComfyUI 自动化执行器

V53.0 新增开发用 `package.json`/lockfile，固定 `@playwright/test` 版本并提供 `test:e2e` script；标准 Playwright runner 不依赖人工点击或 Codex 专用浏览器状态。依赖安装是独立准备步骤（`pnpm install --frozen-lockfile` 和固定 Chromium 安装），交付脚本只检查依赖，不在测试过程中临时下载：

```powershell
$plugin = 'G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Danbooru-Gallery-V50-GalleryOnly'
$pnpm = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd'
$env:PLAYWRIGHT_BROWSERS_PATH = "$plugin\tests\.browsers"
& $pnpm --dir $plugin install --frozen-lockfile
& $pnpm --dir $plugin exec playwright install chromium
```

其它环境通过 runner 的路径参数提供等价 Node/pnpm/browser root；不得依赖上述 Codex 缓存路径作为唯一方案。

```text
tests/e2e/playwright.config.mjs
tests/e2e/gallery.spec.mjs
tests/e2e/helpers/evidence.mjs
tests/workflows/gallery_delivery.json
tests/run_delivery.ps1
```

runner 规则：

- 固定 workflow 只含一个或两个 `DanbooruGalleryNode`，没有模型依赖。
- 每次运行先写唯一 `test-config.json`，包含 mode、feature flags、fixture/data/config/log/db/cache 路径和选定站点；通过 `DANBOORU_GALLERY_TEST_CONFIG` 同时传给 quick-test 和 server。
- fixture 默认 Sites 为四站，也可显式缩小；始终开启 `v2_routes_enabled + gallery_new_ui_enabled`，只开启 `$Sites` 对应 provider，experimental_web 默认关闭；近似榜、legacy_posts_via_v2 分别在独立 case 开关。live 同样只开启被测 `$Sites` Provider，fixture 必须显式为 false，防止继承父进程残留值。
- flag 优先级：loopback test-config（仅测试模式）高于隔离 user config；生产环境只读用户配置/安全默认值。非法组合直接失败：`gallery_new_ui_enabled => v2_routes_enabled`；LegacyProvider 也必须通过 V2 routes capability/browse adapter 服务新 UI；`legacy_posts_via_v2_<site>` 需要对应 provider；approx/experimental 需要各自 provider。
- 不使用固定 sleep；等待 `data-testid=gallery-status`、clientRequestId/queryKey 或明确 network response。
- 通过浏览器 context 的 `X-Gallery-Test-Scenario` 头选择 `success/empty/delay/401/403/429/500/schema_drift/cursor_expired` fixture。
- 后端只有在 fixture mode + loopback 时接受该头；其它环境忽略并记录安全警告。若 fixture mode 检测到非 loopback listen，ComfyUI 启动 fail closed。
- 每个 case 在写盘前先做有界 DOM/network/console 投影和脱敏，不落原始 HAR。
- 支持显式 `-NodePath/-PnpmPath/-PlaywrightBrowsersPath`，或由仓库 wrapper 定位；preflight 校验 Node/pnpm 版本、lockfile、`@playwright/test` 版本和 Chromium revision。缺失时给出准备命令并退出，不在交付测试中隐式安装。

完整执行命令固定为：

```powershell
& 'G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Danbooru-Gallery-V50-GalleryOnly\tests\run_delivery.ps1' `
  -Mode fixture `
  -NodePath 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' `
  -PnpmPath 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd'
```

`run_delivery.ps1` 负责选择空闲端口、创建唯一 run-id 目录、启动/探活/校验进程归属、调用 Playwright、写 manifest，并在 `finally` 中只停止它自己启动的 PID。公网补充测试使用 `-Mode live -Sites danbooru,gelbooru,yandere,civitai`，不复用 fixture artifact 目录。

## 8. 真实 ComfyUI 交付测试

### 8.1 两条测试通道

1. **硬门禁：真实 ComfyUI + 固定 Provider fixture**  
   使用真实节点、真实前端和真实 HTTP 路由，但上游 transport 注入录制并脱敏的 fixture。可确定性制造延迟、取消、空页、401、429、cursor 和 schema drift。

2. **补充门禁：四站公网 live smoke**  
   每站只执行最小 Latest/Rank/Category/Page 流程，记录代理、Cloudflare、限流为环境结果。公网偶发故障不能覆盖确定性测试结论。

测试模式必须通过显式环境变量启用，例如 `DANBOORU_GALLERY_TEST_FIXTURES=1`，只允许 loopback 服务，并在 UI 显示“Fixture Test Mode”。生产默认关闭。

### 8.2 隔离启动

`run_delivery.ps1` 使用空闲端口、唯一 run-id 和独立 user/temp/output/plugin-data 目录，只加载目标插件，避免污染用户工作流、共享 tag DB、凭据、缓存和其它扩展日志。核心启动契约如下；脚本必须用 `try/finally` 包住完整测试：

```powershell
param(
  [ValidateSet('fixture','live')] [string]$Mode = 'fixture',
  [ValidateSet('danbooru','gelbooru','yandere','civitai')] [string[]]$Sites = @('danbooru','gelbooru','yandere','civitai')
)

$root = 'G:\ComfyUI-aki-v3'
$py = "$root\python\python.exe"
$comfy = "$root\ComfyUI"
$plugin = "$comfy\custom_nodes\ComfyUI-Danbooru-Gallery-V50-GalleryOnly"
$fixtureMode = $Mode -eq 'fixture'
$port = 8190 # runner 会探测；若已占用则选择其它端口或直接失败，绝不结束未知 PID
$runId = "$(Get-Date -Format yyyyMMdd-HHmmss)-$([guid]::NewGuid().ToString('N').Substring(0,8))"
$runtime = "$plugin\tests\.runtime\$runId"

if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
  throw "Test port $port is already in use"
}

New-Item -ItemType Directory -Force `
  "$runtime\user", "$runtime\temp", "$runtime\output", `
  "$runtime\plugin-data", "$runtime\plugin-data\logs", "$runtime\plugin-data\cache" | Out-Null

$testConfigPath = "$runtime\test-config.json"
$testConfig = @{
  mode = $Mode
  sites = $Sites
  runtimeRoot = $runtime
  dataRoot = "$runtime\plugin-data"
  logRoot = "$runtime\plugin-data\logs"
  dbPath = "$runtime\plugin-data\gallery-test.db"
  configPath = "$runtime\plugin-data\config-test.json"
  featureFlags = @{
    v2_routes_enabled = $true
    gallery_new_ui_enabled = $true
    provider_danbooru_v2 = $Sites -contains 'danbooru'
    provider_gelbooru_v2 = $Sites -contains 'gelbooru'
    provider_yandere_v2 = $Sites -contains 'yandere'
    provider_civitai_v2 = $Sites -contains 'civitai'
    civitai_experimental_web = $false
  }
}
$testConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $testConfigPath -Encoding UTF8

$args = @(
  "$comfy\main.py",
  '--listen', '127.0.0.1',
  '--port', "$port",
  '--cpu',
  '--disable-all-custom-nodes',
  '--whitelist-custom-nodes', 'ComfyUI-Danbooru-Gallery-V50-GalleryOnly',
  '--user-directory', "$runtime\user",
  '--temp-directory', "$runtime\temp",
  '--output-directory', "$runtime\output"
)

$oldTestConfig = $env:DANBOORU_GALLERY_TEST_CONFIG
$oldFixtureMode = $env:DANBOORU_GALLERY_TEST_FIXTURES
try {
  $env:DANBOORU_GALLERY_TEST_CONFIG = $testConfigPath
  $env:DANBOORU_GALLERY_TEST_FIXTURES = if ($fixtureMode) { '1' } else { '0' }

  & $py "$comfy\main.py" --cpu --quick-test-for-ci --disable-all-custom-nodes `
    --whitelist-custom-nodes ComfyUI-Danbooru-Gallery-V50-GalleryOnly
  if ($LASTEXITCODE -ne 0) { throw 'ComfyUI quick import failed' }

  $server = Start-Process -FilePath $py -ArgumentList $args -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$runtime\server.stdout.log" `
    -RedirectStandardError "$runtime\server.stderr.log"
} finally {
  $env:DANBOORU_GALLERY_TEST_CONFIG = $oldTestConfig
  $env:DANBOORU_GALLERY_TEST_FIXTURES = $oldFixtureMode
}
```

runner 在解析 test config 时验证所有 plugin 可写路径都位于本次 runtime；fixture/live 都不得读取共享 legacy settings 或复制用户凭据，live 默认匿名，需认证的 case 记为 ENV_BLOCKED。随后在 90 秒 deadline 内轮询 `/system_stats`，期间同时检查 `$server.HasExited`；就绪后用 `Get-NetTCPConnection` 确认 listener 的 OwningProcess 等于 `$server.Id`。任何失败都附带 stdout/stderr 尾部并停止测试。E2E、证据写入和 manifest 生成完成后，最外层 `finally` 只停止 `$server.Id` 对应的隔离进程并等待退出，不终止用户现有的 8188 进程，也不复用旧 runtime。

### 8.3 API 启动验收

必须通过：

```text
GET /system_stats
GET /object_info/DanbooruGalleryNode
GET /extensions
GET /danbooru_gallery/v2/providers
GET /danbooru_gallery/v2/browse?source=<site>&view=latest&page_size=20&client_request_id=<uuid>&client_query_key=<hash>
GET /danbooru_gallery/v2/browse?source=<site>&view=ranking&metric=<supported>&period=<supported>&page_size=20&client_request_id=<uuid>&client_query_key=<hash>
GET /danbooru_gallery/v2/facets?source=<site>&facet_kind=<supported>&page_size=20&client_request_id=<uuid>&client_query_key=<hash>
```

API 探针与前端测试必须共用一个 `buildGalleryRequest()`，不得各自手拼 query string。该 helper 先从 `/v2/providers` 选择当前 source 状态为 `available` 的 metric/period/facet kind，再生成 UUID v4 `client_request_id`；`client_query_key` 按第 4.3 节的持久字段构造对象、递归按键名升序排序、序列化为无空白 UTF-8 JSON，最后取 SHA-256 的 64 位小写十六进制全文。fixture 内保存 canonical JSON 和预期 hash，Python 与 JavaScript 各跑同一组向量，防止两端算法漂移。

断言：

- 节点 display name、category、输入输出没有兼容性变化。
- 目标 JS 只加载一次。
- fixture 的 HTTP 状态、warning、pageInfo、ranking fidelity 与预期一致。
- 没有明文秘密或未脱敏 URL 出现在响应/日志。

### 8.4 UI 交付步骤

1. 打开 runner manifest 中记录的 `http://127.0.0.1:<port>`。
2. 创建空白工作流，通过节点库添加 `D站画廊 (Danbooru Gallery)`。
3. 浏览器 viewport 固定 `1440×1000`，ComfyUI canvas zoom 精确设为 `100%`，确认 Gallery DOM widget 可见。
4. 依次执行四站 Latest、Rank、站点实际支持的 Category/Facet、下一页、返回、错误重试。
5. 执行连续五次 source/mode/period 快切，确认只有最后请求提交。
6. 放置两个 Gallery 节点，验证独立状态、独立弹窗和独立分页。
7. reload、切换工作流、删除其中一个节点，验证生命周期清理。
8. 在相同 viewport/100% canvas zoom 下，把 Gallery DOM widget 精确设为 `480×900`、`780×938`、`856×1220`，验证 `.danbooru-controls` overflow 和纯键盘操作。
9. 关闭 fixture 后以各站安全/普通内容过滤跑最小 live smoke；不得修改用户凭据、把凭据写入证据或把不确定分级的缩略图写入共享截图。
10. 关闭隔离 ComfyUI，复核进程退出且用户 8188 实例不受影响。

### 8.5 四站 live smoke

| 站点 | Latest | Rank | Category | 特殊断言 |
|---|---|---|---|---|
| Danbooru | 普通 posts | 官方 day/week/month | 五类 tag | `order:rank` 不进入搜索框；媒体 URL 可代理 |
| Gelbooru | DAPI pid | `sort:score:desc` | Tag DAPI 累计高频/搜索 | date 不支持时明确禁用；HTML fallback 标 degraded |
| Yande.re | page=1 起 | 验证后的 date range + `order:score` | type 标注/related tags | UI 显示“非站内 Popular”；不出现完整 category listing 承诺 |
| Civitai | Newest + cursor | reactions/comments；collected 需预检 | models/creators/model taxonomy；known image tag ID 过滤 | Network host 固定 civitai.com，且不出现 `order:rank`、`.red`、multi-search 或 tRPC 排行调用 |

### 8.6 证据包

每个用例保存到 `tests/artifacts/<version>/<run-id>/`，该目录加入 `.gitignore`：

```text
TCID_step-attempt_site_state.png
TCID_step-attempt_dom.json
TCID_step-attempt_network.json
TCID_step-attempt_console.json
TCID_step-attempt_assertions.json
manifest.json
```

- DOM 只投影 root/source/mode/status/card source/pageKey，不导出整个页面。
- Network 在写盘前投影并删除 Authorization、Cookie、API key、X-Meili 和认证 query；禁止先保存原始 HAR 再脱敏。
- Console 单独输出本插件 URL/`[DanbooruGallery]`，再附一份全局环境噪声基线。
- manifest 为每个 case/step/attempt 记录 `PASS|FAIL|ENV_BLOCKED`、期望、实际、artifact SHA-256、脱敏器版本；同时记录 ComfyUI/Python/插件版本、commit、feature flags、fixture hash、测试时间和端口，不记录秘密。
- fixture/contract 的 FAIL 一律阻止发布。live 的 ENV_BLOCKED 可作为环境结论，但该站不能标记 live verified；依赖 live 预检才能开放的 provisional 能力继续保持 disabled。

## 9. 发布、切流与回滚

建议功能开关：

```text
v2_routes_enabled
gallery_new_ui_enabled
legacy_posts_via_v2_danbooru
legacy_posts_via_v2_gelbooru
legacy_posts_via_v2_yandere
legacy_posts_via_v2_civitai
provider_danbooru_v2
provider_gelbooru_v2
provider_yandere_v2
provider_civitai_v2
gelbooru_approx_rank_enabled
yandere_html_popular_experimental
civitai_experimental_web
```

实际切流顺序（2026-07-19）：

1. 先在隔离配置中完成 V2 合同、四站 fixture、错误、分页、缓存和安全门禁。
2. `legacy_posts_via_v2_*` shadow 路由未实现且不得开启；所有 flag 在误开时 fail closed，旧 `/posts` 保持原函数，避免未经验证的静默切流。
3. 四个稳定 Provider 在交付矩阵通过后默认启用；任一站可用自己的 `provider_<site>_v2` 独立回滚。Gelbooru 近似榜、Yande.re HTML Popular、Civitai 实验网页路径仍关闭。
4. 新 UI 由 `gallery_new_ui_enabled` 整体切换；逐站 Provider 关闭时，同一 UI shell 安全回退旧 fetch 路径，不销毁/重建两套根 DOM。
5. 完成 fixture、live、双节点浏览器、`ui-off`、`v2-off`、进程清理和受保护文件哈希核验。
6. 更新 README、版本、交付说明和已知限制后恢复用户原 8188 服务。

回滚原则：

- 关闭相应 Provider/legacy 路由开关即可逐站恢复旧数据路径；新 UI 只按节点级开关整体回滚，避免混合生命周期。
- 本次分类直接读取公开 API，没有执行用户数据库迁移；旧标签/收藏数据保持原样。
- 缓存全部可丢弃，不作为持久业务状态。
- 发布前备份插件配置和标签数据库；回滚只切读取路径，不删除新表。
- 若仅某站 API 变化，只关闭该站能力，不拖垮其它 Provider。

## 10. 执行清单

- [x] 在修改前建立独立“终极备份”、ZIP、SHA-256 manifest 和恢复说明；本机无可用 Git 命令，因此没有伪造分支/提交状态。
- [x] 保存完整原插件快照，保留旧 `/posts`、收藏、补全、图片代理及节点输入输出行为。
- [x] 完成 V53.0 安全热修：统一脱敏、固定目标 SSRF 白名单、HTTPS/公共 DNS、手工重定向和跨源凭据剥离。
- [x] 建立 Provider 合同、mock transport、网络禁用、并发预算、single-flight 与缓存测试。
- [x] 上线 V2 providers/browse/facets/autocomplete，并保持旧接口默认走旧实现。
- [x] 完成 Danbooru 原生 Popular 与 Civitai 官方 Reactions/Comments 排行；未通过合同核验的 Collected 保持隐藏。
- [x] 完成 Gelbooru 全时段评分榜、Yande.re 周期评分榜及对应能力标注；近似榜和 HTML 实验路径默认关闭。
- [x] 完成四站分类与补全 source 修复；分类直接读取站点公开 API，不迁移或破坏用户原标签数据库。
- [x] 完成 Query Store、四 Request Lane、稳定 query key、pageInfo/游标分页及每站独立状态恢复。
- [x] 完成新导航、能力降级、输出设置兼容、稳定 DOM 测试标识和布局适配。
- [x] 通过 Python compileall、113 个 pytest、46 个 JS 文件语法检查、16 个 Node 测试和 ComfyUI quick-test-for-ci。
- [x] runner 在随机 loopback 端口启动真实 ComfyUI；四站 fixture API 29/29，通过第二页游标检查；浏览器实测 Gelbooru 分类/排行、Danbooru 切站/排行和双节点独立状态。
- [x] 完成四站公网 live smoke：19 PASS、3 ENV_BLOCKED；Gelbooru 因当前环境认证 401 未标记 live verified。
- [x] 完成敏感信息泄漏检查、双节点验证、`gallery_new_ui_enabled=false` 与 `v2_routes_enabled=false` 回滚演练，以及进程/端口清理核验。
- [x] 生成证据包并更新 README、版本、发布说明；交付结论与限制见 `V53_RANKING_CATEGORY_RELEASE_CN.md`。

### 10.1 2026-07-19 交付结论

- 稳定能力默认开启；Gelbooru 周期近似榜、Yande.re HTML Popular、Civitai 实验网页搜索和所有 legacy shadow 开关保持关闭。
- Civitai `model_taxonomy` 只能列出名称，公开图片 API 过滤要求数值 tag ID，因此不伪装成可过滤分类。
- 浏览器矩阵负责验证真实挂载、切页、卡片与能力联动；四站完整组合、错误和分页由同一真实 ComfyUI 进程下的 API probe 覆盖。
- 交付证据、备份位置、逐项结果和恢复命令均记录在发布说明中。

## 11. 官方 API 复核入口

每个实施阶段开始时重新核对公开接口，避免按旧假设编码：

- Danbooru API：<https://danbooru.donmai.us/wiki_pages/help%3Aapi>
- Danbooru Posts：<https://danbooru.donmai.us/wiki_pages/api%3Aposts>
- Danbooru Tags：<https://danbooru.donmai.us/wiki_pages/api%3Atags>
- Danbooru 用户等级/限制：<https://danbooru.donmai.us/wiki_pages/help%3Ausers>
- Gelbooru DAPI：<https://gelbooru.com/index.php?page=wiki&s=view&id=18780>
- Gelbooru 搜索语法：<https://gelbooru.com/index.php?page=wiki&s=view&id=26263>
- Gelbooru Rating：<https://gelbooru.com/index.php?page=wiki&s=view&id=2535>
- Yande.re API：<https://yande.re/help/api>
- Yande.re Cheatsheet：<https://yande.re/help/cheatsheet>
- Yande.re 官方 Popular HTML：<https://yande.re/post/popular_recent>
- Civitai REST API：<https://github.com/civitai/civitai/wiki/REST-API-Reference>
- Civitai Developer API：<https://developer.civitai.com/site/reference/>
- Civitai Images API source：<https://github.com/civitai/civitai/blob/main/src/pages/api/v1/images/index.ts>
