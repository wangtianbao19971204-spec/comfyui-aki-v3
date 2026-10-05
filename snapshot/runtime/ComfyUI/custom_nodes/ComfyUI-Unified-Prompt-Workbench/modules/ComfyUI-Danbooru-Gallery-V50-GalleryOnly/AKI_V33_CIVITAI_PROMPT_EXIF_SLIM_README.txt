AKI V33 - Civitai 收藏夹提示词瘦身修复

修复：
1. 收藏夹图片 metadata / EXIF 中包含整个 ComfyUI workflow 时，不再把整段 JSON 当 prompt 输出。
2. 优先从 extraMetadata.prompt / extraMetadata.negativePrompt 提取干净提示词。
3. 如果是 ComfyUI workflow，则只提取 _meta.title 为 Positive / Negative 的 CLIPTextEncode inputs.text。
4. 继续忽略 JFIF/DPI/ICC 等技术元数据。
5. multi-search/images_v6 仍作为 Civitai 普通搜索主路径。
