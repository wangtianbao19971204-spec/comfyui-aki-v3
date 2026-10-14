# Colab 救援状态续训入口与较长校准端点

日期：2026-10-15。

当完整结果 ZIP 下载中断、但原始 final-state 五件已从固定 SHA 分块前缀中完整救援时，原 `--resume-results` 路线仍要求完整 ZIP 的外部 SHA 和所有原有校验，不降低其验收条件。新增独立、显式的 `partial-rescue` 输入路线，允许准备新的续训资料包；不能把部分救援声称为完整结果归档通过。

`--mode continuation --steps 1500/2000` 使用累计目标，每 250 步保留权重和状态。既有 600/800/1000 继续 save200，50/75 短训和400校准策略不变。允许父端点400/600/800/1000/1500，目标必须大于起点；保存点按累计步数倍数计算。1000→1500只新增500次更新，保留1250和1500检查点及最终权重，仍属于校准候选。

新输入同时需要已验证的父 payload ZIP、其 SHA、恢复起点，以及 `--resume-state-dir`、`--resume-state-manifest`、`--resume-state-manifest-sha256`。这三个救援参数必须完整提供，且不能与完整 results 参数混用。绑定 manifest 保存父配置、完成收据的原始 UTF-8及SHA、端点权重的封存SHA、原救援回执SHA、五件状态的大小和SHA。它明确记录 `source_results_claimed_sha256`、`full_source_archive_verified: false` 与 `verified-prefix-crc-local-sha` 来源，不制造一个已验证的父完整ZIP身份。

状态目录只能是父运行的 final-state 或对应端点-state，精确含 model、optimizer、scheduler、RNG、train_state 五件普通文件；拒绝额外成员、缺件、链接、错误目录名、大小/SHA差异和非端点恢复。先核五件身份才加载状态，CPU审查之后再逐件回读SHA，来源资料不改写。

CPU预检验证JSON累计step/epoch；F32模型为28或40层、840或1200张量、每层10组、rank32/alpha16且有限；AdamW为560或800份参数状态、step等于起点、LR `2e-5`、betas `(0.9, 0.999)`、eps `1e-8`、weight decay `0.01`，动量有限且形状集合与LoRA权重一致；constant scheduler端点、计数和LR匹配。optimizer与scheduler只采用 `torch.load(..., map_location="cpu", weights_only=True)`。RNG同样限制为weights-only，并仅增加Accelerate MT19937所需的固定NumPy四项构造类型；拒绝任意自定义pickle对象。Python/NumPy/Torch CPU RNG以独立生成器检查，CUDA RNG仅检查单GPU字节结构，不初始化CUDA、不修改全局RNG、不运行训练。

CPU状态可读与文件SHA一致不等于恢复训练已成功。新负载provenance及包回执均保存 `actual_resume_verified: false`。远端仍须在第一次数值更新前通过既有Accelerate恢复门禁：明确的RNG恢复成功日志、AdamW全部参数step/有限动量/LR与scheduler匹配。完成收据仍必须具备恰好“目标减起点”次有限Loss/更新、连续累计step序列、全部计划检查点与最终权重。实际云端恢复与画质评估单独验收，不保证中断后的采样顺序等同连续训练。

CPU验证：`test_colab_trial.py` 52项通过，包括完整旧ZIP路线和试跑/校准兼容，以及真实小张量状态序列化的1500负载、来源不改写、Notebook编译、SHA门禁、step/epoch/scheduler错误、目录错误、非有限动量及自定义RNG对象拒绝。新增完成收据测试要求1000→1500恰好500次更新及远端恢复事件；真实trainer计数AST另覆盖1000→1500、1500→2000的累计计数与save250，均无额外更新。该记录仅证明打包和CPU门禁，不证明实际A100恢复或1500/2000训练效果。没有修改或部署生产运行区。
