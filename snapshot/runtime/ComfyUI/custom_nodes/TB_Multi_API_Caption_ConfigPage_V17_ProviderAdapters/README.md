# TB Multi API Caption · 多供应商视觉适配版 V17

这是 V16 的兼容升级版。它保留原有节点类 ID、前端事件名和配置页面路径，因此现有工作流不需要重新接线。

## V17 主要变化

1. 增加真正的 Provider 协议适配层：
   - `openai_chat`
   - `openai_responses`
   - `anthropic_messages`
   - `gemini_generate_content`
2. 图片不再固定保存为原尺寸 PNG：
   - 默认按比例限制长边到 1536
   - 默认转换为 JPEG，质量 92
   - 默认限制编码后图片为 6,000,000 字节
   - 超限时自动降低质量并按比例缩小
3. 支持 `image_first` 和 `text_first`。
4. 支持按模型正则表达式覆盖 Provider 配置。
5. 模型明确回复“没有收到图片”时，状态会标记为 `NOIMG`，不会混入 `successful_results`。
6. `debug_json` 会显示：
   - `protocol`
   - `request_url`
   - `http_status`
   - `image_order`
   - 原始尺寸与发送尺寸
   - MIME 类型
   - 编码格式、质量、字节数和 Base64 字符数
7. Judge 节点的纯文本请求也支持四种协议，不再只支持 OpenAI-compatible。
8. 配置页可以直接编辑协议和图片参数。

## 安装

1. 关闭 ComfyUI。
2. 把旧版本插件文件夹移出 `custom_nodes`，避免同时加载两个相同节点类 ID。
3. 解压本插件文件夹到：

   ```text
   ComfyUI/custom_nodes/TB_Multi_API_Caption_ConfigPage_V17
   ```

4. 启动 ComfyUI。
5. 浏览器执行 `Ctrl+F5` 强制刷新。
6. 旧工作流中的 `TB_Multi_API_Caption_SmartRunner_V16` 会继续正常加载，但显示名称会变成 V17。

配置页面仍为：

```text
http://127.0.0.1:8188/tb_multi_api_caption_v16/config
```

路径保留 `v16` 是为了兼容现有前端代码和旧书签。

## 最重要的配置规则

协议由你调用的 **API 入口** 决定，不由模型名称决定。

例如，中转站同时提供 Claude、Gemini、Grok 模型，但请求地址是：

```text
https://example.com/v1/chat/completions
```

那么必须使用：

```json
{
  "protocol": "openai_chat"
}
```

不能因为模型名包含 `claude` 就改成 `anthropic_messages`。只有直接调用 Anthropic `/v1/messages` 时，才使用 Anthropic 原生协议。

## 当前 qiny 配置

插件已将现有 qiny Provider 调整为：

```json
{
  "type": "openai_compatible",
  "protocol": "openai_chat",
  "base_url": "https://love.qinyan.icu/v1",
  "path": "/chat/completions",
  "image_order": "image_first",
  "image_format": "jpeg",
  "max_image_side": 1536,
  "jpeg_quality": 92,
  "max_image_bytes": 6000000,
  "max_tokens_field": "max_tokens",
  "supports_vision": true,
  "fail_on_missing_image": true
}
```

这会把 OpenAI-compatible 图片块放在文字块之前，降低某些中转转换器只读取第一个内容块的概率。

## Provider 配置字段

### `protocol`

可选值：

| 值 | 用途 |
|---|---|
| `openai_chat` | OpenAI Chat Completions、中转站、兼容 `/chat/completions` 的接口 |
| `openai_responses` | OpenAI Responses API 或兼容 `/responses` 的接口 |
| `anthropic_messages` | Anthropic 原生 `/v1/messages` |
| `gemini_generate_content` | Google Gemini 原生 `generateContent` |

旧值 `openai_compatible` 会自动映射为 `openai_chat`。

### 图片参数

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `image_order` | `image_first` | `image_first` 或 `text_first` |
| `image_format` | `jpeg` | `jpeg`、`png`、`webp` 或 `auto` |
| `max_image_side` | `1536` | 发送前长边限制；`0` 表示不限制 |
| `jpeg_quality` | `92` | JPEG/WebP 质量，范围 20–100 |
| `max_image_bytes` | `6000000` | 编码后图片大小限制；`0` 表示不限制 |
| `image_detail` | 空 | OpenAI 类接口可设置 `auto`、`low` 或 `high` |
| `supports_vision` | `true` | 设为 `false` 时直接阻止给该模型发送图片 |
| `fail_on_missing_image` | `true` | 模型声称未收到图片时标记为 `NOIMG` |

