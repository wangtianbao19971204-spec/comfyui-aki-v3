import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('workspace_audit_tests', ROOT / 'scripts/workspace_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

RETIRED = {
    'schema': 1,
    'status': 'retired',
    'sole_development_git': 'maintenance/comfyui',
    'retired_git_markers': 1,
    'repositories': [
        {
            'runtime_path': 'ComfyUI',
            'original_head': 'a' * 40,
            'role': 'legacy_core_worktree',
            'private_archive_relative': 'archives/example/ComfyUI.git',
        }
    ],
}

MACHINE_LINE = '$root = "G:\\ComfyUI-aki-v3"; # CANARY_NOT_A_CREDENTIAL\n'


class WorkspaceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.runtime = self.base / 'runtime'
        self.repo = self.runtime / 'maintenance' / 'comfyui'
        self.repo.mkdir(parents=True)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Audit Tests')
        self.git('config', 'user.email', 'tests@local.invalid')
        self.write('governance/retired-git.json', RETIRED)
        self.write('snapshot/runtime/tools/hardcoded.ps1', MACHINE_LINE)
        self.write('snapshot/runtime/qwen21_lab/start.ps1', 'Write-Output "clean"\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Baseline')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not isinstance(value, str):
            value = json.dumps(value)
        path.write_text(value, encoding='utf-8')

    def test_only_the_expected_checkout_is_recognised(self):
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertEqual(result['observed_count'], 1)
        self.assertEqual(result['unexpected_git_directories'], [])
        self.assertEqual(result['retired_markers_still_present'], [])
        self.assertEqual(result['sole_development_git_expected_relative'], 'maintenance/comfyui')
        self.assertTrue(result['expected_git_directory_observed'])
        self.assertTrue(result['sole_development_git_holds'])

    def test_extra_repository_breaks_the_sole_claim(self):
        extra = self.runtime / 'somewhere' / '.git'
        extra.mkdir(parents=True)
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertEqual(result['observed_count'], 2)
        self.assertEqual(len(result['unexpected_git_directories']), 1)
        self.assertFalse(result['sole_development_git_holds'])

    def test_worktree_git_file_breaks_claim_without_reading_contents(self):
        marker = self.runtime / 'worktree' / '.git'
        marker.parent.mkdir()
        marker.write_text('gitdir: CANARY_NEVER_READ\n', encoding='utf-8')
        original_read = Path.read_text

        def guarded_read(path, *args, **kwargs):
            if path == marker:
                raise AssertionError('marker content read')
            return original_read(path, *args, **kwargs)

        with mock.patch.object(Path, 'read_text', guarded_read):
            result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertFalse(result['sole_development_git_holds'])
        self.assertEqual(result['unexpected_git_markers'][0]['kind'], 'file')
        self.assertNotIn('CANARY_NEVER_READ', json.dumps(result))

    def test_missing_runtime_root_does_not_pass(self):
        result = audit.classify_runtime_repos(self.base / 'absent', self.repo)
        self.assertFalse(result['runtime_root_present'])
        self.assertFalse(result['sole_development_git_holds'])

    def test_missing_expected_git_directory_does_not_pass(self):
        (self.repo / '.git').rename(self.base / 'saved-git')
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertFalse(result['expected_git_directory_observed'])
        self.assertFalse(result['sole_development_git_holds'])

    def test_repository_must_be_at_the_registered_runtime_location(self):
        other_runtime = self.base / 'other-runtime'
        other_runtime.mkdir()
        result = audit.classify_runtime_repos(other_runtime, self.repo)
        self.assertFalse(result['expected_repository_location_matches'])
        self.assertFalse(result['sole_development_git_holds'])

    def test_walk_errors_fail_closed_and_hide_exception_detail(self):
        real_walk = os.walk

        def failing_walk(root, **options):
            yield from real_walk(root, **options)
            options['onerror'](PermissionError(13, 'CANARY_PRIVATE_DETAIL', str(self.runtime / 'blocked')))

        with mock.patch.object(audit.os, 'walk', side_effect=failing_walk):
            result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertTrue(result['expected_git_directory_observed'])
        self.assertFalse(result['sole_development_git_holds'])
        self.assertEqual(result['traversal_errors'][0]['error'], 'PermissionError')
        self.assertNotIn('CANARY_PRIVATE_DETAIL', json.dumps(result))

    def test_bare_repository_without_git_suffix_is_unexpected(self):
        bare = self.runtime / 'alternate-history'
        (bare / 'objects').mkdir(parents=True)
        (bare / 'refs').mkdir()
        (bare / 'HEAD').write_text('CANARY_HEAD_NEVER_READ\n', encoding='utf-8')
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertFalse(result['sole_development_git_holds'])
        self.assertEqual(result['unexpected_bare_git_repositories'][0]['path'], str(bare))
        self.assertNotIn('CANARY_HEAD_NEVER_READ', json.dumps(result))

    def test_linked_git_marker_is_reported_and_not_followed(self):
        outside = self.base / 'outside-metadata'
        outside.mkdir()
        marker = self.runtime / 'linked-worktree' / '.git'
        marker.parent.mkdir()
        try:
            os.symlink(outside, marker, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(type(exc).__name__)
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertFalse(result['sole_development_git_holds'])
        self.assertEqual(result['unexpected_git_markers'][0]['kind'], 'reparse')

    def test_linked_expected_git_directory_is_not_the_main_checkout(self):
        saved = self.base / 'saved-metadata'
        (self.repo / '.git').rename(saved)
        try:
            os.symlink(saved, self.repo / '.git', target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(type(exc).__name__)
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertFalse(result['expected_git_directory_observed'])
        self.assertFalse(result['sole_development_git_holds'])

    def test_retired_marker_reappearance_is_reported_by_name(self):
        (self.runtime / 'ComfyUI' / '.git').mkdir(parents=True)
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertEqual([item['runtime_path'] for item in result['retired_markers_still_present']], ['ComfyUI'])

    def test_walk_does_not_follow_reparse_points(self):
        outside = self.base / 'outside'
        (outside / 'nested' / '.git').mkdir(parents=True)
        link = self.runtime / 'junction'
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(type(exc).__name__)
        found = audit.scan_git_directories(self.runtime, 'runtime')
        self.assertNotIn('nested', ' '.join(item['path'] for item in found))

    def test_cache_output_temp_and_dependencies_are_scanned(self):
        for name in ('.cache', 'output', 'temp', 'node_modules', '__pycache__'):
            with self.subTest(name=name):
                hidden = self.runtime / 'ComfyUI' / name / 'deep' / '.git'
                hidden.mkdir(parents=True)
                result = audit.classify_runtime_repos(self.runtime, self.repo)
                self.assertFalse(result['sole_development_git_holds'])
                self.assertIn(str(hidden), [item['path'] for item in result['unexpected_git_markers']])

    def test_git_metadata_is_not_descended(self):
        (self.repo / '.git' / 'internal' / '.git').mkdir(parents=True)
        result = audit.classify_runtime_repos(self.runtime, self.repo)
        self.assertTrue(result['sole_development_git_holds'])
        self.assertEqual(result['observed_count'], 1)

    def test_bare_archives_are_classified_separately(self):
        external = self.base / 'external'
        (external / 'archives' / 'retired.git').mkdir(parents=True)
        (external / 'validation' / 'clone' / '.git').mkdir(parents=True)
        result = audit.classify_external_repos(external)
        self.assertEqual(result['bare_count'], 1)
        self.assertEqual(result['nested_count'], 1)
        self.assertEqual(result['classification'], 'archive_and_validation_only')

    def test_missing_external_root_is_not_a_failure(self):
        result = audit.classify_external_repos(self.base / 'absent')
        self.assertFalse(result['present'])

    def test_path_exposure_counts_files_and_hides_matched_text(self):
        report = audit.path_exposure(self.repo)
        self.assertGreaterEqual(report['total_occurrences'], 1)
        self.assertIn('snapshot/runtime/tools/hardcoded.ps1', report['files'])
        self.assertEqual(report['occurrences_by_area'].get('snapshot_tools'), 1)
        encoded = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('CANARY_NOT_A_CREDENTIAL', encoded)
        self.assertFalse(report['contains_credentials'])
        self.assertFalse(report['matched_text_included'])

    def test_path_exposure_ignores_untracked_files(self):
        self.write('snapshot/runtime/tools/untracked.ps1', MACHINE_LINE)
        report = audit.path_exposure(self.repo)
        self.assertNotIn('snapshot/runtime/tools/untracked.ps1', report['files'])

    def test_full_audit_is_read_only_and_reports_no_network(self):
        before = {path: path.read_bytes() for path in self.repo.rglob('*') if path.is_file() and '.git' not in path.parts}
        report = audit.audit(self.runtime, self.base / 'external', self.repo)
        self.assertTrue(report['git_uniqueness']['sole_development_git_holds'])
        self.assertFalse(report['production_modified'])
        self.assertFalse(report['network_accessed'])
        after = {path: path.read_bytes() for path in self.repo.rglob('*') if path.is_file() and '.git' not in path.parts}
        self.assertEqual(before, after)

    def test_git_grep_failure_is_not_swallowed(self):
        broken = self.base / 'not-a-repo'
        broken.mkdir()
        with self.assertRaises(RuntimeError):
            audit.path_exposure(broken)


if __name__ == '__main__':
    unittest.main()
