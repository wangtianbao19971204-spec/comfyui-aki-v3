WeiLin + Danbooru Gallery 完全拆分版（V52/V50）
================================================

WeiLin-Comfyui-Tools-V52-FullPromptSelector
--------------------------------------------
完整拥有 Prompt Selector：
- PromptSelector 节点与 Python 后端
- 前端界面、翻译、提示、日志和自动补全组件
- /prompt_selector/* 路由
- user_data/prompt_selector/data.json
- user_data/prompt_selector/preview/
- 使用 WeiLin 自己的 userdatas_*_danbooru.db 做标签自动补全

ComfyUI-Danbooru-Gallery-V50-GalleryOnly
-----------------------------------------
只拥有各图站搜索、标签获取和画廊相关节点。
不注册 PromptSelector 节点，不包含 Prompt Selector 前端或后端。

画廊中的“多角色编辑器”保留一个可选的共享词库读取按钮：
- 安装 WeiLin 时，它通过 /prompt_selector/data 读取词库；
- 未安装 WeiLin 时，按钮自动禁用，画廊其他功能不受影响。
这只是 API 消费，不是 Prompt Selector 的实现或存储。

数据迁移
--------
旧 data.json -> WeiLin/user_data/prompt_selector/data.json
旧 preview/* -> WeiLin/user_data/prompt_selector/preview/*
保持预览图原文件名不变。
