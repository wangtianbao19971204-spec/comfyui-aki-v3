# 唯一来源、现场比较与归档

文档修订：2026-10-05.1。

## 权威与组成

只有本主 Git 是 ComfyUI 代码/工作流/结构/维护技术的开发来源。[WORKSPACE](../../WORKSPACE.md)定义运行部署区和仓外普通私有资料区。私有资料区没有统一开发 `.git`，不是自动加密仓；其历史原 Git、bundle 和验证 clone 只能作档案或验证，不继续开发。

真实运行环境等于已部署的受审查主仓文件，加上私密配置、模型、预览、环境和应用最新数据。应从现有运行事实核验缺漏，但不能日常将现场反向覆盖还未部署的主仓代码。

## 实现链

[snapshot.py](../../../scripts/snapshot.py)负责捕获、哈希和离线物化；[project.py](../../../scripts/project.py)管理源码 seal 与只读部署计划；[external_state.py](../../../scripts/external_state.py)管理私密 overlay 和资源引用；[workspace_guard.py](../../../scripts/workspace_guard.py)保存生产保护；[archive_workspace.ps1](../../../scripts/archive_workspace.ps1)按 review SHA 执行可恢复移动。

历史技术归档与元数据记录只作为研究/实现备份，不能执行旧脚本里的固定 PID、路径或时间。只有代码与必要输入/环境都满足，才可能完整重演；缺 fixture/原网页/训练图时必须明确写出。

[technical_archive.py](../../../scripts/technical_archive.py)使用显式选单、来源 SHA、仓外 review 和二次核验保留技术原件，不移动/删除源、不改生产。训练触发词的 18 项误报由 [独立审核登记](../../../governance/training-trigger-reviews.json)限定精确路径/字节和单条规则；[专项测试](../../../tests/test_training_trigger_reviews.py)验证 index/HEAD、漂移、强密钥及别名拒绝。硬链接源不复制，留作仓外引用；不能为凑齐文件数降低门禁。

## 验证与备份边界

源码比对和目录清单不会复制权重/预览，不是整机灾备。[外部样例](../../EXTERNAL_ASSETS.md)保存格式与放置说明。可重建缓存不包括不可随意删除的提示词预览绑定、收藏、备注或原始训练数据。

可恢复归档不释放同盘空间；Metadata 验证只检查路径/大小/mtime/链接，不等于内容 SHA。未审核或被凭证门禁拒绝的历史文件保留私有原件，不为凑齐数量放入公开图。

## 更新记录

- 2026-10-05：仓外计划补齐训练/研究资料与本机启动依赖的位置引用；仅为 Qwen 实验环境三条精确配置路径增加 `private_config` + `reference` 校验，拒绝复制、改类、路径别名及公共源码遮盖。使用隔离 fixture 验证，不读取/输出真实配置值，不复制目录资源，不把位置清单称为备份或运行验收；既有 v2/v3 计划保留。
- 2026-10-05：完成旧工作 Git 退休与仓外引用基线；追加审查旧 benchmark 技术实现遗漏、现行标准与历史文档层级。
