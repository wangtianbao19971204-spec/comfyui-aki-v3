AKI V39 - Civitai loose 按钮 + prompt source 修复

本版改动：
1. Civitai 工具栏新增“严格/宽松”切换按钮。
   - 默认严格：多关键词按 exact AND 过滤。
   - 点击“宽松”：不修改搜索框内容，发请求时自动加 mode:loose。
2. Civitai 前端搜索不再套用 Danbooru 的空格转下划线逻辑。
   - 2girls sex 会按原样发送给 Civitai 后端。
3. 修复 prompt source 空命中。
   - 不再出现 Prompt source: api_nested 但实际 prompt 为空的假命中。
   - 只有抽到真实 prompt/negativePrompt 才标记来源。
4. 保留 v36+ 的 Civitai 收藏 Cookie / multi-search Authorization 分离设置与导出备份。
