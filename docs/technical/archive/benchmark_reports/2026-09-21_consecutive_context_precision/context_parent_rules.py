"""Offline corrections for object modifiers and explicit scene evidence."""
import importlib.util
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('camera_parents',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_camera_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
SUPPORT={**previous.SUPPORT,
 '体型与肤色':r'\b(?:skin|body|figure|physique|build|plump|chubby|curvy|slim|slender|muscular|fat|petite|tall|short stature)\b|肤色|体型',
}
BAD={
 '上衣与外套':[r'\b(?:long )?waist cape\b'],
 '头发与发型':[r'\bhair cotton candy\b'],
 '视角与透视':[r'\bmid-field perspective\b',r'\b(?:reach(?:es|ing)? out|grabbing) from behind\b'],
 '持物与道具互动':[r'\bholding up (?:one|two|three|four|five|\d+) fingers\b',r"\bholding another's leg\b"],
 '天空与天气':[r'\b(?:crescent )?moon pendant\b'],
 '体型与肤色':[r'\bplump[, ]+(?:moist )?leaves\b'],
 '种族与幻想生物':[r'\bfairy of the holy flame\b'],
}

def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive='; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining=positive;cues=[]
        for pattern in BAD.get(parent,[]):
            cues.extend(m.group() for m in re.finditer(pattern,remaining));remaining=re.sub(pattern,' ',remaining)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Modifier, body gesture or title; no independent parent evidence.'}
    return result

def additions(body,parents,refinements):
    result=previous.additions(body,parents,refinements)
    parts=refinements._positive_parts(body)
    positive='; '.join(parts)
    positive=re.sub(r'\b(?:no|not|without|never|excluding)\s+[^;.!?]+','',positive)
    for parent,pattern in [
        ('作品角色',r'\b(?:jeff the killer|spider-man noir)\b'),
        ('水彩与油画',r'\boil[- ]painting\b'),
        ('绘画与插画',r'\b(?:painting style|animated-illustration|painterly animation)\b'),
        ('动漫与卡通',r'\b(?:animated-illustration|painterly animation)\b'),
        ('上衣与外套',r'\b(?:black turtleneck(?!\s+dress\b)|puff-sleeve top)\b'),
        ('室内空间',r'\bindoor (?:[a-z-]+ ){0,2}room scenes?\b'),
        ('坐姿与蹲姿',r'\b(?:sit on (?:a |the )?(?:[a-z-]+ ){0,2}countertop|squatting on (?:a |the )?swing)\b'),
        ('制服与职业装',r'\bflight attendant-style uniform\b'),
        ('种族与幻想生物',r'\b(?:biomechanical (?:[a-z-]+ ){0,2}monstrosities|duel monster)\b'),
        ('动物与拟人',r'\b(?:furry female|furry male|bird girl)\b'),
        ('家具与生活用品',r'\b(?:television|microphone stand)\b'),
        ('鞋袜与腿饰',r'\b(?:fishnet tights|cow print thighhighs)\b'),
        ('头饰与发饰',r'\b(?:fedora|diadem|pearl pins|bow clips)\b'),
        ('头发与发型',r'\bgolden short hair\b'),
        ('体型与肤色',r'\bpale porcelain skin\b'),
        ('纯色与抽象背景',r'\bbackground is (?:stark|pure) white\b'),
        ('视角与透视',r'\b(?:three quarter view|low-angle (?:shot|downward view))\b'),
        ('天空与天气',r'\b(?:night scenes?|outdoor night scenes?)\b'),
        ('植物与花园',r'\b(?:bouquet of (?:red )?roses|vase with withered branches|background is dark shrubs)\b'),
        ('手势与肢体动作',r'\b(?:holding up three fingers|v-shaped gesture)\b'),
        ('交通与机械',r'\bsedan is parked\b'),
        ('站姿与跪姿',r'\b(?:stands in a sideways pose|body stands upright)\b'),
    ]:
        if parent not in parents and parent not in result and re.search(pattern,positive):result.append(parent)
    if '动物主体' not in parents and '动物主体' not in result and 'no humans' in parts and 'monkey' in parts:result.append('动物主体')
    if '持物与道具互动' not in parents and '持物与道具互动' not in result:
        if 'sketching' in parts and 'drawing board' in parts and 'pencil' in parts:result.append('持物与道具互动')
        else:
            for part in parts:
                for m in re.finditer(r'\b(?:holds?|holding|grips?|gripping)\s+(?:[a-z-]+\s+){0,7}(?:sword|guitar|cup)\b',part):
                    before=part[:m.start()]
                    if re.search(r'(?:^|[.!?])\s*$',before) or re.search(r'\b(?:she|he|woman|man|figure|hands?|fingers?)\b[^.;!?]{0,70}$',before):
                        result.append('持物与道具互动');break
                if '持物与道具互动' in result:break
    rejected=candidates(body,parents+result,refinements)
    return [parent for parent in result if parent not in rejected]
