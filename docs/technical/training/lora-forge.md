# Anima LoRA 训练与候选发布

文档修订：2026-10-15.4。

## 入口和实现

[anima_lora.py](../../../snapshot/runtime/anima_lora_forge/anima_lora.py)提供 doctor/prepare/command/status/train/submit；[core.py](../../../snapshot/runtime/anima_lora_forge/anima_lora_forge/core.py)完成 profile 加载、配对/重复/尺寸扫描、模型/GPU 预检、dataset TOML、训练命令、运行清单和隔离训练器接入。[新角色模板](../../../snapshot/runtime/anima_lora_forge/templates/new_character.profile.json)是复用起点。

与 ComfyUI 的 Python 环境分离，使用已登记 SD-Trainer/sd-scripts。prepare 产生不可变运行配置，不等于已经训练；新角色模板的执行开关默认锁定，历史 profile 不保证全部锁定，实际 train/submit 必须显式授权。暂存数据使用硬链接或复制，不移动原始黄金集。

## 训练与评估契约

训练器的 [sample_prompts.txt](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/SD-Trainer/config/sample_prompts.txt) 是旧 CLI 引用的公共采样示例；现行 Forge 仍在每次准备时生成自己的采样提示词。GUI 的 `assets/config.json` 是可变本机状态，另提供[空状态示例](../../../examples/plugin-settings/README.md)，不复制现场原件。

内层 trainer 源码外的 Windows 配套也已补齐：10 个启动/更新 BAT 和 [整合包说明](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/README.txt)，精确文件与哈希见 [11 文件补源登记](../../../governance/trainer-portable-source-import.json)。[便携启动入口](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/run_gui_portable.bat)及更新脚本只备份其现有实现；不自动运行、下载或原地更新。以后第三方源码更新仍先经唯一主 Git 审查，不能从运行安装包绕过主仓维护。

先检查触发词、图文配对、形态/服装分布和精确重复，再做冒烟/校准。模型架构、训练对象、rank/alpha、学习率、步数、timestep/flow shift、面积桶、精度与 caption 策略都进入 profile 快照。

按固定 prompt/seed、服装、风格、权重矩阵比较多个检查点，选择有证据的候选，不默认发布末轮。历史项目包含 Rosasha、Alicia 普通/晨星及 2.9B 版本；具体参数与评价以对应 profile、运行/评估/发布记录为准，不用旧 README 中单一角色基线代替所有训练。

[evaluate_checkpoint_plan.py](../../../snapshot/runtime/anima_lora_forge/tools/evaluate_checkpoint_plan.py)将仓外 JSON 评估计划变成独立的 ComfyUI API 闭包，冻结底模、CLIP、VAE、LoRA 文件哈希及每份完整 graph。`prepare` 只读 API/核验文件并建立清单记录的临时 LoRA 硬链接；`execute` 才串行提交 GPU，每张图保留请求、回应、history、PNG 与 SHA。开始及每次提交前拒绝非空队列；失败不清理或中断用户队列，结果不明的提交不自动重试。`cleanup` 只移除清单中来源/哈希仍一致的临时硬链接，发现额外文件即保留全部现场。候选输入不等同安装；使用方法、计划契约及验收边界见[本机检查点比较入口](../changes/training-lora-forge/2026-10-15-local-checkpoint-evaluation.md)。

## 仓内与仓外

训练实现、评估矩阵构建与测试在主仓；联合选单的 **49 份候选中 47 份已作为历史技术原件归档**，不是部署源码。包括全部 17 份训练 profile、15 份发布说明/评估/提示包，以及 15 份角色契约/说明，逐项来源与哈希见 [技术归档登记](../../../governance/technical-archive.json)。

