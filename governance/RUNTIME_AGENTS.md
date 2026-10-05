# ComfyUI 唯一主 Git 路由

这份规则只适用于 ComfyUI 相关工作，不管理此机器的其他项目。版本化原件在 `maintenance/comfyui/governance/RUNTIME_AGENTS.md`。

- **唯一开发与提交入口：本运行根下的 `maintenance/comfyui`。** 本机绝对路径为 `G:\ComfyUI-aki-v3\maintenance\comfyui`。
- 收到任何 ComfyUI 本体、插件、工作流/子图、界面、提示词库、数据库、导入器、模型加载或维护工具修改请求，先进入该主仓，读其 AGENTS、README、PROJECT_MAP 与对应专项说明。
- 源码在主仓 `snapshot/runtime/`；数据库契约/迁移在 `database/`；真实资料分片在 `snapshot/library/`。模型权重与预览原图不入 Git，仅维护清单、格式样例和放置说明。
- 运行根的 `ComfyUI/.git` 与统一工作台旧 `.git` 仅作为私有历史/现场差异/回滚来源。不要在这两处继续开发、提交、拉取覆盖或把未提交版本当废物清除。
- 运行目录是部署目标，不是另一个开发分支。修复先在主 Git 做，验证后按明确部署范围写回；保留当前哈希、队列/服务身份、数据库一致备份与回滚。主仓中的修改不得自动冒充线上已生效。
- 真实提示词可保留；API key、Cookie、令牌、认证配置、插件缓存、私钥不得加入任何公开文件或历史。不得输出密钥原值；不能公开复制 `maintenance` 整目录、原始 `.git`、旧 bundle 或 private-archives。
- 不凭这份路由授权重启、清队列、生图、模型下载、在线数据库替换或 GitHub 推送。只读诊断可在运行区进行；当前用户请求的部署仍须遵守主仓的保护与验收流程。
