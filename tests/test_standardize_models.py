"""Offline model naming and migration regressions; all paths are synthetic."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import model_naming_rules as rules
import standardize_models as migration


class NamingRulesTests(unittest.TestCase):
    def asset(self, *, path='ComfyUI/models/loras/anima/画风与画师/fixture.safetensors',
              kind='lora', family='Anima', file_id=300):
        return {
            'path': path, 'kind': kind, 'observed_present': True,
            'family': family, 'local_sha256': 'a' * 64,
            'sources': [{'provider': 'civitai', 'model_id': 100,
                         'version_id': 200, 'file_id': file_id,
                         'revision': None, 'page_url': 'https://civitai.com/models/100'}],
            'derivation': None,
        }

    def metadata(self, *, base='Anima', version='v1', title='Fixture style'):
        return {
            'model_name': '【Anima｜画风与画师】Old local display · Old version',
            'base_model': base,
            'civitai': {'id': 200, 'modelId': 100, 'baseModel': base,
                        'name': version, 'model': {'name': title, 'type': 'LORA'}},
        }

    def test_selected_version_family_beats_multifamily_title_and_old_directory(self):
        metadata = self.metadata(base='Krea2', title='Anima | Krea2 | Illustrious Style')
        metadata['base_model'] = 'Anima'
        result = rules.build_standardization(self.asset(), metadata)
        self.assertEqual(result['family_slug'], 'krea2')
        self.assertEqual(result['category'], '画风与画师')
        self.assertIn('/loras/krea2/画风与画师/', result['target_path'])

    def test_model_title_alone_does_not_change_version_compatibility(self):
        result = rules.build_standardization(
            self.asset(), self.metadata(title='Anima 2.9B / Krea2 collection'))
        self.assertEqual(result['family_slug'], 'anima')

    def test_authoritative_krea_version_does_not_inherit_lower_priority_anima29(self):
        asset = self.asset(family='Anima-2.9B')
        metadata = self.metadata(base='Krea2')
        metadata['base_model'] = 'Anima-2.9B'
        result = rules.build_standardization(asset, metadata)
        self.assertEqual(result['family_slug'], 'krea2')

    def test_anima29_version_is_split_from_generic_anima_family(self):
        result = rules.build_standardization(self.asset(), self.metadata(version='v1.0 2.9B'))
        self.assertEqual(result['family_slug'], 'anima-2.9b')
        self.assertIn('/anima-2.9b/', result['target_path'])

    def test_anima29_reviewed_model_root_remains_separate(self):
        asset = self.asset(path='ComfyUI/models/diffusion_models/Anima-2.9B/fixture.safetensors',
                           kind='diffusion_model')
        result = rules.build_standardization(asset, self.metadata())
        self.assertEqual(result['family_slug'], 'anima-2.9b')
        self.assertEqual(result['category'], '图像生成')

    def test_finished_local_anima29_uses_verified_release_identity(self):
        asset = self.asset(path='ComfyUI/models/loras/anima/自训角色/alicia_bell_morning_star_anima29_r32_v1.safetensors')
        asset['derivation'] = {'kind': 'local_training'}
        result = rules.build_standardization(asset, self.metadata(base='Anima'))
        self.assertEqual(result['family_slug'], 'anima-2.9b')
        self.assertEqual(result['category'], '自训角色')
        self.assertEqual(result['version'], 'v1')
        self.assertEqual(result['source_identity'], 'local_training:sha256=' + 'a' * 64)
        self.assertNotIn('cv200', result['target_path'])

    def test_unreviewed_local_checkpoint_cannot_be_promoted_to_finished_release(self):
        asset = self.asset(path='ComfyUI/models/loras/anima/自训角色/step0400.safetensors')
        asset['derivation'] = {'kind': 'local_training'}
        with self.assertRaisesRegex(ValueError, 'reviewed finished'):
            rules.build_standardization(asset, self.metadata())

    def test_same_version_multiple_files_use_selected_file_precision_and_identity(self):
        metadata = self.metadata(title='Same model')
        metadata['civitai']['files'] = [
            {'id': 300, 'metadata': {'fp': 'bf16'}},
            {'id': 301, 'metadata': {'fp': 'fp8'}},
        ]
        first = rules.build_standardization(self.asset(file_id=300), metadata)
        second = rules.build_standardization(self.asset(file_id=301), metadata)
        self.assertEqual(first['precision'], 'BF16')
        self.assertEqual(second['precision'], 'FP8')
        self.assertNotEqual(first['target_path'], second['target_path'])
        self.assertTrue(first['target_path'].endswith('__BF16__cv200__f300.safetensors'))
        self.assertTrue(second['target_path'].endswith('__FP8__cv200__f301.safetensors'))

    def test_missing_selected_file_does_not_borrow_another_files_precision(self):
        metadata = self.metadata()
        metadata['civitai']['files'] = [{'id': 301, 'metadata': {'fp': 'fp16'}}]
        result = rules.build_standardization(self.asset(file_id=300), metadata)
        self.assertIsNone(result['precision'])

    def test_int8_convrot_encoding_remains_distinct(self):
        asset = self.asset(path='ComfyUI/models/diffusion_models/krea2/fixture_int8_convrot.safetensors',
                           kind='diffusion_model', family='Krea2')
        metadata = self.metadata(base='Krea2')
        metadata['civitai']['files'] = [{'id': 300, 'metadata': {'fp': 'int8'}}]
        result = rules.build_standardization(asset, metadata)
        self.assertEqual(result['precision'], 'INT8-ConvRot')

    def test_public_plan_excludes_private_and_freely_written_sidecar_fields(self):
        asset = self.asset()
        metadata = self.metadata()
        marker = 'PRIVATE_SYNTHETIC_FIXTURE'
        metadata.update({'notes': marker, 'usage_tips': marker, 'cookie': marker,
                         'api_key': marker, 'images': [{'prompt': marker}],
                         'arbitrary_extension': {'private': marker}})
        metadata['civitai']['model']['description'] = marker
        metadata['civitai']['images'] = [{'meta': {'prompt': marker}}]
        before = copy.deepcopy(metadata)
        result = rules.build_standardization(asset, metadata)
        self.assertNotIn(marker, json.dumps(result, ensure_ascii=False))
        self.assertEqual(metadata, before)
        self.assertEqual(set(result), {'family_slug', 'family_label', 'category',
            'display_name', 'version', 'precision', 'source_identity', 'target_path', 'evidence'})

    def test_source_and_sidecar_version_disagreement_rejected(self):
        metadata = self.metadata()
        metadata['civitai']['id'] = 201
        with self.assertRaisesRegex(ValueError, 'selected version'):
            rules.build_standardization(self.asset(), metadata)

    def test_source_and_sidecar_model_disagreement_rejected(self):
        metadata = self.metadata()
        metadata['civitai']['modelId'] = 101
        with self.assertRaisesRegex(ValueError, 'selected model'):
            rules.build_standardization(self.asset(), metadata)

    def test_deleted_entries_are_rejected_even_when_they_have_a_release_name(self):
        asset = self.asset(path='ComfyUI/models/loras/anima/自训角色/rosasha_anima_r32_v1.safetensors')
        asset['observed_present'] = False
        with self.assertRaisesRegex(ValueError, 'Deleted or absent'):
            rules.build_standardization(asset, self.metadata())

    def test_missing_version_and_digest_cannot_claim_stable_identity(self):
        asset = self.asset()
        asset.update({'sources': [], 'local_sha256': None})
        with self.assertRaisesRegex(ValueError, 'verified content identity'):
            rules.build_standardization(asset, self.metadata())

    def test_original_capture_path_is_not_mutated(self):
        asset, metadata = self.asset(), self.metadata()
        original = copy.deepcopy(asset)
        rules.build_standardization(asset, metadata)
        self.assertEqual(asset, original)

    def test_invalid_scope_and_kind_root_disagreement_rejected(self):
        for overrides in [
            {'path': '../ComfyUI/models/loras/fixture.safetensors'},
            {'path': '/ComfyUI/models/loras/fixture.safetensors'},
            {'path': 'ComfyUI/models/checkpoints/fixture.safetensors'},
            {'path': 'ComfyUI/models/loras/fixture.txt'},
            {'kind': 'vae'},
        ]:
            with self.subTest(overrides=overrides):
                asset = self.asset()
                asset.update(overrides)
                with self.assertRaises(ValueError):
                    rules.build_standardization(asset, self.metadata())

    def test_sanitize_controls_traversal_devices_and_hidden_delimiters(self):
        for value in ['CON', 'prn.txt', 'LPT1', '../bad\\name:*?<>|',
                      'name\x00\x01\n ', 'safe／unsafe', 'safe：unsafe', 'safe｜unsafe',
                      '．', '．．', 'ＣＯＮ', 'trailing. ']:
            with self.subTest(value=value):
                result = rules.sanitize_component(value)
                normalized = unicodedata.normalize('NFKC', result)
                self.assertTrue(result)
                self.assertLessEqual(len(result), 50)
                self.assertFalse(re.search(r'[<>:"/\\|?*\x00-\x1f]', normalized))
                self.assertNotIn(normalized, {'.', '..'})
                self.assertEqual(normalized, normalized.rstrip(' .'))
                self.assertFalse(re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', normalized))

    def test_sanitize_preserves_readable_unicode_and_enforces_length(self):
        self.assertEqual(unicodedata.normalize('NFKC', rules.sanitize_component('角色（晨星）')),
                         '角色(晨星)')
        self.assertEqual(rules.sanitize_component('x' * 100, max_length=8), 'x' * 8)
        for value in [None, 10]:
            with self.assertRaises(ValueError):
                rules.sanitize_component(value)
        with self.assertRaises(ValueError):
            rules.sanitize_component('x', max_length=0)


class MigrationHelpersTests(unittest.TestCase):
    def test_family_case_normalization_preserves_every_payload_and_file_identity(self):
        with tempfile.TemporaryDirectory(prefix='model-case-fixture-') as directory:
            runtime, evidence = Path(directory) / 'runtime', Path(directory) / 'receipts'
            evidence.mkdir()
            rows, originals = [], {}
            for loader, old_family, canonical in [
                ('diffusion_models', 'Anima', 'anima'),
                ('diffusion_models', 'Anima-2.9B', 'anima-2.9b'),
                ('checkpoints', 'Anima', 'anima'),
            ]:
                family = runtime / 'ComfyUI/models' / loader / old_family
                (family / '图像生成/nested').mkdir(parents=True)
                for suffix in ['.safetensors', '.metadata.json', '.jpeg']:
                    file = family / '图像生成/nested' / ('fixture' + suffix)
                    file.write_bytes((loader + old_family + suffix).encode('utf-8'))
                    destination = runtime / 'ComfyUI/models' / loader / canonical / file.relative_to(family)
                    originals[destination] = (file.read_bytes(), file.stat().st_ino)
                rows.append({'new_path': f'ComfyUI/models/{loader}/{canonical}/图像生成/nested/fixture.safetensors'})
            with patch.object(migration, 'quiet') as quiet:
                migration.normalize_family_directory_case(runtime, rows, evidence)
            quiet.assert_called_once_with()
            for file, (payload, inode) in originals.items():
                self.assertEqual(file.read_bytes(), payload)
                self.assertEqual(file.stat().st_ino, inode)
            for row in rows:
                parts = row['new_path'].split('/')
                loader_root = runtime.joinpath(*parts[:3])
                matches = [p for p in loader_root.iterdir() if p.name.casefold() == parts[3].casefold()]
                self.assertEqual([p.name for p in matches], [parts[3]])
                self.assertFalse(any(p.name.startswith('.naming-case-') for p in loader_root.iterdir()))
            journal = [json.loads(line) for line in (evidence / 'apply.jsonl').read_text('utf-8').splitlines()]
            self.assertEqual(len(journal), 3)
            self.assertTrue(all(row['event'] == 'family_case_normalized' for row in journal))
            with patch.object(migration, 'quiet'):
                migration.normalize_family_directory_case(runtime, rows, evidence)
            self.assertEqual(len((evidence / 'apply.jsonl').read_text('utf-8').splitlines()), 3)

    def test_family_case_normalization_refuses_occupied_temporary_folder(self):
        with tempfile.TemporaryDirectory(prefix='model-case-busy-fixture-') as directory:
            runtime, evidence = Path(directory) / 'runtime', Path(directory) / 'receipts'
            evidence.mkdir()
            root = runtime / 'ComfyUI/models/diffusion_models'
            old = root / 'Anima'
            old.mkdir(parents=True)
            weight = old / 'fixture.safetensors'
            weight.write_bytes(b'synthetic preserved payload')
            (root / '.naming-case-anima').mkdir()
            rows = [{'new_path': 'ComfyUI/models/diffusion_models/anima/fixture.safetensors'}]
            with patch.object(migration, 'quiet'), self.assertRaisesRegex(ValueError, 'temporary folder'):
                migration.normalize_family_directory_case(runtime, rows, evidence)
            self.assertEqual(weight.read_bytes(), b'synthetic preserved payload')
            self.assertFalse((evidence / 'apply.jsonl').exists())

    def test_family_case_normalization_refuses_ambiguous_directory_inventory(self):
        with tempfile.TemporaryDirectory(prefix='model-case-ambiguous-fixture-') as directory:
            runtime, evidence = Path(directory) / 'runtime', Path(directory) / 'receipts'
            evidence.mkdir()
            old = runtime / 'ComfyUI/models/diffusion_models/Anima'
            old.mkdir(parents=True)
            weight = old / 'fixture.safetensors'
            weight.write_bytes(b'unchanged fixture')
            rows = [{'new_path': 'ComfyUI/models/diffusion_models/anima/fixture.safetensors'}]
            # NTFS cannot usually create two directory entries differing only
            # by case; simulate the inventory ambiguity without making one.
            with patch.object(migration, 'quiet'), \
                    patch.object(Path, 'iterdir', return_value=iter([old, old.with_name('ANIMA')])), \
                    self.assertRaisesRegex(ValueError, 'ambiguous'):
                migration.normalize_family_directory_case(runtime, rows, evidence)
            self.assertEqual(weight.read_bytes(), b'unchanged fixture')
            self.assertFalse((evidence / 'apply.jsonl').exists())

    def test_family_case_normalization_refuses_linked_family_directory(self):
        with tempfile.TemporaryDirectory(prefix='model-case-link-fixture-') as directory:
            runtime, evidence = Path(directory) / 'runtime', Path(directory) / 'receipts'
            root, outside = runtime / 'ComfyUI/models/diffusion_models', Path(directory) / 'outside'
            evidence.mkdir()
            root.mkdir(parents=True)
            outside.mkdir()
            weight = outside / 'fixture.safetensors'
            weight.write_bytes(b'outside fixture is preserved')
            try:
                (root / 'Anima').symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest('Host does not permit synthetic symlink creation: ' + str(error))
            rows = [{'new_path': 'ComfyUI/models/diffusion_models/anima/fixture.safetensors'}]
            with patch.object(migration, 'quiet'), self.assertRaisesRegex(ValueError, 'Linked'):
                migration.normalize_family_directory_case(runtime, rows, evidence)
            self.assertEqual(weight.read_bytes(), b'outside fixture is preserved')
            self.assertFalse((evidence / 'apply.jsonl').exists())

    def test_family_case_normalization_restores_original_after_second_rename_failure(self):
        with tempfile.TemporaryDirectory(prefix='model-case-rollback-fixture-') as directory:
            runtime, evidence = Path(directory) / 'runtime', Path(directory) / 'receipts'
            evidence.mkdir()
            root = runtime / 'ComfyUI/models/diffusion_models'
            old = root / 'Anima'
            old.mkdir(parents=True)
            weight = old / 'fixture.safetensors'
            weight.write_bytes(b'synthetic rollback payload')
            inode = weight.stat().st_ino
            rows = [{'new_path': 'ComfyUI/models/diffusion_models/anima/fixture.safetensors'}]
            rename = Path.rename
            def fail_second(path, target):
                if path.name == '.naming-case-anima' and Path(target).name == 'anima':
                    raise OSError('synthetic second rename failure')
                return rename(path, target)
            with patch.object(migration, 'quiet'), patch.object(Path, 'rename', new=fail_second), \
                    self.assertRaisesRegex(OSError, 'synthetic second rename'):
                migration.normalize_family_directory_case(runtime, rows, evidence)
            self.assertEqual(weight.read_bytes(), b'synthetic rollback payload')
            self.assertEqual(weight.stat().st_ino, inode)
            self.assertEqual([p.name for p in root.iterdir()], ['Anima'])
            self.assertFalse((evidence / 'apply.jsonl').exists())

    def test_preparation_includes_literal_bracket_named_companions(self):
        # A real regression: pathlib.glob interprets an upstream [Anima] stem
        # as a character class, silently omitting its metadata and previews.
        with tempfile.TemporaryDirectory(prefix='model-plan-fixture-') as directory:
            base = Path(directory)
            repo, runtime, evidence = base / 'repo', base / 'runtime', base / 'receipts'
            source = repo / 'snapshot/inventory/model_sources.json'
            source.parent.mkdir(parents=True)
            relative = 'ComfyUI/models/loras/anima/画风与画师/Fixture [Anima].safetensors'
            weight = runtime / relative
            weight.parent.mkdir(parents=True)
            weight.write_bytes(b'isolated synthetic payload')
            asset = NamingRulesTests().asset(path=relative)
            asset['bytes'] = weight.stat().st_size
            source.write_text(json.dumps({'assets': [asset]}), encoding='utf-8')
            metadata = weight.with_suffix('.metadata.json')
            metadata.write_text(json.dumps(NamingRulesTests().metadata()), encoding='utf-8')
            preview = weight.with_suffix('.jpeg')
            preview.write_bytes(b'isolated synthetic preview')
            store = runtime / 'ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/fixture/user_data/prompt_selector'
            store.mkdir(parents=True)
            (store / 'data.json').write_text('{}', encoding='utf-8')
            with patch.object(migration, 'REPO', repo), patch.object(migration, 'quiet'), \
                    patch.object(migration, 'source_edits', return_value=[]), \
                    patch.object(migration.subprocess, 'check_output', return_value=b'fixture-head\n'), \
                    redirect_stdout(io.StringIO()):
                migration.prepare(runtime, evidence)
            plan = json.loads((evidence / 'plan.json').read_text(encoding='utf-8'))
            companions = plan['rows'][0]['companions']
            self.assertEqual({Path(row['old_path']).name for row in companions},
                             {metadata.name, preview.name})
            for row in companions:
                self.assertTrue((evidence / 'before-companions' / row['old_path']).is_file())

    def test_protected_metadata_retains_unknown_and_personal_fields(self):
        original = {
            'file_name': 'old', 'file_path': 'old/path', 'model_name': 'old display',
            'preview_url': 'old/preview', 'organization': {'family': 'old'},
            'original_file_name': 'download', 'sub_type': 'lora',
            'notes': 'Synthetic note', 'favorite': True, 'exclude': True,
            'usage_tips': {'strength': 0.7}, 'usage_count': 19, 'tags': ['tag'],
            'auto_tags': ['automatic'], 'civitai': {'id': 200, 'trainedWords': ['token']},
            'sha256': 'a' * 64, 'autov3': 'b' * 12,
            'source_url': 'https://example.com/models/fixture',
            'unknown_future_extension': {'preserve': True},
        }
        protected = migration.protected(original)
        self.assertEqual(set(protected), set(original) - migration.ALLOWED_METADATA_CHANGES)
        changed = copy.deepcopy(original)
        for key in migration.ALLOWED_METADATA_CHANGES:
            changed[key] = 'new fixture value'
        self.assertEqual(migration.protected(changed), protected)
        changed['unknown_future_extension']['preserve'] = False
        self.assertNotEqual(migration.protected(changed), protected)

    def test_protected_organization_retains_unrelated_and_private_fields(self):
        original = {'organization': {'family': 'Old family', 'purpose': 'Old category',
            'official_name': 'Old name', 'version': 'v1', 'precision': 'FP16',
            'naming_policy': 'old', 'reviewer_note': 'Private synthetic fixture',
            'future_extension': {'preserve': True}}}
        changed = copy.deepcopy(original)
        for key in migration.ALLOWED_ORGANIZATION_CHANGES:
            changed['organization'][key] = 'new'
        self.assertEqual(migration.protected(original), migration.protected(changed))
        changed['organization']['future_extension']['preserve'] = False
        self.assertNotEqual(migration.protected(original), migration.protected(changed))
        self.assertEqual(migration.protected(original)['organization'],
                         {'reviewer_note': 'Private synthetic fixture',
                          'future_extension': {'preserve': True}})

    def test_rewrite_nested_paths_dictionary_keys_and_serialized_widgets(self):
        mapping = {'old/model.safetensors': 'anima/new/model.safetensors'}
        original = {'old/model.safetensors': {'widgets': ['old/model.safetensors'],
            'serialized': json.dumps({'lora_name': 'old/model.safetensors'}),
            'prompt': 'Use old/model.safetensors as prose'}}
        updated = migration.rewrite(original, mapping)
        self.assertIn('anima/new/model.safetensors', updated)
        body = updated['anima/new/model.safetensors']
        self.assertEqual(body['widgets'], ['anima/new/model.safetensors'])
        self.assertEqual(json.loads(body['serialized']), {'lora_name': 'anima/new/model.safetensors'})
        self.assertEqual(body['prompt'], original['old/model.safetensors']['prompt'])
        self.assertIn('old/model.safetensors', original)

    def test_download_declarations_and_remote_urls_keep_upstream_identity(self):
        old, new = 'upstream.safetensors', 'local/renamed.safetensors'
        declaration = {'name': old, 'url': 'https://example.com/resolve/main/' + old,
                       'directory': 'checkpoints', 'metadata': {'name': old}}
        original = {'selector': old, 'models': [declaration],
                    'url': 'https://example.com/' + old}
        updated = migration.rewrite(original, {old: new})
        self.assertEqual(updated['selector'], new)
        self.assertEqual(updated['models'][0], declaration)
        self.assertEqual(updated['url'], original['url'])

    def test_ambiguous_basenames_do_not_choose_an_arbitrary_model(self):
        rows = [
            {'old_path': 'ComfyUI/models/loras/anima/a/same.safetensors',
             'new_path': 'ComfyUI/models/loras/anima/a/new-a.safetensors'},
            {'old_path': 'ComfyUI/models/loras/krea2/b/same.safetensors',
             'new_path': 'ComfyUI/models/loras/krea2/b/new-b.safetensors'},
        ]
        mapping = migration.aliases(rows)
        self.assertNotIn('same.safetensors', mapping)
        self.assertEqual(mapping['anima/a/same.safetensors'], 'anima/a/new-a.safetensors')
        self.assertEqual(mapping['krea2\\b\\same.safetensors'], 'krea2\\b\\new-b.safetensors')
        self.assertEqual(migration.rewrite('same.safetensors', mapping), 'same.safetensors')

    def test_root_level_basename_alias_slash_variants_are_one_target(self):
        rows = [
            {'old_path': 'ComfyUI/models/checkpoints/sam3.1_multiplex_fp16.safetensors',
             'new_path': 'ComfyUI/models/checkpoints/sam3.1/目标检测与分割/SAM3.1__fixture.safetensors'},
            {'old_path': 'ComfyUI/models/diffusion_models/qwen-image-2.1-UC-BF16.gguf',
             'new_path': 'ComfyUI/models/diffusion_models/qwen-image-2.1/图像生成/Qwen__BF16.gguf'},
        ]
        mapping = migration.aliases(rows)
        for row in rows:
            old_name = Path(row['old_path']).name
            expected = '/'.join(row['new_path'].split('/')[3:])
            with self.subTest(old_name=old_name):
                self.assertIn(old_name, mapping)
                self.assertEqual(mapping[old_name], expected)
                self.assertNotIn('\\', mapping[old_name])
                self.assertEqual(migration.rewrite(old_name, mapping), expected)

    def test_source_edit_candidates_change_exact_private_paths_and_preserve_urls(self):
        with tempfile.TemporaryDirectory(prefix='model-reference-fixture-') as directory:
            base = Path(directory)
            repo, runtime, evidence = base / 'repo', base / 'runtime', base / 'receipts'
            row = {'old_path': 'ComfyUI/models/diffusion_models/Anima-2.9B/fixture.safetensors',
                   'new_path': 'ComfyUI/models/diffusion_models/anima-2.9b/图像生成/Anima-2.9B__fixture.safetensors'}
            relative = 'anima_lora_forge/templates/profile.fixture.json'
            source, live = repo / 'snapshot/runtime' / relative, runtime / relative
            source.parent.mkdir(parents=True)
            live.parent.mkdir(parents=True)
            release = str(runtime / 'anima_lora_forge/releases/fixture/fixture.safetensors')
            remote = 'https://example.com/resolve/main/fixture.safetensors'
            original = {'models': {
                'absolute': str(runtime / row['old_path']),
                'absolute_posix': (runtime / row['old_path']).as_posix(),
                'root_relative': row['old_path'],
                'forge_relative': '../' + row['old_path'],
                'release_copy': release},
                'download': {'name': 'fixture.safetensors', 'url': remote},
                'source_url': remote,
                'private_note': 'Synthetic note mentioning fixture.safetensors stays unchanged'}
            raw = (json.dumps(original, ensure_ascii=False) + '\n').encode('utf-8')
            source.write_bytes(raw)
            live.write_bytes(raw)
            with patch.object(migration, 'REPO', repo), \
                    patch.object(migration, 'deployment_candidates', return_value=iter([source])):
                edits = migration.source_edits([row], runtime, evidence)
            self.assertEqual(len(edits), 1)
            candidate = json.loads((evidence / 'candidate-sources' / relative).read_text(encoding='utf-8'))
            self.assertEqual(candidate['models']['absolute'], str(runtime / row['new_path']))
            self.assertEqual(candidate['models']['absolute_posix'], (runtime / row['new_path']).as_posix())
            self.assertEqual(candidate['models']['root_relative'], row['new_path'])
            self.assertEqual(candidate['models']['forge_relative'], '../' + row['new_path'])
            self.assertEqual(candidate['models']['release_copy'], release)
            self.assertEqual(candidate['download'], original['download'])
            self.assertEqual(candidate['source_url'], remote)
            self.assertEqual(candidate['private_note'], original['private_note'])
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(live.read_bytes(), raw)

    def test_equal_target_aliases_are_removed(self):
        mapping = migration.aliases([{'old_path': 'ComfyUI/models/loras/model.safetensors',
                                     'new_path': 'ComfyUI/models/loras/model.safetensors'}])
        self.assertNotIn('ComfyUI/models/loras/model.safetensors', mapping)

    def test_safe_paths_reject_traversal_absolute_devices_and_hidden_segments(self):
        with tempfile.TemporaryDirectory(prefix='model-path-fixture-') as directory:
            root = Path(directory)
            for value in ['../escape', '/absolute', 'C:/absolute', 'folder\\escape',
                          'folder//empty', 'folder/../escape', '.git/object',
                          'folder/CON', 'folder/name. ', 'folder／escape/model', '．．/escape']:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    migration.safe(root, value)
            self.assertEqual(migration.safe(root, 'ComfyUI/models/loras/new/model.safetensors'),
                             root / 'ComfyUI/models/loras/new/model.safetensors')

    def test_safe_paths_reject_linked_parent_and_weight(self):
        with tempfile.TemporaryDirectory(prefix='model-links-fixture-') as directory:
            root = Path(directory) / 'root'
            outside = Path(directory) / 'outside'
            root.mkdir()
            outside.mkdir()
            weight = outside / 'weight.safetensors'
            weight.write_bytes(b'synthetic weight')
            try:
                (root / 'linked').symlink_to(outside, target_is_directory=True)
                (root / 'weight.safetensors').symlink_to(weight)
            except OSError as error:
                self.skipTest('Host does not permit synthetic symlink creation: ' + str(error))
            for relative in ['linked/new/weight.safetensors', 'weight.safetensors']:
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'Linked'):
                    migration.safe(root, relative)

    def test_legacy_sidecar_repairs_only_local_identity_and_local_preview_query(self):
        old = 'anima/old.safetensors'
        new = 'anima/画风与画师/new.safetensors'
        local = '/weilin/prompt_ui/api/lorainfo/api/loras/img?file=anima%5Cold.safetensors&keep=yes'
        remote = 'https://example.com/images/old.safetensors?file=anima/old.safetensors'
        original = {'file': old, 'path': 'old absolute fixture',
            'images': [{'url': local}, {'url': remote}, {'url': '/different?file=' + old}],
            'userNote': 'Synthetic private note', 'trainedWords': ['keep token'],
            'raw': {'civitai': {'downloadUrl': 'https://example.com/old.safetensors'}},
            'name': 'Original source name', 'baseModelFile': 'Keep original reference'}
        with tempfile.TemporaryDirectory(prefix='model-sidecar-fixture-') as directory:
            file = Path(directory) / 'fixture.weilin-info.json'
            target = Path(directory) / 'new.safetensors'
            file.write_text(json.dumps(original), encoding='utf-8')
            migration.update_shared_info(file, old, new, target)
            updated = json.loads(file.read_text(encoding='utf-8'))
        self.assertEqual(updated['file'], new)
        self.assertEqual(updated['path'], str(target))
        query = dict(migration.parse_qsl(migration.urlsplit(updated['images'][0]['url']).query))
        self.assertEqual(query, {'file': new, 'keep': 'yes'})
        self.assertEqual(updated['images'][1:], original['images'][1:])
        for key in ['userNote', 'trainedWords', 'raw', 'name', 'baseModelFile']:
            self.assertEqual(updated[key], original[key])


class CacheVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='model-cache-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name) / 'runtime'
        self.plan = {'runtime': str(self.runtime), 'rows': []}
        self.views = {prefix: {'list': [], 'excluded': []} for prefix in ('loras', 'checkpoints')}
        self.requests = []
        self.preserved = {}

    def model(self, name, *, excluded=False, planned=True, kind='lora'):
        prefix = 'loras' if kind == 'lora' else 'checkpoints'
        loader = 'loras' if kind == 'lora' else 'diffusion_models'
        relative = f'ComfyUI/models/{loader}/anima/fixture/{name}.safetensors'
        target = self.runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'isolated synthetic model')
        metadata = target.with_suffix('.metadata.json')
        metadata.write_text(json.dumps({'exclude': excluded, 'notes': 'Private synthetic fixture'}),
                            encoding='utf-8')
        self.preserved[target] = target.read_bytes()
        self.preserved[metadata] = metadata.read_bytes()
        self.views[prefix]['excluded' if excluded else 'list'].append({'file_path': target.as_posix()})
        row = {'kind': kind, 'new_path': relative,
               'old_path': f'ComfyUI/models/{loader}/old/{name}.safetensors',
               'baseline_excluded': excluded}
        if planned:
            self.plan['rows'].append(row)
        return row

    def response(self, route, body=None):
        self.assertIsNone(body, 'Cache verification must use read-only requests')
        self.requests.append(route)
        parsed = migration.urlsplit(route)
        _, api, lm, prefix, view = parsed.path.split('/')
        self.assertEqual((api, lm), ('api', 'lm'))
        self.assertIn(view, {'list', 'excluded'})
        query = dict(migration.parse_qsl(parsed.query))
        self.assertEqual(query['page_size'], '100')
        page = int(query['page'])
        items = self.views[prefix][view]
        pages = max(1, (len(items) + 99) // 100)
        return {'items': copy.deepcopy(items[(page - 1) * 100:page * 100]),
                'total': len(items), 'page': page, 'page_size': 100, 'total_pages': pages}

    def verify(self, response=None):
        with patch.object(migration, 'api', side_effect=response or self.response):
            return migration.verify_model_caches(self.plan)

    def test_regular_and_hidden_identities_across_pages_keep_unplanned_items(self):
        first = self.model('first')
        for index in range(99):
            self.model(f'unplanned-{index:03}', planned=False)
        last = self.model('last')
        self.model('hidden', excluded=True)
        self.model('base', kind='diffusion_model')
        if migration.os.name == 'nt':
            # Windows path identity is case-insensitive and tolerates either
            # slash form; the payload paths themselves remain untouched.
            self.views['loras']['list'][0]['file_path'] = str(self.runtime / first['new_path']).upper()
            self.views['loras']['list'][-1]['file_path'] = str(self.runtime / last['new_path'])
        counts = self.verify()
        self.assertEqual(counts, {'loras': {'regular': 101, 'excluded': 1},
                                  'checkpoints': {'regular': 1, 'excluded': 0}})
        self.assertIn('/api/lm/loras/list?page=2&page_size=100', self.requests)
        self.assertEqual(len(self.views['loras']['list']), 101)
        for file, payload in self.preserved.items():
            self.assertEqual(file.read_bytes(), payload)

    def test_hidden_identity_in_regular_cache_is_rejected(self):
        self.model('hidden', excluded=True)
        hidden = self.views['loras']['excluded'].pop()
        self.views['loras']['list'].append(hidden)
        with self.assertRaisesRegex(ValueError, 'expected cache view'):
            self.verify()

    def test_same_identity_in_both_views_is_rejected(self):
        self.model('visible')
        self.views['loras']['excluded'].append(copy.deepcopy(self.views['loras']['list'][0]))
        with self.assertRaisesRegex(ValueError, 'both regular and excluded'):
            self.verify()

    def test_duplicate_identity_repeated_on_second_page_is_rejected(self):
        for index in range(101):
            self.model(f'model-{index:03}', planned=False)
        self.views['loras']['list'][-1] = copy.deepcopy(self.views['loras']['list'][0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.verify()

    def test_page_omission_cannot_pass_using_reported_total(self):
        for index in range(101):
            self.model(f'model-{index:03}', planned=False)
        def omit_second_page(route, body=None):
            result = self.response(route, body)
            if '/loras/list?' in route and result['page'] == 2:
                result['items'] = []
            return result
        with self.assertRaisesRegex(ValueError, 'omitted identities'):
            self.verify(omit_second_page)

    def test_total_page_count_drift_is_rejected_even_if_every_item_is_returned(self):
        for index in range(101):
            self.model(f'model-{index:03}', planned=False)
        def change_page_count(route, body=None):
            result = self.response(route, body)
            if '/loras/list?' in route and result['page'] == 2:
                result['total_pages'] = 1
            return result
        with self.assertRaisesRegex(ValueError, 'pagination changed'):
            self.verify(change_page_count)

    def test_total_identity_count_drift_is_rejected(self):
        for index in range(101):
            self.model(f'model-{index:03}', planned=False)
        def change_total(route, body=None):
            result = self.response(route, body)
            if '/loras/list?' in route and result['page'] == 2:
                result['total'] = 102
            return result
        with self.assertRaisesRegex(ValueError, 'pagination changed'):
            self.verify(change_total)

    def test_exclusion_flag_drift_from_reviewed_baseline_is_rejected(self):
        row = self.model('fixture', excluded=True)
        row['baseline_excluded'] = False
        with self.assertRaisesRegex(ValueError, 'Baseline exclusion'):
            self.verify()

    def test_old_identity_in_cache_is_rejected_while_current_identity_exists(self):
        row = self.model('fixture')
        self.views['loras']['list'].append({'file_path': str(self.runtime / row['old_path'])})
        with self.assertRaisesRegex(ValueError, 'Old model identity'):
            self.verify()

    def test_empty_caches_accept_zero_or_one_reported_page(self):
        for reported_pages in (0, 1):
            with self.subTest(reported_pages=reported_pages):
                def empty(route, body=None):
                    result = self.response(route, body)
                    result['total_pages'] = reported_pages
                    return result
                self.assertEqual(self.verify(empty),
                    {'loras': {'regular': 0, 'excluded': 0},
                     'checkpoints': {'regular': 0, 'excluded': 0}})

    def test_legacy_plan_without_new_exclusion_field_still_checks_expected_view(self):
        row = self.model('fixture', excluded=True)
        row.pop('baseline_excluded')
        self.assertEqual(self.verify()['loras'], {'regular': 0, 'excluded': 1})
        self.views['loras']['list'].append(self.views['loras']['excluded'].pop())
        with self.assertRaisesRegex(ValueError, 'expected cache view'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
