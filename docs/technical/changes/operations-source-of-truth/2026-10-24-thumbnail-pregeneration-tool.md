# 新增离线缩略图预生成维护工具（2026-10-24）

- 背景：生产 `user_data/prompt_selector/preview` 有 152,161 张预览图，而 `preview_thumbnails` 只有 39,630 个；约 74% 的 Tag 卡片首次显示需现场生成缩略图（旧管线 25–28 ms/张、服务端并发 2）。
- 新增 `scripts/pregenerate_preview_thumbnails.py`（独立于 ComfyUI 运行）：按现有 `sha1(filename).webp` 命名与源文件 mtime 新鲜度规则补齐缺失/过期缩略图；只写 `preview_thumbnails/`，tmp+`os.replace` 原子写、可中断续跑；默认 **dry-run**，必须 `--apply`；`--root/--limit/--jobs/--resume/--fast/--progress-every` 参数化。`--fast` 走新的 draft+快速 WEBP 管线（默认档与服务器现管线输出字节一致）。
- 自测：仓外临时目录 8/8 用例（dry-run 不写、apply 契约、幂等、缺失/过期补齐、limit+resume、损坏图退出码 1 且无半写、默认根不存在时安全退出码 2）。
- 预估：仅补 11.25 万张 `--fast --jobs 4` 约 6.5–8 分钟、磁盘 +2.0–2.2 GB；全量 15.2 万张约 12–18 分钟。
- 边界：默认不写运行区，生产使用需显式 `--apply` 与用户授权；本次未对生产执行。缩略图管线本身的加速见 [工作台交互延迟优化](../runtime-workbench/2026-10-24-workbench-interaction-latency.md)。
