"""Recall explicit content evidence through the reviewed refinement vocabulary."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('precision_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_context_precision/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
SUPPORT={**previous.SUPPORT,
 '交通与机械':r'\b(?:car|cars|truck|train|subway|metro|tram|bus|buses|bicycle|motorcycle|aircraft|robot|mecha|machine|mechanical)\b',
}
# These domains have concrete nouns or qualified descriptive phrases. Generic
# motion, occupational, emotional and adult interpretations remain excluded.
RECALL={'头发与发型','眼睛与瞳色','头饰与发饰','上衣与外套','裙装与礼服','裤装','鞋袜与腿饰','首饰与随身配饰','制服与职业装','传统与民族服饰','泳装与内衣','奇幻与角色服饰','身体改造与伤痕','非人特征','视角与透视','纯色与抽象背景','室内空间'}
ATOMIC=RECALL|{'动物与拟人','动物主体','交通与机械','植物与花园','自然地貌与水域','天空与天气','漫画与线稿','绘画与插画','动漫与卡通','水彩与油画','家具与生活用品','食物与饮料','武器与装备','裸露与遮盖','体型与肤色','服装材质与剪裁'}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    if '交通与机械' in parents and 'machine vision' in positive:
        remaining=re.sub(r'\bmachine vision\b','',positive)
        if not re.search(SUPPORT['交通与机械'],remaining):result['交通与机械']={'false_cues':['machine vision'],'reason':'Visual processing aesthetic, no mechanical subject.'}
    if '拥抱与日常互动' in parents:
        remaining=re.sub(r'\b(?:stockings|socks|tights|boots)\b[^.;!?]{0,85}\b(?:hug|hugging) (?:her|his|their|the) (?:legs|calves|feet)\b','',positive)
        if remaining!=positive and not re.search(SUPPORT['拥抱与日常互动'],remaining):result['拥抱与日常互动']={'false_cues':['garment fits legs'],'reason':'Garment fit, no interpersonal embrace.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive='; '.join(parts)
    positive=re.sub(r'\b(?:no|not|without|never|excluding)\s+[^;.!?]+','',positive)
    wanted=(RECALL|ATOMIC)-set(parents)-set(result)
    nodes=refinements.extract_refinements(body,wanted)
    for node in nodes:
        item=refinements.REFINEMENT_NODES[node];parent=item['parent']
        if parent in result:continue
        if node=='weather.fog' and 'indoors' in parts and 'onsen' in parts and 'steam' in parts:continue
        if parent in RECALL or any(node in refinements._EXACT.get(part,[]) for part in parts):result.append(parent)
    for parent,pattern in [
        ('交通与机械',r'\b(?:super robot|subway(?: carriage)?)\b'),
        ('头饰与发饰',r'\b(?:hair bobbles|headpiece|flower tucked behind (?:her|his|the) ear)\b'),
        ('传统与民族服饰',r'\b(?:taichou haori|haori)\b'),
        ('首饰与随身配饰',r'\bascot\b'),
        ('种族与幻想生物',r'\b(?:traditional youkai|youkai \(youkai watch\))'),
        ('作品角色',r'\b(?:monitoring \(vocaloid\)|pokemon)\b'),
        ('动漫与卡通',r'\b(?:anime artwork|visual novel cg)\b'),
        ('绘画与插画',r'\b(?:beautiful illustration|illustration aesthetics)\b'),
        ('漫画与线稿',r'\bdelicate linework\b'),
        ('鞋袜与腿饰',r'\bleg garter\b'),
        ('泳装与内衣',r'\bbustier\b(?![- ](?:style )?(?:dress|gown)\b)'),
        ('上衣与外套',r'\bstrapless top\b'),
        ('室内空间',r'\b(?:inside the (?:subway|train) carriage|(?:stands|sits) at a bar)\b'),
        ('植物与花园',r'\b(?:potted (?:[a-z-]+ ){0,2}(?:ferns?|plants?)|bouquet of (?:[a-z-]+ ){0,3}roses)\b'),
        ('视角与透视',r'\b(?:pov peephole|overhead angle)\b'),
        ('纯色与抽象背景',r'\bbackground is pure (?:light |dark )?(?:gray|grey|white|black)\b'),
        ('坐姿与蹲姿',r'\b(?:woman|man|figure|she|he)\b[^.!?]{0,160}\bsits(?: [a-z]+ly)? on\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    if '服装材质与剪裁' not in parents and '服装材质与剪裁' not in result and re.search(r'\b(?:lace|leather|silk|denim|velvet)\b[^.;!?]{0,35}\b(?:dress|gown|top|coat|jacket|shirt|skirt|pants|sleeves)\b',positive):result.append('服装材质与剪裁')
    if '持物与道具互动' not in parents and '持物与道具互动' not in result:
        for part in parts:
            for m in re.finditer(r'\b(?:holds?|holding|grips?|gripping)\s+(?:[a-z-]+\s+){0,7}(?:bag|device|carving|staff|cup|phone|smartphone|microphone|guitar|bass|umbrella|bouquet|book)\b',part):
                before=part[:m.start()]
                if re.search(r'(?:^|[.!?])\s*$',before) or re.search(r'\b(?:she|he|woman|man|figure|hands?|fingers?)\b[^.;!?]{0,70}$',before):
                    result.append('持物与道具互动');break
            if '持物与道具互动' in result:break
        if '持物与道具互动' not in result and re.search(r'\b(?:phone|smartphone|device|cup|book) in (?:her |his |the )?hands?\b',positive):result.append('持物与道具互动')
    rejected=candidates(body,parents+result,refinements)
    return [parent for parent in result if parent not in rejected]
