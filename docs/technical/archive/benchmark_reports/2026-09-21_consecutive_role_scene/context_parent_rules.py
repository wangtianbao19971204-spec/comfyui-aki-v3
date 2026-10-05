"""Keep named roles and depicted settings distinct; recall explicit prose evidence."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('prose_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_prose_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
RECALL=previous.RECALL

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent,pattern,support in [
      ('职业与身份',r'\bfuture princess\b',r'\b(?:occupation|nurse|teacher|warrior|knight|soldier|queen|king|princess|virtual youtuber)\b'),
      ('自然地貌与水域',r'\bfan with ink-wash landscape painting\b',r'\b(?:sea|river|lake|mountain|forest|pool|waterfall|beach)\b'),
      ('绘画与插画',r'\bfan with ink-wash landscape painting\b',r'\b(?:illustration|painting|painted|digital art)\b'),
      ('艺术流派与视觉风格',r'\bsticker style\b|\bstreet photography style\b',r'\b(?:aesthetic|gothic|retro|vintage|surrealism|fantasy|art nouveau|art deco)\b'),
    ]:
        if parent not in parents:continue
        remaining=re.sub(pattern,' ',positive)
        if remaining!=positive and not refinements.extract_refinements(body,[parent]) and not re.search(support,remaining):
            result[parent]={'false_cues':re.findall(pattern,positive),'reason':'A title, depicted picture or different style axis is not evidence for this parent.'}
    if '城市与街道' in result and re.search(r'\bnight market\b',refinements._scene_text(positive)):
        result.pop('城市与街道')
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=[]
    for part in refinements._positive_parts(body):
        if part == 'sentimental graffiti':
            continue
        if re.fullmatch(r'(?:visor|helmet|gauntlets?)\s*\(armor\)?',part):
            part='armor'
        if ('(' in part or ')' in part) and part not in refinements._EXACT and not re.fullmatch(r'digimon\s*\(creature\)?',part):
            outside=re.sub(r'\([^()]*\)?',' ',part)
            if len(outside.split()) >= 5 and re.search(r'\b(?:wears|wearing|she|he|her|his|head tilted)\b',outside):
                part=outside
            else:
                continue
        parts.append(part)
    positive='; '.join(parts)
    for parent,pattern in [
      ('焦点与景深',r'\b(?:blurry background|blurred (?:background|cityscape|city lights)|background (?:is |slightly |softly |elements are )?blurred|soft city blur)\b'),
      ('人工光与发光',r'\b(?:stage lighting|studio lights?|studio lighting|photography light stand|softboxes|flash or fill light|warm yellow lamplight|city lights)\b'),
      ('建筑与设施',r'\b(?:jail|stained glass|city buildings|stone buildings|glass window|brick wall|road guardrail|relay station|swimming pool)\b'),
      ('像素与平面设计',r'\bsticker style\b|(?:^|;\s*)flat color(?:;|$)'),
      ('布局与画面结构',r'\b(?:comic frame border|central composition|symmetrical composition|centered slightly|slightly left of center)\b'),
      ('文字与图形',r'\b(?:exclamation mark|graffiti)\b'),
      ('惊讶与紧张',r'\b(?:nervous smile|comedic stress)\b'),
      ('射精与体液',r'\b(?:sweating|cum-like fluid)\b'),
      ('摄影与写实',r'\b(?:old movie(?!\s+poster\b)|film camera|phone-captured|real photos|photographic grain|double exposure)\b'),
      ('艺术流派与视觉风格',r'\bdark fantasy\b'),
      ('种族与幻想生物',r'\bgiantess\b|\bdigimon\s*\(creature\)?'),
      ('武器与装备',r'\barmor\b'),
      ('家具与生活用品',r'\b(?:baseball (?:mitt|bat|glove)|red velvet seat|newsstand counter)\b|(?:^|;\s*)baseball(?:;|$)'),
      ('平静与冷淡',r'\bthoughtful expression\b'),
      ('持物与道具互动',r'\b(?:flipping through a magazine|grips a glossy black clutch)\b'),
      ('手势与肢体动作',r'\b(?:trembling hand|leans slightly forward|head tilted|toys with a strand of hair|gentle wave|hands (?:lightly clasped|folded))\b'),
      ('漫画与线稿',r'\b(?:intricate linework|adult-oriented doujinshi)\b'),
      ('自然光',r'\bmoonlit\b'),
      ('体型与肤色',r'\b(?:fair and flawless skin|skin is fair|sun-kissed skin)\b'),
      ('眼口表情',r'\b(?:lips are parted|lips parted slightly)\b'),
      ('首饰与随身配饰',r'\b(?:smartband|black clutch)\b'),
      ('服装材质与剪裁',r'\b(?:sleeveless dress|corduroy shorts|wide-sleeved hanfu)\b'),
      ('质量与分辨率',r'\bhigh-resolution\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    rejected=candidates(body,parents+result,refinements)
    result=[p for p in result if p not in rejected]
    # Re-evaluate only a domain with an explicit false cue removed. This keeps
    # independent evidence elsewhere in the same prompt eligible for recall.
    for parent,pattern in [
        ('动漫与卡通',r'\bbackground wall features\b[^.!?;]*'),
        ('非人特征',r'\b(?:hoodie|hood|hat|headband)\s+with\s+(?:[a-z-]+\s+){0,3}(?:cat|rabbit|animal|fox|dog|bunny)\s+ears\b'),
        ('动物与拟人',r'\bfaux fur\b|\bfurry scarf\b'),
        ('动物主体',r'\brock bison\b|\btiger & bunny\b'),
        ('惊讶与紧张',r'\bfear & hunger\b'),
        ('天空与天气',r'\brainbow\s+(?:accents|gradients|hair)\b'),
        ('绘画与插画',r'\b(?:in|of) the painting\b|\bas if drawn to something\b'),
        ('持物与道具互动',r'\bcarrying both\b[^.;!?]*'),
        ('植物与花园',r'\b(?:text|italic|lettering|caption)\s+(?:reads?\s+)?["“][^"”]*["”]|\bbamboo scroll\b|\b(?:embroidered|embossed)\s+(?:flowers|blooms)\b|\brose[- ]gold\b'),
    ]:
        if parent not in result:continue
        cleaned=re.sub(pattern,' ',positive)
        if cleaned!=positive and not refinements.extract_refinements(cleaned,[parent]) and parent not in previous.additions(cleaned,[p for p in parents if p!=parent],refinements):
            result.remove(parent)
    return result
