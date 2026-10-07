# WeiLin 四选择器深度分类交付报告

交付时间：2026-07-30（Asia/Shanghai）

## 结论

本次改造已经完成并在正在运行的 ComfyUI 中生效。

- WeiLin 的角色、服装、场景、动作 Tags 已按固定清单关联到四个 Anima 选择器。
- 运行时不调用 LLM，也不扫描关键词重新猜分类；同步只读取版本化映射、Prompt ID、内容哈希和源分类作用域。
- 原先“未知分类落到动作”的兜底已删除。未知分类现在只进入审计结果并被跳过，不会污染任何选择器。
- 四个弹窗都支持递归二级、三级及更深分类；已实测 `成人互动 → 体位 → 后入 → 背身位`。
- 弹窗内使用“同步 WeiLin”按钮执行一次刷新，不做弹窗打开期间的轮询热更新。
- 同步后保留仍然有效的筛选和已选项，删除或改名后留下的失效选择会被清理。
- 角色选择器不再按显示名吞掉同名但 Tags 不同的 WeiLin 项，收藏和选择改用稳定来源 ID。

## 固定映射与后续同步约定

当前 WeiLin 快照：

- 源分类：200
- 源 Prompt：16,442
- 正常路由 Prompt：15,970
- 安全隔离 Prompt：472
- 混合分类：41
- 冻结 Prompt 路由：5,910
- 当前未映射分类：0
- 当前待复核 Prompt：0
- Taxonomy 版本：`2026-07-30.deep-v2`
- WeiLin 源 SHA-256：`743d8af5de17b6c2b138ebaf01c2d037007f9f3c541e462632cd4ecc994a78f8`

后续按按钮时：

1. 已映射普通分类里新增的 Prompt 自动继承固定分类。
2. 新分类使用以下显式前缀时自动同步，并保留前缀后的二、三级路径：
   - `Anima/角色/...` 或 `角色/...`
   - `Anima/场景/...`、`Anima/背景/...`、`场景/...`、`背景/...`
   - `Anima/动作/...`、`Anima/姿势/...`、`动作/...`、`姿势/...`
   - `Anima/服装/...` 或 `服装/...`
   - ASCII `/` 和全角 `／` 均支持。
3. 新增的任意无类型分类不会被猜测，会显示在 `unmapped_categories` 并跳过。
4. 现有混合分类里出现全新 Prompt，或冻结 Prompt 的 Alias/Prompt/Description 被修改，会进入 `pending_prompt_ids`，等待更新静态清单；不会静默改投其他选择器。
5. 同步按钮从后端读取最新完整快照，再在浏览器内计算新增、更新、删除数量。它是“一次手动变化同步”，不是网络层只下载差异的增量协议。

以上约定保证日常新增内容无需 LLM；真正含义不明确的分类会显式暴露，避免自动误分。

## 深度审计增补

除 200 个源分类的基础映射外，本次对混合内容逐条做了高置信度多路由增补。增补只增加正确的目标选择器，不删除原有有效归属。

- 配套原版内容：337 条
- 服装补充分流：73 条
- 动作/镜头第一批：35 条
- 动作/体位第二批：75 条
- 场景补充分流：107 条
- 角色身份补充分流：100 条
- 多身份角色 Prompt：4 条，均保留全部角色身份路径

专项修正：

- 110 条补充动作中表情误分为 0。
- 3 条明确“骑乘”内容固定到 `成人互动 → 体位 → 骑乘位`。
- 森林藤蔓内容固定到室外自然环境；两条舞台内容固定到舞台与演出。
- 19 条扶她和 3 条伪娘/男娘统一到现有 `种族与形态` 树，不再产生平行的性别分类。
- 深层示例 `成人互动 → 体位 → 后入 → 背身位` 当前包含 284 个去重后条目。

清单为确定性产物。离线生成器可以重建或检查清单，但 ComfyUI 运行时不会执行生成器中的审计规则。

## 四个 API 的实测结果

| 选择器 | 去重后 WeiLin 项 | 命中的源分类 | 未映射 | 待复核 |
|---|---:|---:|---:|---:|
| 动作 | 10,345 | 167 | 0 | 0 |
| 场景 | 2,031 | 84 | 0 | 0 |
| 服装 | 2,235 | 126 | 0 | 0 |
| 角色 | 2,374 | 89 | 0 | 0 |

四个接口均返回：

- HTTP 200
- 分类审计 200/200
- 安全隔离 472
- 静态路由 5,910
- 源哈希匹配为 true
- 手动同步使用 `Cache-Control: no-store`

浏览器缓存命中后的压缩传输实测：

| 选择器 | 压缩大小 | 响应时间 |
|---|---:|---:|
| 动作 | 2,799,086 bytes | 0.287 s |
| 场景 | 546,059 bytes | 0.058 s |
| 服装 | 463,204 bytes | 0.050 s |
| 角色 | 643,621 bytes | 0.071 s |

