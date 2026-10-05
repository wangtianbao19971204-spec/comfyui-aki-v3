# V52：Civitai 收藏 Tags 加速与重复提示修复

## 修复的问题

V51 已能解析 Civitai 收藏图片的 prompt/Tags，但存在两个体验问题：

1. 第一次解析偏慢。
2. 鼠标经过、点击选中、导出或界面重新渲染时，可能重复解析同一张图片，并连续显示：
   - `C站提示词/Tags已解析：structured_keys`
   - `C站提示词/Tags已解析：trpc_generation_data`

## 原因

V51 的收藏详情链路按以下顺序尝试：

1. REST `imageId`
2. REST `postId`
3. tRPC `image.getGenerationData`
4. tRPC `tag.getVotableTags`
5. 下载图片读取内嵌元数据

收藏列表来自 `image.getInfinite`，通常已经带有真实图片 ID，但缺少生成元数据。对收藏图片先尝试 REST 没有必要，并可能先等待一到两个超时。

前端方面，悬停 Tooltip、点击选择和导出会分别调用详情解析；界面重绘后还会产生新的 JavaScript 对象，旧的对象级标记无法阻止重复请求。

## V52 改动

### 后端

- 收藏图片携带 `favorite=1` 时，优先调用 `image.getGenerationData`。
- 如果 generation data 已包含 prompt/Tags，立即返回，不再无条件等待 `tag.getVotableTags`。
- 只有 generation data 不足时才继续请求 `tag.getVotableTags`。
- REST 和图片元数据下载改为后续兜底。
- 远程解析放入工作线程，避免同步 `requests` 阻塞 ComfyUI HTTP 事件循环。
- 按真实 Civitai 图片 ID 建立进程级缓存：
  - 成功结果缓存 6 小时。
  - 失败结果缓存 60 秒。
  - 最大 512 条，超过后清理最早的一部分。
- 同一图片的并发请求共享一个后台任务。

### 前端

- 按真实图片 ID 建立页面级结果缓存。
- 悬停、点击和导出对同一图片共享一个 Promise。
- Tooltip 增加 180ms 停留判断；鼠标只是快速划过图片时不发送请求。
- 后台自动解析成功或未找到 prompt 时不再显示 Toast。
- 用户主动复制、收藏、导入导出设置等操作的原有 Toast 不受影响。

## 安装

### 使用补丁

关闭 ComfyUI，覆盖：

```text
py/danbooru_gallery/danbooru_gallery.py
js/danbooru_gallery/danbooru_gallery.js
```

然后重启 ComfyUI，并在浏览器按 `Ctrl + F5`。

### 使用完整包

移走旧图库版本，只保留一个 Gallery 插件目录，再解压 V52 完整包到 `custom_nodes`。

WeiLin V52 FullPromptSelector 不需要修改。
