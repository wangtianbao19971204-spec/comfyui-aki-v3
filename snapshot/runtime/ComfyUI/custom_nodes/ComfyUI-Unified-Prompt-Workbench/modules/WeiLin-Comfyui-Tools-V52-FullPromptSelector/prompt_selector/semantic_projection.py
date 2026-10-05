"""Read-only eligibility overlay; source data remains the editing authority."""
import hashlib
import json
import copy
import re
from collections import Counter
from .semantic_taxonomy import CLASS_LABELS, SUBCATEGORY_PARENTS, semantic_themes, original_count_markers


def binding(category, prompt):
    personal = {'is_user_plan', 'favorite', 'usage_count', 'last_used', 'created_at', 'updated_at', 'image', '_classification', '_selector_favorites', '_collection'}
    value = [{k: v for k, v in category.items() if k != 'prompts' and k not in personal},
        {k: v for k, v in prompt.items() if k not in personal}]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def read_projection(path):
    with open(path, encoding='utf-8') as stream:
        document = json.load(stream)
    if document.get('schema') != 'S4-semantic-projection-v1' or not isinstance(document.get('decisions'), dict):
        raise ValueError('Invalid semantic projection; rebuild candidate review metadata')
    return document


def decision_for(document, category, prompt):
    explicit = prompt.get('_classification')
    current_binding = binding(category, prompt)
    decision = explicit if isinstance(explicit, dict) and explicit.get('binding') == current_binding else document['decisions'].get(prompt['id'])
    if decision is None or decision.get('binding') != current_binding:
        quarantined = isinstance(prompt.get('_import_quarantine'), dict)
        return {'disposition': 'quarantined' if quarantined else 'pending',
            'reason': 'import_record_needs_repair' if quarantined else 'source_changed_or_unreviewed',
            'manual_search_eligible': False, 'random_pool_eligible': False,
            'strict_model_pool_eligible': False, 'usage': 'unknown', 'model_scope': 'unknown',
            'content_type': None, 'primary_class': None}
    if decision.get('disposition') not in ('pending', 'quarantined', 'reviewed', 'classified'):
        raise ValueError('Invalid review disposition')
    for key in ('manual_search_eligible', 'random_pool_eligible', 'strict_model_pool_eligible'):
        if type(decision.get(key)) is not bool:
            raise ValueError('Invalid review eligibility')
    if decision['disposition'] not in ('reviewed', 'classified') and any(decision[k] for k in
            ('manual_search_eligible', 'random_pool_eligible', 'strict_model_pool_eligible')):
        raise ValueError('Non-reviewed record cannot enter selection')
    return decision


def rebind_unchanged_prompt(document, old_category, old_prompt, category, prompt):
    """Keep a valid review when only its owning category context changes."""
    if binding(old_category, old_prompt) != binding(old_category, prompt):
        return
    if binding(old_category, old_prompt) == binding(category, prompt):
        return
    decision = decision_for(document, old_category, old_prompt)
    if decision.get('binding') == binding(old_category, old_prompt):
        prompt['_classification'] = {**copy.deepcopy(decision), 'binding': binding(category, prompt)}


