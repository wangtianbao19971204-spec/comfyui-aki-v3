"""Build a reversible, reviewed source update without modifying production."""
from update_common import *
import os,shutil,sqlite3,uuid

stamp=now()
for src,name in ((DATA,'data.json'),(PROJECTION,'semantic_projection.json')):
    dest=BACKUP/name
    if not dest.exists():shutil.copy2(src,dest)
    assert sha(src)==sha(dest),'Production changed during audit'
if not (BACKUP/'tags.db').exists():
    with sqlite3.connect('file:'+DB.as_posix()+'?mode=ro',uri=True) as src,sqlite3.connect(BACKUP/'tags.db') as dest:src.backup(dest)
data=read(BACKUP/'data.json');projection=read(BACKUP/'semantic_projection.json')
byid={p['id']:(c,p) for c in data['categories'] for p in c['prompts']}
bybody=defaultdict(list)
for pid,(c,p) in byid.items():bybody[norm(p['prompt'])].append(pid)
categories={c['name']:c for c in data['categories']}
shutil.copy2(BACKUP/'tags.db',STAGE/'tags.db')
db=sqlite3.connect(STAGE/'tags.db');db.row_factory=sqlite3.Row
tags={x['t_uuid']:dict(x) for x in db.execute('SELECT * FROM tag_tags')}
tagmeta={uid:json.loads(s) for uid,s in db.execute('SELECT tag_uuid,data FROM workbench_tag_meta')}
tagbodies=defaultdict(list)
for uid,t in tags.items():tagbodies[norm(t['text'])].append(uid)
groups={g['name']:dict(g) for g in db.execute('SELECT * FROM tag_groups')}
folders={(x['p_uuid'],x['name']):dict(x) for x in db.execute('SELECT * FROM tag_subgroups')}
matching={(x['dataset'],x['id']):x for x in read(HERE/'matching.json')}
old_entries={}
for f in [OLD/'r2_suozhang.json',OLD/'r2_suozhang_r18.json',OLD/'r2_nai45_community_pack.json',*(OLD/'official_data').glob('*.json')]:
    v=read(f)
    if isinstance(v,dict):
        for e in v.get('entries',[]):old_entries[e['id']]=e
oldthumbs={}
thumb_manifest=OLD/'phase2/official_thumb_manifest.json'
if thumb_manifest.exists():
    for r in read(thumb_manifest)['rows']:
        if r.get('status')!='failed':oldthumbs[(r['codex'],r['image'],r.get('asset_rev'))]=r
images={};operations=[];registry=[];reviews=[];stats=Counter();groupstats=defaultdict(Counter)
def plan_image(meta,e):
    url=image_url(meta,e)
    if not url:return ''
    suffix=Path(e['image']).suffix.lower()
    if suffix not in ('.jpg','.jpeg','.png','.webp','.gif','.avif'):suffix='.jpg'
    name='web_'+hashlib.sha256(url.encode()).hexdigest()[:24]+suffix
    if name not in images:
        record={'filename':name,'url':url,'source':source_key(meta,e)}
        cache=oldthumbs.get((e.get('assetCodexId') or meta['id'],e['image'],e.get('assetRev')))
        if cache and (OLD/'phase2/official_thumbs'/cache['cache']).exists():record['reuse_cache']=str(OLD/'phase2/official_thumbs'/cache['cache'])
        images[name]=record
    return name

def category_for(meta,e):
    parts=list(e.get('path') or [meta['title']])
    parts=['连续场景' if x=='连续漫画' else x for x in parts]
    name=' / '.join(parts) if len(parts)>1 else parts[0]+' / 主目录'
    if meta['id'].startswith('artist_') and parts[0]=='画风组词典':name='画师串 / 正文画师串'
    if name not in categories:
        categories[name]={'id':'web-cat-'+hashlib.sha1(name.encode()).hexdigest()[:16],'name':name,'created_at':stamp,'updated_at':stamp,'prompts':[]}
        data['categories'].append(categories[name]);stats['new_source_folders']+=1
    return categories[name]

