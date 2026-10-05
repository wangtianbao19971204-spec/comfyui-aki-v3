"""Exercise production pool functions without importing the ComfyUI server."""
import ast
from array import array
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import threading
import types

ROOT = Path(__file__).resolve().parents[2]
SELECTOR = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector'
package = types.ModuleType('pool_verification')
package.__path__ = [str(SELECTOR)]
sys.modules[package.__name__] = package


def load(name):
    spec = importlib.util.spec_from_file_location('pool_verification.' + name, SELECTOR / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


taxonomy = load('semantic_taxonomy')
projection = load('semantic_projection')
namespace = {
    'Counter': Counter, 'array': array, 'CLASS_LABELS': taxonomy.CLASS_LABELS,
    'FACET_CLASS_MAP': taxonomy.FACET_CLASS_MAP,
    'SUBCATEGORY_PARENTS': taxonomy.SUBCATEGORY_PARENTS,
    'semantic_themes': taxonomy.semantic_themes,
    'subcategory_owner': taxonomy.subcategory_owner,
    'selector_subcategories': projection.selector_subcategories,
    'decision_for': projection.decision_for,
    '_PROMPT_FILE_LOCK': threading.RLock(), '_PROMPT_CACHE_LOCK': threading.RLock(),
    'COLLECTION_KINDS': [], 'CLASS_ROUTES': {}, 'collection_groups': lambda data: [],
}
names = {'parse_pool_filters', 'pool_filter_hit', '_library_entry', '_library_index_payload', '_library_matches'}
tree = ast.parse((SELECTOR / 'prompt_selector.py').read_text(encoding='utf-8'))
exec(compile(ast.Module([node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[]), str(SELECTOR / 'prompt_selector.py'), 'exec'), namespace)
parse = namespace['parse_pool_filters']
hit = namespace['pool_filter_hit']
checks = []


def check(name, value):
    assert value, name
    checks.append(name)


def index_for(data):
    namespace['_reviewed_library_data'] = lambda: data
    namespace['_LIBRARY_STATE'] = {'index': None, 'views': {False: data}}
    return namespace['_library_index_payload']()


semantic = {
    'primary_class': 'appearance', 'alternative_classes': ['clothing_accessory'],
    'themes': ['composition', 'count'], 'count_markers': ['1girl'],
    'subcategories': ['坐姿与蹲姿', '裙装与礼服'],
}
check('raw_filter_parser_deduplicates', parse('sub:坐姿与蹲姿;subcategory:坐姿与蹲姿;count:1girl') == {'sub': ['坐姿与蹲姿'], 'count': ['1girl']})
check('facet_is_major_theme', hit(semantic, {'theme': ['composition_camera']}))
check('count_is_major_theme', hit(semantic, {'theme': ['person_count']}))
check('leaf_owner_is_major_theme', hit(semantic, {'theme': ['pose_action']}))
check('legacy_facet_uses_same_topic', hit(semantic, {'facet': ['pose']}))
check('same_owner_or', hit(semantic, {'sub': ['坐姿与蹲姿', '移动与运动']}))
check('same_owner_all', not hit(semantic, {'sub': ['坐姿与蹲姿', '移动与运动']}, 'all'))
check('different_owners_require_both', not hit(semantic, {'sub': ['坐姿与蹲姿', '上衣与外套']}))
check('different_owners_match', hit(semantic, {'sub': ['坐姿与蹲姿', '裙装与礼服']}))
check('count_and_leaf_require_both', not hit(semantic, {'sub': ['坐姿与蹲姿'], 'count': ['2girls']}))
check('stale_theme_ids_cannot_widen_match', not hit({**semantic, 'theme_ids': ['artist_style']}, {'theme': ['artist_style']}))
check('legacy_style_quality_alias', hit({'primary_class': 'style_medium'}, {'theme': ['style_quality']}))
fixture = {'categories': [{'id': 'fixture', 'prompts': [
    {'id': '1', '_semantic': semantic},
    {'id': '2', '_semantic': {'primary_class': 'appearance', 'subcategories': ['坐姿与蹲姿', 'unknown-small-leaf']}},
]}], '_semantic_class_labels': taxonomy.CLASS_LABELS, '_review_counts': {'classified': 2}}
pool = index_for(fixture)['filter_pool']
check('stable_owner_even_when_primary_differs', pool['subcategory']['pose_action']['坐姿与蹲姿'] == 2)
check('unknown_leaf_omitted_and_reported', pool['unmapped_subcategories'] == {'unknown-small-leaf': 1} and all('unknown-small-leaf' not in values for values in pool['subcategory'].values()))
check('theme_count_covers_leaf_reference', pool['theme']['pose_action'] == 2)
check('count_topic_and_marker_agree', pool['theme']['person_count'] == pool['count']['1girl'] == 1)
rows = [(prompt, 'fixture', 'fixture', 'fixture', [], '') for prompt in fixture['categories'][0]['prompts']]
match = namespace['_library_matches']
check('legacy_theme_parameter_matches_count_topic', list(match({}, rows, None, '', 'person_count', {'person_count'}, '', '', '', '', '')) == [0])
check('leaf_can_be_selected_without_theme', list(match({}, rows, None, '', '', set(), '', '', '', '', '', {'sub': ['坐姿与蹲姿']})) == [0, 1])
check('theme_and_owned_leaf_returns_all_references', list(match({}, rows, None, '', '', set(), '', '', '', '', '', {'theme': ['pose_action'], 'sub': ['坐姿与蹲姿']})) == [0, 1])
bound_category = {'id': 'bound', 'name': 'bound', 'prompts': []}
bound_prompt = {'id': 'bound', 'prompt': '1girl, sitting, dress'}
decision = {**semantic, 'binding': projection.binding(bound_category, bound_prompt), 'disposition': 'classified', 'manual_search_eligible': True, 'random_pool_eligible': False, 'strict_model_pool_eligible': False}
document = {'schema': 'S4-semantic-projection-v1', 'decisions': {'bound': decision}, 'class_labels': taxonomy.CLASS_LABELS}
entry = namespace['_library_entry'](document, bound_category, bound_prompt)
check('fast_projection_theme_ids_include_count_and_leaf_owner', {'person_count', 'pose_action'}.issubset(entry['_semantic']['theme_ids']))
custom_pose = {'primary_class': 'appearance', 'subcategories': ['自定义姿态', '同名自定义'], 'subcategory_owners': {'自定义姿态': 'pose_action', '同名自定义': 'pose_action'}}
custom_clothing = {'primary_class': 'appearance', 'subcategories': ['同名自定义'], 'subcategory_owners': {'同名自定义': 'clothing_accessory'}}
custom_fixture = {'categories': [{'id': 'custom', 'prompts': [{'id': '1', '_semantic': custom_pose}, {'id': '2', '_semantic': custom_clothing}]}], '_semantic_class_labels': taxonomy.CLASS_LABELS, '_review_counts': {'classified': 2}}
custom_pool = index_for(custom_fixture)['filter_pool']
check('custom_leaf_has_explicit_owner', custom_pool['subcategory']['pose_action']['自定义姿态'] == 1)
check('custom_leaf_adds_owner_topic', 'pose_action' in taxonomy.semantic_themes(custom_pose))
check('canonical_owner_cannot_be_overridden', taxonomy.subcategory_owner({'subcategory_owners': {'坐姿与蹲姿': 'clothing_accessory'}}, '坐姿与蹲姿') == 'pose_action')
check('invalid_custom_owner_is_rejected', taxonomy.subcategory_owner({'subcategory_owners': {'自定义姿态': 'invalid'}}, '自定义姿态') is None)
check('custom_conflict_is_omitted_and_reported', custom_pool['conflicting_subcategories']['同名自定义'] == {'clothing_accessory': 1, 'pose_action': 1} and all('同名自定义' not in leaves for leaves in custom_pool['subcategory'].values()))
check('custom_leaf_has_qualified_filter', custom_pool['subcategory_values']['自定义姿态'] == 'pose_action::自定义姿态')
check('custom_qualified_filter_matches', hit(custom_pose, {'sub': ['pose_action::自定义姿态']}))
check('custom_qualified_filter_does_not_mix_owners', not hit(custom_clothing, {'sub': ['pose_action::同名自定义']}))
check('custom_qualified_filter_does_not_include_unowned_label', not hit({'subcategories': ['自定义姿态']}, {'sub': ['pose_action::自定义姿态']}))
check('custom_owner_group_preserves_or', hit(custom_pose, {'sub': ['pose_action::自定义姿态', '移动与运动']}))

result = {'checks': checks, 'passed': len(checks)}
if '--full' in sys.argv:
    store = SELECTOR.parent / 'user_data/prompt_selector'
    document = projection.read_projection(store / 'semantic_projection.json')
    data = json.loads((store / 'data.json').read_text(encoding='utf-8'))
    view = projection.project_library(data, document)
    index = index_for(view)
    pool = index['filter_pool']
    semantics = [p['_semantic'] for c in view['categories'] for p in c['prompts']]
    themes = Counter()
    leaves = Counter()
    owned_leaves = Counter()
    markers = Counter()
    invalid_owners = []
    stale_themes = 0
    for semantic in semantics:
        topic_ids = taxonomy.semantic_themes(semantic)
        themes.update(topic_ids)
        stale_themes += set(semantic.get('theme_ids') or []) != topic_ids
        leaves.update(set(semantic.get('subcategories') or []))
        markers.update(set(semantic.get('count_markers') or []))
        for leaf in set(semantic.get('subcategories') or []):
            owner = taxonomy.subcategory_owner(semantic, leaf)
            if owner:
                owned_leaves[(owner, leaf)] += 1
            if owner and owner not in topic_ids:
                invalid_owners.append(leaf)
    assert dict(themes) == pool['theme']
    assert dict(markers) == pool['count']
    for owner, entries in pool['subcategory'].items():
        for leaf, count in entries.items():
            assert owned_leaves[(owner, leaf)] == count
            if leaf in taxonomy.SUBCATEGORY_PARENTS:
                assert taxonomy.SUBCATEGORY_PARENTS[leaf] == owner
            else:
                assert pool['subcategory_values'][leaf] == owner + '::' + leaf
    assert not invalid_owners and not stale_themes
    result['full_library'] = {
        'records': len(semantics), 'major_themes': len(pool['theme']),
        'leaf_buttons': sum(map(len, pool['subcategory'].values())),
        'default_leaf_buttons': sum(count >= 10 for values in pool['subcategory'].values() for count in values.values()),
        'unmapped_subcategories': pool['unmapped_subcategories'],
        'conflicting_subcategories': pool['conflicting_subcategories'],
        'counts': pool['count'], 'major_theme_counts': pool['theme'],
        'default_count_buttons': sum(count >= 10 for count in pool['count'].values()),
        'rare_count_markers_preserved': {marker: count for marker, count in pool['count'].items() if count < 10},
        'invalid_owner_count': len(invalid_owners), 'stale_theme_ids': stale_themes,
    }
    (Path(__file__).parent / 'pool_index_verified.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
destination = Path(__file__).parent / ('pool_backend_full_verification.json' if '--full' in sys.argv else 'pool_backend_verification.json')
destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
