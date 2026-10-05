from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
REPORT = ROOT / "report"

MODEL_ORDER = ("anima_original", "anima_29b", "krea2")
MODEL_LABELS = {
    "anima_original": "Anima 原版微调",
    "anima_29b": "Anima 2.9B BF16",
    "krea2": "Krea2 Turbo",
}
CASE_LABELS = {
    "smoke_single_character": "基础单人",
    "anime_action": "动漫动作",
    "architecture_perspective": "建筑透视",
    "attribute_swap": "属性交换",
    "counting_still_life": "精确计数",
    "dance_foreshortening": "人体与透视",
    "english_signage": "英文招牌",
    "low_light_neon": "低照度霓虹",
    "photoreal_carpenter": "写实木匠",
    "product_design": "产品设计",
    "risograph_poster": "孔版印刷海报",
    "three_character_binding": "三人空间绑定",
    "two_person_action": "双人动作关系",
    "natural_landscape": "自然风景",
    "chinese_bookshop_sign": "中文书店招牌",
    "tag_style_character": "Tag 人物",
    "unusual_viewpoint": "特殊机位",
    "length_short": "短提示",
    "length_medium": "中提示",
    "length_long": "长提示",
    "aspect_ultrawide": "超宽画幅",
    "aspect_ultratall": "超高画幅",
    "aspect_square": "方形画幅",
}