### `model_overrides`

用于同一个 Provider 下按模型名称覆盖参数。`match` 是不区分大小写的正则表达式，第一条匹配规则生效。

```json
[
  {
    "match": "claude",
    "set": {
      "image_order": "image_first"
    }
  },
  {
    "match": "known-text-only-model",
    "set": {
      "supports_vision": false
    }
  }
]
```

同一个 `/chat/completions` 中转站下，通常只覆盖图片顺序、尺寸或格式，不要随意覆盖 `protocol`。

## 原生 Provider 示例

### Anthropic 原生

```json
{
  "name": "anthropic-direct",
  "type": "anthropic",
  "protocol": "anthropic_messages",
  "base_url": "https://api.anthropic.com/v1",
  "path": "/messages",
  "models_endpoint": "/models",
  "api_key": "env:ANTHROPIC_API_KEY",
  "models": [
    "你的 Claude 模型 ID"
  ],
  "image_order": "image_first",
  "image_format": "jpeg",
  "max_image_side": 1536,
  "jpeg_quality": 92,
  "max_image_bytes": 5000000,
  "supports_vision": true,
  "fail_on_missing_image": true,
  "headers": {},
  "extra_payload": {}
}
```

发送的图片块格式为：

```json
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/jpeg",
    "data": "..."
  }
}
```

### Gemini 原生

```json
{
  "name": "gemini-direct",
  "type": "gemini",
  "protocol": "gemini_generate_content",
  "base_url": "https://generativelanguage.googleapis.com/v1beta",
  "path": "/models/{model}:generateContent",
  "models_endpoint": "/models",
  "api_key": "env:GEMINI_API_KEY",
  "models": [
    "你的 Gemini 模型 ID"
  ],
  "image_order": "text_first",
  "image_format": "jpeg",
  "max_image_side": 1536,
  "jpeg_quality": 92,
  "max_image_bytes": 6000000,
  "supports_vision": true,
  "fail_on_missing_image": true,
  "headers": {},
  "extra_payload": {}
}
```

发送的图片块格式为：

```json
{
  "inlineData": {
    "mimeType": "image/jpeg",
    "data": "..."
  }
}
```

### OpenAI Responses

```json
{
  "name": "openai-responses",
  "type": "openai",
  "protocol": "openai_responses",
  "base_url": "https://api.openai.com/v1",
  "path": "/responses",
  "models_endpoint": "/models",
  "api_key": "env:OPENAI_API_KEY",
  "models": [
    "你的视觉模型 ID"
  ],
  "image_order": "image_first",
  "image_format": "jpeg",
  "max_image_side": 1536,
  "jpeg_quality": 92,
  "max_image_bytes": 6000000,
  "supports_vision": true,
  "fail_on_missing_image": true,
  "headers": {},
  "extra_payload": {}
}
```

发送的图片块类型为 `input_image`。

## 如何判断图片在哪一层丢失

运行后查看 `debug_json` 对应模型：

```json
{
  "protocol": "openai_chat",
  "http_status": 200,
  "request_url": "https://.../chat/completions",
  "image_order": "image_first",
  "image": {
    "mime_type": "image/jpeg",
    "byte_size": 248135,
    "base64_chars": 330848,
    "width": 1024,
    "height": 1536,
    "original_width": 2048,
    "original_height": 3072
  }
}
```

如果这里有完整的 `image` 信息并且 HTTP 为 200，但模型仍返回 `NOIMG`，说明：

1. 插件已经完成图片编码；
2. 请求已经到达中转服务；
3. 更可能是中转服务在向实际模型转换协议时丢失了图片，或者该模型路由没有视觉能力。

客户端无法把 Anthropic/Gemini 原生请求体发送到仅支持 `/chat/completions` 的中转入口来绕过这一层。

## 安全说明

配置页支持明文 API Key，但推荐使用环境变量：

```json
{
  "api_key": "env:QINY_API_KEY"
}
```

Windows 启动前可设置：

```bat
set QINY_API_KEY=你的密钥
```

或者在 ComfyUI 启动脚本中设置后再启动 Python。
