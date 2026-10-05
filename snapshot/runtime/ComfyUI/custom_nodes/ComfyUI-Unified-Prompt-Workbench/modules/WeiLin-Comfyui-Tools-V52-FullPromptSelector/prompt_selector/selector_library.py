"""Anima selector views and migration over the WeiLin source document."""
import copy
import hashlib
import re
from urllib.parse import quote
from .semantic_projection import binding, decision_for, CLASS_ROUTES, BUILTIN_SUBCATEGORIES

KINDS = {'pose': 'pose_action', 'clothing': 'clothing_accessory',
    'background': 'background_environment', 'character': 'identity',
    'artist': 'artist_style', 'style_quality': 'style_medium'}

COLLECTION_KINDS = (*KINDS, 'tag', 'model', 'image', 'resource')


def collection_catalog(data):
    state = data.get('selector_library', {})
    if 'collections' in state:
        return state['collections'], {}
    groups = {'default': {'id': 'default', 'name': '默认收藏', 'isSystem': True}}
    aliases = {}
    for kind, source in state.get('groups', {}).items():
        aliases[kind] = {}
        for item in source:
            identity = item['id']
            if identity == 'default':
                continue
            if identity in groups and groups[identity]['name'] != item['name']:
                identity = 'collection-' + hashlib.sha256((kind + ':' + identity).encode()).hexdigest()[:24]
            aliases[kind][item['id']] = identity
            groups.setdefault(identity, {**copy.deepcopy(item), 'id': identity})
    return list(groups.values()), aliases


def collection_groups(data, kind=None):
    return collection_catalog(data)[0]


def prompt_collection(prompt, kind=None):
    if '_collection' in prompt:
        return prompt['_collection']
    records = prompt.get('_selector_favorites', {})
    return records.get(kind) or next(iter(records.values()), {})


def migrate_collections(data):
    state = data['selector_library']
    if 'collections' in state:
        return False
    groups, aliases = collection_catalog(data)
    state['collections'] = groups
    for kind in state.get('kinds', []):
        records = list(state.get('unresolved', {}).get(kind, []))
        records.extend(p['_selector_favorites'][kind] for c in data['categories'] for p in c['prompts'] if kind in p.get('_selector_favorites', {}))
        mapping = aliases.get(kind, {})
        for record in records:
            record['groupIds'] = [mapping.get(identity, identity) for identity in record.get('groupIds', ['default'])]
    for category in data['categories']:
        for prompt in category['prompts']:
            if prompt.get('_selector_favorites') and '_collection' not in prompt:
                kind = selector_kind(prompt.get('_classification', {}))
                prompt['_collection'] = copy.deepcopy(prompt_collection(prompt, kind))
    state['collection_catalog_version'] = 1
    return True


def resource_id(kind, key):
    return 'anima-' + kind + '-' + hashlib.sha256(str(key).encode('utf-8')).hexdigest()[:24]


def canonical_key(kind, prompt_id):
    return f'shared:weilin:{kind}:{prompt_id}'


def selector_kind(decision):
    route = CLASS_ROUTES.get(decision.get('primary_class'))
    return route[0] if route else None


