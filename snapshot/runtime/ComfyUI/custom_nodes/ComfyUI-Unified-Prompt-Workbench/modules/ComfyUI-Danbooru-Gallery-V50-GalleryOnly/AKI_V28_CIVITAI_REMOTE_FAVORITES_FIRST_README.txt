AKI V28 - Civitai 收藏夹优先远端读取

修复点：
- v27 中 civitai:favorites 可能仍然走本地收藏，导致远端收藏夹有内容但插件显示 0 张。
- v28 改为：只要设置里保存了 Civitai.red Copy as cURL / Request Headers 且解析到 Cookie，civitai:favorites 就优先调用远端 image.getInfinite 读取收藏夹内容。
- 如果远端读取失败，才回退到本地 Civitai 收藏快照。

测试：
1. 设置里粘贴 Civitai.red Copy as cURL。
2. 点“测试远端收藏”，确认能读到收藏夹名。
3. 主界面来源选 Civitai，点收藏夹按钮或输入 civitai:favorites。
4. C诊断里应看到 calls.label = remote_collection，而不是 local_civitai_favorites。
