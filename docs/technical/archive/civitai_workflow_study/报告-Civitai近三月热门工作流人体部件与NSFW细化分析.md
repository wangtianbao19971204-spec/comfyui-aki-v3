# Civitai 近三个月热门 ComfyUI 工作流：手 / 脸 / 身体部件 / 器官 / NSFW 的「选中」与「细化」机制分析

> **数据窗口**：2026-07-04 ~ 2026-10-04（近三个月）

> **样本**：该窗口内 Civitai `Workflows` 类型发布的全部工作流条目 789 个模型，成功取回并解析正文 **723 个模型 / 937 张工作流图**
，按下载量加权覆盖 **94.6%**（1,039,090 / 1,098,977 次下载）。

> **方法**：Civitai v1 API 游标分页拉清单 → 复用浏览器登录会话取回工作流正文 → 从本地节点源码自动提取 1444 个节点类的输入参数顺序 → 节点图谱 + 连线解析


> **一句话导读**：部件级「选中 → 细化」是一套**高影响力的专门技法**——只有少数工作流在用，却覆盖了相当比例的下载量。它集中在 Illustrious / Anima / Krea 2 / SDXL 这些「出单张图」的生态里；本窗口数量最多的视频生成工作流（MiniMax H3 等）基本不用它。


## 0. 核心结论

三个月内热门工作流的「人体局部细化」已经形成高度统一的工业化范式：

> **先用专用 YOLO 检测/分割模型把部件「选中」成掩码（SEGS），再由 Impact Pack 的 detailer 节点把掩码区域裁剪放大后以低 denoise 重采样，并通过 `EditDetailerPipe` 给每个部件注入独立提示词。**

三个最关键的点：

1. **选中靠专用模型，不靠提示词。** 脸是绝对主力（`face_yolov9c`（22 次）、`face_yolov8m`（13 次）），手用 `hand_yolov9c` / `hand_yolov8s`，眼睛用 `Eyeful_v2-paired` / `Anzhc Eyes -seg-hd`，头发用 `hair_yolov8n-seg` / `hair_seg_bigmodel_afterdetailer`，人物整体用 `person_yolov8m-seg`；而 **NSFW 下半身器官完全依赖动漫专用分割模型**（`ntd11_anime_nsfw_segm_v3_all`、`pussyv2`）。

2. **细化参数有明确共识区间。** `denoise` 中位数 **0.3**（P25 0.25 ~ P75 0.45）、`steps` **20.0**、`cfg` **3.5**、`guide_size` **512.0**、`bbox_crop_factor` **3.0**、`bbox_dilation` **10.0** —— 即「放大到短边 512、掩码外扩 10px、重绘约三分之一」。

3. **分工粒度是「一部件一 detailer」。** 头部工作流普遍串联 3~5 个细化节点，各自绑定不同检测器与提示词，而不是一个 detailer 通吃；最多的工作流挂了 12 个细化器。


## 0.5 先定位：这套技法在整体版图里占多大

本窗口 723 个可解析工作流里，真正做「部件级选中 + 细化」的只是少数；但按下载量加权后影响力显著。同时必须区分**两类完全不同的掩码用途**：

| 技法 | 工作流数 | 占模型比 | 占下载量比 |
|---|---|---|---|
| 部件检测 / 器官分割（**本报告主题**） | 29 | 4.0% | **17.4%** |
| Detailer 类细化节点 | 43 | 5.9% | **25.9%** |
| Ultralytics 系检测器 | 28 | 3.9% | **17.3%** |
| SAM / GroundingDINO 系分割 | 30 | 4.1% | **18.1%** |
| 背景抠除（RMBG / BiRefNet / PersonMask） | 24 | 3.3% | **10.2%** |
| 上述任一种（合计） | 70 | 9.7% | **30.2%** |

> **关键区分**：同样是「分割出掩码」，一类用于**人体部件 / 器官细化**（detailer 路线），另一类用于**主体抠图与背景合成**（RMBG / BiRefNet / PersonMask 路线）。前者才是本报告的主题。

| 用途 | 工作流数（共 723） |
|---|---|
| 部件检测 / 器官分割（本报告主题） | 29 |
| 纯抠图 / 背景分离（用途不同） | 9 |
| 两者都不用 | 685 |

### 各基础模型的部件细化采用率

| 基础模型 | 工作流总数 | 用到部件检测 | 用到细化器 | 部件检测占比 |
|---|---|---|---|---|
| MiniMax H3 | 164 | 0 | 0 | 0% |
| Krea 2 | 141 | 9 | 16 | 6% |
| Other | 102 | 1 | 1 | 1% |
| Anima | 59 | 8 | 9 | 14% |
| Qwen 2.1 | 31 | 0 | 3 | 0% |
| Flux.2 Klein 9B | 26 | 0 | 2 | 0% |
| ZImageTurbo | 25 | 1 | 1 | 4% |
| LTXV 2.3 | 22 | 0 | 0 | 0% |
| Illustrious | 20 | 8 | 9 | 40% |
| Qwen | 17 | 0 | 0 | 0% |
| LTXV 2.5 | 15 | 0 | 0 | 0% |
| SDXL 1.0 | 15 | 2 | 2 | 13% |

> **Illustrious / Anima / Krea 2 是三个主战场**；**MiniMax H3（窗口内数量最多的视频模型）几乎不用**——视频生成流程不做局部重绘。


> 细化器用得最多的头部工作流：`ComfyUI Image Workflows`（95376 次下载）；`Z-Image Base & Turbo Pro Grade Wor`（34475 次下载）；`Anima Workflows`（33811 次下载）；`Krea 2 Pro Grade w/ Image Edit, St`（19589 次下载）；`Illustrious/ Pony/ SDXL SFW & NSFW`（15453 次下载）。


## 1. 谁在做「局部细化」

| 能力 | 模型数 / 总模型 723 |
|---|---|
| 使用检测/分割模型（选中） | 38（5%） |
| 使用 detailer 类节点（细化） | 43（6%） |
| 使用 SAM 辅助分割 | 27（4%） |
| 使用 NSFW 专用分割模型 | 2（0%） |

> 按纯模型数看占比很低，但如 0.5 节所述，**按下载量加权后 Detailer 路线覆盖 25.9%**，属于典型的「少数精尖工作流定义标准、其余用户套用」格局。绝大多数工作流（685 个）完全不涉及掩码，它们是视频生成或整图编辑流程。


### 1.1 基础模型分布：谁在细化，谁不在

| 基础模型 | 工作流总数 | 含细化器 | 占比 |
|---|---|---|---|
| MiniMax H3 | 164 | 0 | 0% |
| Krea 2 | 141 | 16 | 11% |
| Other | 102 | 1 | 1% |
| Anima | 59 | 9 | 15% |
| Qwen 2.1 | 31 | 3 | 10% |
| Flux.2 Klein 9B | 26 | 2 | 8% |
| ZImageTurbo | 25 | 1 | 4% |
| LTXV 2.3 | 22 | 0 | 0% |
| Illustrious | 20 | 9 | 45% |
| Qwen | 17 | 0 | 0% |
| LTXV 2.5 | 15 | 0 | 0% |
| SDXL 1.0 | 15 | 2 | 13% |
| Qwen 2 | 13 | 0 | 0% |
| Wan Video 2.2 I2V-A14B | 12 | 0 | 0% |