def _custom_resource(data, kind, record, now):
    pid = resource_id(kind, 'custom:' + str(record['id']))
    for category in data['categories']:
        for prompt in category['prompts']:
            if prompt['id'] == pid:
                content = str(record.get('customContent') or '')
                if not content.strip():
                    raise ValueError('自建资料正文不能为空')
                prompt.update(alias=str(record.get('nickname') or record.get('name') or '自建资料'),
                    prompt=content, updated_at=now, _selector_legacy_custom=copy.deepcopy(record))
                prompt['_classification']['binding'] = binding(category, prompt)
                return category, prompt
    category = next((c for c in data['categories'] if c['id'] == 'anima-custom-' + kind), None)
    if category is None:
        category = {'id': 'anima-custom-' + kind, 'name': 'Anima 自建/' + CLASS_ROUTES[KINDS[kind]][1],
            'created_at': now, 'updated_at': now, 'prompts': []}
        data['categories'].append(category)
    prompt = {'id': pid, 'alias': str(record.get('nickname') or record.get('name') or '自建资料'),
        'prompt': str(record.get('customContent') or ''), 'description': '', 'image': '', 'tags': [],
        'favorite': True, 'created_at': now, 'updated_at': now,
        '_selector_legacy_custom': copy.deepcopy(record)}
    if not prompt['prompt'].strip():
        raise ValueError('自建资料正文不能为空')
    prompt['_classification'] = {'binding': binding(category, prompt), 'disposition': 'classified',
        'primary_class': KINDS[kind], 'content_type': 'fragment', 'usage': 'positive', 'declared_usage': 'positive',
        'manual_search_eligible': True, 'random_pool_eligible': False, 'strict_model_pool_eligible': False,
        'model_scope': 'unknown', 'semantic_review_status': 'user_created', 'alternative_classes': []}
    category['prompts'].append(prompt)
    return category, prompt


