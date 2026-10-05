# 部位检测层升级 + Anima 部位细化链

- 当前修复版本：`runs/20261004_repair_audit/REPORT.txt`，验收状态以同目录 `FINAL_DELIVERY.json` 为准。
- UAP、发布模板、独立扩展已就地修复；前端增加批量与 LLLite 兼容性保护。保留九个工作流分支，所有细化默认关闭。
- 当前部位顺序：手 → 脚 → 区域标准/快速（二选一）→ 脸 → 眼 → 可选 1.5× 二放。没有人体、头发、四肢、服装或独立皮肤细化。
- 新验收：静态全图检查、隔离浏览器交互、2.9B 中性四部位 + USDU 实跑。不是九个生产分支全部端到端重跑；脚在靴子样例上无检出，成人区域没有本轮生成验收。

以下交付、模型和蒙版数据为初次升级的历史记录，不是当前文件统计或当前全链验收。

## 交付

- `检测模板_05_脸手眼_仅蒙版.json` — 22429 B
- `检测模板_06_人体服装皮肤_仅蒙版.json` — 24928 B
- `检测模板_07_脚_仅蒙版.json` — 7012 B
- `生产扩展_10_部位细化_Anima.json` — 50234 B

## 模型

- `face_yolov9c.pt` — 49.3 MB
- `hand_yolov9c.pt` — 49.2 MB
- `Eyeful_v2-Individual.pt` — 21.5 MB
- `adetailerFootYolov8x_v20.pt` — 130.4 MB
- `ntd11_anime_nsfw_segm_v5-variant1.pt` — 19.6 MB
- `deeplabv3p-resnet50-human.onnx` — 45.0 MB
- `model.safetensors` — 180.3 MB
- `config.json` — 0.0 MB
- `preprocessor_config.json` — 0.0 MB

## 蒙版实测

- **检测模板_05 (f_front.jpg)**：face 7.12%，hand 5.06%，eye 0.76%，combined 12.18%
- **检测模板_06 (clothed.jpg)**：clothes 34.90%，person 50.75%，skin 16.04%，hair 8.67%，limbs 0.00% (full clothing)
- **检测模板_06 (f_front.jpg)**：hair 7.69%，limbs 35.87%，clothes 6.82%，person 69.05%，skin 65.59%
- **检测模板_07 (towel_front.png)**：feet 1.70% (2 boxes)
- **生产扩展_10 (f_front.jpg)**：runtime_s 517，changed_pixels_gt8 7.94%，detections {'face': 1, 'eye': 2, 'hand': 1, 'foot': 0, 'nsfw': 4}
- **segformer_b2_clothes anime check (model-level)**：f_front.jpg Hair 7.5%, Left-leg 15.4%, Right-arm 12.4%，f_rear.jpg Hair 8.6%, Right-leg 12.0%，clothed.jpg Hair 8.7%
- **deeplabv3p LIP anime check (why BodySegment was dropped)**：clothed.jpg Hair 0.11%, Left-arm 0.01%, class10 'Torso-skin' 0.03%

## 关键发现

- `segformer_b2_clothes` 自带 Hair / 左右臂 / 左右腿，动漫图可用（头发 3–9%，四肢 1–15%）——此前「无可用检测器」的判断已更正。
- `deeplabv3p LIP` 的 `Torso-skin` 实为 LIP class 10 = Jumpsuits，不是皮肤；该模型动漫图整体失效，已移除。
- 皮肤改用派生蒙版（人体前景 − 服装），实测 16.04%。
- 全网 32 个工作流中，人体遮罩层只占 12%，且集中在一个作者；部位细化主流是 脸/NSFW/眼/手 四区。

## 回滚

当前修复是就地修改，不能通过删除旧 deliverables 回滚。使用 `runs/20261004_repair_audit/rollback.py`，默认只检查哈希；`--apply` 才恢复备份，遇到后续改动会拒绝覆盖。不会删除模型、资料库或工作流目录；不恢复已移除的不安全正向样例。
无核心/插件代码改动，未重启服务，未清队列。
