# Anima LoRA 训练与候选发布

文档修订：2026-10-14.2。

## 入口和实现

[anima_lora.py](../../../snapshot/runtime/anima_lora_forge/anima_lora.py)提供 doctor/prepare/command/status/train/submit；[core.py](../../../snapshot/runtime/anima_lora_forge/anima_lora_forge/core.py)完成 profile 加载、配对/重复/尺寸扫描、模型/GPU 预检、dataset TOML、训练命令、运行清单和隔离训练器接入。[新角色模板](../../../snapshot/runtime/anima_lora_forge/templates/new_character.profile.json)是复用起点。

与 ComfyUI 的 Python 环境分离，使用已登记 SD-Trainer/sd-scripts。prepare 产生不可变运行配置，不等于已经训练；新角色模板的执行开关默认锁定，历史 profile 不保证全部锁定，实际 train/submit 必须显式授权。暂存数据使用硬链接或复制，不移动原始黄金集。

## 训练与评估契约

训练器的 [sample_prompts.txt](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/SD-Trainer/config/sample_prompts.txt) 是旧 CLI 引用的公共采样示例；现行 Forge 仍在每次准备时生成自己的采样提示词。GUI 的 `assets/config.json` 是可变本机状态，另提供[空状态示例](../../../examples/plugin-settings/README.md)，不复制现场原件。

内层 trainer 源码外的 Windows 配套也已补齐：10 个启动/更新 BAT 和 [整合包说明](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/README.txt)，精确文件与哈希见 [11 文件补源登记](../../../governance/trainer-portable-source-import.json)。[便携启动入口](../../../snapshot/runtime/anima_lora_forge/vendor/sd-trainer/run_gui_portable.bat)及更新脚本只备份其现有实现；不自动运行、下载或原地更新。以后第三方源码更新仍先经唯一主 Git 审查，不能从运行安装包绕过主仓维护。

先检查触发词、图文配对、形态/服装分布和精确重复，再做冒烟/校准。模型架构、训练对象、rank/alpha、学习率、步数、timestep/flow shift、面积桶、精度与 caption 策略都进入 profile 快照。

按固定 prompt/seed、服装、风格、权重矩阵比较多个检查点，选择有证据的候选，不默认发布末轮。历史项目包含 Rosasha、Alicia 普通/晨星及 2.9B 版本；具体参数与评价以对应 profile、运行/评估/发布记录为准，不用旧 README 中单一角色基线代替所有训练。

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

## Colab 短训

[colab_trial.py](../../../snapshot/runtime/anima_lora_forge/tools/colab_trial.py)从已审查的 `vendor/sd-trainer/SD-Trainer/vendor/sd-scripts` 打包纯 Python 源码、许可证、精确允许的 Qwen3/T5 架构与 tokenizer 文件，以及用户选定目录中的同名图片/caption。它排除 `.git`、环境、缓存、GUI 私人配置、权重和预览；模型只通过显式公开 HTTPS 地址、大小和 SHA-256 的 manifest 获取。打包不会启动本机训练、上传文件、挂载 Drive 或修改来源数据。输出 ZIP、逐文件哈希清单、干净的 `.ipynb` 和打包收据应保存到仓外新目录，真实训练图片和权重不进入 Git。

manifest 顶层为 `expected_num_blocks`（原版 28、2.9B 为 40）和 `files` 列表。每项包含 `role`（`dit` / `vae` / `qwen3` / `tokenizer`）、相对 `path`、`url`、`sha256`，可加 `bytes`。权重相对目标只允许 `models/<name>.safetensors`；tokenizer 只允许精确列出的 `trainer/configs/qwen3_06b/` 与 `trainer/configs/t5_old/` 纯文件。缺失的 T5 `spiece.model` 可从用户审核的仓外纯文件通过 `--t5-spiece` 注入，不公开本机源路径。既有 `infer_anima_num_blocks` 补丁随源码保留，远端以真实模型 header 探测结果与 manifest 核对，不能默默套用另一底模深度。

```text
python tools/colab_trial.py build --dataset-dir <approved-images> --trigger-token <unique-token> --output-dir <new-external-directory> --run-id <unique-run-id> --model-manifest <public-model-manifest.json> --t5-spiece <reviewed-spiece.model> --steps 75 --seed 261012
```

Notebook 先上传对应 ZIP，核对 ZIP 哈希和全部成员清单，再安全解压到新的 `/content/anima_trial/<run-id>`。解压拒绝路径越界、链接、大小写重名、额外成员与篡改。训练环境使用独立 Linux venv 和官方 PyPI，依赖按现行受审查 trainer 版本固定；当前支持 Python 3.10–3.12 和 BF16 CUDA GPU。标准 venv 的 ensurepip 失败时，在同一目录使用 `--without-pip`，再由宿主 pip 的 `--python` 明确向 venv 安装固定 pip/setuptools/wheel；不向宿主安装训练依赖，安装计时记录回退状态。Colab 2025.10 / Python 3.12 的真实会话已验证此安装方式；更新的 Python 3.13 运行时暂不支持。采用 r32 / alpha16 / LR `2e-5` / batch1 / BF16、DiT-only、gradient checkpointing、workers0、50 或 75 步，每 25 步保存权重及续训状态，无采样预览；`qwen_image_vae_2d` 默认省略，只有显式选项才加入。面积桶为 1024、no-upscale、512–1536、步长 64。数据集变更、随机种子和模型选择进入不可变 trial 配置。

