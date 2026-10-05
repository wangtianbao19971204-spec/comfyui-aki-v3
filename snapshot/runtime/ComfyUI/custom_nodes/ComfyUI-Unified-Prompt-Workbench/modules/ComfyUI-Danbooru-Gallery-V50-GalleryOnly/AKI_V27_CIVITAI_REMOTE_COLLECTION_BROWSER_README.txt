AKI V27 - Civitai 远端收藏夹浏览（实验）

本版新增：
1. Civitai 远端收藏夹浏览：当来源切到 Civitai，并在设置中启用“Civitai 远端收藏（实验）”后，点击收藏夹按钮，会优先读取远端收藏夹内容。
2. 支持 image.getInfinite：按默认收藏夹 ID 拉取远端收藏图片列表，并支持继续翻页（基于 nextCursor）。
3. 设置页新增收藏夹下拉框：测试远端收藏成功后，会显示远端收藏夹列表，可直接选择默认收藏夹。
4. 搜索框支持 collection:收藏夹ID（或名字） 语法，可手动切换指定远端收藏夹。
5. 如果远端收藏浏览失败，会自动回退到插件原有的 Civitai 本地收藏模式。

使用方法：
- 打开设置 -> Civitai.red API（可选）
- 启用“Civitai 远端收藏（实验）”
- 粘贴 civitai.red 的 Request Headers 或 Copy as cURL（必须包含登录 Cookie）
- 点“测试远端收藏”
- 从下拉框选择默认收藏夹（例如 cloth）
- 保存设置
- 主界面切到 Civitai，点击收藏夹按钮，即可浏览远端收藏夹内容

注意：
- 远端收藏图片 URL 为按 Civitai 当前图片 CDN 规则拼接的实验实现；若站方再次改版，可能需要后续微调。
- 添加/移除收藏逻辑仍走 collection.saveItem。
