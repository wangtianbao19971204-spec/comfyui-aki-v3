# WeiLin 法典源目录归属交付记录

日期：2026-07-30

## 最终规则

WeiLin 法典 Tags 在角色、场景、动作、服装四个 Anima 选择器中的显示分类，改为直接继承 WeiLin Prompt Selector 的原生目录：

1. 权威来源仍为：
   `WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/prompt_selector/data.json`
2. 只对以下三个法典根删除第一段：
   - `所长常规NovelAI个人法典`
   - `所长色色NovelAI个人法典(上)`
   - `所长色色NovelAI个人法典(下)`
3. 根目录后的所有 ASCII `/` 层级原样保留。
4. 全角 `／` 只是名称文字，不作为目录分隔符。
5. `默认/*`、独立 `服装`、`r18姿势`、`普通姿势` 不是这三个主法典目录，继续使用原有逻辑。

示例：

- `所长色色NovelAI个人法典(上)/后入/背后位`
  → `后入 → 背后位`
- `所长色色NovelAI个人法典(上)/后入／背后位`
  → 单个分类名 `后入／背后位`
- `所长常规NovelAI个人法典/人物形象`
  → `人物形象`

剥掉三个根以后，只有 `其他` 和 `杂项` 会发生跨法典同名合并；来源分类 ID、完整原目录和 Prompt ID 仍保留在数据中。

## 选择器归属边界

原 taxonomy 仍只负责：

- 判断一条 Prompt 属于 `pose`、`background`、`clothing`、`character` 中的哪些选择器。
- Prompt 级多选择器归属。
- 472 条既有安全隔离。
- 去重、预览图与来源追踪。

人工生成的“成人互动、体位、来源混合库、语义容量分桶”等路径不再参与法典分类显示。

不能只靠原目录名决定四选择器归属，因为当前大量来源分类和 Prompt 同时属于两个或更多选择器。

## 数据与容量

- 源数据：200 个分类、16,442 条 Prompt。
- 三个法典根：194 个分类、16,393 条 Prompt。
- 删除根后的原生层级：
  - 179 个一层目录
  - 13 个两层目录
  - 2 个三层目录
- 原生目录渲染叶节点：415 个。
- 最大原生叶节点：787 条。
- 18 个原生叶节点超过 200 条，8 个超过 300 条。

这次按用户的新决定，以源目录真实性优先，不再为了 200/300 条容量限制拆改法典目录；选择器继续使用分页浏览。

## 缓存迁移

- 四个选择器的 WeiLin 分类路径与折叠状态升级到 v2。
- 旧人工分类筛选会在首次打开时重置，避免错误选中或零结果。
- 本地分类、Traits、收藏分组不被清除。
- item ID、已选 Tags、收藏键、Prompt 文本和预览 URL 均不依赖分类路径，因此保持不变。
- 前端同时实现了源目录投影，因此当前 ComfyUI 不重启也可在 `Ctrl+F5` 后显示新结构。
- 下次正常重启 ComfyUI 后，后端也会直接输出新目录结构。

## 前后对比

| 选择器 | 条目数 | ID | Prompt | 预览 |
|---|---:|---|---|---|
| 动作 | 10,345 | 不变 | 不变 | 不变 |
| 场景 | 2,031 | 不变 | 不变 | 不变 |
| 服装 | 2,235 | 不变 | 不变 | 不变 |
| 角色 | 2,374 | 不变 | 不变 | 不变 |

## 验证结果

- 5 个相关前端脚本语法检查通过。
- 4 组 JavaScript 测试通过。
- 20 个 Python 单元测试通过。
- taxonomy 生成器 `--check` 通过。
- 源数据 SHA-256 与 taxonomy 一致。
- 所有 200 个分类均有审计结果。
- 没有未映射分类或待处理的当前 Prompt。
- 实际 ComfyUI 弹窗：
  - 动作源目录导航 165 行。
  - 服装源目录导航 121 行。
  - 三个主法典根名称出现 0 次。
  - `后入 → 背后位`两级路径筛选得到 4 张卡片。
  - `服饰`源目录筛选得到 204 条、当前页 48 张卡片。
  - 前端日志没有发现相关运行错误。
  - 验收创建的临时节点已经全部删除。

## 修改文件

- `tools/build_weilin_taxonomy.mjs`
- `data/weilin_category_taxonomy.json`
- `nodes.py`
- `js/anima_shared_prompt_data.js`
- `js/anima_character_selector.js`
- `js/anima_background_selector.js`
- `js/anima_pose_selector.js`
- `js/anima_clothing_selector.js`
- `tests/test_weilin_taxonomy_manifest.py`
- `tests/test_lora_performance_and_shared_prompts.py`
- `tests/anima_shared_prompt_data.test.mjs`

## 备份

改造前完整备份：

`G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\backups\weilin_source_directory_taxonomy_20260730_204924`

恢复说明见备份目录中的 `RESTORE.md`。