def folder_for(meta,e):
    parts=list(e.get('path') or [meta['title']]);parts=['连续场景' if p=='连续漫画' else p for p in parts]
    area=parts[0];name=' / '.join(parts[1:]) or '主目录'
    if area not in groups:
        uid=str(uuid.uuid5(uuid.NAMESPACE_URL,'quicktagcloud:area:'+area))
        cur=db.execute('INSERT INTO tag_groups(name,color,create_time,p_uuid) VALUES (?,?,?,?)',(area,'',int(datetime.now().timestamp()),uid))
        groups[area]={'p_uuid':uid,'id_index':cur.lastrowid};stats['new_tag_groups']+=1
    g=groups[area];key=(g['p_uuid'],name)
    if key not in folders:
        uid=str(uuid.uuid5(uuid.NAMESPACE_URL,'quicktagcloud:folder:'+area+'/'+name))
        cur=db.execute('INSERT INTO tag_subgroups(group_id,name,color,create_time,p_uuid,g_uuid) VALUES (?,?,?,?,?,?)',(g['id_index'],name,'',int(datetime.now().timestamp()),g['p_uuid'],uid))
        folders[key]={'id_index':cur.lastrowid,'g_uuid':uid};stats['new_tag_folders']+=1
    return folders[key]

def provenance(meta,e):
    return {'dataset':meta['id'],'entry_id':e['id'],'version':meta.get('version'),'url':source_url(meta,e),'rating':e.get('rating'),'source_model':meta.get('exampleModel') or ('NovelAI v5' if 'nai5' in meta['id'] else 'NovelAI v4.5' if 'suozhang' in meta['id'] or 'nai45' in meta['id'] else None),'negative':e.get('negative',''),'character_prompts':e.get('characterPrompts',[]),'images':e.get('images',[]),'original_url':image_url(meta,e,original=True)}

