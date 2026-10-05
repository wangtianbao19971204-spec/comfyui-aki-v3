"""Recall concrete domains through the reviewed contextual vocabulary."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('language_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_language_contexts/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
SUPPORT={**previous.SUPPORT,
 '传统与民族服饰':previous.SUPPORT['传统与民族服饰']+r'|\b(?:toga|greco-roman clothes|ancient greek clothes|ancient attire|uchikake|wataboushi|sarashi)\b|韩服|浴衣|纱丽|巫女服|民族服饰',
 '身体改造与伤痕':r'\b(?:tattoo|scar|scars|bandages?|bandaid|prosthetic|mechanical (?:arm|leg)|piercing|nose stud|bruise)\b|纹身|伤疤|绷带|穿孔',
 '食物与饮料':r'\b(?:food|drink|tea|coffee|juice|milk|wine|beer|sake|cocktail|rice|bread|cake|fruit|apple|strawberry|honey|chocolate)\b|食物|饮料|酒|茶|咖啡',
 '自慰':r'\b(?:masturbation|masturbating|self[- ]pleasure|self[- ]stimulation|fingering (?:herself|himself)|self fingering)\b|自慰',
}
RECALL=previous.previous.RECALL|{
 '面部特征','服装材质与剪裁','穿着状态','植物与花园','建筑与设施','城市与街道','自然地貌与水域',
 '交通与机械','家具与生活用品','食物与饮料','武器与装备','文字与图形','绘画与插画','水彩与油画',
 '漫画与线稿','动漫与卡通','手势与肢体动作','裸露与遮盖',
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    parts=refinements._positive_parts(body);positive='; '.join(parts)
    bad={
      '卧姿与趴姿':[r'\bbent over\b'],
      '传统与民族服饰':[r'\b(?:(?:open|purple|white|black) )?robe\b'],
      '食物与饮料':[r'\bwine glass\b'],
      '动漫与卡通':[r'\bcartoon patterns?\b'],
    }
    for parent,patterns in bad.items():
        if parent not in parents:continue
        remaining=positive;cues=[]
        for pattern in patterns:
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if parent=='传统与民族服饰' and refinements.extract_refinements(remaining,[parent]):
            result.pop(parent,None)
            continue
        if cues and not re.search(SUPPORT[parent],remaining,re.I):result[parent]={'false_cues':cues,'reason':'The phrase describes posture, clothing or a container; no independent parent evidence.'}
    if '身体改造与伤痕' in parents:
        remaining=positive;cues=[]
        for part in parts:
            for m in re.finditer(r'\bpiercing\b',part):
                if not refinements._phrase_allowed('身体改造与伤痕','piercing',part,m.start(),m.end()):
                    cues.append('piercing eyes');remaining=remaining.replace(part,part[:m.start()]+' '+part[m.end():])
        if cues and not re.search(SUPPORT['身体改造与伤痕'],remaining):result['身体改造与伤痕']={'false_cues':cues,'reason':'Piercing describes gaze rather than a body modification.'}
    if '自慰' in parents and 'fingering' in parts and not re.search(SUPPORT['自慰'],positive):
        result['自慰']={'false_cues':['unqualified fingering'],'reason':'Finger contact does not identify a self-directed act.'}
    if '服装材质与剪裁' in parents and 'spider web' in positive and 'silk' in parts and not re.search(r'\b(?:dress|shirt|pants|skirt|coat|jacket|gloves|stockings|clothes|outfit|bodysuit)\b',positive):
        result['服装材质与剪裁']={'false_cues':['silk in spider webs'],'reason':'Natural web material, no garment material.'}
    if '动漫与卡通' in parents and 'cartoon figures' in positive and re.search(r'\b(?:camisole|shirt|dress)\b[^;]{0,130}\bpattern\b',positive):
        remaining=positive.replace('cartoon figures','')
        if not re.search(SUPPORT['动漫与卡通'],remaining):result['动漫与卡通']={'false_cues':['cartoon figures in clothing pattern'],'reason':'Pattern on a garment, not the image medium.'}
    if '纯色与抽象背景' in parents and 'dark background' in positive and re.search(r'\bbackground is (?:an? )?(?:outdoor scene|street|city|room)\b',positive):
        if not any(part in {'black background','dark background','simple background'} for part in parts):result['纯色与抽象背景']={'false_cues':['dark background within a real setting'],'reason':'A dark real setting is not a plain or abstract backdrop.'}
    if '城市与街道' in parents and re.search(r'\blike (?:a )?tranquil moment captured in a park or courtyard\b',positive):
        remaining=re.sub(r'\blike (?:a )?tranquil moment captured in a park or courtyard\b','',positive)
        if not re.search(r'\b(?:city|street|sidewalk|urban|alley|park)\b',remaining):result['城市与街道']={'false_cues':['comparison to a park'],'reason':'Comparison describes mood; actual scene is a path in woods.'}
    if '服装材质与剪裁' in parents:
        remaining=re.sub(r'\b(?:leather briefcase|silk fan)\b','',positive)
        if 'spider silk' in remaining and not re.search(r'\b(?:dress|shirt|pants|skirt|coat|jacket|gloves|stockings|clothes|outfit|bodysuit)\b',remaining):
            remaining=re.sub(r'\b(?:spider silk|see-through)\b','',remaining)
        if remaining!=positive and not refinements.extract_refinements(remaining,['服装材质与剪裁']):
            result['服装材质与剪裁']={'false_cues':['material of a prop or natural restraint'],'reason':'No independent garment material remains.'}
    if '植物与花园' in parents:
        remaining=re.sub(r'\bbamboo wall\b','',positive)
        if remaining!=positive and not refinements.extract_refinements(remaining,['植物与花园']):
            result['植物与花园']={'false_cues':['bamboo wall'],'reason':'Building material without independent live plants.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive=re.sub(r'\b(?:no|not|without|never|excluding)\s+[^;.!?]+','','; '.join(parts))
    for node in refinements.extract_refinements(body,RECALL-set(parents)-set(result)):
        parent=refinements.REFINEMENT_NODES[node]['parent']
        if parent not in result:result.append(parent)
    for parent,pattern in [
        ('身体改造与伤痕',r'\bbandaid\b'),
        ('鞋袜与腿饰',r'\b(?:green|red|blue|black|white|brown) footwear\b'),
        ('家具与生活用品',r'\b(?:flute|recorder|oven)\b'),
        ('制服与职业装',r'\bgraduation gown\b'),
        ('头饰与发饰',r'\b(?:hood up|ribbon wound through (?:her hair|it))\b'),
        ('穿着状态',r'\b(?:hood up|open coat|open jacket|open robe)\b'),
        ('服装材质与剪裁',r'\bfur trim\b'),
        ('纯色与抽象背景',r'\b(?:pure black or deep gray background|solid-colored wall)\b'),
        ('人工光与发光',r'\bstudio-lit\b'),
        ('文字与图形',r'\b(?:game screenshot|viewfinder overlay)\b'),
        ('裸露与遮盖',r'\b(?:complete nude|bare (?:breasts|chest)|lower body fully exposed)\b'),
        ('手势与肢体动作',r'\b(?:raise (?:your|her|his|the) (?:right|left) hand|lift the (?:right|left) leg)\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    # Posture must belong to a person; furniture standing or sitting is not enough.
    for parent,pattern in [
        ('站姿与跪姿',r'\b(?:standing(?: behind (?:girl|boy))?|kneeling|kneels)\b'),
        ('坐姿与蹲姿',r'\b(?:sitting|seated|squatting|squats)\b'),
    ]:
        if parent in parents or parent in result:continue
        if any(re.fullmatch(pattern,part) for part in parts):result.append(parent)
    rejected=candidates(body,parents+result,refinements)
    return [parent for parent in result if parent not in rejected]
