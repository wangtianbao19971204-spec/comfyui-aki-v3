"""Exercise production selector helpers over temporary, explicitly bound fixtures."""
import ast
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLUGIN = ROOT / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench'
SOURCE = PLUGIN / 'modules/comfyui-anima-tools/nodes.py'
HELPERS = PLUGIN / 'modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector'
FUNCTIONS = {
    '_normalize_shared_category_filter_value', '_shared_prompt_category_paths_match_filter',
    '_parse_shared_prompt_filters', '_shared_prompt_item_matches_filters', '_shared_prompt_source_options',
    '_shared_prompt_codex_directory_levels', '_make_shared_prompt_preview_url',
    '_load_semantic_projection_runtime', '_build_reviewed_shared_payloads',
    '_artist_category_tree', '_artist_search_rank', '_artist_page', '_artist_page_fingerprint',
}


def load_functions(path):
    source = path.read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    constants = [node for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id in {
                     '_SHARED_PROMPT_KINDS', '_SHARED_PROMPT_PARENT_FILTER_PREFIX',
                     '_SHARED_PROMPT_CHILD_FILTER_PREFIX', '_SHARED_PROMPT_PATH_FILTER_PREFIX',
                     '_SHARED_PROMPT_CATEGORY_SEPARATOR'} for target in node.targets)]
    context = {'hashlib': hashlib, 'json': json, 'os': os, 're': re, 'urllib': urllib, 'Path': Path}
    exec(compile(ast.Module(body=constants + functions, type_ignores=[]), str(path), 'exec'), context)
    return context


current = load_functions(SOURCE)
baseline = load_functions(HERE / 'before/nodes.py')
checks = []


def check(name, assertion):
    assert assertion, name
    checks.append(name)


