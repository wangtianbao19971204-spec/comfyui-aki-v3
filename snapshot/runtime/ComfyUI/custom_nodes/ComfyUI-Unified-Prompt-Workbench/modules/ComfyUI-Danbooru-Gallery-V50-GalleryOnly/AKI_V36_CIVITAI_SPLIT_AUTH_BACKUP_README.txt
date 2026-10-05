AKI V36 - Civitai 双认证输入框与完整备份

改动：
1. 设置页把 Civitai 认证拆成两个输入框：
   - ① Civitai.red 收藏/collection Cookie：粘 collection.getAllUser / collection.saveItem 的 Copy as cURL。
   - ② search-new.civitai.com 搜索授权：粘 multi-search 的 Copy as cURL。
2. 后端分别保存：
   - civitai_collection_headers
   - civitai_search_headers
   并继续保留旧版 civitai_browser_headers 作为兼容合并备份。
3. 导出设置会包含两套 Civitai 认证字段、Civitai API key、默认收藏夹 ID、远端收藏开关。
4. 导入设置会恢复两套 Civitai 认证字段。
5. collection.* / image.getInfinite 只用收藏 Cookie；multi-search 只用搜索授权，避免互相污染。

注意：导出的设置文件包含账号 Cookie 与搜索授权，只能自用，不要发给别人。
