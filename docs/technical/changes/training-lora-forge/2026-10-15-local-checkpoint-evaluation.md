# 本机 Anima 检查点比较入口

日期：2026-10-15。

原角色专用评估脚本绑定固定目录、提示词及采样参数。新增 [evaluate_checkpoint_plan.py](../../../../snapshot/runtime/anima_lora_forge/tools/evaluate_checkpoint_plan.py)，读取仓外不可变计划，以 [Anima 模板](../../../../snapshot/runtime/character_lora_forge/templates/anima_current_api.json) 的底模、CLIP、VAE、采样及解码核心节点构造独立 API 闭包。正负提示词直接进入 CLIPTextEncode；仅去掉前端提示词、LoRA UI、种子转发及开关节点，不修改生产模板。

## 使用

在主仓选定 Python 执行；所有真实计划、权重和输出放仓外：

```text
python -X utf8 -B snapshot/runtime/anima_lora_forge/tools/evaluate_checkpoint_plan.py prepare --plan <absolute-external-plan.json>
python -X utf8 -B snapshot/runtime/anima_lora_forge/tools/evaluate_checkpoint_plan.py execute --evaluation-root <plan-output-root> --limit 1
python -X utf8 -B snapshot/runtime/anima_lora_forge/tools/evaluate_checkpoint_plan.py execute --evaluation-root <plan-output-root>
python -X utf8 -B snapshot/runtime/anima_lora_forge/tools/evaluate_checkpoint_plan.py cleanup --evaluation-root <plan-output-root>
```

`prepare` 不提交图像；`execute` 是明确的 GPU 执行入口，须处于用户授权的实测范围。先一张 smoke、目视确认有效后续跑剩余矩阵。`--limit` 表示本次最多新增多少张；已完成输出必须仍匹配保存哈希才可跳过。可继续等待已获得 prompt ID 的任务；请求结果不明时停止，由操作者核对 history，避免重复生图。

## 仓外计划契约

顶层 `schema_version: 1`，包含：

- `run_id`：唯一 ASCII 标识；`comfy_root`、`output_root`：绝对路径，后者为尚不存在的仓外新目录。
- `base_url`：默认 `http://127.0.0.1:8188`，只允许无鉴权的本机 HTTP 服务。
- `models`：`dit`、`text_encoder`、`vae`，各自具有绝对 `path`、`sha256` 和 API 枚举的 loader `name`。路径须与指定 ComfyUI 的 models 目录/名字一致；额外模型根暂不支持。
- `checkpoints`：列表，每项为 `id`、`step`、绝对 `path`、`sha256`。只读 safetensors 头部及文件哈希，不加载训练模型、optimizer/pickle 或 Torch。
- `prompts`：由 `prompt_id` 到 `{positive, negative?}` 的映射；顶层 `negative` 可作为缺省值。
- `sampling`：明确的 `width`、`height`、`steps`、`cfg`、`shift`、`sampler`、`scheduler`。
- `jobs`：明确列表，每项为唯一 `job_key`、`checkpoint_id`、`prompt_id`、`strength`、`seed`。工具不自行补充训练步数、强度或提示词。

相同 checkpoint、强度与 seed 的比较须使用相同模型、提示词及采样参数。生产采样器和云端原生 flow-matching 采样器应分开记录，不能把两者当作等价结果。

## 输入和输出边界

`prepare` 在任何 API 调用、输出创建或临时硬链接操作前解析绝对输出路径，拒绝其落在整个主源码仓库（含 docs、governance、snapshot/evidence）或 ComfyUI 运行目录内。仓库根同时从 Git 祖先与固定 snapshot/runtime 布局识别，Git 元数据缺失的源码副本仍受保护；相同名称前缀的仓外兄弟目录不因字符串前缀被误拒绝。

临时模型输入位于指定 ComfyUI 的 `models/loras/_temporary_anima_eval/<run_id>/`，来源权重不移动，`prepare_receipt.json` 逐个记录硬链接身份、大小、SHA 和用途。清理前要求队列空闲，核验目录只有记录文件且来源/哈希不变；不递归删除，不删除原权重及评估图。它不会写 LoRA 资料卡或改变默认工作流。

仓外评估根冻结计划、工具/模板身份、模型哈希、节点模式、队列快照和全部 graph；每任务保留 API request/response、history、采样前后 system_stats、复制后的原 PNG 及 SHA。返回图必须来自此次 SaveImage 子目录、具有预期文件名前缀和分辨率，复制后再核对 SHA。结果 manifest 只是执行证据；角色一致性、服装/配饰/风格响应仍须逐图目视核验，不能以任务完成或文件存在宣称成品发布。

## 验证和限制

CPU 安全测试覆盖整个源码仓库根及非 runtime 子目录在 API/创建前拒绝、名称前缀相同的仓外兄弟目录正常到达队列门禁、路径越界在 API/输出创建前拒绝、非空队列拒绝而不删除用户任务、结果不明的旧提交不重发、临时目录额外文件导致全部保留、意外输出路径不复制。真实 24 图计划的 schema、graph 闭包及当前节点必需输入已通过只读校验；工具自身不把该结果标为 GPU 画质验收。GPU 与人工视觉结论由本次运行的仓外收据另记。

2026-10-15 收紧输出边界发生在本机三个矩阵全部执行结束后。旧矩阵的准备回执保留当时 runner SHA、完整 graph 和原始结果，不回写为新源码身份；新运行须以新 runner SHA 准备。本次已执行矩阵的实际输出位于仓外，该边界修复不改变其输入或历史证据。

只支持当前 Anima 核心模板及本机 ComfyUI 的 models 目录。队列检查无法阻止另一客户端在检查后立刻提交；如出现其他任务，下一次提交停止，已有用户任务保持原状。异常中断留下的 `.execution.lock` 应先核对进程及 queue/history 后人工解除。模型和训练不能在同一 GPU 同时进行。