### 1.2 每个工作流挂载的检测器个数

| 检测器个数 | 工作流数 |
|---|---|
| 0 | 685 |
| 1 | 25 |
| 2 | 9 |
| 3 | 3 |
| 4 | 1 |

### 1.3 每个工作流的细化器节点个数

| 细化器个数 | 工作流数 |
|---|---|
| 1 | 16 |
| 2 | 7 |
| 3 | 8 |
| 4 | 5 |
| 5 | 1 |
| 6 | 1 |
| 8 | 2 |
| 10 | 2 |
| 12 | 1 |

## 2. 「选中」：怎么把目标部件框出来 / 抠出来

### 2.1 承担「选中」的节点类型

| 节点类型 | 出现次数 |
|---|---|
| UltralyticsDetectorProvider | 75 |
| BboxDetectorSEGS | 16 |
| RMBG | 14 |
| easy sam3ImageSegmentation | 13 |
| LayerMask: PersonMaskUltra V2 | 6 |
| ImpactSimpleDetectorSEGS | 6 |
| ApplyPuLIDFlux2 | 6 |
| SAM3_Detect | 6 |
| BiRefNetRMBG | 5 |
| LCPersonMask | 4 |
| IkkiUltralyticsDetector | 4 |
| LCRemBG | 3 |
| PuLIDModelLoader | 2 |
| PuLIDEVACLIPLoader | 2 |
| PuLIDInsightFaceLoader | 2 |
| GroundingDinoSAMSegment (segment anything) | 1 |

**检测方式分布**（bbox 出矩形框，segm 出像素级掩码）：

| 检测方式 | 次数 |
|---|---|
| bbox（矩形框检测） | 61 |
| segm（像素分割） | 18 |
| 其他 | 18 |

### 2.2 被选用的检测/分割模型排行

| 模型文件 | 被引用次数 | 对应部件 |
|---|---|---|
| face_yolov9c | 22 | 脸 |
| face_yolov8m | 13 | 脸 |
| rmbg-2.0 | 10 | 其他 |
| eyeful_v2-paired | 9 | 眼睛 |
| hand_yolov9c | 5 | 手/手指 |
| anzhc face seg 640 v4 y11n | 4 | 脸 |
| anzhc eyes -seg-hd | 4 | 眼睛 |
| person_yolov8m-seg | 4 | 人物整体 |
| hand_yolov8s | 4 | 手/手指 |
| face_yolov8n_v2 | 3 | 脸 |
| ben2 | 3 | 其他 |
| ntd11_anime_nsfw_segm_v3_all | 2 | NSFW 部件（分割） |
| pithanddetailer-v1b-seg | 2 | 手/手指 |
| birefnet-portrait | 2 | 其他 |
| birefnet-general | 2 | 其他 |
| heelsdetect y8m | 2 | 其他 |
| hair_seg_bigmodel_afterdetailer_v10 | 1 | 头发 |
| eyeful_v2-individual | 1 | 眼睛 |
| hair_yolov8n-seg_60 | 1 | 头发 |
| birefnet_toonout | 1 | 其他 |
| eyes | 1 | 眼睛 |
| pussyv2 | 1 | NSFW 部件（分割） |

### 2.3 按部件看选型


**脸**

| 模型 | 次数 |
|---|---|
| face_yolov9c | 22 |
| face_yolov8m | 13 |
| anzhc face seg 640 v4 y11n | 4 |
| face_yolov8n_v2 | 3 |

**眼睛**

| 模型 | 次数 |
|---|---|
| eyeful_v2-paired | 9 |
| anzhc eyes -seg-hd | 4 |
| eyeful_v2-individual | 1 |
| eyes | 1 |

**抠图/背景分离**

| 模型 | 次数 |
|---|---|
| rmbg-2.0 | 10 |
| birefnet-portrait | 2 |
| birefnet-general | 2 |
| birefnet_toonout | 1 |

**手/手指**

| 模型 | 次数 |
|---|---|
| hand_yolov9c | 5 |
| hand_yolov8s | 4 |
| pithanddetailer-v1b-seg | 2 |

**人物整体**

| 模型 | 次数 |
|---|---|
| person_yolov8m-seg | 4 |

**NSFW 部件（分割）**

| 模型 | 次数 |
|---|---|
| ntd11_anime_nsfw_segm_v3_all | 2 |
| pussyv2 | 1 |

**头发**

| 模型 | 次数 |
|---|---|
| hair_seg_bigmodel_afterdetailer_v10 | 1 |
| hair_yolov8n-seg_60 | 1 |

**foot_leg**

| 模型 | 次数 |
|---|---|
| heelsdetect y8m | 2 |

### 2.4 SAM 的定位

| SAM 模型 | 次数 |
|---|---|
| sam_vit_b_01ec64 | 33 |
| sam3 | 10 |
| sam_vit_l_0b3195 | 6 |
| sam_vit_h (2.56gb) | 2 |
| sam_vit_h_4b8939 | 1 |
| sam_hq_vit_h (2.57gb) | 1 |

SAM 相关节点：

| 节点 | 次数 |
|---|---|
| SAMLoader | 40 |
| SAM_SmartInpainter | 7 |
| easy sam3ModelLoader | 4 |
| SAM3Segment | 3 |
| LayerMask: SegmentAnythingUltra V2 | 2 |
| SAMModelLoader (segment anything) | 1 |

> `sam_vit_b` 是最常用档位。SAM 在这里**不是**用来「找」部件的——找部件是 YOLO 的活；SAM 负责把 YOLO 给的矩形框收紧成贴合轮廓的掩码，避免把背景一起重绘。


### 2.5 器官级细化：NSFW 下半身是怎么被单独选中的

这是整套技法里技术含量最高的一环，也是最稀缺的。统计结果很明确——**在 723 个可解析工作流里，只有 3 处检测器专门指向 NSFW 器官**，且集中在少数几个工作流中。原因不难理解：通用 COCO/YOLO 检测器**根本没有「女阴」「肛门」「乳头」这些类别**，必须依赖社区自己标注训练的专用分割模型。


实测到的 NSFW 专用分割模型：

| 模型 | 画风 | 出现次数 | 特点 |
|---|---|---|---|
| `ntd11_anime_nsfw_segm_v3_all.pt` | 动漫 | 2 | 多个器官合并成一张多类别分割图，按区域逐个输出 SEGS |
| `pussyv2` | 写实/通用 | 1 | 专注女性性器官区域 |

其中 `ntd11` 一系的实际调用路径（来自一个公开工作流）：

```
UltralyticsDetectorProvider  model_name = "segm/animeNSFWDetection_v10\ntd11_anime_nsfw_segm_v3_all.pt"
        ↓ (SEGS)
DetailerForEach / FaceDetailer
        ↓ 逐个区域重绘，提示词由 EditDetailerPipe 按区域注入
```

