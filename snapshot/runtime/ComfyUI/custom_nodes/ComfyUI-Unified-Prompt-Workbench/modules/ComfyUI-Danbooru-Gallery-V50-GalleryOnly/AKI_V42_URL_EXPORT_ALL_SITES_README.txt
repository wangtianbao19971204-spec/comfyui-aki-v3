AKI V42 - URL 导出支持三站

基底：v39 稳定前端，保留 Civitai loose 按钮、multi-search、远端收藏认证拆分等功能。

本版新增/修复：
1. “网址”按钮扩展到 Danbooru / Gelbooru / Civitai 三个来源。
2. 开启“网址开”后，选图输出只返回对应网页地址：
   - Danbooru: https://danbooru.donmai.us/posts/{id}
   - Gelbooru: https://gelbooru.com/index.php?page=post&s=view&id={id}
   - Civitai: https://civitai.red/images/{id}
3. 默认关闭时，不再把 Civitai 的 Creator / URL 伪装成 prompt 输出。
4. Civitai 无真实 prompt 时默认输出空；需要 URL 时请开启“网址”按钮。
