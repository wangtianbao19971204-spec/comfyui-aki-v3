"""Recall reviewed prose domains using context-checked nodes, not raw keywords."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('relation_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_relation_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL|{'体型与肤色','光影效果','卧姿与趴姿','天空与天气','平静与冷淡','悲伤与哭泣','惊讶与紧张','愤怒与不满','性别表现','持物与道具互动','摄影与写实','穿脱与整理','射精与体液','手足互动','成人道具'}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern,support in [
      ('动物与拟人',r'\b(?:fake (?:animal|rabbit|cat|fox) ears|playboy bunny)\b',r'\b(?:furry|anthro|animal (?:girl|boy)|cat girl|dog girl|horse girl)\b'),
      ('非人特征',r'\bfake (?:(?:animal|rabbit|cat|fox) )?(?:ears|tail)\b',r'\b(?:horns?|wings?|fangs?|claws?|pointy ears|tentacles?)\b'),
      ('动物主体',r'\b(?:butterfly|bird|cat|dog|fish|rabbit|snake) hair ornaments?\b',r'\b(?:animals?|birds?|horses?|dogs?|cats?|insects?|doberman|dolphin)\b'),
      ('食物与饮料',r'\bchampagne\s+(?:folded[- ]|leather |colored |metallic |satin ){0,4}(?:bag|handbag)\b',r'\b(?:food|drinks?|beverages?|eating|drinking|fruit|desserts?|meals?)\b'),
      ('植物与花园',r'\bbamboo sticks?\b|\bflower knight girl\b',r'\b(?:plants?|foliage|greenery|herbs|trees?|garden|forest|blossoms?|leaves)\b'),
      ('职业与身份',r'\bflower knight girl\b',r'\b(?:occupation|nurse|teacher|warrior|knight|soldier|queen|king|princess|virtual youtuber)\b'),
      ('城市与街道',r'\bbowling alley\b|\bstreet fashion(?: style)?\b',r'\b(?:cityscape|skyline|city street|sidewalk|urban (?:street|setting|environment))\b'),
      ('体型与肤色',r'\b(?:skin detail|realistic skin|smooth skin details)\b',r'\b(?:medium breasts|average breasts|skin tone|complexion|physique|body type|curves)\b'),
      ('家具与生活用品',r'\bdslr style\b',r'\b(?:furniture|chair|table|desk|bed|sofa|shelf|cabinet|phone)\b'),
    ]:
        if parent not in parents:continue
        remaining=re.sub(pattern,' ',positive)
        if remaining!=positive and not refinements.extract_refinements(body,[parent]) and not re.search(support,remaining):
            result[parent]={'false_cues':re.findall(pattern,positive),'reason':'The text names a costume, material, container, title or rendering detail rather than this subject.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for node in refinements.extract_refinements(body,RECALL-set(parents)-set(result)):
        parent=refinements.REFINEMENT_NODES[node]['parent']
        if parent not in result:result.append(parent)
    for parent,pattern in [
      ('头饰与发饰',r'\b(?:scrunchie|beanie|fake (?:animal|rabbit|cat|fox) ears ornament)\b'),
      ('面部特征',r'\b(?:v-shaped eyebrows|dot nose)\b'),
      ('职业与身份',r'\bcheerleader\b'),
      ('制服与职业装',r'\b(?:cheerleader uniform|cheerleader outfit)\b'),
      ('拥抱与日常互动',r'\b(?:cuddling|leaning on (?:his|her) shoulder|holding (?:her|his) (?:left |right )?hand|holding pov hand)\b'),
      ('服装材质与剪裁',r'\b(?:long-sleeved shirt|(?:sheer|translucent) (?:black |white )?(?:pantyhose|stockings)|knit dress|knitted beanie|fur.trimmed (?:coat|jacket))\b'),
      ('色彩与调色',r'\bcolor contrast\b'),
      ('奇幻与角色服饰',r'\bharem outfit\b'),
      ('卧姿与趴姿',r'\b(?:reclines sideways|lounges on (?:a |the )?(?:[a-z-]+\s+){0,3}bed)\b'),
      ('人工光与发光',r'\b(?:fire glow|warm lamp light|artificial light|indoor lights?|desk lamp|globe lamp)\b'),
      ('自然光',r'\b(?:blue hour|natural light(?!\s+(?:pink|blue|green|brown|red|colou?r|transitions?)\b)|light enters[^.;!?]{0,50}window)\b'),
      ('穿脱与整理',r'\b(?:pulling down own clothes|tugging at the hem of her skirt)\b'),
      ('手势与肢体动作',r'\b(?:head tilted gently|placing her head on the table|leans forward|left leg lifted|hand resting behind her back)\b'),
      ('持物与道具互动',r'\b(?:broom riding|(?:(?:she|he|hand|hands)\s+|(?:her|his|their)\s+(?:left |right )?hand\s+)(?:lightly |casually )?holds?\b[^.;!?]{0,55}\b(?:flute|cup|ball|bag|bamboo stick|pack)|holding a red bowling ball)\b'),
      ('穿着状态',r'\b(?:open dress|revealing clothes|sleeves rolled|coat hangs open|sweater draped)\b'),
      ('传统与民族服饰',r'\b(?:xiuhe jacket|xiapei bridal cape)\b'),
      ('武器与装备',r'\bbandolier\b'),
      ('眼睛与瞳色',r'\bgradient eyes\b'),
      ('多格与连续画面',r'\bsplit view\b|\bkoma separated\b'),
      ('束缚与控制',r'\bstuck (?:in (?:the )?)?wall\b'),
      ('室内空间',r'\b(?:convenience store(?!\s+entrance\b)|bowling alley)\b'),
      ('家具与生活用品',r'\b(?:refrigerated food aisle|chilled shelving)\b'),
      ('文字与图形',r'\b(?:labels and prices|pack[^.;!?]{0,50}labels)\b'),
      ('上衣与外套',r'\b(?:open top|black top(?!\s+hat\b)|red shrug)\b'),
      ('摄影与写实',r'\b(?:selfie|photoshoot|photorealistic anatomy)\b'),
      ('裸露与遮盖',r'\b(?:nipples visible|bare torso|lower back visible|exposing her chest|fully exposed|bare chest)\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    rejected=candidates(body,parents+result,refinements)
    return [p for p in result if p not in rejected]