首次清单重建会比缓存命中慢；之后只要 WeiLin `data.json` 或 taxonomy 文件修改时间不变，后端复用内存结果。

## 预览图

- 继续直接复用 WeiLin 自带预览目录和已有预览 URL。
- 去重卡片保留全部来源 Prompt ID、来源分类路径和可用预览列表。
- 当前源数据引用 15,909 个预览文件名。
- 15,881 个预览文件实际存在。
- 533 条源 Prompt 本来没有图片。
- 29 个源侧预览引用缺文件。
- 预览目录中有 1 个未被引用的 `README.txt`。

这 29 个缺图引用和 533 个无图项是 WeiLin 当前源快照的既有状态，本次没有写入、移动或删除预览目录。

## 备份与回滚

修改前备份：

`G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\backups\weilin_deep_taxonomy_20260730_083849`

备份内容：

- 修改前的 `nodes.py`
- 修改前的共享适配器和四个选择器 JS
- 修改前相关测试
- WeiLin `data.json` 源快照
- `RESTORE.md`

校验值：

- 备份 WeiLin 源数据：`743D8AF5DE17B6C2B138EBAF01C2D037007F9F3C541E462632CD4ECC994A78F8`
- 备份 `nodes.py`：`74E84C633709143DB17504ECEAE228EB2A0345470E7EF6C9B4027FF5B4E0F235`
- 备份共享 JS：`E3EBE67DE133E3A3D4BBA7B8EE7BD7AA671776E154CFF9122A09C3302D9B2A39`

完整回滚时，按 `RESTORE.md` 将 `plugin` 下文件复制回原相对路径，并移除本次新增的：

- `data\weilin_category_taxonomy.json`
- `tools\build_weilin_taxonomy.mjs`
- `tests\test_weilin_taxonomy_manifest.py`

然后重启 ComfyUI。WeiLin 约 21.2 GiB 的预览目录没有备份副本，因为本次改造对它完全只读。

## 修改文件

- `ComfyUI\custom_nodes\comfyui-anima-tools\nodes.py`
- `ComfyUI\custom_nodes\comfyui-anima-tools\js\anima_shared_prompt_data.js`
- `ComfyUI\custom_nodes\comfyui-anima-tools\js\anima_pose_selector.js`
- `ComfyUI\custom_nodes\comfyui-anima-tools\js\anima_background_selector.js`
- `ComfyUI\custom_nodes\comfyui-anima-tools\js\anima_clothing_selector.js`
- `ComfyUI\custom_nodes\comfyui-anima-tools\js\anima_character_selector.js`
- `ComfyUI\custom_nodes\comfyui-anima-tools\data\weilin_category_taxonomy.json`
- `ComfyUI\custom_nodes\comfyui-anima-tools\tools\build_weilin_taxonomy.mjs`
- `ComfyUI\custom_nodes\comfyui-anima-tools\tests\test_weilin_taxonomy_manifest.py`
- `ComfyUI\custom_nodes\comfyui-anima-tools\tests\test_lora_performance_and_shared_prompts.py`
- `ComfyUI\custom_nodes\comfyui-anima-tools\tests\anima_shared_prompt_data.test.mjs`

## 验证结果

- Taxonomy 生成器 `--check`：通过
- Python unittest：19/19 通过
- JavaScript 测试：4/4 通过
- 生成器和五个修改 JS 的语法检查：通过
- ComfyUI 重启：成功
- `/system_stats`：HTTP 200
- `comfyui-anima-tools`：启动日志显示加载成功
- 四个共享 API：HTTP 200
- 实机弹窗：角色、服装、场景、动作均成功打开并显示 WeiLin 递归分类
- 动作深层筛选：284 项
- 按钮同步后：筛选仍选中，已选择 1 项仍保留
- 同步提示：`新增 0 / 更新 0 / 删除 0；分类审计 200/200；未映射 0；待复核 0；安全隔离 472`
- 验收产生的临时选择器节点已经全部删除，工作流恢复为原有的 LoRA 加载器节点。

重启日志：

- `G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\logs\weilin_deep_taxonomy_final_restart.stdout.log`
- `G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\logs\weilin_deep_taxonomy_final_restart.stderr.log`

启动日志中的 `triton`、`llama-cpp_vllm` 等提示来自其他既有插件；`comfyui-anima-tools` 本身加载成功。

## 晚间核验清单

1. 打开动作选择器，依次展开 `成人互动 → 体位 → 后入 → 背身位`，确认显示 284 项。
2. 在该分类选一张卡，点击“同步 WeiLin”，确认筛选仍选中且已选数量不变。
3. 打开服装选择器，确认存在 `深度补充 → 服装主题`。
4. 打开背景选择器，确认能看到室内、室外、生活与活动场景等递归分类。
5. 打开角色选择器，确认 `种族与形态` 下存在性别体征、性别表达和各类种族身份；同名但 Tags 不同的 WeiLin 项可分别搜索和选择。
6. 查看同步提示，当前应为未映射 0、待复核 0、分类审计 200/200。