| 参数/发布范围 | 实际归档入口 |
|---|---|
| Rosasha 冒烟、校准和正式参数 | [rosasha_smoke.json](../archive/anima_lora_forge/profiles/rosasha_smoke.json)、[rosasha_calibration_400.json](../archive/anima_lora_forge/profiles/rosasha_calibration_400.json)、[rosasha.json](../archive/anima_lora_forge/profiles/rosasha.json) |
| Alicia 原始身份与普通形态参数 | [alicia_bell_smoke.json](../archive/anima_lora_forge/profiles/alicia_bell_smoke.json)、[calibration_400.json](../archive/anima_lora_forge/profiles/alicia_bell_calibration_400.json)、[ordinary_400.json](../archive/anima_lora_forge/profiles/alicia_bell_ordinary_400.json)及同目录普通形态冒烟配置 |
| Alicia 晨星/2.9B 与修正轮参数 | [morning_star_400.json](../archive/anima_lora_forge/profiles/alicia_bell_morning_star_400.json)、[anima29_400.json](../archive/anima_lora_forge/profiles/alicia_bell_morning_star_anima29_400.json)、[v3_bow_bundle_stress_80.json](../archive/anima_lora_forge/profiles/alicia_bell_morning_star_v3_bow_bundle_stress_80.json)及同目录冒烟、refine、v2/v3 配置 |
| Rosasha 发布包文字材料 | [README](../archive/anima_lora_forge/releases/rosasha_anima_r32_v1/README.md)、[评估](../archive/anima_lora_forge/releases/rosasha_anima_r32_v1/evaluation_report.md)、[prompt pack](../archive/anima_lora_forge/releases/rosasha_anima_r32_v1/prompt_pack.txt) |
| Alicia 普通形态发布包 | [README](../archive/anima_lora_forge/releases/alicia_bell_ordinary_anima_r32_v1/README.md)、[评估](../archive/anima_lora_forge/releases/alicia_bell_ordinary_anima_r32_v1/evaluation_report.md)、[prompt pack](../archive/anima_lora_forge/releases/alicia_bell_ordinary_anima_r32_v1/prompt_pack.txt)、[权重审计](../archive/anima_lora_forge/releases/alicia_bell_ordinary_anima_r32_v1/weight_audit.json) |
| Alicia 晨星发布包 | [README](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima_r32_v1/README.md)、[评估](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima_r32_v1/evaluation_report.md)、[prompt pack](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima_r32_v1/prompt_pack.txt)、[权重审计](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima_r32_v1/weight_audit.json) |
| Alicia 晨星 2.9B 发布包 | [README](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima29_r32_v1/README.md)、[评估](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima29_r32_v1/evaluation_report.md)、[prompt pack](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima29_r32_v1/prompt_pack.txt)、[权重审计](../archive/anima_lora_forge/releases/alicia_bell_morning_star_anima29_r32_v1/weight_audit.json) |

两份未入 Git 的候选是 Rosasha `character.json` 和 `01_visual_spec/visual_spec.json`，因原件硬链接数为 2 而保持外部引用，具体路径与边界见[角色黄金集档案](data-forge.md)。Rosasha 发布目录没有本次可归档的 `weight_audit.json`，不伪造为与三套 Alicia 材料相同。

权重、样本图、数据集、日志和便携训练环境仍在外部；Git 中的权重哈希或目录引用不等于权重副本。历史环境、数据或评估 fixture 缺失时，不能直接重跑这些配置或声称重新验证了模型质量。

17 份历史 profile 中有 9 份保留 `trainer.allow_execute=true`；归档保留原始参数，不构成执行授权。18 项训练触发词误报受[精确审核登记](../../../governance/training-trigger-reviews.json)约束，不放宽其他凭证规则。复用先改成新运行 ID、新输出和本机配置，不直接执行旧训练包。

## 验证

[test_core.py](../../../snapshot/runtime/anima_lora_forge/tests/test_core.py)验证可复用工具逻辑；真实训练需独立 GPU 日志、模型/数据哈希与逐图评估。训练监控端口、进程及 Loss 是运行时事实，不写成永远有效的版本状态。

## Colab 试跑、校准与显式续训

