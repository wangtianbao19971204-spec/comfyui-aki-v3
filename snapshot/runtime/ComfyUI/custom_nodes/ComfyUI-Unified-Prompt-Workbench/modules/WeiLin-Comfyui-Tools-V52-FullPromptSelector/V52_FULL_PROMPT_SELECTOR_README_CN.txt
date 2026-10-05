WeiLin-Comfyui-Tools V52 - Prompt Selector 完整归属版
=====================================================

本版本中 Prompt Selector 已完整迁入 WeiLin：

后端：
- PromptSelector 节点类与 NODE_CLASS_MAPPINGS
- /prompt_selector/* 全部读写、导入导出、预览图和批量操作接口
- user_data/prompt_selector/data.json
- user_data/prompt_selector/default.json
- user_data/prompt_selector/preview/

前端：
- js_node/prompt_selector/prompt_selector.js
- 独立的提示、日志、多语言与自动补全组件
- 不再导入图库插件的 js/global/*

自动补全：
- 使用 WeiLin 自己的 userdatas_*_danbooru.db
- 接口为 /weilin_prompt_selector/autocomplete*
- 不调用 /danbooru_gallery/*

兼容性：
- 节点键仍为 PromptSelector，旧工作流无需替换节点
- 原 /prompt_selector/* 地址保持不变
- 删除或更新 ComfyUI-Danbooru-Gallery 不会影响 Prompt Selector

旧数据迁移：
将旧 data.json 与 preview/ 复制到：
WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/prompt_selector/
