# Anima 2.9B LoRA 运行时兼容

文档修订：2026-10-05.2；状态：已收到独立功能任务的部署与固定参数 A/B 验收交接。

## 当前功能来源

独立任务“探索 Anima 2.9B LoRA Patch”在本轮整理期间，按用户请求将原版 28-block LoRA 的层映射适配到 40-block Anima 2.9B。其新增源码/配置与运行部署，不属于旧 `f1e61294` 冻结包；不能用旧包 PASS 宣称新补丁已验收。

接手入口为 [补丁实现](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-2.9B-loraPatch/__init__.py)、[上游说明](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Anima-2.9B-loraPatch/README.md)、[profiles.json](../../../snapshot/runtime/production_tools/profiles.json)与 [部署/验收收据](../../receipts/anima29_lorapatch_20261005.json)。7 份上游文件锁定提交 `045f240210b52037e6dd3d8328d776463fe54b96`；仅 production / diagnostic / anima 三档加入白名单。没有另建第二个 Git。

## 技术边界

运行时 remap 与文件转换、模型 block 检测补丁是不同方案。对齐只改变正确层位置，不保证原版与 2.9B 输出相同；原生 40-block LoRA 不应再次按原版转换。同一 LoRA 不要同时叠加原始文件、转换文件和重复转换逻辑。

稀疏训练、非标准键命名和部分 block LoRA 需要额外核对，不凭文件名推断架构。用户此次范围仅 2.9B，未扩展到 3.8B。

## 验证与回滚

应有代码与部署 SHA、模型/LoRA 结构检查、固定 prompt/seed 的对照和禁用恢复方式。透明启动补丁可能改变所有既有 2.9B 输出，界面没有新节点不等于没有运行影响。

独立任务记录了同 seed、采样参数下的开启/关闭/无 LoRA 以及 0.7 强度拆解对照；这证明选定样本的运行时重映射生效，不证明所有 LoRA 的质量或任意叠加都合适。原生 40-block LoRA 透传与非标准稀疏键边界仍需逐模型检查。

整理任务于 2026-10-05 独立复核上述 7 文件和 profiles 的源码/部署哈希一致、工作台 ready、队列空；补全清单中的限定部署证据。没有再生图、重启或改工作流默认强度。收据里原有 open_items 是交接时状态；共享清单、文档及 Git 提交由后续维护版本承接，强度重调仍未授权/实施。回滚前先核对当前服务与收据备份，不能直接执行旧 PID 操作。

## 更新记录

- 2026-10-05 追加交接：[原版 Anima 回归收据](../../receipts/anima29_lorapatch_original_anima_check_20261005.json)记录选定 28-block 模型/两个 LoRA 的开关对照像素完全相同，以及选定 2.9B 的重映射变化；整理任务复核了 5 份输出文件 SHA。该结论限于记录中的模型、LoRA 和采样参数，不泛化为所有模型/稀疏键零风险；服务 PID 也仅是收据当时值。

- 2026-10-05：接收补丁部署与 A/B 证据，补齐来源、精确实现入口及接手限制；保留用户工作流数值，旧冻结包不作为新补丁证据。
