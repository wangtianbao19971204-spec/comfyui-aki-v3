from pathlib import Path
import sys, json
from collections import Counter
HERE = Path(__file__).resolve().parent
PREV = HERE.with_name('2026-09-27_llama_verified_writeback')
sys.path.insert(0, str(PREV))
from common import read, sha, save, now, DATA, PROJECTION, PROD, digest, load_rows
import requests, psutil

notes = {
 0:'年龄词来自画师专名，但来源同时涉及具名未成年角色的性化内容，保留排除。',
 1:'来源角色段落有幼龄主体与性化穿着、遮挡语境；本地模板并非完整来源，保留。',
 2:'来源角色段落有幼龄主体与性化姿态，保留。',
 3:'来源有具名未成年角色及明确性化场景，保留。',
 4:'来源明确未成年年龄及性化描写，保留。',
 5:'来源明确未成年年龄及性化描写，保留。',
 6:'来源含幼龄化角色和性化呈现，保留。',
 7:'来源含幼龄化及恋童取向标记，不能由通用模板单独放行，保留。',
 8:'来源含幼龄化与性化身体及动作，保留。',
 9:'来源含明确未成年年龄及性唤起情境，保留。',
 10:'来源幼龄化与限制级标记仍有关联；已检查当前配图，存在幼态主体的性化呈现，保留。',
 11:'画师专名并非年龄证据；来源另有明确性暴力语境，本次不增强检索。',
 12:'年龄词来自画师专名，但来源有具名未成年角色的性化内容，保留。',
 13:'画师专名误命中并不消除具名未成年角色及性化表达，保留。',
 14:'画师专名误命中并不消除具名未成年角色的性化内容，保留。',
 15:'来源涉及具名未成年角色的明确性化内容，保留；画师名另作误命中登记。',
 16:'来源涉及具名未成年角色的明确性化内容，保留；画师名另作误命中登记。',
 17:'画师专名并非年龄证据，但来源的年龄及非自愿性语境未消除，不放行。',
 18:'来源涉及具名未成年角色及性暴力语境，保留；画师名另作误命中登记。',
 19:'画师专名并非年龄证据，但来源的年龄及非自愿性语境未消除，不放行。',
 20:'来源涉及具名未成年角色的性化内容，保留；画师名另作误命中登记。',
 21:'具名未成年角色、限制级及性化穿着语境仍需保留；不以画师专名误命中自动放行。',
 22:'来源明确幼龄化主体与性化呈现，保留。',
 23:'来源明确幼龄化与性化穿着，保留。',
 24:'来源明确幼龄主体与性化呈现，保留。',
 25:'年龄词确系画师专名误命中；已检查对应配图，但图像与来源记录不足以独立确认人物成年，年龄疑点仍未消除，保持待核，不宣称已确认违规。',
 26:'画师专名虽非年龄证据，来源仍涉及具名未成年角色的性化内容，保留。',
 27:'来源明确幼龄化主体与性化呈现，保留。',
 28:'来源有未成年主体与性化互动语境，保留。',
 29:'来源有幼龄主体、性化描写与窥视语境，保留。',
 30:'来源有幼龄角色及性化服装、聚焦语境，保留。',
 31:'来源年龄关联制服与性化角色互动语境未消除，保留。',
 32:'来源明确幼龄化主体及性化穿着，保留。',
 33:'来源幼龄化与性化受虐语境明确，保留。',
 34:'来源含幼龄角色与性化身体互动，保留。',
}
sources = {r['source']:r for r in load_rows()}
reviewed = read(HERE/'source_context_review.json')
assert len(reviewed) == len(notes) == 35
decisions = []
for i, row in enumerate(reviewed):
    raw = sources[row['source']]
    decisions.append({'source':row['source'], 'id':row['id'], 'source_sha256':raw['source_sha256'], 'positive_body_sha256':digest(raw['record']['positive_prompt']), 'decision':'unresolved_no_write' if i==25 else 'retain_hold', 'review_method':'assistant_direct_source_context_review', 'reason':notes[i], 'artist_name_false_age_cue':row['artist_name_age_collision'] and row['other_age_cues']==0})
assert len({r['source'] for r in decisions}) == 35
image_path = PROD/'user_data/prompt_selector/preview/codex_community_ai_misc-5176.jpg'
decisions[10]['image_sha256'] = sha(image_path)
decisions[10]['image_review_method'] = 'assistant_direct_visual_review'
decisions[25]['image_sha256'] = sha(PROD/'user_data/prompt_selector/preview/codex_nai5_community_pack_mengshen_korean_1049.jpg')
decisions[25]['image_review_method'] = 'assistant_direct_visual_review'
save(HERE/'source_context_decisions.json', decisions)
# Retain hashes and non-graphic findings; original source files remain unchanged.
save(HERE/'source_context_review.json', [{k:v for k,v in r.items() if k!='record'} for r in reviewed])
by_source = {r['source']:r for r in decisions}
inventory = read(HERE/'inventory.json')
assert len(inventory)==len({r['source'] for r in inventory})==2395
final = []
for item in inventory:
    item = dict(item)
    item['source_sha256'] = sources[item['source']]['source_sha256']
    if item['source'] in by_source:
        item['final_disposition'] = by_source[item['source']]['decision']
        item['review_reference'] = 'source_context_decisions.json'
    else:
        item['final_disposition'] = 'prior_disposition_preserved'
        item['review_reference'] = 'automated_identity_and_context_recheck_only'
    item['written'] = False
    final.append(item)
