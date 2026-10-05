"""Reusable, hash-bound release gate for the prompt-taxonomy engine.

Two independent gates, both computed from the deployed source in
ComfyUI/.../prompt_selector/:

  replay   - historical replay over every frozen round ledger: each recorded
             correction must still hold against the current engine
             (add/remove parents and refinements).
  contract - full-library count contract against the last verified release
             (.71 live verification). Every count must be strictly equal
             except for an explicitly declared, exactly-sized delta.

Read-only. Writes one receipt.
"""
import argparse
import ast
import hashlib
import importlib
import json
import re
import sys
import time
import types
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import strict_replay
ROOT = HERE.parents[1]
PROD = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector'
DATA = PROD / 'user_data/prompt_selector/data.json'
PROJECTION = DATA.with_name('semantic_projection.json')
SOURCES = PROD / 'prompt_selector'
FROZEN = ROOT / 'benchmark_reports/2026-09-20_consecutive_extension'
BASELINE = ROOT / 'benchmark_reports/2026-09-25_taxonomy_convergence/cycle_01/transaction_v3/attempt_001/live_verification_v3.json'
SOURCES_SHA = ('prompt_selector.py', 'semantic_projection.py',
               'semantic_refinements.py', 'semantic_taxonomy.py')


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_runtime():
    package = types.ModuleType('release_gate_runtime')
    package.__path__ = [str(SOURCES)]
    sys.modules[package.__name__] = package
    pmod = importlib.import_module(package.__name__ + '.semantic_projection')
    rmod = importlib.import_module(package.__name__ + '.semantic_refinements')
    tmod = importlib.import_module(package.__name__ + '.semantic_taxonomy')
    return pmod, rmod, tmod


def load_caller(pmod, tmod, rmod):
    """Extract the deployed ``_library_entry`` so the gate measures exactly what
    the service serves: stored subcategories, theme ids, the soft-light cue
    gate, and the negative-usage rule."""
    caller_path = SOURCES / 'prompt_selector.py'
    tree = ast.parse(caller_path.read_text(encoding='utf-8'), filename=str(caller_path))
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == '_library_entry')
    namespace = {
        'decision_for': pmod.decision_for,
        'selector_subcategories': pmod.selector_subcategories,
        'semantic_themes': tmod.semantic_themes,
        'extract_refinements': rmod.extract_refinements,
        'soft_light_modifier_cue_allowed': pmod.soft_light_modifier_cue_allowed,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(caller_path), 'exec'), namespace)
    return namespace['_library_entry']


def ledger_rows():
    rows = []
    for path in FROZEN.glob('round_*_ledger.jsonl'):
        match = re.search(r'round_(\d+)_', path.name)
        if not match:
            continue
        number = int(match.group(1))
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                rows.append((number, path.name, json.loads(line)))
    rows.sort(key=lambda item: (item[0], item[2].get('n') or 0))
    return rows


def run_replay(pmod, rmod, tmod, max_round=134, caller=None):
    return strict_replay.run_replay(sys.modules[__name__], pmod, rmod, tmod, max_round, caller)