[colab_trial.py](../../../snapshot/runtime/anima_lora_forge/tools/colab_trial.py)从已审查的 `vendor/sd-trainer/SD-Trainer/vendor/sd-scripts` 打包纯 Python 源码、许可证、精确允许的 Qwen3/T5 架构与 tokenizer 文件，以及用户选定目录中的同名图片/caption。它排除 `.git`、环境、缓存、GUI 私人配置和预览；试跑与从头校准不携带权重，显式续训只额外纳入哈希绑定的批准状态。底模通过显式公开 HTTPS 地址、大小和 SHA-256 的 manifest 获取。打包不会启动本机训练、上传文件、挂载 Drive 或修改来源数据。输出 ZIP、逐文件哈希清单、干净的 `.ipynb` 和打包收据应保存到仓外新目录，真实训练图片、权重和续训状态不进入 Git。

manifest 顶层为 `expected_num_blocks`（原版 28、2.9B 为 40）和 `files` 列表。每项包含 `role`（`dit` / `vae` / `qwen3` / `tokenizer`）、相对 `path`、`url`、`sha256`，可加 `bytes`。权重相对目标只允许 `models/<name>.safetensors`；tokenizer 只允许精确列出的 `trainer/configs/qwen3_06b/` 与 `trainer/configs/t5_old/` 纯文件。缺失的 T5 `spiece.model` 可从用户审核的仓外纯文件通过 `--t5-spiece` 注入，不公开本机源路径。既有 `infer_anima_num_blocks` 补丁随源码保留，远端以真实模型 header 探测结果与 manifest 核对，不能默默套用另一底模深度。

```text
python tools/colab_trial.py build --dataset-dir <approved-images> --trigger-token <unique-token> --output-dir <new-external-directory> --run-id <unique-run-id> --model-manifest <public-model-manifest.json> --t5-spiece <reviewed-spiece.model> --steps 75 --seed 261012
```

默认 `--mode trial` 保持 50/75 步、每 25 步保存与 `pipeline-trial-not-release` 范围。400 步校准必须同时显式选择模式和步数，使用新的包目录与运行 ID：

```text
python tools/colab_trial.py build --dataset-dir <approved-images> --trigger-token <unique-token> --output-dir <new-calibration-directory> --run-id <new-calibration-run-id> --model-manifest <public-model-manifest.json> --t5-spiece <reviewed-spiece.model> --mode calibration --steps 400 --seed 261012
```

校准每 100 步保存，范围为 `calibration-not-release`；模式、步数、保存间隔和范围同时冻结在配置、Notebook 与打包收据中。校准沿用试跑的依赖、负载允许清单和基线参数，仍无采样预览。100/200/300/400 步和最终权重留给独立出图比较，校准完成本身不代表角色质量或发布验收通过。

`--mode continuation` 显式恢复已完成校准端点。累计目标 600/800/1000 每 200 步保存，1500/2000 每 250 步保存，范围均为 `continued-calibration-not-release`。`--resume-step` 可为已完成的 400/600/800/1000/1500，且必须小于新目标；保存点按累计步数倍数计算。以下从 400 续至 1000，只新增 600 次更新，要求保存 600/800/1000 步与最终权重：

```text
python tools/colab_trial.py build --dataset-dir <same-approved-images> --trigger-token <same-token> --output-dir <new-continuation-directory> --run-id <new-continuation-run-id> --model-manifest <same-model-manifest.json> --t5-spiece <same-spiece.model> --mode continuation --steps 1000 --seed 261012 --resume-payload <approved-parent-payload.zip> --resume-payload-sha256 <exact-parent-payload-sha256> --resume-results <approved-parent-results.zip> --resume-results-sha256 <exact-parent-results-sha256> --resume-step 400
```

完整结果 ZIP 路线的五个 `--resume-*` 身份参数必须同时提供。打包先核对父资料包和完整结果 ZIP 的外部哈希、安全成员、不可变输入、配置一致性、完成收据和选定端点权重身份；只恢复校准或续训已完成的端点。新运行必须保持相同图文哈希、触发词、底模、种子与训练参数，trainer 只允许此次受审查的累计步数修复差异。状态目录精确包含 `model.safetensors`、`optimizer.bin`、`scheduler.bin`、`random_states_0.pkl`、`train_state.json`，大小和哈希写入新配置；完整 ZIP 路线在本机只复制原始状态字节，不反序列化 optimizer/RNG pickle。

