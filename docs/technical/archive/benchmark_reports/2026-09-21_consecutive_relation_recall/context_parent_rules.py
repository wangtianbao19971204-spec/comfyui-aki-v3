"""Recall explicit subject relations without treating depicted props as anatomy."""
import importlib.util
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('literal_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_literal_core/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL|{'自然光','手势与肢体动作','拥抱与日常互动','站姿与跪姿','坐姿与蹲姿','细节与材质'}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern,support in [
      ('武器与装备',r'\bfinger gun\b',r'\b(?:weapons?|armor|armour|bulletproof|shield|whip|blade|spear|axe)\b'),
      ('动物主体',r'\b(?:butterfly|bunny|rabbit|bird|horse|fish|dog) (?:decorations?|ornaments?|motifs?|tags|dildo|mask|toy)\b',r'\b(?:animals?|birds?|horses?|dogs?|cats?|insects?|doberman)\b'),
      ('非人特征',r'\banal tail\b',r'\b(?:horns?|wings?|fangs?|claws?|pointy ears|animal ears)\b'),
      ('移动与运动',r'\b(?:(?:dark )?shadows?|fish|ducks?) swimming\b|\bclimbing (?:vines?|plants?)\b',r'\b(?:walks?|walking|runs?|running|jumping|dancing|climbing|swimming(?! pool)|flying)\b'),
      ('绘画与插画',r'\b(?:as if )?writing or painting\b',r'\b(?:illustration|painting|painted|digital art)\b'),
    ]:
        if parent not in parents:continue
        remaining=re.sub(pattern,' ',positive)
        if remaining!=positive and not refinements.extract_refinements(body,[parent]) and not re.search(support,remaining):
            result[parent]={'false_cues':re.findall(pattern,positive),'reason':'The cue describes a gesture, decoration, artificial prop or a non-person subject.'}
    if '室内空间' in parents and re.search(r'\bsign reading\b[^.!?;]{0,60}\bcafe\b|\bcafe["”]?\s+signs?\b',positive) and not refinements.extract_refinements(body,['室内空间']) and not re.search(r'\b(?:indoors|interior|inside|room)\b',positive):
        result['室内空间']={'false_cues':['cafe sign'],'reason':'A sign on the street does not establish an interior.'}
    if '非人特征' in parents and 'petal-like tail' in positive and not refinements.extract_refinements(body,['非人特征']):
        result['非人特征']={'false_cues':['petal-like tail of a silk decoration'],'reason':'A decorative object shape is not anatomical evidence.'}
    if '植物与花园' in parents and refinements._scene_text(body)!=body and not refinements.extract_refinements(body,['植物与花园']):
        remaining='; '.join(refinements._positive_parts(refinements._scene_text(body)))
        if not re.search(r'\b(?:berries|foliage|greenery|shrubs|plants?|garden|trees?|leaves)\b',remaining):
            result['植物与花园']={'false_cues':['hair flower list'],'reason':'Flowers are attached hair decorations; independent vegetation is absent.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body);positive='; '.join(parts)
    for node in refinements.extract_refinements(body,RECALL-set(parents)-set(result)):
        parent=refinements.REFINEMENT_NODES[node]['parent']
        if parent not in result:result.append(parent)
    for parent,pattern in [
      ('家具与生活用品',r'\b(?:headphones?|head-mounted display|tennis racket|disco balls?|stools?|dslr|plush (?:horse |rabbit |bunny )?toy)\b'),
      ('建筑与设施',r'\b(?:bunker|railings?|stone dungeon)\b'),
      ('武器与装备',r'\b(?:bulletproof vest|magic whip)\b'),
      ('制服与职业装',r'\bbikesuit\b'),
      ('奇幻与角色服饰',r'\bcatsuit\b'),
      ('穿着状态',r'\b(?:torn (?:underwear|cloak)|discarded[^.;!?]{0,35}(?:top|coat)|rolled.up skirt)\b'),
      ('服装材质与剪裁',r'\b(?:thick-knit[^.;!?]{0,35}sweater|lantern-shaped cuffs)\b'),
      ('人工光与发光',r'\b(?:wall lamps?|camera flashes|lasers?|overhead lights?|fluorescent lights?)\b'),
      ('手势与肢体动作',r'\b(?:finger gun|grabbing another.s wrist|arched back|head tilt|leaning forward|hugging own legs|arms wrapped around (?:her |his |the )?knees|casual wave)\b'),
      ('首饰与随身配饰',r'\bdetached collar\b'),
      ('视线方向',r'\blooking at phone\b'),
      ('成人道具',r'\banal tail\b'),
      ('细节与材质',r'\bultra-detailed\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    artist_text=refinements.strip_nonpositive_nai_weights(body.lower())
    artist_text=re.split(r'negative[ _]prompt\s*:|负面提示词\s*[:：]',artist_text,maxsplit=1)[0]
    artist_text=re.sub(r'\([^()]*(?::\s*(?:-\d+(?:\.\d+)?|0(?:\.0+)?)\s*)\)','',artist_text)
    artists={' '.join(m.strip(' []{}()').replace('_',' ').split()) for m in re.findall(r'\bartist\s*:\s*([^,;:\[\]]+)',artist_text)}
    if artists:
        parent='画师组合' if len(artists)>1 else '画师标签'
        if parent not in parents and parent not in result:result.append(parent)
    rejected=candidates(body,parents+result,refinements)
    return [p for p in result if p not in rejected]
