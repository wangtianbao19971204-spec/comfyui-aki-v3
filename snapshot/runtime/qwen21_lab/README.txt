Qwen-Image 2.1 UC BF16 本地测试实例

访问：http://127.0.0.1:8189
启动：运行 start.ps1；停止：运行 stop.ps1；卸载空闲模型：运行 unload.ps1。
三个操作仅针对 8189 独立实例。主 ComfyUI 仍为 8188。

左侧“工作流”中：
- Qwen21_UC_BF16_background：人物去背景，alpha 通道转为 MASK。
- Qwen21_UC_BF16_hands：双手黑白蒙版，red 通道转为 MASK。
- Qwen21_UC_BF16_coat_mask：外套蒙版，alpha 通道转为 MASK。

LoadImage 可更换图片；TextEncodeQwenImage21 可改指令和 resolution。
默认单图、resolution=512（按原图比例得到 576×448）、25 步、CFG=1、Euler/simple。
节点“Convert Image to Mask”提供原生 MASK 输出，可用于后续通用蒙版处理。
蒙版通道设置来自本轮实测；更换任务后应核对是否有有效 alpha，不能假定所有输出格式相同。

主模型：abenzerps/Qwen-Image-2.1-Uncensored-GGUF，qwen-image-2.1-UC-BF16.gguf。
编码器：qwen3vl_8b_bf16.safetensors；VAE：qwen_image_2.1_vae_bf16.safetensors。
主模型、编码器与 VAE 均为 BF16；未下载 INT8 替代权重。
GGUF 在这里是文件容器；该主模型的全部 297 个权重张量报告为 BF16。
三份权重位于原 ComfyUI/models 目录，独立实例只读取它们。
新 ComfyUI 和依赖放在 qwen21_lab 内；原 Python 包和生产核心未升级。

实测仅使用一张完全着装的人物样图，不代表所有物体、图像风格或部位的可靠性。
人物去背景、双手蒙版、外套蒙版成功；直接要求“只提取外套”为透明图时却返回整个人物。
因此可作为指令式蒙版候选，不是已经验证的 YOLO+SAM 完整替代：没有直接输出类别置信度和独立实例列表，且结果依赖指令和输出通道。
BF16 单次约 25–27 秒，峰值总显存约 30 GiB，系统内存曾短暂接近耗尽。验证后已请求卸载模型。

本轮证据：../benchmark_reports/2026-10-04_qwen21_instruct_deployment/
主要文件：model_manifest.json、models_verified.json、runs/、segmentation_comparison.png、FINAL_DELIVERY.json。
