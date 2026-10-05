ComfyUI-Danbooru-Gallery v13 - Danbooru Browser Request Headers Mode

目的
----
这个版本保留 v12 的浏览器桥接，但新增一个更轻量的 Danbooru 浏览器请求头模式。
它不需要 Playwright，不需要 remote-debugging-port，也不需要启动专用调试浏览器。

适用场景
--------
- 后端 D诊断显示代理请求被 Cloudflare challenge。
- Cookie fallback 已启用但仍不通。
- 你不想使用 Playwright / CDP 浏览器桥接。
- 你的浏览器在同一代理出口下可以打开 Danbooru posts.json 并看到 JSON。

用法
----
1. 用和 ComfyUI 后端相同的代理出口打开浏览器。
2. 打开：
   https://danbooru.donmai.us/posts.json?limit=1
3. 如果出现 Cloudflare 页面，在浏览器里正常通过验证，直到页面显示 JSON。
4. 按 F12 打开 DevTools。
5. 进入 Network，刷新 posts.json 页面。
6. 点 danbooru.donmai.us/posts.json 这一条请求。
7. 在 Headers 里复制 Request Headers；或者右键请求，Copy -> Copy as cURL。
8. 回到 ComfyUI 节点：齿轮设置 -> 用户 -> Danbooru 浏览器请求头模式（比桥接简单）。
9. 粘贴 Request Headers / cURL，勾选启用，保存。
10. 点 D诊断。

成功标志
--------
D诊断里应看到：
- browser_headers: enabled=true present=true cookie=true ua=true
- posts_public_proxy_order_id_desc 或 posts_search_proxy_curl_cffi_chrome category=ok_json

限制
----
如果浏览器地址栏本身也无法显示 posts.json JSON，而是一直 Cloudflare challenge，
这个模式也无法生效。此时需要换代理出口或网络环境。

安全
----
浏览器请求头里通常含 Cookie，属于敏感信息。不要发给别人。
导出日志会尽量脱敏；完整设置导出会包含原始请求头，仅用于本机备份。