完整结果 ZIP 未收齐但已保全原始五件状态时，可另用显式 `partial-rescue` 路线，不能冒称完整 ZIP 审计通过。它要求父资料包及其 SHA、恢复起点，以及绑定的状态目录、救援 manifest 和 manifest SHA；三个救援参数不能与完整结果 ZIP 参数混用。manifest 必须绑定原救援回执、父完成收据、端点权重、五件大小/SHA和 `verified-prefix-crc-local-sha` 来源，保留 `full_source_archive_verified: false`。这一例外在核验五件身份后进行受限 CPU 预检：optimizer/scheduler 采用 `weights_only=True`，RNG仅增加固定 NumPy 构造类型，拒绝自定义 pickle 对象；不初始化 CUDA或开始训练。1000→1500只新增500次更新，保存1250/1500和最终权重。契约、CPU测试与边界见[救援状态续训说明](../changes/training-lora-forge/2026-10-15-rescued-state-continuation.md)。

```text
python tools/colab_trial.py build --dataset-dir <same-approved-images> --trigger-token <same-token> --output-dir <new-external-directory> --run-id <new-run-id> --model-manifest <same-model-manifest.json> --t5-spiece <same-spiece.model> --mode continuation --steps 1500 --seed 261012 --resume-payload <approved-parent-payload.zip> --resume-payload-sha256 <exact-parent-payload-sha256> --resume-state-dir <bound-original-five-state-files> --resume-state-manifest <approved-partial-rescue-manifest.json> --resume-state-manifest-sha256 <exact-manifest-sha256> --resume-step 1000
```

CPU预检的optimizer↔模型对应只检查形状集合，CUDA RNG只检查字节结构；来源状态尚无原云端 SHA 对照时必须保留这一事实。`actual_resume_verified: false` 直到远端首更新前的真实恢复门禁通过，不能由CPU可读、状态文件完整或权重哈希匹配改成已恢复。

远端在第一次数值更新前必须获得 RNG 恢复成功的明确证据；恢复日志缺失或报错即中止。AdamW 各参数状态数量须匹配模型深度，每个参数的累计 step 须等于起点，两个动量张量须形状匹配且有限，学习率须保持 `2e-5`，scheduler 的 `last_epoch` 须等于起点。恢复证据进入遥测和收据，不能仅以状态文件存在或加载函数返回来宣称恢复成功。

[train_network.py](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/SD-Trainer/vendor/sd-scripts/train_network.py)将累计 `global_step` 与起始 epoch 内的批次游标分开，修复恢复 400 步后把计数误设为 epoch 内余数的问题；保留 epoch 边界、梯度累积和末尾不足整组批次的计数，并在外层 epoch 到达目标后停止，防止额外更新。续训命令固定携带 `--resume` 与 `--skip_until_initial_step`。重新建立数据加载器和跳过批次后的采样/打乱顺序不保证等同从头连续训练；RNG、优化器和累计计数门禁不构成逐步数值轨迹一致的证明。

Notebook 先上传对应 ZIP，核对 ZIP 哈希和全部成员清单，再安全解压到新的 `/content/anima_trial/<run-id>`。解压拒绝路径越界、链接、大小写重名、额外成员与篡改。终端路线可选择先手动解压再执行准备/训练，或由完整驱动从 ZIP 开始；完整驱动必须配合新资料包和新运行 ID，不能重新解压到已有工作目录。训练环境使用独立 Linux venv 和官方 PyPI，依赖按现行受审查 trainer 版本固定；当前支持 Python 3.10–3.12 和 BF16 CUDA GPU。标准 venv 的 ensurepip 失败时，在同一目录使用 `--without-pip`，再由宿主 pip 的 `--python` 明确向 venv 安装固定 pip/setuptools/wheel；不向宿主安装训练依赖，安装计时记录回退状态。Colab 2025.10 / Python 3.12 的真实会话已验证此安装方式；更新的 Python 3.13 运行时暂不支持。采用 r32 / alpha16 / LR `2e-5` / AdamW/constant / batch1 / BF16、DiT-only、gradient checkpointing、workers0；试跑为 50 或 75 步，每 25 步保存，校准为 400 步，每 100 步保存，累计 600/800/1000 步续训每 200 步保存，累计 1500/2000 步续训每 250 步保存；各模式都保存权重及续训状态且无采样预览。`qwen_image_vae_2d` 默认省略，只有显式选项才加入。面积桶为 1024、no-upscale、512–1536、步长 64。数据集、随机种子和模型选择进入不可变配置。

