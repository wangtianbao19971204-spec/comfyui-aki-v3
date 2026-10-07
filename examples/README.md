# 公开格式与接入示例

这里提供网页接入、外部资源标注和私有状态组合的公开样例。
受审查的 Tag／提示词资料检查点在 `snapshot/library/`，接手看[资料库入口](../docs/technical/library/README.md)。

## 从哪里看

| 内容 | 入口 | 用途 |
|---|---|---|
| 网页提示词 | [browser-import/payloads.example.json](browser-import/payloads.example.json) | 理解五站桥接的数据格式 |
| 模型与图片 | [external-assets/README.md](external-assets/README.md) | 来源、现行路径、图片绑定和标注样例 |
| 私有状态 | [private-state/README.md](private-state/README.md) | 外部计划、实例登记和恢复边界 |
| 插件状态 | [plugin-settings/README.md](plugin-settings/README.md) | 训练器 GUI 的公开空状态格式 |

## 编辑边界

- 可以修改公开占位值、字段解释和导航；工具输入格式变更须同步对应接口与技术说明。
- 不放真实鉴权配置、密钥、Cookie、模型权重、用户预览／训练原图、数据库二进制或插件缓存。
- 先看每份说明，确认它是工具输入还是文档格式；占位值不当作正式记录。
- `null` 大小／摘要表示未测；目录引用和 SVG 占位图不能代替资源备份。

安装与换机看[开始使用](../docs/GETTING_STARTED.md)及[恢复方法](../docs/RESTORE.md)。
接口详情看[网页接入](../docs/technical/runtime/browser-import.md)、[外部资源](../docs/EXTERNAL_ASSETS.md)及[外部状态](../docs/EXTERNAL_STATE.md)。

## 更新记录

- 2026-10-07：新增目录导航，区分公开样例、真实资料检查点和仓外原件；保留子目录详细说明。
