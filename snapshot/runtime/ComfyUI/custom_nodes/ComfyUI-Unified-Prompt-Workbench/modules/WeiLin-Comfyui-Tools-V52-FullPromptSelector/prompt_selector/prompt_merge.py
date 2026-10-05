"""Explicit, revision-bound exact merges; immutable source snapshots stay in store."""
import copy
import hashlib
import json

from .semantic_projection import binding, decision_for


def _library_index(data):
    """Map every stable prompt id to its category and record, rejecting duplicates."""
    index = {}
    for category in data.get('categories', []):
        for prompt in category.get('prompts', []):
            if prompt['id'] in index:
                raise ValueError('资料库存在重复身份，请先修复')
            index[prompt['id']] = (category, prompt)
    return index


def eligibility_reason(projection, category, prompt):
    """Return '' when a record may take part in a merge, else the blocking reason."""
    decision = decision_for(projection, category, prompt)
    scope = decision.get('model_scope')
    usage = decision.get('declared_usage', decision.get('usage'))
    if (not decision.get('manual_search_eligible') or usage not in ('positive', 'negative')
            or not scope or scope in ('unknown', 'unconfirmed') or prompt.get('_import_quarantine')):
        return '合并前须确认每条资料的分类、正负用途和模型范围；未知范围不能推定为通用'
    return ''


def compatibility_tuple(decision, prompt):
    """The reviewed constraints two records must share before they may be merged."""
    return [decision.get('content_type'), decision.get('declared_usage', decision.get('usage')),
            decision.get('model_scope'), decision.get('primary_class'),
            prompt.get('resource_binding'), prompt.get('model_binding')]


