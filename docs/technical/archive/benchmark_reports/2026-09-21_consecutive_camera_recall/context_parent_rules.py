"""Offline recall from explicit atomic tags and unambiguous subject clauses."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('scene_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_scene_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
SUPPORT={**previous.SUPPORT,
 '自然光':r'\b(?:sunlight|sunrise|sunset|daylight|moonlight|natural light|window light|morning light|evening light)\b|阳光|日光|月光',
 '上衣与外套':r'\b(?:shirt|top|jacket|coat|cloak|cape|sweater|cardigan|blouse|hoodie|vest|poncho)\b|上衣|外套|衬衫',
}
BAD={
 '职业与身份':[r'\bplague doctor mask\b'],
 '自然光':[r'\bnatural light transitions\b'],
 '上衣与外套':[r'\bto cloak (?:her|his|their) (?:back|body|shoulders)\b'],
 '拥抱与日常互动':[r'\bboots\s+hugging\s+(?:her|his|their)\s+calves\b'],
}
ATOMIC_PARENTS={'头发与发型','眼睛与瞳色','体型与肤色','身体改造与伤痕','种族与幻想生物','上衣与外套','裙装与礼服','裤装','鞋袜与腿饰','头饰与发饰','制服与职业装','服装材质与剪裁','站姿与跪姿','坐姿与蹲姿','移动与运动','视角与透视','持物与道具互动'}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Mask, light transition or a covering verb; no independent parent evidence.'}
    if '食物与饮料' in parents and re.search(r'["“][^"”]+["”]\s+sign\b',body,re.I) and not re.search(SUPPORT['食物与饮料'],positive,re.I):
        result['食物与饮料']={'false_cues':['quoted sign text'],'reason':'Only printed words, no actual food.'}
    if '武器与装备' in parents and re.search(r'\bkitchen\b',positive) and re.search(r'\b(?:cut|cutting|slice|slicing) (?:a |the )?(?:loaf|bread)\b',positive) and not refinements.extract_refinements(body,['武器与装备']):
        result['武器与装备']={'false_cues':['bread knife'],'reason':'Kitchen utensil, no weapon use or independent weapon.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive='; '.join(parts)
    positive=re.sub(r'\b(?:no|not|without|never|excluding)\s+[^;.!?]+','',positive)
    # Only a complete independent tag qualifies for this path; words buried
    # inside descriptive clauses remain governed by the context rules below.
    atomic=[]
    for part in parts:
        for node in refinements._EXACT.get(part,[]):
            parent=refinements.REFINEMENT_NODES[node]['parent']
            if parent in ATOMIC_PARENTS and parent not in parents and parent not in result:
                atomic.append((node,parent))
    if atomic:
        supported=set(refinements.extract_refinements(body,{parent for node,parent in atomic}))
        result.extend(dict.fromkeys(parent for node,parent in atomic if node in supported))
    for parent,pattern in [
        ('种族与幻想生物',r'\b(?:demon girls?|monster girls?|giant monsters?)\b'),
        ('身体改造与伤痕',r'\bscar on (?:nose|cheek|forehead)\b'),
        ('体型与肤色',r'\bfat body\b'),
        ('头发与发型',r'\bbaldness\b'),
        ('三维与数字渲染',r'\bvoxel art\b'),
        ('室内空间',r'\bindoor (?:bathtub|bathroom|cafe|café) scenes?\b'),
        ('坐姿与蹲姿',r'\b(?:(?:she|he|woman|man|figure) sits\b|sit on (?:a |the )?(?:[a-z-]+ ){0,3}(?:bench|chair|sofa|table)|sitting (?:in (?:an? )?(?:elegant |relaxed )?posture|cross-legged|with (?:her|his) (?:feet|legs) crossed))'),
        ('站姿与跪姿',r'\b(?:she|he|woman|man|figure) stands\b'),
        ('制服与职业装',r'\bflight attendant uniform\b'),
        ('动漫与卡通',r'\bhand-drawn animation\b'),
        ('漫画与线稿',r'\b(?:confident|sweeping) (?:[a-z-]+ ){0,2}linework\b'),
        ('绘画与插画',r'\banimation illustration style\b'),
        ('服装材质与剪裁',r'\bsatin (?:strapless )?dress\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    if '持物与道具互动' not in parents and '持物与道具互动' not in result:
        for part in parts:
            for m in re.finditer(r'\b(?:holds?|holding|grips?|gripping|clutches|clutching)\s+(?:[a-z-]+\s+){0,6}(?:tablet|cake box|pickaxe|knife|umbrella|bouquet|clipboard|tote bag|shopping bag)\b',part):
                before=part[:m.start()]
                if not before.strip() or re.search(r'\b(?:she|he|woman|man|girl|boy|character|figure|hands?|fingers?)\b[^.;!?]{0,70}$',before):
                    result.append('持物与道具互动');break
            if '持物与道具互动' in result:break
    if result:
        rejected=candidates(body,parents+result,refinements)
        result=[parent for parent in result if parent not in rejected]
    return result
