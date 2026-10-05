# ComfyUI 模型对比复用流程

这份手册归纳自 2026-08-24 的 Anima 原版、Anima 3.8B/2.9B 与 Krea2 对比。目标不是制造一个脱离实际使用的学术分数，而是在同一台机器上比较每套模型工作流的真实能力、速度、资源成本、稳定性和适用范围。

当前可复用基线位于：

- `benchmark_reports/2026-08-24_anima_anima29_krea2/`
- 核心执行器：`scripts/run_benchmark.py`
- 测试配置：`benchmark_config.json`
- 最终报告：`report/三模型详细对比报告.md`

## 1. 一分钟流程

1. 为本轮建立全新的 benchmark 目录，不修改用户正在使用的工作流。
2. 盘点模型、编码器、VAE、自定义节点、版本和 SHA256。
3. 为每个模型建立最短但完整的原生 API 工作流，并分别做单图冒烟测试。
4. 固定提示词、尺寸、种子、批量大小和检查项；采样参数使用各模型合理的原生参数。
5. 按 smoke、core、advanced、length、aspect、reliability、speed 顺序运行。
6. 每个任务前后都等待队列清空并调用 ComfyUI `/free` 卸载所有模型。
7. 每个任务保存 API prompt、ComfyUI history、输出路径、耗时和 0.5 秒间隔资源遥测。
8. 生成同场景并排联系表，按统一量表人工评分。
9. 生成统计图、Markdown 和 HTML 报告。
10. 最后再次卸载，确认队列为空、显存回落，并扫描旧模型引用。

## 2. 对比原则

### 2.1 必须固定的变量

- 同一正向提示词。
- 同一画面尺寸和宽高比。
- 同一主种子。
- `batch_size = 1`。
- 同一场景检查项，例如人数、左右关系、颜色、动作、物件和文字。
- 同一种负面提示模式。需要比较空负面与通用负面时，应作为独立任务记录。
- 同一 ComfyUI、PyTorch、CUDA、硬件和后台环境。
- 每个任务执行相同的模型卸载纪律。

### 2.2 不应强行固定的变量

以下参数应使用各模型发布页或已验证工作流的合理默认值：

- 步数。
- CFG。
- 采样器与调度器。
- ModelSampling 类型和 shift。
- 文本编码器及其加载类型。
- VAE。
- latent 节点类型。

完全相同的 CFG、步数和采样器看似公平，实际上可能让某些模型工作在错误区间。本流程比较的是“各模型在正常工作流中的实际产出”，不是单位 FLOP 的学术基准。

### 2.3 必须单独注明的差异

- Base、微调版、Turbo、量化版不能混称为同一个模型。
- LoRA 开启时属于 LoRA 兼容性测试，不能并入纯基模能力分数。
- 复用旧基线时要注明它不是完全交错运行，缓存、温度和后台负载可能造成小偏差。
- 自定义提示词适配器、特殊编码节点和量化方式都属于工作流的一部分，必须进入模型清单。

## 3. 新建一轮对比

推荐目录名：

```text
benchmark_reports/YYYY-MM-DD_modelA_modelB_modelC/
```

建议目录结构：

```text
benchmark_config.json
scripts/
raw/
  api_prompts/
  history/
  telemetry/
  results.jsonl
  results.csv
  manual_scores.json
contact_sheets/
report/
  assets/
logs/
```

不要直接复制上一轮的 `raw/`，否则可续跑逻辑会把旧任务视为已完成。新一轮只复制经过检查的脚本和配置骨架；旧报告完整保留。

## 4. 运行前检查

### 4.1 模型与组件清单

每个模型至少记录：

- 显示名称和内部键名。
- 主模型相对路径、文件大小、修改时间和 SHA256。
- 文本编码器路径和加载类型。
- VAE 路径。
- latent 节点类型。
- ModelSampling 节点和 shift。
- 默认 steps、CFG、sampler、scheduler。
- 必需自定义节点和版本。
- 发布页建议与本地实际设置的差异。

PowerShell 核验示例：

```powershell
$Model = 'G:\ComfyUI-aki-v3\ComfyUI\models\diffusion_models\example.safetensors'
Get-Item -LiteralPath $Model | Select-Object FullName, Length, LastWriteTime
Get-FileHash -LiteralPath $Model -Algorithm SHA256
```

### 4.2 环境快照

记录 GPU、显存、CPU、系统内存、Windows、Python、PyTorch/CUDA、BF16 支持以及 ComfyUI commit。至少执行：

```powershell
nvidia-smi
& 'G:\ComfyUI-aki-v3\python\python.exe' --version
git -C 'G:\ComfyUI-aki-v3\ComfyUI' rev-parse HEAD
```

### 4.3 服务和节点检查

