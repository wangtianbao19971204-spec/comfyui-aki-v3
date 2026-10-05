"""Independent query contract for the *currently deployed* source.

The .71 receipt (reviewer_backend_v3/g6_20260925_003_query_contract.json) is
bound to the .71 source hashes and refuses to rerun. This script reruns the same
contract on whatever source is deployed now:

  * the 73 fixture checks from the frozen harness chain, plus the global
    child-count equality check (74 named checks);
  * the same 13 deterministic page-query cases, each executed twice for
    determinism, with complete filter counts recorded;
  * the rebuild cross-check, strengthened: the offline, source-faithful index
    rebuild must equal the *live service* index byte-for-byte after parsing.

Read-only with respect to production.
"""
import argparse
import ast
import hashlib
import importlib
import json
import sys
import time
import types
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REVIEWER = ROOT / 'benchmark_reports/2026-09-25_taxonomy_convergence/reviewer_backend_v3'
GENERATOR = REVIEWER / 'verify_g6.py'
CYCLE = ROOT / 'benchmark_reports/2026-09-25_taxonomy_convergence/cycle_01'
MANIFEST = CYCLE / 'approved_operations_v3_62c043b86a69_2a35469cd744.json'
PROD = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector'
DATA = PROD.parent / 'user_data/prompt_selector/data.json'
PROJECTION = PROD.parent / 'user_data/prompt_selector/semantic_projection.json'
BASE = 'http://127.0.0.1:8188'
SOURCE_FILES = ('prompt_selector.py', 'semantic_projection.py',
                'semantic_refinements.py', 'semantic_taxonomy.py')


def stamp():
    return datetime.now(timezone.utc).astimezone().isoformat()


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def value_shape(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'type': type(value).__name__,
            'length': len(value) if isinstance(value, (dict, list, str)) else None,
            'canonical_sha256': hashlib.sha256(raw).hexdigest()}


