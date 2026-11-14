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

## 未验证 / 限制

- 实际点击、页面打开、卡片写回动作需要人工在浏览器验收；本次只验证到"代码被加载 + 逻辑分支可执行"。
- 未改为"空输入即列全部"（`minChars: 0`）：这一项在 Vue 组件里（`vue-widgets/src/composables/useAutocomplete.ts`），需要重建 `web/comfyui/vue-widgets/` 产物；当前 fork 的 vite 构建在 `web/comfyui/autocomplete.js` 的绝对 URL 导入（`/extensions/ComfyUI-Unified-Prompt-Workbench/prompt_target.js`）上失败，属于构建配置问题，未在本次处理。直接改生成的 bundle 又会连带影响 Prompt 节点的标签候选行为，故未采用。

## 回滚依赖

还原该文件即可；不涉及数据库、后端与工作流数据。
