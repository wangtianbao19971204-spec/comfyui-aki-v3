WeiLin + Danbooru Gallery 独立拆分版（V51/V49）

职责划分
========
1. WeiLin-Comfyui-Tools-V51-PromptStore
   - 管理提示词共享库 data.json
   - 管理所有提示词预览图 preview/
   - 管理 data.json 自动备份
   - WeiLin 共享预设面板从这里读取

2. ComfyUI-Danbooru-Gallery-V49-CivitaiTagsFix
   - 管理 Danbooru / Gelbooru / Yande.re / Civitai 图库功能
   - 不再保存用户词库和预览图

唯一正确的预览图目录
====================
ComfyUI/custom_nodes/WeiLin-Comfyui-Tools-V51-PromptStore/
└─ user_data/
      ├─ data.json
      ├─ default.json
      └─ preview/

迁移
====
把旧插件中的 data.json 和 preview/ 移到上面的 WeiLin 目录。
data.json 中的 image 字段只保存文件名，因此必须保留原预览图文件名。

兼容说明
========
如果找不到 WeiLin，图库只会创建临时兼容存储，并在控制台显示 gallery-fallback；
