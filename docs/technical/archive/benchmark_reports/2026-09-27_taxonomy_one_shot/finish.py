from common import *
import shutil, collections

release=read(HERE/'release_receipt.json');assert release['passed'] and release['phase']=='accepted'
pre=read(HERE/'preflight.json');gate=read(HERE/'final_gate.json');measure=read(HERE/'measure_final/summary.json')
revision=read(HERE/'revision_finalize/receipt.json');assert revision['passed']
assert sha(DATA)==revision['final_data_sha256']
effective_data_sha=revision['final_data_sha256']
scan=read(HERE/'scan_live_final/scan_summary.json');query=read(OLD/'one_shot_query_contract.json');live=read(OLD/'one_shot_revision_live.json')
cases=read(HERE/'live_cases.json');assert query['passed'] and live['passed'] and cases['passed']
assert sha(SOURCES/'semantic_refinements.py')==pre['stage_sha256']['semantic_refinements.py']
for path,digest in pre['frozen_hashes'].items():assert sha(ROOT/path)==digest
adjudication=read(HERE/'residual_adjudication.json')
paths=[ROOT/'benchmark_reports/分类工作入口.md',ROOT/'benchmark_reports/分类标准.md',ROOT/'benchmark_reports/分类标准变更记录.md',OLD/'托管进度_HANDOFF.md',OLD/'family_inventory.json',OLD/'convergence_ledger.json',ROOT/'benchmark_reports/2026-09-20_consecutive_extension/progress.json',ROOT/'benchmark_reports/2026-09-25_taxonomy_convergence/EXECUTION_STATE.json']
doc_backup=HERE/'backup/status_before_release';doc_backup.mkdir(parents=True,exist_ok=True)
for i,path in enumerate(paths):shutil.copy2(path,doc_backup/f'{i}_{path.name}')

