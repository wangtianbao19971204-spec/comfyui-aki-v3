"""Replay existing pool behavior, then exercise the new hierarchy on real data."""
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
old_suite = ROOT / 'benchmark_reports/2026-09-20_taxonomy_audit/verify_filter_pool.py'
source = old_suite.read_text(encoding='utf-8').split("result = {'checks': checks")[0]
source = source.replace("projection = load('semantic_projection')", "projection = load('semantic_projection')\nrefinements = load('semantic_refinements')")
source = source.replace("'Counter': Counter,", "'REFINEMENT_NODES': refinements.REFINEMENT_NODES, 'REFINEMENT_VERSION': refinements.REFINEMENT_VERSION, 'extract_refinements': refinements.extract_refinements, 'Counter': Counter,")
scope = {'__file__': str(HERE / 'verify_backend.py')}
exec(compile(source, str(old_suite), 'exec'), scope)
check, checks = scope['check'], scope['checks']
taxonomy, projection, refinements = (scope[name] for name in ('taxonomy', 'projection', 'refinements'))
namespace, hit, parse = (scope[name] for name in ('namespace', 'hit', 'parse'))
nodes = refinements.REFINEMENT_NODES
loaded_hashes = {name: hashlib.sha256((scope['SELECTOR'] / name).read_bytes()).hexdigest()
                 for name in ('prompt_selector.py', 'semantic_refinements.py')}


def by_tag(parent, tag):
    return next(identity for identity, node in nodes.items() if node['parent'] == parent and tag in node['tags'])


long_hair = by_tag('头发与发型', 'long hair')
short_hair = by_tag('头发与发型', 'short hair')
blue_eyes = by_tag('眼睛与瞳色', 'blue eyes')
parents = ['头发与发型', '眼睛与瞳色']
semantic = {'primary_class': 'appearance', 'subcategories': parents,
            'refinements': refinements.extract_refinements('1girl, long hair, blue eyes', parents)}
check('detail_parser_preserves_and_deduplicates', parse('detail:' + long_hair + ';detail:' + long_hair) == {'detail': [long_hair]})
check('child_can_be_selected_directly', hit(semantic, {'detail': [long_hair]}))
check('parent_without_child_keeps_broad_behavior', hit({**semantic, 'refinements': []}, {'sub': ['头发与发型']}))
check('parent_and_child_do_not_or_broaden', not hit(semantic, {'sub': ['头发与发型'], 'detail': [short_hair]}))
check('theme_and_child_do_not_or_broaden', not hit(semantic, {'theme': ['appearance'], 'detail': [short_hair]}))
check('sibling_children_any', hit(semantic, {'detail': [long_hair, short_hair]}, 'any'))
check('sibling_children_all', not hit(semantic, {'detail': [long_hair, short_hair]}, 'all'))
check('different_parent_children_both_required', hit(semantic, {'detail': [long_hair, blue_eyes]}, 'any'))
check('different_parent_children_not_or', not hit({**semantic, 'refinements': [long_hair]}, {'detail': [long_hair, blue_eyes]}, 'any'))
check('stale_child_requires_parent', not hit({**semantic, 'subcategories': []}, {'detail': [long_hair]}))
check('unknown_child_fails_closed', not hit(semantic, {'detail': ['nonexistent-node']}))
check('count_and_child_intersect', not hit(semantic, {'count': ['1girl'], 'detail': [long_hair]}))
check('nested_parent_path_matches', hit({**semantic, 'subcategories': ['头发与发型/自定义']}, {'detail': [long_hair]}))
check('nested_parent_path_extracts', long_hair in refinements.extract_refinements('long hair', ['头发与发型/自定义']))

category = {'id': 'edit-check', 'name': 'alias does not classify'}
prompt = {'id': 'edit-check', 'prompt': 'long hair', 'alias': 'short hair'}
decision = {'primary_class': 'appearance', 'subcategories': ['头发与发型'], 'taxonomy_version': '2026-09-20',
            'binding': projection.binding(category, prompt), 'disposition': 'classified',
            'manual_search_eligible': True, 'random_pool_eligible': False, 'strict_model_pool_eligible': False}
prompt['_classification'] = decision
entry = namespace['_library_entry']({}, category, prompt)
check('entry_uses_body_not_alias', long_hair in entry['_semantic']['refinements'] and short_hair not in entry['_semantic']['refinements'])
edited = {**prompt, 'prompt': 'short hair', '_classification': {**decision}}
edited['_classification']['binding'] = projection.binding(category, edited)
edited_entry = namespace['_library_entry']({}, category, edited)
check('edited_body_recomputes_children', short_hair in edited_entry['_semantic']['refinements'] and long_hair not in edited_entry['_semantic']['refinements'])
check('derived_details_not_written_to_source', 'refinements' not in prompt['_classification'] and '_semantic' not in prompt)
negative = {**prompt, '_classification': {**decision, 'declared_usage': 'negative'}}
check('negative_usage_has_no_positive_children', not namespace['_library_entry']({}, category, negative)['_semantic']['refinements'])

