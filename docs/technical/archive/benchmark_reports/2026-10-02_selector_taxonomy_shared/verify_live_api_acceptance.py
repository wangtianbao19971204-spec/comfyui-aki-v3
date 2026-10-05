"""Read-only post-restart API acceptance, bound to exact pre-release counts and IDs."""
import ast
import gzip
import hashlib
import importlib.util
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLUGIN = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
BACKEND = PLUGIN / 'modules/comfyui-anima-tools/nodes.py'
SHARED_JS = PLUGIN / 'modules/comfyui-anima-tools/js/anima_shared_prompt_data.js'
KINDS = ('character', 'artist', 'clothing', 'pose', 'background', 'style_quality')
SNAPSHOTS = HERE / 'live_api_snapshots'
BEFORE = json.loads((HERE / 'live_before.json').read_text(encoding='utf-8'))
RESTART = json.loads((HERE / 'restart_receipt.json').read_text(encoding='utf-8'))
calls, checks = [], []


def sha(body):
    return hashlib.sha256(body).hexdigest()


def check(name, condition):
    assert condition, name
    checks.append(name)


def http(route, payload=None, snapshot=None, timeout=45):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = Request('http://127.0.0.1:8188' + route, data=body,
                      headers={'Accept-Encoding': 'gzip', 'Cache-Control': 'no-cache',
                               **({'Content-Type': 'application/json'} if body is not None else {})})
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        decoded = gzip.decompress(raw) if response.headers.get('Content-Encoding') == 'gzip' else raw
        status = response.status
    if snapshot:
        SNAPSHOTS.mkdir(exist_ok=True)
        (SNAPSHOTS / snapshot).write_bytes(decoded)
    data = json.loads(decoded)
    calls.append({'route': route, 'method': 'GET' if payload is None else 'POST', 'status': status,
                  'elapsed_seconds': round(time.perf_counter() - started, 4), 'wire_bytes': len(raw),
                  'decoded_bytes': len(decoded), 'response_sha256': sha(decoded),
                  **({'snapshot': str(SNAPSHOTS / snapshot)} if snapshot else {})})
    return data


def canonical_tree(items, index):
    theme_ids, child_ids = defaultdict(set), defaultdict(lambda: defaultdict(set))
    labels = index['semantic_classes']
    subcategories = index['filter_pool']['subcategory']
    for item in items:
        semantic = item['_semantic']
        for theme in semantic['theme_ids']:
            if theme in labels:
                theme_ids[theme].add(item['id'])
        for owner, vocabulary in subcategories.items():
            for parent in vocabulary:
                if any((child == parent or child.startswith(parent + '/'))
                       and semantic['subcategory_owners'].get(child) == owner
                       for child in semantic['subcategories']):
                    theme_ids[owner].add(item['id'])
                    child_ids[owner][parent].add(item['id'])
    values = index['filter_pool'].get('subcategory_values', {})
    return [{'key': 'shared-theme:' + theme, 'label': label, 'count': len(theme_ids[theme]),
             'children': [{'key': 'shared-sub:' + values.get(child, child), 'label': child,
                           'count': len(ids), 'owner': theme} for child, ids in child_ids[theme].items()]}
            for theme, label in labels.items() if theme_ids[theme]]


def independent_filter(item, filters, index):
    semantic = item['_semantic']
    groups = defaultdict(list)
    for value in filters:
        if value.startswith('shared-theme:'):
            groups['theme'].append(value[len('shared-theme:'):] in semantic['theme_ids'])
        elif value.startswith('shared-source:'):
            groups['source'].append(value[len('shared-source:'):] == item['source_category_id'])
        elif value.startswith('shared-sub:'):
            identity = value[len('shared-sub:'):]
            owner, separator, child = identity.partition('::')
            if not separator:
                child = identity
                owner = next((owner for owner, children in index['filter_pool']['subcategory'].items()
                              if child in children), child)
            groups['sub:' + owner].append(any((label == child or label.startswith(child + '/'))
                and (not separator or semantic['subcategory_owners'].get(label) == owner)
                for label in semantic['subcategories']))
        else:
            raise AssertionError('Unexpected independent-oracle key: ' + value)
    return all(any(hits) for hits in groups.values())


receipt = {'started_at': datetime.now(timezone(timedelta(hours=8))).isoformat(), 'passed': False,
           'baseline_sha256': sha((HERE / 'live_before.json').read_bytes()),
           'nodes_sha256': sha(BACKEND.read_bytes()), 'shared_js_sha256': sha(SHARED_JS.read_bytes()),
           'checks': checks, 'calls': calls, 'production_writes': 0, 'formal_data_writes': 0,
           'queue_writes': 0, 'workflow_writes': 0, 'browser_actions': 0, 'service_restarts': 0}
