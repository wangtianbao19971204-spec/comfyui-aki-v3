from common import *
from collections import Counter
import psutil, requests
sys.path.insert(0,str(UPDATE))
from db_fingerprint import fingerprint

release=read(HERE/'release_receipt.json')
assert release['phase']=='accepted' and release['applied'] and release['passed']
assert read(HERE/'live_acceptance.json')['passed'] and read(HERE/'live_query_contract.json')['passed']
preflight=read(HERE/'preflight.json')
assert sha(DATA)==preflight['stage_sha256']['data.json']
assert sha(PROJECTION)==preflight['stage_sha256']['semantic_projection.json']
assert fingerprint(DB)==read(HERE/'tag_db_baseline_fingerprint.json')
for relative,h in preflight['untouched_image_hashes'].items():assert sha(ROOT/relative)==h
ports=psutil.net_connections('tcp')
owners=sorted({c.pid for c in ports if c.status=='LISTEN' and c.laddr.port==8188})
assert owners==[release['production']['pid']]
assert not any(c.status=='LISTEN' and c.laddr.port==8081 for c in ports)
queue=requests.get('http://127.0.0.1:8188/queue',timeout=30).json()
assert not queue['queue_running'] and not queue['queue_pending']
old=HERE.with_name('2026-09-27_llama_verified_writeback')
last_review=HERE.with_name('2026-09-27_remaining_classification')
old_approved=read(old/'approved_classifications.json')['decisions']
old_sources={s:r for r in old_approved for s in r['sources']}
operations=read(HERE/'operations.json')
new_sources={s:r for r in operations for s in r['sources']}
assert len(new_sources)==len(operations)==3 and not set(old_sources)&set(new_sources)
inventory={r['source']:r for r in read(HERE/'inventory.json')}
presence=read(HERE/'presence_verification.json'); assert presence['passed']
by_presence={r['source']:r for r in presence['rows']}
reviews={r['source']:r for r in read(HERE/'source_reviews.json')}
prior_reviews={r['source']:r for r in read(last_review/'source_context_decisions.json')}
cue={r['source']:r for r in read(HERE/'corrected_cue_evidence.json')}
ledger=[]
for source,r in inventory.items():
    result={'source':source,'id':r['id'],'source_sha256':r['source_sha256'],'presence':by_presence[source]['presence'],'tag_ids':by_presence[source]['tag_ids'],'business_categories_changed':source in new_sources,'semantic_proposal_certified':source in new_sources}
    if source in new_sources:
        result.update(status='classification_applied',reason='已直接核对实际本地正文、来源与配图，仅修改批准的分类字段。')
    elif r.get('user_confirmed'):
        result.update(status='user_confirmation_preserved',reason='保留用户人工确认，不自动覆盖。')
    elif r['id'] and not r.get('eligible'):
        result.update(status='eligibility_preserved',reason='保留原写入资格，不扩大内容池。')
    elif result['presence']=='already_in_tag_only':
        result.update(status='existing_tag_no_duplicate',reason='实际基础 Tag 库有对应，不重复创建资源；分类准确性未据此认证。')
    elif source in reviews:
        result.update(status=reviews[source]['decision'],reason=reviews[source]['reason'],direct_review='source_reviews.json')
    elif source in prior_reviews:
        result.update(status=prior_reviews[source]['decision'],reason=prior_reviews[source]['reason'],direct_review='previous_source_context_review')
    else:
        result.update(status='prior_hold_preserved_not_semantically_certified',reason='原有保留处置继续有效；本次只复核来源绑定、当前存在性及词面证据，未宣称分类模型结果已逐条审核正确。')
    if source in cue:
        result.update(corrected_age_cues=cue[source]['age_cues'],retained_lexical_age_evidence=cue[source]['retained_age_evidence'],cue_correction_is_not_approval=True)
    ledger.append(result)
