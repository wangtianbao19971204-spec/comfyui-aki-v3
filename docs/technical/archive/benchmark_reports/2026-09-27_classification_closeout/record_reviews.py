from audit_remaining import *
from review_cues import evidence

raw={r['source']:r for r in load_rows()}
candidates=read(HERE/'remaining_metadata_candidates.json')
lexical=read(HERE/'new_lexical_candidates.json')
assert len(candidates)==101 and len(lexical)==13
notes={
 0:('retain_hold','来源明确恋童取向标记，保持排除，不增强检索。'),
 1:('unresolved_no_write','衣着正文无明确性行为；已查配图，幼龄与挑逗性设定的疑点仍未充分消除，保留待核，不判定普通穿着本身违规。'),
 2:('unresolved_no_write','衣着正文无明确性行为；已查配图，幼龄与挑逗性呈现的疑点仍未充分消除，保留待核。'),
 6:('unresolved_missing_image','全文为普通幼儿园制服，非性化正文；资源与 Tag 库均无对应。来源配图浏览连接失败，图文整体尚未核实，不新建。'),
 7:('existing_tag_no_duplicate','正文为简短人物及画师标签，已有基础 Tag 对应，本次不重复新建资源；不把存在性验证当作图片审核。'),
 24:('retain_hold','已核对来源全文与当前配图，存在明确幼龄化主体的性化呈现，保留。'),
 33:('retain_hold','来源明确未成年年龄且有透视衣物语境，保留排除。'),
 34:('retain_hold','多格来源有未成年主体的性化叙事，保留。'),
 35:('retain_hold','来源含未成年角色及性化叙事，保留。'),
 36:('retain_hold','完整场景为性化情境，不能将其中普通照片段落单独视为整条记录已合格，保留。'),
 42:('retain_hold','已查图文，成年人与幼龄主体的性化互动呈现仍有关联，保留。'),
 45:('retain_hold','已查图文，成年人与幼龄主体的性化互动呈现仍有关联，保留。'),
 46:('unresolved_no_write','短正文与来源目录均关联幼龄主体的成人向情境，现有证据不足以视作普通合影，不放行。'),
 54:('approve_classification_review','年龄词仅来自奶瓶物品名。全文及配图没有幼龄参与者；只审核既有成人记录的中性分类元数据。'),
 58:('approve_classification_review','全文及配图是医院照护与非性化哺乳场景，婴幼儿出现及哺乳本身不是性化依据。按真实医疗服饰与表情场景核对。'),
 71:('unresolved_no_write','图像呈现单个成年人，但正文仍含双人及幼龄设定，图文不一致，不能根据单张图覆盖正文年龄疑点。'),
}
reviews=[]
data=read(DATA);doc=read(PROJECTION)
byid={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
visual={1,2,24,42,45,54,58,71}
for i,row in enumerate(candidates):
    if i in notes:decision,note=notes[i]
    elif 72<=i<=99:decision,note='retain_linked_context','已阅读全文；该条属于同一组逐步转向未成年性化互动的连续叙事，不能仅按单帧日常词面放行。关联证据为同组 80、81、91、94–96 号来源记录。'
    else:decision,note='retain_hold','已阅读全文，来源存在幼龄主体或年龄疑点与性化动作、穿着或互动语境，保留排除。'
    src=raw[row['source']]
    r={'source':row['source'],'id':row['id'],'source_sha256':src['source_sha256'],'positive_body_sha256':digest(src['record']['positive_prompt']),'review_method':'assistant_direct_full_source_review','decision':decision,'reason':note,'candidate_index':i}
    if i in visual:
        p=byid[row['id']][1];r.update(image_sha256=sha(PROD/'user_data/prompt_selector/preview'/p['image']),image_review_method='assistant_direct_visual_review')
    reviews.append(r)
lex_notes={
 0:('unresolved_no_write','词面年龄仅来自画师专名；已查配图，角色年龄及幼态呈现仍未得到可靠澄清，保持待核。'),
 1:('unresolved_no_write','词面年龄仅来自画师专名；已查配图，具名角色年龄证据不足，保持待核。'),
 2:('retain_hold','纸艺形式不是年龄证据；来源另有具名角色及非自愿暴露语境，保留。'),
 3:('retain_hold','纸艺形式不是年龄证据；来源仍涉及具名未成年角色的性化内容，保留。'),
 4:('unresolved_no_write','儿童画是画法而非人物年龄；已查图像，但参与者年龄与相关叙事仍不够明确，保留待核。'),
 6:('unresolved_no_write','奶瓶是物品；来源另有少女及校园运动服语境，已查图像仍不足以消除年龄疑点，不直接放行。'),
 7:('unresolved_no_write','奶瓶是物品；已查当前图像，与相邻来源的年轻化人物造型存在关联，尚未充分确认成年，不作分类增强。'),
 8:('retain_hold','奶瓶是物品；已查配图，幼态主体及性化呈现仍需保留排除，不能靠纠正单词误命中放行。'),
 9:('retain_hold','服装名不是年龄证据；来源仍有拘束及非自愿性语境疑点，保留原处置。'),
 10:('approve_classification_review','身体描述复合词不表示有儿童参与；全文及配图均为成年女性礼服场景，只审核中性分类元数据。'),
 11:('retain_hold','minor 修饰伤势程度，不表示未成年；来源另有明确性暴力情境，保留原处置。'),
 12:('unresolved_no_write','儿童画是画法，非年龄证据；已查配图，人物年龄疑点未消除，保持待核。'),
}
lex_visual={0,1,4,6,7,8,10,12}
for i,row in enumerate(lexical):
    if i==5:
        assert row['source']==candidates[54]['source'];continue
    decision,note=lex_notes[i];src=raw[row['source']]
    r={'source':row['source'],'id':row['id'],'source_sha256':src['source_sha256'],'positive_body_sha256':digest(src['record']['positive_prompt']),'review_method':'assistant_direct_full_source_review','decision':decision,'reason':note,'lexical_candidate_index':i}
    if i in lex_visual:
        p=byid[row['id']][1];r.update(image_sha256=sha(PROD/'user_data/prompt_selector/preview'/p['image']),image_review_method='assistant_direct_visual_review')
    reviews.append(r)
assert len(reviews)==len({r['source'] for r in reviews})==113
save(HERE/'source_reviews.json',reviews)
save(HERE/'browser_limitation.json',{'checked_at':now(),'source':candidates[6]['source'],'operation':'read-only source image inspection','attempts':2,'errors':['createBrowserTab timed out and reset kernel','getState: Browsers nodeRepl.fetch request failed; browser inventory unavailable'],'image_imported':False,'source_text_nonsexual':True,'source_media_verified':False})

changes={
 '10bd2797-7307-582c-8225-a4fd3e8abfef':{
  'remove':['头发与发型'],'add':['穿脱与整理'],
  'reason':'完整本地正文中只有发带而无头发描写，移除头发误挂；明确自行提衣，补衣着整理动作。奶瓶只作物品，未作为年龄证据。'},
 'codex-codex_6e699406-4111':{
  'remove':['裙装与礼服','眼睛与瞳色','建筑与设施'],'add':['制服与职业装','面部特征'],
  'reason':'病号服按制服服饰归属；眼袋属于面部特征，空洞目光与闭眼属于已保留的表情轴；病号服一词不推出独立建筑。照护哺乳保持非性化场景归属。'},
 '9d8b5f4b-8c98-5cb0-9dfd-3b45cd9ebf82':{
  'remove':[],'add':['头发与发型','裸露与遮盖','服装材质与剪裁','室内空间','人工光与发光','家具与生活用品','首饰与随身配饰'],
  'reason':'全文明确头发飘动、肩背露出、丝质贴身开衩礼服、舞厅、吊灯照明和面饰；补齐这些独立轴，保持礼服主类。可选花瓣不额外挂植物，景深不推导摄影风格。'},
}
approvals=[];manual={}
source_by_id={r['id']:r for r in reviews if r['decision']=='approve_classification_review'}
assert set(changes)==set(source_by_id)
for pid,change in changes.items():
    c,p=byid[pid];old=P.decision_for(doc,c,p);review=source_by_id[pid]
    assert old['manual_search_eligible'] and old.get('semantic_review_status')!='user_confirmed'
    assert set(change['remove'])<=set(old['subcategories'])
    subs=sorted((set(old['subcategories'])-set(change['remove']))|set(change['add']))
    assert set(subs)<=set(T.SUBCATEGORY_PARENTS)
    item={'id':pid,'sources':[review['source']],'body_sha256':digest(p['prompt']),'primary_class':old['primary_class'],'subcategories':subs,'review':change['reason'],'review_method':'assistant_direct_local_body_source_and_image_review','image_sha256':review['image_sha256']}
    approvals.append(item);manual[pid]=item
save(HERE/'manual_reviews.json',manual)
save(HERE/'approved_classifications.json',{'passed':True,'created_at':now(),'decisions':approvals,'local_model_audit_used_for_acceptance':False,'direct_full_source_reviews':113,'direct_image_reviews':sum('image_sha256' in r for r in reviews),'scope':'Only these three independently reviewed existing records may receive classification metadata edits. No excluded source text or image import is authorized by this receipt.'})

cases=[('artist:child (isoliya)',0),('child (isoliya), child',1),('artist:ajishio (loli king), loli',1),('baby bottle',0),('baby bottles, baby',1),('minor wounds',0),('minor injuries, minor',1),("child’s drawing, child",1),('paper child',0),('child-bearing hips',0),('baby doll, child',1),('baby face',1),('kindergarten uniform',1),('baby in arms',1),('artist:child (isoliya), baby bottle, shota',1)]
for text,expected in cases:assert sum(x['is_age_evidence'] for x in evidence(text))==expected,(text,expected)
save(HERE/'cue_boundary_checks.json',{'passed':True,'checks':len(cases),'rules_sha256':sha(HERE/'review_cues.py'),'source_correction_sha256':sha(HERE/'corrected_cue_evidence.json'),'automatic_content_clearance':False})
print(json.dumps({'direct_source_reviews':len(reviews),'direct_image_reviews':sum('image_sha256' in r for r in reviews),'decisions':dict(Counter(r['decision'] for r in reviews)),'approved_classifications':len(approvals),'cue_boundary_checks':len(cases)},ensure_ascii=False))
