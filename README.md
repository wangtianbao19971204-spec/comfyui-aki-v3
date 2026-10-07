# ComfyUI 统一维护仓

这里保存 ComfyUI 源码、插件、工作流、真实提示词资料检查点和维护工具。所有相关修改都从这个 Git 开始。

**完整运行实例 = 已部署的 Git 文件 + 仓外私有状态**。私有状态包括配置、模型/LoRA、图片、运行环境和最新数据库；它们另行保存，Git 提供来源、放置说明和示例。

## 从这里开始

| 你要做什么 | 入口 |
|---|---|
| 第一次拉取、准备本机工具 | [开始使用](docs/GETTING_STARTED.md) |
| 看文件结构、找到对应源码 | [项目地图](docs/PROJECT_MAP.md) · [快照目录](docs/SNAPSHOT.md) |
| 修改、测试、提交、合并和同步 | [日常维护](docs/MAINTENANCE.md) |
| 换机器、恢复资料、补模型和图片 | [恢复方法](docs/RESTORE.md) · [模型来源](docs/MODEL_SOURCES.md) |
| 深入读一项功能、交给 AI 接手 | [技术目录](docs/technical/README.md) · [维护规则](AGENTS.md) |
| 了解现有问题、验证过哪些项目 | [已知问题](docs/KNOWN_ISSUES.md) · [文档导航](docs/README.md) |

## 文件结构

```text
comfyui/
├─ README.md             本页：项目介绍与阅读入口
├─ AGENTS.md             AI 与维护者共同遵守的规则
├─ snapshot/             源码、工作流、真实资料检查点及清单
│  ├─ runtime/           本体、插件、工作流和运行工具
│  ├─ library/           提示词、SQL、模板和旧资料检查点
│  ├─ inventory/         模型来源、环境和媒体登记
│  └─ evidence/          捕获时的验收记录
├─ database/             数据库结构、契约、迁移登记和虚构样例
├─ scripts/              维护工具；从 maintain.py 开始
├─ tests/                维护工具的隔离测试
├─ examples/             外部资源和私有状态的公开格式示例
├─ governance/           版本、审核和保留规则
├─ docs/                 操作指南、功能说明和历史记录
├─ .githooks/            本地提交/上传门禁
├─ .github/              GitHub 仓库检查
└─ CHANGELOG.md          维护更新记录
```

各目录的简短自述见 [文档](docs/README.md)、[工具](scripts/README.md)、[测试](tests/README.md)、[数据库](database/README.md)、[示例](examples/README.md)、[治理](governance/README.md)、[本地门禁](.githooks/README.md)、[GitHub 检查](.github/README.md)。

## 维护与运行

先在本地分支修改并验收，再上传 GitHub、通过 PR 合入 `main`，最后同步本地主线。助手只在用户已授权的范围内处理合并；Git 合并与运行区部署分别验收。线上主仓：[comfyui-aki-v3](https://github.com/wangtianbao19971204-spec/comfyui-aki-v3)。

运行目录接收明确范围的部署；最新应用资料保留在运行区。首次 clone 后按恢复指南补齐环境与私有资源，不直接运行快照、不用旧检查点覆盖现有数据库。

模型权重、真实原图、凭据和原始私有 Git 不上传。拉取者可从[私有状态示例](examples/private-state/README.md)建立自己的组合；引用清单不代表资源已经备份。详细边界见[工作区](docs/WORKSPACE.md)、[外部状态](docs/EXTERNAL_STATE.md)与[安全/许可说明](docs/SECURITY.md)。
