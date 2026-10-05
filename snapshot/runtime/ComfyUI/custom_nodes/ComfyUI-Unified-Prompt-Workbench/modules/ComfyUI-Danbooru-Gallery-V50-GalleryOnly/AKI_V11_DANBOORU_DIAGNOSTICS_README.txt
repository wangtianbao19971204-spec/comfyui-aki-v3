ComfyUI-Danbooru-Gallery v1.1 D站诊断版

本版本基于当前 Gelbooru 正常的 v1.0 G 修复版制作。
目标：不改 G 站搜索/预览/输出逻辑，只增加 Danbooru 诊断能力。

新增内容：
1. 后端接口：/danbooru_gallery/diagnose_danbooru?tags=rating:general
2. 节点工具栏按钮：D诊断
3. 诊断维度：
   - Cloudflare challenge
   - Danbooru login/api_key 认证问题
   - 代理/网络连接问题
   - 图片/CDN 请求问题
4. 诊断结果不会输出完整 api_key。

使用方法：
1. 关闭 ComfyUI。
2. 覆盖 py/ 和 js/，或使用完整包替换插件目录。
3. 重启 ComfyUI，浏览器 Ctrl+F5。
4. G 站继续按原方式使用。
5. 要查 D 站时点击节点上的“D诊断”，复制报告发给我。

也可以直接打开：
http://127.0.0.1:8188/danbooru_gallery/diagnose_danbooru?tags=rating:general
