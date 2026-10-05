# 大模型与预览：Git 只留样例、位置和清单

本仓库用于代码、工作流、提示词内容与维护记录。模型权重、真实预览、生成图、插件下载缓存、Python/CUDA 环境和凭证不进普通 Git；也不把这些文件伪装成分片代码上传。现有模型/媒体清单继续保留，但**清单不是权重或图片备份**。

仓库唯一视觉占位样例在 [`examples/external-assets/preview.example.svg`](../examples/external-assets/preview.example.svg)，是自行绘制的中性 SVG，不读取真实图库。登记格式见 [`asset-record.example.json`](../examples/external-assets/asset-record.example.json)，机器可读的目录表见 [`locations.json`](../examples/external-assets/locations.json)。没有制造假的 `.safetensors`、`.pt`、`.gguf` 或能被加载器误认的空模型文件。

## 路径怎么理解

下文 `ComfyUI/...` 均相对**运行根**，不是仓库的 `snapshot/` 根，也不是某台机器的盘符。离线还原生成运行目录后，才把外部文件放到对应位置；不要把权重复制到 `snapshot/runtime/` 后强制加入 Git。

| 资源 | 放置位置（相对运行根） | 配套要求 |
|---|---|---|
| 底模/UNet | `ComfyUI/models/diffusion_models/` | 保留 Anima、Anima-2.9B、krea2 等家族子目录；匹配工作流引用 |
| 整合 checkpoint | `ComfyUI/models/checkpoints/` | 按具体加载器选择，不能将所有检测模型塞进同一目录 |
| 文本编码器 / VAE | `ComfyUI/models/text_encoders/`、`ComfyUI/models/vae/` | 必须匹配生成架构，不只凭文件名判断 |
| LoRA / 控制 / IP-Adapter | `ComfyUI/models/loras/`、`controlnet/`、`ipadapter/` | 保留家族与子目录；图像编码器另在 `clip_vision/` |
| YOLO bbox / segm | `ComfyUI/models/ultralytics/bbox/`、`segm/` | 检测与分割文件不能互换；精确文件名见模型清单 |
| SAM / RMBG / BiRefNet | 当前清单中的 `sams/`、`checkpoints/`、`sam3dbody/`、`RMBG/` 或 `birefnet/` | 不同插件的加载路径不同，按已使用节点核对，不能统一搬家 |
| PixAI Tagger | `ComfyUI/models/taggers/pixai-tagger-v1.0/` | 当前加载器至少检查 `model.safetensors`、`config.json`、`preprocessor_config.json`、`tagger_pipeline.py` |
| 超分 / 本地语言模型 | `ComfyUI/models/upscale_models/`、`ComfyUI/models/LLM/` | 视觉 GGUF 需要同版本兼容的 mmproj；超分与扩散二放是不同资源 |
| 插件内模型 | 例如 `ComfyUI/custom_nodes/comfyui_controlnet_aux/ckpts/`、`comfyui-kjnodes/intrinsic_loras/` | 不止 models 总目录；保留 inventory 中的完整嵌套路径 |

权威列表：`snapshot/inventory/models.json`；工作流引用检查：`snapshot/inventory/workflow_models.json`。清单的 `sha256: null` 表示尚未计算，不是已验真。新获取/替换的关键资源应记录确切版本、无鉴权来源页、许可、字节数和实际 SHA-256。不要将签名下载链接、查询参数内令牌或账户信息保存到公开说明。

特殊格式的补充放置契约见 [runtime-support.json](../governance/runtime-support.json)：T5/ChatGLM 的 `.model` 分词文件、DensePose `.torchscript`、MediaPipe `.task`，以及 MANO/网格的 `.pkl`、`.npy`、`.npz`。它们没有伪装成源码上传；恢复时保留完整相对目录并核对配套版本。`.pkl` 等只作文件指纹登记，不为清点而反序列化。MANO 等资源仍受自己的许可限制，不随 GitHub 仓库自动分发。

目录型模型需要**同一版本的完整目录**，包括存在的 config、tokenizer、vocab/merges、processor/preprocessor、标签映射、分片 index 与全部权重 shard。自定义模型代码需人工审查并记录来源，不因文件小就自动可信；不从其他版本拼凑。除加载器明确支持单文件形式外，不能只保留 `model.safetensors`。`extra_model_paths` 或目录链接引用的外盘路径由使用者本地配置，不把本机用户名/私有绝对目录写成公共默认值。

## 提示词预览放置与绑定

共同父路径：

`ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/prompt_selector/`

- `preview/`：原图，保留实际 PNG/JPEG/WebP 等位图格式、原始文件名与提示词记录的引用。
- `preview_thumbnails/`：对应缩略图；可另行备份，或通过匹配版本的应用有控制地重建。不要随意改名推断绑定。

原图/缩略图共 191,791 个文件、23,339,796,621 字节（首版清单统计，非永远不变）。真实媒体另行备份；Git 中只有路径/大小/时间清单，不含媒体 payload，也没有逐图内容哈希。SVG 样例只演示版式，**不保证生产加载器支持 SVG**，不能直接替换已绑定的真实文件。

## GitHub 之前

真实提示词内容按用户决定保留；示例、库结构和代码同在一个主仓库。所有可达提交和引用都须扫描凭证，尤其旧插件缓存、设置、日志、下载 URL 和 `.env`。大资源目录及其缓存继续忽略；不能用 `git add -f` 绕过资源/凭证边界。模型/媒体是否可以外部分发还受各自许可约束，登记不构成再分发授权。

本页只定义放置规范与示例，不会自动下载、迁移、启用任何模型或运行工作流。