远端 prepare/run/entry 再核对初始负载文件的大小、SHA-256、目录与运行 ID；生成配置及 dataset TOML 也须与 prepare 时记录的冻结配置和哈希一致。已有训练收据拒绝覆盖，续训必须另建显式冻结运行。这些目录内核验不能替代解压前的外部 ZIP 哈希核对。成功收据要求累计步数达到目标、实际 Loss 与优化器更新次数精确等于“目标减起点”、Loss 的累计 step 序列连续，并且全部计划保存点和最终 safetensors 都存在、header 合法；400 步校准必须具备 100/200/300/400 步及最终权重五份，400→1000 则必须具备 401–1000 的 600 条 Loss/更新、通过恢复门禁及四份新权重。

输出分别记录依赖安装、模型下载/预检、模型/训练器准备、latent/text 缓存、训练循环（含保存）、有限 Loss、VRAM、每步吞吐以及每个候选 safetensors 的 header/哈希。净更新测量从 `process_batch` 到 AdamW 完成并同步 CUDA，覆盖前向/反向/优化器，排除数据获取、缓存、模型装载和保存；同步本身有少量测量开销。缓存显式写入临时磁盘，与部分本机历史任务的内存缓存不同，且本次无预览，总耗时不能冒称严格同参数 A/B。失败日志同样保留下载；不自动续训、不自动释放其他会话、不自动挂载或授权 Drive。50/75 步只检验管线和速度，400 步及后续显式续训只产生校准候选；角色质量仍须固定参数出图及多个检查点评估。

[test_colab_trial.py](../../../snapshot/runtime/anima_lora_forge/tests/test_colab_trial.py)覆盖 CPU 打包、来源数据不改写、纯文件隐私边界、Notebook 代码编译、28/40 架构契约、命令与缺项拒绝、安全解压及检查点 header/哈希，并验证试跑兼容、校准策略、篡改配置/图文/TOML 的拒绝、完整父状态身份、RNG/AdamW 恢复门禁与缺少计划检查点时的失败收据。[test_trainer_resume_step_accounting.py](../../../snapshot/runtime/anima_lora_forge/tests/test_trainer_resume_step_accounting.py)在 CPU 上执行真实 trainer 的计数/循环 AST，覆盖 400→1000 恰好 600 更新、epoch 边界、梯度累积、末尾不足整组和外层停止；它不执行实际 GPU 或模型运算。现行 Colab、计数修复与 Forge core 合计 61 项 CPU 回归通过。CPU 测试通过不代表 Colab GPU、网络下载或模型质量验收通过；实际训练记录和包应独立保存在仓外。

2026-10-14 已在 Chrome 的 Colab 2025.10 / Python 3.12.12 / Torch 2.6.0 CUDA 12.4 会话上，用批准的 120 对图文数据完成原版 Anima 28 层的 75 步试验。实际 GPU 为 NVIDIA A100-SXM4-40GB；由于 Notebook 输出 iframe 无法稳定加载，本次通过 Colab 文件侧栏上传和内置终端执行冻结资料包，不把此结果视为 Notebook 全部交互已验收。依赖安装 132.54 秒、模型下载与预检 84.22 秒、训练器进程 143.54 秒，其中 latent 缓存 32.99 秒、文本缓存 7.46 秒、模型/训练器准备 37.18 秒、训练及保存 65.91 秒；75 次净更新合计 59.02 秒。退出码 0，75 个有限 Loss 记录，4 份 BF16 LoRA header/哈希通过，CUDA 峰值已分配显存 6,186,939,392 字节。安装、模型准备与训练器三段合计 360.30 秒，不含资料上传、结果打包/下载与浏览器交互等待。