with tempfile.TemporaryDirectory(prefix='canonical-selector-fixture-') as temporary:
    plugin = Path(temporary) / 'plugin'
    helper_dir = plugin / 'prompt_selector'
    helper_dir.mkdir(parents=True)
    for name in ('semantic_projection.py', 'semantic_taxonomy.py'):
        shutil.copyfile(HELPERS / name, helper_dir / name)
    store = plugin / 'user_data/prompt_selector'
    store.mkdir(parents=True)
    source_path = store / 'data.json'
    (store / 'semantic_projection.json').write_text(
        json.dumps({'schema': 'S4-semantic-projection-v1', 'decisions': {}}), encoding='utf-8')
    adapter, _ = current['_load_semantic_projection_runtime'](str(source_path))
    categories = [{'id': 'source:A', 'name': '同名来源/分类', 'prompts': []},
                  {'id': 'source:B', 'name': '同名来源/分类', 'prompts': []}]

    def add(identity, primary, subcategories, index=0, alternatives=None, themes=None, form='atomic_tag', usage='positive'):
        category = categories[index]
        prompt = {'id': identity, 'alias': identity, 'prompt': '\n  @artist, exact_(token),  \n',
                  'favorite': False, 'updated_at': 'fixture', 'image': ''}
        semantic = {'disposition': 'reviewed', 'manual_search_eligible': True,
                    'random_pool_eligible': True, 'strict_model_pool_eligible': True,
                    'usage': usage, 'content_type': form, 'primary_class': primary,
                    'alternative_classes': alternatives or [], 'themes': themes or [],
                    'subcategories': subcategories, 'taxonomy_version': 'fixture-v1'}
        semantic['binding'] = adapter.binding(category, prompt)
        prompt['_classification'] = semantic
        category['prompts'].append(prompt)
        return prompt

    for number in range(193):
        children = ['画师标签'] if number < 120 else ['画师组合']
        if number == 192:
            children += ['服装材质与剪裁']
        add(f'artist-{number:03d}', 'artist_style', children, number % 2,
            alternatives=['clothing_accessory'] if number == 192 else [])
    add('character', 'identity', ['作品角色'])
    add('appearance', 'appearance', ['头发与发型', '眼睛与瞳色'], themes=['count'])
    add('clothing', 'clothing_accessory', ['服装材质与剪裁'])
    add('pose', 'pose_action', ['手势与肢体动作'])
    add('expression', 'expression_gaze', ['视线方向'])
    add('background', 'background_environment', ['室内空间'])
    for primary in ('composition_camera', 'lighting_color', 'style_medium', 'quality_detail'):
        add(primary, primary, [next(iter(adapter.SUBCATEGORY_PARENTS))])
    add('template', 'artist_style', ['画师标签'], form='template')
    add('negative', 'artist_style', ['画师标签'], usage='negative')
    categories[0]['prompts'].append({'id': 'pending', 'alias': 'pending', 'prompt': 'pending'})
    data = {'last_modified': 'fixture-revision', 'categories': categories}
    source_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    args = (str(source_path), 1, data, 'fixture-sha')
    old = baseline['_build_reviewed_shared_payloads'](*args)
    new = current['_build_reviewed_shared_payloads'](*args)
    summary = current['_build_reviewed_shared_payloads'](*args, summary_only=True)
    for kind in new:
        check(f'{kind}_eligibility_and_order_unchanged', [item['id'] for item in old[kind]['items']] ==
              [item['id'] for item in new[kind]['items']])
        check(f'{kind}_prompt_bytes_unchanged', [item['tags'] for item in old[kind]['items']] ==
              [item['tags'] for item in new[kind]['items']])
        check(f'{kind}_full_summary_same_canonical_semantic', [item['_semantic'] for item in new[kind]['items']] ==
              [item['_semantic'] for item in summary[kind]['items']])
    check('kind_counts_unchanged', new['artist']['kind_counts'] == old['artist']['kind_counts'])
    check('pending_and_quarantine_unchanged', new['artist']['pending_prompt_ids'] == old['artist']['pending_prompt_ids']
          and new['artist']['quarantined_prompt_ids'] == old['artist']['quarantined_prompt_ids'])
    check('summary_has_exact_source_fields', all(item['source_category_id'] in {'source:A', 'source:B'}
          for payload in summary.values() for item in payload['items']))
    items = new['artist']['items']
    parents = new['artist']['semantic_subcategory_owners']
    parse = current['_parse_shared_prompt_filters']
    hit = current['_shared_prompt_item_matches_filters']
    late = next(item for item in items if item['source_prompt_id'] == 'artist-192')
    check('alternative_and_subtopic_theme_included', late['_semantic']['theme_ids'] == ['artist_style', 'clothing_accessory'])
    check('subtopic_owner_is_canonical', late['_semantic']['subcategory_owners']['服装材质与剪裁'] == 'clothing_accessory')
    appearance = next(item for item in new['character']['items'] if item['source_prompt_id'] == 'appearance')
    check('facet_theme_uses_canonical_mapping', 'person_count' in appearance['_semantic']['theme_ids'])
    check('themes_same_group_or', hit(late, ['shared-theme:identity', 'shared-theme:artist_style'], parents))
    check('same_owner_subcategories_or', hit(late, ['shared-sub:画师标签', 'shared-sub:画师组合'], parents))
    check('cross_owner_subcategories_and_accept', hit(late, ['shared-sub:画师组合', 'shared-sub:服装材质与剪裁'], parents))
    check('cross_owner_subcategories_and_reject', not hit(items[0], ['shared-sub:画师标签', 'shared-sub:服装材质与剪裁'], parents))
    check('theme_and_subcategory_intersect', not hit(late, ['shared-theme:identity', 'shared-sub:画师组合'], parents))
    check('source_id_exact_no_display_name_guess', not hit(late, ['shared-source:同名来源/分类'], parents))
    check('source_id_not_prefix_match', not hit(late, ['shared-source:source'], parents))
    check('source_and_theme_intersect', hit(late, ['shared-source:source:A', 'shared-theme:clothing_accessory'], parents)
          and not hit(late, ['shared-source:source:B', 'shared-theme:clothing_accessory'], parents))
    check('qualified_subtopic_respects_owner', hit(late, ['shared-sub:clothing_accessory::服装材质与剪裁'], parents)
          and not hit(late, ['shared-sub:identity::服装材质与剪裁'], parents))
    check('shared_filters_roundtrip', parse('shared-filters:' + json.dumps(['shared-theme:artist_style', 'shared-source:source:A'])) ==
          ['shared-theme:artist_style', 'shared-source:source:A'])
    for raw in ('shared-filters:{}', 'shared-filters:[1]', 'shared-filters:["shared-source:A","shared-source:B"]'):
        try:
            parse(raw)
        except ValueError:
            checks.append('invalid_filter_rejected:' + raw)
        else:
            raise AssertionError(raw)

    payload = {**new['artist'], 'revision': 'fixture-revision'}
    page = current['_artist_page']
    result, status = page(payload, {'filter': 'shared-theme:clothing_accessory', 'include_tree': True, 'limit': 60})
    check('cross_page_semantic_match_uses_whole_catalog', status == 200 and result['total'] == 1
          and result['items'][0]['source_prompt_id'] == 'artist-192')
    result, _ = page(payload, {'filter': 'shared-filters:' + json.dumps(['shared-sub:画师标签', 'shared-source:source:B']), 'limit': 100})
    check('source_subcategory_intersection_count', result['total'] == 60 and len(result['items']) == 60)
    all_ids = []
    for offset in range(0, 193, 60):
        result, status = page(payload, {'offset': offset, 'limit': 60})
        all_ids.extend(item['id'] for item in result['items'])
    check('pagination_unique_and_complete', len(all_ids) == len(set(all_ids)) == 193)
    result, _ = page(payload, {'filter': 'shared-path:WeiLin / 画师与作者\u001f画师标签', 'limit': 0})
    check('legacy_path_preserved', result['total'] == 120 and result['items'] == [])
    stale, status = page(payload, {'revision': 'old-revision'})
    check('revision_mismatch_still_rejected', status == 409)
    tree = current['_artist_category_tree'](items + [items[0]], payload['semantic_classes'], parents)
    by_key = {node['key']: node for node in tree}
    check('canonical_class_order', list(by_key) == ['shared-theme:clothing_accessory', 'shared-theme:artist_style'])
    check('canonical_labels_no_weilin_or_source_root', by_key['shared-theme:artist_style']['label'] == '画师与作者')
    check('tree_counts_use_stable_id_dedup', by_key['shared-theme:artist_style']['count'] == 193)
    check('canonical_sub_key', by_key['shared-theme:clothing_accessory']['children'][0]['key'] == 'shared-sub:服装材质与剪裁')
    sources = current['_shared_prompt_source_options'](items + [items[0]])
    check('same_display_name_distinct_source_ids', {source['id']: source['count'] for source in sources} ==
          {'source:A': 97, 'source:B': 96})
    check('source_metadata_include_tree', page(payload, {'include_tree': True, 'limit': 0})[0]['source_options'] == sources)
    custom = copy.deepcopy(late)
    custom['_semantic']['subcategories'] = ['自定义主题']
    custom['_semantic']['subcategory_owners'] = {'自定义主题': 'artist_style'}
    custom_tree = current['_artist_category_tree']([custom], payload['semantic_classes'], parents)
    custom_node = next(node for node in custom_tree if node['key'] == 'shared-theme:artist_style')
    check('dynamic_subcategory_uses_same_qualified_identity', custom_node['children'][0]['key'] == 'shared-sub:artist_style::自定义主题')
    check('dynamic_qualified_filter_matches', hit(custom, ['shared-sub:artist_style::自定义主题'], parents))
    current['_find_weilin_prompt_selector_data'] = lambda: str(source_path)
    current['_SHARED_PROMPT_TAXONOMY_PATH'] = str(source_path)
    check('disk_cache_schema_bumped', current['_artist_page_fingerprint']()[0] == 'artist-page-v2-canonical')

receipt = {'verified_at': datetime.now(timezone(timedelta(hours=8))).isoformat(), 'passed': True,
           'checks': checks, 'check_count': len(checks), 'nodes_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
           'baseline_nodes_sha256': hashlib.sha256((HERE / 'before/nodes.py').read_bytes()).hexdigest(),
           'method': 'AST-isolated actual production functions, canonical semantic helper copies and strictly temporary synthetic documents; no route-bearing ComfyUI imports.',
           'production_data_writes': 0, 'service_restarts': 0, 'gpu_runs': 0,
           'limits': ['No live new endpoint or browser verification; root performs one final controlled restart and acceptance.']}
(HERE / 'backend_canonical_contract.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'passed': True, 'checks': len(checks), 'nodes_sha256': receipt['nodes_sha256']}, ensure_ascii=False))
