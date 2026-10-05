AKI V31 - Civitai 全量 multi-search / images_v6 版

本版调整：
1. Civitai 普通文本搜索统一走网页真实图片搜索接口：
   https://search-new.civitai.com/multi-search
   indexUid = images_v6
2. strict / loose 不再切换到旧的 model-candidate 主搜索逻辑。
   - strict：multi-search 返回候选后，本地要求所有关键词命中 prompt/tagNames/model/user。
   - loose：multi-search 返回候选后，本地按命中分数排序。
3. 官方 /api/v1/images 仅保留两类用途：
   - 空搜索 / 最新页 fallback
   - 结构化直达查询（modelId / version / postId / username）
4. 远端收藏夹、提示词增强、Civitai.red 远端收藏浏览逻辑继续保留。

预期：
- sex 1girl / wet nude / 1girl blue_hair 这类普通搜索，不再依赖旧的模型候选池。