def migrate(data, sources, favorites, official, now):
    """Idempotent import. Never rehydrate a deleted or edited canonical item."""
    state = data.setdefault('selector_library', {'version': 1, 'kinds': [], 'groups': {}, 'unresolved': {}})
    state.setdefault('legacy_favorites', copy.deepcopy(favorites))
    known = {p['id'] for c in data['categories'] for p in c['prompts']}
    existing = {p['id']: p for c in data['categories'] for p in c['prompts']}
    imported = {}
    for kind, rows in sources.items():
        if kind in state['kinds']:
            imported[kind] = 0
            continue
        category = {'id': 'anima-builtin-' + kind, 'name': 'Anima 内置/' + CLASS_ROUTES[KINDS[kind]][1],
            'created_at': now, 'updated_at': now, 'prompts': []}
        names, identities = {}, {}
        for row in rows:
            original = copy.deepcopy(row)
            old_id = str(row.get('id') or row['name'])
            pid = resource_id(kind, old_id)
            if pid in known:
                raise ValueError('Built-in identity collides before migration: ' + pid)
            name = row.get('name_zh') or row['name']
            text = row.get('tags', '')
            preview = row.get('preview', '')
            if kind == 'artist':
                text = '@' + row['name']
                preview = f"https://fastly.jsdelivr.net/gh/ThetaCursed/Anima-Assets@main/images/{row.get('p', 1)}/{old_id}.webp"
            if kind == 'character':
                norm = lambda value: ' '.join(str(value or '').lower().replace('_', ' ').split())
                details = official.get(norm(row['name']) + '||' + norm(row.get('copyright'))) or {}
                original['official'] = copy.deepcopy(details)
                raw_name = row['name'] + (', ' + row['copyright'] if row.get('copyright') else '')
                text = details.get('trigger') or raw_name
                preview = 'https://blobs.animadex.net/Outputs/thumbs/' + quote(raw_name, safe='') + '.webp'
            subcategories = []
            for label in row.get('categories', []):
                english = re.search(r'\(([^)]+)\)$', label)
                translated = BUILTIN_SUBCATEGORIES.get(english[1] if english else label, label)
                if translated not in subcategories:
                    subcategories.append(translated)
            if kind == 'character':
                subcategories = [str(row.get('copyright') or '其他角色').replace('/', ' · ')]
            elif kind == 'artist':
                subcategories = ['画师标签/' + (row['name'][0].upper() if row['name'][0].isascii() and row['name'][0].isalpha() else '其他')]
            prompt = {'id': pid, 'alias': name, 'aliases': list(dict.fromkeys([row['name'], row.get('name_zh', '')])),
                'prompt': text, 'description': row.get('tags_zh', ''), 'image': '', 'preview_url': preview,
                'tags': list(row.get('traits', [])), 'favorite': False, 'template': False,
                'created_at': now, 'updated_at': now, 'usage_count': 0, 'last_used': None,
                '_selector_origin': {'kind': kind, 'id': old_id, 'record': original}}
            if kind == 'character':
                detail = details.get('tags') or ', '.join(filter(None, [row.get('gender'),
                    row.get('hair') and row['hair'] + ' hair', row.get('eye') and row['eye'] + ' eyes']))
                prompt['character_details'] = ', '.join(detail) if isinstance(detail, list) else str(detail)
            classification = {'disposition': 'classified', 'primary_class': KINDS[kind],
                'content_type': 'atomic_tag' if kind in ('artist', 'character') else 'fragment',
                'usage': 'positive', 'declared_usage': 'positive', 'model_scope': 'anima',
                'manual_search_eligible': True, 'random_pool_eligible': True, 'strict_model_pool_eligible': True,
                'subcategories': subcategories, 'alternative_classes': [], 'themes': [],
                'semantic_review_status': 'builtin_metadata_preserved', 'classification_uncertain': False}
            # Keep ambiguous sexual minor material out of the newly shared selection pools.
            content = (name + ' ' + text).lower().replace('_', ' ')
            if re.search(r'\b(loli|shota|child|underage|schoolgirl|schoolboy|teen)\b|幼女|幼童|未成年', content) and re.search(r'\b(nude|naked|sex|sexual|nipples|panties|lingerie|revealing)\b|裸体|性交|露乳', content):
                classification.update(disposition='quarantined', manual_search_eligible=False,
                    random_pool_eligible=False, strict_model_pool_eligible=False,
                    semantic_review_status='age_content_review_required')
            classification['binding'] = binding(category, prompt)
            prompt['_classification'] = classification
            category['prompts'].append(prompt)
            known.add(pid)
            names.setdefault(row['name'], []).append(prompt)
            old_key = f"local:{old_id}" if kind != 'character' else f"local:{row['name']}:{row.get('copyright', '')}"
            identities[old_key] = prompt
            identities[old_id] = prompt
        section = favorites.get(kind, {})
        state['groups'][kind] = copy.deepcopy(section.get('groups', [{'id': 'default', 'name': 'Default Favorites', 'isSystem': True}]))
        state['unresolved'][kind] = []
        for favorite in section.get('items', []):
            key = str(favorite.get('selectorKey') or favorite.get('id') or '')
            match = identities.get(key)
            for prefix in (f'shared:weilin:{kind}:', f'weilin:{kind}:'):
                if key.startswith(prefix):
                    match = existing.get(key[len(prefix):])
            if match is None and not favorite.get('selectorKey') and len(names.get(favorite.get('name'), [])) == 1:
                match = names[favorite['name']][0]
            if match:
                match['favorite'] = True
                match.setdefault('_selector_favorites', {})[kind] = copy.deepcopy(favorite)
            elif favorite.get('isCustom'):
                _, custom = _custom_resource(data, kind, favorite, now)
                custom.setdefault('_selector_favorites', {})[kind] = copy.deepcopy(favorite)
            else:
                state['unresolved'][kind].append(copy.deepcopy(favorite))
        data['categories'].append(category)
        state['kinds'].append(kind)
        imported[kind] = len(rows)
    data['last_modified'] = now
    return imported


def favorites_view(data, document, legacy):
    result = copy.deepcopy(legacy)
    state = data.get('selector_library', {})
    kinds = state.get('kinds', [])
    catalog, aliases = collection_catalog(data)
    for kind in kinds:
        result[kind] = {'groups': copy.deepcopy(catalog),
            'items': copy.deepcopy(state.get('unresolved', {}).get(kind, []))}
        for record in result[kind]['items']:
            record['groupIds'] = [aliases.get(kind, {}).get(identity, identity) for identity in record.get('groupIds', ['default'])]
    for category in data.get('categories', []):
        for prompt in category.get('prompts', []):
            if not prompt.get('favorite'):
                continue
            decision = decision_for(document, category, prompt)
            kind = selector_kind(decision)
            if kind not in kinds:
                continue
            metadata = copy.deepcopy(prompt_collection(prompt, kind))
            metadata.update(id=f"weilin:{kind}:{prompt['id']}", selectorKey=canonical_key(kind, prompt['id']),
                name=prompt['alias'], isCustom=False)
            metadata.setdefault('groupIds', ['default'])
            metadata['groupIds'] = [aliases.get(kind, {}).get(identity, identity) for identity in metadata['groupIds']]
            metadata.setdefault('nickname', '')
            result[kind]['items'].append(metadata)
    return result