def confirm_classification(document, category, prompt, selected, *, previous_category=None, previous_prompt=None):
    """Store an explicit editor choice with the same atomic source revision."""
    if not isinstance(prompt.get('prompt'), str) or not prompt['prompt'].strip():
        raise ValueError('请填写有效正文后再确认分类')
    classes = set(document.get('class_labels', {})) | set(CLASS_ROUTES) | set(CLASS_LABELS)
    if not isinstance(selected, dict) or selected.get('primary_class') not in classes:
        raise ValueError('请选择内容分类')
    if selected.get('content_type') not in ('atomic_tag', 'fragment', 'template', 'model_reference'):
        raise ValueError('请选择内容形式')
    if selected.get('usage') not in ('positive', 'negative', 'mixed', 'unknown'):
        raise ValueError('请选择正负向用途')
    result = {'binding': binding(category, prompt), 'disposition': 'classified',
        'primary_class': selected['primary_class'], 'content_type': selected['content_type'],
        'usage': selected['usage'] if selected['usage'] in ('positive', 'negative') else 'unknown',
        'declared_usage': selected['usage'], 'model_scope': 'unknown', 'themes': [],
        'manual_search_eligible': True, 'random_pool_eligible': False, 'strict_model_pool_eligible': False,
        'semantic_review_status': 'user_confirmed', 'alternative_classes': [],
        'classification_uncertain': False, 'note_kind': None, 'note': ''}
    if 'subcategories' in selected:
        result['subcategories'] = normalize_subcategories(selected['subcategories'])
    result['count_markers'] = original_count_markers(prompt['prompt']) if result['usage'] != 'negative' else []
    if selected.get('random_pool_eligible') is True and result['usage'] == 'positive' and result['content_type'] in ('atomic_tag', 'fragment'):
        result.update(random_pool_eligible=True, strict_model_pool_eligible=True, model_scope='anima')
    if previous_category is not None and previous_prompt is not None:
        previous = decision_for(document, previous_category, previous_prompt)
        same_classification = (
            previous.get('manual_search_eligible') is True
            and previous.get('primary_class') == selected['primary_class']
            and previous.get('content_type') == selected['content_type']
            and previous.get('declared_usage', previous.get('usage')) == selected['usage']
        )
        if same_classification:
            # Secondary categories are references to the same maintained item.
            # Editing its title/body must not silently remove those references.
            for key in ('alternative_classes', 'themes', 'classification_uncertain', 'subcategories'):
                if key == 'subcategories' and key in selected:
                    continue
                if key in previous:
                    result[key] = copy.deepcopy(previous[key])
            if previous_prompt.get('prompt') == prompt.get('prompt'):
                for key in ('note_kind', 'note'):
                    if key in previous:
                        result[key] = copy.deepcopy(previous[key])
    result['themes'] = [value for value in result['themes'] if value != 'count']
    result['alternative_classes'] = [value for value in result['alternative_classes'] if value != 'person_count']
    if result['count_markers']:
        result['themes'].append('count')
    previous_owners = (previous_prompt or {}).get('_classification', {}).get('subcategory_owners', {})
    result['subcategory_owners'] = {label: previous_owners.get(label, result['primary_class'])
        for label in result.get('subcategories', []) if label not in SUBCATEGORY_PARENTS}
    result['taxonomy_version'] = '2026-09-20-v1'
    return result


def project_library(data, document, include_pending=False):
    # Shallow-copy containers; prompt and unknown source fields are never modified.
    categories = []
    counts = Counter()
    for category in data.get('categories', []):
        items = []
        for prompt in category.get('prompts', []):
            decision = decision_for(document, category, prompt)
            counts[decision['disposition']] += 1
            if include_pending or (decision['disposition'] in ('reviewed', 'classified') and decision['manual_search_eligible']):
                semantic = {**decision, 'subcategories': selector_subcategories(decision, prompt)}
                semantic['theme_ids'] = sorted(semantic_themes(semantic))
                items.append({**prompt, '_semantic': semantic})
        categories.append({**category, 'prompts': items})
    return {**data, 'categories': categories, '_review_counts': dict(counts),
        '_semantic_class_labels': {**document.get('class_labels', {}), **CLASS_LABELS},
        '_selection_projection': 'S4-semantic-projection-v1'}