轻量证据和完整权重/续训状态 ZIP 均已下载并保存在仓外。完整 ZIP 为 2,319,568,398 字节，SHA-256 为 `d94f10ded9688da466df491eaa75080278e85b43c9b10181241fdef8ccdc6b9a`；本机副本与远端身份一致，36 个成员的唯一性、安全路径、非链接及 CRC 检查通过。轻量证据独立核对了全部 120 对来源图文哈希、三份底模身份、75 次有限 Loss/更新记录，以及 TensorBoard 与遥测逐项一致性。四份导出权重实际大小与哈希均匹配回执，各有 840 个有限 BF16 张量、280 组模块，覆盖且仅覆盖第 0–27 层；rank32、alpha16 和完整无重叠数据区间通过，并安全提取后再次核对哈希。四组续训状态文件完整保留；未执行 pickle，也未实际验收恢复训练。浏览器下载事件超时不能作为下载失败的证据，应以本机文件、大小和哈希为准。角色质量、正式长训、自动续训和本机部署均未验收。

同日使用新的冻结运行，以霓 120 对图文在 A100-SXM4-40GB / Python 3.12.13 上完成原版 Anima v1.0、28 层的 400 步校准。退出码 0，400 次更新及有限 Loss 与 TensorBoard 一致；训练循环及保存 322.16 秒，净更新 311.16 秒，整个训练器进程 400.51 秒。安装、模型下载/预检和训练器合计 792.20 秒，不含上传、打包/下载、浏览器等待、本机核验及评估。完整结果 ZIP 为 2,898,835,116 字节、SHA-256 `5caa492ed1bb4b19a4e43b2b95fce01a116cce6d4aeeffb28d0b7281c1f652b8`，42 个安全唯一成员及 CRC 通过；五份权重各有 840 个有限 BF16 张量、280 个模块、rank32/alpha16，精确覆盖第 0–27 层。该次状态清单已保留，但未实际恢复训练。

400 步结果已实际查看 30 张有效新图和 4 个复用位置。脸型、尖长刘海和原装轮廓有改善，但金花侧别/成对大小花、衣领与十字布局、灰布发带替换和水彩响应等门槛未全通过；200 与 400 仅保留为比较及续训候选，没有成品推荐强度、正式 LoRA 安装或发布。详细训练与逐图记录留在仓外 `validation/colab-ni-calibration-20261014-01`。

后续使用新冻结运行 `ni_colab_continuation_20261014_1000_v1` 在 Colab 2026.07 / Python 3.12.13 / A100-SXM4-40GB 上从step400恢复，累计完成1000、只新增600次更新。独立轻量证据审计核对了首个新更新前的RNG恢复、560份AdamW参数状态的step400/有限动量/LR `2e-5`、scheduler400，以及401–1000的600条有限Loss、600次更新和TensorBoard/遥测一致性。净更新512.84秒，训练循环含保存526.47秒，训练器620.15秒；安装263.41秒、模型下载/预检107.97秒，三阶段工作量合计991.54秒。安装预热与上传重叠，该合计不是端到端墙钟时间，不包含结果回收或评估。轻量审计只支持训练证据，不包含新权重/状态二进制；完整2,317,819,261字节ZIP的本机回收及独立审计仍待完成。冻结20图评估比较400/600/800/1000各五场景，20张均在本次会话新生成、0复用，评估ZIP来源核验通过，root已实际查看5张场景联系表及20张原PNG，并保存20格source/hash绑定的正式视觉记录，20PNG当前SHA核对通过。600至1000的脸/尖刘海/发束层次改善，1000原装三十字较接近参考；800原装一大一小花为对照。但所有近景金花侧别错误，灰布发带均未出现，水彩均缺乏明确响应；现代换装成功但花饰仍不稳定，没有一个检查点全门槛通过。下一步优先侧向提示词及数据/服装/配饰/画风覆盖诊断，不自动延长到2000。当前没有选定成品或推荐强度，不自动发布、安装、部署或继续训练；不声称恢复轨迹等同连续训练。

