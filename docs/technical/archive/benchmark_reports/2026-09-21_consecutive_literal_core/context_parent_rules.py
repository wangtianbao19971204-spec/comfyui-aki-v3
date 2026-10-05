"""Recall literal tag evidence without guessing identities or inherited context."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('completion_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_context_completion/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL|{'身体部位','职业与身份','制服与职业装','头饰与发饰','动物与拟人','动物主体','手势与肢体动作','布局与画面结构','喜悦与微笑','头发与发型'}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent, pattern in [
      ('首饰与随身配饰',r'\benergy rings?\b'),
      ('非人特征',r'\b(?:fake animal ears|(?:rabbit|cat|fox) girl cosplay)\b'),
      ('植物与花园',r'\b(?:teacup|china cup) with\b'),
      ('植物与花园',r'\b(?:hair|ponytails?|braids?)\b[^.;!?]{0,45}\badorned with\b[^.;!?]{0,20}\bflowers?\b'),
      ('纯色与抽象背景',r'\b(?:kimono|dress|fabric|shirt):?\s*(?:a |the )?(?:black|white|red) background\b'),
      ('城市与街道',r'\bas if\b[^.;!?]{0,65}\bamusement park\b'),
      ('交通与机械',r'\bsubway tiles?\b'),
      ('食物与饮料',r'\bmeat written on\b|\bcherry (?:blossoms?|trees?)\b'),
      ('穿脱与整理',r'\bdressing (?:mirror|table)\b'),
    ]:
        if parent in parents and re.search(pattern,positive) and not refinements.extract_refinements(body,[parent]):
            result[parent]={'false_cues':re.findall(pattern,positive),'reason':'Context identifies a decoration, comparison, garment or material, not an independent subject.'}
    if '摄影与写实' in parents and re.search(r'\bchibi\b',positive) and set(refinements.extract_refinements(body,['摄影与写实']))=={'photo.cinematic'}:
        result['摄影与写实']={'false_cues':['cinematic with explicit chibi style'],'reason':'Cinematic mood alone does not establish photography or realism in an explicitly chibi image.'}
    if '纯色与抽象背景' in parents and 'dark forest floor' in positive and 'dark background' in positive and not re.search(r'\b(?:plain|simple|solid) (?:black )?background\b',positive):
        result['纯色与抽象背景']={'false_cues':['dark background with actual forest floor'],'reason':'The scene has a concrete environment rather than a plain backdrop.'}
    patterns={
      '首饰与随身配饰':r'\bhair ribbon\b|\b(?:drinking|water) glasses\b',
      '食物与饮料':r'\bchampagne gold\b|\btea sets?\b',
      '建筑与设施':r'\bschool (?:uniform|blazer)\b',
      '人工光与发光':r'\b(?:hair|skin)\b[^.!?]{0,85}\billuminated (?:under|in)\b[^.!?]*',
      '动物与拟人':r'\bfurry hemline\b',
      '拥抱与日常互动':r'\bfabric hugging (?:her|his|the)(?: soft)? curves\b',
      '服装材质与剪裁':r'\b(?:black |red )?velvet (?:booth|curtain)\b|\bchair draped with white fabric\b',
      '文字与图形':r'\bfreedom symbolism\b|\bcontent rating\b',
      '职业与身份':r'\blike a princess\b',
      '自然地貌与水域':r'\boutdoors?\b',
    }
    for parent,pattern in patterns.items():
        if parent not in parents:continue
        if parent=='人工光与发光' and refinements.extract_refinements(body,[parent]):continue
        if parent=='自然地貌与水域' and not re.search(r'\b(?:city|street|park|stage|indoors|indoor|kitchen|fishbowl|architectural setting)\b',positive):continue
        remaining=re.sub(pattern,' ',positive)
        if remaining==positive or refinements.extract_refinements(remaining,[parent]):continue
        # These parents include concepts without dedicated refinement nodes.
        supports={
          '首饰与随身配饰':r'\b(?:jewelry|jewellery|necklace|earrings?|bracelet|anklet|armlet|gloves?|belt|chain|choker|collar|scarf|bag|necktie|bowtie|eyepatch)\b',
          '建筑与设施':r'\b(?:building|architecture|door|window|railing|stairs|bridge|wall|pavilion|airport)\b',
          '自然地貌与水域':r'\b(?:landscape|nature|sea|ocean|river|lake|pool|poolside|mountain|hill|beach|desert|waterfall|valley|wasteland|grassland|meadow|field|snow-covered ground)\b',
          '服装材质与剪裁':r'\b(?:sleeves?|lace|silk|satin|knit|knitted|leather|frills?|frilled|pleated|mesh|sheer|transparent|see-through|cutout)\b',
        }
        if parent in supports and re.search(supports[parent],remaining):continue
        result[parent]={'false_cues':re.findall(pattern,positive),'reason':'The cue names an accessory location, material, comparison or scene metadata; independent parent evidence is absent.'}
    for parent, independent in [
      ('人工光与发光',r'\b(?:floor lamp|desk lamp|table lamp)\b'),
      ('首饰与随身配饰',r'\bgauntlets?\b'),
      ('穿脱与整理',r'\b(?:fixing|adjusting|combing|brushing) (?:her |his |the )?hair\b'),
      ('植物与花园',r'\b(?:berries|foliage|greenery|shrubs)\b'),
    ]:
        if parent in result and re.search(independent,positive):
            del result[parent]
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body);positive='; '.join(parts)
    # Exact standalone tags can recall any owner. Prose remains scoped to the
    # reviewed domains and context guards rather than unqualified keyword hits.
    exact={node for part in parts for node in refinements._EXACT.get(part,[])}
    possible={refinements.REFINEMENT_NODES[n]['parent'] for n in exact}|RECALL
    for node in refinements.extract_refinements(body,possible-set(parents)-set(result)):
        parent=refinements.REFINEMENT_NODES[node]['parent']
        if parent in RECALL or node in exact:
            if parent not in result:result.append(parent)
    for parent,pattern in [
      ('职业与身份',r'\b(?:virtual youtuber|executioner|female (?:flight attendant|nurse|singer))\b'),
      ('传统与民族服饰',r'\b(?:ancient egyptian clothes|egyptian clothes)\b'),
      ('制服与职业装',r'\b(?:nun robe|nun habit|nurse.s uniform|uniform jacket|nontraditional miko)\b'),
      ('身体部位',r'\bfingernails\b'),
      ('头饰与发饰',r'\b(?:kanzashi|earmuffs|hair ribbon|(?<!clitoral )hood|hair[^.!?;]{0,35}tied with a[^.!?;]{0,15}bow)\b'),
      ('首饰与随身配饰',r'\b(?:eyepatch|wrist cuffs|gold chain|anklet|armlet)\b'),
      ('穿着状态',r'\b(?:open (?:hanfu|collar)|drenched[^.;!?]{0,20}shirt|torn (?:thighhighs|sacrament robe)|clothes on floor|removed clothes)\b'),
      ('服装材质与剪裁',r'\b(?:raglan sleeves|juliet sleeves|knit sweater|knitted gloves|pleated camisole)\b'),
      ('人工光与发光',r'\b(?:glowing eyes|glow eyes|stage lights|led (?:strips|backdrop)|overhead (?:recessed|cool-white) light|ceiling lights|red light source)\b'),
      ('文字与图形',r'\b(?:fake screenshot|health bar|dialogue box|dated|brand logos?|lettering)\b'),
      ('站姿与跪姿',r'\bstanding (?:in|under)\b'),
      ('坐姿与蹲姿',r'\b(?:woman|nurse|figure)\b[^.;!?]{0,80}\bsits\b'),
      ('视线方向',r'\b(?:gazes?|gazing|eyes|looking|gaze)[^.;!?]{0,70}\b(?:lens|camera|viewer)\b'),
      ('手势与肢体动作',r'\b(?:hand on (?:hip|waist)|hand[^.;!?]{0,20}cupping[^.;!?]{0,15}cheek|arms outstretched|hands above your head|hands up|legs raised and crossed)\b'),
      ('布局与画面结构',r'\b(?:composition[^.;!?]{0,80}(?:center|left|right)|stands center stage|stands slightly left of center|diagonal line guides)\b'),
      ('家具与生活用品',r'\b(?:shoe cabinet|refrigerator|fishbowl|stethoscope|round-bottom flask)\b'),
      ('动物主体',r'\b(?:magpies|goldfish)\b'),
      ('动物与拟人',r'\bhorse (?:girl|boy)\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    rejected=candidates(body,parents+result,refinements)
    return [p for p in result if p not in rejected]