def merge_selection_edit(current, document, submitted):
    """Merge a visible-library edit without interpreting hidden omissions as deletion.

    The caller must enforce the source revision before and during the atomic save.
    Hidden records can only be changed through explicit stable-ID editor actions.
    """
    if submitted.get('_selection_projection') != 'S4-semantic-projection-v1':
        raise ValueError('Reload library before saving: missing selection revision context')
    visible = project_library(current, document)
    visible_ids = {p['id'] for c in visible['categories'] for p in c['prompts']}
    all_ids = {p['id'] for c in current['categories'] for p in c['prompts']}
    hidden_ids = all_ids - visible_ids
    seen = set()
    incoming_categories = {}
    for category in submitted.get('categories', []):
        if category['id'] in incoming_categories:
            raise ValueError('Duplicate submitted category identity')
        incoming_categories[category['id']] = category
        for prompt in category.get('prompts', []):
            if prompt['id'] in hidden_ids or prompt['id'] in seen:
                raise ValueError('Hidden or duplicate identity in selection save; use explicit editor')
            seen.add(prompt['id'])
    result = copy.deepcopy(current)
    for key, value in submitted.items():
        if key not in ('categories', '_review_counts', '_semantic_class_labels', '_selection_projection', 'revision', 'base_revision', '_source_to_canonical', '_merge_history'):
            result[key] = copy.deepcopy(value)
    result['categories'] = []
    old_categories = {c['id']: c for c in current['categories']}
    old_prompts = {p['id']: p for c in current['categories'] for p in c.get('prompts', [])}
    for cid, category in incoming_categories.items():
        merged = {**copy.deepcopy(old_categories.get(cid, {})), **copy.deepcopy(category)}
        clean = []
        for prompt in merged.get('prompts', []):
            if prompt['id'] in current.get('_source_to_canonical', {}) or (prompt['id'] not in old_prompts and any(prompt['id'] in event.get('source_ids', []) for event in current.get('_merge_history', []))):
                raise ValueError('Merged source identity cannot be recreated by a selection save')
            # A legacy consumer may return only its known display fields.
            # Missing keys are not an explicit request to delete source data.
            preserved = {**copy.deepcopy(old_prompts.get(prompt['id'], {})), **prompt}
            preserved.pop('_semantic', None)
            if '_merge_sources' in old_prompts.get(prompt['id'], {}):
                preserved['_merge_sources'] = copy.deepcopy(old_prompts[prompt['id']]['_merge_sources'])
            clean.append(preserved)
        # Keep hidden records in their original slots; a no-op edit round-trips.
        remaining = iter(clean)
        prompts = []
        for original in old_categories.get(cid, {}).get('prompts', []):
            if original['id'] in hidden_ids:
                prompts.append(copy.deepcopy(original))
            else:
                replacement = next(remaining, None)
                if replacement is not None:
                    prompts.append(replacement)
        prompts.extend(remaining)
        merged['prompts'] = prompts
        result['categories'].append(merged)
    for cid, category in old_categories.items():
        if cid not in incoming_categories:
            hidden = [copy.deepcopy(p) for p in category.get('prompts', []) if p['id'] in hidden_ids]
            if hidden:
                result['categories'].append({**copy.deepcopy(category), 'prompts': hidden})
    return result


# These are the existing selector capabilities, not inferred model compatibility.
CLASS_ROUTES = {
    'artist_style': ('artist', '画师与作者'),
    'identity': ('character', '角色与身份'), 'appearance': ('character', '外观'),
    'clothing_accessory': ('clothing', '服装与配饰'), 'pose_action': ('pose', '动作与姿势'),
    'expression_gaze': ('pose', '表情与视线'),
    'background_environment': ('background', '背景与环境'),
    'composition_camera': ('style_quality', '构图与镜头'),
    'lighting_color': ('style_quality', '光影与色彩'),
    'style_medium': ('style_quality', '风格与媒介'),
    'quality_detail': ('style_quality', '质量与细节'),
}


BUILTIN_SUBCATEGORIES = {
    'Gestures & Arms': '手势与手臂', 'Standing & Dynamic': '站立与动态',
    'Sitting Poses': '坐姿', 'Lying & Prone': '卧姿与趴姿',
    'Adjusting & Dressing': '整理服饰与发型', 'Props & Holding': '持物与道具互动',
    'Duo & Interaction': '双人与互动', 'Daily & Miscellaneous': '日常与其他动作',
    'Dress & Gown': '礼服与裙装', 'Casual & Daily': '日常与休闲',
    'Uniform & Suit': '制服与西装', 'Swimsuit & Lingerie': '泳装与内衣',
    'Fantasy & Cosplay': '奇幻与角色服饰', 'Revealing': '露肤与剪裁',
    'Nature & Outdoors': '自然与户外', 'Urban & Daily': '城市与日常',
    'Minimalist & Abstract': '极简与抽象', 'Fantasy & Sci-Fi': '幻想与科幻',
}