配套的分区提示词语法（实测原文）：

```
[LAB]
[ALL] nsfw
[NIPPLES] nsfw, nipples
[PUSSY] nsfw, pussy
[ANUS] nsfw, (anus)
[PENIS] nsfw, penis
[TESTICLES] nsfw, testicles
```

> 这套写法的精妙之处：**同一个 detailer 节点，按落入哪个分割区域自动切换提示词**。乳头区域只喂 `nsfw, nipples`，女阴区域只喂 `nsfw, pussy`，彼此不污染——这正是「按器官细化」而不是「整张图重画一遍」的关键。


另外还有一条更轻量的路子：直接用 LoRA 承担器官知识。实测到工作流里出现 `krea2GPTGrandPUSSYTruth.safetensors`、`qwen21_v2_Pussy.safetensors`、`NSFW Qwen Lora.safetensors` 这类命名，以及本地已有的 `NSFW_01_女性-半写实_v1.pt` / `NSFW_03_男性-2D动漫_v2.pt` 等分割模型——说明「专用分割模型 + 区域提示词」已是这个圈子的标准做法。


## 3. 「细化」：选中之后怎么重绘

### 3.1 细化器节点类型

| 细化节点 | 出现次数 |
|---|---|
| FaceDetailer | 30 |
| ToDetailerPipe | 16 |
| DetailDaemonSamplerNode | 13 |
| LCDetailPipeOut | 11 |
| LCSkinBeauty | 11 |
| DetailerForEach | 11 |
| FaceDetailerPipe | 8 |
| DetailerForEachDebug | 7 |
| EditDetailerPipe | 6 |
| DetailerForEachPipe | 5 |
| IkkiDetailerProcessor | 4 |
| IkkiDetailerKSampler | 4 |
| FromDetailerPipe | 2 |
| LCDetailDaemon | 2 |
| Detailer (SEGS/pipe) [Eclipse] | 2 |
| BasicPipeToDetailerPipe | 2 |

### 3.2 细化参数的实际取值

> 参数映射经过双重校验（INPUT_TYPES 顺序对齐 + 取值区间校验 + 识别混入的 `control_after_generate` 控制值）：**可信 55 个节点实例**，丢弃 82 个无法确认对齐的实例。

| 参数 | 样本数 | 中位数 | P25 | P75 | 最大 | 最常见取值 |
|---|---|---|---|---|---|---|
| `denoise` | 55 | 0.3 | 0.25 | 0.45 | 0.6 | 0.5、0.25、0.26、0.3 |
| `steps` | 55 | 20.0 | 9.0 | 20.0 | 40.0 | 20.0、14.0、8.0、30.0 |
| `cfg` | 55 | 3.5 | 3.0 | 6.0 | 8.0 | 1.0、3.5、3.0、6.0 |
| `guide_size` | 55 | 512.0 | 512.0 | 768.0 | 1440.0 | 512.0、1440.0、768.0、1024.0 |
| `max_size` | 55 | 1024.0 | 1024.0 | 1440.0 | 4096.0 | 1024.0、4096.0、1440.0、1280.0 |
| `feather` | 55 | 16.0 | 5.0 | 16.0 | 100.0 | 5.0、16.0、100.0、8.0 |
| `noise_mask_feather` | 55 | 20.0 | 20.0 | 64.0 | 100.0 | 20.0、64.0、0.0、12.0 |
| `bbox_threshold` | 38 | 0.5 | 0.4 | 0.5 | 0.8 | 0.5、0.4、0.3、0.25 |
| `bbox_dilation` | 38 | 10.0 | 8.0 | 10.0 | 16.0 | 10.0、8.0、0.0、6.0 |
| `bbox_crop_factor` | 38 | 3.0 | 3.0 | 3.0 | 4.0 | 3.0、2.5、1.1、1.2 |
| `drop_size` | 39 | 10.0 | 10.0 | 16.0 | 32.0 | 10.0、16.0、9.0、4.0 |
| `sam_threshold` | 38 | 0.93 | 0.9 | 0.93 | 0.98 | 0.93、0.9、0.5、0.98 |
| `cycle` | 55 | 1.0 | 1.0 | 1.0 | 10.0 | 1.0、10.0 |

采样器与调度器（按名称识别，非按位置猜）：

| 采样器 / 调度器 | 次数 |
|---|---|
| euler_ancestral | 20 |
| euler | 19 |
| er_sde | 4 |
| dpmpp_3m_sde_gpu | 4 |
| res_multistep | 2 |
| dpmpp_2m_sde | 2 |
| dpmpp_3m_sde | 2 |
| dpmpp_2m | 2 |
| simple（调度器） | 20 |
| normal（调度器） | 11 |
| sgm_uniform（调度器） | 10 |
| beta（调度器） | 6 |
| karras（调度器） | 6 |
| linear_quadratic（调度器） | 2 |

### 3.3 掩码后处理链

| 节点 | 出现次数 |
|---|---|
| MaskPreview | 69 |
| MaskPreview+ | 56 |
| MaskToImage | 37 |
| ImageAndMaskPreview | 34 |
| SolidMask | 17 |
| ImageToMask | 16 |
| GrowMaskWithBlur | 16 |
| InvertMask | 16 |
| ImageBlur | 15 |
| SegsToCombinedMask | 12 |
| LCPreviewMask | 11 |
| LCApplyLUT | 11 |
| MaskToSEGS | 11 |
| GrowMask | 10 |
| MaskComposite | 5 |
| LCImageMaskResize | 4 |
| MaskBlur+ | 2 |
| LayerMask: MaskPreview | 2 |
| LayerMask: MaskEdgeUltraDetail V3 | 1 |
| ImageColorToMask | 1 |
| Mask_Blur_Plus | 1 |
| LayerMask: MaskGrow | 1 |

> 掩码类节点霸占高频榜，说明这套流程的工程量**大半花在掩码上**：`GrowMaskWithBlur` / `GrowMask` 给重绘留过渡带；`SegsToCombinedMask` / `MaskToSEGS` 在 SEGS 与掩码之间来回转换；`MaskPreview+` / `ImageAndMaskPreview` 用来肉眼确认选中区域对不对。


## 4. 提示词分区：每个部件喂什么词

### 4.1 细化节点携带的提示词

