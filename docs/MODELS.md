# 模型与依赖维护

权重文件不放普通 Git，也没有擅自安装 Git LFS/DVC、搬动模型或重新下载。

权威清单：`snapshot/inventory/models.json`。工作流引用：`snapshot/inventory/workflow_models.json`。软件环境：`snapshot/inventory/environment.json`。

## 分层

- 生成底模：Anima 原版、Anima 2.9B、Krea2 等 diffusion_models/checkpoints。
- 配套组件：文本编码器、CLIP、VAE、模型 patch；必须匹配底模家族。
- LoRA：角色、姿势、修复、风格等；不能仅靠名字判断架构兼容。
- 检测与蒙版：YOLO、SAM、RMBG/PixAI 等；检测模型不是负责最终重绘的生成底模。
- 放大：OmniSR 等超分模型，以及工作流中的扩散二放参数。

原版 Anima LoRA/LLLite 不能直接当作 Anima 2.9B 的同架构权重；新模型或同名替换后需重新核对编码器、VAE 与静态家族约束。当前说明不构成任意 LoRA 的画质保证。

## 清单精度

首版记录现有权重的路径、大小、修改时间；**未对全部大模型计算内容 SHA-256**。`sha256: null` 不是验证成功。模型引用匹配是静态路径/文件名候选：`missing`、`ambiguous` 必须复核，历史工作流缺失依赖不能自动替换成相似模型。

后续新增或替换重要权重时，人工确认来源、版本、许可证和兼容性，再对目标文件计算 SHA-256，记录来源页/版本 ID。不要从命名推断量化方式、许可证或下载来源。带鉴权参数的下载 URL、Cookie 和 token 不能入库。

## 备份与迁移

完整另存 `ComfyUI/models`，包括模型相邻的 config/tokenizer/processor 文件；同样保留清单中生产插件内的权重。模型清单只定位文件，不能从清单还原权重。遇到目录链接或 extra_model_paths 的外部位置时必须单独记录并备份链接目标。

本轮不自动下载、不切换模型、不推理。迁移后先静态依赖检查，再用隔离中性样例逐模型冒烟；不要直接重跑带外部 API 或批量出图的正式工作流。
