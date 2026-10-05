AKI V17 - Civitai.red 检索重构版

目标：让 C站不再只是“拉一页 images 后本地过滤”，而是更接近可用图库搜索。

主要变更：
1. 默认继续使用 https://civitai.red，civitai.com 作为 fallback。
2. Civitai 普通搜索词现在优先走：
   - /api/v1/tags?query=...
   - /api/v1/models?tag=...
   - /api/v1/models?query=...
   然后用发现的 modelId 去 /api/v1/images 拉模型图库。
3. Images 最新页只作为本地 prompt/resource/username 过滤兜底。
4. 支持结构化搜索：
   model:123
   version:123
   post:123
   user:name
   tag:1girl
   sfw / nsfw / any
   nsfw:true / nsfw:false / nsfw:any
   sort:Newest / sort:Most_Reactions / sort:Most_Comments
   period:Day / Week / Month / Year / AllTime
5. 分页优先使用 nextCursor；没有 cursor 时回退 page。
6. 新增 C诊断按钮，输出 red/com API、Tags/Models/Images 检索计划、实际返回数量和 debug 信息。
7. 设置页新增 Civitai API Key（可选）。匿名也可用，API Key 仅用于更高限制或账号可见内容。
8. 选中 Civitai 图片后的输出增强：prompt、negative、model、model version、seed、sampler、steps、CFG、creator、image URL。

注意：
- Civitai Images API 本身没有真正的 prompt/tag 搜索参数。v17 是用 Tags/Models API 做检索增强。
- 如果 tag/model 查询结果不理想，C诊断可以显示具体是 red 失败、com fallback、模型发现为空，还是本地过滤过严。
