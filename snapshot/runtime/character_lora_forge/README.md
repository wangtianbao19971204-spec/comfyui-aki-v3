# Character LoRA Forge

面向 ComfyUI 的可续跑角色一致性数据集流水线。它复用浏览器里已经启动的同一
ComfyUI 后端，但通过 `127.0.0.1:8188` 的正式队列 API 提交任务，因此不依赖
窗口坐标、缩放比例或某个按钮的位置。Chrome 仍可用来实时查看队列、结果和母工作流。

## 能做什么

1. 从当前 ComfyUI 历史任务捕获一份最小 API 工作流模板；
2. 将角色视觉宪法、视角、景别、动作、背景、光线和风格展开为可复现任务矩阵；
3. 自动修改正/负提示词、seed、尺寸、模型、LoRA 栈和保存前缀；
4. 可选地把标准参考图接入已安装的 Anima LLLite，降低纯文字生成的身份漂移；
5. 顺序提交批量任务，保存图片、prompt id、seed、工作流输入与状态，失败后可续跑；
6. 先做分辨率、曝光、锐度、画幅和近重复检查，再调用现有多模态 LLM 接口；
7. 按身份、成年感、比例、发型、脸眼、服装、装备、技术质量和信息增量评分；
8. 生成 `review.html` 和 `machine_gold`，经确认后复制到种子集或正式训练集。
9. 可根据上一轮 LLM 拒绝原因自动建立 `repair-plan`，或用 `subset-plan` 只补指定视角。

## 为什么没有直接把所有高分图塞进训练集

参考流程明确要求：漂亮不等于可训练。错误年龄感、头身比、发型结构、服装层次、
枪支数量或固定背景会被 LoRA 一并学走。因此机器结果先进入
`runs/<run_id>/machine_gold`，默认保留一次确认门。需要完全自动时才使用
`--auto-promote`。

多风格也采用分层配额：

- `anchor`：中性、清晰、可比较的主数据，负责身份；
- `style_stress`：绘本、电影感、墨彩等少量压力测试，只有身份高分才入选；
- 罗莎莎示例的黄金集目标为 11 张，其中中性图最多 8 张，每个附加风格最多 1 张。

这样能得到“跨风格仍是同一人”的训练底图，同时减少把某一种画风误绑到角色触发词。

## 快速使用

PowerShell：

```powershell
cd G:\ComfyUI-aki-v3\character_lora_forge

# 1. 检查浏览器背后的 ComfyUI、节点、GPU 和 LLM 配置
..\python\python.exe forge.py --config characters\rosasha\character.json doctor

# 2. 查看计划，不出图
..\python\python.exe forge.py --config characters\rosasha\character.json plan

# 3. 小批量生成 2 张，用于检查工作流
..\python\python.exe forge.py --config characters\rosasha\character.json generate --limit 2

# 4. 对指定 run 做 LLM 筛选
..\python\python.exe forge.py --config characters\rosasha\character.json score --run-id 20260726_120000

# 5. 一次跑完当前配置；默认不自动进入训练集
..\python\python.exe forge.py --config characters\rosasha\character.json run

# 6. 确认 review.html 后，把 machine_gold 复制到角色配置指定的训练目录
..\python\python.exe forge.py --config characters\rosasha\character.json promote --run-id 20260726_120000

# 7. 根据上一轮筛选结果建立修复重绘计划
..\python\python.exe forge.py --config characters\rosasha\character.json `
  repair-plan --source-run 20260726_120000

# 8. 只建立指定批次的补图计划
..\python\python.exe forge.py --config characters\rosasha\character.json `
  subset-plan --batches R01_side_identity_clean R03_expression_mature
```

也可以双击 `启动_罗莎莎_小批测试.bat`，它会生成并筛选 2 张测试图，不会自动
提升到训练集。若系统禁止直接运行 PowerShell 脚本，可用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\运行_角色炼制.ps1 -Action doctor
```

## 创建下一个角色

1. 复制 `characters/rosasha` 为新的角色目录；
2. 替换 `02_master_refs` 中的参考图；
3. 重写 `01_visual_spec/visual_spec.json`，把永久身份、默认设计、可变项和淘汰项写清；
4. 修改 `character.json` 的 `character_id`、触发词、提示词、批次和参考图；
5. 先运行 `doctor` 与 `plan`，再用 `run --limit 2` 做小批验证；
6. 标准脸、正面全身、侧面/后四分之三、服装和装备仍未统一时，不应进入 LoRA 训练。

## 目录约定

角色目录遵循参考文档：

- `00_source`：人物卡、原始描写和原图，不直接训练；
- `01_visual_spec`：视觉宪法；
- `02_master_refs`：标准参考图；
- `03_seed_v0`：首轮黄金种子；
- `04_v0_outputs`：临时 LoRA 生成的候选；
- `05_dataset_v1`：筛选修复后的正式训练集；
- `06_rejected`：淘汰图和原因；
- `07_tests`：固定测试矩阵；
- `08_models`：LoRA、参数和日志；
- `09_workflows`：工作流与依赖说明；
- `runs`：每次自动化的计划、状态、候选、评分与报告。

## 捕获新的母工作流

在 Chrome 的 ComfyUI 中手动运行一次希望复用的母工作流，然后：

```powershell
..\python\python.exe forge.py --config characters\rosasha\character.json `
  capture-template --prompt-id latest --output-node 13
```

捕获逻辑会从输出节点反向保留依赖闭包，去掉没有参与本次出图的反推、画廊和预览支路。
如果节点编号变化，只需同步修改角色配置里的 `comfyui.bindings`。

## LLM 筛选

示例读取你现有
`TB_Multi_API_Caption_ConfigPage_V17_ProviderAdapters/providers.json`，
但不会把 API key 写入运行记录或终端。候选图和两张标准参考图会发送给所选视觉模型。
若不希望发送图片，使用 `score --no-llm`；此时只有技术评分，不能替代角色一致性判断。

## 当前边界

- 本项目负责底图生成、元数据、LLM 排序、报告和训练集归档；
- LoRA 训练器、rank、alpha、学习率、步数和 caption 语法没有被提前写死；
- 罗莎莎的宝石发饰、枪套精确结构和最终成年幼态范围仍需标准参考组确认；
- 第一轮优先建立 8–12 张种子图和 v0，不建议直接追求 40 张正式数据。
