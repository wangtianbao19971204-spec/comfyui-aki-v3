AKI V34 - Civitai 认证合并保存修复

修复点：
1. Civitai 远端收藏 Cookie 与 multi-search Authorization 不再互相覆盖。
2. 允许用户先粘 collection.getAllUser 的 Copy as cURL，再粘 multi-search 的 Copy as cURL；保存时会合并 Cookie/Authorization。
3. 设置状态新增：Cookie / CivitaiToken / SearchAuth，用于判断收藏夹与搜索认证是否都存在。
4. collection.getAllUser 401 时给出更准确的提示：需要重新粘 civitai.red 登录状态下的 collection.getAllUser cURL。

使用建议：
- 先粘 collection.getAllUser 的 Copy as cURL，保存并测试远端收藏，确认 CivitaiToken=有。
- 再粘 multi-search 的 Copy as cURL，保存，确认 SearchAuth=有。
- v34 会保留已有 Cookie，不会被新 cURL 轻易覆盖。
