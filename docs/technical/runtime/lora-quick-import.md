# 新下载 LoRA 快速整理

把 Downloads 中的新 LoRA 按“家族／用途”命名、移进 ComfyUI，并登记来源与工作台卡片。只处理新增文件，重复原件保留。

在主仓的独立开发分支中，保持 ComfyUI 已启动、生成队列为空，执行：

```powershell
.\scripts\Import-DownloadedLoras.ps1 -Apply
```

去掉 `-Apply` 只看计划。完成后刷新工作台页面即可选用；无需重启。上传的是来源清单、工具与说明，权重、侧车、预览、缓存及私有收据不进 Git。

流程：本批完整摘要 → 排除重复 → 查询确切 Civitai 文件 → 分类命名 → 校验跨盘复制 → 单项登记／加载器核验 → 移除已成功导入的下载原件 → 更新公开来源目录。官方版本的底模字段决定家族，名称中的跨家族字样不改变它；服装／制服和画风关键词用于用途，无法判断的留在“其他与待核”。来源未匹配、文件仍在下载或身份不明时跳过并显示原因。

Python 3.11+ 的可移植入口：

```powershell
python -X utf8 -B scripts/import_lora_downloads.py --downloads '<下载目录>' --runtime '<运行根>' --apply
```

`--api` 只允许本机服务；`--cache-db` 可指定当前 LoRA Manager SQLite；`--evidence-root` 可指定仓外收据根；`--categories` 接受“完整 SHA256 → 用途”的已核对 JSON。默认收据在本机 LocalAppData 的 `ComfyUI-LoRA-Imports`，每次使用新子目录。来源页、版本、文件 ID、原文件名和完整摘要见[公开下载表](../../MODEL_SOURCES.md)；命名规则见[分类说明](../../MODEL_NAMING.md)。

不会覆盖既有同名文件，也不会批量迁移旧模型、重建全库、改变收藏／备注／排除或保存工作流。SQLite 使用一致 backup 留存；中断时按 `journal.jsonl` 和 `completed-assets.json` 核对本批文件，再恢复来源登记，不能用旧库覆盖在线库。若存在半完成目标，停止重复导入，人工核对摘要和卡片；未完成卡片／加载器核验前保留下载原件。复制后的内容摘要验证属于路径验收，未代表 GPU 推理通过。新卡片只尝试确切版本的官方静图缩略图，失败不阻断权重导入；`--no-preview` 可跳过。此批插件下载器报告离线，三项预览尚未取到，后续可用管理器“获取”补图。

实现：[Python 导入器](../../../scripts/import_lora_downloads.py)、[一行入口](../../../scripts/Import-DownloadedLoras.ps1)。测试：[保护与来源回归](../../../tests/test_import_lora_downloads.py)。

## 更新记录

- 2026-10-09：提炼日常增量导入流程，复用现行命名规则和单卡片登记，避免新下载等待全库迁移。检查 15 个下载，12 个完整摘要重复，新增 3 个确切来源；具体现场结果见[本批收据](../../receipts/lora_quick_import_20261009.json)。上传门禁和 PR 验收另行执行。
