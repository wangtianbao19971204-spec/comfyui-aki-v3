AKI V32 - Civitai multi-search 授权 + prompt 误判修复

修复：
1. multi-search/images_v6 支持从 Civitai 设置中的 Copy-as-cURL / Request Headers 读取 Authorization / X-Meili-API-Key。
   - 如果 search-new.civitai.com 返回 401 missing_authorization_header，需要在 Civitai 网页搜索时抓 multi-search 请求，复制 Copy as cURL，粘到设置页的 Civitai.red Request Headers / Cookie 输入框。
   - 可以同时粘贴 collection 请求和 multi-search 请求；插件会合并 Cookie 与 Authorization。
2. 忽略 jfif_version / JFIF / DPI / ICC 等技术图片元数据，避免把 (1, 1) 误当成 prompt。
3. 继续保留 v31：普通文本搜索统一走 multi-search/images_v6，strict/loose 只影响本地过滤。

使用：
- Civitai 远端收藏：需要 collection.getAllUser 或 saveItem 的 Copy as cURL（含 Cookie）
- Civitai 普通搜索：若 C诊断显示 multi-search HTTP 401，需要抓 multi-search 的 Copy as cURL（含 Authorization）
- 二者可一并粘贴到同一输入框。
