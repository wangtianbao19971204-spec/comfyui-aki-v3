"""Production page/count integration, cache invalidation, and full-data timings."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
previous = ROOT / 'benchmark_reports/2026-09-20_topic_drilldown/verify_backend.py'
scope = {'__file__': str(HERE / 'verify_backend.py')}
exec(compile(previous.read_text(encoding='utf-8').split("result = {'passed': len(checks)")[0], str(previous), 'exec'), scope)
ns, checks, check = scope['namespace'], scope['checks'], scope['check']
counts = scope['scope']['load']('semantic_filter_counts')
selector = scope['scope']['SELECTOR']
tree = ast.parse((selector / 'prompt_selector.py').read_text(encoding='utf-8'))
names = {'_library_page_payload', '_library_scope_rows', '_library_rows_for', '_build_library_rows',
         '_search_terms', '_rank_terms', '_library_state_reset', '_patch_derived_caches',
         '_cache_prompt_data', '_library_entry_in_view', '_library_view_locked'}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), str(selector / 'prompt_selector.py'), 'exec'), ns)
ns.update(build_filter_masks=counts.build_filter_masks, conditional_filter_counts=counts.conditional_filter_counts,
          row_mask=counts.row_mask, _LIBRARY_PAGE_SIZE=30, _LIBRARY_PAGE_SIZE_MAX=200,
          _LIBRARY_MATCH_CACHE_LIMIT=24, _lib_trace=lambda *a, **k: None,
          _prompt_data_signature=lambda: (1, 2), _projection_signature=lambda: (3, 4),
          collection_groups=lambda data: [{'id': 'default'}, {'id': 'group-a'}],
          prompt_collection=lambda prompt: prompt.get('collection', {}))
long_hair, short_hair, blue_eyes = (scope[n] for n in ('long_hair', 'short_hair', 'blue_eyes'))
page = ns['_library_page_payload']


def install(data):
    state = dict(version=((1, 2), (3, 4)), data=data, document={}, indexed=True,
                 entries={p['id']: p for c in data['categories'] for p in c['prompts']},
                 views={}, rows={}, ranges={}, matches={}, view_index={}, row_index={},
                 filter_masks={}, filter_scopes={}, index=None)
    ns['_LIBRARY_STATE'] = state
    ns['_reviewed_library_data'] = lambda pending=False: ns['_library_view_locked'](state, pending)
    return state


def record(identity, text, favorite=False, form='atomic_tag', usage='positive', pending=False):
    parents = ['头发与发型', '眼睛与瞳色']
    return {'id': identity, 'prompt': text, 'favorite': favorite,
            '_semantic': {'primary_class': 'appearance', 'subcategories': parents,
                          'refinements': scope['refinements'].extract_refinements(text, parents),
                          'count_markers': ['1girl'] if '1girl' in text else ['2girls'],
                          'content_type': form, 'declared_usage': usage,
                          'disposition': 'pending' if pending else 'classified',
                          'manual_search_eligible': not pending}}


fixture = {'last_modified': 'fixture-v1', 'categories': [
    {'id': 'a', 'name': 'source-a', 'prompts': [record('a1', '1girl, long hair, blue eyes', True),
        record('a2', '2girls, short hair', form='template'), record('a3', '1girl, long hair', pending=True)]},
    {'id': 'b', 'name': 'source-b', 'prompts': [record('b1', '1girl, long hair', True, usage='mixed'),
        record('b2', '2girls, short hair, blue eyes')]}
]}
fixture['categories'][0]['prompts'][0]['collection'] = {'groupIds': ['group-a']}
state = install(fixture)


def query(**kwargs):
    return page(kwargs.pop('category_id', ''), kwargs.pop('query', ''), 0, 30, include_filter_counts=True, **kwargs)


def assert_count(name, result, total, long, short, blue):
    actual = result['filter_counts']['detail']
    check(name, (result['total'], actual.get(long_hair, 0), actual.get(short_hair, 0), actual.get(blue_eyes, 0)) == (total, long, short, blue))


assert_count('counts_only_eligible_rows', query(), 4, 2, 2, 2)
assert_count('counts_text_scope', query(query='long hair'), 2, 2, 0, 1)
assert_count('counts_source_scope', query(category_id='a'), 2, 1, 1, 1)
assert_count('counts_favorites_scope', query(view='favorites'), 2, 2, 0, 1)
assert_count('counts_collection_scope', query(collection='group-a'), 1, 1, 0, 1)
assert_count('counts_usage_scope', query(usage='mixed'), 1, 1, 0, 0)
assert_count('counts_form_scope', query(content_type='template'), 1, 0, 1, 0)
assert_count('counts_review_scope', query(view='review'), 1, 1, 0, 0)
assert_count('counts_empty_query_scope', query(query='impossible-unique-query'), 0, 0, 0, 0)
assert_count('counts_sibling_any', query(pool_filters='detail:' + long_hair), 2, 2, 2, 1)
assert_count('counts_sibling_all', query(pool_filters='detail:' + long_hair, pool_mode='all'), 2, 2, 0, 1)
assert_count('counts_different_parents_and', query(pool_filters='detail:' + long_hair + ';detail:' + blue_eyes), 1, 1, 1, 1)
assert_count('counts_unknown_detail_fails_closed', query(pool_filters='detail:invalid'), 0, 0, 0, 0)
check('missing_source_has_explicit_empty_axes', all(query(category_id='missing')['filter_counts'][axis] == {} for axis in ('theme', 'subcategory', 'count', 'detail')))
check('counts_are_opt_in', 'filter_counts' not in page('', '', 0, 30))
index = ns['_library_index_payload']()
check('search_metadata_contains_original_tags', all(n['tags'] == scope['refinements'].REFINEMENT_NODES[n['id']]['tags'] for children in index['filter_pool']['refinements'].values() for n in children))
saved_masks = state['filter_masks'][False]
query(pool_filters='detail:' + short_hair)
check('pool_change_reuses_mask_and_nonpool_scope', state['filter_masks'][False] is saved_masks and len(state['filter_scopes']) < len(state['matches']))

# Exercise the actual cache update path without writing a production record.
entry_function = ns['_library_entry']
ns['_library_entry'] = lambda document, category, prompt: copy.deepcopy(prompt)
updated = copy.deepcopy(fixture)
updated['categories'][0]['prompts'][0]['favorite'] = False
ns['_cache_prompt_data'](updated, ['a1'])
check('favorite_update_invalidates_counts', not state['filter_masks'] and not state['filter_scopes'])
assert_count('favorite_update_recount', query(view='favorites'), 1, 1, 0, 0)
updated = copy.deepcopy(updated)
updated['categories'][0]['prompts'][0] = record('a1', '1girl, short hair, blue eyes')
ns['_cache_prompt_data'](updated, ['a1'])
assert_count('text_edit_recounts_details', query(), 4, 1, 3, 2)
updated = copy.deepcopy(updated)
updated['categories'][1]['prompts'].append(updated['categories'][0]['prompts'].pop(0))
ns['_cache_prompt_data'](updated, ['a1'])
check('source_move_invalidates_counts', not state['filter_masks'] and not state['filter_scopes'])
assert_count('source_move_recount', query(category_id='a'), 1, 0, 1, 0)
updated = copy.deepcopy(updated)
updated['categories'][1]['prompts'] = [p for p in updated['categories'][1]['prompts'] if p['id'] != 'b1']
ns['_cache_prompt_data'](updated, ['b1'])
assert_count('deletion_recount', query(), 3, 0, 3, 2)
ns['_cache_prompt_data'](updated)
check('document_replacement_clears_all_count_caches', not state['filter_masks'] and not state['filter_scopes'] and state['data'] is None)
ns['_library_entry'] = entry_function

result = {'checks': checks, 'passed': len(checks)}
if '--full' in sys.argv:
    started = time.monotonic()
    code_paths = [selector / n for n in ('prompt_selector.py', 'semantic_refinements.py', 'semantic_filter_counts.py', 'semantic_projection.py')]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    store = selector.parent / 'user_data/prompt_selector'
    data_path = Path(json.loads((HERE / 'parent_corrections_staged.json').read_bytes())['staged_path']) if '--staged' in sys.argv else store / 'data.json'
    data_bytes = data_path.read_bytes()
    data_hash = hashlib.sha256(data_bytes).hexdigest()
    data = json.loads(data_bytes)
    del data_bytes
    doc = scope['projection'].read_projection(store / 'semantic_projection.json')
    view = scope['projection'].project_library(data, doc)
    for category in view['categories']:
        for prompt in category['prompts']:
            sem = prompt['_semantic']
            sem['refinements'] = [] if sem.get('declared_usage', sem.get('usage')) == 'negative' else scope['refinements'].extract_refinements(prompt.get('prompt', ''), sem['subcategories'])
    state = install(view)
    t = time.monotonic()
    initial = query()
    cold = time.monotonic() - t
    expected = ns['_library_index_payload']()
    check('all_global_child_counts_equal_conditional_counts', all(initial['filter_counts']['detail'][n['id']] == n['count'] for children in expected['filter_pool']['refinements'].values() for n in children))
    cases = [dict(), dict(pool_filters='detail:' + long_hair), dict(pool_filters='detail:' + long_hair, pool_mode='all'),
             dict(pool_filters='detail:' + long_hair + ';detail:' + blue_eyes),
             dict(query='twintails', pool_filters='detail:' + long_hair), dict(view='favorites'),
             dict(usage='positive', content_type='atomic_tag'), dict(pool_filters='count:1girl;detail:' + long_hair)]
    outputs = []
    for kwargs in cases:
        t = time.monotonic()
        answer = query(**kwargs)
        elapsed = time.monotonic() - t
        t = time.monotonic()
        repeated = query(**kwargs)
        cached = time.monotonic() - t
        assert repeated == answer
        outputs.append({'params': kwargs, 'total': answer['total'], 'filter_counts': answer['filter_counts'],
                        'seconds': round(elapsed, 4), 'cached_seconds': round(cached, 4)})
    masks = state['filter_masks'][False]
    result['full_library'] = {'records': initial['total'], 'cold_page_and_index_seconds': round(cold, 3),
        'mask_count': len(masks['values']), 'mask_bytes': sum(sys.getsizeof(v) for v in masks['values'].values()),
        'seconds_including_projection': round(time.monotonic() - started, 3)}
    result['code_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    result['source_data_sha256'] = data_hash
    assert before == result['code_sha256'], 'Production code changed during full verification'
    (HERE / 'expected_index.json').write_text(json.dumps(expected, ensure_ascii=False), encoding='utf-8')
    (HERE / 'expected_count_queries.json').write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding='utf-8')
result['passed'] = len(checks)
(HERE / ('backend_linkage_full.json' if '--full' in sys.argv else 'backend_linkage.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