本机已按封存清单实际核验47/70个32MiB分块，无哈希异常。第48块传输中Colab断开，现有命名会话无法由自动重连恢复，人工恢复检查待完成；没有执行本次运行时删除，也不以连接中断证明远端文件一定丢失。完整包仍待回收及审计，不构成完整权重/状态交付。官方files.download在真实代码单元中串行请求单块、等本机落盘并核大小/SHA的方式已成功回收此前分块；下载提示缺失或事件超时不能作为失败结论。全部70块验过后须按编号原样串接并核对原ZIP大小/SHA，再执行完整独立审计。

已将核验过的47块保留为独立本机副本，并沿固定ZIP成员头顺序救援完整前缀成员。step600的BF16导出权重已保存，91,986,464字节，SHA-256 `ce8d93a4388cbeced66751a91638736db614246f10d0ca09bc36e1eff503b157`，与冻结训练回执吻合。另保存11个原始状态文件：final累计1000-state与step600-state各有model、optimizer、RNG、scheduler、train_state五个组件；step800-state仅取得model。11件大小、CRC和保存后SHA回读通过，主代理再次核对全部大小/SHA。三份model的安全头审查为F32、840张量、28层、280模块、r32，JSON分别确认final的1000步/epoch9和step600的600步/epoch5。状态文件没有外部远端SHA可比对，身份依据为47块固定SHA覆盖、成员CRC及新计算SHA；未反序列化pickle/bin或实际加载恢复。

随后以纯CPU字节转换从三份F32模型重建600/800/1000/final四份BF16导出，保留冻结云端回执的完整metadata、原键序及导出时间。600先通过原始header、全部张量字节、payload及整文件SHA逐项精确对照，才开放其余三份；四件均匹配各自封存云端文件大小、payload SHA与完整文件SHA，主代理和独立审核者再次实读核验通过。全部840张量的F32输入及BF16输出有限；未使用Torch/GPU、加载训练模型或执行训练。四份文件来源明确为本机重建，文件身份与云端原导出完全一致；重建回执SHA为 `50ce95f69ecfba5754ba1ad83e0b28d65e4d1bedf19fb9b7a358c612c6cd9dff`。这仅完成四份权重身份核验，完整ZIP仍47/70、中央目录及全部状态审计pending，救援状态尚未实际恢复，画质门槛仍未全通过；不构成成品发布。

后续新会话优先回收轻量证据、各候选权重小包，再回收optimizer/RNG等大状态包，每份落盘核验后才推进。该顺序是此次中断形成的流程建议，尚未作为新会话流程实测；不得自动挂载Drive或把尚未审计的状态当作已验证续训入口。

## 更新记录

- 2026-10-15：新增本机参数化检查点评估入口与显式 `partial-rescue` 续训契约，补累计1500/2000、save250及1000→1500只新增500次更新的说明。救援状态先核身份再进行受限CPU预检；完整旧ZIP未验证、CPU形状集合/CUDA结构及实际远端恢复的边界分别保留。打包/CPU测试不构成续训执行或成品选择，详见对应短说明。

- 2026-10-15：原版28层Anima的本机实测完成57张新图：四检查点×三强度×两seed共24张，800/1000服装、配饰、画风及补充seed控制30张，无LoRA诊断3张；原图、graph、history和三组独立审计保存在仓外。目视选择1000步/0.8为本次最佳动漫候选、800为回退；金花细节与水彩/3D仍有限制，未达全轴成品发布，暂不执行已准备的1500或2000。本机近景侧别和灰发带响应修正了旧云端20图结论，不能混淆两种采样器。完整旧ZIP仍未收齐，精确SHA重建权重、CPU状态预检及真实恢复分别记录。临时评估输入清理保留来源权重和图片；输出目录保护补至整个主仓，7项CPU安全测试通过，无生产安装或部署。

- 2026-10-15：补记47块独立保全、11件原始状态字节救援与CPU重建四份BF16权重。600先精确匹配原件header/全部张量/payload/整文件SHA，再处理800/1000/final；四份均与冻结云端文件大小及完整SHA一致，另经主代理与独立审核者实读复核。未加载pickle/bin、Torch/GPU或实际恢复训练；完整ZIP及全部状态审计仍pending。训练和画质结论不变，无成品发布。