def apply_favorites(data, document, incoming, current, now):
    state = data['selector_library']
    migrate_collections(data)
    changes, removed = {}, set()
    known = {group['id']: group for group in collection_groups(data)}
    for kind in state['kinds']:
        section = incoming.get(kind)
        if not isinstance(section, dict) or section == current.get(kind):
            continue
        validate_groups(section.get('groups'))
        previous = {group['id']: group for group in current.get(kind, {}).get('groups', [])}
        updated = {group['id']: group for group in section['groups']}
        removed.update(previous.keys() - updated.keys())
        for identity, group in updated.items():
            if identity in previous and group == previous[identity]:
                continue
            if identity in changes and changes[identity]['name'] != group['name']:
                raise ValueError('不同入口提交了互相冲突的收藏组名称')
            changes[identity] = group
    if removed.intersection(changes):
        raise ValueError('收藏组同时被修改和删除，请重新核对')
    items = {p['id']: (c, p) for c in data['categories'] for p in c['prompts']}
    for kind in state['kinds']:
        if kind not in incoming or incoming[kind] == current.get(kind):
            continue
        section = incoming[kind]
        if not isinstance(section, dict) or not isinstance(section.get('items'), list) or not isinstance(section.get('groups'), list):
            raise ValueError('Invalid selector favorites section')
        validate_groups(section['groups'])
        removed_groups = {g['id'] for g in current.get(kind, {}).get('groups', [])} - {g['id'] for g in section['groups']}
        records = list(section['items'])
        if removed_groups:
            identity = lambda record: record.get('selectorKey') or record.get('id')
            incoming_ids = {identity(record) for record in records}
            for record in current.get(kind, {}).get('items', []):
                if identity(record) and identity(record) not in incoming_ids and removed_groups.intersection(record.get('groupIds', [])):
                    records.append(copy.deepcopy(record))
        selected, unresolved = set(), []
        for record in records:
            key = str(record.get('selectorKey') or record.get('id') or '')
            prefix = f'shared:weilin:{kind}:'
            short_prefix = f'weilin:{kind}:'
            pid = key[len(prefix):] if key.startswith(prefix) else key[len(short_prefix):] if key.startswith(short_prefix) else ''
            if record.get('isCustom'):
                category, prompt = _custom_resource(data, kind, record, now)
                pid = prompt['id']
                items[pid] = (category, prompt)
            if pid not in items:
                unresolved.append(copy.deepcopy(record))
                continue
            category, prompt = items[pid]
            if selector_kind(decision_for(document, category, prompt)) != kind:
                raise ValueError('Resource classification changed; reload favorites')
            selected.add(pid)
            prompt.setdefault('_selector_favorites', {})[kind] = copy.deepcopy(record)
            prompt['_collection'] = copy.deepcopy(record)
        for pid, (category, prompt) in items.items():
            if selector_kind(decision_for(document, category, prompt)) == kind:
                prompt['favorite'] = pid in selected
        state['unresolved'][kind] = unresolved
    for identity, group in changes.items():
        update_collection(data, {'kind':'tag', 'operation':'rename' if identity in known else 'create', 'group_id':identity, 'name':group['name']})
    for identity in removed:
        update_collection(data, {'kind':'tag', 'operation':'delete', 'group_id':identity})
    for kind in state['kinds']:
        normalize_collection_memberships(data, kind)
    data['last_modified'] = now


