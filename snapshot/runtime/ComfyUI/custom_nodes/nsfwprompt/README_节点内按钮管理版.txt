PromptSelector 节点内按钮管理版

这版不再依赖右下角悬浮按钮。

安装：
1. 建议删除/移走旧的 nsfwprompt 目录中的旧文件，或直接完整覆盖。
2. 把本文件夹放到 ComfyUI/custom_nodes/ 下，或者把本包里的 __init__.py、NSFWPromptSelector_LocalMerged.py、web 文件夹完整复制到你的 nsfwprompt 目录。
3. 必须保留 web/promptselector_node_button_manager.js；只复制 .py 不会出现节点内按钮。
4. 完全重启 ComfyUI，并在浏览器按 Ctrl+F5 强刷新。

节点：
- NSFW 提示词选择器 · 使用版：只负责选择标签并输出提示词。
- PromptSelector 标签管理器 · 点开面板：拖到工作流后，节点内部会出现“打开管理面板”“独立页面打开”“刷新管理数据”三个按钮。

管理方式：
- 点击“打开管理面板”：在 ComfyUI 内弹出管理面板。
- 点击“独立页面打开”：打开 /promptselector_direct_manager/page。
- 也可以右键使用节点，选择“打开 PromptSelector 标签管理面板”。

保存：
- 面板里点“保存写回PY”会写回当前 NSFWPromptSelector_LocalMerged.py，并自动生成 .bak。
- 写回后需要重启 ComfyUI，重新添加使用节点，才能刷新下拉列表。

如果节点内按钮没有出现：
- 检查 __init__.py 是否包含 WEB_DIRECTORY。
- 检查 web/promptselector_node_button_manager.js 是否在节点文件夹内。
- 打开浏览器开发者工具 Console，搜索 [PromptSelector] Node-button manager extension loaded。
- 可手动打开：http://127.0.0.1:8188/promptselector_direct_manager/page


随机功能修复说明
----------------
本版将“随机模式”和“随机种子”移动到使用节点顶部。
随机模式包括：关闭、仅空分类随机1个、每类随机1个、随机3个、随机5个、随机10个、随机20个、场景随机、动作随机、服装随机、镜头随机、全部随机。
随机种子 = 0 时，每次执行都会重新随机；随机种子为非 0 时，随机结果固定，便于复现。
如果修改管理数据并写回 PY，仍然需要重启 ComfyUI 后重新添加使用节点，才能刷新下拉选项。
