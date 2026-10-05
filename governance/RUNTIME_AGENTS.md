# ComfyUI 唯一主 Git 路由

这份规则只适用于 ComfyUI 相关工作，不管理此机器的其他项目。版本化原件在 `maintenance/comfyui/governance/RUNTIME_AGENTS.md`。

- **唯一开发与提交入口：本运行根下的 `maintenance/comfyui`。** 本机绝对路径为 `G:\ComfyUI-aki-v3\maintenance\comfyui`。
- 收到任何 ComfyUI 本体、插件、工作流/子图、界面、提示词库、数据库、导入器、模型加载或维护工具修改请求，先进入该主仓，读其 AGENTS、README、PROJECT_MAP 与对应专项说明。
- 源码在主仓 `snapshot/runtime/`；数据库契约/迁移在 `database/`；真实资料分片在 `snapshot/library/`。模型权重与预览原图不入 Git，仅维护清单、格式样例和放置说明。
- 运行区旧 Git 退休到仓外私有档案；不要在运行根、本体、插件或训练依赖目录重新 init/提交/拉取覆盖。上游更新也先在主 Git 评审和验证。旧历史、dirty 原件与映射必须保留，不能当废物清除。
- 运行目录是部署目标，不是另一个开发分支。修复先在主 Git 做，验证后按明确部署范围写回；保留当前哈希、队列/服务身份、数据库一致备份与回滚。主仓中的修改不得自动冒充线上已生效。
- 本地实际使用环境由主 Git 部署文件与仓外私密配置/模型/预览/最新运行数据共同组成。仓外根本机为 `G:\ComfyUI-local`；详见主仓 `docs/WORKSPACE.md` 与 `docs/EXTERNAL_STATE.md`。外部引用不是资源备份，旧资料导出也不是可覆盖在线库的授权。
- 真实提示词可保留；API key、Cookie、令牌、认证配置、插件缓存、私钥不得加入任何公开文件或历史。不得输出密钥原值；不能公开复制运行根、`maintenance`、仓外根、原始 `.git`、旧克隆或私有 bundle。
- 不凭这份路由授权重启、清队列、生图、模型下载、在线数据库替换或 GitHub 推送。只读诊断可在运行区进行；当前用户请求的部署仍须遵守主仓的保护与验收流程。