try:
    print('PHASE waiting_for_ready', flush=True)
    status = None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            status = http('/unified-workbench/status', timeout=5)
            if len(status['modules']) == 5 and all(module['ready'] for module in status['modules']):
                break
        except Exception:
            pass
        time.sleep(2)
    check('five_modules_ready', status is not None and len(status['modules']) == 5
          and all(module['ready'] for module in status['modules']))
    check('seventy_six_nodes_ready', status['nodes'] == 76)
    listeners = sorted({connection.pid for connection in psutil.net_connections(kind='tcp')
                        if connection.status == psutil.CONN_LISTEN and connection.laddr.port == 8188})
    check('controlled_restart_listener_owner', listeners == [RESTART['new_pid']])
    queue = http('/queue')
    check('queue_empty_before', not queue['queue_running'] and not queue['queue_pending'])
    receipt['service'] = {'listener_pids': listeners, 'modules': status['modules'], 'nodes': status['nodes']}
    print('PHASE canonical_index', flush=True)
    index = http('/prompt_selector/library/index', snapshot='library_index.json')
    check('index_class_labels_current', index['semantic_classes'] == json.loads(
        (HERE / 'library_index_body.json').read_bytes())['semantic_classes'])
    taxonomy_path = PLUGIN / 'modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector/semantic_taxonomy.py'
    spec = importlib.util.spec_from_file_location('_live_api_canonical_taxonomy', taxonomy_path)
    taxonomy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(taxonomy)
    receipt['taxonomy_helper_sha256'] = sha(taxonomy_path.read_bytes())
    indices, snapshots, trees = {}, {}, {}
    for kind in KINDS:
        print('PHASE kind_index ' + kind, flush=True)
        payload = http('/anima-tools/shared-prompts?kind=' + kind + '&index=1', snapshot=kind + '_index.json')
        check(kind + '_enabled', payload['enabled'] is True)
        ids = [item['id'] for item in payload['items']]
        ordered_sha = sha(json.dumps(ids).encode())
        check(kind + '_count_unchanged', len(ids) == BEFORE['kind_indices'][kind]['count'])
        check(kind + '_ordered_ids_unchanged', ordered_sha == BEFORE['kind_indices'][kind]['ordered_ids_sha256'])
        check(kind + '_ids_unique', len(ids) == len(set(ids)))
        check(kind + '_source_sha_unchanged', payload['source_sha256'] == BEFORE['kind_indices'][kind]['source_sha256'])
        check(kind + '_taxonomy_schema_v2', payload['taxonomy_version'] == 'shared-selector-library-v2')
        field_failures = []
        for item in payload['items']:
            semantic = item['_semantic']
            if (semantic.get('theme_ids') != sorted(taxonomy.semantic_themes(semantic))
                    or semantic.get('subcategory_owners') != {child: taxonomy.subcategory_owner(semantic, child)
                        for child in semantic.get('subcategories', []) if taxonomy.subcategory_owner(semantic, child)}
                    or not item.get('source_category_id') or not item.get('source_category')
                    or semantic.get('disposition') not in ('reviewed', 'classified')
                    or semantic.get('manual_search_eligible') is not True or semantic.get('usage') != 'positive'
                    or semantic.get('content_type') not in ('fragment', 'atomic_tag')):
                field_failures.append(item['id'])
        check(kind + '_canonical_fields_and_eligibility', not field_failures)
        tree = canonical_tree(payload['items'], index)
        check(kind + '_canonical_tree_owners_and_keys', all(node['label'] == index['semantic_classes'][node['key'].split(':', 1)[1]]
            and all(child['owner'] == node['key'].split(':', 1)[1]
                    and child['label'] in index['filter_pool']['subcategory'][child['owner']]
                    for child in node['children']) for node in tree))
        indices[kind] = {'count': len(ids), 'ordered_ids_sha256': ordered_sha,
                         'source_sha256': payload['source_sha256'], 'revision': payload['revision'],
                         'taxonomy_version': payload['taxonomy_version'],
                         'canonical_tree': tree, 'source_options': payload['source_options']}
        if kind == 'artist':
            snapshots[kind] = payload
        print(json.dumps({'kind': kind, 'count': len(ids), 'canonical_fields': 'PASS'}, ensure_ascii=False), flush=True)
    receipt['kind_indices'] = indices

    print('PHASE artist_semantic_source_pages', flush=True)
    artist = snapshots['artist']
    items = artist['items']
    metadata = http('/anima-tools/artist-page', {'revision': artist['revision'], 'include_tree': True,
                                               'sort': 'name-asc', 'offset': 0, 'limit': 60}, snapshot='artist_page_initial.json')
    check('artist_initial_page_sixty', len(metadata['items']) == 60)
    check('artist_initial_total_unchanged', metadata['total'] == len(items))
    check('artist_source_options_equal_index', metadata['source_options'] == artist['source_options'])
    expected_sources = defaultdict(set)
    for item in items:
        expected_sources[item['source_category_id']].add(item['id'])
    check('artist_source_counts_exact_ids', {entry['id']: entry['count'] for entry in metadata['source_options']} ==
          {identity: len(ids) for identity, ids in expected_sources.items()})
    rendered_tree = []
    clipped = []
    values = index['filter_pool'].get('subcategory_values', {})
    for theme, label in index['semantic_classes'].items():
        root = next((node for node in metadata['tree'] if node['key'] == 'shared-theme:' + theme), None)
        if root is None:
            continue
        check('artist_theme_label_' + theme, root['label'] == label and root['name'] == label)
        inventory = index['filter_pool']['subcategory'].get(theme, {})
        children = []
        for child in root['children']:
            if child['name'] not in inventory:
                clipped.append({'owner': theme, 'label': child['name'], 'key': child['key']})
                continue
            children.append({'key': 'shared-sub:' + values.get(child['name'], child['name']),
                             'label': child['name'], 'count': child['count'], 'owner': theme})
        rendered_tree.append({'key': root['key'], 'label': label, 'count': root['count'], 'children': children})
    normalize = lambda tree: [(node['key'], node['label'], node['count'], sorted(
        (child['key'], child['label'], child['count'], child['owner']) for child in node['children'])) for node in tree]
    check('artist_server_tree_after_inventory_clip_matches_independent_snapshot', normalize(rendered_tree) == normalize(indices['artist']['canonical_tree']))
    receipt['artist_tree_clipped_metadata'] = clipped
    source = max(metadata['source_options'], key=lambda entry: entry['count'])
    filters = ['shared-theme:artist_style', 'shared-source:' + source['id']]
    expected = [item for item in items if independent_filter(item, filters, index)]
    expected.sort(key=lambda item: str(item.get('name') or '').casefold())
    check('artist_test_source_has_two_pages', len(expected) > 60)
    wire_filter = 'shared-filters:' + json.dumps(filters, ensure_ascii=False)
    query = {'revision': artist['revision'], 'filter': wire_filter, 'sort': 'name-asc', 'offset': 0, 'limit': 60}
    first = http('/anima-tools/artist-page', query, snapshot='artist_filtered_page1.json')
    second = http('/anima-tools/artist-page', {**query, 'offset': 60}, snapshot='artist_filtered_page2.json')
    check('artist_semantic_source_total_matches_snapshot', first['total'] == second['total'] == len(expected))
    check('artist_semantic_source_page1_exact', [item['id'] for item in first['items']] == [item['id'] for item in expected[:60]])
    check('artist_semantic_source_page2_exact', [item['id'] for item in second['items']] == [item['id'] for item in expected[60:120]])
    check('artist_pages_sixty_and_no_duplicates', len(first['items']) == 60 and len(second['items']) == 60
          and not {item['id'] for item in first['items']}.intersection(item['id'] for item in second['items']))
    check('artist_filtered_source_and_theme_on_full_cards', all(item['source_category_id'] == source['id']
          and 'artist_style' in item['_semantic']['theme_ids'] for item in first['items'] + second['items']))
    receipt['artist_filter_acceptance'] = {'filters': filters, 'expected_total': len(expected),
        'page1': len(first['items']), 'page2': len(second['items']), 'sort': 'name-asc',
        'selected_source': source, 'oracle': 'Independent grouped predicate over complete artist index snapshot.'}
    queue = http('/queue')
    check('queue_empty_after', not queue['queue_running'] and not queue['queue_pending'])
    formal_mismatches = [path for path, expected in BEFORE['formal_files'].items() if sha(Path(path).read_bytes()) != expected]
    check('eighteen_workflows_and_three_formal_data_files_unchanged', not formal_mismatches)
    check('nodes_source_unchanged_during_acceptance', sha(BACKEND.read_bytes()) == receipt['nodes_sha256'])
    check('shared_source_unchanged_during_acceptance', sha(SHARED_JS.read_bytes()) == receipt['shared_js_sha256'])
    receipt['formal_files_unchanged'] = len(BEFORE['formal_files'])
    receipt['queue'] = {'running': 0, 'pending': 0}
    receipt['passed'] = True
except Exception as error:
    receipt['error'] = str(error)
    raise
finally:
    receipt['finished_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    receipt['check_count'] = len(checks)
    receipt['limits'] = ['Read-only API and canonical-field acceptance only; browser visuals and prompt insertion are not verified here.',
                         'Canonical trees for all six kinds are independently projected from current live index and complete kind snapshots; artist additionally checks its real server tree after renderer inventory clipping.',
                         'HTTP elapsed times are observations for this run, not a complete frontend, CPU, memory or GPU performance certification.']
    (HERE / 'live_api_acceptance.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': receipt['passed'], 'checks': len(checks), 'error': receipt.get('error'),
                      'receipt': str(HERE / 'live_api_acceptance.json')}, ensure_ascii=False), flush=True)
