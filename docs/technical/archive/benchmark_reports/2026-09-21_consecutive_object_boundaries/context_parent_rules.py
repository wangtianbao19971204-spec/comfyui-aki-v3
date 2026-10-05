"""Offline repair of referents and missing existing concepts; no new leaves."""
import importlib.util
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location('role_scene_parents', Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_role_scene/context_parent_rules.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
RECALL = previous.RECALL

FALSE_CUES = {
    '动物主体': r'\bdogs: bullets & carnage\b|\bhorse stance\b|\b(?:blue )?(?:bird|bunny|rabbit|butterfly|snake) (?:embroidery|tattoo)\b',
    '建筑与设施': r'\brune factory\b',
    '头饰与发饰': r'\bheadband\b(?=[^.!?;]{0,60}\bpanasonic\b)',
    '体型与肤色': r'\bslender (?:straps?|(?:double-ended )?toys?|fingers?)\b|\bfingers are long and slender\b',
    '移动与运动': r'\b(?:chain|train) running\b|\b(?:dust motes|plastic particle glitters) (?:float|floating)\b',
    '站姿与跪姿': r'\bstanding in for\b',
    '光影效果': r'\b(?:naturalistic|commanding) silhouette\b',
    '摄影与写实': r'\bmagical realism\b',
    '绘画与插画': r'\bdrawing the (?:main )?visual focus\b|\b(?:top of the|spatial depth of the) painting\b|\blike a flowing painting\b',
    '天空与天气': r'\bartificial snow\b|\b(?:glitter|sparkle|shimmer)[a-z]* like stars\b|\b(?:golden )?auspicious clouds\b|\bplastic solar system model\b|\bpainted moon surface\b',
    '非人特征': r'\bas translucent as cicada wings\b|\bcat-eared maid cosplayer\b|\blace cat ears\b|\bscales gem pasties\b',
    '植物与花园': r'\b(?:red |white )?(?:flowers?|rose|mushroom) hair(?:clip| ornaments?)\b|\bears adorned with (?:tiny white )?flowers\b|\bdress flower\b|\b(?:white lace )?flower pinned behind one ear\b|["“][^"”]*["”]\s+in white italic\b|\bhat adorned with blooming pink flowers and green leaves\b',
    '人工光与发光': r'\bglowing rim light\b',
    '食物与饮料': r'\bcoffee table\b|\btea (?:parlor|parlour)\b|\bteacup\b|\bas if drinking a hot drink\b',
    '服装材质与剪裁': r'\bleather (?:sofa|armchair)\b',
    '自然光': r'\blike moonlight\b',
    '视角与透视': r'\blow-angle dawn light\b|\bnatural light enters from an upward angle\b',
    '职业与身份': r'\bqueen of spades\b|\bprostitute red lipstick\b|\bknight helmet\b',
    '持物与道具互动': r'\bas if holding (?:an? |the )?(?:device|book|object)\b|\bas if drinking a hot drink\b',
    '平静与冷淡': r'\b(?:overall )?atmosphere is calm\b',
    '城市与街道': r'\bmodern urban touch\b|\b(?:romantic moments on the )?edge of the city\b',
    '家具与生活用品': r'\b(?:snapshot from a phone or compact camera|shot with professional photography equipment|shot by a professional camera|with an old digital camera or phone)\b|\bdelicate chain running\b',
    '交通与机械': r'\b(?:portable camera|vintage camera|rangefinder camera|silver camera|using camera|holding camera|photography equipment)\b',
    '性交与体位': r'\bas if inviting the viewer to have sex\b',
}


def cleaned_evidence(positive, parent):
    if parent == '植物与花园':
        positive = re.sub(r'\bhat flowers\b', ' ', positive)
    if parent == '服装材质与剪裁' and re.search(r'\bchair has rivet detailing\b', positive):
        positive = re.sub(r'\bvisible leather creases\b', ' ', positive)
    pattern = FALSE_CUES.get(parent)
    if not pattern:
        return positive
    return re.sub(pattern, ' ', positive)


def independent_parent(remaining, parent):
    # These legitimate parent concepts need not have a dedicated leaf.
    patterns = {
        '城市与街道': r'\bcity buildings\b',
        '职业与身份': r'\bclown\b',
        '人工光与发光': r'\bwindows? (?:some )?with (?:faint |warm |interior )?light\b',
    }
    return bool(parent in patterns and re.search(patterns[parent], remaining))


def candidates(body, parents, refinements):
    result = previous.candidates(body, parents, refinements)
    positive = '; '.join(refinements._positive_parts(body))
    for parent in parents:
        remaining = cleaned_evidence(positive, parent)
        if parent == '自然地貌与水域' and re.search(r'\b(?:crosswalk|outdoor stadium|indoor ice rink)\b', positive):
            remaining = re.sub(r'\b(?:outdoors?|ice rink|ice)\b', ' ', remaining)
        if remaining == positive:
            continue
        supported = (independent_parent(remaining, parent)
                     or refinements.extract_refinements(remaining, [parent])
                     or parent in previous.additions(remaining, [p for p in parents if p != parent], refinements))
        if supported:
            result.pop(parent, None)
        else:
            result[parent] = {'reason': 'The cue describes a title, attached object, local property or comparison; no independent parent evidence remains.'}
    return result


def additions(body, parents, refinements):
    result = previous.additions(body, parents, refinements)
    parts = []
    for part in refinements._positive_parts(body):
        if ('(' in part or ')' in part) and part not in refinements._EXACT and not re.fullmatch(r'(?:digimon\s*\(creature|youkai\s*\(youkai watch)\)?', part):
            outside = re.sub(r'\([^()]*\)?', ' ', part)
            if len(outside.split()) >= 5 and re.search(r'\b(?:wears|wearing|she|he|her|his|head tilted)\b', outside):
                part = outside
            else:
                continue
        parts.append(part)
    positive = '; '.join(parts)
    for parent, pattern in [
        ('家具与生活用品', r'\b(?:headset|earphone cable|nintendo switch|cauldron|cooking pot|cash register|display cabinets?|barstool|mailbox|bookshelves|large screen)\b'),
        ('天空与天气', r'\b(?:twilight|midnight)\b'),
        ('色彩与调色', r'\b(?:color palette|warm tones|cool color tones|cool-warm contrast|cold.warm contrast|film grain|fine grain|blue theme)\b|(?:^|[;.!?]\s*)colors (?:are|center|dominated)\b'),
        ('焦点与景深', r'\b(?:soft-focus|soft-focused|blurred garden|blurred traditional architecture|blurred cluster of buildings|background softly blurred)\b'),
        ('人工光与发光', r'\b(?:camera flash|arena lights|paper lanterns|warm amber lights|lighting fixtures)\b'),
        ('手势与肢体动作', r'\b(?:hands in opposite sleeves|head slightly tilted|tilting her head|head tilted up|one raised hand|legs bent together|extend your right arm)\b'),
        ('服装材质与剪裁', r'\b(?:wide sleeves|deep v-neck|fur-trimmed dress|thick knit shawl|strapless dress)\b'),
        ('上衣与外套', r'\btabard\b'),
        ('武器与装备', r'\b(?:holster|longsword)\b'),
        ('首饰与随身配饰', r'\bsuspenders\b|\bchain running from her wrist to her hip\b'),
        ('艺术流派与视觉风格', r'\b(?:retro-futuristic atmosphere|biopunk)\b'),
        ('建筑与设施', r'\b(?:traditional architecture|goalpost|utility poles|traditional korean house|hanok|ancient architecture|high-rises)\b'),
        ('布局与画面结构', r'\b(?:vertical composition|positioned slightly to the left|composition is centered|composition centers|figure positioned slightly|centrally positioned)\b'),
        ('摄影与写实', r'\b(?:movie tonal|retro film texture|analog film texture|filmic texture|editorial shot|professional studio fashion shoot|filmic|polaroid tone|amateur photography|camera settings)\b'),
        ('坐姿与蹲姿', r'\b(?:woman sits|sits on a|cosplayer crouches)\b'),
        ('持物与道具互动', r'\b(?:hand grips an ancient longsword|holds a pair of|she cradles|she reads an open book|hand on doorknob)\b'),
        ('泳装与内衣', r'\bfundoshi\b'),
        ('穿着状态', r'\b(?:clothed female|clothes tug|bikini pull|garment is loosely fastened|robe[^.;!?]{0,75}partially open)\b'),
        ('头饰与发饰', r'\b(?:headgear|flower hair ornaments|lace bow|silver hairpins)\b'),
        ('传统与民族服饰', r'\bchinese traditional outfit\b'),
        ('穿脱与整理', r'\b(?:hand gently brushing through her hair|hand tugging the robe)\b'),
        ('卧姿与趴姿', r'\bwoman elegantly reclines\b'),
        ('奇幻与角色服饰', r'\b(?:maid cosplayer|witch clothes|translucent bunnysuit)\b'),
        ('幻想与科幻环境', r'\b(?:backrooms|cosmic landscape|acts as a portal)\b'),
        ('种族与幻想生物', r'\brobot girl\b|\byoukai\s*\(youkai watch\)?|\bhuge robot\b'),
        ('自然光', r'\b(?:dawn light|natural daylight|sunlight|sunbeams)\b'),
        ('身体部位', r'(?:^|;\s*)(?:large )?pectorals(?:;|$)'),
        ('漫画与线稿', r'\b(?:linear hatching|thick outlines|messy draft|messy lines)\b'),
        ('制服与职业装', r'\bwrestling outfit\b'),
        ('交通与机械', r'\b(?:drone|huge robot)\b'),
        ('室内空间', r'\b(?:indoor bookshelf|victorian study|white tiled corridor)\b'),
        ('景别与主体占比', r'\b(?:middle shot|medium shot|mid-shot|medium to near shot|capturing her full figure|close-ups)\b'),
        ('植物与花园', r'\b(?:climbing vines|sparse leaves|plum branches|tropical rainforest)\b'),
        ('自然地貌与水域', r'\b(?:green grassland|green hills|tropical rainforest)\b'),
        ('文字与图形', r'\b(?:tv signage|advertisements visible|mining rusted sign)\b'),
        ('体型与肤色', r'\b(?:skin pale|skin is pale)\b'),
        ('拥抱与日常互动', r'\b(?:tender embrace|cradled securely in her arms)\b'),
        ('亲密互动', r'\bkiss on (?:the |her |his |girl.s )?forehead\b'),
        ('平静与冷淡', r'\b(?:appears serene|dazed empty expression)\b'),
        ('眼口表情', r'\b(?:lips slightly parted|parted pink lips)\b'),
        ('悲伤与哭泣', r'\bexpression is melancholic\b'),
    ]:
        evidence = positive
        if parent == '天空与天气':
            evidence = re.sub(r'\btwilight (?:blue|purple|color|colou?r palette)\b', ' ', evidence)
        elif parent == '交通与机械':
            evidence = re.sub(r'\bdrone (?:photography|shot|footage|view)\b', ' ', evidence)
        elif parent == '自然地貌与水域' and re.search(r'\b(?:theme park|themed amusement park|super mario world)\b', evidence):
            evidence = re.sub(r'\bgreen hills\b', ' ', evidence)
        if parent not in parents and parent not in result and re.search(pattern, evidence):
            result.append(parent)
    rejected = candidates(body, parents + result, refinements)
    return [parent for parent in result if parent not in rejected]
