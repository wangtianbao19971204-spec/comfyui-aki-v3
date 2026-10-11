# Anima 2.9B LoRA 运行时兼容

文档修订：2026-10-05.3；状态：已收到独立功能任务的部署、固定参数 A/B 与工作流强度判定交接。


2026-10-11 源码候选更新：统一 [LoRA/ControlNet 补丁](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-LoRA-ControlNet-Patch/README.md)锁定 `b25ae637102f2358116fe419a409f0594f61245b`，8 份上游原件摘要见 `UPSTREAM.json`，未改上游代码。production / diagnostic / anima 白名单以统一补丁替代旧 LoRA-only 补丁，旧源码保留但不叠加加载。新增 [原生加载器](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-LLLite/native_loader.py)直接读取现有 controlnet 目录，输出 MODEL_PATCH；只有原生 AnimaLLLiteApply 能获得 ControlNet 映射，旧 sdscripts 节点保留给原版流程。

真实 any-v2 权重在 CPU 上完成 40 个区块逐项精确路由检查：28 个继承块应用对应模块，12 个新增块原样透传；原生 40-block LoRA 不再次转换，禁用补丁及非列表路径被加载器拒绝。工具为 [anima_control_cpu_acceptance.py](../../../scripts/anima_control_cpu_acceptance.py)，须显式给出权重目录和全新收据路径；它不采样，ComfyUI 的注意力能力探测仍可能初始化 CUDA。本轮 Torch GPU 分配为 0。

**以上是未部署候选，不能借用 10 月 5 日旧补丁的 GPU A/B 证明新控制链画质。** 上游还支持其他层数/方向，本轮只验收 28→40 的 2.9B 用例。禁用变量改为 `ANIMA_COMPAT_LORA_REMAP` / `ANIMA_COMPAT_CONTROLNET_REMAP`；旧 `ANIMA_LORA_REMAP` 不控制新补丁。回滚必须成组恢复白名单、节点源码和四份工作流，不能只关新补丁后继续执行新控制图。详情见 [简化变更](../changes/runtime-workflows/2026-10-11-anima-control.md)与 [收据](../../receipts/anima_control_simple_20261011.json)。

## 当前功能来源

独立任务“探索 Anima 2.9B LoRA Patch”在本轮整理期间，按用户请求将原版 28-block LoRA 的层映射适配到 40-block Anima 2.9B。其新增源码/配置与运行部署，不属于旧 `f1e61294` 冻结包；不能用旧包 PASS 宣称新补丁已验收。

接手入口为 [补丁实现](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-2.9B-loraPatch/__init__.py)、[上游说明](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-2.9B-loraPatch/README.md)、[profiles.json](../../../snapshot/runtime/production_tools/profiles.json)与 [部署/验收收据](../../receipts/anima29_lorapatch_20261005.json)。7 份上游文件锁定提交 `045f240210b52037e6dd3d8328d776463fe54b96`；仅 production / diagnostic / anima 三档加入白名单。没有另建第二个 Git。

## 技术边界

运行时 remap 与文件转换、模型 block 检测补丁是不同方案。对齐只改变正确层位置，不保证原版与 2.9B 输出相同；原生 40-block LoRA 不应再次按原版转换。同一 LoRA 不要同时叠加原始文件、转换文件和重复转换逻辑。

稀疏训练、非标准键命名和部分 block LoRA 需要额外核对，不凭文件名推断架构。用户此次范围仅 2.9B，未扩展到 3.8B。

## 验证与回滚

应有代码与部署 SHA、模型/LoRA 结构检查、固定 prompt/seed 的对照和禁用恢复方式。透明启动补丁可能改变所有既有 2.9B 输出，界面没有新节点不等于没有运行影响。

独立任务记录了同 seed、采样参数下的开启/关闭/无 LoRA 以及 0.7 强度拆解对照；这证明选定样本的运行时重映射生效，不证明所有 LoRA 的质量或任意叠加都合适。原生 40-block LoRA 透传与非标准稀疏键边界仍需逐模型检查。

整理任务于 2026-10-05 独立复核上述 7 文件和 profiles 的源码/部署哈希一致、工作台 ready、队列空；补全清单中的限定部署证据。收据里原有 open_items 是交接时状态；共享清单、文档及 Git 提交由后续维护版本承接。回滚前先核对当前服务与收据备份，不能直接执行旧 PID 操作。

## 工作流强度判定

推荐流 `Anima_推荐版_*` 的 `[02]` 子图内嵌四条 LoRA，强度均为 1.0（`remielle-dan-zzz-anima-Tanger`、`anima_vagina_detail_v1`、`HighHeel_SoundingANIMA`、`NikkeB1`）。补丁上线后需要判断这些值是否过量。

实测结论是**不需要调整**：同 seed 下 1.0 画面干净、角色最还原，0.7 与 0.5 只是逐级削弱角色一致性。依据见 [强度对照收据](../../receipts/anima29_lorapatch_production_lora_strength_20261005.json)。

先前"把四条 1.0 降到 0.6"的建议据此撤回。那个泛白观察来自另一组测试用的 `anima-base-1-painterly-v2` 风格 LoRA，它本身强度极高，在原版 Anima 上以 1.0 叠加同样泛白，属于单个 LoRA 的强度特性，不是工作流缺陷。因此工作流数值保持原样，逐 LoRA 的强度取舍仍由使用者在工作台决定。

## 更新记录

- 2026-10-05 追加强度判定：以推荐流实际使用的四条 LoRA 做 1.0 / 0.7 / 0.5 固定 seed 对照，判定默认强度无需下调，并撤回先前的 0.6 建议；推荐流无需结构性修正。见 [强度对照收据](../../receipts/anima29_lorapatch_production_lora_strength_20261005.json)。

- 2026-10-05 追加交接：[原版 Anima 回归收据](../../receipts/anima29_lorapatch_original_anima_check_20261005.json)记录选定 28-block 模型/两个 LoRA 的开关对照像素完全相同，以及选定 2.9B 的重映射变化；整理任务复核了 5 份输出文件 SHA。该结论限于记录中的模型、LoRA 和采样参数，不泛化为所有模型/稀疏键零风险；服务 PID 也仅是收据当时值。

- 2026-10-05：接收补丁部署与 A/B 证据，补齐来源、精确实现入口及接手限制；保留用户工作流数值，旧冻结包不作为新补丁证据。