```powershell
$Server = 'http://127.0.0.1:8188'
Invoke-RestMethod -Uri "$Server/queue"
Invoke-RestMethod -Uri "$Server/object_info"
```

确认：

- ComfyUI API 可访问。
- 队列没有其他用户任务。
- 所有工作流节点都出现在 `object_info`。
- 模型、CLIP 和 VAE 出现在对应节点的可选列表。
- 每个模型先用短提示单独生成成功，且没有花图、全黑、全白或抽象噪声。

## 5. API 工作流构建

优先建立显式、可审计的 API graph，不直接依赖 UI 工作流中易变化的 widget 顺序。

### 5.1 Anima 原生路径

典型节点顺序：

```text
UNETLoader
CLIPLoader
ModelSamplingAuraFlow
CLIPTextEncode positive/negative
EmptyLatentImage
KSampler
VAELoader
VAEDecode
SaveImage
```

Anima 2.9B 使用 40-block 原生动态 block 检测时，不应继续引用只为 3.8B 建立的 Qwen 3.5 自定义节点或 adapter。

### 5.2 Krea2 路径

典型节点顺序：

```text
UNETLoader
CLIPLoader(type=krea2)
CLIPTextEncode positive/negative
EmptySD3LatentImage
KSampler
Krea2 VAE
VAEDecode
SaveImage
```

Krea2 的文本编码器、VAE、latent 类型和低步数 Turbo 设置必须作为一个整体核验。混用 Anima/Qwen VAE 或错误的 CLIP 类型会把工作流错误伪装成模型画质问题。

### 5.3 工作流版本规则

- 保留用户原工作流不动。
- 为测试新建带模型版本名的工作流。
- 工作流 JSON、API graph 和模型清单同时归档。
- 先通过单图冒烟，再进入批量队列。

## 6. 测试矩阵

本轮采用每模型 42 个任务，下一次可以直接复用：

| 任务组 | 数量 | 目的 |
|---|---:|---|
| Smoke | 1 | 最基础单人，验证整条生成链 |
| Core | 12 | 多人绑定、双人动作、文字、建筑、写实、动漫、平面、产品、计数、光照和人体 |
| Advanced | 4 | 风景、中文文字、Tag 响应和特殊机位 |
| Length | 3 | 同种子的短、中、极长提示 |
| Aspect | 3 | 超宽、超高和方形画幅 |
| Reliability | 9 | 3 个高风险场景各换 3 个种子 |
| Speed | 9 | 3 档步数各跑 3 个种子 |
| Negative smoke | 1 | 比较实际负面提示与通用负面提示 |
| 合计 | 42 | 三模型为 126 个任务 |

### 6.1 核心场景应覆盖

- 单人身份、服装和手持物。
- 三人左右站位与属性绑定。
- 双人手物交互。
- 中英文文字。
- 建筑直线与深透视。
- 写实皮肤、工具和材质。
- 动漫动作、缩短透视与完整肢体。
- 严格双色或特定平面风格。
- 单一产品的几何和透明材质。
- 精确计数与不重叠。
- 左右颜色光源和对应反射。
- 风景层次与指定数量。
- 特殊机位和透明表面关系。

### 6.2 长提示测试

短、中、长提示必须使用同一种子和尺寸。检查两个不同问题：

1. 是否发生技术性崩坏，例如花图、噪声、空白或节点错误。
2. 图像仍正常时，后半段约束遗漏到什么程度。

如果只在某个长度后花图，应追加边界控制：

- 用 tokenizer 记录 token 数，而不是只数中文或英文字符。
- 逐段增加相同前缀，定位首次失败区间。
- 在相近 token 数下换一组语义简单的后缀。
- 同时用已知短提示复测同一管线。

这样可以区分上下文边界、适配器错误、特定语义冲突和偶发种子问题。

### 6.3 稳定性测试

不要只展示最好的一张。至少对以下高风险场景跑 3 个种子：

- 多人空间绑定。
- 左右颜色或服装交换。
- 强动作、手脚和缩短透视。

报告应写成 `满足次数/总次数`，例如“核心颜色绑定 3/3，严格无额外物件 2/3”。需要生产可靠性的场景建议扩展到 6 个种子。

### 6.4 速度阶梯

每个模型选择三个合理步数，不使用统一步数。例如本轮：

| 模型 | 低 | 中 | 高 |
|---|---:|---:|---:|
| Anima 原版 | 20 | 30 | 50 |
| Anima 2.9B | 28 | 40 | 50 |
| Krea2 Turbo | 4 | 8 | 12 |

每档至少跑 3 个种子，报告中使用中位数。至少一轮倒序运行步数，用于暴露热缓存、温度和运行顺序效应。

## 7. 执行顺序

以下命令假定新 benchmark 目录中的执行器沿用本轮接口：