- `5×` 512 \| True \| 4096 \| 0 \| randomize \| 14 \| 6 \| euler_ancestral \| normal \| 0.26 \| 16 \| True \| True \| 0.4 \| 8 \| 3 \| none \| 4 \| 0.9 \| 0 \| 0.7 \| False \| 16 \| 0.2 \| 1 \| False \| 64 \| False \| False
- `4×` 512 \| True \| 1024 \| 481937092674701 \| fixed \| 20 \| 3.5 \| euler \| sgm_uniform \| 0.5 \| 16 \| True \| True \| 0.5 \| 8 \| 3 \| center-1 \| 4 \| 0.9 \| 0 \| 0.7 \| False \| 16 \|  \| 1 \| False \| 64 \| False \| False
- `3×` 512 \| False \| 1024 \| 879851501711326 \| fixed \| 9 \| 3 \| euler \| simple \| 0.12 \| 5 \| True \| False \|  \| 0.3 \| 1 \| False \| 20 \| False \| False
- `2×` 512 \| True \| 1024 \| 481937092674701 \| fixed \| 20 \| 3.5 \| euler \| sgm_uniform \| 0.5 \| 16 \| True \| True \| 0.5 \| 8 \| 3 \| center-1 \| 4 \| 0.9 \| 0 \| 0.7 \| False \| 16 \| eyes,detailed eyes \| 1 \| False \| 64 \| False \| False
- `2×` 512 \| True \| 1024 \| 481937092674701 \| fixed \| 30 \| 3.5 \| res_multistep \| linear_quadratic \| 0.15 \| 16 \| True \| True \|  \| 1 \| False \| 32 \| False \| False
- `2×` 512 \| False \| 1024 \| 879851501711326 \| fixed \| 14 \| 2.7 \| euler \| simple \| 0.25 \| 5 \| True \| False \|  \| 0.2 \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 4096 \| True \| 0 \| randomize \| 20 \| 8 \| euler_ancestral \| normal \| 0.5 \| 16 \| 4 \| 12 \| 0.2 \| 1 \| 1 \| False \| 64 \| False \| True
- `1×` 512 \| True \| 1024 \| 188001448409988 \| fixed \| 40 \| 5 \| euler_ancestral \| simple \| 0.4 \| 60 \| True \| True \| 0.5000000000000001 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.5000000000000001 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 188001448409988 \| fixed \| 40 \| 5 \| euler_ancestral \| simple \| 0.6 \| 30 \| True \| True \| 0.5000000000000001 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7000000000000002 \| False \| 10 \| eye focus \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 388588442666511 \| fixed \| 40 \| 5 \| euler_ancestral \| simple \| 0.4 \| 60 \| True \| True \| 0.5000000000000001 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.5000000000000001 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 388588442666511 \| fixed \| 40 \| 5 \| euler_ancestral \| simple \| 0.6 \| 30 \| True \| True \| 0.5000000000000001 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7000000000000002 \| False \| 10 \| eye focus \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 513795447416006 \| randomize \| 30 \| 5 \| euler_ancestral \| simple \| 0.4 \| 5 \| True \| True \|  \| 1 \| False \| 20 \| False \| False
- `1×` 728 \| True \| 1024 \| 282370891703335 \| fixed \| 4 \| 1 \| euler \| simple \| 0.4 \| 5 \| True \| True \| 0.5 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 9 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 728 \| True \| 1024 \| 282370891703335 \| fixed \| 4 \| 1 \| euler \| simple \| 0.3 \| 5 \| True \| True \| 0.5 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 9 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 1024 \| True \| 1536 \| 1094088136850947 \| randomize \| 20 \| 3 \| euler_ancestral \| normal \| 0.35 \| 12 \| True \| True \| 0.3 \| 0 \| 1.2 \| rect-4 \| 90 \| 0.93 \| 0 \| 0.73 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 768 \| True \| 1024 \| 1094088136850947 \| randomize \| 14 \| 3 \| euler_ancestral \| normal \| 0.25 \| 20 \| True \| True \| 0.3 \| 0 \| 1.5 \| rect-4 \| 15 \| 0.93 \| 0 \| 0.73 \| False \| 10 \| hand focus, \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 643195177391019 \| randomize \| 16 \| 8 \| er_sde \| simple \| 0.35 \| 5 \| True \| True \| 0.6 \| 10 \| 2.5 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 1280 \| True \| 1536 \| 598670726561934 \| randomize \| 30 \| 4.5 \| er_sde \| beta \| 0.35 \| 15 \| True \| True \| 0.5 \| 10 \| 4 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 438018737464274 \| randomize \| 20 \| 3 \| euler \| normal \| 0.5 \| 5 \| True \| True \| 0.5 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 19 \| False \| False
- `1×` 512 \| True \| 1024 \| 748458286274640 \| randomize \| 20 \| 3 \| euler \| normal \| 0.5 \| 5 \| True \| True \| 0.5 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1440 \| 674870319687314 \| increment \| 8 \| 1 \| euler \| simple \| 0.5 \| 100 \| True \| True \|  \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 4096 \| 759409859388382 \| randomize \| 16 \| 6 \| er_sde \| simple \| 0.26 \| 16 \| True \| True \| 0.4 \| 8 \| 3 \| none \| 4 \| 0.9000000000000001 \| 0 \| 0.7 \| False \| 16 \| 0.2 \| 1 \| False \| 64 \| False \| False
- `1×` 512 \| True \| 1024 \| 0 \| fixed \| 16 \| 5.5 \| euler \| simple \| 0.3 \| 5 \| True \| True \|  \| 1 \| False \| 12 \| False \| False
- `1×` 768 \| True \| 1024 \| 708492396029774 \| fixed \| 20 \| 4 \| dpmpp_2m_sde \| karras \| 0.3 \| 5 \| True \| True \| 0.5 \| 0 \| 1.1 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 512 \| True \| 1024 \| 708492396029774 \| fixed \| 20 \| 4 \| dpmpp_2m_sde \| karras \| 0.3 \| 5 \| True \| True \| 0.5 \| 10 \| 2.5 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 1024 \| True \| 1024 \| 42 \| fixed \| 4 \| 1 \| er_sde \| simple \| 0.2 \| 5 \| True \| True \| 0.8 \| 10 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 768 \| True \| 1280 \| 80088176054206 \| randomize \| 8 \| 1 \| euler \| simple \| 0.2 \| 16 \| True \| False \| 0.5 \| 16 \| 2 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 32 \|  \| 1 \| False \| 24 \| False \| False
- `1×` 512 \| True \| 1280 \| 19634121882446 \| randomize \| 8 \| 1 \| euler \| simple \| 0.25 \| 8 \| True \| True \| 0.25 \| 6 \| 3 \| center-1 \| 0 \| 0.93 \| 0 \| 0.7 \| False \| 4 \|  \| 1 \| False \| 12 \| False \| False
- `1×` 768 \| True \| 1280 \| 107430621971184 \| fixed \| 22 \| 4.5 \| dpmpp_3m_sde_gpu \| sgm_uniform \| 0.2 \| 8 \| True \| True \| 0.4 \| 12 \| 2.2 \| center-1 \| 0 \| 0.5 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False
- `1×` 896 \| True \| 1280 \| 107430621971184 \| fixed \| 20 \| 4.5 \| dpmpp_3m_sde_gpu \| sgm_uniform \| 0.2 \| 8 \| True \| True \| 0.5 \| 10 \| 2.5 \| center-1 \| 0 \| 0.5 \| 0 \| 0.7 \| False \| 10 \|  \| 1 \| False \| 20 \| False \| False

### 4.2 NSFW 相关提示词

