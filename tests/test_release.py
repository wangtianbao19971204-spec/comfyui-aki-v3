import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release


BASELINE = {'schema': 1, 'package': 'comfyui', 'version': '0.0.0',
            'state': 'unreleased-baseline', 'tag_prefix': 'comfyui-v', 'prepared': None}


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        release.git(self.repo, '-c', 'init.templateDir=', 'init', '-b', 'main')
        self.git('config', 'user.name', 'Release Fixture')
        self.git('config', 'user.email', 'release-fixture@local.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.write('governance/version.json', release.encoded(BASELINE))
        payload = b"print('fixture')\n"
        self.write('snapshot/runtime/ComfyUI/main.py', payload)
        self.write('snapshot/manifest.json', release.encoded({
            'schema': 1, 'created_at': 'fixture', 'source_root': str(self.root / 'runtime'),
            'files': [{'source': 'ComfyUI/main.py', 'path': 'runtime/ComfyUI/main.py',
                       'kind': 'file', 'sha256': release.sha(payload), 'bytes': len(payload)}]}))
        self.write('CHANGELOG.md', b'# Fixture changelog\n')
        self.commit('fixture source')
        self.base = self.head()
        self.release_branch = 'release/fixture'
        self.git('switch', '-c', self.release_branch)
        self.receipt = self.root / 'rollback.json'
        self.receipt.write_bytes(b'{"fixture_only":true,"not_a_live_backup":true}\n')
        self.notes = {'schema': 1, 'summary': 'Isolated maintenance fixture', 'components': ['fixture'],
                      'changes': ['Fixture change'], 'tests': ['Fixture checks only; no live acceptance'],
                      'rollback': {'target_commit': self.base, 'receipt_id': 'fixture-recovery',
                                   'receipt_sha256': release.sha(self.receipt.read_bytes()),
                                   'scope': ['Code only'], 'limitations': ['No online data restored']}}
        self.note_path = self.root / 'reviewed-notes.json'
        self.save_notes()
        self.technical = patch.object(release, 'technical_check', return_value={'pass': True})
        self.technical.start()
        self.addCleanup(self.technical.stop)

    def write(self, relative, data):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def git(self, *args):
        return release.git(self.repo, *args).stdout.decode().strip()

    def commit(self, message):
        self.git('add', '--all')
        self.git('commit', '-qm', message)

    def head(self):
        return self.git('rev-parse', 'HEAD')

    def save_notes(self):
        self.note_path.write_bytes(release.encoded(self.notes))
        self.review_sha = release.sha(self.note_path.read_bytes())

    def prepare(self, **overrides):
        options = dict(repo=self.repo, expected_branch=self.release_branch, expected_head=self.base,
                       expected_version='0.0.0', increment='patch',
                       notes_path=self.note_path, review_sha256=self.review_sha, rollback_receipt=self.receipt)
        options.update(overrides)
        return release.prepare(**options)

    def ready(self):
        self.prepare()
        self.commit('prepare release metadata')
        self.git('switch', 'main')
        self.git('merge', '--no-ff', '-m', 'fixture user-approved PR merge', self.release_branch)
        return self.head()

    def tag(self, **overrides):
        options = dict(repo=self.repo, expected_head=self.head(), expected_version='0.0.1')
        options.update(overrides)
        return release.tag(**options)

    def assert_no_tags(self):
        self.assertEqual(self.git('tag', '--list'), '')

    def test_semver_increment_and_invalid_forms(self):
        self.assertEqual(release.bump('1.2.3', 'patch'), '1.2.4')
        self.assertEqual(release.bump('1.2.3', 'minor'), '1.3.0')
        self.assertEqual(release.bump('1.2.3', 'major'), '2.0.0')
        for value in ['v1.0.0', '01.0.0', '1.2', '1.2.3-rc1', '-1.0.0', '1.2.3\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.version(value)

    def test_baseline_is_not_an_existing_numbered_release(self):
        self.assertEqual(release.validate_version(copy.deepcopy(BASELINE)), BASELINE)
        value = copy.deepcopy(BASELINE); value['version'] = '1.0.0'
        with self.assertRaises(ValueError):
            release.validate_version(value)

    def test_prepare_writes_only_metadata_and_never_commits_or_tags(self):
        with patch.object(release, 'full_gates', side_effect=AssertionError('prepare must not scan all history')):
            result = self.prepare(increment='major')
        self.assertEqual(result['version'], '1.0.0')
        self.assertEqual(result['preparation_branch'], self.release_branch)
        self.assertFalse(result['committed']); self.assertFalse(result['tag_created'])
        self.assertEqual(self.head(), self.base); self.assert_no_tags()
        self.assertEqual(self.git('rev-parse', 'main'), self.base)
        metadata, _ = release.read_version(self.repo)
        self.assertEqual(metadata['prepared']['base_commit'], self.base)
        record = json.loads((self.repo / metadata['prepared']['notes_path']).read_bytes())
        self.assertFalse(record['runtime_deployed'])
        self.assertEqual(record['reviewed_notes']['rollback']['receipt_id'], 'fixture-recovery')
        self.assertNotIn(str(self.receipt), json.dumps(record))
        self.assertFalse((self.root / 'runtime').exists())

    def test_prepare_expected_head_and_version_are_required(self):
        for options in [{'expected_head': 'a' * 40}, {'expected_version': '9.0.0'}]:
            with self.subTest(options=options), self.assertRaises(RuntimeError):
                self.prepare(**options)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assert_no_tags()

    def test_prepare_requires_explicit_release_branch_argument(self):
        options = dict(repo=self.repo, expected_head=self.base, expected_version='0.0.0', increment='patch',
                       notes_path=self.note_path, review_sha256=self.review_sha, rollback_receipt=self.receipt)
        with self.assertRaises(TypeError):
            release.prepare(**options)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_prepare_cli_requires_explicit_release_branch_argument(self):
        args = ['release.py', 'prepare', '--expected-head', self.base, '--expected-version', '0.0.0',
                '--bump', 'patch', '--notes', str(self.note_path), '--review-sha256', self.review_sha,
                '--rollback-receipt', str(self.receipt)]
        with patch.object(sys, 'argv', args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            release.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)

    def test_prepare_rejects_main_and_invalid_expected_branch(self):
        for branch in [None, '', 'main', 'feature/release', 'refs/heads/release/fixture',
                       'release/', 'release/a..b', 'release/a b', 'release/x.lock', 'release/x\n']:
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                self.prepare(expected_branch=branch)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_prepare_rejects_main_checkout_even_with_release_branch_argument(self):
        self.git('switch', 'main')
        with self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assert_no_tags()

    def test_prepare_rejects_wrong_release_branch_checkout(self):
        self.git('switch', '-c', 'release/other')
        with self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assert_no_tags()

    def test_prepare_rejects_detached_head(self):
        self.git('switch', '--detach', self.base)
        with self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)

    def test_prepare_rejects_untracked_or_staged_changes(self):
        self.write('unreviewed.txt', b'unreviewed')
        with self.assertRaises(RuntimeError):
            self.prepare()
        self.git('add', 'unreviewed.txt')
        with self.assertRaises(RuntimeError):
            self.prepare()

    def test_prepare_rejects_missing_or_stale_note_review(self):
        with self.assertRaises(ValueError):
            self.prepare(review_sha256='0' * 64)
        self.note_path.write_bytes(self.note_path.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_prepare_requires_verified_rollback_receipt(self):
        self.receipt.write_bytes(b'changed receipt')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)

    def test_prepare_rejects_missing_rollback_scope(self):
        self.notes['rollback']['scope'] = []
        self.save_notes()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_prepare_rejects_credential_in_notes_without_echoing_value(self):
        value = 'sk-' + 'A8b7C6d5E4f3G2h1' * 3
        self.notes['summary'] = value
        self.save_notes()
        with self.assertRaises(ValueError) as caught:
            self.prepare()
        self.assertNotIn(value, str(caught.exception))

    def test_prepare_rejects_parallel_change_during_catalogue_gate(self):
        def drift(repo):
            self.write('parallel.txt', b'owned by another editor')
            return {'pass': True}
        with patch.object(release, 'technical_check', side_effect=drift), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertTrue((self.repo / 'parallel.txt').exists())
        self.assertFalse((self.repo / 'docs/releases/comfyui-v0.0.1.json').exists())

    def test_prepare_rejects_branch_drift_without_ref_oid_changes(self):
        self.git('branch', 'release/other')
        before_refs = release.refs(self.repo)
        def drift(repo):
            self.git('switch', 'release/other')
            return {'pass': True}
        with patch.object(release, 'technical_check', side_effect=drift), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.refs(self.repo), before_refs)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertFalse((self.repo / 'docs/releases/comfyui-v0.0.1.json').exists())

    def test_prepare_rejects_head_drift_during_catalogue_gate(self):
        def drift(repo):
            self.write('parallel.txt', b'concurrent source')
            self.commit('concurrent fixture commit')
            return {'pass': True}
        with patch.object(release, 'technical_check', side_effect=drift), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertNotEqual(self.head(), self.base)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertEqual((self.repo / 'parallel.txt').read_bytes(), b'concurrent source')
        self.assertFalse((self.repo / 'docs/releases/comfyui-v0.0.1.json').exists())

    def test_prepare_requires_catalogue_pass(self):
        with patch.object(release, 'technical_check', side_effect=RuntimeError('catalogue failed')), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)

    def test_release_lock_is_not_reclaimed(self):
        lock = self.repo / '.git/comfyui-release.lock'
        lock.write_text('other owner')
        with self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(lock.read_text(), 'other owner')

    def test_tag_rejects_uncommitted_preparation(self):
        self.prepare()
        self.git('switch', 'main')
        with self.assertRaises(RuntimeError):
            self.tag()
        self.assert_no_tags()

    def test_tag_rejects_clean_release_branch_before_user_merge(self):
        self.prepare()
        self.commit('fixture release metadata awaits user merge')
        with patch.object(release, 'full_gates', side_effect=AssertionError('branch refusal must precede gates')):
            with self.assertRaises(RuntimeError):
                self.tag()
        self.assertEqual(self.git('rev-parse', 'main'), self.base)
        self.assert_no_tags()

    def test_tag_rejects_wrong_expected_head_or_version(self):
        self.ready()
        with self.assertRaises(RuntimeError):
            self.tag(expected_head=self.base)
        with self.assertRaises(RuntimeError):
            self.tag(expected_version='0.0.2')
        self.assert_no_tags()

    def test_tag_uses_real_complete_gates_on_fixture_and_is_annotated(self):
        head = self.ready()
        with patch.object(release.security_guard, 'run', wraps=release.security_guard.run) as security:
            result = self.tag()
        security.assert_called_once_with(self.repo)
        self.assertTrue(result['gates']['full_history_pass'])
        self.assertEqual(self.git('cat-file', '-t', 'refs/tags/comfyui-v0.0.1'), 'tag')
        self.assertEqual(self.git('rev-parse', 'refs/tags/comfyui-v0.0.1^{}'), head)
        self.assertEqual(self.head(), head)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertFalse(result['pushed']); self.assertFalse(result['runtime_deployed'])

    def test_tag_rejects_gate_failure_without_creating_ref(self):
        self.ready()
        with patch.object(release, 'full_gates', side_effect=RuntimeError('gate failed')), self.assertRaises(RuntimeError):
            self.tag()
        self.assert_no_tags()

    def test_tag_never_overwrites_existing_tag(self):
        self.ready()
        self.git('tag', 'comfyui-v0.0.1', self.base)
        with self.assertRaises(RuntimeError):
            self.tag()
        self.assertEqual(self.git('rev-parse', 'refs/tags/comfyui-v0.0.1'), self.base)

    def test_tag_rejects_post_preparation_source_change(self):
        self.ready()
        self.write('snapshot/runtime/ComfyUI/main.py', b'new source after review')
        self.commit('unreviewed additional source')
        with self.assertRaises(RuntimeError):
            self.tag()
        self.assert_no_tags()

    def test_tag_rejects_head_drift_during_gates(self):
        head = self.ready()
        def drift(repo):
            self.write('parallel.txt', b'concurrent change')
            self.commit('parallel commit')
            return {'pass': True}
        with patch.object(release, 'full_gates', side_effect=drift), self.assertRaises(RuntimeError):
            self.tag(expected_head=head)
        self.assert_no_tags()
        self.assertTrue((self.repo / 'parallel.txt').exists())

    def test_tag_rejects_dirty_drift_during_gates(self):
        self.ready()
        def drift(repo):
            self.write('parallel.txt', b'uncommitted concurrent change')
            return {'pass': True}
        with patch.object(release, 'full_gates', side_effect=drift), self.assertRaises(RuntimeError):
            self.tag()
        self.assert_no_tags()

    def test_tag_rejects_branch_drift_during_gates(self):
        self.ready()
        self.git('branch', 'release/same-merged-head')
        before_refs = release.refs(self.repo)
        def drift(repo):
            self.git('switch', 'release/same-merged-head')
            return {'pass': True}
        with patch.object(release, 'full_gates', side_effect=drift), self.assertRaises(RuntimeError):
            self.tag()
        self.assertEqual(release.refs(self.repo), before_refs)
        self.assert_no_tags()

    def test_atomic_tag_creation_rejects_last_moment_head_change(self):
        self.ready()
        original = release.git
        def racing(repo, *args, **kwargs):
            if args[:2] == ('update-ref', '--stdin'):
                original(repo, 'update-ref', 'refs/heads/main', self.base)
            return original(repo, *args, **kwargs)
        with patch.object(release, 'git', side_effect=racing), self.assertRaises(RuntimeError):
            self.tag()
        self.assert_no_tags()

    def test_next_prepare_requires_previous_explicit_release_tag(self):
        self.ready()
        self.git('switch', '-c', 'release/next')
        with self.assertRaises(RuntimeError):
            self.prepare(expected_branch='release/next', expected_head=self.head(), expected_version='0.0.1')

    def test_environment_ignores_inherited_git_redirection(self):
        before = self.head()
        with patch.dict(os.environ, {'GIT_DIR': str(self.root / 'wrong'), 'GIT_INDEX_FILE': str(self.root / 'wrong-index'),
                                     'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': 'unsafe'}):
            self.assertEqual(self.head(), before)
            self.prepare()
        self.assertFalse((self.root / 'wrong-index').exists())

    def test_full_gate_does_not_accept_content_only_downgrade(self):
        with patch.object(release.security_guard, 'run', return_value={'pass': True, 'mode': 'all-history', 'content_only': True}):
            with self.assertRaises(RuntimeError):
                release.full_gates(self.repo)

    def test_prepare_atomic_write_failure_preserves_baseline(self):
        with patch.object(release, 'replace_file', side_effect=OSError('fixture write failure')), self.assertRaises(OSError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertFalse((self.repo / 'docs/releases/comfyui-v0.0.1.json').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_prepare_postwrite_drift_preserves_other_edit(self):
        replace = release.replace_file
        def drift(path, raw):
            replace(path, raw)
            self.write('parallel.txt', b'other editor data')
        with patch.object(release, 'replace_file', side_effect=drift), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertEqual((self.repo / 'parallel.txt').read_bytes(), b'other editor data')
        self.assertFalse((self.repo / 'docs/releases/comfyui-v0.0.1.json').exists())

    def test_prepare_rejects_postwrite_branch_drift_without_ref_oid_changes(self):
        self.git('branch', 'release/other')
        before_refs = release.refs(self.repo)
        replace = release.replace_file
        def drift(path, raw):
            replace(path, raw)
            if json.loads(raw)['state'] == 'prepared':
                self.git('switch', 'release/other')
        with patch.object(release, 'replace_file', side_effect=drift), self.assertRaises(RuntimeError):
            self.prepare()
        self.assertEqual(release.refs(self.repo), before_refs)
        self.assertEqual(release.read_version(self.repo)[0], BASELINE)
        self.assertFalse((self.repo / 'docs/releases/comfyui-v0.0.1.json').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_prepare_does_not_undo_concurrent_commit_after_writes(self):
        replace = release.replace_file
        def drift(path, raw):
            replace(path, raw)
            self.commit('concurrent explicit commit')
        with patch.object(release, 'replace_file', side_effect=drift), self.assertRaises(release.ReleaseStateError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.state, 'prepare_partial_state_retained')
        self.assertNotEqual(self.head(), self.base)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertTrue((self.repo / 'docs/releases/comfyui-v0.0.1.json').is_file())

    def test_tag_reports_created_ref_if_postcheck_drift_occurs(self):
        self.ready()
        original = release.git
        def drift(repo, *args, **kwargs):
            result = original(repo, *args, **kwargs)
            if args[:2] == ('update-ref', '--stdin'):
                self.write('parallel.txt', b'new editor data after tag')
            return result
        with patch.object(release, 'git', side_effect=drift), self.assertRaises(release.ReleaseStateError) as caught:
            self.tag()
        self.assertEqual(caught.exception.state, 'tag_created_postcheck_failed')
        self.assertEqual(self.git('tag', '--list'), 'comfyui-v0.0.1')
        self.assertEqual((self.repo / 'parallel.txt').read_bytes(), b'new editor data after tag')

    def test_full_gate_rejects_inconsistent_pass_with_findings(self):
        with patch.object(release.security_guard, 'run', return_value={'pass': True, 'mode': 'all-history',
                                                                     'content_only': False, 'findings': [{'rule': 'fixture'}]}):
            with self.assertRaises(RuntimeError):
                release.full_gates(self.repo)

    def test_next_prepare_after_explicit_tag_increments_only_once(self):
        self.ready(); self.tag()
        self.notes['rollback']['target_commit'] = self.head()
        self.save_notes()
        self.git('switch', '-c', 'release/next')
        result = self.prepare(expected_branch='release/next', expected_head=self.head(),
                              expected_version='0.0.1', increment='minor')
        self.assertEqual(result['version'], '0.1.0')
        self.assertEqual(self.git('tag', '--list'), 'comfyui-v0.0.1')


if __name__ == '__main__':
    unittest.main()
