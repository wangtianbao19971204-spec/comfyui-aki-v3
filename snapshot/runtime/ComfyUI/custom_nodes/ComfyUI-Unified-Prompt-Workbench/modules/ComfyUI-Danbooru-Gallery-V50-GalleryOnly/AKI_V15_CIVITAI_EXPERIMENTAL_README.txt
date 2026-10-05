AKI V15 Civitai experimental source

新增内容：
- Danbooru Gallery 来源下拉新增 Civitai。
- 后端接入 Civitai public Images API: https://civitai.com/api/v1/images
- Civitai 图片 URL 支持通过插件 image_proxy 预览。
- 选中 Civitai 图片时，selection_data 输出保留原始 meta.prompt；如有 negativePrompt，会追加为：Negative prompt: ...

搜索框支持的 Civitai 轻量语法：
- 空搜索：最新图片
- model:123        -> modelId=123
- version:123      -> modelVersionId=123
- post:123         -> postId=123
- user:name        -> username=name
- nsfw:true/false  -> Civitai nsfw 参数
- sort:Newest      -> Civitai sort 参数（也可尝试 Most Reactions / Most Comments）

限制：
- Civitai Images API 不等同 Danbooru/Gelbooru tag 搜索；普通词只会对当前 API 返回页做本地 prompt/tag 粗过滤。
- 这版暂不做 Civitai API Key UI；先验证公开预览和 prompt 抽取是否可用。
- 若 Civitai 图片 CDN 或 API 被网络拦截，请导出日志排查。