SUBCATEGORY_RULES = {
    'pose_action': [
        ('坐姿', r'\b(sitting|seiza|lotus position|squat(?:ting)?)\b|坐姿|坐着|蹲'),
        ('卧姿与趴姿', r'\b(lying|prone|supine|on (?:back|stomach|side)|reclining)\b|躺|卧姿|趴'),
        ('站立与动态', r'\b(standing|walking|running|jumping|dancing|flying|kneeling)\b|站姿|站立|行走|奔跑|跳跃|跪'),
        ('手势与手臂', r'\b(hand|hands|arm|arms|finger|fingers|peace sign|v sign|waving|salute)\b|手势|手臂|举手'),
        ('持物与道具互动', r'\b(holding|carrying|wielding|riding|playing instrument)\b|持物|手持|拿着|骑乘'),
        ('整理服饰与发型', r'\b(adjusting|dressing|undressing|tying hair|fixing hair)\b|整理服|整理头发|穿衣'),
        ('双人与互动', r'\b(hugging|embracing|holding hands|handshake|carrying another|couple|duo)\b|双人|拥抱|牵手|互动'),
    ],
    'expression_gaze': [
        ('视线方向', r'\b(looking|gaze|eye contact|staring|averted eyes)\b|视线|看向|凝视'),
        ('微笑与喜悦', r'\b(smile|smiling|laughing|happy|grin)\b|微笑|笑容|开心'),
        ('悲伤与哭泣', r'\b(crying|tears|sad|weeping)\b|哭|悲伤|泪'),
        ('愤怒与不满', r'\b(angry|frown|scowl|annoyed)\b|愤怒|生气|皱眉'),
        ('惊讶与紧张', r'\b(surprised|shocked|nervous|scared|blush)\b|惊讶|紧张|害羞|脸红'),
        ('眼口细节', r'\b(open mouth|closed eyes|wink|tongue|pout)\b|眨眼|闭眼|张嘴'),
    ],
    'clothing_accessory': [
        ('礼服与裙装', r'\b(dress|gown|skirt)\b|礼服|连衣裙|裙装'),
        ('日常与休闲', r'\b(shirt|jeans|hoodie|sweater|t-shirt|casual|shorts|jacket|coat)\b|休闲|衬衫|外套|毛衣'),
        ('制服与西装', r'\b(uniform|suit|blazer|school uniform)\b|制服|西装'),
        ('泳装与内衣', r'\b(swimsuit|bikini|lingerie|underwear|bra|panties|swimwear)\b|泳装|比基尼|内衣'),
        ('奇幻与角色服饰', r'\b(armor|cosplay|fantasy|witch|maid|kimono|hanfu)\b|盔甲|角色扮演|汉服|和服'),
        ('配饰与鞋袜', r'\b(hat|glasses|necklace|earrings|boots|shoes|socks|stockings|gloves)\b|帽子|眼镜|项链|耳环|鞋|袜|手套'),
    ],
    'background_environment': [
        ('自然与户外', r'\b(forest|mountain|beach|ocean|river|lake|garden|flower|sky|nature)\b|森林|山|海滩|河流|花园|天空'),
        ('城市与日常', r'\b(city|street|urban|building|room|cafe|bedroom|school|kitchen)\b|城市|街道|房间|咖啡|卧室|厨房'),
        ('极简与抽象', r'\b(simple background|white background|black background|gradient|abstract|minimalist)\b|纯色|渐变|抽象|极简'),
        ('幻想与科幻', r'\b(fantasy|sci-fi|cyberpunk|spaceship|magic|space station|dungeon)\b|科幻|幻想|魔法|太空|赛博'),
    ],
}


def normalize_subcategories(values):
    if not isinstance(values, list) or len(values) > len(SUBCATEGORY_PARENTS):
        raise ValueError(f'细分类必须是最多 {len(SUBCATEGORY_PARENTS)} 项的列表')
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError('细分类必须是文字')
        parts = [part.strip() for part in value.split('/') if part.strip()]
        label = '/'.join(parts)
        if not label or len(label) > 120 or len(parts) > 4 or any(ord(c) < 32 for c in label):
            raise ValueError('细分类路径无效')
        if label not in result:
            result.append(label)
    return result



_SOFT_LIGHT_MODIFIER_AGE_RISK = re.compile(
    r'\b(?:loli|shota|mesugaki|child|children|underage|teen|teenage(?:r|rs)?|randoseru|junior high school|aged.down|young boy|little (?:girl|boy))\b|'
    r'\b(?:age(?:d)?\s*(?:[0-9]|1[0-7])\b|(?:[0-9]|1[0-7])[ -]+years?[ -]+old\b)|未成年|幼女|幼童|小正太|萝莉', re.I)


