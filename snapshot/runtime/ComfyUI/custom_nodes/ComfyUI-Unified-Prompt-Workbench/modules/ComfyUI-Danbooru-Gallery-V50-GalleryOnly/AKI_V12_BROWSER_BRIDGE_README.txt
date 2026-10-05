AKI V12 - Danbooru Browser Bridge / D站浏览器桥接

目的：
- 当普通 Python requests / curl_cffi 请求 Danbooru 被 Cloudflare challenge 拦截，但真实浏览器可以打开 Danbooru 时，可以让 ComfyUI 后端连接本机 Chrome/Edge 的 CDP 调试端口，通过真实浏览器读取 posts.json。
- 该功能默认关闭，不影响 Gelbooru/G站。

前提：
1. ComfyUI 的 Python 环境安装 Playwright：
   Portable 示例：
     .\python_embeded\python.exe -m pip install -U playwright
   venv/conda 示例：
     python -m pip install -U playwright

2. 启动一个专用 Chrome 调试配置。建议不要用日常默认配置，使用单独 user-data-dir。
   Windows Chrome 示例：
     start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\danbooru-bridge-profile" --proxy-server="http://127.0.0.1:10081" https://danbooru.donmai.us/posts.json?limit=1

   Windows Edge 示例：
     start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\danbooru-bridge-profile" --proxy-server="http://127.0.0.1:10081" https://danbooru.donmai.us/posts.json?limit=1

3. 在这个浏览器窗口里完成 Danbooru / Cloudflare 验证。
   地址栏打开：
     https://danbooru.donmai.us/posts.json?limit=1
   目标是页面直接显示 JSON 数组。不是 Just a moment，也不是 HTML。

插件设置：
- 齿轮 -> 用户 -> Danbooru 浏览器桥接（实验）
- cdp_url 默认：http://127.0.0.1:9222
- 启用“浏览器桥接 fallback”后，普通 D站请求失败时会自动尝试桥接。
- 勾选“优先使用浏览器桥接”后，D站 posts.json 会先走桥接，不先等 Python 请求失败。

诊断：
- 设置里点“测试浏览器桥接”可以单独测试。
- 点主界面的 D诊断时，如果桥接已启用，报告会出现 posts_search_browser_bridge。
- 成功标志：category=ok_json。

注意：
- 浏览器桥接不是绕过 Cloudflare。它只是复用你本机真实浏览器已经通过验证的会话。
- 如果专用浏览器地址栏打开 posts.json 都还是 Cloudflare challenge，则桥接也不会成功；需要换代理出口或先通过验证。
- 不要把 API key / Cookie / cf_clearance 发给别人。