result = {'passed': len(checks), 'checks': checks}
if '--full' in sys.argv:
    started = time.monotonic()
    store = scope['SELECTOR'].parent / 'user_data/prompt_selector'
    data = json.loads((store / 'data.json').read_bytes())
    document = projection.read_projection(store / 'semantic_projection.json')
    view = projection.project_library(data, document)
    entries = []
    for category in view['categories']:
        for prompt in category['prompts']:
            semantic = prompt['_semantic']
            semantic['refinements'] = [] if semantic.get('declared_usage', semantic.get('usage')) == 'negative' else refinements.extract_refinements(prompt.get('prompt', ''), semantic['subcategories'])
            entries.append(prompt)
    index = scope['index_for'](view)
    pool = index['filter_pool']
    detail_counts = scope['Counter'](identity for p in entries for identity in set(p['_semantic']['refinements']))
    for parent, children in pool['refinements'].items():
        for child in children:
            assert child['parent'] == parent
            assert child['owner'] == taxonomy.SUBCATEGORY_PARENTS[parent]
            assert child['count'] == detail_counts[child['id']]
            assert child['count'] <= pool['subcategory'][child['owner']][parent]
    for prompt in entries:
        semantic = prompt['_semantic']
        for identity in semantic['refinements']:
            assert nodes[identity]['parent'] in semantic['subcategories'], prompt['id']
    old_index = json.loads((ROOT / 'benchmark_reports/2026-09-20_taxonomy_audit/pool_index_verified.json').read_bytes())
    for name in ('theme', 'subcategory', 'count', 'subcategory_values', 'conflicting_subcategories'):
        assert pool[name] == old_index['filter_pool'][name], name
    cases = [
        ('sub:头发与发型', 'any', lambda s: '头发与发型' in s['subcategories']),
        ('detail:' + long_hair, 'any', lambda s: long_hair in s['refinements']),
        ('detail:' + short_hair, 'any', lambda s: short_hair in s['refinements']),
        ('sub:头发与发型;detail:' + long_hair, 'any', lambda s: long_hair in s['refinements']),
        ('detail:' + long_hair + ';detail:' + short_hair, 'any', lambda s: bool({long_hair, short_hair}.intersection(s['refinements']))),
        ('detail:' + long_hair + ';detail:' + short_hair, 'all', lambda s: {long_hair, short_hair}.issubset(s['refinements'])),
        ('detail:' + long_hair + ';detail:' + blue_eyes, 'any', lambda s: {long_hair, blue_eyes}.issubset(s['refinements'])),
        ('theme:appearance;detail:' + long_hair, 'any', lambda s: long_hair in s['refinements']),
        ('count:1girl;detail:' + long_hair, 'any', lambda s: long_hair in s['refinements'] and '1girl' in s.get('count_markers', [])),
        ('sub:裙装与礼服;detail:' + long_hair, 'any', lambda s: long_hair in s['refinements'] and '裙装与礼服' in s['subcategories']),
        ('detail:nonexistent-node', 'any', lambda s: False),
    ]
    results = []
    for filters, mode, predicate in cases:
        expected = sum(predicate(p['_semantic']) for p in entries)
        parsed = parse(filters)
        actual = sum(hit(p['_semantic'], parsed, mode) for p in entries)
        assert actual == expected, (filters, mode, expected, actual)
        results.append({'filters': filters, 'mode': mode, 'expected': expected})
    (HERE / 'expected_index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (HERE / 'expected_queries.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    result['full_library'] = {'records': len(entries), 'parent_topics': sum(len(v) for v in pool['subcategory'].values()),
        'registered_children': len(nodes), 'populated_children': len(detail_counts),
        'visible_children': sum(n >= 10 for n in detail_counts.values()),
        'expandable_parents': sum(any(c['count'] >= 10 for c in children) for children in pool['refinements'].values()),
        'records_with_children': sum(bool(p['_semantic']['refinements']) for p in entries),
        'unchanged_existing_pool': True, 'queries_verified': len(results), 'elapsed_seconds': round(time.monotonic()-started, 2)}
result['code_sha256'] = {name: hashlib.sha256((scope['SELECTOR'] / name).read_bytes()).hexdigest()
                         for name in ('prompt_selector.py', 'semantic_refinements.py')}
assert result['code_sha256'] == loaded_hashes, 'Code changed during verification; rerun against the completed revision'
destination = HERE / ('backend_full_verification.json' if '--full' in sys.argv else 'backend_verification.json')
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