def soft_light_modifier_cue_exclusion(decision, category, prompt, current_subcategories):
    """Return a stable first-failure reason for the shared soft-light eligibility gate."""
    usage = decision.get('declared_usage', decision.get('usage'))
    body = str(prompt.get('prompt', ''))
    category_name = str(category.get('name', ''))
    if decision.get('disposition') not in ('reviewed', 'classified') or decision.get('manual_search_eligible') is not True:
        return 'review_or_manual_eligibility'
    if decision.get('semantic_review_status') == 'user_confirmed':
        return 'user_confirmed'
    if usage not in ('positive', 'mixed'):
        return 'nonpositive_or_unknown_usage'
    if decision.get('primary_class') == 'artist_style':
        return 'artist_only'
    if category_name.split('/')[0].strip() == '🔞一键模式' or re.search(r'小孩|幼女|幼童|正太|萝莉|未成年', category_name):
        return 'protected_source_category'
    if not 1 <= len(body) <= 1800:
        return 'outside_length_scope'
    normalized_body = body.replace('_', ' ')
    if _SOFT_LIGHT_MODIFIER_AGE_RISK.search(normalized_body):
        return 'age_risk'
    # Require a student/school-uniform context and an explicit school location.
    # Adult evidence must describe the subject; a teacher or unrelated adult
    # elsewhere in the prompt cannot exempt an age-uncertain student.
    school_student = re.search(r'\b(?:student|pupil|schoolgirl|schoolboy)\b|学生|女学生|男学生', normalized_body, re.I)
    school_uniform = re.search(r'\b(?:school uniform|sailor uniform|serafuku)\b|校服|水手服', normalized_body, re.I)
    school_setting = re.search(r'\b(?:school|classroom|schoolhouse)\s+(?:staircase|stairs|stairway|corridor|hallway|classroom)\b|\bclassroom\b|\bschool\s+campus\b|学校(?:走廊|楼梯|教室|校园)|校园|教室', normalized_body, re.I)
    explicit_adult_subject = re.search(r'\badult\s+(?:woman|man|female|male|person|model|cosplayer)\b|成年(?:女性|男性|人)', normalized_body, re.I)
    explicit_adult_student = re.search(r'\badult\s+(?:(?:female|male)\s+)?(?:student|pupil)\b|\badult\s+(?:university|college)\s+student\b|成年大学生', normalized_body, re.I)
    if school_setting and (school_student or school_uniform):
        if school_student and not explicit_adult_student:
            return 'school_age_context'
        if not school_student and not explicit_adult_subject:
            return 'school_age_context'
    if '光影效果' not in current_subcategories:
        return 'missing_current_parent'
    return None


def soft_light_modifier_cue_allowed(decision, category, prompt, current_subcategories):
    """Current-source qualification shared by candidate scans and runtime callers."""
    return soft_light_modifier_cue_exclusion(decision, category, prompt, current_subcategories) is None

def selector_subcategories(decision, prompt):
    if decision.get('taxonomy_version'):
        return normalize_subcategories(decision.get('subcategories', []))
    if normalize_subcategories(decision.get('subcategories', [])):
        return normalize_subcategories(decision['subcategories'])
    primary = decision.get('primary_class')
    text = ' '.join([str(prompt.get('alias', '')), str(prompt.get('prompt', ''))]).lower().replace('_', ' ')
    matches = [label for label, pattern in SUBCATEGORY_RULES.get(primary, []) if re.search(pattern, text)]
    return matches or [{'pose_action': '日常与其他动作', 'expression_gaze': '其他表情',
        'clothing_accessory': '其他服饰', 'background_environment': '其他场景',
        'artist_style': '画师标签'}.get(primary, '其他')]


def fragment_route(decision):
    if (decision['disposition'] not in ('reviewed', 'classified') or not decision['manual_search_eligible']
            or decision['usage'] != 'positive' or decision['content_type'] not in ('fragment', 'atomic_tag')):
        return None
    return CLASS_ROUTES.get(decision['primary_class'])
