ComfyUI-Danbooru-Gallery V50 - 纯画廊版
==========================================

本版本已彻底移除 Prompt Selector：
- 不注册 PromptSelector 节点
- 不注册 /prompt_selector/* 后端路由
- 不包含 Prompt Selector 前端 JS、翻译字典或用户数据
- 不读取或写入 WeiLin 的提示词库

画廊插件只负责 Danbooru / Gelbooru / Yande.re / Civitai 等图站搜索、标签和图库界面。
Prompt Selector 的完整前端、后端、自动补全、data.json 与 preview/ 均归 WeiLin V52 管理。

两个插件可以同时安装，也可以只安装其中一个；删除本画廊插件不会影响 Prompt Selector。
