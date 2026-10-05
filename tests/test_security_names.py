"""Strong-only Git name checks; fixtures never contain a real credential."""
import gzip
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/security_guard.py'
SPEC = importlib.util.spec_from_file_location('security_names_guard', SCRIPT)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class SecurityNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@invalid.local')
        self.write('README.md', b'public fixture\n')
        self.git('add', 'README.md'); self.git('commit', '-m', 'fixture')

    def git(self, *args, data=None):
        result = subprocess.run(['git', '-C', str(self.repo), *args], input=data, capture_output=True)
        if result.returncode:
            self.fail('Fixture Git command failed; command/output withheld')
        return result.stdout

    def write(self, relative, value):
        path = self.repo / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def value(self):
        return 'sk-' + 'A1b2C3d4E5f6G7h8' * 3

    def assert_hidden_failure(self, report, rule):
        self.assertFalse(report.get('pass', not report['findings']))
        self.assertIn(rule, {item['rule'] for item in report['findings']})
        self.assertNotIn(self.value(), json.dumps(report))
        matching = [item for item in report['findings'] if item['rule'] == rule]
        self.assertTrue(all(item['path'].startswith('<redacted-name:sha256:') for item in matching))

    def test_staged_filename_is_checked_without_payload_secret(self):
        name = 'folder/' + self.value() + '.txt'
        self.write(name, b'innocuous file body'); self.git('add', '--', name)
        self.assert_hidden_failure(guard.run(self.repo, staged=True), 'filename_openai_style_key')
        self.assert_hidden_failure(guard.scan_names(self.repo, staged=True), 'filename_openai_style_key')

    def test_deleted_historical_name_still_fails_but_current_stage_is_clean(self):
        name = self.value() + '.txt'
        self.write(name, b'innocuous file body'); self.git('add', '--', name)
        self.git('commit', '-m', 'historical name')
        self.git('mv', '--', name, 'safe.txt'); self.git('commit', '-m', 'safe current name')
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])
        self.assert_hidden_failure(guard.run(self.repo), 'filename_openai_style_key')
        self.assert_hidden_failure(guard.scan_names(self.repo), 'filename_openai_style_key')

    def test_branch_name_fails_both_gates_and_refs_are_opaque(self):
        self.git('update-ref', 'refs/heads/' + self.value(), 'HEAD')
        for staged in [True, False]:
            report = guard.run(self.repo, staged=staged)
            self.assert_hidden_failure(report, 'refname_openai_style_key')
            self.assertEqual(report['refs'], guard.refs(self.repo))

    def test_unborn_symbolic_head_name_is_checked_before_first_commit(self):
        self.git('symbolic-ref', 'HEAD', 'refs/heads/' + self.value())
        self.assert_hidden_failure(guard.run(self.repo, staged=True), 'refname_openai_style_key')

    def test_lightweight_tag_ref_name_is_checked_without_tag_payload(self):
        self.git('update-ref', 'refs/tags/' + self.value(), 'HEAD')
        self.assert_hidden_failure(guard.run(self.repo), 'refname_openai_style_key')

    def test_direct_scanner_call_cannot_skip_reference_names(self):
        self.git('update-ref', 'refs/heads/' + self.value(), 'HEAD')
        self.assert_hidden_failure(guard.scan_objects(self.repo, []), 'refname_openai_style_key')

    def test_pre_push_remote_ref_name_is_checked_and_deletion_is_allowed(self):
        head = self.git('rev-parse', 'HEAD').decode().strip()
        record = 'refs/heads/main ' + head + ' refs/heads/' + self.value() + ' ' + '0' * 40
        self.assert_hidden_failure(guard.run_pre_push(self.repo, record), 'push_refname_openai_style_key')
        deletion = '(delete) ' + '0' * 40 + ' refs/heads/' + self.value() + ' ' + head
        report = guard.run_pre_push(self.repo, deletion)
        self.assertTrue(report['pass'])
        self.assertNotIn(self.value(), json.dumps(report))

    def test_gitlink_name_stays_redacted_in_both_name_and_payload_findings(self):
        self.git('update-index', '--add', '--cacheinfo', '160000', 'a' * 40, self.value())
        report = guard.run(self.repo, staged=True)
        self.assert_hidden_failure(report, 'filename_openai_style_key')
        self.assertIn('nested_gitlink', {item['rule'] for item in report['findings']})
        self.assert_hidden_failure(guard.run(self.repo, staged=True, content_only=True), 'filename_openai_style_key')

    def test_empty_directory_tree_name_is_not_skipped(self):
        empty = self.git('hash-object', '-w', '-t', 'tree', '--stdin', data=b'').decode().strip()
        raw = b'40000 ' + self.value().encode() + b'\0' + bytes.fromhex(empty)
        root = self.git('hash-object', '-w', '-t', 'tree', '--stdin', data=raw).decode().strip()
        commit = self.git('commit-tree', root, '-m', 'empty directory fixture').decode().strip()
        self.git('update-ref', 'refs/heads/tree', commit)
        self.assert_hidden_failure(guard.run(self.repo), 'filename_openai_style_key')
        self.assert_hidden_failure(guard.scan_names(self.repo), 'filename_openai_style_key')

    def test_name_check_does_not_apply_generic_assignment_or_entropy_rules(self):
        name = 'api_key=' + 'Q94WnbS8FJY75FsVD73B3vR9' + '.txt'
        self.assertTrue(guard.patterns(name.encode()))
        self.assertFalse(guard.strong_name_rules(name))
        self.write(name, b'benign'); self.git('add', '--', name)
        self.assertTrue(guard.run(self.repo, staged=True)['pass'])

    def test_compressed_and_sensitive_metadata_cannot_reveal_the_name(self):
        name = 'cache-' + self.value() + '.gz'
        self.write(name, gzip.compress(b'benign')); self.git('add', '--', name)
        report = guard.run(self.repo, staged=True)
        self.assert_hidden_failure(report, 'filename_openai_style_key')
        self.assertTrue(report['compressed_objects'])
        self.assertTrue(report['sensitive_named_objects'])
        self.assertNotIn(name, json.dumps(report))

    def test_names_only_is_explicitly_not_a_content_certification(self):
        self.write('safe.txt', self.value().encode()); self.git('add', 'safe.txt')
        report = guard.scan_names(self.repo, staged=True)
        self.assertTrue(report['pass']); self.assertFalse(report['payloads_scanned'])
        self.assertEqual(report['scanned_bytes'], 0)
        self.assertFalse(guard.run(self.repo, staged=True)['pass'])


if __name__ == '__main__':
    unittest.main()
