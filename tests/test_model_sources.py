"""Offline catalogue acceptance with synthetic paths, metadata, and hashes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import model_sources as sources


class ModelSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline-model-sources-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        (self.repo / 'snapshot/inventory').mkdir(parents=True)
        (self.repo / 'docs').mkdir()
        workflow = self.repo / sources.WORKFLOW_SOURCE
        workflow.parent.mkdir(parents=True)
        workflow.write_text('{"fixture": true}\n', encoding='utf8')
        self.inventory = {'files': [
            {'path': 'ComfyUI/models/diffusion_models/base.safetensors', 'bytes': 100},
            {'path': 'ComfyUI/models/vae/配套.safetensors', 'bytes': 20},
            {'path': 'ComfyUI/models/loras/retired.safetensors', 'bytes': 10},
            {'path': 'ComfyUI/custom_nodes/fixture/model.safetensors', 'bytes': 30},
        ]}
        self.inventory_path = self.repo / sources.INVENTORY
        self.inventory_path.write_text(json.dumps(self.inventory, ensure_ascii=False), encoding='utf8')
        self.inventory_sha256 = sources.digest(self.inventory_path)
        self.workflow_sha256 = sources.digest(workflow)

    def source(self):
        return {'page_url': 'https://civitai.com/models/100?modelVersionId=200',
                'download_url': 'https://civitai.com/api/download/models/200',
                'provider': 'Civitai', 'model_id': 100, 'version_id': 200,
                'file_id': 300, 'filename': 'base.safetensors',
                'declared_sha256': 'a' * 64, 'revision': None,
                'evidence': [{'kind': 'version_metadata', 'reference': 'snapshot/inventory/example.json'}],
                'availability': '离线元数据记录；未联网验证'}

    def catalogue(self):
        assets = []
        for index, item in enumerate(self.inventory['files']):
            assets.append({**item, 'kind': ['diffusion_model', 'vae', 'lora', 'plugin_weight'][index],
                           'captured_in_inventory': True, 'observed_present': index != 2,
                           'local_sha256': 'b' * 64 if index == 0 else None,
                           'source_status': ['version_metadata', 'upstream_mapping', 'unresolved', 'local_derivative'][index],
                           'family': 'fixture-family' if index in {0, 1} else None,
                           'sources': [self.source()] if index in {0, 1, 3} else [],
                           'companions': ['ComfyUI/models/vae/配套.safetensors'] if index == 0 else [],
                           'workflows': [sources.WORKFLOW] if index == 0 else [],
                           'derivation': {'kind': 'local_conversion', 'parent_path': assets[0]['path'],
                                          'recipe_reference': 'snapshot/runtime/fixture/README.md',
                                          'original_weight_required': True,
                                          'reproducibility': 'weights_backup_required'} if index == 3 else None,
                           'notes': ['虚构隔离样例；不表示真实模型或兼容性。']})
        result = {'schema': 1, 'captured_at': '2026-10-07T00:00:00+00:00',
                  'inventory_sha256': self.inventory_sha256, 'workflow_sha256': self.workflow_sha256,
                  'notes': ['来源定位不等于下载验证。'], 'assets': assets,
                  'missing_workflow_references': [{'reference': 'missing.safetensors',
                                                    'workflows': [sources.WORKFLOW],
                                                    'notes': ['保持原引用，不自动替换。']}], 'summary': {}}
        result['summary'] = sources.compute_summary(result)
        return result

    def validate(self, catalogue):
        return sources.validate_catalogue(catalogue, self.inventory, self.inventory_sha256, self.workflow_sha256)

    def save(self, catalogue):
        (self.repo / sources.CATALOGUE).write_text(json.dumps(catalogue, ensure_ascii=False), encoding='utf8')

    def standardized(self, asset, *, name='规范底模.safetensors'):
        original_type = asset['path'].split('/')[2]
        target = f'ComfyUI/models/{original_type}/fixture-family/图像生成/{name}'
        asset['current_path'] = target
        asset['standardization'] = {'family_slug': 'fixture-family',
                                    'family_label': '样例家族', 'category': '图像生成',
                                    'display_name': '规范底模', 'version': 'v1',
                                    'precision': 'fp16', 'source_identity': 'cv200__f300',
                                    'target_path': target,
                                    'evidence': ['snapshot/inventory/example.json']}
        return asset

    def test_current_placement_keeps_capture_identity_bytes_and_summary(self):
        catalogue = self.catalogue()
        original = copy.deepcopy(catalogue['assets'][0])
        asset = self.standardized(catalogue['assets'][0])
        self.assertEqual(self.validate(catalogue), catalogue['summary'])
        self.assertEqual(asset['path'], original['path'])
        self.assertEqual(asset['bytes'], original['bytes'])
        self.assertTrue(asset['captured_in_inventory'])
        self.assertEqual(sources.current_path(asset), asset['current_path'])
        self.assertEqual(sources.current_path(catalogue['assets'][1]), catalogue['assets'][1]['path'])
        for field in ('version', 'precision', 'source_identity'):
            asset['standardization'][field] = None
        self.validate(catalogue)
        for field, value in [('path', 'ComfyUI/models/diffusion_models/changed.safetensors'),
                             ('bytes', 101), ('captured_in_inventory', False)]:
            bad = copy.deepcopy(catalogue); bad['assets'][0][field] = value
            with self.subTest(field=field), self.assertRaises(sources.CatalogueError):
                self.validate(bad)

    def test_placement_requires_present_asset_and_complete_whitelisted_contract(self):
        catalogue = self.catalogue(); self.standardized(catalogue['assets'][0])
        for field in ('current_path', 'standardization'):
            bad = copy.deepcopy(catalogue); del bad['assets'][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(sources.CatalogueError, 'incomplete_standardization'):
                self.validate(bad)
        bad = copy.deepcopy(catalogue); bad['assets'][0]['observed_present'] = False
        with self.assertRaisesRegex(sources.CatalogueError, 'missing_asset_has_current_path'):
            self.validate(bad)
        for value in (None, {}, {**catalogue['assets'][0]['standardization'], 'unreviewed': 'fixture'}):
            bad = copy.deepcopy(catalogue); bad['assets'][0]['standardization'] = value
            with self.subTest(value=value), self.assertRaisesRegex(sources.CatalogueError, 'invalid_standardization_schema'):
                self.validate(bad)
        bad = copy.deepcopy(catalogue); bad['assets'][0]['current_path'] = None
        with self.assertRaises(sources.CatalogueError):
            self.validate(bad)

    def test_current_paths_cannot_escape_models_change_loader_type_or_use_devices(self):
        catalogue = self.catalogue(); self.standardized(catalogue['assets'][0])
        for target in ('../outside/model.safetensors', '/outside/model.safetensors',
                       'G:/models/model.safetensors',
                       'ComfyUI/custom_nodes/fixture/fixture-family/图像生成/model.safetensors',
                       'ComfyUI/models/loras/fixture-family/图像生成/model.safetensors',
                       'ComfyUI/models/diffusion_models/fixture-family/图像生成/NUL.safetensors',
                       'ComfyUI/models/diffusion_models/fixture-family/图像生成/．．/model.safetensors'):
            bad = copy.deepcopy(catalogue)
            bad['assets'][0]['current_path'] = target
            bad['assets'][0]['standardization']['target_path'] = target
            with self.subTest(target=target), self.assertRaises(sources.CatalogueError):
                self.validate(bad)
        bad = copy.deepcopy(catalogue)
        bad['assets'][3]['current_path'] = 'ComfyUI/models/checkpoints/fixture-family/图像生成/model.safetensors'
        bad['assets'][3]['standardization'] = copy.deepcopy(catalogue['assets'][0]['standardization'])
        bad['assets'][3]['standardization']['target_path'] = bad['assets'][3]['current_path']
        with self.assertRaisesRegex(sources.CatalogueError, 'current_path_model_root_mismatch'):
            self.validate(bad)

    def test_standardization_components_target_and_evidence_cannot_drift(self):
        catalogue = self.catalogue(); self.standardized(catalogue['assets'][0])
        for field, value in [('family_slug', 'other-family'), ('category', '角色'),
                             ('target_path', 'ComfyUI/models/diffusion_models/fixture-family/图像生成/other.safetensors'),
                             ('family_slug', 'a/b'), ('category', 'NUL'),
                             ('evidence', ['../private.json']),
                             ('evidence', ['snapshot/a.json', 'SNAPSHOT/A.json']),
                             ('version', False), ('precision', []), ('source_identity', {})]:
            bad = copy.deepcopy(catalogue); bad['assets'][0]['standardization'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(sources.CatalogueError):
                self.validate(bad)

    def test_current_path_collisions_include_unmoved_and_missing_history_case_insensitively(self):
        catalogue = self.catalogue(); self.standardized(catalogue['assets'][0])
        duplicate = copy.deepcopy(catalogue['assets'][0])
        duplicate.update(path='ComfyUI/models/diffusion_models/extra.safetensors', captured_in_inventory=False)
        # Change ASCII filename case, while leaving the classification contract valid.
        duplicate['current_path'] = duplicate['current_path'].replace('.safetensors', '.SAFETENSORS')
        duplicate['standardization']['target_path'] = duplicate['current_path']
        catalogue['assets'].append(duplicate); catalogue['summary'] = sources.compute_summary(catalogue)
        with self.assertRaisesRegex(sources.CatalogueError, 'duplicate_current_asset_path'):
            self.validate(catalogue)
        for present in (True, False):
            bad = self.catalogue(); moved = self.standardized(bad['assets'][0])
            unmoved = copy.deepcopy(bad['assets'][2])
            unmoved.update(path=moved['current_path'].replace('.safetensors', '.SAFETENSORS'),
                           captured_in_inventory=False, observed_present=present)
            bad['assets'].append(unmoved); bad['summary'] = sources.compute_summary(bad)
            with self.subTest(present=present), self.assertRaisesRegex(sources.CatalogueError, 'duplicate_current_asset_path'):
                self.validate(bad)

    def test_standardized_render_prefers_current_path_and_keeps_history_and_maintenance(self):
        catalogue = self.catalogue(); asset = self.standardized(catalogue['assets'][0])
        self.validate(catalogue)
        rendered = sources.render_markdown(catalogue)
        self.assertIn('| ' + sources.cell(asset['current_path']) + ' |', rendered)
        self.assertIn('捕获历史路径：' + sources.cell(asset['path']), rendered)
        self.assertIn('生成底模<br>样例家族<br>分类：图像生成', rendered)
        for text in ('标准名称：规范底模', '标准分类：样例家族 / 图像生成', '规范版本：v1',
                     '精度：fp16', '来源身份：cv200', '命名证据：snapshot/inventory/example.json',
                     '维护时使用现行放置路径', '虚构隔离样例'):
            self.assertIn(text, rendered)
        self.assertIn('| ' + sources.cell(catalogue['assets'][1]['path']) + ' |', rendered)
        self.save(catalogue)
        original = Path.open
        allowed = {self.repo / sources.CATALOGUE, self.inventory_path,
                   self.repo / sources.WORKFLOW_SOURCE}
        def bounded_open(path, *args, **kwargs):
            self.assertIn(path, allowed, 'Checker tried to follow the current runtime placement')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', bounded_open):
            self.assertEqual(sources.check_catalogue(self.repo)[0], catalogue)

    def test_valid_catalogue_retains_missing_captured_assets_and_exact_counts(self):
        catalogue = self.catalogue()
        summary = self.validate(catalogue)
        self.assertEqual(summary['asset_count'], 4)
        self.assertEqual(summary['inventory_asset_count'], 4)
        self.assertEqual(summary['observed_present_count'], 3)
        self.assertEqual(summary['observed_missing_count'], 1)
        self.assertEqual(summary['workflow_asset_count'], 1)
        self.assertEqual(summary['source_status_counts'], {key: 1 for key in sources.STATUSES})
        self.assertFalse(catalogue['assets'][2]['observed_present'])

    def test_metadata_check_reads_only_catalogue_inventory_and_workflow(self):
        catalogue = self.catalogue(); self.save(catalogue)
        allowed = {self.repo / sources.CATALOGUE, self.inventory_path,
                   self.repo / sources.WORKFLOW_SOURCE}
        original = Path.open
        touched = []
        def bounded_open(path, *args, **kwargs):
            self.assertIn(path, allowed, 'Checker attempted to open a model/runtime path')
            self.assertFalse(any(character in args[0] for character in 'wax+'))
            touched.append(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', bounded_open):
            read, summary = sources.check_catalogue(self.repo)
        self.assertEqual(read, catalogue)
        self.assertEqual(summary, catalogue['summary'])
        self.assertEqual(set(touched), allowed)

    def test_public_urls_accept_stable_version_pages_and_downloads(self):
        for value in ['https://civitai.com/models/10?modelVersionId=20',
                      'https://civitai.com/models/10/example?modelVersionId=20',
                      'https://civitai.com/models/10/versions/20',
                      'https://huggingface.co/example/model/tree/abcdef',
                      'https://github.com/example/project/releases/tag/v1']:
            with self.subTest(value=value):
                self.assertEqual(sources.public_url(value), value)
        self.assertEqual(sources.public_url('https://huggingface.co/example/model/resolve/main/model.safetensors', download=True),
                         'https://huggingface.co/example/model/resolve/main/model.safetensors')

    def test_public_urls_reject_credentials_sessions_queries_local_aliases_and_non_https(self):
        protocol = 'https'
        userinfo = 'user:secret'
        forbidden = ['http://civitai.com/models/10', protocol + '://' + userinfo + '@example.com/file',
                     'https://example.com/file?token=fixture', 'https://example.com/file?session=fixture',
                     'https://civitai.com/models/10?modelVersionId=20&token=fixture',
                     'https://civitai.com/models/10?modelVersionId=20&modelVersionId=21',
                     'https://civitai.com/models/10?modelVersionId=text',
                     'https://civitai.com/models/10?modelVersion%49d=20',
                     'https://civitai.com/login?modelVersionId=20',
                     'https://example.com/file#secret', 'https://example.com/file#',
                     'https://example.com/file?', 'https://127.0.0.1/model',
                     'https://[::1]/model', 'https://2130706433/model',
                     'https://0x7f.0x0.0x0.0x1/model', 'https://machine.local/model',
                     'https://machine.internal/model', 'https://localhost.localdomain/model',
                     'https://localhost/model', 'https://example.com:443/file',
                     'https://example.com/auth/file', 'https://example.com/%73ession/file',
                     'https://example.com/../file', 'https://example.com/%2e%2e/file',
                     'https://example.com\\@127.0.0.1/file']
        for value in forbidden:
            with self.subTest(value=value), self.assertRaises(sources.CatalogueError):
                sources.public_url(value)
        with self.assertRaisesRegex(sources.CatalogueError, 'url_query_forbidden'):
            sources.public_url('https://civitai.com/models/10?modelVersionId=20', download=True)

    def test_portable_paths_reject_absolute_traversal_ads_and_case_duplicates(self):
        for value in ['../model', 'a/../model', 'a\\..\\model', '/model', 'C:/models/a',
                      'C:\\models\\a', '\\\\server\\share\\a', 'a//model', 'a/./model',
                      'a:stream', 'a./model', 'NUL.safetensors', '.git/model', 'a／model', '．．/model']:
            with self.subTest(value=value), self.assertRaises(sources.CatalogueError):
                sources.relative_path(value)
        with self.assertRaisesRegex(sources.CatalogueError, 'duplicate_relative_path'):
            sources.path_list(['ComfyUI/models/a', 'comfyui/models/A'])
        self.assertEqual(sources.relative_path('ComfyUI/models/loras/角色（样例）.safetensors'),
                         'ComfyUI/models/loras/角色（样例）.safetensors')

    def test_path_contract_covers_companions_workflows_evidence_and_derivation(self):
        for category in ['companions', 'workflows', 'evidence', 'parent_path', 'recipe_reference']:
            catalogue = self.catalogue()
            if category in {'companions', 'workflows'}:
                catalogue['assets'][0][category] = ['../escape']
            elif category == 'evidence':
                catalogue['assets'][0]['sources'][0]['evidence'][0]['reference'] = '/private/config.json'
            else:
                catalogue['assets'][3]['derivation'][category] = 'C:/private/model'
            with self.subTest(category=category), self.assertRaises(sources.CatalogueError):
                self.validate(catalogue)

    def test_duplicate_assets_and_original_inventory_coverage_fail(self):
        catalogue = self.catalogue(); duplicate = copy.deepcopy(catalogue['assets'][0])
        duplicate['path'] = duplicate['path'].upper(); catalogue['assets'].append(duplicate)
        with self.assertRaisesRegex(sources.CatalogueError, 'duplicate_asset_path'):
            self.validate(catalogue)
        catalogue = self.catalogue(); catalogue['assets'].pop()
        with self.assertRaisesRegex(sources.CatalogueError, 'inventory_coverage_mismatch'):
            self.validate(catalogue)

    def test_inventory_bytes_and_membership_are_not_silently_reclassified(self):
        for key, value in [('bytes', 101), ('captured_in_inventory', False),
                           ('path', 'comfyui/models/diffusion_models/base.safetensors')]:
            catalogue = self.catalogue(); catalogue['assets'][0][key] = value
            with self.subTest(key=key), self.assertRaises(sources.CatalogueError):
                self.validate(catalogue)
        catalogue = self.catalogue(); extra = copy.deepcopy(catalogue['assets'][2])
        extra.update(path='ComfyUI/models/loras/new.safetensors', captured_in_inventory=False, observed_present=True)
        catalogue['assets'].append(extra); catalogue['summary'] = sources.compute_summary(catalogue)
        self.assertEqual(self.validate(catalogue)['inventory_asset_count'], 4)

    def test_local_derivative_requires_recipe_and_can_have_no_direct_source(self):
        catalogue = self.catalogue(); catalogue['assets'][3]['sources'] = []
        self.validate(catalogue)
        for value in [None, {}, {'kind': 'local_conversion'},
                      {**catalogue['assets'][3]['derivation'], 'unknown': 'ambiguous'}]:
            bad = copy.deepcopy(catalogue); bad['assets'][3]['derivation'] = value
            with self.subTest(value=value), self.assertRaises(sources.CatalogueError):
                self.validate(bad)
        bad = self.catalogue(); bad['assets'][0]['sources'] = []
        with self.assertRaisesRegex(sources.CatalogueError, 'resolved_asset_requires_source'):
            self.validate(bad)

    def test_hashes_binding_and_local_vs_declared_remain_distinct(self):
        for category in ['inventory_sha256', 'workflow_sha256', 'local_sha256', 'declared_sha256']:
            catalogue = self.catalogue()
            if category in {'inventory_sha256', 'workflow_sha256'}:
                catalogue[category] = 'c' * 64
            elif category == 'local_sha256':
                catalogue['assets'][0][category] = 'malformed'
            else:
                catalogue['assets'][0]['sources'][0][category] = 'malformed'
            with self.subTest(category=category), self.assertRaises(sources.CatalogueError):
                self.validate(catalogue)
        catalogue = self.catalogue(); catalogue['assets'][2]['local_sha256'] = 'a' * 64
        with self.assertRaisesRegex(sources.CatalogueError, 'missing_asset_has_local_sha256'):
            self.validate(catalogue)
        catalogue = self.catalogue(); self.save(catalogue)
        self.inventory_path.write_text(json.dumps(self.inventory, indent=2), encoding='utf8')
        with self.assertRaisesRegex(sources.CatalogueError, 'inventory_sha256_mismatch'):
            sources.check_catalogue(self.repo)

    def test_summary_drift_bool_counts_and_unknown_schema_fields_fail(self):
        catalogue = self.catalogue(); catalogue['summary']['asset_count'] += 1
        with self.assertRaisesRegex(sources.CatalogueError, 'summary_mismatch'):
            self.validate(catalogue)
        catalogue = self.catalogue(); catalogue['summary']['workflow_asset_count'] = True
        with self.assertRaisesRegex(sources.CatalogueError, 'summary_mismatch'):
            self.validate(catalogue)
        catalogue = self.catalogue(); catalogue['assets'][0]['sources'][0]['token'] = 'fixture'
        with self.assertRaisesRegex(sources.CatalogueError, 'invalid_source_schema'):
            self.validate(catalogue)
        catalogue = self.catalogue(); catalogue['schema'] = True
        with self.assertRaisesRegex(sources.CatalogueError, 'invalid_catalogue_schema'):
            self.validate(catalogue)

    def test_missing_references_are_separate_and_cannot_carry_signed_links(self):
        catalogue = self.catalogue()
        catalogue['missing_workflow_references'][0]['reference'] = 'folder\\missing.safetensors'
        self.validate(catalogue)
        catalogue['missing_workflow_references'][0]['reference'] = 'https://huggingface.co/example/repo/resolve/main/model.safetensors'
        self.validate(catalogue)
        for reference in ['..\\missing.safetensors', 'C:\\private\\missing.safetensors',
                          'https://huggingface.co/example/repo/resolve/main/model?token=fixture']:
            bad = copy.deepcopy(catalogue); bad['missing_workflow_references'][0]['reference'] = reference
            with self.subTest(reference=reference), self.assertRaises(sources.CatalogueError):
                self.validate(bad)

    def test_render_contains_every_asset_download_version_family_notes_and_missing_reference(self):
        catalogue = self.catalogue()
        text = sources.render_markdown(catalogue)
        for asset in catalogue['assets']:
            self.assertIn(sources.cell(asset['path']), text)
        for group in ['正式 v2 所需', '底模与配套', 'LoRA', '其他模型与插件权重']:
            self.assertIn('## ' + group, text)
        self.assertIn('https://civitai.com/models/100?modelVersionId=200', text)
        self.assertIn('https://civitai.com/api/download/models/200', text)
        self.assertIn('model=100, version=200, file=300', text)
        self.assertIn('fixture-family', text)
        self.assertIn('虚构隔离样例', text)
        self.assertIn('本机：' + 'b' * 64, text)
        self.assertIn('上游声明：' + 'a' * 64, text)
        self.assertIn('未核验', text)
        self.assertIn('父模型文件', text)
        self.assertIn('缺失工作流引用', text)
        self.assertIn('missing.safetensors', text)
        self.assertIn('不自动替换', text)
        self.assertIn('不联网、不下载、不读取模型内容', text)

    def test_render_escapes_metadata_markup_without_losing_prose(self):
        catalogue = self.catalogue()
        catalogue['assets'][0]['notes'] = ['<script>unsafe</script> | [fake](https://example.com)']
        self.validate(catalogue)
        text = sources.render_markdown(catalogue)
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;unsafe&lt;/script&gt; &#124; &#91;fake&#93;', text)

    def test_render_only_replaces_fixed_document_and_preserves_input_bytes(self):
        catalogue = self.catalogue(); self.save(catalogue)
        inputs = {relative: (self.repo / relative).read_bytes() for relative in
                  [sources.CATALOGUE, sources.INVENTORY, sources.WORKFLOW_SOURCE]}
        target = self.repo / sources.DOCUMENT
        target.write_text('old generated guide', encoding='utf8')
        self.assertEqual(sources.render(self.repo), catalogue['summary'])
        self.assertEqual(target.read_text(encoding='utf8'), sources.render_markdown(catalogue))
        for relative, content in inputs.items():
            self.assertEqual((self.repo / relative).read_bytes(), content)
        self.assertEqual(list(target.parent.glob('.MODEL_SOURCES.md.*.tmp')), [])

    def test_render_rejects_hardlink_target_and_preserves_other_file(self):
        self.save(self.catalogue())
        outside = Path(self.temp.name) / 'other.md'; outside.write_text('preserve', encoding='utf8')
        target = self.repo / sources.DOCUMENT
        try:
            os.link(outside, target)
        except OSError:
            self.skipTest('Hardlinks unavailable in this isolated filesystem')
        with self.assertRaisesRegex(sources.CatalogueError, 'not_single_regular_file'):
            sources.render(self.repo)
        self.assertEqual(outside.read_text(encoding='utf8'), 'preserve')

    def test_linked_output_and_catalogue_are_rejected(self):
        self.save(self.catalogue())
        outside = Path(self.temp.name) / 'other.md'; outside.write_text('preserve', encoding='utf8')
        target = self.repo / sources.DOCUMENT
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest('Symlinks unavailable in this isolated filesystem')
        with self.assertRaisesRegex(sources.CatalogueError, 'linked_or_reparse_path'):
            sources.render(self.repo)
        self.assertEqual(outside.read_text(encoding='utf8'), 'preserve')
        target.unlink()
        catalogue = self.repo / sources.CATALOGUE
        elsewhere = Path(self.temp.name) / 'elsewhere.json'; elsewhere.write_bytes(catalogue.read_bytes())
        catalogue.unlink(); catalogue.symlink_to(elsewhere)
        with self.assertRaisesRegex(sources.CatalogueError, 'linked_or_reparse_path'):
            sources.check_catalogue(self.repo)

    def test_duplicate_json_keys_fail_without_echoing_values(self):
        self.save(self.catalogue())
        path = self.repo / sources.CATALOGUE
        path.write_text('{"schema":1,"schema":"fixture-sensitive"}', encoding='utf8')
        with self.assertRaisesRegex(sources.CatalogueError, 'duplicate_json_key') as caught:
            sources.check_catalogue(self.repo)
        self.assertNotIn('fixture-sensitive', str(caught.exception))

    def test_cli_repo_override_check_is_read_only_and_render_outputs_short_json(self):
        self.save(self.catalogue())
        script = Path(sources.__file__)
        command = [sys.executable, '-X', 'utf8', '-B', str(script)]
        rendered = subprocess.run(command + ['--repo', str(self.repo), 'render'], capture_output=True,
                                  encoding='utf8', timeout=20)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        receipt = json.loads(rendered.stdout)
        self.assertEqual(receipt['document'], sources.DOCUMENT)
        self.assertEqual(receipt['catalogue_sha256'], sources.digest(self.repo / sources.CATALOGUE))
        self.assertEqual(receipt['document_sha256'], sources.digest(self.repo / sources.DOCUMENT))
        self.assertTrue((self.repo / sources.DOCUMENT).is_file())
        before = {str(path.relative_to(self.repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in self.repo.rglob('*') if path.is_file()}
        check = subprocess.run(command + ['check', '--repo', str(self.repo)], capture_output=True,
                               encoding='utf8', timeout=20)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertTrue(json.loads(check.stdout)['pass'])
        self.assertEqual(json.loads(check.stdout)['catalogue_sha256'], receipt['catalogue_sha256'])
        self.assertEqual(before, {str(path.relative_to(self.repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in self.repo.rglob('*') if path.is_file()})

    def test_cli_check_rejects_missing_or_tampered_readable_document(self):
        self.save(self.catalogue())
        command = [sys.executable, '-X', 'utf8', '-B', str(Path(sources.__file__)),
                   'check', '--repo', str(self.repo)]
        missing = subprocess.run(command, capture_output=True, encoding='utf8', timeout=20)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)['error'], 'rendered_document_missing')
        sources.render(self.repo)
        accepted = subprocess.run(command, capture_output=True, encoding='utf8', timeout=20)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        target = self.repo / sources.DOCUMENT
        target.write_text(target.read_text(encoding='utf8').replace('version=200', 'version=201'), encoding='utf8')
        modified = target.read_bytes()
        rejected = subprocess.run(command, capture_output=True, encoding='utf8', timeout=20)
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(json.loads(rejected.stdout)['error'], 'rendered_document_mismatch')
        self.assertEqual(target.read_bytes(), modified, 'Check silently rewrote the readable document')


if __name__ == '__main__':
    unittest.main()
