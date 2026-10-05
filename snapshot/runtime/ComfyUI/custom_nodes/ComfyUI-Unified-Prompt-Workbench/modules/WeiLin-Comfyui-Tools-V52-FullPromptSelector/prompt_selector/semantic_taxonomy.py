"""Shared semantic owners for the library's topic and subcategory filters."""
import re

CLASS_LABELS = {
    'identity': '角色与身份', 'person_count': '人物数量', 'appearance': '外观与身体',
    'clothing_accessory': '服装与配饰', 'pose_action': '动作与姿势',
    'expression_gaze': '表情与视线', 'background_environment': '背景与环境',
    'composition_camera': '构图与镜头', 'lighting_color': '光影与色彩',
    'style_medium': '风格与媒介', 'artist_style': '画师与作者',
    'quality_detail': '质量与细节', 'object_prop': '物品与道具',
    'task_template': '综合场景', 'negative_exclusion': '负向与排除',
}

FACET_CLASS_MAP = {
    'character': 'identity', 'count': 'person_count', 'appearance': 'appearance',
    'clothing': 'clothing_accessory', 'pose': 'pose_action', 'expression': 'expression_gaze',
    'background': 'background_environment', 'composition': 'composition_camera',
    'lighting': 'lighting_color', 'style': 'style_medium', 'artist': 'artist_style',
    'quality': 'quality_detail', 'object': 'object_prop', 'negative': 'negative_exclusion',
    'task_template': 'task_template',
}

SUBCATEGORY_GROUPS = {
    'identity': ['作品角色', '原创人物', '职业与身份', '种族与幻想生物', '动物与拟人', '性别表现'],
    'appearance': ['头发与发型', '眼睛与瞳色', '面部特征', '体型与肤色', '身体部位', '身体改造与伤痕', '非人特征', '裸露与遮盖'],
    'clothing_accessory': ['裙装与礼服', '上衣与外套', '裤装', '制服与职业装', '传统与民族服饰',
        '泳装与内衣', '奇幻与角色服饰', '鞋袜与腿饰', '头饰与发饰', '首饰与随身配饰', '服装材质与剪裁', '穿着状态'],
    'pose_action': ['坐姿与蹲姿', '站姿与跪姿', '卧姿与趴姿', '移动与运动', '手势与肢体动作',
        '持物与道具互动', '拥抱与日常互动', '穿脱与整理', '战斗与施法', '亲密互动',
        '自慰', '口部互动', '手足互动', '性交与体位', '射精与体液', '束缚与控制', '暴力与伤害'],
    'expression_gaze': ['视线方向', '喜悦与微笑', '悲伤与哭泣', '愤怒与不满', '惊讶与紧张', '平静与冷淡', '眼口表情'],
    'background_environment': ['自然地貌与水域', '植物与花园', '天空与天气', '城市与街道', '建筑与设施',
        '室内空间', '幻想与科幻环境', '纯色与抽象背景'],
    'composition_camera': ['视角与透视', '景别与主体占比', '局部特写', '焦点与景深', '布局与画面结构', '多格与连续画面', '文字与图形'],
    'lighting_color': ['自然光', '人工光与发光', '光影效果', '色彩与调色'],
    'style_medium': ['摄影与写实', '动漫与卡通', '漫画与线稿', '绘画与插画', '水彩与油画',
        '三维与数字渲染', '像素与平面设计', '艺术流派与视觉风格'],
    'artist_style': ['画师标签', '画师组合'],
    'quality_detail': ['质量与分辨率', '细节与材质'],
    'object_prop': ['武器与装备', '交通与机械', '家具与生活用品', '食物与饮料', '动物主体', '成人道具'],
    'task_template': ['人物综合场景', '环境综合场景', '叙事与情境', '连续场景'],
    'negative_exclusion': ['质量排除', '内容排除'],
    'person_count': [],
}

SUBCATEGORY_PARENTS = {label: owner for owner, labels in SUBCATEGORY_GROUPS.items() for label in labels}


def subcategory_owner(decision, label):
    canonical = SUBCATEGORY_PARENTS.get(label) or SUBCATEGORY_PARENTS.get(label.split('/', 1)[0])
    if canonical:
        return canonical
    owner = (decision.get('subcategory_owners') or {}).get(label)
    return owner if owner in CLASS_LABELS else None


def semantic_themes(decision):
    result = {decision.get('primary_class'), *(decision.get('alternative_classes') or [])}
    result.update(FACET_CLASS_MAP.get(value, value) for value in decision.get('themes') or [])
    result.update(subcategory_owner(decision, value) for value in decision.get('subcategories') or [])
    if decision.get('count_markers'):
        result.add('person_count')
    return result.intersection(CLASS_LABELS)


def semantic_subcategories(decision, prompt=None):
    return list(dict.fromkeys(decision.get('subcategories') or []))


def strip_nonpositive_nai_weights(body):
    markers = re.compile(r'(?<![\d.])(?P<weight>[-+]?\d+(?:\.\d+)?)\s*::|::')
    result = []
    cursor = 0
    suppress = False
    for match in markers.finditer(body):
        if not suppress:
            result.append(body[cursor:match.start()])
        if match.group('weight') is not None:
            if float(match.group('weight')) <= 0:
                suppress = True
            elif not suppress:
                result.append(match.group())
        elif suppress:
            suppress = False
        else:
            result.append(match.group())
        cursor = match.end()
    if not suppress:
        result.append(body[cursor:])
    return ''.join(result)


def original_count_markers(body):
    text = str(body or '').lower().replace('\n', ',')
    text = re.sub(r'\s+', ' ', text.replace('\\', ''))
    text = strip_nonpositive_nai_weights(text)
    text = re.sub(r'\([^()]*(?::\s*(?:-\d+(?:\.\d+)?|0(?:\.0+)?)\s*)\)', '', text)
    text = re.split(r'原版负面|负面提示词\s*[:：]|negative[ _]prompt\s*:', text, maxsplit=1)[0]
    result = []
    for value in re.split(r'[,，]|(?<!\d)::', text):
        value = re.sub(r'^\s*(?:\+?\d+(?:\.\d+)?\s*::|char\d+\s*[:：]|(?:source|target|mutual)#|(?:right|left) girl:)', '', value)
        value = value.strip(' {}[]()【】（）\t')
        if re.search(r':\s*(?:-\d+(?:\.\d+)?|0(?:\.0+)?)$', value):
            continue
        value = re.sub(r':\s*\+?\d+(?:\.\d+)?$', '', value).rstrip()
        candidates = [value.replace('_', ' ')]
        # An exported space-separated tag list retains underscores within tags.
        if len(re.findall(r'\b[a-z]+_[a-z_]+\b', value)) >= 2 and not re.search(r'\b(?:no|not|without|never)\b', value):
            candidates.extend(word.strip('{}[]()').replace('_', ' ') for word in value.split())
        for candidate in candidates:
            if re.fullmatch(r'[1-9][0-9]*(?:girls?|boys?|others?)|multiple (?:girls|boys|others)|solo|no humans|duo|group', candidate) and candidate not in result:
                result.append(candidate)
    return result