def apply_collection(data, prompt, decision, group_ids, details=None):
    """Keep collection membership in the same resource transaction as editing."""
    if not isinstance(group_ids, list) or any(not isinstance(value, str) for value in group_ids):
        raise ValueError('收藏组必须是 ID 列表')
    kind = selector_kind(decision)
    migrate_collections(data)
    groups = collection_groups(data)
    known = {group['id'] for group in groups}
    if any(value not in known for value in group_ids):
        raise ValueError('收藏组或资料主题已变化，请重新选择收藏组')
    metadata = prompt.setdefault('_collection', copy.deepcopy(prompt_collection(prompt, kind)))
    metadata['groupIds'] = list(dict.fromkeys(group_ids)) or (['default'] if 'default' in known else [])
    if details is not None:
        if not isinstance(details, dict) or any(key not in ('nickname', 'notes') or not isinstance(value, str) for key, value in details.items()):
            raise ValueError('收藏别名和备注必须为文本')
        metadata.update(details)
    if kind:
        prompt.setdefault('_selector_favorites', {})[kind] = copy.deepcopy(metadata)


def validate_groups(groups):
    if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('id'), str)
            or not g['id'] or not isinstance(g.get('name'), str) or not g['name'].strip() for g in groups):
        raise ValueError('收藏组必须包含有效 ID 和名称')
    ids = [g['id'] for g in groups]
    if len(set(ids)) != len(ids) or 'default' not in ids:
        raise ValueError('收藏组 ID 不能重复，默认收藏组必须保留')


def normalize_collection_memberships(data, kind):
    known = {group['id'] for group in collection_groups(data)}
    for entries in data['selector_library'].get('references', {}).values():
        for identity, memberships in entries.items():
            entries[identity] = [value for value in memberships if value in known] or ['default']
    records = list(data['selector_library'].get('unresolved', {}).get(kind, []))
    records.extend(prompt['_selector_favorites'][kind] for category in data['categories'] for prompt in category['prompts']
        if kind in prompt.get('_selector_favorites', {}))
    records.extend(prompt['_collection'] for category in data['categories'] for prompt in category['prompts'] if '_collection' in prompt)
    for record in records:
        record['groupIds'] = list(dict.fromkeys(g for g in record.get('groupIds', []) if g in known)) or ['default']


def update_collection(data, payload):
    kind = payload.get('kind')
    state = data.get('selector_library', {})
    if kind not in COLLECTION_KINDS:
        raise ValueError('未知的资料类型')
    migrated = migrate_collections(data)
    groups = collection_groups(data)
    validate_groups(groups)
    operation = payload.get('operation')
    group_id = str(payload.get('group_id') or '').strip()
    name = str(payload.get('name') or '').strip()
    if operation not in ('create', 'rename', 'delete') or not group_id:
        raise ValueError('需要有效的收藏组操作和 ID')
    group = next((g for g in groups if g['id'] == group_id), None)
    if operation in ('create', 'rename'):
        if not name:
            raise ValueError('请填写收藏组名称')
        if any(g['id'] != group_id and g['name'].strip().casefold() == name.casefold() for g in groups):
            raise ValueError('已有同名共享收藏组')
    if operation == 'create':
        if group:
            if group['name'] == name and not group.get('isSystem'):
                return migrated
            raise ValueError('收藏组 ID 已存在，请重新创建')
        groups.append({'id': group_id, 'name': name, 'isSystem': False})
        return True
    if group is None:
        if operation == 'delete':
            return migrated
        raise KeyError('收藏组已不存在，请重新加载')
    if group_id == 'default' or group.get('isSystem'):
        raise ValueError('默认或系统收藏组不能改名或删除')
    if operation == 'rename':
        if group['name'] == name:
            return migrated
        group['name'] = name
    else:
        groups.remove(group)
        for member_kind in state.get('kinds', []):
            normalize_collection_memberships(data, member_kind)
    return True
