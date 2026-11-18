# JoyCaption 显存腾退、磁盘卸载拦截与 ComfyUI 中断接入（2026-11-15）

## 问题与根因

在 UAP 实机测试完 `Krea2 生产` 生图后切换到「提示词反推 -> JoyCaption · 三路反推」时，后端队列长期停留在 `(5) ??%` 且点击「取消当前任务」/「停止当前运行」均无法终止执行。排查 `production.stderr.log` 与 `ComfyUI-Olm-JoyCaption/olm_joycaption.py` 确认两项叠加根因：

1. **未先回收 ComfyUI 驻留模型显存**：Krea2 UNet（BF16）与 Qwen3-VL 仍驻留在 32GB RTX 5090 D 显存中，`OlmJoyCaption._get_model_and_processor` 直接调用 `LlavaForConditionalGeneration.from_pretrained(..., device_map="auto")`（FP16 约 17.2GB），导致 `accelerate` 因剩余显存不足将大量层卸载到 CPU 与磁盘（`Some parameters are on the meta device because they were offloaded to the cpu and disk`），自回归逐 token 读写磁盘导致单次推理耗时数小时。
2. **`model.generate` 未接入 ComfyUI 中断信号**：推理循环未传入 `StoppingCriteria` 检查 `comfy.model_management.processing_interrupted()`，收到 `/api/interrupt` 后仍阻塞在生成循环中无法退出。

## 修改内容

- 修改 [olm_joycaption.py](../../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Olm-JoyCaption/olm_joycaption.py)：
  1. **加载前按精度检查并腾退显存**：CUDA 模式下按 `fp16`（18.5 GiB）/ `8bit`（10.5 GiB）/ `4bit`（7.0 GiB）检查 `comfy.model_management.get_free_memory`；不足时自动调用 `unload_all_models()` 与 `soft_empty_cache()` 腾出 GPU 显存。
  2. **磁盘卸载硬拦截**：若腾退后 `hf_device_map` 仍出现 `"disk"` 卸载（如外部进程占满显存与内存），立即释放半加载对象并抛出明确 `RuntimeError`，提示释放显存或开启 `load_4bit` / `load_8bit`，杜绝静默假死。
  3. **逐 Token 响应 ComfyUI 中断与安全清理**：在加载前后与生成前后调用 `throw_exception_if_processing_interrupted()`，向 `model.generate` 注入 `_ComfyInterruptCriteria` 逐步检查 `processing_interrupted()`，并在 `finally` 中保证 `unload_after=True` 正常清理模型缓存。
- 新增隔离回归测试 [test_olm_joycaption_vram_interrupt.py](../../../../tests/test_olm_joycaption_vram_interrupt.py)，无需 GPU 或重依赖即可覆盖低显存自动卸载、磁盘卸载拦截、逐歩中断退出与 `unload_after` 缓存回收。

## 验证与限制

- `python -m unittest discover -s tests -p "test_olm_joycaption_vram_interrupt.py"` 3 项用例全部通过；代码已同步备份并写回运行区 `ComfyUI/custom_nodes/ComfyUI-Olm-JoyCaption/olm_joycaption.py`。
- 因生产端口 `8188` 当前 Python 进程需重启后方能重载更新后的 `olm_joycaption.py`（此前已入队的单次磁盘卸载任务耗时 `53m15s` 后自然结束，队列现已归零），未在未经用户确认下擅自重启生产服务；下次常规重启后新显存腾退与逐 token 中断保护即正式生效。