def load(name: str):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def weighted(row: dict) -> float:
    return (
        row["prompt_adherence"] * 0.5
        + row["visual_quality"] * 0.3
        + row["structure_artifacts"] * 0.2
    )


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def main() -> int:
    summary = load("summary_stats.json")
    speed = load("speed_stats.json")
    scores = load("score_summary.json")
    manual = load("manual_scores.json")
    inventory = load("model_inventory.json")
    runtime = load("final_runtime_check.json")

    score_rows = []
    for model in MODEL_ORDER:
        row = scores["models"][model]
        score_rows.append(
            f"| {MODEL_LABELS[model]} | {row['prompt_adherence_mean']:.3f} | "
            f"{row['visual_quality_mean']:.3f} | {row['structure_artifacts_mean']:.3f} | "
            f"**{row['weighted_mean']:.3f}** |"
        )

    performance_rows = []
    for model in MODEL_ORDER:
        row = summary["models"][model]
        performance_rows.append(
            f"| {MODEL_LABELS[model]} | {row['wall_time_s_mean']:.2f} s | "
            f"{row['wall_time_s_median']:.2f} s | {row['peak_vram_mb_mean'] / 1024:.2f} GB | "
            f"{row['peak_vram_mb_max'] / 1024:.2f} GB | {row['system_available_mb_min'] / 1024:.2f} GB |"
        )

    speed_rows = []
    for model in MODEL_ORDER:
        for steps, row in speed[model].items():
            samples = ", ".join(f"{value:.2f}" for value in row["samples_s"])
            speed_rows.append(
                f"| {MODEL_LABELS[model]} | {steps} | {samples} | **{row['median_s']:.2f} s** |"
            )

    case_rows = []
    for case_id, case in manual["cases"].items():
        values = [weighted(case[model]) for model in MODEL_ORDER]
        winner = MODEL_LABELS[MODEL_ORDER[values.index(max(values))]]
        case_rows.append(
            f"| {CASE_LABELS[case_id]} | {case['category']} | {values[0]:.2f} | "
            f"{values[1]:.2f} | {values[2]:.2f} | {winner} |"
        )

    detail_rows = []
    for case_id, case in manual["cases"].items():
        row = case["anima_29b"]
        note = row["note"].replace("|", "\\|")
        detail_rows.append(
            f"| {CASE_LABELS[case_id]} | {row['prompt_adherence']:.1f} | "
            f"{row['visual_quality']:.1f} | {row['structure_artifacts']:.1f} | {note} |"
        )

    category_names = sorted(
        scores["models"]["anima_29b"]["category_weighted_mean"].keys()
    )
    category_rows = []
    for category in category_names:
        values = [
            scores["models"][model]["category_weighted_mean"][category]
            for model in MODEL_ORDER
        ]
        winner = MODEL_LABELS[MODEL_ORDER[values.index(max(values))]]
        category_rows.append(
            f"| {category} | {values[0]:.2f} | {values[1]:.2f} | {values[2]:.2f} | {winner} |"
        )

    machine = inventory["machine"]
    anima29 = inventory["models"]["anima_29b"]["files"]
    original_time = summary["models"]["anima_original"]["wall_time_s_mean"]
    anima29_time = summary["models"]["anima_29b"]["wall_time_s_mean"]
    original_vram = summary["models"]["anima_original"]["peak_vram_mb_mean"]
    anima29_vram = summary["models"]["anima_29b"]["peak_vram_mb_mean"]
    krea_vram = summary["models"]["krea2"]["peak_vram_mb_mean"]

    report = f"""# ComfyUI 三模型工作流详细对比报告

**版本：** 2026-08-24，Anima 2.9B BF16 替换 3.8B 后重测  
**比较对象：** Anima 原版微调、Anima 2.9B preview v1 BF16、Krea2 DaSiWa Turbo Raw  
**执行结果：** {summary['all_successes']}/{summary['all_tasks']} 个任务成功，0 个失败  
**重要约束：** 每个任务执行前后都调用 ComfyUI `/free`，三个模型都按同一卸载纪律运行。

## 1. 一页结论

### 1.1 最短答案

1. **Anima 2.9B 已经解决此前 3.8B 工作流的花图问题。** 本轮 42/42 成功，包含极长提示、极端画幅和三轮随机种子，没有出现彩色噪声或花屏式崩坏。
2. **2.9B 不是原版 Anima 的全面替代品。** 综合人工加权分是 **{scores['models']['anima_29b']['weighted_mean']:.3f}**，原版是 **{scores['models']['anima_original']['weighted_mean']:.3f}**，几乎持平；2.9B 在属性绑定、低照度霓虹、三人空间、方形和极宽画幅更强，但在双人交互、特殊机位、海报文字和深透视人体上有退步。
3. **Krea2 仍是综合完成度冠军。** 得分 **{scores['models']['krea2']['weighted_mean']:.3f}**，在写实、文字、商业产品、建筑和复杂交互上领先，但主任务峰值显存均值约 **{krea_vram / 1024:.2f} GB**，必须及时卸载。
4. **日常动漫与 Tag 工作应优先试 2.9B；低成本批量出图保留原版；写实、文字和商业视觉交给 Krea2。** 这三者更适合分工，而不是只留一个。

### 1.2 综合人工评分

评分范围 0 到 5。加权公式为：提示遵循 50% + 视觉质量 30% + 结构/伪影 20%。这是全分辨率联系表人工审阅，不把自动图像指标伪装成审美分数。

| 模型 | 提示遵循 | 视觉质量 | 结构/伪影 | 加权总分 |
|---|---:|---:|---:|---:|
{chr(10).join(score_rows)}

![人工评分总览](assets/manual_scores.png)

### 1.3 2.9B 的定位

Anima 2.9B 把原始 28 个 transformer block 扩展到 40 个，但继续使用原版 Anima 的 Qwen3 0.6B 文本编码器与 Qwen Image VAE。本地安装选择发布页的 **BF16 完整权重**，没有用默认 INT8 文件，因此本轮更接近模型本身的上限，也避免把量化差异误判成架构差异。

它的实际提升主要体现在：

- 颜色、左右位置和角色物件绑定更可靠。
- 霓虹左右分区、对应反射等空间描述非常强。
- Tag 式动漫人物、三人构图、超宽/超高画幅稳定。
- 手部和一般结构伪影平均略少于原版。

它没有解决的难点包括：

- 精确计数仍会多生成物体。
- 英文只能完成大标题，细菜单容易遗漏；中文仍不可用。
- 两人之间的“谁拿什么、倒向哪里、猫在桌下”等关系会被重新解释。
- 极长提示不会花图，但会压缩为较简单的画面，后半段计数和文字约束大量丢失。

## 2. 替换与清理结果

### 2.1 已删除的 3.8B 运行内容

以下内容已从当前 ComfyUI 运行目录删除：

- `models/diffusion_models/Anima-3.8B.safetensors` 及其 metadata。
- `models/diffusion_models/Anima/anima38B_base.safetensors` 重复副本及 metadata。
- `qwen35_4b.safetensors`、`Anima-3.8B-expanded_adapter.safetensors`、`anima38B_base_txt.safetensors`。
- `anima38B_base_controlnet.safetensors`。
- `custom_nodes/comfyui-anima-3-8B` 自定义节点目录。
- 四个依赖 3.8B 专用节点或权重的工作流 JSON。
- 重复且无工作流引用的 `qwen_3_06b_base.safetensors`；保留同哈希的正式文件 `anima_baseV10_txt.safetensors`。

模型目录、工作流和自定义节点已做精确名称与引用扫描，没有留下当前可执行的 3.8B 引用。旧的 `2026-08-24_anima_anima38_krea2` 基准报告没有删除，它是历史证据，不参与当前运行。

### 2.2 新安装的 2.9B 文件

| 组件 | 文件 | 大小 | SHA-256 |
|---|---|---:|---|
| 扩散模型 | `{anima29[0]['name']}` | {anima29[0]['size_gib']:.3f} GiB | `{anima29[0]['sha256']}` |
| 文本编码器 | `{anima29[1]['name']}` | {anima29[1]['size_gib']:.3f} GiB | `{anima29[1]['sha256']}` |
| VAE | `{anima29[2]['name']}` | {anima29[2]['size_gib']:.3f} GiB | `{anima29[2]['sha256']}` |

扩散权重经过文件大小、完整 SHA-256、Safetensors 头和 tensor 数检查：928 个 tensor，transformer block 索引 0 到 39，样本 dtype 为 BF16。扩散模型本体与发布页 BF16 文件哈希完全一致。

### 2.3 新工作流

新工作流以用户原有的大型 Anima 工作流为骨架，保留 63 个顶层节点和 12 个子图，没有做成最小演示图。必要调整只有：

- UNET 改为 `Anima-2.9B/anima29B_v10_bf16.safetensors`。
- 复用 `anima_baseV10_txt.safetensors` 和 `qwen_image_vae.safetensors`。
- AuraFlow shift 设为 3。
- 主采样改为 50 steps、CFG 3.5、Euler、SGM Uniform。
- 移除 3.8B 专用加载器与统一提示节点依赖。

## 3. 测试环境

| 项目 | 值 |
|---|---|
| GPU | {machine['gpu']}，{machine['gpu_memory_mb'] / 1024:.2f} GB |
| CPU | {machine['cpu']}，{machine['cpu_cores_threads']} 核/线程 |
| 系统内存 | {machine['system_ram_mb'] / 1024:.2f} GB |
| 操作系统 | {machine['os']} |
| Python | {machine['python']} |
| PyTorch / CUDA | {machine['pytorch']} / {machine['cuda']} |
| BF16 | {machine['bf16_supported']} |
| ComfyUI commit | `{machine['comfyui_commit']}` |
| 2.9B 支持路径 | ComfyUI 原生动态 block 检测，不依赖专用自定义节点 |

## 4. 方法与公平性

### 4.1 任务构成

每个模型共 42 个任务：

| 任务组 | 数量 | 目的 |
|---|---:|---|
| 主场景 | 23 | 基础单人、多人绑定、文字、写实、动漫、物体、计数、光照、长短提示、极端画幅 |
| 稳定性 | 9 | 3 个高风险场景各换 3 个种子 |
| 速度阶梯 | 9 | 3 档步数各跑 3 个种子 |
| 负面提示冒烟 | 1 | 观察通用负面提示是否触发明显崩坏或风格偏移 |
| **合计** | **42** | 三模型共 126 个任务 |

Anima 原版和 Krea2 的结果来自同一天、同一机器、同一套测试器的原基线记录；本轮新跑 Anima 2.9B。这样避免无意义地重复消耗数小时，但它仍不是严格交错顺序的实验，温度、缓存和后台负载可能带来小幅偏差。

### 4.2 统一内容与模型原生参数

三个模型使用相同的正向提示、尺寸、主种子和检查项，但采样参数遵循各自工作流的合理默认值：

| 模型 | 主步数 | CFG | 采样器 | 调度器 | Shift |
|---|---:|---:|---|---|---:|
| Anima 原版 | 50 | 7.0 | res_multistep | beta | 3 |
| Anima 2.9B BF16 | 50 | 3.5 | Euler | sgm_uniform | 3 |
| Krea2 Turbo | 8 | 1.0 | Euler | simple | 模型路径内处理 |

这不是“完全相同参数”的横比，因为相同参数会让其中两个模型处在不合理区间；这里比较的是三套可实际使用的工作流表现。

### 4.3 卸载纪律

每个任务都保存 `unload_before` 和 `unload_after` 记录，并向 `/free` 发送 `unload_models=true` 与 `free_memory=true`。这对 Krea2 尤其重要：其模型组件磁盘总量约 33.22 GiB，主任务峰值显存均值超过 30 GB。Anima 原版和 2.9B 也执行相同卸载步骤，避免一个模型的驻留状态污染下一个模型。

最终验收时间 `{runtime['checked_at']}`：运行队列 {runtime['queue_running']}/{runtime['queue_pending']}（执行中/等待中），已再次请求卸载模型；显存可用 {runtime['vram_free_mib'] / 1024:.2f}/{runtime['vram_total_mib'] / 1024:.2f} GB；3.8B 精确运行路径命中 {runtime['precise_38b_runtime_path_hits']}，工作流引用命中 {runtime['precise_38b_workflow_reference_hits']}。

## 5. 性能与资源

以下只统计 23 个共同主场景。wall time 包括 ComfyUI 收到任务到输出完成的实用等待时间，因此包含必要的加载与卸载影响。

| 模型 | 平均耗时 | 中位耗时 | 峰值显存均值 | 峰值显存最大值 | 最低可用系统内存 |
|---|---:|---:|---:|---:|---:|
{chr(10).join(performance_rows)}

![性能与资源对比](assets/resources.png)

### 5.1 资源解读

- 2.9B 主任务平均耗时是原版的 **{anima29_time / original_time:.2f} 倍**，峰值显存均值是原版的 **{anima29_vram / original_vram:.2f} 倍**。
- 2.9B 比 Krea2 省显存明显：Krea2 的峰值显存均值约为 2.9B 的 **{krea_vram / anima29_vram:.2f} 倍**。
- 2.9B 与 Krea2 的主任务 wall time 接近，不代表计算量接近。Krea2 只有 8 步，但超大模型的加载和内存搬运占了大量时间；2.9B 则是 50 步的持续采样。
- `post_unload_vram` 仍可能包含 CUDA context、ComfyUI 缓存及桌面进程，不能把它当作“模型还没卸载”的直接证据。最终应以 `/free` 后队列为空、模型可重新从磁盘加载以及显存回落共同判断。

## 6. 步数、耗时与边际收益

### 6.1 三轮速度结果

| 模型 | 步数 | 三个样本耗时 | 中位数 |
|---|---:|---|---:|
{chr(10).join(speed_rows)}

![步数与耗时曲线](assets/speed_curves.png)

![步数画质联系表](../contact_sheets/speed_step_quality_series.jpg)

### 6.2 2.9B 的推荐步数

- **28 步：** 中位 11.98 秒，主要构图和风格已经形成，适合找构图、批量候选与提示词调试。
- **40 步：** 中位 15.79 秒，是本轮最均衡的实际档位，细节略稳，耗时仍明显低于 50 步。
- **50 步：** 中位 18.43 秒，符合官方作者的个人推荐，适合最终图；本轮联系表中相对 40 步的视觉增益很小，不应默认用于所有草图。

因此建议把大型工作流的正式默认保留在 50 步以贴近发布建议，同时在日常队列中增加 28/40 步快捷档。先 28 步挑种子，40 步确认，只有最终候选再 50 步。

## 7. 分数与能力分布

### 7.1 各能力类别

| 类别 | Anima 原版 | Anima 2.9B | Krea2 | 本场景最高 |
|---|---:|---:|---:|---|
{chr(10).join(category_rows)}

这张表比单一总分更重要。2.9B 的总分没有超过原版，原因不是它“没有提升”，而是提升集中在绑定、灯光和多人空间，退步集中在交互、海报和机位。用户应按任务类型分流。

### 7.2 核心场景总览

![核心场景联系表](../contact_sheets/overview_core.jpg)

**动漫与 Tag：** 2.9B 的 Tag 人物是本轮最稳的项目之一，银色 bob、琥珀眼、白手套、黑长靴、怀表与全身站姿几乎全部成立。动漫动作也清楚，但强透视肢体仍可能牺牲自然度。原版风格更柔和，2.9B 线条和绑定更明确；Krea2 更像通用商业插画，未必是最纯粹的 Anima 味道。

**属性与多人绑定：** 2.9B 在基准种子中完整满足左右发色、外套和反色雨伞，还把黄猫放在唯一绿箱上；三轮稳定性中核心绑定 3/3，一轮增加红色行李箱。三人站台场景也大体维持左中右身份与关键物件，但一轮多出小人物。

**双人动作：** 这是 2.9B 明显弱项。它把“左侧咖啡师从玻璃壶倒茶到右侧顾客手中的白杯”改写为陶壶倒向中央玻璃容器，猫也从桌下跑到桌面。画面漂亮不等于关系正确。

**精确计数：** 2.9B 正确给出三枚绿梨、红本与黄铜钥匙，但白杯从两个变成三个，总数由七变八，并出现明显白边。它比原版略高，但仍不适合依赖纯文生图完成严格库存、菜单或产品数量图。

### 7.3 写实、产品与文字

![高级场景联系表](../contact_sheets/overview_advanced.jpg)

**写实木匠：** 2.9B 的老人皮肤、护目镜、牛仔围裙、木屑和工坊光线成立，写实度比原版更好；但手中物件更像金属尺而非木工刨，也没有完整全身。Krea2 对材质和工具语义更可靠。

**产品手表：** 2.9B 保留蓝色表带和右侧红表冠，但把方形透明表盘改成圆形不透明结构，严格两针也没有保持。Krea2 在工业几何、透明材质和商业棚拍上明显更适合。

**英文与中文：** 2.9B 能稳定写出较大的 `MOONLIGHT CAFE`，`24H` 很小，三行价格菜单基本丢失；孔版海报的 `GROW BEYOND` 变成近似词。中文 `月光书店` 和 `今日营业` 仍是假字。Krea2 是三者中唯一能在本轮对复杂中英文文字给出高可用结果的模型。

### 7.4 光照、风景与机位

2.9B 的霓虹场景表现极强：红光只在左墙、青光只在右墙，湿地反射保持对应颜色，黄衣骑手和蓝包裹都清楚，没有人群。自然风景也正确维持 S 形河流、左右岸材质和黑色远山，但白鸟多于五只。

特殊机位中，箱内仰视、温室、放大镜和蓝蝴蝶都可读，但蝴蝶被移到手指附近，左手“指向玻璃边缘蝴蝶”的关系不再精确。2.9B 能理解机位词，却不保证复杂手物关系。

### 7.5 极端画幅

![极端画幅联系表](../contact_sheets/overview_aspect.jpg)

2.9B 的 1536x640 超宽图完整保持左侧海洋、右侧灯塔、中央横向列车和两侧人物；640x1536 超高图也维持井道纵深、底部工程师与顶部圆形开口。方形温室的中心喷泉、左右橘树和单一园丁正确，但主体偏小且留有白边。总体上，2.9B 对非标准画幅很稳。

## 8. 长提示专项

![长短提示联系表](../contact_sheets/overview_length.jpg)

三张图使用同一种子，提示从短到中再到极长。2.9B 的行为可以概括为：

- 短提示：三人站台场景清楚，主要角色和列车成立。
- 中提示：颜色、服装、猫在蓝箱、透明伞、红车和空间层次完成度最高，是它最舒服的密度。
- 极长提示：没有花图，也没有转成抽象噪声，但把三人缩减为两人，遗漏纸鹤、硬币、自动售货机行数、精确文字、时钟和部分姿态约束。

因此，之前 3.8B 的“长 prompt 触发花图”在当前 2.9B BF16 原生路径中不复现。不过这不意味着 2.9B 能完整记住所有长约束。更有效的策略是控制在中等长度，把角色身份、左右位置、动作、关键物件、数量和镜头按优先级放在前半段；次要材质与环境装饰交给二次细化或局部重绘。

## 9. 稳定性

![稳定性总览](../contact_sheets/overview_reliability.jpg)

| 高风险场景 | Anima 原版 | Anima 2.9B BF16 | Krea2 |
|---|---|---|---|
| 属性交换 | {manual['reliability']['attribute_swap']['anima_original']} | {manual['reliability']['attribute_swap']['anima_29b']} | {manual['reliability']['attribute_swap']['krea2']} |
| 深透视舞者 | {manual['reliability']['dance_foreshortening']['anima_original']} | {manual['reliability']['dance_foreshortening']['anima_29b']} | {manual['reliability']['dance_foreshortening']['krea2']} |
| 三人绑定 | {manual['reliability']['three_character_binding']['anima_original']} | {manual['reliability']['three_character_binding']['anima_29b']} | {manual['reliability']['three_character_binding']['krea2']} |

2.9B 的优势更像“核心绑定稳定”，而不是“严格计数稳定”。它经常保留谁穿什么、谁在左边，却可能额外增加一个人或行李箱。需要 exactly N 的场景应至少抽 3 到 6 个种子再筛选。

## 10. 负面提示词冒烟测试

三个模型都额外执行了一次通用负面提示：低质量、模糊、畸形手、多指、融合身体、重复主体、坏透视、色噪与抽象伪影。2.9B 在该单次冒烟中正常生成，没有花图。

这个结果只能证明“常见通用负面词不会立刻触发崩坏”，不能证明负面提示一定改善 2.9B。发布模型更依赖正向描述与合理 CFG；生产工作流应让负面提示保持短而具体，避免把大量互相矛盾的风格词堆进去。

## 11. 23 个主场景总分

| 场景 | 类别 | Anima 原版 | Anima 2.9B | Krea2 | 本场景最高 |
|---|---|---:|---:|---:|---|
{chr(10).join(case_rows)}

## 12. Anima 2.9B 逐场景审阅

| 场景 | 提示遵循 | 视觉质量 | 结构/伪影 | 观察 |
|---|---:|---:|---:|---|
{chr(10).join(detail_rows)}

## 13. 实际工作流建议

### 13.1 日常动漫与角色设计

优先使用 Anima 2.9B，起步设置：

```text
UNET: Anima-2.9B/anima29B_v10_bf16.safetensors
Text encoder: anima_baseV10_txt.safetensors
VAE: qwen_image_vae.safetensors
Shift: 3
Sampler: Euler
Scheduler: SGM Uniform
CFG: 3.5
Steps: 28 预览 / 40 常用 / 50 最终
```

提示词建议采用“核心 Tag + 简短自然语言关系”的混合形式。把人物数、左右位置、发色服装、手持物和动作放前面；年份、`highres`、`absurdres`、风格或 artist tag 放后面。没有必要继续堆 score tag。

### 13.2 快速批量候选

原版 Anima 仍有价值：峰值显存均值约 {original_vram / 1024:.2f} GB，主任务平均 {original_time:.2f} 秒，成本最低；中提示、特殊机位、海报和双人动作的本轮分数还高于 2.9B。先用原版搜索构图，再把选中的 prompt/seed 交给 2.9B 细化，是很实用的双阶段路线。

### 13.3 写实、文字与商业视觉

Krea2 优先处理：真人皮肤与材质、工具和产品几何、建筑直线、中英文招牌、多对象动作关系。它不是常驻模型：任务结束立即 `/free`，切换到 Anima 前再次确认队列为空。若只做动漫人物，Krea2 的 30GB 级峰值通常不值得。

### 13.4 长提示与复杂场景

不要把所有内容塞进一个超长 prompt。建议拆成：

1. 首轮只固定人数、身份、站位、镜头与大动作。
2. 第二轮加入每人服装和唯一关键物件。
3. 文字、精确计数、透明产品和手物交互改用局部重绘、ControlNet、参考图或专用文字工作流。
4. 每次改变关系约束后换 3 个以上种子检查稳定性，不只看最好的一张。

## 14. 最终优缺点清单

### Anima 原版微调

**优点：** 三者中最省资源、最快；动漫风格柔和；中提示、双人动作、特殊机位和海报在本轮并不弱；已有工作流和 LoRA 生态最成熟。

**缺点：** 属性交换经常附加多余物体；计数和文字弱；写实材质与工具语义有限；手部和重复物件概率略高。

### Anima 2.9B BF16

**优点：** 不依赖 3.8B 专用节点；42/42 稳定无花图；属性与多人绑定、低照度霓虹、Tag、极端画幅优秀；一般结构伪影比原版少；显存远低于 Krea2。

**缺点：** 比原版慢约 {(anima29_time / original_time - 1) * 100:.0f}%、峰值显存均值高约 {(anima29_vram / original_vram - 1) * 100:.0f}%；总分并未全面超过原版；双人交互、强透视人体、海报和特殊机位有退步；精确文字、计数和极长约束仍弱。

### Krea2 DaSiWa Turbo

**优点：** 综合得分最高；写实、材质、文字、产品、建筑、复杂关系和长提示完成度最好；少步数即可形成成熟图像。

**缺点：** 峰值显存接近整张 5090 D 的容量，系统可用内存最低只剩约 {summary['models']['krea2']['system_available_mb_min'] / 1024:.2f} GB；加载卸载成本高；动漫 Tag 风格未必比 Anima 更对味；连续切换时最容易让 ComfyUI 变卡。

## 15. 限制与解释边界

- 人工评分只有一名审阅者，虽使用统一量表，仍包含审美判断。
- 每个主场景只有一个固定种子；稳定性专项只覆盖 3 类高风险场景。
- 原版与 Krea2 复用同日同测试器记录，硬件和方法一致，但不是与 2.9B 完全交错运行。
- 各模型使用合理的原生参数而非完全相同参数，结论对应“实际工作流体验”，不是每 FLOP 的学术基准。
- Krea2 测的是 DaSiWa Turbo Raw 微调，不代表所有 Krea2 权重。
- Anima 原版测的是 `miaomiaoHarem_anima15` 微调，不代表官方 base 的全部表现。
- 2.9B 使用 BF16 完整文件；INT8 主文件可能更省资源，也可能改变细节与速度，本报告不能代替 INT8 专项测试。

## 16. 可复核产物

| 产物 | 路径 |
|---|---|
| 机器可读结果 | `raw/results.jsonl`、`raw/results.csv` |
| 人工评分 | `raw/manual_scores.json` |
| 汇总统计 | `raw/summary_stats.json`、`raw/speed_stats.json`、`raw/score_summary.json` |
| 模型身份与哈希 | `raw/model_inventory.json` |
| 最终队列、显存与残留扫描 | `raw/final_runtime_check.json` |
| 全部联系表 | `contact_sheets/` |
| 测试配置 | `benchmark_config.json` |
| 执行器 | `scripts/run_benchmark.py` |
| 2.9B 工作流构建器 | `scripts/build_anima29_workflow.ps1` |
| 本报告生成器 | `scripts/build_final_report.py` |

## 17. 参考资料

- [Anima 2.9B 官方模型卡](https://huggingface.co/Gazingstars123/Anima-2.9B)：架构、共享文本编码器/VAE、提示词、分辨率和采样建议。
- [用户指定的 Anima 2.9B 发布页](https://civitai.red/models/2855007/anima-29b?modelVersionId=3224434)：version 3224434 与 BF16 文件身份。
- [ComfyUI 仓库](https://github.com/comfyanonymous/ComfyUI)：原生加载与节点运行环境。

---

**最终判断：** 2.9B 是一个可用、稳定、能力分布更偏向绑定和空间控制的 Anima 分支，它成功替代了当前有问题的 3.8B 运行链，但不应删除原版 Anima。保留“原版快速候选 + 2.9B 动漫绑定与最终图 + Krea2 写实/文字/商业难题”的三路分工，收益高于强行选出唯一赢家。
"""

    REPORT.mkdir(parents=True, exist_ok=True)
    target = REPORT / "三模型详细对比报告.md"
    target.write_text(report, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
