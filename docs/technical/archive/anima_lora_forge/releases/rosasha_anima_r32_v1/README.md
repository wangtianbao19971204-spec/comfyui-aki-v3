# 罗莎莎 Anima LoRA v1

- 文件：`rosasha_anima_r32_v1.safetensors`
- 底模：Anima Base v1.0
- 触发词：`rsrs_anima`
- Rank / Alpha：32 / 16
- 选中 checkpoint：400 steps（约 3.3 dataset epochs）
- 建议强度：`0.8–1.0`，默认从 `0.9` 开始
- SHA256：`3B3679BFC88D4A4187F4318093917C8AB7C1C37F6B9CC2CF6535FAA0EB803834`

## 使用原则

触发词主要控制人物身份、发色、绿眼、单侧马尾、黑蝴蝶结和矮小体型。
服装和画风应在 prompt 中显式指定，以保留多服装、多风格能力。

每次人物全身预览都应明确加入 `fully clothed` 和具体服装；不要只写触发词。

## 推荐起始 Prompt

```text
rsrs_anima, one 23-year-old adult Lalafell woman,
very short compact four-head-tall fantasy proportions,
emerald green eyes, honey-gold fluffy curls,
one high side ponytail with one large black ribbon,
fully clothed, full body
```

详细服装模板见 `prompt_pack.txt`，审核结果见 `evaluation_report.md`。

