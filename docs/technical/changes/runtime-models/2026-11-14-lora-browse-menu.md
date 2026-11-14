# 2026-11-14 LoRA 节点增加"打开 LoRA 管理器（写入本节点）"入口

## 改了什么

`modules/comfyui-lora-manager/web/comfyui/lora_loader.js`：

- 引入 `openLoraBrowserForNode`（来自同模块 `workflow_targets.js`，原本已实现但没有任何入口调用它）；
- 在 LoRA Loader / Lora Stacker / WanVideo Lora Select / Create Hook LoRA 的右键菜单里，`Active Filters Search` 之上新增一项「打开 LoRA 管理器（写入本节点）」，调用 `openLoraBrowserForNode(this)`；
- 打开失败（例如节点所在分支未启用）时用 `showToast` 报错，不再静默。

## 为什么

节点里的 LoRA 栏是搜索框（`autocomplete.js` 默认 `minChars: 1`），只能边打边选，看不到整库缩略图。插件其实已经有"页面浏览 → 定向写回节点"的完整链路（`workflow_targets.js` 生成 `/loras?lm_target=…&lm_token=…`，页面侧 `static/js/utils/workflowTarget.js` 显示"写入目标"徽标，`/api/lm/register-nodes` 负责登记节点与 token），只是没有按钮去触发。补这个入口比改 autocomplete 更稳，也不需要重建 Vue 产物。

## 验证了什么

- `node --check` 通过；8188 实际返回的 `/extensions/comfyui-lora-manager/lora_loader.js` 字节数（12309）与磁盘一致，并且包含新增菜单文案的 UTF-8 字节序列——说明改动已被服务端加载。
- 菜单注入沿用同文件已有的 `getExtraMenuOptions` 写法，与 `Active Filters Search` 同层，不新增节点 widget，因此不改变 `widgets_values` 序列化或既有工作流。

## 同批完成：修好 Vue 产物构建 + 空栏即可浏览

原先这条改不动，是因为 `vue-widgets` 的 vite 构建在 `web/comfyui/autocomplete.js` 的绝对 URL 导入上失败：

```
Rollup failed to resolve import "/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js"
```

处理：

1. `vue-widgets/vite.config.mts`：在 `lora-manager:keep-runtime-modules-external` 插件里增加一条规则——以 `/extensions/` 开头的 specifier 直接 `external: true`。这类地址本来就应该由浏览器在运行时解析（工作台那份 `prompt_target.js` 只在运行期存在），构建期不该解析。
2. 加 `output.inlineDynamicImports: true`：这份产物是作为单个扩展脚本被加载的，不能拆出需要相对路径再取一次的 async chunk。产物恢复为单文件 `lora-manager-widgets.js`（705 KB）+ sourcemap。
3. `vue-widgets/src/composables/useAutocomplete.ts`：`minChars` 按 modelType 区分——`loras` 用 **0**（点进空栏即列出库，缩略图悬停可见，每页 20 条、滚动续载），`prompt` 保持 **1**（不影响标签补全的打字手感）。

验证：

- `npm run build` 成功：118 modules，单文件 705 KB；产物里存在 `minChars: modelType === "loras" ? 0 : 1`
- `vue-widgets` 单测 **96 passed (7 files)**（含 `AutocompleteTextWidget.test.ts`）
- 8188 实际返回的 `/extensions/comfyui-lora-manager/vue-widgets/lora-manager-widgets.js` 为 705414 字节，且字节级包含上述三元表达式——重建产物已被服务端加载
- `node --check` 通过（右键菜单那处改动）

## 未验证 / 限制

- 浏览器里的实际交互（空栏列表、悬停预览、滚动续载、卡片写回节点）仍需人工点验；本次只验证到"构建成功 + 单测通过 + 产物被加载 + 逻辑字节正确"。
- 重建产物与仓库里原先那份不是同一次构建（依赖版本有小幅上浮），单文件结构与模块内联方式保持一致；若前端出现异常，可用仓库上一版 `lora-manager-widgets.js` 直接回退。

## 回滚依赖

还原上述 4 个文件（`vite.config.mts`、`useAutocomplete.ts`、`lora-manager-widgets.js`、`.map`）与 `lora_loader.js` 即可；不涉及数据库、后端与工作流数据。
