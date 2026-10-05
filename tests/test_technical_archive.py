import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import technical_archive as archive


class TechnicalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base / 'runtime'
        self.repo = self.base / 'repo'
        self.private = self.base / 'private'
        for path in (self.runtime, self.repo, self.private):
            path.mkdir()

    def source(self, name='benchmark_reports/batch/scripts/check.py', data=b'answer = 42\n'):
        path = self.runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def selection(self, *names, **notes):
        return {'schema': 1, 'entries': [
            {'source': name, 'role': 'implementation'}
            for name in names or ('benchmark_reports/batch/scripts/check.py',)], **notes}

    def plan(self, selection=None):
        return archive.plan(selection or self.selection(), self.runtime, self.repo)

    def apply(self, review):
        return archive.apply_plan(review, review['review_sha256'], self.repo)

    def target(self, name='benchmark_reports/batch/scripts/check.py', data=None):
        path = self.repo / archive.ARCHIVE / name
        if data is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path

    def rebind(self, review):
        review.pop('review_sha256', None)
        review['review_sha256'] = archive.canonical_hash(review)
        return review

    def test_byte_identity_original_structure_and_public_minimum(self):
        source = self.source()
        original = source.read_bytes()
        review = self.plan()
        self.assertEqual(list(self.repo.iterdir()), [])
        result = self.apply(review)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.target().read_bytes(), original)
        self.assertEqual(result['copied'], [review['records'][0]['source']])
        self.assertFalse(result['source_modified'])
        self.assertFalse(result['snapshot_manifest_modified'])
        self.assertFalse(result['deployed'])
        self.assertFalse((self.repo / 'snapshot').exists())
        public = json.loads((self.repo / archive.PROVENANCE).read_text(encoding='utf-8'))
        self.assertEqual(set(public['files'][0]), {'source', 'path', 'sha256', 'role'})
        self.assertNotIn(str(self.runtime), json.dumps(public))
        self.assertNotIn('reason', json.dumps(public))
        self.assertEqual((self.repo / archive.README).read_bytes(), archive.README_BYTES)

    def test_same_approved_plan_is_provably_idempotent(self):
        self.source()
        review = self.plan()
        self.apply(review)
        before = (self.repo / archive.PROVENANCE).read_bytes()
        result = self.apply(review)
        self.assertEqual(result['copied'], [])
        self.assertEqual(result['retained_identical'], [review['records'][0]['source']])
        self.assertEqual((self.repo / archive.PROVENANCE).read_bytes(), before)

    def test_existing_identical_target_can_be_registered_without_overwrite(self):
        self.source()
        target = self.target(data=b'answer = 42\n')
        timestamp = target.stat().st_mtime_ns
        review = self.plan()
        self.assertEqual(review['records'][0]['status'], 'identical_existing')
        self.assertEqual(self.apply(review)['copied'], [])
        self.assertEqual(target.stat().st_mtime_ns, timestamp)

    def test_conflicting_existing_content_is_never_overwritten(self):
        self.source()
        target = self.target(data=b'important existing content\n')
        review = self.plan()
        self.assertEqual(review['records'][0]['reason'], 'existing_target_differs')
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertEqual(target.read_bytes(), b'important existing content\n')
        self.assertFalse((self.repo / archive.PROVENANCE).exists())

    def test_all_source_drift_preflight_precedes_writes(self):
        self.source('benchmark_reports/batch/a.py')
        changed = self.source('benchmark_reports/batch/b.py')
        review = self.plan(self.selection('benchmark_reports/batch/a.py', 'benchmark_reports/batch/b.py'))
        changed.write_bytes(b'changed = True\n')
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_target_appearing_after_review_is_checked_before_writes(self):
        self.source()
        review = self.plan()
        target = self.target(data=b'new independent edit\n')
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertEqual(target.read_bytes(), b'new independent edit\n')
        self.assertFalse((self.repo / archive.PROVENANCE).exists())

    def test_hash_mismatch_and_modified_review_fail_closed(self):
        self.source()
        review = self.plan()
        with self.assertRaises(archive.ArchiveError):
            archive.apply_plan(review, '0' * 64, self.repo)
        edited = copy.deepcopy(review)
        edited['records'][0]['bytes'] += 1
        with self.assertRaises(archive.ArchiveError):
            self.apply(edited)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_rehashed_mapping_cannot_escape_fixed_archive_destination(self):
        self.source()
        review = self.plan()
        review['records'][0]['destination'] = 'snapshot/runtime/replace.py'
        with self.assertRaises(archive.ArchiveError):
            self.apply(self.rebind(review))
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_secret_is_quarantined_without_value_in_report(self):
        secret = 'sk-' + 'R7s8T9' * 7
        self.source(data=('api_key = "' + secret + '"\n').encode())
        review = self.plan()
        self.assertEqual(review['records'][0]['reason'], 'credential_gate')
        self.assertIn('openai_style_key', review['records'][0]['rules'])
        self.assertNotIn(secret, json.dumps(review))
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_dynamic_environment_reference_is_source_not_a_literal_secret(self):
        self.source(data=b'import os\napi_key = os.getenv("SERVICE_API_KEY")\n')
        self.assertEqual(self.plan()['records'][0]['status'], 'new_archive')

    def test_private_names_and_active_controls_are_not_archived(self):
        names = ['benchmark_reports/batch/providers.json', 'benchmark_reports/batch/.env',
                 'benchmark_reports/batch/AGENTS.md', 'benchmark_reports/batch/.gitattributes',
                 'benchmark_reports/batch/model.safetensors', 'benchmark_reports/batch/preview.png']
        for name in names:
            self.source(name, b'plain text')
        review = self.plan(self.selection(*names))
        self.assertTrue(all(row['status'] == 'rejected' for row in review['records']))

    def test_before_stage_candidate_vendor_are_reference_only(self):
        names = ['benchmark_reports/batch/before-code/old.py',
                 'benchmark_reports/batch/stage/module.py',
                 'benchmark_reports/batch/candidate_1/module.py',
                 'benchmark_reports/batch/vendor/dependency.py',
                 'benchmark_reports/batch/node_modules/source.js',
                 'benchmark_reports/batch/code.py.before_fix']
        for name in names:
            self.source(name)
        review = self.plan(self.selection(*names))
        self.assertTrue(all(row['status'] == 'rejected' for row in review['records']))
        self.source('benchmark_reports/batch/build_candidate.py')
        self.assertEqual(self.plan(self.selection('benchmark_reports/batch/build_candidate.py'))['records'][0]['status'], 'new_archive')

    def test_json_and_report_text_need_explicit_selection_and_scan(self):
        self.source('benchmark_reports/batch/REPORT.txt', b'A bounded technical report\n')
        self.source('benchmark_reports/batch/contract.json', b'{"schema": 1}\n')
        self.source('benchmark_reports/batch/unselected.py')
        review = self.plan(self.selection('benchmark_reports/batch/REPORT.txt', 'benchmark_reports/batch/contract.json'))
        self.assertEqual(len(self.apply(review)['copied']), 2)
        self.assertFalse(self.target('benchmark_reports/batch/unselected.py').exists())

    def test_disguised_binary_compression_and_non_utf8_are_refused(self):
        payloads = [b'PK\x03\x04hidden', b'\x1f\x8bhidden', b'MZbinary', b'bad\0text', b'\xff\xfe']
        for data in payloads:
            with self.subTest(data=data[:2]):
                self.source(data=data)
                self.assertEqual(self.plan()['records'][0]['status'], 'rejected')

    def test_file_and_total_byte_limits(self):
        self.source(data=b'x' * (archive.MAX_FILE + 1))
        self.assertEqual(self.plan()['records'][0]['reason'], 'file_over_limit')
        self.source(data=b'a = 1\n')
        with patch.object(archive, 'MAX_TOTAL', 2):
            with self.assertRaises(archive.ArchiveError):
                self.plan()

    def test_reference_and_missing_fixture_do_not_claim_copies(self):
        self.source()
        self.source('benchmark_reports/batch/before/old.py')
        selection = self.selection(required_external_data=[{'source': 'benchmark_reports/batch/before', 'reason': 'Historical originals remain private'}],
                                   missing_fixture=[{'source': 'benchmark_reports/batch/tests/fixture.json', 'reason': 'Not present in retained source'}])
        review = self.plan(selection)
        self.assertEqual(len(review['references']), 2)
        result = self.apply(review)
        self.assertTrue(all(not row['copied'] and not row['content_verified'] for row in result['references']))
        self.assertFalse(self.target('benchmark_reports/batch/before/old.py').exists())
        self.assertNotIn('fixture.json', (self.repo / archive.PROVENANCE).read_text())

    def test_reference_only_plan_writes_no_public_archive(self):
        review = self.plan({'schema': 1, 'entries': [], 'required_external_data': [
            {'source': 'benchmark_reports/data', 'reason': 'External retained data'}]})
        self.assertEqual(self.apply(review)['copied'], [])
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_missing_public_fixture_can_still_exist_as_private_original(self):
        self.source()
        self.source('benchmark_reports/fixture.json', b'{}')
        selection = self.selection(missing_fixture=[{'source': 'benchmark_reports/fixture.json', 'reason': 'missing'}])
        row = self.plan(selection)['references'][0]
        self.assertTrue(row['exists'])
        self.assertFalse(row['copied'])
        self.assertFalse(row['content_verified'])

    def test_human_selection_annotations_are_bound_but_not_public(self):
        self.source()
        selection = self.selection(scope='one historical feature', archive_base=archive.ARCHIVE,
                                   execution_status='not_executed', notes=['Historical reference only'])
        review = self.plan(selection)
        self.assertEqual(review['selection']['notes'], selection['notes'])
        self.apply(review)
        public = (self.repo / archive.PROVENANCE).read_text(encoding='utf-8')
        self.assertNotIn('one historical feature', public)
        selection['archive_base'] = 'snapshot/runtime'
        with self.assertRaises(archive.ArchiveError):
            self.plan(selection)

    def test_duplicate_alias_traversal_ads_and_unicode_aliases(self):
        bad = ['../escape.py', '/escape.py', 'dir\\file.py', 'dir/../file.py',
               'dir/file.py:stream', 'dir/CON.py', 'dir/file.py ', 'dir/\uff21.py']
        for name in bad:
            with self.subTest(name=name), self.assertRaises(archive.ArchiveError):
                self.plan(self.selection(name))
        with self.assertRaises(archive.ArchiveError):
            self.plan(self.selection('batch/A.py', 'batch/a.py'))

    def test_source_under_nested_public_checkout_is_refused(self):
        nested = self.runtime / 'maintenance/repo'
        nested.mkdir(parents=True)
        (nested / 'example.py').write_text('safe = True\n')
        review = archive.plan(self.selection('maintenance/repo/example.py'), self.runtime, nested)
        self.assertEqual(review['records'][0]['status'], 'rejected')

    def make_symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError:
            self.skipTest('Symlink creation unavailable')

    def test_source_link_and_linked_parent_not_followed(self):
        outside = self.base / 'outside.py'
        outside.write_text('safe = True\n')
        link = self.runtime / 'linked.py'
        self.make_symlink(link, outside)
        self.assertEqual(self.plan(self.selection('linked.py'))['records'][0]['reason'], 'linked_or_reparse_path')
        parent = self.runtime / 'linked-folder'
        self.make_symlink(parent, self.private, directory=True)
        (self.private / 'source.py').write_text('answer = 42\n')
        self.assertEqual(self.plan(self.selection('linked-folder/source.py'))['records'][0]['status'], 'rejected')

    def test_destination_parent_link_not_followed(self):
        self.source()
        (self.repo / 'docs/technical').mkdir(parents=True)
        self.make_symlink(self.repo / archive.ARCHIVE, self.private, directory=True)
        with self.assertRaises(archive.ArchiveError):
            self.plan()
        self.assertEqual(list(self.private.iterdir()), [])

    def test_private_reference_to_environment_link_is_recorded_without_following(self):
        self.source()
        self.make_symlink(self.runtime / 'node_modules', self.private, directory=True)
        selection = self.selection(required_external_data=[{'source': 'node_modules/dependency', 'reason': 'Private external environment'}])
        row = self.plan(selection)['references'][0]
        self.assertEqual(row['type'], 'linked_or_reparse_path_not_followed')
        self.assertIsNone(row['exists'])
        self.assertFalse(row['content_verified'])

    def test_root_link_not_resolved_before_link_check(self):
        alias = self.base / 'runtime-link'
        self.make_symlink(alias, self.runtime, directory=True)
        with self.assertRaises(archive.ArchiveError):
            archive.plan(self.selection(), alias, self.repo)

    def test_hardlinked_source_or_target_is_ambiguous(self):
        source = self.source()
        try:
            os.link(source, self.base / 'hardlink.py')
        except OSError:
            self.skipTest('Hard link unavailable')
        self.assertEqual(self.plan()['records'][0]['reason'], 'hardlinked_path')

    def test_existing_readme_conflict_aborts_before_copy(self):
        self.source()
        readme = self.repo / archive.README
        readme.parent.mkdir(parents=True)
        readme.write_text('Unrelated documentation\n')
        with self.assertRaises(archive.ArchiveError):
            self.plan()
        self.assertFalse(self.target().exists())

    def test_previous_provenance_content_drift_is_detected(self):
        self.source()
        self.apply(self.plan())
        self.target().write_bytes(b'modified archived file\n')
        with self.assertRaises(archive.ArchiveError):
            self.plan()

    def test_independent_provenance_change_invalidates_old_plan(self):
        self.source()
        stale = self.plan()
        self.source('benchmark_reports/batch/other.py')
        self.apply(self.plan(self.selection('benchmark_reports/batch/other.py')))
        with self.assertRaises(archive.ArchiveError):
            self.apply(stale)
        self.assertFalse(self.target().exists())

    def test_incremental_plan_preserves_previous_provenance(self):
        self.source()
        self.apply(self.plan())
        self.source('benchmark_reports/batch/other.py')
        self.apply(self.plan(self.selection('benchmark_reports/batch/other.py')))
        value = json.loads((self.repo / archive.PROVENANCE).read_text(encoding='utf-8'))
        self.assertEqual(len(value['files']), 2)

    def test_busy_lock_is_not_reclaimed(self):
        self.source()
        review = self.plan()
        lock = self.repo / 'local/technical-archive.apply.lock'
        lock.parent.mkdir()
        lock.write_bytes(b'')
        with self.assertRaises(archive.ArchiveError):
            self.apply(review)
        self.assertTrue(lock.exists())
        self.assertFalse(self.target().exists())

    def test_private_reports_must_stay_in_nonoverlapping_external_root(self):
        good = self.private / 'plans/review.json'
        self.assertEqual(archive.private_path(good, self.private, self.runtime, self.repo), good)
        for private_root, path in ((self.repo, self.repo / 'plan.json'),
                                   (self.runtime, self.runtime / 'plan.json'),
                                   (self.base, self.private / 'plan.json'),
                                   (self.private, self.repo / 'plan.json')):
            with self.subTest(path=path), self.assertRaises(archive.ArchiveError):
                archive.private_path(path, private_root, self.runtime, self.repo)

    def test_private_report_is_exclusive_and_never_overwritten(self):
        report = self.private / 'report.json'
        archive.save_new(report, b'{}\n')
        with self.assertRaises(FileExistsError):
            archive.save_new(report, b'changed\n')
        self.assertEqual(report.read_bytes(), b'{}\n')

    def test_cli_plan_and_apply_use_external_reports_and_safe_summary(self):
        self.source()
        selection = self.private / 'selection.json'
        selection.write_text(json.dumps(self.selection()), encoding='utf-8')
        script = Path(archive.__file__).resolve()
        base = [sys.executable, '-B', str(script), '--repo', str(self.repo)]
        report = self.private / 'plan.json'
        result = subprocess.run(base + ['plan', '--runtime', str(self.runtime), '--selection', str(selection),
                                       '--private-root', str(self.private), '--report', str(report)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['selected'], 1)
        self.assertNotIn(str(self.runtime), result.stdout)
        receipt = self.private / 'receipt.json'
        applied = subprocess.run(base + ['apply', '--plan', str(report), '--review-sha256', summary['review_sha256'],
                                        '--private-root', str(self.private), '--report', str(receipt)], capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(json.loads(applied.stdout)['copied'], 1)
        self.assertTrue(receipt.exists())

    def test_untrusted_fields_and_reason_with_credentials_are_refused(self):
        self.source()
        selection = self.selection()
        selection['arbitrary'] = 'untrusted'
        with self.assertRaises(archive.ArchiveError):
            self.plan(selection)
        secret = 'sk-' + 'A9b8C7' * 7
        selection = self.selection(required_external_data=[{'source': 'batch/data', 'reason': secret}])
        with self.assertRaises(archive.ArchiveError) as error:
            self.plan(selection)
        self.assertNotIn(secret, str(error.exception))


if __name__ == '__main__':
    unittest.main()