assert len(ledger)==len({r['source'] for r in ledger})==2395
save(HERE/'final_dispositions.json',ledger)
all_sources=set(inventory)|set(old_sources)
assert len(all_sources)==2440 and not set(inventory)&set(old_sources)
summary={'original_sources':2440,'previously_applied':45,'newly_applied':3,'total_applied_sources':48,'remaining_without_classification_write':2392,'current_remaining_presence':presence['counts'],'current_status_counts':dict(Counter(r['status'] for r in ledger)),'new_direct_source_reviews':len(reviews),'new_direct_image_reviews':sum('image_sha256' in r for r in reviews.values()),'records_with_corrected_non_age_hits':len(cue),'records_with_only_non_age_lexical_hits':sum(r['retained_age_evidence']==0 for r in cue.values()),'historical_source_artifacts_modified':False,'import_filter_changed':False,'local_model_used':False}
save(HERE/'closure_summary.json',summary)
historical=read(HERE/'historical_compatibility.json');scan=read(HERE/'scan_adjudication.json');live=read(HERE/'live_acceptance.json');contract=read(HERE/'stage_contract.json')
state={'status':'accepted_with_documented_retained_items','completed_at':now(),'production_mutated':True,'applied_classification_changes':3,'total_applied_since_model_proposals':48,'remaining_not_written':2392,'data_sha256':sha(DATA),'projection_sha256':sha(PROJECTION),'engine_sha256':sha(PROD/'prompt_selector/semantic_refinements.py'),'live_pid':owners[0],'sole_listener_ok':True,'local_model_used':False,'tag_database_unchanged':True,'bodies_images_favorites_notes_and_eligibility_unchanged':True,'raw_records':324891,'visible_index':contract['indexed_records'],'historical_assertions':historical['checks'],'new_unresolved_scan_flags':scan['new_unresolved_flags'],'all_changed_records_live_checked':live['all_changed_records_checked'],'unresolved_items_are_not_passed':True,'ordinary_missing_source_image_review':'browser_connector_unavailable; source mengshen_r18:asset-268 retained without import','background_classification_job_running':False}
save(HERE/'EXECUTION_STATE.json',state)
report=f'''# 分类收尾核对与写回报告

完成时间：{state['completed_at']}。

**本次正式修正 3 条既有资源分类，累计写回 48 条。**剩余 2,392 条来源没有写回，不计作分类正确或审核通过。没有启动本地 llama，没有新增资源或图片。

## 本次实际完成

- 对剩余 2,395 条来源完成当前生产资源及基础 Tag 库存在性验证：2,283 条已有本地资源，7 条仅在基础 Tag 库，105 条两库均无对应。来源 ID 无重复，与之前已写回的 45 条无交集。
- 新增直接阅读全文核对 113 条来源、查看 16 条当前本地配图；判断绑定原文与图像哈希，不复述露骨内容。除此之外的保留项不宣称已完成逐条语义审核。
- 修正 41 条记录中的非年龄词命中理由，其中 27 条所有词面年龄命中均来自专名、物品、画法或词义误判。此前的 14 条画师名误命中已包含在内。其他命中原因包括另一画师专名、奶瓶、服装名、纸艺/画法、伤势程度及成年身体描述复合词。
- 这只是核对证据纠正，不是自动放行。已确认的原排除依据、未决年龄与配图问题、人工确认和写入资格分别保留。原始来源登记与历史收据保持不变，导入筛查器没有被修改为宽泛白名单。

## 三条分类修正

| 记录 | 修正内容 |
|---|---|
| 奶瓶道具记录 | 奶瓶不作人物年龄证据；去掉由发带误推的头发分类，补正文明确的衣着整理动作。 |
| 医院照护场景 | 非性化哺乳不作排除理由；病号服归制服服饰，眼袋归面部特征，去掉由服装词误推的建筑等归属。 |
| 成年人物礼服场景 | 补齐正文明确的头发、服装剪裁、室内、吊灯照明、家具与面饰等分类，保持原主类。 |

三条主类均未改变。原文、图片、收藏、别名、备注、人数标记、用户确认和资格保持；分类引擎与基础 Tag 库未改动。逐条前后差异见 `operations.json`。

## 验证结果

- 全库 324,891 条完成字段与身份一致性校验，仅批准的 3 条分类字段及对应投影、修订号发生变化。
- 完整独立重建与线上索引一致，共 {contract['indexed_records']:,} 条可见资源，筛选数量变化与操作清单完全一致。
- {historical['checks']:,} 项原始正文历史断言通过；之前两条出版方正文修订的固定哈希兼容证明保持，不改写历史样本。
- 完整既有扫描执行完毕，固定线索范围 {scan['scope']['in_scope']:,} 条，仍为 15 个已判定标记，新增未解决标记 0。此扫描不代表全库语义准确率。
- 完成备份、隔离回滚演练、一次受控写回与重启、3 条实际接口逐条校验及完整线上查询契约。71 个工作台节点正常，队列为空，8188 由 PID {owners[0]} 独占。

## 保留项和实际限制

- 7 条基础 Tag 已存在，无需重复新增；这不等于其分类与图片都已审核正确。
- 明确性化未成年、性暴力或其他需保留的资料不继续增强检索。不能把网站省略了角色段落的本地通用模板视作整条资料已合格。
- 普通幼儿园制服来源 `mengshen_r18:asset-268` 的正文无性化内容，但当前两库无对应，来源配图浏览连接两次失败，图片未核实，因此尚未导入。浏览器故障不影响三条现有资源写回。
- 其余缺证或保留项的逐条状态和理由见 `final_dispositions.json`；没有把它们合并成新增的业务类别，也没有把保留当作通过。

本轮可确认的分类修正已完成。没有本地模型、分类或发布任务在后台继续运行；保留项等待新的具体证据，不自动重复进行全库轮次。

证据：`closure_summary.json`、`source_reviews.json`、`corrected_cue_evidence.json`、`presence_verification.json`、`operations.json`、`release_receipt.json`、`live_acceptance.json`、`live_query_contract.json`、`EXECUTION_STATE.json`。回滚备份保存在本目录 `backup`。
'''
(HERE/'分类收尾核对与写回报告.md').write_text(report,encoding='utf-8')
entry=ROOT/'benchmark_reports/分类工作入口.md';original=entry.read_text(encoding='utf-8')
heading='## 分类收尾写回（2026-09-27）'
assert not original.startswith(heading)
entry.write_text(heading+'\n\n本次 3 条分类已正式写回并验收，累计 48 条；剩余 2,392 条未写回，不计作全部审核通过。新增直接阅读全文 113 条、检查配图 16 条；41 条词面误命中理由已纠正并保留上下文判断。全库结构、历史、完整索引及线上查询通过，未使用本地 llama。\n\n报告：[分类收尾核对与写回报告](2026-09-27_classification_closeout/分类收尾核对与写回报告.md)；状态：`2026-09-27_classification_closeout/EXECUTION_STATE.json`。\n\n'+original,encoding='utf-8')
print(json.dumps(state,ensure_ascii=False))
