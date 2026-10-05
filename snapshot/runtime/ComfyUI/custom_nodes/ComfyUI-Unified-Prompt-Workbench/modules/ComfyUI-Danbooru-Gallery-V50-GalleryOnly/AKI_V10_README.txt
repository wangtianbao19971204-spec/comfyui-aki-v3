ComfyUI-Danbooru-Gallery v1.0-gelbooru-html-fallback

重点：
- Gelbooru 优先走 DAPI JSON。
- 如果 DAPI 401 / 未配置 user_id+api_key / JSON 失败，会自动退回 Gelbooru 网页搜索页解析，不再直接显示空结果。
- Danbooru 仍是原生 API；如果 Cloudflare challenge，代码无法保证绕过。
- 完整包不包含任何账号或 API key。

安装：
1. 关闭 ComfyUI。
2. 备份旧 custom_nodes/ComfyUI-Danbooru-Gallery。
3. 删除旧目录。
4. 解压本包，把 ComfyUI-Danbooru-Gallery 放入 custom_nodes。
5. 重启 ComfyUI，浏览器 Ctrl+F5。
6. 节点来源选择 Gelbooru，类别勾选 general。

如果你已有 Gelbooru user_id/api_key，仍建议在设置里填上；否则会用 HTML fallback。