```powershell
$Python = 'G:\ComfyUI-aki-v3\python\python.exe'
$Root = 'G:\ComfyUI-aki-v3\benchmark_reports\YYYY-MM-DD_modelA_modelB_modelC'

# 1. 最先运行，任何模型失败都先停止扩展测试
& $Python "$Root\scripts\run_benchmark.py" --phases smoke --models all

# 2. 共同主场景
& $Python "$Root\scripts\run_benchmark.py" --phases core,advanced,length,aspect --models all

# 3. 三个高风险场景的多种子稳定性
& $Python "$Root\scripts\run_benchmark.py" --phases reliability --models all

# 4. 三轮速度阶梯，最后一轮倒序
& $Python "$Root\scripts\run_benchmark.py" --phases speed --models all --seed-offset 0
& $Python "$Root\scripts\run_benchmark.py" --phases speed --models all --seed-offset 100
& $Python "$Root\scripts\run_benchmark.py" --phases speed --models all --seed-offset 200 --reverse-speed-steps

# 5. 实际工作流负面提示模式
& $Python "$Root\scripts\run_benchmark.py" --phases smoke --models all --negative-mode live
```

执行器通过 `job_key` 识别已成功任务，意外中断后重复同一命令即可续跑。只有明确要覆盖旧结果时才使用 `--force`。

## 8. 卸载与资源纪律

这是本流程最重要的运行约束之一。每一个任务都执行：

1. 等待 `/queue` 中执行和等待任务都为 0。
2. 记录卸载前资源状态。
3. POST `/free`，body 为 `{"unload_models": true, "free_memory": true}`。
4. 等待显存读数稳定。
5. 启动 0.5 秒间隔遥测。
6. 提交单个任务并等待 history 完成。
7. 停止遥测并保存完整样本。
8. 再次 `/free` 并保存卸载后状态。

手动卸载命令：

```powershell
& 'G:\ComfyUI-aki-v3\benchmark_reports\2026-08-24_anima_anima29_krea2\scripts\unload_all_models.ps1'
```

Krea2 必须同样在任务前后卸载。Anima 也执行相同纪律，避免上一模型的驻留状态污染下一模型。

不要只凭卸载后显存仍有少量占用就判断卸载失败。CUDA context、ComfyUI 缓存和桌面程序都会占显存。应综合判断：

- `/free` 请求成功。
- 队列为空。
- 显存明显回落并趋于稳定。
- 下一任务确实重新加载模型。
- ComfyUI 进程仍可正常响应。

## 9. 每个任务必须保存的数据

- 唯一 `job_key`。
- phase、case id、category 和检查项。
- 模型键、显示名和完整参数。
- prompt、negative、seed、尺寸。
- 实际提交的 API graph JSON。
- ComfyUI prompt id 和 history JSON。
- 输出图片绝对路径。
- 成功/失败、异常和 traceback。
- wall time。
- GPU 显存、利用率、功耗、温度。
- ComfyUI RSS 和系统可用内存。
- 卸载前后资源状态。
- 图像尺寸、均值、标准差等自动健康指标。

自动图像指标只用于发现空白、噪声、损坏或尺寸错误，不作为审美评分。

## 10. 人工评分

先生成全分辨率同场景联系表，再评分。不要在缩略图列表中凭第一印象打分。

本轮量表为 0 到 5：

| 维度 | 权重 | 核心问题 |
|---|---:|---|
| Prompt adherence | 50% | 人数、位置、属性、动作、计数、文字和关键关系是否满足 |
| Visual quality | 30% | 构图、光线、材质、风格完成度和整体观感 |
| Structure/artifacts | 20% | 手脚、脸、透视、重复物体、边框、花图和其他伪影 |

加权分：

```text
总分 = Prompt adherence * 0.50
     + Visual quality * 0.30
     + Structure/artifacts * 0.20
```

评分要求：

- 每个分数都附一条事实性说明。
- 先逐项核对 config 中的 `checks`，再看审美。
- 文字和计数必须按实际结果判定，不能因为画面好看而放宽。
- 结构维度分数越高表示伪影越少。
- 稳定性结果单列，不用一张最佳图代替。
- 保存审阅者、日期和评分方法。

## 11. 生成联系表和报告

```powershell
$Python = 'G:\ComfyUI-aki-v3\python\python.exe'
$Root = 'G:\ComfyUI-aki-v3\benchmark_reports\YYYY-MM-DD_modelA_modelB_modelC'

& $Python "$Root\scripts\make_contact_sheets.py"

# 完成人工审阅并写入 raw/manual_scores.json 后执行
& $Python "$Root\scripts\build_report_assets.py"
& $Python "$Root\scripts\build_final_report.py"
& $Python "$Root\scripts\render_report.py"
```

最终报告至少包含：

