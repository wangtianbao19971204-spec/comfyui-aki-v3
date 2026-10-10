# GPU 点选与深度计算

日期：2026-10-10。

用户反馈在图片上点选袜子区域后等待很久。旧 `studio_models.py` 每次点击都在 CPU 新建 SAM、读取权重、重新编码整图；后台深度还共用同一把锁。

## 实现与边界

- SAM 和 Depth Anything V2 Small 优先使用 ComfyUI 配置的 CUDA 设备；保留 `--cpu`。纹理渲染器、模型版本、图像预处理、三档候选排序和工作流 schema 不变。
- CPU 内存最多保留一份 SAM、一份深度模型/处理器，以及四份 SAM 特征（ViT-B 合计约 16 MiB）。缓存键包含权重路径、大小、修改时间以及图像内容、尺寸、类型和执行设备；换模型清空对应特征，不同图片不串用选区。
- SAM、深度各自串行；GPU 推理另行互斥。模型载入和深度预处理在取得 GPU 使用权前进行。仅在队列空闲时持有 ComfyUI `PromptQueue.mutex` 完成短时 GPU 推理，防止工作线程在推理中启动新任务。期间队列状态/提交可能短暂等待。已有排队/执行任务、队列锁忙、空闲显存小于 3 GiB 加 ComfyUI 保留量时改用 CPU；CPU 推理不占 GPU/队列锁。
- GPU 不卸载 ComfyUI 模型，不调用其全局模型加载/释放逻辑。成功、异常或 OOM 后均将本模型移回 CPU；OOM 在释放 GPU/队列锁后重试 CPU，其他错误照常报告。CUDA allocator 可保留可复用内存，cuBLAS 也有少量工作区，这不等于模型常驻显存。
- GPU 使用 FP32 并在持有使用权期间临时关闭 TF32/自动混合精度，结束恢复原标志。首次 TF32 对照的深度边缘误差超阈值，未作为验收结果。
- `sam.inference`、`depth_inference` 返回实际设备、CPU 回退原因、缓存命中和耗时；编辑器设备文字与深度提示同步更新。状态不写入工作流。

## 验证

当前 RTX 5090 D / Torch 2.9.1+cu130，三个既有真实夹具、七个坐标，对比本分支之前的 CPU 源码。离线时间仅为推理入口耗时，含模型/缓存开销；不能当成浏览器总耗时。

| 检查 | 结果 |
| --- | --- |
| 原 CPU 每次 SAM 点选 | 3.07–4.62 秒 |
| GPU 首次 SAM 点选 | 0.96–1.12 秒 |
| GPU 同图后续 SAM 点选 | 0.11–0.13 秒 |
| CPU 缓存命中后点选 | 0.031–0.042 秒 |
| 隔离 ComfyUI 点选 HTTP | 首次 2.60 秒；后续 0.30–1.10 秒；含线程、文档更新开销 |
| GPU 深度，模型已缓存 | 0.10–0.27 秒 |
| CPU 回退与旧版 | SAM、分数、深度逐元素相同 |
| GPU 与 CPU 选区 | 最低 IoU 0.999970；单个候选最多 26 个边缘像素不同；非逐像素相同 |
| GPU 与 CPU 深度 | 最大绝对误差 3.231e-5；最大误差/该图深度范围 < 6.561e-6 |
| 深度替换后的完整成品 | 黑袜交叉腿：油光逐像素相同；摩尔纹 2073600 像素中 33 像素相差 1 色阶 |
| 模型/特征显存 | 每次推理后参数、buffer、缓存均在 CPU；重复点击分配量不增长。独立进程清除 cuBLAS 工作区后存活 CUDA 张量为 0 |
| ComfyUI 调度 | 隔离实例执行真实纹理节点期间点选回退 CPU，队列完成后再用 GPU；未跑扩散模型。繁忙 CPU 回退实测 9.33 秒，不能保证队列忙时即时响应 |
| 编辑器流程 | 真实模型 HTTP 点选、候选切换、撤销重做、后台深度并行、应用确认、重开数据一致通过 |

[推理合同](../../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/test_studio_models.py)覆盖缓存失效/上限、CPU 配置、GPU 协调、低显存、OOM/异常释放、本地模型加载与精度标志恢复；全插件共 55 项 Python 测试通过，前端 17 项通过。新增 [真实模型对照工具](../../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/gpu_acceptance.py)和 [隔离 HTTP 工具](../../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Stocking-Texture/tests/gpu_http_acceptance.py)。摘要与证据哈希见[收据](../../../receipts/stocking_gpu_selection_20261010.json)。图片、模型、完整项目和输出都保留仓外。

## 限制与发布

原生 Chrome 工具无法可靠识别当前网址并停止控制，所以本轮没有浏览器实点验收；API 成功不替代页面验收。显存不足/OOM 使用故障注入测试，未刻意占满真实显卡。只验证上述显卡和夹具，不承诺所有设备/图片的速度或位级一致性。

本次改动未部署生产。部署范围是 `studio_models.py`、`studio.py`、`studio_api.py`、`studio_assets.py`；无需迁移数据库、替换权重或改工作流。回滚恢复这四个文件的发布前版本并按既有服务流程重启；原 CPU 行为随之恢复。合并/部署另遵守主仓门禁和用户授权。
