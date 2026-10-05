"""Offline repairs and narrow recall of explicit subject/object facts."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('material_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_material_contexts/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
BAD={
 '城市与街道':[r'\bstreet (?:culture vibe|selfie style)\b',r'\burban (?:young )?woman\b',r'\b(?:urban )?street-style snapshot\b'],
 '天空与天气':[r'\b(?:bishoujo senshi )?sailor moon\b'],
 '拥抱与日常互动':[r'\b(?:stockings|pants|skirt)\s+(?:that )?hugg?ing\s+(?:her|his|their)\s+(?:slender |long )?(?:legs|thighs|hips)\b'],
 '愤怒与不满':[r'\bsuggestive pout\b'],
 '植物与花园':[r'\b(?:woven )?grass basket\b'],
 '建筑与设施':[r'\bnose bridge\b'],
 '职业与身份':[r'\bkawasaki (?:[a-z0-9-]+ )?ninja\b',r'["“]?ninja["”]? logos?\b'],
 '持物与道具互动':[r'\bas if (?:capturing|evoking) (?:a )?moment of afternoon reading\b'],
 '漫画与线稿':[r'\bline art piece\b'],
 '食物与饮料':[r'\b(?:red |white )?wine glasses\b'],
}
SUPPORT={**previous.SUPPORT,
 '建筑与设施':r'\b(?:buildings?|architecture|structures?|arch|arches|bridges?|towers?|castles?|church|temple|factory|industrial|station|ruins?|stadium|library|laboratory|railway|overpass)\b|建筑|桥|塔|拱',
 '漫画与线稿':r'\b(?:line art|lineart|manga|comic|sketch|ink|screentone|linework)\b|漫画|线稿|素描',
 '食物与饮料':r'\b(?:food|drink|wine|beer|juice|milk|tea|coffee|bread|cake|fruit|meat|rice|soup|vegetable|ice cream|cocktail|alcohol)\b|食物|饮料|水果|咖啡|果汁',
}
def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Named object, anatomy, material or depicted artwork; independent parent evidence absent.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive='; '.join(parts)
    for parent,pattern in [
        ('身体改造与伤痕',r'\b(?:burn scar|scar on (?:face|chest)|quadruple amputee)\b'),
        ('奇幻与角色服饰',r'\bbreastplate\b'),
        ('头饰与发饰',r'\bcirclet\b'),
        ('职业与身份',r'\b(?:female |male )?flight attendant\b(?![- ]style|\s+(?:uniform|outfit|costume))'),
        ('上衣与外套',r'\b(?:sleeveless|short-sleeve|long-sleeve) (?:[a-z-]+ ){0,2}top\b'),
        ('移动与运动',r'\bfigure skater\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    if '持物与道具互动' not in parents:
        for part in parts:
            for m in re.finditer(r'\b(?:holds?|holding|grips?|gripping|clutches|clutching)\s+(?:up\s+)?(?:[a-z-]+\s+){0,6}(?:bottle|glass|phone|smartphone|drumstick|newspaper|book|handbag|telescope|helmet|cup|ball|receiver|handlebars)\b',part):
                before=part[:m.start()]
                if not before.strip() or re.search(r'\b(?:she|he|woman|man|girl|boy|character|figure|hands?|fingers?)\b[^.;!?]{0,70}$',before):
                    result.append('持物与道具互动');return result
    return result