def compare(rebuilt, live, paths, path=''):
    if len(paths) >= 200:
        return
    if isinstance(rebuilt, dict) and isinstance(live, dict):
        for key in sorted(set(rebuilt) | set(live)):
            if key not in rebuilt or key not in live:
                paths.append({'path': f'{path}/{key}', 'live': value_shape(live.get(key)),
                              'rebuilt': value_shape(rebuilt.get(key))})
            elif rebuilt[key] != live[key]:
                compare(rebuilt[key], live[key], paths, f'{path}/{key}')
    elif isinstance(rebuilt, list) and isinstance(live, list):
        if len(rebuilt) != len(live):
            paths.append({'path': f'{path}/@length', 'live': value_shape(live),
                          'rebuilt': value_shape(rebuilt)})
        for index, (left, right) in enumerate(zip(rebuilt, live)):
            if left != right:
                compare(left, right, paths, f'{path}/{index}')
    else:
        paths.append({'path': path, 'live': value_shape(live), 'rebuilt': value_shape(rebuilt)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='g6_current_source_query_contract_001')
    args = parser.parse_args()

    live_raw = None
    with urllib.request.urlopen(BASE + '/prompt_selector/library/index', timeout=240) as response:
        live_raw = response.read()
    live = json.loads(live_raw)
    with urllib.request.urlopen(BASE + '/prompt_selector/library/revision', timeout=60) as response:
        revision = json.loads(response.read())

    # Extract the frozen harness factory and run it against the deployed source.
    tree = ast.parse(GENERATOR.read_text(encoding='utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'run_73_fixture')
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            node.value.keys.append(ast.Constant('harness'))
            node.value.values.append(ast.Name('ns', ast.Load()))
    ast.fix_missing_locations(function)
    helper = {'Path': Path, 'ROOT': ROOT, 'CAND': PROD, 'prod': PROD, 'sha': sha_file,
              'types': types, 'importlib': importlib, 'sys': sys}
    exec(compile(ast.Module([function], type_ignores=[]), str(GENERATOR), 'exec'), helper)
    fixture = helper['run_73_fixture'](PROD)
    harness = fixture['harness']
    namespace = harness['ns']
    scope = harness['scope']
    checks = list(fixture['checks'])

    library = scope['scope']['load']('selector_library')
    namespace.update(COLLECTION_KINDS=library.COLLECTION_KINDS, CLASS_ROUTES=library.CLASS_ROUTES,
                     collection_groups=library.collection_groups,
                     prompt_collection=library.prompt_collection)
    projection = scope['projection']
    refinements = scope['refinements']
    data = json.loads(DATA.read_bytes())
    document = projection.read_projection(PROJECTION)
    entry = namespace['_library_entry']
    assert entry.__code__.co_filename == str(PROD / 'prompt_selector.py')

    started = time.monotonic()
    counts = {}
    view = {**data, 'categories': [], '_semantic_class_labels': {**projection.CLASS_LABELS}}
    for category in data.get('categories', []):
        prompts = []
        for prompt in category.get('prompts', []):
            decision = projection.decision_for(document, category, prompt)
            disposition = decision.get('disposition', '?')
            counts[disposition] = counts.get(disposition, 0) + 1
            if disposition in ('reviewed', 'classified') and decision.get('manual_search_eligible'):
                prompts.append(entry(document, category, prompt))
        view['categories'].append({**category, 'prompts': prompts})
    view['_review_counts'] = counts
    installed = harness['install'](view)
    installed['views'][False] = view
    installed['index'] = None
    namespace['_reviewed_library_data'] = (lambda pending=False: view if not pending
                                           else namespace['_library_view_locked'](installed, pending))
    query = harness['query']
    initial = query()
    rebuilt = namespace['_library_index_payload']()
    elapsed = round(time.monotonic() - started, 2)

    mismatches = []
    compare(rebuilt, live, mismatches)
    rebuild_matches_live = not mismatches
    # Stricter than the .71 contract, which compared against a saved candidate
    # index: the source-faithful rebuild must equal what the service serves now.
    checks.append('source_faithful_rebuild_matches_live_index')

    detail_counts = initial['filter_counts']['detail']
    global_child_counts_equal = all(
        detail_counts.get(node['id'], 0) == node['count']
        for children in rebuilt['filter_pool']['refinements'].values() for node in children)
    checks.append('all_global_child_counts_equal_conditional_counts')

    hair_long = next(identity for identity, node in refinements.REFINEMENT_NODES.items()
                     if node.get('parent') == '头发与发型' and 'long hair' in node.get('tags', []))
    blue_eyes = next(identity for identity, node in refinements.REFINEMENT_NODES.items()
                     if node.get('parent') == '眼睛与瞳色' and 'blue eyes' in node.get('tags', []))
    soft_id = 'light_effect.soft'
    soft_parent = refinements.REFINEMENT_NODES[soft_id]['parent']
    operations = json.loads(MANIFEST.read_text(encoding='utf-8'))['operations']
    source_id = operations[0]['category_id']
    general = [{}, {'pool_filters': 'detail:' + hair_long},
               {'pool_filters': 'detail:' + hair_long, 'pool_mode': 'all'},
               {'pool_filters': 'detail:' + hair_long + ';detail:' + blue_eyes},
               {'query': 'twintails', 'pool_filters': 'detail:' + hair_long}, {'view': 'favorites'},
               {'usage': 'positive', 'content_type': 'atomic_tag'},
               {'pool_filters': 'count:1girl;detail:' + hair_long}]
    targeted = [{'pool_filters': 'sub:' + soft_parent}, {'pool_filters': 'detail:' + soft_id},
                {'pool_filters': 'detail:' + soft_id + ';detail:' + hair_long},
                {'category_id': source_id, 'pool_filters': 'detail:' + soft_id},
                {'category_id': source_id,
                 'pool_filters': 'sub:' + soft_parent + ';detail:' + soft_id}]
    query_results = []
    for params in general + targeted:
        first = query(**params)
        second = query(**params)
        deterministic = first == second
        query_results.append({'params': params, 'total': first['total'],
                              'filter_counts': first['filter_counts'],
                              'deterministic': deterministic})
    determinism_ok = all(item['deterministic'] for item in query_results)

    receipt = {
        'schema': 'independent-g6-query-contract/v1',
        'generation': args.label,
        'created_at': stamp(),
        'contract_target': 'currently deployed source (not the frozen .71 candidate)',
        'source_sha256': {name: sha_file(PROD / name) for name in SOURCE_FILES},
        'data_sha256': sha_file(DATA),
        'projection_sha256': sha_file(PROJECTION),
        'live': {'library_revision': revision, 'library_index_sha256': hashlib.sha256(live_raw).hexdigest(),
                 'library_index_bytes': len(live_raw)},
        'library': {'raw_records': sum(len(category.get('prompts', [])) for category in data['categories']),
                    'indexed_records': initial['total'], 'dispositions': counts,
                    'elapsed_seconds': elapsed},
        'checks': checks,
        'named_checks': len(checks),
        'legacy_fixture_count': fixture['count'],
        'harness_sha256': fixture['harness_sha256'],
        'query_case_count': len(query_results),
        'query_cases': query_results,
        'query_cases_deterministic': determinism_ok,
        'all_global_child_counts_equal': global_child_counts_equal,
        'rebuild_matches_live_index': rebuild_matches_live,
        'rebuild_mismatches': mismatches,
        'dynamic_nodes': {'hair_long': hair_long, 'blue_eyes': blue_eyes,
                          'soft_id': soft_id, 'soft_parent': soft_parent,
                          'category_id_used': source_id},
        'production_mutated': False,
    }
    receipt['passed'] = bool(fixture['count'] == 73 and determinism_ok
                             and global_child_counts_equal and rebuild_matches_live)
    out = HERE / f'{args.label}.json'
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'label': args.label, 'passed': receipt['passed'],
                      'named_checks': receipt['named_checks'],
                      'legacy_fixture_count': receipt['legacy_fixture_count'],
                      'query_case_count': receipt['query_case_count'],
                      'query_cases_deterministic': determinism_ok,
                      'all_global_child_counts_equal': global_child_counts_equal,
                      'rebuild_matches_live_index': rebuild_matches_live,
                      'rebuild_mismatch_count': len(mismatches),
                      'indexed_records': initial['total']},
                     ensure_ascii=False, indent=2))
    return 0 if receipt['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
