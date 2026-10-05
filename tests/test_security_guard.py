import contextlib
import gzip
import bz2
import lzma
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'security_guard.py'
SPEC = importlib.util.spec_from_file_location('comfyui_security_guard', SCRIPT)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class SecurityGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Security Tests')
        self.git('config', 'user.email', 'tests@local.invalid')
        self.write('README.md', b'Public example repository.\n')
        self.git('add', 'README.md')
        self.git('commit', '-m', 'Initial')

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout

    def write(self, path, value):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)

    @staticmethod
    def credential():
        # Assemble in memory; the tests themselves contain no credential literal.
        return b'sk-' + b'A1b2C3d4E5f6G7h8' * 3

    def test_staged_bytes_not_worktree(self):
        self.write('file.txt', self.credential())
        self.git('add', 'file.txt')
        self.write('file.txt', b'Safe replacement only in worktree')
        report = guard.run(self.repo, staged=True)
        self.assertFalse(report['pass'])
        self.assertIn('openai_style_key', {item['rule'] for item in report['findings']})
        self.assertNotIn(self.credential().decode(), json.dumps(report))

    def test_all_history_includes_deleted_secret(self):
        self.write('old.txt', self.credential())
        self.git('add', 'old.txt')
        self.git('commit', '-m', 'Old fixture')
        self.git('rm', 'old.txt')
        self.git('commit', '-m', 'Remove fixture')
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])
        self.assertFalse(guard.run(self.repo, staged=False)['pass'])

    def test_gzip_and_escaped_source_map(self):
        self.write('cache.json.gz', gzip.compress(json.dumps({'data': self.credential().decode()}).encode()))
        escaped = b'\\u0073\\u006b-' + self.credential()[3:]
        self.write('source.map', b'{"sourcesContent":["' + escaped + b'"]}')
        self.git('add', 'cache.json.gz', 'source.map')
        report = guard.run(self.repo, staged=True)
        rules = {item['rule'] for item in report['findings']}
        self.assertIn('gzip_openai_style_key', rules)
        self.assertIn('escaped_openai_style_key', rules)
        self.assertEqual(len(report['compressed_objects']), 1)

    def test_cross_part_boundary(self):
        key = self.credential()
        self.write('snapshot/library/json/data.json/00000.part', b'{"key":"' + key[:20])
        self.write('snapshot/library/json/data.json/00001.part', key[20:] + b'"}')
        self.git('add', 'snapshot')
        report = guard.run(self.repo, staged=True)
        self.assertEqual(report['cross_part_boundaries'], 1)
        self.assertIn('cross_part_openai_style_key', {item['rule'] for item in report['findings']})

    def test_forbidden_payload_paths(self):
        for path in ['.env', 'model.safetensors', 'file.db-wal', 'nested/.cache/x.json', 'id_rsa', 'plugin/credentials.json']:
            self.assertTrue(guard.blocked_path(path), path)
        self.assertFalse(guard.blocked_path('snapshot/library/sql/userdatas.db/00000.part'))
        self.assertFalse(guard.blocked_path('src/authorization.py'))
        self.assertFalse(guard.blocked_path('comfy/text_encoders/t5_pile_tokenizer/added_tokens.json'))

    def test_short_placeholder_and_real_assignment(self):
        self.assertFalse(guard.patterns(b'api_key = "your-api-key"'))
        candidate = b'api_key = "' + b'B94WnbS8FJY75FsVD73B3vR9' + b'"'
        self.assertIn('literal_credential_assignment', guard.patterns(candidate))
        self.assertIn('url_credential_query', guard.patterns(b'https://local.invalid/?api_key=' + candidate.split(b'"')[1]))

    def test_boundary_inside_blob(self):
        scanner = guard.StreamScanner()
        scanner.feed(self.credential()[:20])
        scanner.feed(self.credential()[20:])
        self.assertIn('openai_style_key', scanner.findings)

    def test_fixture_requires_exact_sha(self):
        payload = self.credential()
        digest = guard.hashlib.sha256(payload).hexdigest()
        try:
            guard.REVIEWED_FIXTURES[digest] = 'explicit_test_fixture'
            guard.FIXTURE_ENDS[digest] = 'fixture.txt'
            self.write('fixture.txt', payload)
            self.git('add', 'fixture.txt')
            self.assertTrue(guard.run(self.repo, staged=True)['pass'])
            self.write('fixture.txt', payload + b' changed')
            self.git('add', 'fixture.txt')
            self.assertFalse(guard.run(self.repo, staged=True)['pass'])
        finally:
            guard.REVIEWED_FIXTURES.pop(digest, None)
            guard.FIXTURE_ENDS.pop(digest, None)

    def test_corrupt_gzip_is_rejected(self):
        self.write('invalid.gz', b'\x1f\x8b' + b'invalid compressed payload')
        self.git('add', 'invalid.gz')
        report = guard.run(self.repo, staged=True)
        self.assertFalse(report['pass'])
        self.assertTrue(any('gzip' in item['rule'] for item in report['findings']))

    def test_sql_pair_and_utf16(self):
        self.assertIn('sql_credential_key_value', guard.patterns(b"('api_key','" + b'Q94WnbS8FJY75FsVD73B3vR9' + b"')"))
        scanner = guard.StreamScanner()
        scanner.feed(self.credential().decode().encode('utf-16-le'))
        self.assertIn('nul_encoded_openai_style_key', scanner.findings)

    def test_historical_boundary_is_not_lost(self):
        value = self.credential()
        self.write('parts/00000.part', value[:20])
        self.write('parts/00001.part', value[20:])
        self.git('add', 'parts')
        self.git('commit', '-m', 'Historical parts')
        self.write('parts/00000.part', b'Safe first part')
        self.write('parts/00001.part', b'Safe second part')
        self.git('add', 'parts')
        self.git('commit', '-m', 'New parts')
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])
        history = guard.run(self.repo, staged=False)
        self.assertFalse(history['pass'])
        self.assertTrue(any(item['rule'] == 'cross_part_openai_style_key' for item in history['findings']))

    def test_bare_repo_and_historical_aliases(self):
        self.write('safe.json', b'{}')
        self.git('add', 'safe.json')
        self.git('commit', '-m', 'Shared blob')
        self.write('private/credentials.json', b'{}')
        self.git('add', 'private')
        self.git('commit', '-m', 'Path alias')
        self.git('rm', 'private/credentials.json')
        self.git('commit', '-m', 'Removed alias')
        bare = self.repo / 'bare.git'
        self.git('clone', '--bare', str(self.repo), str(bare))
        report = guard.run(bare, staged=False)
        self.assertFalse(report['pass'])
        self.assertTrue(any(item['path'] == 'private/credentials.json' for item in report['findings']))

    def test_concatenated_gzip(self):
        self.write('joined.gz', gzip.compress(b'First member\n') + gzip.compress(self.credential()))
        self.git('add', 'joined.gz')
        report = guard.run(self.repo, staged=True)
        self.assertIn('gzip_openai_style_key', {item['rule'] for item in report['findings']})

    def test_source_expressions_are_not_credentials(self):
        for source in [b'class_token = self.tokens.repeat(1)', b'token = torch.flatten(source)', b'token = "backbone.model.cls_token"']:
            self.assertFalse(guard.patterns(source), source)

    def test_precise_external_resource_paths(self):
        for folder in ['input', 'output', 'temp', 'models']:
            self.assertIn('external_runtime_asset_payload', guard.blocked_path('snapshot/runtime/ComfyUI/' + folder + '/sample.png'))
        for folder in ['preview', 'preview_thumbnails']:
            path = 'snapshot/runtime/ComfyUI/custom_nodes/module/user_data/prompt_selector/' + folder + '/small.png'
            self.assertIn('external_library_preview_payload', guard.blocked_path(path))
        for path in ['snapshot/runtime/ComfyUI/comfy_api/input/types.py', 'snapshot/runtime/ComfyUI/comfy/ldm/models/model.py',
                     'assets/examples/preview.svg', 'examples/models/README.md',
                     'snapshot/runtime/ComfyUI/custom_nodes/comfyui-anima-tools/data/shared_prompt_cache/artist.json.gz']:
            self.assertFalse(guard.blocked_path(path), path)

    def test_zip_members_scanned_without_extraction(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('member.txt', self.credential())
        self.write('payload.zip', output.getvalue())
        self.git('add', 'payload.zip')
        report = guard.run(self.repo, staged=True)
        self.assertIn('zip_openai_style_key', {item['rule'] for item in report['findings']})
        self.assertFalse((self.repo / 'member.txt').exists())

    def test_zip_private_file_and_traversal_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('../.env', 'EMPTY=1')
        rules, metadata = guard.scan_zip_payload(output.getvalue())
        self.assertIn('unsafe_archive_member_path', rules)
        self.assertIn('archive_private_credential_file', rules)

    def test_manifest_part_order_is_scanned(self):
        token = self.credential()
        self.write('snapshot/library/data/c.part', token[:20])
        self.write('snapshot/library/data/a.part', token[20:])
        self.write('snapshot/library/data/b.part', b'Unrelated lexical middle part')
        manifest = {'files': [{'path': 'library/data', 'parts': [{'path': 'c.part'}, {'path': 'a.part'}, {'path': 'b.part'}]}]}
        self.write('snapshot/manifest.json', json.dumps(manifest).encode())
        self.git('add', 'snapshot')
        report = guard.run(self.repo, staged=True)
        self.assertTrue(any(item['rule'] == 'cross_part_openai_style_key' for item in report['findings']))

    def test_nested_gzip_archive_is_rejected(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('secret.txt', self.credential())
        wrapped = gzip.compress(inner.getvalue())
        self.write('wrapped.gz', wrapped)
        self.git('add', 'wrapped.gz')
        report = guard.run(self.repo, staged=True)
        self.assertIn('nested_archive_requires_review', {item['rule'] for item in report['findings']})
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('bundle.gz', wrapped)
        rules, _ = guard.scan_zip_payload(outer.getvalue())
        self.assertIn('nested_archive_requires_review', rules)

    def test_unsupported_archive_signatures_and_suffixes(self):
        samples = [bz2.compress(self.credential()), lzma.compress(self.credential()), b'\x28\xb5\x2f\xfddata',
                   b'7z\xbc\xaf\x27\x1cdata', b'Rar!data', b'\0' * 257 + b'ustar' + b'data']
        for sample in samples:
            self.assertIsNotNone(guard.archive_magic(sample))
            self.write('opaque.dat', sample)
            self.git('add', 'opaque.dat')
            report = guard.run(self.repo, staged=True)
            self.assertIn('unsupported_archive_requires_review', {item['rule'] for item in report['findings']})
        for extension in ['.bz2', '.xz', '.zst', '.7z', '.rar', '.tar']:
            self.assertIn('unsupported_archive_suffix', guard.blocked_path('data' + extension))

    def test_pre_push_rejects_unreferenced_sha(self):
        tree = self.git('rev-parse', 'HEAD^{tree}').decode().strip()
        raw = subprocess.check_output(['git', '-C', str(self.repo), 'commit-tree', tree], input=b'Orphan candidate\n')
        orphan = raw.decode().strip()
        report = guard.run_pre_push(self.repo, f'{orphan} {orphan} refs/heads/upload ' + '0' * 40)
        self.assertFalse(report['pass'])
        self.assertEqual(report['findings'][0]['rule'], 'unscanned_unreferenced_push_root')

    def test_pre_push_main_and_deletion(self):
        oid = self.git('rev-parse', 'HEAD').decode().strip()
        self.assertTrue(guard.run_pre_push(self.repo, f'refs/heads/main {oid} refs/heads/main ' + '0' * 40)['pass'])
        self.assertTrue(guard.run_pre_push(self.repo, '(delete) ' + '0' * 40 + f' refs/heads/old {oid}')['pass'])
        with self.assertRaises(ValueError):
            guard.run_pre_push(self.repo, 'malformed push record')


if __name__ == '__main__':
    unittest.main()