delta=measure['delta'];pid=release['production']['pid']
table='\n'.join(f'| {axis} | {target} | {number:+d} |' for axis,items in delta.items() for target,number in items.items())
report=f'''# 集中修复与正式验收（第 94 批）

已部署 `2026-09-27.01`，正式验收通过。受控进程 PID {pid} 独占 8188，队列为空，工作台 71 个节点无降级。

本次按用户授权采用“一次集中修复、一次发布、一次完整验收”。未新建第 153–155 轮，历史 clean streak 仍为 0；旧“三轮干净新样本”条件已被本次协议替代，不伪记其达成。

## 实际结果

- 原 76 条扫描标记中，61 条确认为缺陷并已修复：20 条父类误挂，29 条家具皮革，12 条头发、装饰树、柔光、身体轮廓及肤色鞋袜边界。
- 15 条保留原分类：8 条有独立配饰依据，5 条有衣物/鞋履材质依据，1 条是真实照明剪影，1 条是持物扫描误报。逐条结论绑定正文哈希；未对整类设置豁免。
- 额外修复一条第 116 轮旧记录：皮包的重复材质描述不应算衣料。第 114/121/116 轮共 4 条旧皮革预期有逐条证据修订，冻结账本未改。
- 全库实际发生分类变化 {measure['changed_records']} 条，完整操作清单为 `approved_operations.json`。以下是相对已验证第 91 批的净变化；主题变化来自撤回父类后重新计算。

| 轴 | 分类 | 净变化 |
| --- | --- | ---: |
{table}

## 全量核对

1. 遍历原始库 323,680 条；对全部 323,676 条服务索引记录做修改前后逐条比较，4 条待分类记录保持原状。全部操作与批准清单严格一致。
2. 使用未修改的 34 类线索扫描器：范围内 72,746 条，原始标记 76 → {scan['flagged_rows']}，未被标记比例 99.896% → {scan['clean_pct']}%。剩余标记全部逐条核实，当前已判定缺陷为 0。
3. 精确历史回放 {gate['replay']['checks']:,} 项全部通过。旧门禁的整轮豁免已删除；修订绑定轮次、ID、正文、原账本与证据哈希，并执行新预期。另有 14 项防误放行测试通过。
4. 37 项边界测试、76 条现场用例、73 项暂存查询基础测试通过。上线后 {len(cases['checks'])} 条逐条验证、75 项查询契约和 13 个确定性查询场景通过；按现行源码离线重建的完整索引与线上零差异。
5. 20 条记录更改严格局限于批准的父类删除。正文、记录其他字段及记录数未改；投影重新生成且字节完全一致；部分替换后的三文件回滚演练通过。上线重扫与暂存扫描索引完全一致，{len(pre['frozen_hashes'])} 个冻结轮次文件未变。

最后补齐资料修订号 `{revision['new_revision']}`，替换沿用的旧修订号 `{revision['old_revision']}`，确保已打开页面刷新分类缓存。此步仅改顶层 `last_modified`，完整库其余内容逐字节等价；无需重启，线上重新生成的索引与已通过离线重建的索引仅修订号不同，旧修订编辑请求已验证返回 409，避免覆盖新分类。此前扫描与门禁的原始数据哈希留存不改，由 `revision_finalize/receipt.json` 证明分类内容等价并绑定最终数据哈希。

发布前另发现旧线上工作台仅有 55 个节点，LoRA 管理模块处于降级状态。正常权限的独立导入检查确认依赖齐全；本次正常权限受控重启后已实际恢复 71 个节点且无降级。未安装新依赖、未改 LoRA 源码，诊断见 `workbench_baseline_diagnostic.json`。

这些比例是既有扫描范围下的结果，不是全库语义准确率。其余来源、长文本、画师条目等仍遵循原有扫描排除口径；未宣称发现所有未来问题。当前范围已验收，不再为了完成本任务追加抽样轮次。后续仅在有具体新例或新增数据时按同一严格门禁处理。

## 可核验证据

- `release_receipt.json`：受控替换、重启、正式验收及进程身份。
- `preflight.json` / `final_gate.json`：文件绑定、精确增量及严格历史回放。
- `measure_final/changes.json` / `approved_operations.json`：完整影响记录与批准操作。
- `review_decisions.json` / `residual_adjudication.json`：原始标记逐条结论及 15 条保留依据。
- `data_invariants_and_rollback.json`：数据字段不变性、投影及回滚演练。
- `scan_live_final/scan_summary.json`：上线后的未改口径全量扫描。
- `../2026-09-25_full_coverage/one_shot_query_contract.json`：75 项检查、13 查询及索引一致性。

引擎 SHA256：`{pre['stage_sha256']['semantic_refinements.py']}`  
数据 SHA256：`{effective_data_sha}`  
投影 SHA256：`{pre['stage_sha256']['semantic_projection.json']}`

本次为一个正式发布。前期候选中过宽的家具关系及光晕判断均在暂存时被拦住，未上线。第 92 批零变化暂存和第 93 批未完成草稿由本批取代，不记成历史已发布成果。
'''
(HERE/'集中修复与验收报告.md').write_text(report,encoding='utf-8')
progress_path=paths[6];progress=read(progress_path)
progress.update(release_validation_pending=False,completion_status='accepted_under_single_consolidated_protocol',sampling_stop_condition_applicable=False)
progress['acceptance_protocol']={'mode':'single_consolidated_release_and_total_acceptance','authorized_at':'2026-09-27','replaces':'three consecutive clean new sampling rounds','evidence':'2026-09-27_taxonomy_one_shot/集中修复与验收报告.md','passed':True,'new_rounds_run':0}
progress['latest_verified_release']={'batch':94,'version':'2026-09-27.01','actual_refinement_version':'2026-09-27.01','evidence':'2026-09-27_taxonomy_one_shot/release_receipt.json','data_sha256':effective_data_sha,'data_revision':revision['new_revision'],'projection_sha256':pre['stage_sha256']['semantic_projection.json'],'semantic_refinements_sha256':pre['stage_sha256']['semantic_refinements.py'],'next_round':None}
progress['latest_audit']['repair_status']='resolved_and_replayed_in_batch94'
progress['latest_audit']['verification_evidence']='2026-09-27_taxonomy_one_shot/final_gate.json'
save(progress_path,progress)
summary=f'''## 当前状态（2026-09-27，第 94 批）

生产已部署 `2026-09-27.01`，集中修复与完整验收通过。原 76 条标记中 61 条缺陷修复、15 条有据保留；全库实际分类变化 {measure['changed_records']} 条。未改扫描器口径，上线扫描原始标记 15，逐条核实后的已判定未决缺陷为 0。原始库 323,680 条、索引 323,676 条，固定线索范围 72,746 条；这些数字不代表全库语义准确率。

严格历史回放 {gate['replay']['checks']:,} 项、上线逐条检查 {len(cases['checks'])} 条、查询契约 75 项及 13 场景通过，完整离线重建与线上索引零差异。PID {pid} 独占 8188，队列空，71 个工作台节点无降级。

用户已明确授权用“一次集中修复、一次发布、一次完整验收”替代三轮新抽样要求。本任务已按新协议验收，未启动第 153–155 轮，clean streak 仍如实保留为 0；不再按旧页中的待办自动继续抽样。新数据或具体新问题另按精确门禁修复。

主报告：[集中修复与验收报告](2026-09-27_taxonomy_one_shot/集中修复与验收报告.md)。当前状态：`2026-09-27_taxonomy_one_shot/EXECUTION_STATE.json`。完整收据及操作清单位于该目录。

数据 `{effective_data_sha}`；投影 `{pre['stage_sha256']['semantic_projection.json']}`；引擎 `{pre['stage_sha256']['semantic_refinements.py']}`。资料修订号已更新为 `{revision['new_revision']}`，并验证旧版编辑请求会被拒绝，页面可重新获取当前分类。

第 92 批零变化暂存和第 93 批草稿未单独部署，由本批取代。旧周期二状态已标记 superseded，不能再据此宣称有后台任务。旧状态文档保存在本批 `backup/status_before_release` 中。

'''
entry=paths[0].read_text(encoding='utf-8');tail=entry[entry.index('## 叶子粒度'):] if '## 叶子粒度' in entry else ''
paths[0].write_text(summary+'以下保留分类粒度和历史执行说明；历史轮次停止条件不再适用于上述已验收任务。\n\n'+tail,encoding='utf-8')
paths[3].write_text(summary.replace('(2026-09-27_taxonomy_one_shot/','(../2026-09-27_taxonomy_one_shot/'),encoding='utf-8')
standard=paths[1].read_text(encoding='utf-8')
standard=standard.replace('- 停止条件：**连续 3 轮全新样本无需修正、无排除，且回归、完整性与正式接口验证通过。**','- 当前任务停止条件（2026-09-27 用户授权替代）：一次集中修复、一次正式发布及完整回归/索引/上线验收。三轮新样本条件仅保留为旧协议历史，不再用于本次收口。')
standard+='\n\n## 2026-09-27 第 94 批：集中边界修复与新验收协议\n\n家具、车辆内饰及手持皮包的重复皮革材质描述不推出服装衣料；真实皮服、帽檐、鞋履材质保留。耳机沿既有生活器具口径，不单独支持首饰；领带、独立穿戴配饰和穿孔首饰可保留宽父类。明确的场景柔光不被同文其他柔软材质或虚化否决；物件光晕仍保留排除。数字长度括注、颜色修饰和 no text 后分隔符不吞掉正向头发标签；装饰化 tree girl、hourglass silhouette 与肤色鞋袜分别按其修饰对象消歧。\n\n本批未新增分类层级或叶子。原账本保持冻结，历史预期修订按记录、字段及哈希验证，不允许整轮豁免。用户已授权本批集中完整验收替代三轮新抽样条件；验收结果见 `2026-09-27_taxonomy_one_shot/集中修复与验收报告.md`。\n'
paths[1].write_text(standard,encoding='utf-8')
change=paths[2].read_text(encoding='utf-8');paths[2].write_text('# 分类标准变更记录\n\n## 2026-09-27.01：第 94 批集中修复（已发布并验收）\n\n'+summary.split('## 当前状态（2026-09-27，第 94 批）\n\n',1)[1]+'\n以下为历史记录，其中“待发布”等状态仅对应当时快照。\n\n'+change.removeprefix('# 分类标准变更记录\n'),encoding='utf-8')
families=collections.Counter((r['flag']['target'],r['flag']['kind']) for r in adjudication['accepted_current_classifications'])
inventory={'schema':'full-coverage-family-inventory/v2','created_at':now(),'run':'scan_live_final','scan_path':'../2026-09-27_taxonomy_one_shot/scan_live_final/scan_summary.json','in_scope_records':72746,'flagged_records':15,'clean_records':72731,'open_items':0,'raw_flag_items':15,'family_count':len(families),'families':[{'target':k[0],'kind':k[1],'raw_flags':v,'open_items':0,'disposition':'record_specific_reviewed_current_classification'} for k,v in families.items()],'adjudication':'../2026-09-27_taxonomy_one_shot/residual_adjudication.json'}
save(paths[4],inventory)
ledger=read(paths[5]);ledger['runs'].append({'run_label':'batch94_scan_live_final','recorded_at':now(),'in_scope_records':72746,'flagged_records':15,'raw_flag_items':15,'open_items_remaining':0,'record_specific_retained_flags':15,'clean_pct':scan['clean_pct'],'note':'Unmodified scanner; no family waiver; each retained flag has a body-bound judgment. Accepted under user-authorized single-release protocol.'});ledger['current']=inventory;save(paths[5],ledger)
state=read(paths[7]);state.update(status='superseded_by_verified_batch94',active_processes=[],superseded_at=now(),superseded_by='benchmark_reports/2026-09-27_taxonomy_one_shot/EXECUTION_STATE.json',note='Old cycle02 preparation is historical and inactive; its offline tests were never a release. Current production is independently verified by batch94.');save(paths[7],state)
save(HERE/'EXECUTION_STATE.json',{'status':'accepted','production_mutated':True,'batch':94,'version':'2026-09-27.01','accepted_at':now(),'pid':pid,'sole_listener_ok':True,'new_sampling_rounds':0,'historical_clean_streak':progress['current_clean_streak'],'acceptance_protocol':progress['acceptance_protocol'],'remaining_adjudicated_defects':0,'raw_scanner_flags':15,'next_action':'No additional sampling rounds. Address specific future evidence or new data when requested.','report':'集中修复与验收报告.md'})
save(HERE/'documentation_reconciliation.json',{'completed_at':now(),'updated':[str(p.relative_to(ROOT)) for p in paths],'backups':str(doc_backup.relative_to(ROOT)),'frozen_files_unchanged':len(pre['frozen_hashes']),'passed':True})
save(OLD/'current_release.json',{'batch':94,'version':'2026-09-27.01','accepted':True,'receipt':'../2026-09-27_taxonomy_one_shot/release_receipt.json','state':'../2026-09-27_taxonomy_one_shot/EXECUTION_STATE.json','current_scan':'../2026-09-27_taxonomy_one_shot/scan_live_final/scan_summary.json','current_index':'../2026-09-27_taxonomy_one_shot/scan_live_final/coverage_index.jsonl','note':'The old root coverage_index.jsonl and scan_summary.json remain immutable historical run046 evidence. Current inventory points to the accepted batch94 scan; use these current paths for further analysis.'})
print('ACCEPTED_AND_RECONCILED',measure['changed_records'],pid)
