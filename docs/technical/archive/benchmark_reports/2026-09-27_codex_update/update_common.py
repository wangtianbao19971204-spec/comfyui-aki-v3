from audit_matching import HERE, ROOT, PROD, OLD, read, norm, content
from pathlib import Path
from collections import Counter,defaultdict
import copy,hashlib,importlib,json,re,sys,types,unicodedata
from datetime import datetime
from urllib.parse import quote,urljoin

DATA=PROD/'user_data/prompt_selector/data.json'
PROJECTION=DATA.with_name('semantic_projection.json')
DB=PROD/'user_data/userdatas_zh_CN_tags.db'
BACKUP=HERE/'backup';STAGE=HERE/'stage';WEB=HERE/'sources/web'
for directory in (BACKUP,STAGE):directory.mkdir(exist_ok=True)
pkg=types.ModuleType('codex_update_runtime');pkg.__path__=[str(PROD/'prompt_selector')];sys.modules[pkg.__name__]=pkg
P=importlib.import_module(pkg.__name__+'.semantic_projection')
R=importlib.import_module(pkg.__name__+'.semantic_refinements')
T=importlib.import_module(pkg.__name__+'.semantic_taxonomy')
def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def now():return datetime.now().astimezone().isoformat()
def sources():
    for meta in read(WEB/'codexes.json'):
        file=WEB/(meta['id']+'.external.json')
        if not file.exists():file=WEB/(meta['id']+'.json')
        for e in read(file)['entries']:yield meta,e
def source_key(meta,e):return meta['id']+':'+e['id']
def source_url(meta,e):return 'https://novelai.quicktagcloud.com/?c='+quote(meta['id'])+'&id='+quote(e['id'])
def image_url(meta,e,path=None,original=False):
    path=path or e.get('original' if original else 'image')
    if not path:return None
    if meta.get('assetPathMode')=='relative':return urljoin(meta['assetBaseUrl']+'/',path)
    codex=e.get('assetCodexId') or meta['id']
    url='https://assets.quicktagcloud.com/'+('originals/' if original else 'images/')+quote(codex,safe='')+'/'+quote(path,safe='/')
    if e.get('assetRev'):url+='?v='+quote(e['assetRev'],safe='')
    return url
YOUTH=re.compile(r'(?<![a-z])(?:loli(?:con)?|shota(?:con)?|child(?:ren)?|underage|minor|teen(?:age|ager)?|toddler|baby|infant|little girl|little boy|young girl|young boy|schoolgirl|schoolboy|elementary|middle school|high school|kindergarten|kanna kamui|anya forger)(?![a-z])|幼女|幼童|幼儿|未成年|小学生|中学生|初中|高中生|萝莉|正太|康娜|阿尼亚',re.I)
EXPLICIT=re.compile(r'(?<![a-z])(?:nsfw|nude|naked|topless|nipples?|pussy|vulva|penis|sex|sexual|erotic|intercourse|penetrat\w*|cum|semen|creampie|masturbat\w*|fellatio|cunnilingus|paizuri|fingering|orgasm|rape|gangbang)(?![a-z])|性交|性爱|交配|强奸|轮奸|自慰|射精|口交|足交|乳交|手交|露出|裸体|淫|肉便器',re.I)
def exclusion(meta,e):
    positive=T.strip_nonpositive_nai_weights(content(e)).replace('_',' ')
    title=e.get('title','');path=' / '.join(e.get('path',[]))
    age=YOUTH.search(positive+' '+title+' '+path) or re.search(r'\b(?:hoto cocoa|kafuu chino)\b',positive,re.I)
    sexual=EXPLICIT.search(positive+' '+title) or e.get('rating') in ('explicit','nsfw','r18') or bool(meta.get('nsfw'))
    if age and sexual:return 'age_sensitive_sexual_content'
    return None

def describe(meta,e):
    parts=['来源：'+meta['title']+'；版本：'+str(meta.get('version','')),source_url(meta,e)]
    if e.get('note'):parts.append('原注：\n'+e['note'])
    if e.get('negative'):parts.append('负面提示词（不并入正向正文）：\n'+e['negative'])
    for cp in e.get('characterPrompts',[]):
        if cp.get('negative'):parts.append(str(cp.get('label','角色'))+' 负面：\n'+cp['negative'])
    return '\n\n'.join(parts)

def classify_new(meta,e,body):
    # New entries use the already deployed phrase and context guards. Existing
    # records are never bulk reclassified by this import.
    artist=meta['id'].startswith('artist_') or '画师' in ' '.join(e.get('path',[]))
    if artist:
        subs=['画师组合' if len([v for v in body.split(',') if 'artist:' in v])>1 or '画师组' in ' '.join(e.get('path',[])) else '画师标签']
        primary='artist_style';nodes=[]
    else:
        nodes=R.extract_refinements(body,list(T.SUBCATEGORY_PARENTS),enable_soft_modifier_cues=True)
        subs=sorted({R.REFINEMENT_NODES[n]['parent'] for n in nodes})
        owners=Counter(T.SUBCATEGORY_PARENTS[s] for s in subs)
        # Explicit source role helps choose the main axis; memberships still
        # require a phrase recognized in the complete positive body.
        path=' / '.join(e.get('path',[]))
        prefer='clothing_accessory' if meta['id'] in ('kisegaeningyou','qianteng') or '服装' in path or '服饰' in path else None
        if prefer in owners:primary=prefer
        elif owners:primary=owners.most_common(1)[0][0]
        elif re.search(r'artist\s*:',body,re.I):primary='artist_style';subs=['画师标签']
        else:primary=None
    owners={T.SUBCATEGORY_PARENTS[s] for s in subs}
    count=T.original_count_markers(body)
    if count:owners.add('person_count')
    decision={'disposition':'classified','primary_class':primary,'content_type':'template' if len([x for x in body.split(',') if x.strip()])>4 else 'fragment','usage':'positive','declared_usage':'positive','model_scope':'unknown','themes':[],'manual_search_eligible':True,'random_pool_eligible':False,'strict_model_pool_eligible':False,'semantic_review_status':'source_import_with_current_rules','alternative_classes':sorted(owners-{primary}),'classification_uncertain':primary is None,'subcategories':subs,'count_markers':count,'taxonomy_version':'2026-09-20-v1','note_kind':'review_note','note':'新增资料按 2026-09-27.01 现行正文规则归属；来源和模型保持独立。'}
    return decision,list(nodes)

TAG_THEME={'上衣与外套':'服饰›上装','裙装与礼服':'服饰›下装','裤装':'服饰›下装','鞋袜与腿饰':'服饰›鞋袜','首饰与随身配饰':'服饰›配饰','头饰与发饰':'服饰›配饰','家具与生活用品':'道具›器物','交通与机械':'道具›器物','武器与装备':'道具›器物','职业与身份':'角色›职业','作品角色':'角色›原作','种族与幻想生物':'角色›种族','动物主体':'生物›动物','植物与花园':'生物›植物','室内空间':'场景›室内','自然地貌与水域':'场景›室外','天空与天气':'场景›室外','光影效果':'画面›打光','自然光':'画面›打光','人工光与发光':'画面›打光','色彩与调色':'画面›配色','性交与体位':'成人›性交','口部互动':'成人›前戏','亲密互动':'成人›前戏','视角与透视':'画面›构图','布局与画面结构':'画面›构图','质量与分辨率':'画风›画质'}
