"""Retain literal subject evidence and recall explicit viewing and light cues."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('structured_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_structured_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL|{'色彩与调色','焦点与景深','景别与主体占比','视线方向','人工光与发光','局部特写','眼口表情'}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern,support in [
      ('植物与花园',r'\btree of savior\b|\b(?:rose|flower) tattoos?\b|\bbamboo weave\b',r'\b(?:plants?|foliage|leaves|blossoms|garden|trees?|forest|flowers?|bamboo)\b'),
      ('穿脱与整理',r'\bdressing room\b',r'\b(?:adjusting|undressing|removing clothes|putting on clothes|pulling up|peeling (?:the )?glove off)\b'),
      ('首饰与随身配饰',r'\bring of (?:[a-z-]+\s+){0,3}stains\b',r'\b(?:jewelry|jewellery|necklace|earrings|bracelet|gloves|belt|collar|chain|scarf)\b'),
      ('视角与透视',r'\b(?:high|low)[ -]angle (?:sunlight|lighting|light|glare)\b',r'\b(?:perspective|camera angle|viewpoint|pov|aerial)\b'),
      ('视线方向',r'\b(?:high|low)[ -]angle looking (?:down|up)\b',r'\b(?:gaze|gazes|staring|looking at viewer|looking at camera)\b'),
    ]:
        if parent not in parents:continue
        remaining=re.sub(pattern,'',positive)
        if remaining!=positive and not refinements.extract_refinements(remaining,[parent]) and not re.search(support,remaining):
            result[parent]={'false_cues':re.findall(pattern,positive),'reason':'Named reference, depicted pattern, object or lighting cue rather than this subject.'}
    if '非人特征' in parents and re.search(r'\bgloves\b[^.;!?]{0,80}\bclaws\b',positive) and not refinements.extract_refinements(body,['非人特征']):
        result['非人特征']={'false_cues':['claws on gloves'],'reason':'Costume attachment rather than anatomical nonhuman trait.'}
    if '移动与运动' in parents and re.search(r'\b(?:curtain movement|maggots squirming|wriggling maggots)\b',positive) and not re.search(r'\b(?:walking|running|jumping|swimming|flying|dancing|climbing)\b',positive):
        result['移动与运动']={'false_cues':['object or insect movement'],'reason':'Movement is not performed by the person.'}
    if '室内空间' in parents and re.search(r'\boutside (?:[a-z]+\s+){0,3}library\b',positive) and not re.search(r'\b(?:indoors|inside (?:the |a )?library)\b',positive):
        result['室内空间']={'false_cues':['outside library'],'reason':'Explicitly outside the building.'}
    contextual={
      '城市与街道':(r'\bstreet lamps\b|\burban detachment\b|\bas if[^.;!?]{0,90}camera on the street\b|\bstreet edge\b',r'\b(?:city|street|sidewalk|urban|alley|park)\b'),
      '食物与饮料':(r'\btea room\b',previous.SUPPORT['食物与饮料']),
      '服装材质与剪裁':(r'\bleather handbag\b|\bhandbag is[^.!?]*|\bchair is[^.!?]*',r'\b(?:lace|silk|satin|leather|mesh|knit|denim|velvet|fur|sheer|transparent)\b'),
      '动漫与卡通':(r'\bcartoon silhouette\b',r'\b(?:anime|cartoon|animated)\b'),
      '穿着状态':(r'\boff-shoulder bag\b',r'\b(?:wet clothes|open coat|unbuttoned)\b'),
      '自然地貌与水域':(r'\bwall displays[^.!?]*|\bbrows like distant mountains\b',None),
      '建筑与设施':(r'\bschool emblem\b|\bcampus atmosphere\b',None),
      '首饰与随身配饰':(r'\bring light\b',None),
      '植物与花园':(r'\bgauze flower\b',None),
      '裙装与礼服':(r'\bdress she wore is gone\b',None),
    }
    for parent,(pattern,support) in contextual.items():
        if parent not in parents:continue
        # Restrict material cleanup to handbag descriptions with no worn material.
        if parent=='服装材质与剪裁' and 'leather handbag' not in positive:continue
        remaining=re.sub(pattern,' ',positive)
        if remaining!=positive and not refinements.extract_refinements(remaining,[parent]) and not (support and re.search(support,remaining)):
            result[parent]={'false_cues':re.findall(pattern,positive),'reason':'Object, depiction, absent garment or comparison without independent subject evidence.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for node in refinements.extract_refinements(body,RECALL-set(parents)-set(result)):
        parent=refinements.REFINEMENT_NODES[node]['parent']
        if parent not in result:result.append(parent)
    for parent,pattern in [
      ('服装材质与剪裁',r'\b(?:knitted (?:cardigan|scarf|sweater)|knit cardigan|faux fur coat|lace-trimmed bralette|transparent short puff sleeves)\b'),
      ('穿着状态',r'\b(?:wet clothes|panties aside|pantie aside|open (?:black )?graduation gown|(?:coat|shirt|blazer|cardigan|jacket)[^.;!?]{0,40}(?:unbuttoned|slipping|open))\b'),
      ('裸露与遮盖',r'\b(?:bare breasts?|exposed pussy|one bare breast)\b'),
      ('视线方向',r'\b(?:gaze|gazes|gazing|eyes|stares?|glances?|looking)\b[^.;!?]{0,70}\b(?:camera|viewer|smartphone|down|left|right)\b'),
      ('色彩与调色',r'\b(?:(?:color|colour|overall|warm|cool) palette|palette (?:is|of)|(?:blue|cool|warm|pastel) tones|overall tone|tones of)\b'),
      ('人工光与发光',r'\b(?:nightstand lamp glow|bioluminescent background|glow eyes|hanging lamps|streetlights|studio light|overhead fluorescent lights|chandelier)\b'),
      ('文字与图形',r'\b(?:motion lines|spoken question|star \(symbol\)|inscription)\b'),
      ('局部特写',r'\b(?:focus on (?:her |his )?hands and face|focuses tightly on her face)\b'),
      ('交通与机械',r'\bsled\b'),
      ('持物与道具互动',r'\b(?:holding|holds|cradles)\b[^.;!?]{0,60}\b(?:rope|bouquet|briefcase|maggots)\b'),
      ('植物与花园',r'\bfiddle-leaf fig\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    rejected=candidates(body,parents+result,refinements)
    return [p for p in result if p not in rejected]