输出分别记录依赖安装、模型下载/预检、模型/训练器准备、latent/text 缓存、训练循环（含保存）、有限 Loss、VRAM、每步吞吐以及每个候选 safetensors 的 header/哈希。净更新测量从 `process_batch` 到 AdamW 完成并同步 CUDA，覆盖前向/反向/优化器，排除数据获取、缓存、模型装载和保存；同步本身有少量测量开销。缓存显式写入临时磁盘，与部分本机历史任务的内存缓存不同，且本次无预览，总耗时不能冒称严格同参数 A/B。失败日志同样保留下载；不自动续训、不自动释放其他会话、不自动挂载或授权 Drive。50/75 步只检验管线和速度，角色质量仍须本地固定参数出图及多个检查点评估。

[test_colab_trial.py](../../../snapshot/runtime/anima_lora_forge/tests/test_colab_trial.py)覆盖 CPU 打包、来源数据不改写、纯文件隐私边界、Notebook 代码编译、28/40 架构契约、命令与缺项拒绝、安全解压及检查点 header/哈希。CPU 测试通过不代表 Colab GPU、网络下载或模型质量验收通过；实际短训记录和包应独立保存在仓外。

2026-10-14 已在 Chrome 的 Colab 2025.10 / Python 3.12.12 / Torch 2.6.0 CUDA 12.4 会话上，用批准的 120 对图文数据完成原版 Anima 28 层的 75 步试验。实际 GPU 为 NVIDIA A100-SXM4-40GB；由于 Notebook 输出 iframe 无法稳定加载，本次通过 Colab 文件侧栏上传和内置终端执行冻结资料包，不把此结果视为 Notebook 全部交互已验收。依赖安装 132.54 秒、模型下载与预检 84.22 秒、训练器进程 143.54 秒，其中 latent 缓存 32.99 秒、文本缓存 7.46 秒、模型/训练器准备 37.18 秒、训练及保存 65.91 秒；75 次净更新合计 59.02 秒。退出码 0，75 个有限 Loss 记录，4 份 BF16 LoRA header/哈希通过，CUDA 峰值已分配显存 6,186,939,392 字节。完整权重/续训状态 ZIP 已在远端生成，浏览器下载暂未核验；仅从可见终端保存了摘要收据，不冒称权重已落地。角色质量、正式长训、自动续训和本机部署均未验收。

## 更新记录

- 2026-10-14：新增参数化 Colab 50/75 步短训打包器，保留原版/2.9B 动态深度探测；只携带审查源码、纯 tokenizer 与选定图文资料，公开底模地址通过精确哈希 manifest 注入。CPU 回归 26 项通过，补打包/隐私边界/Notebook/训练参数/恶意 ZIP/检查点及 ensurepip 回退；Colab 2025.10 / Python 3.12 的 A100 终端短训 75 步通过，Notebook 输出/浏览器下载仍有交互限制。真实 GPU、外部上传、耗时与角色质量分开验收，源码变更不部署到生产。

- 2026-10-07：补旧 CLI 引用的公共 `config/sample_prompts.txt`，另以空状态示例说明可变 GUI 配置；不导入本机 `assets/config.json`，不改变现行 Forge 采样提示词或启动训练。原字节与精确路径门禁纳入[完整性复核](../changes/operations-source-of-truth/2026-10-07-completeness-recheck.md)。

- 2026-10-07：两个现存 Anima 2.9B profile 的 `models.dit` 相对路径随底模规范位置更新；原训练 release／resume 副本路径、数据集、参数和历史输出保留，未提交训练任务。运行 profile 原件与具体变更留在仓外迁移证据，公开范围见[标准化收据](../../receipts/model_standardization_20261007.json)。
- 2026-10-05：补入默认 Anima 训练路径需要的 Qwen3/T5 架构 `config.json` 和 3 份 trainer 版本标记；这两份配置是模型架构说明，不是 API 凭证，使用精确路径例外并保留内容扫描。T5 `spiece.model` 继续仓外登记，恢复到 [支持文件契约](../../../governance/runtime-support.json)中的原相对路径后才能使用对应默认 tokenizer；本轮不训练、不下载、不运行更新器。

- 2026-10-05：补齐 11 份外层维护脚本/说明，共 29,362 字节，受控新路径导入并 seal；运行原件未改、未执行 BAT、未开始训练。

- 2026-10-05：统一数据准备、独立训练、检查点矩阵和发布记录的接手入口；代码/参数记录/权重分开归属，本轮不启动训练。
- 2026-10-05：补齐 17 份参数和四套发布文字包的归档链接；核实联合资料 47/49 入仓及两份硬链接例外，保留环境/数据/权重缺口，未训练、推理或发布新权重。