- 一页结论和场景分工建议。
- 模型身份、哈希和工作流参数。
- 方法、公平性和限制。
- 23 个共同主场景的时间、显存和系统内存。
- 步数、耗时和画质边际收益。
- 各能力类别与逐场景分数。
- 长提示、稳定性和负面提示专项。
- 联系表、原始记录和脚本索引。
- 最终卸载和残留引用检查。

`build_final_report.py` 含有模型名称和结论性文字，下一轮必须按新模型改写，不能只替换配置后原样复用。

## 12. 花图和异常排查顺序

遇到花图时先判断工作流，再判断模型能力：

1. 用短、简单、已知可工作的提示复测。
2. 核对主模型是否与发布版本完全一致，并检查 SHA256。
3. 核对 VAE，错误 VAE 是高优先级嫌疑。
4. 核对 CLIP 文件及 `CLIPLoader` type。
5. 核对 latent 类型。
6. 核对 ModelSampling 和 shift。
7. 核对 CFG、sampler、scheduler 和 steps。
8. 暂时绕过自定义 adapter 或统一提示节点，使用发布页原生路径对照。
9. 清空负面提示后复测。
10. 对长提示做 token 边界测试，并在相近长度换语义简单的文本。
11. 换至少 2 个种子，排除偶发失败。
12. 每次测试前后卸载，排除模型驻留和显存压力。

常见判断：

- 短提示也花图：优先怀疑 VAE、CLIP、采样路径、权重或节点兼容性。
- 只在长提示花图：检查 tokenizer、上下文边界和提示适配器。
- 图像正常但漏条件：这是提示遵循能力或上下文优先级问题，不属于技术性花图。
- 切换 Krea2 后明显变卡：先等队列空，再 `/free`，确认系统内存和显存回落。
- 相同步数运行时间飘动：检查冷加载、后台负载，并做倒序复测和中位数统计。

## 13. 替换或删除模型时的安全流程

1. 先保存旧报告、模型清单、哈希和必要的测试图。
2. 扫描工作流、自定义节点配置和 benchmark 脚本中的旧文件名及节点类名。
3. 新模型放到正确目录，验证哈希和节点列表。
4. 从原工作流复制新工作流，不改用户原件。
5. 新模型先完成 smoke、length 和一个高风险 reliability 场景。
6. 新链路稳定后再跑完整测试。
7. 确认旧工作流引用为 0 后，才删除旧权重和专用组件。
8. 删除后重启或刷新模型列表，再做最终单图验收。
9. 最后卸载所有模型并保存 `final_runtime_check.json`。

删除旧模型和安装新模型不要与正在运行的批量测试同时进行。

## 14. 本轮得到的可复用经验

- 先验证管线正确性，再讨论画质。3.8B 的花图不能直接当作模型能力结论。
- 中等长度提示通常比极长提示更有效。把人数、身份、左右、动作、关键物件和镜头放在前半段。
- “核心属性正确”与“严格计数正确”是两种能力，必须分开评分。
- 最佳单图不能代表稳定性，至少三种子联系表才有参考价值。
- 模型之间应比较各自合理工作流，而不是盲目统一 CFG 和步数。
- Krea2 的少步数不等于低资源；加载和内存搬运可能占主要时间。
- Anima 原版、较大 Anima 和 Krea2 可以按快筛、动漫绑定、写实商业任务分工，不必强行只留一个赢家。
- 自动统计负责可复核性，最终审美和提示遵循仍需要全分辨率人工审阅。

## 15. 最终检查表

### 开跑前

- [ ] 新 benchmark 目录已建立，旧结果未混入。
- [ ] 用户原工作流未修改。
- [ ] 模型、CLIP、VAE 和自定义节点路径已核对。
- [ ] 文件大小、SHA256、版本和发布页参数已记录。
- [ ] 每个模型短提示单图生成正常。
- [ ] 队列为空，API 和 `nvidia-smi` 正常。

### 运行中

- [ ] 每任务前后 `/free`。
- [ ] API prompt、history、telemetry 和图片都已保存。
- [ ] 失败任务写入异常而不是静默跳过。
- [ ] smoke 通过后才扩展到完整场景。
- [ ] 速度至少三轮，稳定性至少三个种子。

### 报告前

- [ ] 联系表包含相同场景的所有模型。
- [ ] 人工评分有统一维度、权重和事实性说明。
- [ ] 自动指标未被当作审美分数。
- [ ] 报告明确区分模型能力、工作流兼容性和资源成本。
- [ ] 限制、基线复用和非交错运行已披露。

### 收尾

- [ ] 最终队列为 0/0。
- [ ] 所有模型已再次卸载。
- [ ] 显存和系统内存已回落并稳定。
- [ ] 旧模型和旧节点引用扫描已保存。
- [ ] Markdown、HTML、联系表、原始数据和脚本均可打开。