- 2026-10-15：400→1000真实A100续训完成，只新增600次更新；独立轻量证据核对RNG/AdamW/scheduler恢复、600条有限Loss/更新及TensorBoard/遥测一致性。净训练512.84秒、训练循环含保存526.47秒；安装与上传重叠，三阶段工作量不是端到端墙钟。冻结20张新图来源核验及root逐原PNG审阅完成，脸发和部分原装改善，但近景金花侧别、灰布发带及水彩均未通过。完整训练ZIP及新权重/状态本机独立审计仍待完成；官方files.download代码单元串行32MiB分块已有真实落地/hash证据，整包/512MiB/多并发请求不稳定。没有成品选择、发布、安装或部署，不自动延长到2000。

- 2026-10-14：新增显式 continuation 累计 600/800/1000 步、save200，绑定批准父资料包/完整结果及五项状态身份；远端强制核验 RNG、AdamW 动量/累计 step/学习率和 scheduler 恢复。修复 trainer 恢复时混用累计步数与 epoch 内批次游标，并在外层 epoch 阻止超出目标的更新；400→1000 只新增 600 次更新。61 项 CPU 回归通过，包含真实计数 AST 边界覆盖；采样顺序不宣称等同连续训练，实际GPU续训/首轮画质证据见2026-10-15记录，无生产部署。

- 2026-10-14：新增显式 400 步校准模式、每 100 步保存，保持既有 50/75 步试跑及保存间隔兼容。远端重复核验不可变输入、运行 ID、准备配置与数据 TOML；完成收据必须具备全部计划检查点与精确 Loss/更新次数。该阶段 35 项 CPU 回归及真实 A100 的 400 步训练通过，五份权重和 42 个 ZIP 成员独立核验通过；30 张有效新图及 4 个复用位置的评估仍有身份/服装控制缺口，没有正式发布或安装。

- 2026-10-14：新增参数化 Colab 50/75 步短训打包器，保留原版/2.9B 动态深度探测；只携带审查源码、纯 tokenizer 与选定图文资料，公开底模地址通过精确哈希 manifest 注入。CPU 回归 26 项通过，补打包/隐私边界/Notebook/训练参数/恶意 ZIP/检查点及 ensurepip 回退；Colab 2025.10 / Python 3.12 的 A100 终端短训 75 步通过，完整结果下载及独立证据核验通过。Notebook 输出交互仍有限制；真实 GPU、外部上传、耗时与角色质量分开验收，源码变更不部署到生产。

- 2026-10-07：补旧 CLI 引用的公共 `config/sample_prompts.txt`，另以空状态示例说明可变 GUI 配置；不导入本机 `assets/config.json`，不改变现行 Forge 采样提示词或启动训练。原字节与精确路径门禁纳入[完整性复核](../changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)。

- 2026-10-07：两个现存 Anima 2.9B profile 的 `models.dit` 相对路径随底模规范位置更新；原训练 release／resume 副本路径、数据集、参数和历史输出保留，未提交训练任务。运行 profile 原件与具体变更留在仓外迁移证据，公开范围见[标准化收据](../../receipts/model_standardization_20261007.json)。
- 2026-10-05：补入默认 Anima 训练路径需要的 Qwen3/T5 架构 `config.json` 和 3 份 trainer 版本标记；这两份配置是模型架构说明，不是 API 凭证，使用精确路径例外并保留内容扫描。T5 `spiece.model` 继续仓外登记，恢复到 [支持文件契约](../../../governance/runtime-support.json)中的原相对路径后才能使用对应默认 tokenizer；本轮不训练、不下载、不运行更新器。

- 2026-10-05：补齐 11 份外层维护脚本/说明，共 29,362 字节，受控新路径导入并 seal；运行原件未改、未执行 BAT、未开始训练。

- 2026-10-05：统一数据准备、独立训练、检查点矩阵和发布记录的接手入口；代码/参数记录/权重分开归属，本轮不启动训练。
- 2026-10-05：补齐 17 份参数和四套发布文字包的归档链接；核实联合资料 47/49 入仓及两份硬链接例外，保留环境/数据/权重缺口，未训练、推理或发布新权重。
