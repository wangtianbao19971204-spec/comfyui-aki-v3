"""Offline repair of explicit scene evidence and misleading object phrases."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('evidence_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_evidence_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
SUPPORT={**previous.SUPPORT,
 '首饰与随身配饰':r'\b(?:ring|rings|earrings?|necklace|bracelet|choker|pendant|jewelry|gloves?|glasses|eyewear|mask|scarf|belt|bag|handbag|watch|necktie|tie)\b|首饰|戒指|耳环|项链',
 '种族与幻想生物':r'\b(?:angel|demon|devil|elf|fairy|youkai|cyclops|harvin|monster|vampire|succubus|incubus|zombie|ghost|dragon)\b|天使|恶魔|精灵|怪物',
 '传统与民族服饰':r'\b(?:kimono|yukata|hakama|haori|qipao|cheongsam|hanfu|hanbok|sari|traditional clothes|japanese clothes|chinese clothes)\b|和服|汉服|旗袍',
 '卧姿与趴姿':r'\b(?:lying|reclining|reclined|prone|supine|on stomach|on back)\b|侧卧|趴着|躺',
}
BAD={
 '传统与民族服饰':[r'\broyal robe\b'],
 '头发与发型':[r'\bhair bells?\b'],
 '自然地貌与水域':[r'\bcelestial river\b'],
 '首饰与随身配饰':[r'\bthe ring\b',r'\b(?:cuffs and collar|collar and cuffs)\b'],
 '移动与运动':[r'\bdynamic pose\b'],
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,patterns in BAD.items():
        if parent not in parents:continue
        remaining=positive;cues=[]
        for pattern in patterns:
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):result[parent]={'false_cues':cues,'reason':'Object component, title or figurative scene; no independent parent evidence.'}
    if '卧姿与趴姿' in parents and 'on side' in positive and re.search(r'\b(?:standing|squatting)\b',positive) and not re.search(SUPPORT['卧姿与趴姿'],positive):
        result['卧姿与趴姿']={'false_cues':['on side with upright pose'],'reason':'Side position in an explicitly upright scene, no lying posture.'}
    if '种族与幻想生物' in parents and re.search(r'(?:reading|text)\s*[:：]?\s*[“"]?[^,;.!?]*天使',body.replace('_',' '),re.I) and not re.search(SUPPORT['种族与幻想生物'],positive,re.I):
        result['种族与幻想生物']={'false_cues':['angel in lettering'],'reason':'Only text contains the species word.'}
    if '持物与道具互动' in parents and re.search(r'\bsign reading\b',positive):
        remaining=re.sub(r'\b(?:neon )?sign reading\b','sign',positive)
        remaining=re.sub(r"\bgrabbing another's ass\b",'',remaining)
        if not re.search(SUPPORT['持物与道具互动'],remaining):result['持物与道具互动']={'false_cues':['sign reading'],'reason':'Reading describes lettering, not a person using a prop.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive=re.sub(r'\b(?:no|not|without|never|excluding)\s+[^;.!?]+','','; '.join(parts))
    for parent,pattern in [
        ('种族与幻想生物',r'\b(?:harvin|cyclops)\b'),
        ('身体改造与伤痕',r'\bmechanical (?:arm|leg)\b'),
        ('鞋袜与腿饰',r'\bstocking\b'),
        ('服装材质与剪裁',r'\blatex\b[^.;!?]{0,35}\b(?:stockings?|bodysuit|cape|dress|gloves|boots|suit)\b'),
        ('制服与职业装',r'\b(?:navy-style uniform|(?:airline )?stewardess dress)\b'),
        ('交通与机械',r'\byacht\b'),
        ('站姿与跪姿',r'\b(?:standing at|(?:woman|man|figure|she|he)\b[^.!?;]{0,140}\bstands? (?:in|beside|at)|she kneels|he kneels)\b'),
        ('坐姿与蹲姿',r'\b(?:half-crouches|(?:woman|man|she|he) sat (?:by|on|in))\b'),
        ('穿脱与整理',r'\bsliding\b[^.!?;]{0,70}\bhigh heel off\b'),
        ('手势与肢体动作',r'\b(?:five-finger gesture|hand is raised)\b'),
        ('视角与透视',r'\blow-angle (?:composition|shot|view)\b'),
        ('幻想与科幻环境',r'\b(?:celestial river|toy block kingdom)\b'),
        ('文字与图形',r'\b(?:video website interface|neon sign reading)\b'),
        ('室内空间',r'\bairport lobby\b'),
        ('头饰与发饰',r'\b(?:hairclips?|hair clips?|rose tucked (?:in|into) her hair|rose is pinned above her forehead)\b'),
        ('建筑与设施',r'\b(?:chinese |traditional )?pavilion\b'),
        ('植物与花园',r'\b(?:green vegetation|palm fronds|monstera plant|scattered (?:[a-z-]+ )?roses)\b'),
    ]:
        text=re.sub(r'\bpanty and stocking with garterbelt(?: style)?\b','',positive) if parent=='鞋袜与腿饰' else positive
        if parent not in parents and parent not in result and re.search(pattern,text):result.append(parent)
    if any(part in {'koi','carp'} for part in parts) and '动物主体' not in parents and '动物主体' not in result:result.append('动物主体')
    if 'painterly' in parts and '绘画与插画' not in parents and '绘画与插画' not in result:result.append('绘画与插画')
    if 'the ring' in parts and '作品角色' not in parents and '作品角色' not in result:result.append('作品角色')
    if '持物与道具互动' not in parents and '持物与道具互动' not in result:
        for part in parts:
            for m in re.finditer(r'\b(?:holds?|holding|grips?|gripping|carrying)\s+(?:[a-z-]+\s+){0,7}(?:parasol|luggage|suitcase|rose|flower)\b',part):
                before=part[:m.start()]
                if re.search(r'\b(?:hand-drawn|drawing of|painting of|cartoon bear)\b',before):continue
                if re.search(r'(?:^|[.!?])\s*$',before) or re.search(r'\b(?:she|he|woman|man|figure|hands?|fingers?)\b[^.;!?]{0,70}$',before):
                    result.append('持物与道具互动');break
            if '持物与道具互动' in result:break
    rejected=candidates(body,parents+result,refinements)
    return [parent for parent in result if parent not in rejected]
