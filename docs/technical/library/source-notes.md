# 原站来源说明与个人备注

2026-11-01：资料与 Tag 详情新增共用的只读“来源说明”。原站维护的说明保存在结构化来源版本中，个人 `description`、收藏备注及 Tag `notes` 继续独立保存。

## 实现链

- 唯一投影：`W/prompt_selector/source_notes.py`，由 `tag_api.py` 注册 `GET /prompt_selector/source-notes?resource_id=…`。资源沿原生单跳 canonical 映射，Tag 按 UUID 只读查询。此路由不改变任何个人字段或修订号。
- 唯一显示组件：统一包 `web/source_notes.js`。Tag 管理详情与 `zz_tb_shared_preset_manager.js` 的资料详情各有一个挂点；关闭详情会取消旧请求。
- 每个 `dataset + entry_id` 的最后来源版本优先，完整 `raw_entry.note` 优先于旧扁平字段。最新版本清空说明时，不恢复旧说明；不同来源分别展示。
- 使用文本节点及换行显示，不解析来源 HTML。链接仅允许原站 HTTPS，不显示哈希、发布号或内部 ID。说明不用 `pre` 元素，资料的“全选正文/复制正文”仍只作用于原正文。

路径缩写沿用[资料库索引](README.md)。本功能仅在详情中显示来源说明，没有扩展全文搜索，不将来源文字拼入个人描述，也不自动采用来源正文。

## 验证与边界

`tests/test_source_notes.py` 覆盖旧字段、完整原文优先、空说明删除、多来源、链接过滤、Tag 只读和 canonical 归属；`tests/test_source_notes_ui.mjs` 覆盖字面显示、取消、过期响应和重试。既有 Tag 身份与编辑保存回归继续执行。

[中性预览夹具](../../../examples/source-notes/preview.html)包含虚构来源说明、独立个人备注及正文选择按钮；隔离预览时把夹具与主仓 `web/source_notes.js` 放在同一全新目录，仅通过本机只读 HTTP 服务访问。它用于组件布局检查，不代替原生工作台的最终验收。

历史资料修复与 UI 可见性分别签收。2026-11-01 13:19 的受控发布已签收；真实浏览器核对所长 2062/2063 两条来源说明、Tag 详情、关闭重开及复制/全选正文，个人备注独立、正文逐字相同且未混入说明。三张截图及完整 UI/HTTP 收据保留在私有发布批次，公开 Git 只保存代码、合成样例与范围摘要；本轮没有生成或 GPU 画质验收。

## 更新记录

- 2026-11-01：新增只读来源说明投影、共用详情组件、隔离样例与 Python/JS 验证。原站信息与个人备注分别保存；实际部署及浏览器结果见[法典维护记录](../changes/library-web-import/2026-11-01-current-source-delta.md)。