for number,(meta,e) in enumerate(sources(),1):
    key=source_key(meta,e);body=content(e);match=matching[(meta['id'],e['id'])];entry={'source':key,'source_sha256':hashlib.sha256(json.dumps(e,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'match_method':match['match']}
    reason=exclusion(meta,e)
    if reason:
        entry.update(disposition='excluded',reason=reason);registry.append(entry);stats['excluded']+=1;groupstats[meta['id']]['excluded']+=1;continue
    if not body:
        entry['disposition']='no_prompt_content';registry.append(entry);stats['no_prompt_content']+=1;continue
    pid=match.get('target_id')
    if pid and pid in byid:
        c,p=byid[pid];before=copy.deepcopy(p);action=[]
        # Only an actual publisher revision with a matching previous source can
        # replace a body. Longer local originals and confirmed edits survive.
        if match.get('web_body_changed') and not match.get('same_body'):
            if match.get('local_matches_old') and not match.get('user_confirmed'):
                p['prompt']=body;decision,nodes=classify_new(meta,e,body);p['_classification']=decision;action.append('upstream_body_update')
            else:
                reviews.append({'source':key,'id':pid,'reason':'preserved_local_body_divergence','old_body_sha256':hashlib.sha256(before['prompt'].encode()).hexdigest(),'upstream_body_sha256':hashlib.sha256(body.encode()).hexdigest()})
        old=old_entries.get(e['id'],{})
        revision_changed=old and e.get('image') and (e.get('image'),e.get('assetRev'))!=(old.get('image'),old.get('assetRev'))
        existing_image=p.get('image','')
        image_missing=not existing_image or not (PROD/'user_data/prompt_selector/preview'/existing_image).is_file()
        if e.get('image') and (image_missing or revision_changed and match['match'] in ('id','merged_id')):
            p['image']=plan_image(meta,e);action.append('preview_update')
        if action:
            p['updated_at']=stamp
            if 'upstream_body_update' in action:
                p['_external_source']=provenance(meta,e)
                if not p.get('description'):p['description']=describe(meta,e)
            if isinstance(p.get('_classification'),dict):p['_classification']['binding']=P.binding(c,p)
            operations.append({'store':'library','id':pid,'action':action,'source':key,'before_sha256':hashlib.sha256(json.dumps(before,ensure_ascii=False,sort_keys=True).encode()).hexdigest()})
            for a in action:stats[a]+=1;groupstats[meta['id']][a]+=1
        entry.update(disposition='library_existing',target_id=pid,local_body_sha256=hashlib.sha256(p['prompt'].encode()).hexdigest(),source_details=provenance(meta,e))
    elif len([x for x in re.split('[,，]',body) if x.strip()])<=4 and not e.get('characterPrompts'):
        candidates=tagbodies.get(norm(body),[])
        if candidates:
            uid=min(candidates);m=copy.deepcopy(tagmeta.get(uid,{}));action='tag_existing'
            if e.get('image') and (not m.get('preview') or not (PROD/'user_data/prompt_selector/preview'/m['preview']).is_file()):
                m['preview']=plan_image(meta,e);db.execute('INSERT INTO workbench_tag_meta VALUES (?,?) ON CONFLICT(tag_uuid) DO UPDATE SET data=excluded.data',(uid,json.dumps(m,ensure_ascii=False)))
                tagmeta[uid]=m;stats['tag_preview_added']+=1;groupstats[meta['id']]['tag_preview_added']+=1
                operations.append({'store':'tags','id':uid,'action':['preview_update'],'source':key})
        else:
            folder=folder_for(meta,e);uid=str(uuid.uuid5(uuid.NAMESPACE_URL,'quicktagcloud:body:'+norm(body)))
            assert uid not in tags
            db.execute('INSERT INTO tag_tags(subgroup_id,text,desc,color,create_time,t_uuid,g_uuid) VALUES (?,?,?,?,?,?,?)',(folder['id_index'],body,e.get('title',''),'',int(datetime.now().timestamp()),uid,folder['g_uuid']))
            decision,nodes=classify_new(meta,e,body)
            m={'themes':sorted({TAG_THEME[s] for s in decision['subcategories'] if s in TAG_THEME}),'facets':[],'notes':describe(meta,e),'external_source':provenance(meta,e)}
            if e.get('image'):m['preview']=plan_image(meta,e)
            db.execute('INSERT INTO workbench_tag_meta VALUES (?,?)',(uid,json.dumps(m,ensure_ascii=False)))
            tagmeta[uid]=m;tags[uid]={'text':body};tagbodies[norm(body)].append(uid);action='tag_added'
            operations.append({'store':'tags','id':uid,'action':['add'],'source':key});stats['tag_added']+=1;groupstats[meta['id']]['tag_added']+=1
        entry.update(disposition=action,target_id=uid,source_details=provenance(meta,e))
    else:
        candidates=bybody.get(norm(body),[])
        if candidates:
            pid=min(candidates);entry.update(disposition='library_existing',target_id=pid,source_details=provenance(meta,e))
        else:
            c=category_for(meta,e);pid='codex-'+e['id']
            if pid in byid:pid='web-'+hashlib.sha256(key.encode()).hexdigest()[:24]
            assert pid not in byid
            p={'id':pid,'alias':e.get('title',''),'prompt':body,'description':describe(meta,e),'image':plan_image(meta,e),'tags':[],'favorite':False,'template':False,'is_user_plan':False,'created_at':stamp,'updated_at':stamp,'usage_count':0,'last_used':None,'_external_source':provenance(meta,e)}
            decision,nodes=classify_new(meta,e,body);p['_classification']={**decision,'binding':P.binding(c,p)}
            c['prompts'].append(p);byid[pid]=(c,p);bybody[norm(body)].append(pid)
            entry.update(disposition='library_added',target_id=pid,source_details=provenance(meta,e))
            operations.append({'store':'library','id':pid,'action':['add'],'source':key});stats['library_added']+=1;groupstats[meta['id']]['library_added']+=1
            reviews.append({'source':key,'id':pid,'reason':'new_classification','primary':decision['primary_class'],'parents':decision['subcategories'],'nodes':nodes,'chars':len(body)})
    registry.append(entry)
    if number%5000==0:print('STAGED',number,dict(stats),flush=True)
db.commit()
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
db.close()
data['last_modified']=stamp
with (STAGE/'data.json').open('w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,separators=(',',':'))
shutil.copy2(BACKUP/'semantic_projection.json',STAGE/'semantic_projection.json')
save(HERE/'operations.json',operations);save(HERE/'source_registry.json',registry);save(HERE/'image_plan.json',list(images.values()));save(HERE/'classification_review.json',reviews)
save(HERE/'stage_summary.json',{'created_at':stamp,'stats':dict(stats),'datasets':{k:dict(v) for k,v in groupstats.items()},'records_before':read(HERE/'live_inventory.json')['stats']['total'],'records_after':len(byid),'source_entries':len(registry),'planned_images':len(images),'cached_images':sum('reuse_cache' in x for x in images.values()),'baseline_data_sha256':sha(BACKUP/'data.json'),'stage_data_sha256':sha(STAGE/'data.json'),'stage_db_sha256':sha(STAGE/'tags.db')})
save(HERE/'EXECUTION_STATE.json',{'status':'staged_unreleased','production_mutated':False,'summary':'stage_summary.json','updated_at':now()})
print('STAGE_READY',dict(stats),'images',len(images),flush=True)