def run_contract(pmod, rmod, tmod, declared_delta, caller=None, declared_parent=None,
                 declared_theme=None):
    """Count contract against the last verified release.

    ``declared_delta`` covers leaf (detail) changes. ``declared_parent`` covers
    parent (subcategory) changes and exists so that a reviewed parent-correction
    batch can pass the gate without weakening the zero-drift assertion that
    applies to every ordinary tag/rule batch.
    """
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    first = baseline['query_results'][0]
    base_detail = first['filter_counts']['detail']
    base_sub = first['filter_counts']['subcategory']
    base_theme = first['filter_counts']['theme']
    base_count = first['filter_counts']['count']
    payload = json.loads(DATA.read_bytes())
    whitelist = set(tmod.SUBCATEGORY_PARENTS)
    doc = pmod.read_projection(PROJECTION)
    detail, sub, theme, count = Counter(), Counter(), Counter(), Counter()
    total = 0
    for category in payload['categories']:
        for prompt in category.get('prompts', []):
            # The service indexes only records that carry a stored classification;
            # 4 of 323,680 records have none and are absent from the live index.
            if not isinstance(prompt.get('_classification'), dict):
                continue
            total += 1
            if caller is None:
                decision = pmod.decision_for(doc, category, prompt)
                parents = [p for p in pmod.selector_subcategories(decision, prompt) if p in whitelist]
                leaves = list(rmod.extract_refinements(prompt.get('prompt') or '', parents))
                themes = tmod.semantic_themes(decision)
            else:
                semantic = caller(doc, category, prompt)['_semantic']
                parents = [p for p in semantic['subcategories'] if p in whitelist]
                leaves = list(semantic['refinements'])
                themes = semantic.get('theme_ids') or sorted(tmod.semantic_themes(semantic))
            for parent in parents:
                sub[parent] += 1
            for leaf in leaves:
                detail[leaf] += 1
            for name_theme in themes:
                theme[name_theme] += 1
            for token in re.findall(r'\b\d+girls?\b|\b\d+boys?\b|\bsolo\b|\bno humans\b', (prompt.get('prompt') or '').lower()):
                count[token] += 1
    del payload
    deltas = {}
    for key, value in base_detail.items():
        current = detail.get(key, 0)
        if current != value:
            deltas[key] = {'baseline': value, 'current': current, 'diff': current - value}
    for key, value in detail.items():
        if key not in base_detail:
            deltas[key] = {'baseline': None, 'current': value, 'diff': value}
    declared_parent = declared_parent or {}
    sub_deltas = {k: {'baseline': v, 'current': sub.get(k, 0), 'diff': sub.get(k, 0) - v}
                  for k, v in base_sub.items() if sub.get(k, 0) != v}
    for k, v in sub.items():
        if k not in base_sub:
            sub_deltas[k] = {'baseline': None, 'current': v, 'diff': v}
    unexplained_parent = {k: v for k, v in sub_deltas.items()
                          if declared_parent.get(k) != v['diff']}
    theme_deltas = {k: {'baseline': v, 'current': theme.get(k, 0), 'diff': theme.get(k, 0) - v}
                    for k, v in base_theme.items() if theme.get(k, 0) != v}
    declared_theme = declared_theme or {}
    unexplained_theme = {k: v for k, v in theme_deltas.items()
                         if declared_theme.get(k) != v['diff']}
    expected = {key: value for key, value in declared_delta.items()}
    unexplained = {k: v for k, v in deltas.items() if expected.get(k) != v['diff']}
    declared_mismatches = {
        kind: {k: {'declared': v, 'actual': actual.get(k, {}).get('diff', 0)}
               for k, v in declared.items() if actual.get(k, {}).get('diff', 0) != v}
        for kind, declared, actual in (
            ('detail', expected, deltas), ('parent', declared_parent, sub_deltas),
            ('theme', declared_theme, theme_deltas))}
    return {
        'total_records': total,
        'baseline_total': first['total'],
        'total_matches': total == first['total'],
        'detail_deltas': deltas,
        'declared_delta': expected,
        'unexplained_detail_deltas': unexplained,
        'subcategory_deltas': sub_deltas,
        'declared_parent_delta': declared_parent,
        'unexplained_parent_deltas': unexplained_parent,
        'theme_deltas': theme_deltas,
        'declared_theme_delta': declared_theme,
        'unexplained_theme_deltas': unexplained_theme,
        'declared_mismatches': declared_mismatches,
        'passed': (total == first['total'] and not unexplained
                   and not unexplained_parent and not unexplained_theme
                   and not any(declared_mismatches.values())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gate', choices=('replay', 'contract', 'all'), default='all')
    parser.add_argument('--label', default='release_gate_S1')
    parser.add_argument('--source-dir', default=None,
                        help='Override module directory (default: deployed production source)')
    parser.add_argument('--data', default=None,
                        help='Override library data.json (default: deployed production library)')
    parser.add_argument('--projection', default=None,
                        help='Override semantic_projection.json (default: deployed projection)')
    parser.add_argument('--max-round', type=int, default=134,
                        help='Closed-history boundary; later rounds are pending work')
    parser.add_argument('--delta', default='part.shoulder=4474',
                        help='declared allowed detail delta, e.g. part.shoulder=4474')
    parser.add_argument('--parent-delta', default='',
                        help='declared allowed parent (subcategory) delta for a reviewed '
                             'parent-correction batch, e.g. 身体部位=711')
    parser.add_argument('--theme-delta', default='',
                        help='declared allowed theme delta for a reviewed parent-correction batch '
                             'whose added parents introduce a new owner theme, e.g. pose_action=1')
    args = parser.parse_args()
    declared = {}
    for item in args.delta.split(','):
        if '=' in item:
            key, value = item.split('=', 1)
            declared[key.strip()] = int(value)
    declared_parent = {}
    for item in (args.parent_delta or '').split(','):
        if '=' in item:
            key, value = item.split('=', 1)
            declared_parent[key.strip()] = int(value)
    declared_theme = {}
    for item in (args.theme_delta or '').split(','):
        if '=' in item:
            key, value = item.split('=', 1)
            declared_theme[key.strip()] = int(value)
    started = time.time()
    global SOURCES
    global DATA, PROJECTION
    if args.source_dir:
        SOURCES = Path(args.source_dir)
    if args.data:
        DATA = Path(args.data)
    if args.projection:
        PROJECTION = Path(args.projection)
    pmod, rmod, tmod = load_runtime()
    caller = load_caller(pmod, tmod, rmod)
    receipt = {
        'schema': 'taxonomy-release-gate/v1', 'label': args.label,
        'created_at': datetime.now(timezone.utc).astimezone().isoformat(),
        'source_sha256': {name: sha_file(SOURCES / name) for name in SOURCES_SHA},
        'data_path': str(DATA),
        'projection_path': str(PROJECTION),
        'projection_sha256': sha_file(PROJECTION),
        'data_sha256': sha_file(DATA),
    }
    if args.gate in ('replay', 'all'):
        receipt['replay'] = run_replay(pmod, rmod, tmod, args.max_round, caller)
    if args.gate in ('contract', 'all'):
        receipt['contract'] = run_contract(pmod, rmod, tmod, declared, caller, declared_parent,
                                           declared_theme)
    receipt['elapsed_seconds'] = round(time.time() - started, 1)
    replay_ok = receipt.get('replay', {}).get('failures', 0) == 0
    contract_ok = receipt.get('contract', {}).get('passed', True)
    receipt['passed'] = replay_ok and contract_ok
    (HERE / f'{args.label}.json').write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'passed': receipt['passed'],
        'replay': receipt.get('replay', {}).get('checks'),
        'replay_failures': receipt.get('replay', {}).get('failures'),
        'records_without_body': receipt.get('replay', {}).get('records_without_body'),
        'contract_passed': receipt.get('contract', {}).get('passed'),
        'detail_deltas': receipt.get('contract', {}).get('detail_deltas'),
        'subcategory_deltas': receipt.get('contract', {}).get('subcategory_deltas'),
        'theme_deltas': receipt.get('contract', {}).get('theme_deltas'),
        'unexplained_theme_deltas': receipt.get('contract', {}).get('unexplained_theme_deltas'),
        'elapsed': receipt['elapsed_seconds'],
    }, ensure_ascii=False, indent=2))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