def review_fingerprint(projection, category, prompt):
    """Snapshot of everything one reviewed row contributes to the merge decision."""
    decision = decision_for(projection, category, prompt)
    payload = {'category_id': str(category.get('id')),
               'body': prompt.get('prompt'),
               'compatibility': compatibility_tuple(decision, prompt)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def merge_plan(data, projection, prompt_ids, canonical_id, reviewed=None):
    """Per-item verdicts for one merge selection.

    The strict ``merge_preview`` stays the gate that decides whether a selected
    set may be merged at all.  This plan answers the follow-up question the
    workbench was missing: for each selected source, did it fold into the kept
    record, or was it skipped, and why.  ``reviewed`` carries the classification
    fingerprints captured when the user confirmed the comparison, so a source
    that changed afterwards is reported instead of merged silently.
    """
    if not isinstance(prompt_ids, list) or not 2 <= len(prompt_ids) <= 30:
        raise ValueError('请选择 2 到 30 条资料')
    if any(not isinstance(x, str) or not x for x in prompt_ids) or len(set(prompt_ids)) != len(prompt_ids):
        raise ValueError('资料身份重复或无效')
    if canonical_id not in prompt_ids:
        raise ValueError('请选择一条保留身份的资料')
    index = _library_index(data)
    mapping = data.get('_source_to_canonical') or {}
    if canonical_id not in index:
        record = mapping.get(canonical_id)
        target = record.get('canonical_id') if isinstance(record, dict) else ''
        raise ValueError('保留身份的资料已不存在' + (f'（此前已并入 {target}）' if target
            else '，请刷新列表后重新选择'))
    canonical_category, canonical = index[canonical_id]
    if reviewed is not None and reviewed.get(canonical_id) != review_fingerprint(
            projection, canonical_category, canonical):
        raise ValueError('对照后保留资料的正文或分类已变化，请重新对照')
    blocked = eligibility_reason(projection, canonical_category, canonical)
    if blocked:
        raise ValueError('保留身份的资料需要先确认分类：' + blocked)
    canonical_compat = compatibility_tuple(
        decision_for(projection, canonical_category, canonical), canonical)
    body = canonical.get('prompt')
    rows = [{'resource_id': canonical_id, 'target_id': canonical_id, 'status': 'kept', 'reason': '',
             'category_id': str(canonical_category.get('id') or canonical_category.get('name') or ''),
             'category_name': canonical_category.get('name') or '',
             'alias': canonical.get('alias') or canonical_id}]
    for prompt_id in prompt_ids:
        if prompt_id == canonical_id:
            continue
        found = index.get(prompt_id)
        status, reason = 'merged', ''
        if found is None:
            record = mapping.get(prompt_id)
            target = record.get('canonical_id') if isinstance(record, dict) else ''
            if target == canonical_id:
                reason = '此前已并入保留资料'
            elif target:
                reason = f'此前已并入其他资料（{target}）'
            else:
                reason = '资料已不存在（可能已被删除，或正在其他窗口编辑）'
            status = 'skipped'
        else:
            category, prompt = found
            decision = decision_for(projection, category, prompt)
            if reviewed is not None and reviewed.get(prompt_id) != review_fingerprint(
                    projection, category, prompt):
                # The record no longer matches what the user compared, so it is
                # reported instead of being folded in behind their back.
                status, reason = 'skipped', '对照后这条资料已变化，保留为独立资料'
            else:
                reason = eligibility_reason(projection, category, prompt)
                if reason:
                    status = 'skipped'
                elif prompt.get('prompt') != body:
                    status, reason = 'skipped', '正文并非逐字相同：保留为独立资料'
                elif compatibility_tuple(decision, prompt) != canonical_compat:
                    status, reason = 'skipped', '类型、分类、用途或模型约束不同：保留为独立资料'
                else:
                    status, reason = 'merged', ''
        row = {'resource_id': prompt_id, 'target_id': canonical_id, 'status': status, 'reason': reason}
        if found is not None:
            row.update({'category_id': str(found[0].get('id') or found[0].get('name') or ''),
                        'category_name': found[0].get('name') or '',
                        'alias': found[1].get('alias') or prompt_id})
        else:
            row.update({'category_id': '', 'category_name': '', 'alias': prompt_id})
        rows.append(row)
    return {'canonical_id': canonical_id, 'rows': rows,
            'mergeable_ids': [row['resource_id'] for row in rows if row['status'] == 'merged']}


def merge_task_record(data, task_id):
    """Durable per-item record of one numbered merge task, or None."""
    if not isinstance(task_id, str) or not task_id:
        return None
    for event in reversed(data.get('_merge_history') or []):
        if isinstance(event, dict) and event.get('task_id') == task_id:
            return event
    return None


def _checked_ids(prompt_ids, canonical_id):
    if not isinstance(prompt_ids, list) or not 2 <= len(prompt_ids) <= 30:
        raise ValueError('请选择 2 到 30 条资料')
    if any(not isinstance(x, str) or not x for x in prompt_ids) or len(set(prompt_ids)) != len(prompt_ids):
        raise ValueError('资料身份重复或无效')
    if canonical_id not in prompt_ids:
        raise ValueError('请选择一条保留身份的资料')


def merge_comparison(data, projection, prompt_ids, canonical_id, index=None):
    """Read-only comparison rows for the selected ids, tolerant of missing ones.

    The strict gate in ``merge_preview`` still decides whether a set may be
    merged; this comparison keeps the dialog able to show every selected source
    even when one of them has already changed or disappeared.
    """
    _checked_ids(prompt_ids, canonical_id)
    index = _library_index(data) if index is None else index
    rows = []
    for pid in prompt_ids:
        if pid not in index:
            continue
        category, prompt = index[pid]
        rows.append({'category': copy.deepcopy({k: v for k, v in category.items() if k != 'prompts'}),
                     'classification': copy.deepcopy(decision_for(projection, category, prompt)),
                     'prompt': copy.deepcopy(prompt)})
    differing = []
    if len(rows) > 1:
        keys = set().union(*(r['prompt'].keys() for r in rows)) - {'id', 'prompt', '_classification'}
        for key in sorted(keys):
            values = [json.dumps(r['prompt'].get(key), ensure_ascii=False, sort_keys=True) for r in rows]
            if len(set(values)) > 1:
                differing.append(key)
    return {'canonical_id': canonical_id, 'prompt_ids': prompt_ids, 'sources': rows,
            'differing_fields': differing,
            'missing': [pid for pid in prompt_ids if pid not in index],
            'revision': str(data.get('last_modified') or '')}


def merge_review_token(canonical_id, prompt_ids, fingerprints):
    """Token binding one reviewed comparison to a numbered merge task."""
    payload = {'canonical_id': canonical_id, 'prompt_ids': list(prompt_ids),
               'fingerprints': dict(fingerprints)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def merge_preview(data, projection, prompt_ids, canonical_id):
    _checked_ids(prompt_ids, canonical_id)
    index = _library_index(data)
    if any(x not in index for x in prompt_ids):
        raise ValueError('所选资料已变化，请重新选择')
    compatibility = []
    for pid in prompt_ids:
        category, prompt = index[pid]
        decision = decision_for(projection, category, prompt)
        blocked = eligibility_reason(projection, category, prompt)
        if blocked:
            raise ValueError(blocked)
        compatibility.append(compatibility_tuple(decision, prompt))
    preview = merge_comparison(data, projection, prompt_ids, canonical_id, index=index)
    rows = preview['sources']
    bodies = [r['prompt'].get('prompt') for r in rows]
    if not isinstance(bodies[0], str) or not bodies[0].strip() or any(x != bodies[0] for x in bodies[1:]):
        raise ValueError('正文并非逐字相同：保留为独立资料')
    if any(x != compatibility[0] for x in compatibility[1:]):
        raise ValueError('类型、分类、用途或模型约束不同：保留为独立资料')
    preview.pop('missing', None)
    preview['compatibility'] = compatibility[0]
    preview['review_token'] = hashlib.sha256(json.dumps(preview, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return preview


def apply_merge(data, projection, payload, now):
    preview = merge_preview(data, projection, payload.get('prompt_ids'), payload.get('canonical_id'))
    if payload.get('metadata_reviewed') is not True or payload.get('review_token') != preview['review_token']:
        raise ValueError('请先对照当前来源及元数据，再确认合并')
    result = copy.deepcopy(data)
    canonical_id = preview['canonical_id']
    removed = set(preview['prompt_ids']) - {canonical_id}
    canonical_category = next(c for c in result['categories'] if any(p['id'] == canonical_id for p in c['prompts']))
    canonical = next(p for p in canonical_category['prompts'] if p['id'] == canonical_id)
    decision = copy.deepcopy(decision_for(projection, canonical_category, canonical))
    sources = []
    for row in preview['sources']:
        previous = row['prompt'].get('_merge_sources')
        if previous:
            sources.extend(copy.deepcopy(previous))
        # Keep the current version as well as older source versions.
        snapshot = copy.deepcopy(row)
        snapshot['prompt'].pop('_merge_sources', None)
        if snapshot not in sources:
            sources.append(snapshot)
    canonical['_merge_sources'] = sources
    aliases = []
    for row in sources:
        p = row['prompt']
        for alias in [p.get('alias'), *(p.get('aliases') if isinstance(p.get('aliases'), list) else [])]:
            if isinstance(alias, str) and alias and alias not in aliases:
                aliases.append(alias)
    canonical['aliases'] = aliases
    canonical['favorite'] = any(r['prompt'].get('favorite') for r in preview['sources'])
    if any(r['prompt'].get('is_user_plan') is True for r in preview['sources']):
        canonical['is_user_plan'] = True
    canonical['updated_at'] = now
    canonical['_classification'] = decision
    decision['binding'] = binding(canonical_category, canonical)
    mapping = result.setdefault('_source_to_canonical', {})
    for record in mapping.values():
        if record['canonical_id'] in removed:
            record['canonical_id'] = canonical_id
    for row in preview['sources']:
        pid = row['prompt']['id']
        if pid in removed:
            mapping[pid] = {'canonical_id': canonical_id, 'source_category_id': row['category']['id']}
    for category in result['categories']:
        if any(p['id'] in removed for p in category['prompts']) or category is canonical_category:
            category['updated_at'] = now
        category['prompts'] = [p for p in category['prompts'] if p['id'] not in removed]
    result.setdefault('_merge_history', []).append({'at': now, 'review_token': preview['review_token'],
        'canonical_id': canonical_id, 'source_ids': preview['prompt_ids'], 'metadata_reviewed': True,
        'sources': copy.deepcopy(sources)})
    result['last_modified'] = now
    return result, preview


def merged_source(data, source_id, category_id=''):
    mapping = data.get('_source_to_canonical', {}).get(source_id)
    if not mapping or (category_id and category_id != mapping['source_category_id']):
        return None
    for category in data.get('categories', []):
        for prompt in category.get('prompts', []):
            if prompt['id'] == mapping['canonical_id']:
                return category, prompt
    return None


def known_merged_import(data, category_id, prompt, fingerprint):
    """A historical import is already represented only if its exact snapshot matches."""
    # History remains even after explicit deletion of the maintained item, so a
    # later source sync cannot silently resurrect it or discard its provenance.
    sources = [row for event in data.get('_merge_history', []) for row in event.get('sources', [])]
    return any(str(row['category'].get('id')) == category_id
        and str(row['prompt'].get('id')) == str(prompt.get('_source_id') or prompt.get('id'))
        and fingerprint({**row['prompt'], '_source_id': row['prompt']['id']}) == prompt.get('_source_fingerprint')
        for row in sources)
