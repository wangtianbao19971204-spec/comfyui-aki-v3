# WeiLin 全量重分类与服装选择器修复交付

日期：2026-07-30

## 交付结论

- 已修复“服装 Tag 选择器进入 WeiLin 后没有内容”的实际故障。
- 已对当前 WeiLin Prompt Selector 的 16,442 条提示词完成全量审计。
- 其中 15,970 条进入角色、场景、动作、服装四个选择器；472 条安全隔离内容继续不进入四个选择器。
- 全部可用提示词均有确定分类，未映射分类为 0，待处理提示词为 0。
- 最末级分类目标限制为 200，硬限制为 300；真实 API 最大叶子为 196，没有任何叶子超过 200 或 300。
- 没有使用 LLM、提示词正文猜测或随机数字/哈希分片。

## 1. 服装选择器修复

### 根因

旧的浏览器持久化状态同时保存了：

- WeiLin 共享集合/共享分类；
- Anima 本地服装特征，例如 `high heels`。

WeiLin 共享服装本身没有 Anima 本地 `traits` 字段，而服装选择器会把分类和特征做 AND 过滤，因此后端数据虽然已经加载，界面仍会被本地特征筛成 0 条。

### 修复

- 恢复旧筛选状态时，只要当前处于 WeiLin 集合或共享分类，就自动清除不兼容的本地特征。
- 选择任意 WeiLin 共享分类时自动清除本地特征。
- 选择本地特征时自动退出 WeiLin 独占集合，并清除共享分类条件。
- 在 WeiLin 范围内不再显示会产生冲突的本地特征复选框，改为明确提示。
- 仍保留“一键同步 WeiLin”，同步后当前分类和选择状态不丢失。

### 实机结果

- WeiLin 共享服装合并后：2,207 条。
- 默认第一页：48 张卡片和预览正常渲染。
- 实测路径：`混合服装 → 来源混合库 → 综合 → 常规法典 → 日常服`。
- 实测该叶子：120 条，分页与卡片显示正常。
- 点击“同步 WeiLin”后仍保持 120 条筛选结果。
- 点击“全部服装”后共享分类自动取消，恢复 2,637 条合并服装并重新显示本地特征筛选。
- 浏览器日志中没有 Anima/WeiLin 服装选择器错误。

## 2. 全量分类原则

最终可见结构为：

`Anima 语义分类 → WeiLin 来源集合 → WeiLin 原最次级分类 → 必要时的语义子类`

来源集合固定显示为：

- `默认`
- `常规法典`
- `色色法典上`
- `色色法典下`
- `独立分类`

保留规则：

- WeiLin 原分类名只在第一个 ASCII `/` 处分割。
- 全角 `／` 属于原分类名内容，不会被误拆；例如 `口交（类口交／颜射）` 和 `表情包／搞怪` 会完整保留。
- 可以由名称/别名明确识别时才进入语义子类。
- 无法可靠按名称判断的内容停留在原 WeiLin 最次级分类，不强行猜测。
- 只有原本会超过 200 条的 15 个叶子才增加语义子类。
- 容量拆分使用 64 个可读语义标签，例如 `近战与兵器`、`自然与户外`、`翻译条目`、`版本与元数据`。
- 不存在 `·01/02`、`分片`、`shard`、`bucket` 或哈希样式的可见分类名。

## 3. 数据与容量审计

WeiLin 源文件：

`G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\prompt_selector\data.json`

源 SHA256：

`bcec17df62b7e2d4019af4f29d010219114a9dd12acca547608428344cd00236`

分类版本：

`2026-07-30.full-v3`

| 选择器 | API 条目 | 叶子数 | 最大叶容量 | 超过 200 | 超过 300 |
|---|---:|---:|---:|---:|---:|
| 角色 | 2,374 | 179 | 164 | 0 | 0 |
| 场景 | 2,031 | 227 | 180 | 0 | 0 |
| 动作 | 10,345 | 430 | 196 | 0 | 0 |
| 服装 | 2,235 | 199 | 125 | 0 | 0 |

说明：服装 API 为 2,235 条；与 Anima 本地服装合并并按提示词去重后，界面中的 WeiLin 共享服装为 2,207 条。

额外独立审计：

- 检查 17,716 个实时分类路径。
- 缺失原 WeiLin 最次级目录：0。
- 缺失来源集合：0。
- 198 个非隔离源分类全部出现在四个 API 的联集中。
- `unmapped=0`、`pending=0`、`source_matches=true`。

## 4. 验证结果

- JavaScript 语法检查：通过。
- JavaScript 测试：4/4 通过。
- Python 全套单元测试：20/20 通过。
- 分类生成器 `--check`：通过，清单可从当前源文件确定性复现。
- ComfyUI 已使用原启动参数重启。
- `http://127.0.0.1:8188/system_stats`：HTTP 200。
- 四个共享提示词 API：HTTP 200。
- 浏览器实机服装选择器：通过。
- 测试期间创建的临时节点已全部删除。

启动日志：

- `G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\logs\weilin_full_reclass_restart.stdout.log`
- `G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\logs\weilin_full_reclass_restart.stderr.log`

启动日志里已有的 `llama-cpp_vllm`/`ggml.dll` 警告属于其他插件；`comfyui-anima-tools` 与 WeiLin Prompt Selector 均成功载入。

## 5. 修改文件

- `nodes.py`
- `js\anima_clothing_selector.js`
- `js\anima_shared_prompt_data.js`
- `tools\build_weilin_taxonomy.mjs`
- `data\weilin_category_taxonomy.json`
- `tests\anima_shared_prompt_data.test.mjs`
- `tests\test_lora_performance_and_shared_prompts.py`
- `tests\test_weilin_taxonomy_manifest.py`

未修改 WeiLin 的 `data.json` 和预览图片。

## 6. 备份与恢复

本次修改前完整备份：

`G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\backups\weilin_full_reclass_20260730_185113`

备份包含：

- 本次涉及的插件代码、测试和旧分类清单；
- WeiLin 源 `data.json` 快照；
- 文件哈希；
- 恢复说明 `RESTORE.md`。

恢复入口：

`G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\backups\weilin_full_reclass_20260730_185113\RESTORE.md`

## 7. 预览图片现状

这次只复用 WeiLin 原预览，不复制或修改图片：

- 被提示词引用的预览：15,909。
- 没有图片字段的提示词：533。
- 本地预览文件：15,881。
- 源数据引用但本地缺失：29。
- 孤立文件：1（`README.txt`）。

这 29 个缺图是 WeiLin 源目录本身的现状，不是本次分类产生的丢失。

## 8. 后续同步边界

- 已映射普通分类中的新增提示词可以通过“同步 WeiLin”增量读取。
- 新分类使用 `Anima/角色/...`、`Anima/场景/...`、`Anima/动作/...`、`Anima/服装/...` 前缀时，会按显式契约直接进入对应选择器；同时兼容全角 `／`。
- 没有上述前缀且从未审核过的全新分类不会由运行时猜测，API 会将其列为 `unmapped`。
- 原本属于混合库、必须逐条判定的新增或被修改条目会列为 `pending`，需要重新运行分类生成器审核。
- 这样可以保留一键增量同步，同时避免后续靠 LLM 或提示词正文把内容静默分错。
