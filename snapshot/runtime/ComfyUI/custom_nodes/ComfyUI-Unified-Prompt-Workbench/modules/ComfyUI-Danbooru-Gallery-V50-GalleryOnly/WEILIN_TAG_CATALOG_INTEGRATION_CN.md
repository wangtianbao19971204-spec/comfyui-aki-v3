# Gallery × WeiLin 分类词库整合

画廊的“词库”按钮会以只读方式联邦查询同一 `custom_nodes` 目录下的：

`WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/`

它不会把 WeiLin 的 24 万条记录复制进 `tags_cache.db`，也不会修改 WeiLin 数据库。

## 两类结果

- `atomic_tag`：不超过 120 字、最多 6 个词且不含提示词分隔符的短 tag。只有能映射到 Gallery 或 WeiLin Danbooru 规范身份的条目，才显示“加入画廊筛选”。
- `prompt_phrase`：长句、复合串、带逗号/分号/换行/权重语法的提示词。界面和 API 始终返回原始 `raw_text`，只允许逐字复制，不会把整句发送给 Booru API。

画师分类不进入整合层：Gallery `category=1`、WeiLin 子分类 77“艺术家风格”和 493“一键画师串”都会被排除。其他相似 tag 仅保留分类成员关系或官方 alias，不按中文相似度删除、覆盖或合并身份。

## API

- `GET /danbooru_gallery/tag_catalog/status`
- `GET /danbooru_gallery/tag_catalog/categories`
- `GET /danbooru_gallery/tag_catalog/search?query=&group_id=&subgroup_id=&kind=&page=&cursor=&limit=`
- `GET /danbooru_gallery/tag_catalog/item?t_uuid=`

搜索接口最大每页 50 条，返回 `has_more` 和 `next_cursor` 用于翻页。后续页按 WeiLin `id_index` 做稳定游标分页，因此大分类不受页码上限影响；画师条目也会在计数和分页之前排除，不会造成相邻页重复。`page` 仅保留给旧调用方和界面页码显示。WeiLin 未安装或数据库不可用时，接口会显式返回 `available=false`，不会回退为未核验的批量导入。

## 汉化导入边界

离线构建工具 `tools/build_weilin_gallery_integration.py` 只生成候选包，不直接写数据库。当前规则要求：

1. WeiLin 分类库中文说明、WeiLin Danbooru 中文首段、既有三方共识包三者完全同译；
2. Gallery 规范 tag、分类和现有译文为权威；
3. artist 永久拒绝，既有译文不覆盖；
4. 译名必须是最多 24 字的安全短中文；
5. 所有输入只读、记录 SHA-256，输出原子生成且拒绝覆盖。

WeiLin 公开提示词数据仓库为 MIT：
https://github.com/weilin9999/WeiLin-Comfyui-Tools-Prompt
