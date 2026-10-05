# 罗莎莎项目

这是可运行的示例角色项目。当前定位是建立 `8–12` 张黄金种子图并训练临时
LoRA v0；正式 Dataset v1 和 LoRA v1 应在 v0 压力测试之后继续。

`01_visual_spec/visual_spec.json` 仍是草案，已明确标出未决项。机器筛选结果会放
进某次 `runs/<run_id>/machine_gold`，只有执行 `promote` 或 `--auto-promote`
才会复制到 `03_seed_v0`。

两张工作簿内嵌图已经作为初始参考：

- `rosasha_master_fullbody.png`：比例、服装、枪套；
- `rosasha_cooking_scene.png`：脸部、气质、料理情境。

参考图中的玫瑰背景、构图和料理道具不是永久身份特征。
