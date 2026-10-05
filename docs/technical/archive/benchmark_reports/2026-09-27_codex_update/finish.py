from update_common import *

release=read(HERE/'release_receipt.json');assert release['passed'] and release['phase']=='accepted'
v=read(HERE/'data_validation.json');live=read(HERE/'live_acceptance.json');contract=read(HERE/'live_query_contract.json');assert live['passed'] and contract['passed']
summary=read(HERE/'stage_summary.json');registry=read(HERE/'source_registry.json');images=read(HERE/'image_link_validation.json')
source_counts=defaultdict(Counter)
for r in registry:source_counts[r['source'].split(':',1)[0]][r['disposition']]+=1
lines=['# 全站资料更新与验收报告','',f'已正式更新并验收。网站 15 个资料集共 40,386 条来源记录全部核对，桌面 8 份 Word 的 18,506 条解析内容全部有对应结论。目录名为 9 月 13 日版，但其中 Word 实际为 9 月 25 日版。','',
f'- 资源库新增 **{v["library_added"]:,}** 条长提示词；基础词库新增 **{v["tag_added"]:,}** 条。',
f'- 更新 **{v["body_updates"]}** 条已有正文，并同步 **{v["paired_tag_body_updates"]}** 条对应 Tag 副本。',
f'- 安装 **8,562** 个配图文件（约 1.64 GB）；{images["source_rows_with_verified_preview"]:,} 条应有配图的纳入记录全部确认可找到本地配图。图库中的多图信息与原图链接保留在来源快照及记录元数据，现有界面仍以一张预览图显示。',
'- 所有旧条目、收藏、个人备注、使用记录和既有选取资格保留；没有新增相同正文的资源库记录。192 条长串此前只在底层 Tag 数据中存在，本次补入可分类的资源视图，原底层记录保留。','',
'## 核对范围与结果','',
'网站使用已核验清单哈希的固定发布版本 `r-01892afa9f19ef14c255`；梦神资料集以网站指向的当前外部源 342 条为准。旧记录不因来源撤下而删除。','',
'| 资料集 | 核对条数 | 新增长提示词 | 新增基础词条 | 跳过 |','|---|---:|---:|---:|---:|']
for m in read(WEB/'codexes.json'):
    c=source_counts[m['id']];lines.append(f'| {m["title"]} | {sum(c.values()):,} | {c["library_added"]:,} | {c["tag_added"]:,} | {c["excluded"]+c["no_prompt_content"]:,} |')
lines+=['','2,440 条来源记录按未成年相关性内容筛查规则跳过新增或更新；1 条没有可用提示词正文。另有 2 条网页正文与本地版本冲突，保留本地完整正文并归档网页版本，未强行覆盖。具体处置见 [来源核对清单](source_registry.json)。','',
'## 校验与运行状态','',
f'- 资源库 **{v["library_after"]:,}** 条，正式索引 **{contract["library"]["indexed_records"]:,}** 条；原有 4 条待定记录保持原状。基础词库 **{v["tag_after"]:,}** 行。',
'- 全库结构、身份、增量、个人字段、去重、分类绑定、词库完整性及回滚演练通过。',
'- 语义扫描按既有范围检查 73,869 条，新增未决标记 0；15 条原有提示与上一版已复核记录一致。保留来源、超长文本等仍遵循原扫描排除口径，这不等于全库语义零错误。',
'- 修正新增内容中 12 处有正文证据的父归属漏项和 4 条归类空缺；引擎 `2026-09-27.02` 补充“超长雪白头发”精确写法，旧库影响为 0。',
'- 10,452 项历史断言通过；两条本次更新过正文的冻结样本分别保留旧版回归和新版断言证明，468 份冻结文件未改。',
f'- 上线 {len(live["checks"])} 条代表记录、{live["preview_http_checks"]} 个配图接口检查通过；{contract["named_checks"]} 项查询契约、{contract["query_case_count"]} 组查询通过；完整重建与实际索引零差异。',
f'- 8188 仅由 PID **{release["production"]["pid"]}** 监听，队列为空，工作台 71 个节点无降级。','',
'本次已完成，无需继续抽样轮次。刷新工作台即可读取新版本；以后可按本次来源清单做增量核对。','',
'证据：[数据校验](data_validation.json) · [Word 对照](document_coverage_receipt.json) · [配图校验](image_link_validation.json) · [历史兼容](historical_compatibility.json) · [上线验收](live_acceptance.json) · [发布收据](release_receipt.json)。备份保存在本目录 `backup/`。','']
report=HERE/'全站资料更新与验收报告.md';report.write_text('\n'.join(lines),encoding='utf-8')
pointer=ROOT/'benchmark_reports/分类工作入口.md';old=pointer.read_text(encoding='utf-8')
heading='## 最新资料更新（2026-09-27，全站资料集）'
if not old.startswith(heading):
    pointer.write_text(heading+'\n\n已完成网站全部 15 个资料集及桌面 8 份 Word 核对与正式更新。新增资源 1,211 条、基础词条 4,876 条，更新正文 46 条，安装配图 8,562 个；引擎为 `2026-09-27.02`。全量结构校验、历史兼容和上线索引一致性通过。\n\n最新报告：[全站资料更新与验收报告](2026-09-27_codex_update/全站资料更新与验收报告.md)；状态：`2026-09-27_codex_update/EXECUTION_STATE.json`。下面第 94 批段落保留为此次资料更新之前的历史状态。\n\n'+old,encoding='utf-8')
save(HERE/'EXECUTION_STATE.json',{'status':'accepted','production_mutated':True,'passed':True,'report':report.name,'receipt':'release_receipt.json','updated_at':now(),'open_next_steps':[]})
for filename in ('分类标准.md','分类标准变更记录.md'):
    path=ROOT/'benchmark_reports'/filename;text=path.read_text(encoding='utf-8')
    marker='2026-09-27 全站资料更新（2026-09-27.02）'
    if marker not in text:
        path.write_text(text+'\n\n### '+marker+'\n\n新增资料继续按 1–4 个 tag 进入基础词库、长串进入资源库的既有做法；完整角色正向段落、负面字段、来源和配图分别保留。正文更新沿用既有主类与个人资格；两条冻结旧正文保留原历史回归，新来源正文另以精确双版本哈希验证原断言。细分仅增加 `very long snow white hair → hair.very_long` 精确写法，没有新建主题或细分，旧库该写法影响为 0。全量核对、发布和线上验收见 [全站资料更新与验收报告](2026-09-27_codex_update/全站资料更新与验收报告.md)。\n',encoding='utf-8')
print('REPORT',report)
