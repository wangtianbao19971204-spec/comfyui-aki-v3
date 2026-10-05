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
SPEC = importlib.util.spec_from_file_location('maintenance_entry_tests', ROOT / 'scripts/maintain.py')
maintain = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintain)


class MaintenanceEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Maintenance Tests')
        self.git('config', 'user.email', 'tests@local.invalid')
        self.write('governance/version.json', {'version': '0.1.0', 'state': 'prepared'})
        self.write('snapshot/manifest.json', {'created_at': 'historical-time', 'accepted_runtime_deployments': [{'receipt': 'bounded'}]})
        self.write('governance/retention-policy.json', json.loads((ROOT / 'governance/retention-policy.json').read_bytes()))
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
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_prepared_metadata_is_not_tagged_release(self):
        state = maintain.collect_status(self.repo)
        self.assertFalse(state['local_release']['exists'])
        self.assertFalse(state['runtime']['checked_live'])
        self.assertIsNone(state['runtime']['deployment_commit'])
        self.assertFalse(state['backup']['independent_backup_verified'])

    def test_annotated_tag_is_recognized_without_changing_version_counter(self):
        self.git('tag', '-a', 'comfyui-v0.1.0', '-m', 'Release')
        state = maintain.collect_status(self.repo)
        self.assertTrue(state['local_release']['annotated'])
        self.assertEqual(state['version_metadata_state'], 'prepared')
        self.assertEqual(state['local_release']['first_parent_commits_after_release'], 0)

    def test_lightweight_tag_is_not_certified_as_annotated(self):
        self.git('tag', 'comfyui-v0.1.0')
        self.assertFalse(maintain.collect_status(self.repo)['local_release']['annotated'])

    def test_uncommitted_changes_are_shown_and_preserved(self):
        self.write('new-file.json', {'change': True})
        before = (self.repo / 'new-file.json').read_bytes()
        state = maintain.collect_status(self.repo)
        self.assertFalse(state['working_tree_clean'])
        self.assertEqual(state['changes'], [{'status': '??', 'path': 'new-file.json'}])
        self.assertEqual(before, (self.repo / 'new-file.json').read_bytes())

    def test_rename_status_is_parsed(self):
        self.git('mv', 'snapshot/manifest.json', 'snapshot/renamed.json')
        state = maintain.changes(self.repo)
        self.assertEqual(state[0]['from'], 'snapshot/manifest.json')
        self.assertEqual(state[0]['path'], 'snapshot/renamed.json')

    def test_status_does_not_change_git_index(self):
        index = self.repo / '.git/index'
        before = index.read_bytes()
        maintain.collect_status(self.repo)
        self.assertEqual(before, index.read_bytes())

    def test_history_omits_merged_branch_internals(self):
        self.git('checkout', '-b', 'imported')
        self.write('import.json', {'old': True})
        self.git('add', 'import.json')
        self.git('commit', '-qm', 'Old imported commit')
        self.git('checkout', 'main')
        self.git('merge', '--no-ff', 'imported', '-m', 'Archive merge')
        rows = maintain.history(self.repo)
        self.assertEqual(len(rows), 2)
        self.assertFalse(any('Old imported commit' in row for row in rows))

    def test_history_redacts_secret_metadata(self):
        token = 'sk-' + 'Ab12Cd34Ef56Gh78' * 3
        self.git('commit', '--allow-empty', '-qm', token)
        self.assertNotIn(token, '\n'.join(maintain.history(self.repo)))

    def test_history_limit_is_bounded(self):
        for limit in (0, 51):
            with self.assertRaises(ValueError):
                maintain.history(self.repo, limit)

    def test_policy_cannot_claim_automatic_execution(self):
        data = maintain.policy(self.repo)
        data['automatic_actions'] = True
        self.write('governance/retention-policy.json', data)
        with self.assertRaises(ValueError):
            maintain.policy(self.repo)

    def test_policy_cannot_claim_unverified_backup_destination(self):
        data = maintain.policy(self.repo)
        data['backup_destination'] = 'unverified-target'
        self.write('governance/retention-policy.json', data)
        with self.assertRaises(ValueError):
            maintain.policy(self.repo)

    def test_invalid_version_is_rejected(self):
        self.write('governance/version.json', {'version': '../invalid'})
        with self.assertRaises(ValueError):
            maintain.collect_status(self.repo)

    def test_check_staged_stops_at_failed_documentation(self):
        with mock.patch.object(maintain.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as call:
            self.assertEqual(maintain.check_staged(self.repo), 1)
            self.assertEqual(call.call_count, 1)

    def test_check_staged_fresh_is_explicit(self):
        with mock.patch.object(maintain.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as call:
            self.assertEqual(maintain.check_staged(self.repo), 0)
            self.assertIn('--cache-staged', call.call_args_list[-1].args[0])
        with mock.patch.object(maintain.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as call:
            self.assertEqual(maintain.check_staged(self.repo, fresh=True), 0)
            self.assertNotIn('--cache-staged', call.call_args_list[-1].args[0])


if __name__ == '__main__':
    unittest.main()
