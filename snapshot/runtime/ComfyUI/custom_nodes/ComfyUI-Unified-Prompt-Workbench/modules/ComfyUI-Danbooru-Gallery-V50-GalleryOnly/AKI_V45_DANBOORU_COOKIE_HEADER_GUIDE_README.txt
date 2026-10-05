AKI V45 - Danbooru Cookie / Browser Headers 引导文案增强

本版本只做引导文案和入口调整，不改动主要抓取逻辑。

修改内容：
1. Danbooru Cookie fallback 的说明改成可照着操作的步骤：
   - 打开 https://danbooru.donmai.us/posts.json?limit=1
   - F12 -> Application -> Storage -> Cookies -> https://danbooru.donmai.us
   - 找到 cf_clearance，复制 Value
   - 在 Cookie fallback 输入框填写 cf_clearance=复制到的值

2. Danbooru 浏览器请求头模式的说明改成可照着操作的步骤：
   - 打开 posts.json?limit=1 并确认显示 JSON
   - F12 -> Network -> 刷新页面
   - 点击 posts.json?limit=1 请求
   - 右键请求 -> Copy -> Copy as cURL (bash)
   - 整段粘贴到浏览器请求头输入框
   - 保存后检查状态：Cookie=有、cf_clearance=有、UA=有

3. 设置页里的“打开 Danbooru”按钮改为直接打开 posts.json?limit=1 验证页。

说明：
- Cookie fallback 仍然是手动 Cookie 模式。
- 浏览器请求头模式可以避免手动拆出 cf_clearance；直接粘贴 Copy as cURL 即可。
- 完全自动读取 Chrome 的 cf_clearance 仍不建议做：ComfyUI 页面不能安全读取另一个站点的 Cookie，HttpOnly Cookie 也不能被普通网页脚本读取。需要自动复用浏览器会话时，应使用已有的浏览器桥接/CDP方案，而不是从网页端偷取 Cookie。