save(HERE/'remaining_dispositions.json', final)
baseline = read(HERE/'baseline_runtime.json')
assert sha(DATA)==baseline['data_sha256']
assert sha(PROJECTION)==baseline['projection_sha256']
assert sha(PROD/'prompt_selector/semantic_refinements.py')==baseline['engine_sha256']
ports = psutil.net_connections('tcp')
owners = sorted({c.pid for c in ports if c.status=='LISTEN' and c.laddr.port==8188})
assert owners == [baseline['owner']['pid']]
assert not any(c.status=='LISTEN' and c.laddr.port==8081 for c in ports)
assert psutil.Process(owners[0]).create_time()==baseline['owner']['create_time']
base = 'http://127.0.0.1:8188'
queue = requests.get(base+'/queue',timeout=30).json()
workbench = requests.get(base+'/unified-workbench/status',timeout=30).json()
index = requests.get(base+'/prompt_selector/library/index',timeout=180).json()
assert index==read(PREV/'live_index.json')
assert workbench['nodes']==71 and not workbench['degraded']
state = {'status':'review_complete_with_retained_holds','completed_at':now(),'production_mutated':False,'new_classification_writes':0,'remaining_sources_reconciled':2395,'direct_source_reviews':35,'artist_name_age_false_hits':14,'direct_image_reviews':2,'direct_review_unresolved':1,'other_prior_holds_preserved':2360,'local_model_used':False,'live_index_unchanged':True,'live_pid':owners[0],'data_sha256':sha(DATA),'projection_sha256':sha(PROJECTION),'engine_sha256':baseline['engine_sha256'],'queue':queue,'workbench_nodes':workbench['nodes'],'previous_applied_classifications':45,'semantic_accuracy_scope':'35 full-source context decisions; other rows received mapping/hash/context rechecks and retain previous dispositions. No claim of semantic correctness for all remaining model proposals.'}
save(HERE/'EXECUTION_STATE.json',state)
report = f'''# 剩余分类核对报告

完成时间：{state['completed_at']}。

本次对剩余 **2,395 条来源记录**完成身份、正文绑定与保留原因复核；进一步直接阅读全文核对 35 条，并检查其中 2 条当前本地配图。**没有新增写回**。上一批 45 条分类仍保持生效，本地 llama 未启动。

## 查明的情况

- 234 条本地正文未命中既有敏感词规则，但全部仍关联本地配图。源资料中的角色段落可能没有进入本地正文，因此仅看本地的画师、背景或光影模板不足以确认整条记录可放行。
- 对全体剩余来源检查了画师名与年龄词的碰撞，发现 14 条 `child (isoliya)` 误命中。它是画师专名，不能作为角色年龄证据。但其中一些资料仍有具名未成年角色或其他明确排除语境，不能据此整体放行。
- 对上述 14 条，以及 21 条“来源正文未命中原显式规则、但数据集有成人标记”的疑似误拦项，共 35 条进行了直接全文核对。34 条保留原有排除或未决原因；1 条画师专名误命中虽已检查配图，但年龄疑点仍未消除，保持待核，没有被写成“确认违规”。
- 原有规则也存在漏掉性化语境的情况。因此本次没有扩大白名单，也没有把“未命中词表”当作安全证明。

## 覆盖与边界

2,395 条来源 ID 不重复，与上一批已写回的 45 条来源无交集。逐条结果保存在 `remaining_dispositions.json`。其中 35 条有本次直接全文结论，其余 2,360 条保留原处置，未被宣称已逐条语义审核通过。

初筛去向为：1,975 条本地仍有需保留的语境线索；234 条进入来源关联复核；68 条已有直接审核记录；112 条没有本地资源目标（7 条仅在基础 Tag 库，105 条两库未找到）；4 条保留人工确认；2 条保留原写入资格。它们是核对处置原因，不是新增业务分类。

## 当前运行情况

正文、分类、图片和用户字段均未改动；数据、投影、分类引擎哈希与已验收版本一致。实际线上完整索引与上一批验收索引相等，71 个工作台节点无降级，服务仍由同一进程独占 8188。没有本地模型或分类任务在后台继续运行。

生产未变，因此沿用绑定同一文件哈希的上一批全库结构、历史回放与查询验收证据，没有再重复重启和全量发布。

## 后续处理

有明确性化未成年语境的资料不能继续增强分类或检索。普通资料仍按现有业务分类处理；对于仅剩年龄与配图证据未决的那一条，只在独立证据充分后再核对分类，不根据画师专名误命中直接放行。本次没有重新导入被排除的正文或图片。

核对证据：`inventory_summary.json`、`source_context_decisions.json`、`remaining_dispositions.json`、`EXECUTION_STATE.json`。报告和直接核对结论均不复述露骨内容。
'''
(HERE/'剩余分类核对报告.md').write_text(report,encoding='utf-8')
entry = HERE.parent/'分类工作入口.md'
original = entry.read_text(encoding='utf-8')
heading = '## 剩余分类继续核对（2026-09-27）'
if original.startswith(heading):
    _, separator, rest = original.partition('\n\n## ')
    assert separator
    original = '## '+rest
entry.write_text(heading+'\n\n剩余 2,395 条来源完成映射与保留原因复核，35 条直接阅读全文、2 条检查本地配图；14 条画师专名误命中已单列，未据此整体放行。本次新增写回 0 条，上一批 45 条保持生效；未启动本地 llama。其余保留项未宣称逐条语义验证通过。\n\n报告：[剩余分类核对报告](2026-09-27_remaining_classification/剩余分类核对报告.md)。\n\n'+original,encoding='utf-8')
print(json.dumps(state,ensure_ascii=False))