- `3×` 色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，马赛克，卡通崩坏，绘制错误， ⏎ bad anatomy, bad proportions, malformed limbs, ugly, mutilated,  ⏎ signature, watermark, username, overlay, stamp,  ⏎ No nipples, bad nipples, pubic hair, ⏎ deformed
- `3×` Nipples, breasts, 乳头，乳晕，胸部，乳房 ⏎  ⏎ Pussy, Vagina, 阴道，阴蒂，阴唇, ⏎  ⏎ 手部，手指，美甲
- `2×` pt poze : RAW photo, detailed, natural light, looking straight at the camera, skin blemishes, 8k, HD, UHD, imperfect skin, skin pores, solo, centered, clear features, sharp focus, film grain, uhd, candid portrait, high quality image, Sharp Focus, In Frame, puckered anus
- `2×` {"diffusion_models:krea2GPTGrandPUSSYTruth.safetensors":{"air":"urn:air:krea2:diffusionmodel:civitai:452459@3123514","reference_type":"civitai","folder_role":"diffusion_models","relative_path":"krea2GPTGrandPUSSYTruth.safetensors"}}
- `2×` worst quality, low quality, lowres, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, bad anatomy, watermark, artist name, signature, early, old, realistic, nsfw,
- `2×` 🔞Select the nsfw add to the text
- `1×` Include whether the image is sfw, suggestive, or nsfw.
- `1×` ugly, bad, wrong, low quality, monochrome,  simple background, nsfw, worst quality, lowres, score_1, score_2, score_3, blurry, jpeg artifacts, sepia, bad anatomy, watermark, artist name, white background,
- `1×` masterpiece, best quality, highres, sensitive, explicit
- `1×` {"kleinovaNSFWGeneration_30bf16.safetensors":{"air":"urn:air:flux2:checkpoint:civitai:2547526@2999852","sha256":"2d5b548efd8b8e26abfe52f9cf7774d10e63084a7bfba9d2e0e66c3131fb10f8"},"diffusion_models:kleinovaNSFWGeneration_30bf16.safetensors":{"air":"urn:air:flux2:checkpoint:civitai:2547526@2999852"}}
- `1×` keeping everything exactly the same, Remove the Person's Clothing and Accessoires, increase her breast size to large. Make the Person complete naked and nude, restore the image quality to 4k HDR
- `1×` images/2026-09-16/krea2GPTGrandPUSSYTruth, seed, euler, simple, 10_steps_0002.png
- `1×` Qwen 2.1\qwen21_v2_Pussy.safetensors
- `1×` Qwen 2.1\NSFW Qwen Lora.safetensors
- `1×` the task prompt variations will create 5 variation of the prompt you enter in the user_prompt. ⏎  ⏎ for nsfw fewshot training -> setup the nsfw version in the eclipse config -> repo root folder config.json ⏎  ⏎ "few_shot_training_file": "llm_few_shot_training_nsfw.json",
- `1×` ✍️  MODE A  —  SUBJECT KEYWORD  →  AI PROMPT  (active by default, index=0) ⏎  ⏎ Type any subject keyword or phrase in  [prompt_text]  below. ⏎ Qwen3-VL-2B (local, ~3 GB, auto-downloads on first run) expands it into ⏎ a rich, photorealistic prompt for Krea-2 Turbo. ⏎  ⏎ Everything else below (Mode / 
- `1×` 🔞  NSFW TOGGLE  (0 = Off/safe, default \| 1 = On/mature) ⏎  ⏎ One [easy int] control fans into two instruction switches — one feeds Mode A (PromptEnhancer), one feeds Mode B (QwenVL image-describe). Only the switch for whichever Mode is currently active actually executes (lazy-eval), so setting this
- `1×` nsfw, lowres, bad quality, worst quality, score_1, score_2, score_3, poorly drawn, flat color, sketch, jpeg artifacts, ⏎ mutated, ugly, disfigured, long body, bad anatomy, bad hands, missing fingers, extra fingers, extra digits, fewer digits,  ⏎ simple background, transparent background, blurry, fur
- `1×` masterpiece, ultra high quality, ultra-realistic photography, high detail, detailed skin, skin textures,  ⏎ slim girl, perfect body, tall, skinny, slender body, small waist,  ⏎ completely nude, collarbone, navel,  ⏎ beautiful breasts, huge breasts, big round tits, soft pink nipples, puffy areoles, p
- `1×` keqing (genshin impact)​,upper_body​,cloth,covered_nipples
- `1×` HMNSFW, f4nt4sy,Topless, 二次元风格，一位蓝发少女，手持一把蓝色武器 ⏎ masterpiece, very aesthetic
- `1×` plastic skin, waxy skin, doll face, artificial face, CGI face, cartoon, anime, illustration, 3d render, blurry subject, blurry face, blurry hands, blurry feet, one person out of focus, low detail, low quality, extra Penis, fruit, third person, extra person, additional person, background person, crow
- `1×` * Model: Stable Yogi ⏎  ⏎ https://civitai.red/models/2741166/muse-by-stable-yogi-krea2?modelVersionId=3147272 ⏎  ⏎ * Clip for Nsfw ⏎  ⏎ https://huggingface.co/DreamFast/Qwen3-VL-4b-Heretic-ComfyUI/blob/main/qwen3-vl-4b-heretic_fp8_e4m3fn.safetensors
- `1×` Hand-drawn dark fantasy field journal illustration, fine-nib dip pen crosshatching, colored ink washes, handwritten calligraphy, weathered antique manuscript texture.
- `1×` A raw, atmospheric in-universe field-notes manuscript featuring fine-nib ink line art, heavy crosshatching, variable ink bleed, coffee ring stains, and worn parchment creases. Blends precise relic schematic drawings with expressive explorer journal notes.

## 5. 组合拓扑：哪些部件被联合细化

### 5.1 检测器覆盖的部件组合（每个工作流计一次）

| 部件组合 | 工作流数 |
|---|---|
| 脸 | 12 |
| 抠图/背景分离 | 9 |
| 眼睛 + 脸 | 3 |
| 手/手指 | 2 |
| 脸 + 人物整体 | 2 |
| 眼睛 | 2 |
| 服装 + 眼睛 + 脸 + NSFW 部件（分割） | 1 |
| 脸 + 手/手指 | 1 |
| 眼睛 + 头发 + 手/手指 | 1 |
| 脸 + 手/手指 + 人物整体 | 1 |
| 服装 + 眼睛 + 头发 + 手/手指 + 人物整体 | 1 |
| 眼睛 + 手/手指 | 1 |
| 脸 + NSFW 部件（分割） | 1 |
| foot_leg + 抠图/背景分离 | 1 |

### 5.2 检测器模型组合

| 模型组合 | 工作流数 |
|---|---|
| rmbg-2.0 | 7 |
| face_yolov8m | 7 |
| face_yolov9c | 3 |
| face_yolov8n_v2 | 2 |
| face_yolov8m + person_yolov8m-seg | 2 |
| anzhc eyes -seg-hd + anzhc face seg 640 v4 y11n | 1 |
| hand_yolov8s | 1 |
| anzhc eyes -seg-hd + anzhc face seg 640 v4 y11n + ntd11_anime_nsfw_segm_v3_all | 1 |
| face_yolov8m + hand_yolov8s | 1 |
| eyeful_v2-paired + hair_seg_bigmodel_afterdetailer_v10 + pithanddetailer-v1b-seg | 1 |
| eyeful_v2-paired | 1 |
| face_yolov8m + hand_yolov8s + person_yolov8m-seg | 1 |
| eyeful_v2-individual + face_yolov8m | 1 |
| eyeful_v2-paired + hair_yolov8n-seg_60 + hand_yolov8s + person_yolov8m-seg | 1 |
| birefnet_toonout | 1 |

### 5.3 细化器节点组合

| 细化器组合 | 工作流数 |
|---|---|
| FaceDetailer | 9 |
| DetailDaemonSamplerNode | 6 |
| DetailerForEach | 4 |
| LCSkinBeauty | 4 |
| DetailDaemonSamplerNode + LCDetailPipeOut + LCSkinBeauty | 3 |
| DetailerForEach + FaceDetailer | 3 |
| LCDetailDaemon + LCDetailPipeOut + LCSkinBeauty | 2 |
| EditDetailerPipe + FaceDetailerPipe + MaskDetailerPipe + ToDetailerPipe | 1 |
| FaceDetailer + FromDetailerPipe | 1 |
| DetailDaemonSamplerNode + LCDetailPipeOut | 1 |
| ToDetailerPipe | 1 |
| DetailDaemonSamplerNode + Detailer (SEGS/pipe) [Eclipse] | 1 |

## 6. 真实数据流：哪个检测器喂给哪个细化器

> 这一节不是「出现在同一张图里」的统计，而是沿工作流连线**反向追踪**得到的确切接线关系。

| 检测器 → 细化器 | 接线次数 |
|---|---|
| face_yolov9c -> ToDetailerPipe | 15 |
| face_yolov9c -> FaceDetailerPipe | 12 |
| face_yolov8m -> FaceDetailer | 12 |
| face_yolov9c -> EditDetailerPipe | 10 |
| anzhc face seg 640 v4 y11n -> FaceDetailer | 10 |
| face_yolov8m -> DetailerForEach | 7 |
| anzhc eyes -seg-hd -> FaceDetailer | 6 |
| hand_yolov9c -> DetailerForEachPipe | 5 |
| hand_yolov9c -> DetailerForEachDebug | 5 |
| eyeful_v2-paired -> DetailerForEachDebug | 5 |
| person_yolov8m-seg -> FaceDetailer | 4 |
| hand_yolov8s -> FaceDetailer | 4 |
| pithanddetailer-v1b-seg -> IkkiDetailerProcessor | 3 |
| eyeful_v2-paired -> IkkiDetailerProcessor | 3 |
| pithanddetailer-v1b-seg -> IkkiDetailerKSampler | 3 |
| eyeful_v2-paired -> IkkiDetailerKSampler | 3 |
| hair_yolov8n-seg_60 -> FaceDetailer | 3 |
| anzhc face seg 640 v4 y11n -> FromDetailerPipe | 2 |
| ntd11_anime_nsfw_segm_v3_all -> FaceDetailer | 2 |
| face_yolov8n_v2 -> FaceDetailerPipe | 2 |
| face_yolov8n_v2 -> EditDetailerPipe | 2 |
| person_yolov8m-seg -> DetailerForEach | 2 |
| hand_yolov8s -> DetailerForEach | 2 |
| face_yolov9c -> BasicPipeToDetailerPipe | 2 |
| pussyv2 -> DetailerForEach | 2 |
| face_yolov9c -> DetailerForEach | 1 |
| face_yolov8n_v2 -> ToDetailerPipe | 1 |
| hair_seg_bigmodel_afterdetailer_v10 -> IkkiDetailerProcessor | 1 |
| hair_seg_bigmodel_afterdetailer_v10 -> IkkiDetailerKSampler | 1 |
| eyeful_v2-individual -> FaceDetailer | 1 |

### 6.1 每个检测器被哪些细化器消费

- **face_yolov9c** → ToDetailerPipe（15）、FaceDetailerPipe（12）、EditDetailerPipe（10）、BasicPipeToDetailerPipe（2）、DetailerForEach（1）、DetailerPipeToBasicPipe（1）
- **face_yolov8m** → FaceDetailer（12）、DetailerForEach（7）
- **eyeful_v2-paired** → DetailerForEachDebug（5）、IkkiDetailerProcessor（3）、IkkiDetailerKSampler（3）、FaceDetailer（1）、DetailerForEach（1）、BasicPipeToDetailerPipe（1）、FaceDetailerPipe（1）
- **anzhc face seg 640 v4 y11n** → FaceDetailer（10）、FromDetailerPipe（2）
- **hand_yolov9c** → DetailerForEachPipe（5）、DetailerForEachDebug（5）
- **anzhc eyes -seg-hd** → FaceDetailer（6）
- **person_yolov8m-seg** → FaceDetailer（4）、DetailerForEach（2）
- **hand_yolov8s** → FaceDetailer（4）、DetailerForEach（2）
- **pithanddetailer-v1b-seg** → IkkiDetailerProcessor（3）、IkkiDetailerKSampler（3）
- **face_yolov8n_v2** → FaceDetailerPipe（2）、EditDetailerPipe（2）、ToDetailerPipe（1）
- **hair_yolov8n-seg_60** → FaceDetailer（3）、DetailerForEach（1）
- **ntd11_anime_nsfw_segm_v3_all** → FaceDetailer（2）
- **hair_seg_bigmodel_afterdetailer_v10** → IkkiDetailerProcessor（1）、IkkiDetailerKSampler（1）
- **pussyv2** → DetailerForEach（2）
- **eyeful_v2-individual** → FaceDetailer（1）
- **eyes** → FaceDetailer（1）

### 6.2 挂在图里但从未接入细化器的检测器

| 检测器 | 次数 |
|---|---|
| face_yolov8n_v2 | 1 |

> 这些多半是「预留接口」或已断开的调试分支——说明社区习惯在工作流里常备检测器备用。


## 7. 头部工作流的真实链路

> 口径：把同一模型下多张工作流图的信息合并，细化器按「配置签名」去重，再按下载量排序；因此列出的每个细化器代表一种不同的参数配置。


### ComfyUI Image Workflows

- 模型 ID `1386234` ｜ 下载量 **95376** ｜ 基础模型 Illustrious ｜ NSFW 等级 31 ｜ 共 5 张图（`Standard_V39.json`, `Advanced_V39.json`, `Basic_V39.json`）
- **选中**（1 个检测器）：
  - `bbox/face_yolov9c.pt` → 脸（bbox）
- SAM：`sam_vit_b_01ec64`
- **细化**（4 个细化器实例）：
  - `FaceDetailerPipe` guide_size=512、max_size=4096、steps=14、cfg=6、denoise=0.26、feather=16、bbox_threshold=0.4、bbox_dilation=8、bbox_crop_factor=3
  - `EditDetailerPipe`【脸 + 杂物/水印】 
  - `ToDetailerPipe`【杂物/水印】 
  - `MaskDetailerPipe` guide_size=512、max_size=4096、steps=20、cfg=8、denoise=0.5、feather=16

### Z-Image Base & Turbo Pro Grade Workflow I2I/T2I (Low or High VRAM)

- 模型 ID `2184844` ｜ 下载量 **34475** ｜ 基础模型 ZImageTurbo ｜ NSFW 等级 31 ｜ 共 1 张图（`zImageBaseTurboProGrade_v29DeathstarVersion.json`）
- **选中**：**手动掩码路线**（无检测器，靠 `LCPreviewMask`、`LCImageMaskResize`、`LCApplyLUT` 直接给掩码）
- 掩码链：LCPreviewMask → LCImageMaskResize → LCApplyLUT
- **细化**（3 个细化器实例）：
  - `LCDetailPipeOut` 
  - `LCSkinBeauty` 
  - `LCDetailDaemon` 

### Anima Workflows

- 模型 ID `2426853` ｜ 下载量 **33811** ｜ 基础模型 Anima ｜ NSFW 等级 31 ｜ 共 5 张图（`AnimaStandardV9.json`, `AnimaBasicV9.json`, `AnimaAdvancedV9.json`）
- **选中**（1 个检测器）：
  - `bbox/face_yolov9c.pt` → 脸（bbox）
- SAM：`sam_vit_b_01ec64`
- **细化**（1 个细化器实例）：
  - `ToDetailerPipe`【杂物/水印】 

### Krea 2 Pro Grade w/ Image Edit, Style Transfer, Moodboard, Controlnet, Multi-reference, Smart Detailers, In & Outpaint, & Low VRAM options

- 模型 ID `2726952` ｜ 下载量 **19589** ｜ 基础模型 Krea 2 ｜ NSFW 等级 31 ｜ 共 1 张图（`krea2ProGradeWImageEditStyleTransfer_v241DeathstarVersion.json`）
- **选中**：**手动掩码路线**（无检测器，靠 `LCPreviewMask`、`LCApplyLUT` 直接给掩码）
- 掩码链：LCPreviewMask → LCApplyLUT
- **细化**（3 个细化器实例）：
  - `LCDetailPipeOut` 
  - `LCSkinBeauty` 
  - `LCDetailDaemon` 

### Moody Krea2 Simple Workflow

- 模型 ID `2743636` ｜ 下载量 **18475** ｜ 基础模型 Krea 2 ｜ NSFW 等级 31 ｜ 共 1 张图（`moodyKrea2Simple_v40.json`）
- **选中**（1 个检测器）：
  - `bbox/face_yolov8m.pt` → 脸（bbox）
- 掩码链：SegsToCombinedMask → MaskPreview → MaskToSEGS → MaskPreview+

### Illustrious/ Pony/ SDXL SFW & NSFW Pro Grade Workflow (Low and high VRAM)

- 模型 ID `2282970` ｜ 下载量 **15453** ｜ 基础模型 Illustrious ｜ NSFW 等级 31 ｜ 共 1 张图（`illustriousPonySDXLSFWNSFW_v14LC123Sigmas.json`）
- **选中**：**手动掩码路线**（无检测器，靠 `MaskPreview`、`LCApplyLUT`、`LCImageMaskResize` 直接给掩码）
- SAM：`sam3`、`sam_vit_b_01ec64`
- 掩码链：MaskPreview → LCApplyLUT → LCImageMaskResize
- **细化**（3 个细化器实例）：
  - `DetailDaemonSamplerNode` 
  - `LCSkinBeauty` 
  - `LCDetailPipeOut` 

### ANIMA Pro Grade SFW/NSFW W/ Controlnet, Regional Prompt, & Realism enhancer

- 模型 ID `2382239` ｜ 下载量 **11022** ｜ 基础模型 Anima ｜ NSFW 等级 31 ｜ 共 1 张图（`animaProGradeSFWNSFWW_v23ButWaitTheresMore.json`）
- **选中**：**手动掩码路线**（无检测器，靠 `LCPreviewMask`、`LCApplyLUT` 直接给掩码）
- SAM：`sam_vit_b_01ec64`
- 掩码链：LCPreviewMask → LCApplyLUT
- **细化**（2 个细化器实例）：
  - `LCDetailPipeOut` 
  - `DetailDaemonSamplerNode` 

### Illustrious/ Pony/ SDXL Pro Grade Workflow (Low or High VRAM)

- 模型 ID `2189190` ｜ 下载量 **10678** ｜ 基础模型 Illustrious ｜ NSFW 等级 31 ｜ 共 1 张图（`illustriousPonySDXLProGrade_v2201KitchenSinkVer.json`）
- **选中**（1 个检测器）：
  - `bbox/face_yolov8n_v2.pt` → 脸（bbox）
- SAM：`sam3`
- 掩码链：MaskPreview → LCApplyLUT
- **细化**（1 个细化器实例）：
  - `DetailDaemonSamplerNode` 

### FLUX2 Klein_9b Pro Grade Workflow (High & Low VRAM), w/ Controlnet, GGUF capable

- 模型 ID `2213699` ｜ 下载量 **9410** ｜ 基础模型 Flux.2 Klein 9B ｜ NSFW 等级 15 ｜ 共 1 张图（`flux2Klein9bProGradeWorkflowHigh_v1001Updates.json`）
- **选中**：**手动掩码路线**（无检测器，靠 `MaskPreview`、`LCApplyLUT` 直接给掩码）
- SAM：`sam3`、`sam_vit_b_01ec64`
- 掩码链：MaskPreview → LCApplyLUT
- **细化**（3 个细化器实例）：
  - `LCDetailPipeOut` 
  - `DetailDaemonSamplerNode` 
  - `LCSkinBeauty` 

### Krea2 ID Edit Pro Grade Character Dataset Creator w/ autotagger

- 模型 ID `2805529` ｜ 下载量 **9103** ｜ 基础模型 Krea 2 ｜ NSFW 等级 3 ｜ 共 1 张图（`krea2IDEditProGrade_v81FilenameBugFix.json`）
- **选中**（1 个检测器）：
  - `RMBG-2.0` → 抠图/背景分离（other）

### Z-Image Base & Turbo Pro Grade Realism Workflow (Low or High VRAM)

- 模型 ID `2231181` ｜ 下载量 **6100** ｜ 基础模型 ZImageTurbo ｜ NSFW 等级 15 ｜ 共 1 张图（`Lonecats ZImage Base _Turbo Realism 8.0/Lonecat's ZIT Realism 8.0.json`）
- **选中**（1 个检测器）：
  - `RMBG-2.0` → 抠图/背景分离（other）
- SAM：`sam_vit_b_01ec64`

### Workflow for your "ART"

- 模型 ID `2730327` ｜ 下载量 **5865** ｜ 基础模型 Qwen 2.1 ｜ NSFW 等级 31 ｜ 共 1 张图（`workflowForYourART_qwen21V27.json`）
- **选中**：**手动掩码路线**（无检测器，靠 手动掩码 直接给掩码）
- **细化**（1 个细化器实例）：
  - `DetailDaemonSamplerNode` 

### Lonecat's Krea2 Identity Edit & Head Swap

- 模型 ID `2803688` ｜ 下载量 **5168** ｜ 基础模型 Krea 2 ｜ NSFW 等级 15 ｜ 共 1 张图（`lonecatsKrea2Identity_v602HeadSwapRMBG.json`）
- **选中**（1 个检测器）：
  - `RMBG-2.0` → 抠图/背景分离（other）
- 掩码链：LCApplyLUT
- **细化**（1 个细化器实例）：
  - `LCSkinBeauty` 

### 简单易懂的Illustrious工作流/text2img：Simple Workflow for Illustrious(lora、fix、FaceDetailer)

- 模型 ID `1768409` ｜ 下载量 **5050** ｜ 基础模型 Illustrious ｜ NSFW 等级 31 ｜ 共 2 张图（`anima to illustrious.json`, `illustrious.json`）
- **选中**（2 个检测器）：
  - `segm/Anzhc Face seg 640 v4 y11n.pt` → 脸（segm）
  - `segm/Anzhc Eyes -seg-hd.pt` → 眼睛（segm）
- SAM：`sam_vit_l_0b3195`
- **细化**（5 个细化器实例）：
  - `FaceDetailer` guide_size=512、max_size=1024、steps=40、cfg=5、denoise=0.4、feather=60、bbox_threshold=0.5、bbox_dilation=10、bbox_crop_factor=3
  - `FromDetailerPipe` 
  - `FaceDetailer`【眼睛】 guide_size=512、max_size=1024、steps=40、cfg=5、denoise=0.6、feather=30、bbox_threshold=0.5、bbox_dilation=10、bbox_crop_factor=3
  - `FaceDetailer` guide_size=512、max_size=1024、steps=40、cfg=5、denoise=0.4、feather=60、bbox_threshold=0.5、bbox_dilation=10、bbox_crop_factor=3
  - `FaceDetailer`【眼睛】 guide_size=512、max_size=1024、steps=40、cfg=5、denoise=0.6、feather=30、bbox_threshold=0.5、bbox_dilation=10、bbox_crop_factor=3

### [Krea2 Edit] Anime2Real Workflow (Anime to Realistic)

- 模型 ID `2835514` ｜ 下载量 **4038** ｜ 基础模型 Krea 2 ｜ NSFW 等级 31 ｜ 共 1 张图（`Krea2EditAnime2real_v30DpNonAsian.json`）
- **选中**（1 个检测器）：
  - `bbox/face_yolov8m.pt` → 脸（bbox）
- SAM：`sam_vit_b_01ec64`
- **细化**（1 个细化器实例）：
  - `FaceDetailer` guide_size=1024、max_size=1024、steps=4、cfg=1、denoise=0.2、feather=5、bbox_threshold=0.8、bbox_dilation=10、bbox_crop_factor=3

### Moody Krea2 Image to Image 4KHD Workflow V1  (洗图流)

- 模型 ID `2874142` ｜ 下载量 **3044** ｜ 基础模型 Krea 2 ｜ NSFW 等级 31 ｜ 共 1 张图（`moodyKrea2ImageToImage4KHD_v10.json`）
- **选中**（1 个检测器）：
  - `bbox/face_yolov8m.pt` → 脸（bbox）
- 掩码链：SegsToCombinedMask → MaskPreview → MaskToSEGS → MaskPreview+
- **细化**（2 个细化器实例）：
  - `DetailerForEach` guide_size=1440、max_size=1440、steps=3、cfg=1、denoise=0.35、feather=100
  - `DetailerForEach` guide_size=1440、max_size=1440、steps=6、cfg=1、denoise=0.25、feather=100

## 8. 提炼出的可复用手法

1. **选中交给专用模型，别用提示词硬猜。** 脸 → `face_yolov9c`、`face_yolov8m`（全样本被引用 42 次）；手 → `hand_yolov9c`、`hand_yolov8s`；眼睛 → `eyeful_v2-paired`、`anzhc eyes -seg-hd`；头发 → `hair_seg_bigmodel_afterdetailer_v10`、`hair_yolov8n-seg_60`；人物整体 → `person_yolov8m-seg`。

2. **NSFW 器官是独立的一套体系。** 动漫 NSFW 用 `ntd11_anime_nsfw_segm_v3_all`、`pussyv2`。这类模型把女阴 / 肛门 / 乳头等**直接分割成彼此独立的区域**，再逐个喂给 detailer —— 这是「器官级细化」能成立的前提，通用检测器做不到这一点。

3. **一部件一 detailer。** 基础做法：串联多个 `FaceDetailer` / `DetailerForEach`，每个绑定不同检测器与提示词。进阶做法：改用 `ToDetailerPipe` → `EditDetailerPipe` → `FaceDetailerPipe` 管道，在管道中途改提示词。实测到的分区语法：

   ```
   [CONCAT] face, detailed face
   [CONCAT] {eyes|eyes,detailed eyes}
   [CONCAT] hand, perfect hands
   [LAB]
   [ALL] nsfw
   [NIPPLES] nsfw, nipples
   [PUSSY] nsfw, pussy
   [ANUS] nsfw, (anus)
   [PENIS] nsfw, penis
   [TESTICLES] nsfw, testicles
   ```

4. **参数照抄这个区间就对了**（下表为实测 P25 ~ P75，中位数在括号内）：

| 参数 | 含义 | 中位数 | P25 ~ P75 |
|---|---|---|---|
| `denoise` | 重绘强度 | 0.3 | 0.25 ~ 0.45 |
| `steps` | 步数 | 20.0 | 9.0 ~ 20.0 |
| `cfg` | CFG | 3.5 | 3.0 ~ 6.0 |
| `guide_size` | 裁剪放大目标短边 | 512.0 | 512.0 ~ 768.0 |
| `max_size` | 裁剪放大上限 | 1024.0 | 1024.0 ~ 1440.0 |
| `feather` | 掩码羽化 | 16.0 | 5.0 ~ 16.0 |
| `noise_mask_feather` | 噪声掩码羽化 | 20.0 | 20.0 ~ 64.0 |
| `bbox_threshold` | 检测置信度阈值 | 0.5 | 0.4 ~ 0.5 |
| `bbox_dilation` | 检测框外扩 | 10.0 | 8.0 ~ 10.0 |
| `bbox_crop_factor` | 裁剪倍率 | 3.0 | 3.0 ~ 3.0 |
| `drop_size` | 最小目标尺寸 | 10.0 | 10.0 ~ 16.0 |
| `sam_threshold` | SAM 阈值 | 0.93 | 0.9 ~ 0.93 |

5. **掩码要「养大」再重绘。** `bbox_dilation` + `GrowMask`/`GrowMaskWithBlur` + `feather` 的组合是为了避免拼接硬边；`noise_mask_feather` 中位 20.0。

6. **先放大再重绘。** detailer 内部按 `guide_size` 把裁剪区缩放到目标短边后再采样，等价于对局部做一次「超分 + 重绘」——这正是低 denoise 也能显著提升细节的原因。

7. **采样器集中在 `euler_ancestral`（20）、`euler`（19），调度器以 `simple`、`normal`、`sgm_uniform` 为主。** 细化阶段不需要复杂调度。
