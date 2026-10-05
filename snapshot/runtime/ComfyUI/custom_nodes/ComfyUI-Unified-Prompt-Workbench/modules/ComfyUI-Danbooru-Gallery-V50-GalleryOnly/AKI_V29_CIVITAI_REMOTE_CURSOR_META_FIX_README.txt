AKI V29 - Civitai 远端收藏夹 cursor/meta 热修复

修复内容：
- 修复 Civitai 远端收藏夹 image.getInfinite 返回 HTTP 400 invalid_union / expected bigint 的问题。
- Civitai Web 对 tRPC 使用 superjson；首页收藏夹请求需要 cursor=null + meta.values.cursor=["undefined"]。
- v29 按浏览器抓到的 Request URL 格式补上 tRPC meta 编码。

使用：
- 启用 Civitai 远端收藏并保存 Copy as cURL / Request Headers。
- 点击收藏夹按钮或搜索 civitai:favorites。
- C诊断 calls 中应看到 remote_collection items > 0，而不是 image.getInfinite HTTP 400。
