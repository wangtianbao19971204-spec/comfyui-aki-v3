import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import workspace_history as history


class WorkspaceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.git'
        self.source.mkdir()
        history.git(self.source, 'init', '--bare')
        self.empty = history.hm.put_object(self.source, 'tree', b'')
        self.public = self.root / 'public.git'

    def tearDown(self):
        self.temp.cleanup()

    def blob(self, data):
        return history.hm.put_object(self.source, 'blob', data)

    def tree(self, rows):
        return history.hm.put_object(self.source, 'tree', history.encode_tree(rows))

    def commit(self, tree, parents=(), message=b'fixture\n', signature=False):
        header = b'tree ' + tree.encode()
        header += b''.join(b'\nparent ' + parent.encode() for parent in parents)
        header += b'\nauthor Fixture <fixture@invalid.local> 1700000000 +0000'
        header += b'\ncommitter Fixture <fixture@invalid.local> 1700000000 +0000'
        if signature:
            header += b'\ngpgsig -----BEGIN PGP SIGNATURE-----\n test-signature\n -----END PGP SIGNATURE-----'
        return history.hm.put_object(self.source, 'commit', header + b'\n\n' + message)

    def head(self, oid):
        history.git(self.source, 'update-ref', 'refs/heads/main', oid)
        history.git(self.source, 'symbolic-ref', 'HEAD', 'refs/heads/main')

    def build(self, **kwargs):
        return history.build(self.source, self.public, self.root / 'map.json', self.root / 'scan.json', **kwargs)

    def verify(self, report):
        return history.verify(self.source, self.public, report)

    def test_untouched_graph_unreachable_commit_and_tag_keep_ids(self):
        base = self.commit(self.empty)
        head = self.commit(self.empty, [base], b'head\n')
        orphan = self.commit(self.empty, [base], b'unreachable\n')
        self.head(head)
        tag = history.hm.put_object(self.source, 'tag',
            f'object {head}\ntype commit\ntag version\ntagger Fixture <fixture@invalid.local> 1700000000 +0000\n\nrelease\n'.encode())
        history.git(self.source, 'update-ref', 'refs/tags/version', tag)
        before = history.hm.inventory_files(self.source)
        report = self.build()
        self.assertEqual(report['commit_map'], {base: base, head: head, orphan: orphan})
        self.assertEqual(report['tag_map'], {tag: tag})
        self.assertEqual(report['source_fully_unreachable_commits'], 1)
        self.assertEqual(report['recovered_tips'], {orphan: orphan})
        self.assertEqual(before, history.hm.inventory_files(self.source))
        self.assertEqual(self.verify(report)['commits_verified'], 3)
        self.assertTrue(history.sg.run(self.public)['pass'])

    def test_weights_externalized_and_reference_hash_verified(self):
        kept = self.blob(b'print("unchanged")\n')
        dropped = self.blob(b'unpublished weight fixture')
        child = self.tree([(b'weight.bin', dropped, b'100644'), (b'code.py', kept, b'100644')])
        root = self.tree([(b'dependency', child, b'40000')])
        base = self.commit(self.empty)
        changed = self.commit(root, [base], b'resource\n', signature=True)
        self.head(changed)
        report = self.build()
        self.assertEqual(report['commit_map'][base], base)
        self.assertNotEqual(report['commit_map'][changed], changed)
        self.assertEqual(report['externalized_blobs'][dropped]['sha256'], hashlib.sha256(b'unpublished weight fixture').hexdigest())
        self.assertEqual(report['stripped_invalid_signatures'][0]['removed_headers'], ['gpgsig'])
        self.assertNotIn(dropped, history.metadata(self.public))
        self.assertIn(kept, history.metadata(self.public))
        self.assertTrue(self.verify(report)['only_declared_payload_or_gitlink_exclusions'])
        self.assertTrue(history.sg.run(self.public)['pass'])

    def test_same_forbidden_blob_is_not_renamed_to_safe_extension(self):
        blob = self.blob(b'forbidden shared fixture')
        tree = self.tree([(b'weights.bin', blob, b'100644'), (b'fake.txt', blob, b'100644')])
        self.head(self.commit(tree))
        report = self.build()
        refs = report['reference_roots'][tree]['externalized_entries']
        self.assertEqual({item['path'] for item in refs}, {'weights.bin', 'fake.txt'})
        self.assertNotIn(blob, history.metadata(self.public))
        self.verify(report)

    def test_gitlink_replaced_by_plain_text_metadata(self):
        gitlink = 'a' * 40
        root = self.tree([(b'dependency', gitlink, b'160000')])
        old = self.commit(root)
        self.head(old)
        report = self.build()
        entry = report['reference_roots'][root]['externalized_entries'][0]
        self.assertEqual(entry['object'], gitlink)
        self.assertEqual(entry['reasons'], ['nested_gitlink'])
        self.assertEqual(self.verify(report)['commits_verified'], 1)
        self.assertTrue(history.sg.run(self.public)['pass'])

    def test_shallow_parent_requires_opt_in_and_exact_boundary(self):
        missing = 'b' * 40
        old = self.commit(self.empty, [missing])
        self.head(old)
        (self.source / 'shallow').write_text(old + '\n', encoding='ascii')
        with self.assertRaises(ValueError):
            self.build()
        report = self.build(allow_shallow=True)
        self.assertEqual(report['missing_shallow_parents'], [{'commit': old, 'missing_parent': missing, 'parent_position': 0}])
        self.assertNotEqual(report['commit_map'][old], old)
        self.assertEqual(self.verify(report)['missing_shallow_edges_verified'], 1)
        self.assertEqual(history.git(self.public, 'rev-parse', '--is-shallow-repository').stdout.strip(), b'false')

    def test_missing_non_shallow_parent_refused(self):
        old = self.commit(self.empty, ['c' * 40])
        self.head(old)
        with self.assertRaises(ValueError):
            self.build(allow_shallow=True)
        self.assertFalse(self.public.exists())

    def test_credentials_fail_closed_before_public_objects_created(self):
        value = b'sk-' + b'aZ9kL2mN7pQ4rS6tU8vW0xY3' + b'AbCdEf'
        blob = self.blob(b'api_key = "' + value + b'"\n')
        self.head(self.commit(self.tree([(b'unsafe.py', blob, b'100644')])))
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.public.exists())
        scan = json.loads((self.root / 'scan.json').read_text())
        self.assertTrue(scan['findings'])
        self.assertNotIn(value.decode(), json.dumps(scan))

    def test_metadata_name_collision_fails_closed(self):
        blob = self.blob(b'forbidden payload')
        root = self.tree([(b'weight.bin', blob, b'100644'), (history.REFERENCE_FILE, self.blob(b'{}'), b'100644')])
        self.head(self.commit(root))
        with self.assertRaises(ValueError):
            self.build()

    def test_destination_is_never_overwritten(self):
        self.head(self.commit(self.empty))
        self.public.mkdir()
        with self.assertRaises(ValueError):
            self.build()

    def test_reflog_only_commit_is_scanned_and_preserved(self):
        base = self.commit(self.empty)
        side = self.commit(self.empty, [base], b'reflog only\n')
        head = self.commit(self.empty, [base], b'current head\n')
        history.git(self.source, 'update-ref', '--create-reflog', 'refs/heads/main', side)
        self.head(head)
        report = self.build()
        self.assertEqual(report['source_reflog_only_commits'], 1)
        self.assertEqual(report['source_fully_unreachable_commits'], 0)
        self.assertEqual(report['commit_map'][side], side)
        self.verify(report)

    def test_unreferenced_credential_commit_is_not_skipped(self):
        self.head(self.commit(self.empty))
        value = b'sk-' + b'aZ9kL2mN7pQ4rS6tU8vW0xY3' + b'AbCdEf'
        blob = self.blob(b'api_key = "' + value + b'"\n')
        self.commit(self.tree([(b'forgotten.py', blob, b'100644')]), message=b'forgotten\n')
        self.assertTrue(history.sg.run(self.source)['pass'])
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.public.exists())

    def test_exact_review_allows_credential_payload_externalization_not_exemption(self):
        value = b'sk-' + b'aZ9kL2mN7pQ4rS6tU8vW0xY3' + b'AbCdEf'
        payload = b'api_key = "' + value + b'"\n'
        blob = self.blob(payload)
        self.head(self.commit(self.tree([(b'config.py', blob, b'100644')])))
        scan = history.SourceGraph(self.source).scan()
        plan = {'schema': 1, 'objects': {blob: {
            'sha256': hashlib.sha256(payload).hexdigest(), 'paths': ['config.py'],
            'finding_rules': sorted({item['rule'] for item in scan['findings']}),
            'reason': 'credential_bearing_history_payload'}}}
        report = self.build(externalization_plan=plan)
        self.assertNotIn(blob, history.metadata(self.public))
        self.assertTrue(history.sg.run(self.public)['pass'])
        self.assertNotIn(value.decode(), json.dumps(report))
        self.verify(report)

    def test_reviewed_payload_hash_drift_is_rejected(self):
        payload = b'weight fixture'
        blob = self.blob(payload)
        self.head(self.commit(self.tree([(b'weight.bin', blob, b'100644')])))
        plan = {'schema': 1, 'objects': {blob: {'sha256': '0' * 64,
                'paths': ['weight.bin'], 'finding_rules': ['model_weight_payload'],
                'reason': 'unreviewed_credential_shaped_history_payload'}}}
        with self.assertRaises(ValueError):
            self.build(externalization_plan=plan)
        self.assertNotIn(blob, history.metadata(self.public))

    def test_merge_parent_order_and_aggregate_coverage(self):
        base = self.commit(self.empty)
        first = self.commit(self.empty, [base], b'first\n')
        second = self.commit(self.empty, [base], b'second\n')
        merge = self.commit(self.empty, [second, first], b'merge\n')
        self.head(merge)
        report = self.build()
        aggregate = history.aggregate_history(self.public, report, self.root / 'aggregate.json')
        result = history.verify(self.source, self.public, report, aggregate)
        self.assertEqual(result['commits_verified'], 4)

    def test_parallel_full_history_gate_matches_serial(self):
        one = self.blob(b'normal source one')
        two = self.blob(b'normal source two')
        self.head(self.commit(self.tree([(b'a.txt', one, b'100644'), (b'b.txt', two, b'100644')])))
        report = self.build(scan_workers=2)
        serial = history.sg.run(self.public)
        parallel = history.audit_public(self.public, workers=2)
        for key in ['pass', 'findings', 'scanned_objects', 'scanned_blobs', 'scanned_bytes', 'cross_part_boundaries']:
            self.assertEqual(serial[key], parallel[key], key)
        self.verify(report)

    def test_parallel_gate_falls_back_for_cross_part_boundaries(self):
        value = b'sk-' + b'aZ9kL2mN7pQ4rS6tU8vW0xY3' + b'AbCdEf'
        first = self.blob(value[:19])
        second = self.blob(value[19:])
        self.head(self.commit(self.tree([(b'part-00000.part', first, b'100644'),
                                         (b'part-00001.part', second, b'100644')])))
        serial = history.SourceGraph(self.source).scan()
        parallel = history.SourceGraph(self.source).scan(workers=2)
        self.assertEqual(serial['findings'], parallel['findings'])
        self.assertEqual(parallel['cross_part_boundaries'], 1)
        self.assertTrue(any(item['rule'].startswith('cross_part_') for item in parallel['findings']))

    def test_git_environment_redirection_is_ignored_and_restored(self):
        blob = self.blob(b'intended source')
        head = self.commit(self.tree([(b'code.txt', blob, b'100644')]))
        self.head(head)
        injections = {name: str(self.root / 'wrong-location') for name in [
            'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE',
            'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
            'GIT_NAMESPACE', 'GIT_SHALLOW_FILE', 'GIT_REPLACE_REF_BASE']}
        injections.update({'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'alias.injection',
                           'GIT_CONFIG_VALUE_0': 'must not be used'})
        with patch.dict(os.environ, injections):
            before = {key: value for key, value in os.environ.items() if key.startswith('GIT_')}
            self.assertEqual(history.git(self.source, 'rev-parse', 'HEAD').stdout.strip().decode(), head)
            with history.Reader(self.source) as reader:
                self.assertEqual(reader.read(blob), ('blob', b'intended source'))
            with history.scoped_git_environment(self.source):
                self.assertNotIn('GIT_DIR', os.environ)
                self.assertEqual(os.environ['GIT_NO_REPLACE_OBJECTS'], '1')
            self.assertEqual(before, {key: value for key, value in os.environ.items() if key.startswith('GIT_')})
            report = self.build()
            self.verify(report)
            aggregate = history.aggregate_history(self.public, report, self.root / 'aggregate.json')
            self.assertTrue(history.verify(self.source, self.public, report, aggregate)['fsck_strict_passed'])
            self.assertEqual(before, {key: value for key, value in os.environ.items() if key.startswith('GIT_')})

    def test_verification_rejects_restored_original_gitlink_tree(self):
        tree = self.tree([(b'component', 'a' * 40, b'160000')])
        old = self.commit(tree)
        self.head(old)
        report = self.build()
        for oid in [tree, old]:
            with history.Reader(self.source) as reader:
                kind, data = reader.read(oid)
            self.assertEqual(history.hm.put_object(self.public, kind, data), oid)
        history.git(self.public, 'update-ref', 'refs/heads/main', old)
        report['commit_map'][old] = old
        report['refs'][0]['public_oid'] = old
        with self.assertRaises(RuntimeError):
            self.verify(report)

    def test_verification_rejects_wrong_tree_tag_target(self):
        content = self.blob(b'safe document')
        target = self.tree([(b'correct.txt', content, b'100644')])
        other = self.tree([(b'wrong.txt', content, b'100644')])
        self.head(self.commit(other))
        suffix = b'\ntype tree\ntag version\ntagger Fixture <fixture@invalid.local> 1700000000 +0000\n\nrelease\n'
        tag = history.hm.put_object(self.source, 'tag', b'object ' + target.encode() + suffix)
        history.git(self.source, 'update-ref', 'refs/tags/version', tag)
        report = self.build()
        self.verify(report)
        wrong = history.hm.put_object(self.public, 'tag', b'object ' + other.encode() + suffix)
        history.git(self.public, 'update-ref', 'refs/tags/version', wrong)
        history.git(self.public, 'update-ref', 'refs/archive-tags/' + tag, wrong)
        report['tag_map'][tag] = wrong
        next(item for item in report['refs'] if item['ref'] == 'refs/tags/version')['public_oid'] = wrong
        with self.assertRaises((RuntimeError, KeyError)):
            self.verify(report)

    def test_verification_rejects_wrong_blob_tag_target(self):
        target = self.blob(b'correct document')
        other = self.blob(b'wrong document')
        self.head(self.commit(self.tree([(b'correct.txt', target, b'100644'), (b'wrong.txt', other, b'100644')])))
        suffix = b'\ntype blob\ntag version\ntagger Fixture <fixture@invalid.local> 1700000000 +0000\n\nrelease\n'
        tag = history.hm.put_object(self.source, 'tag', b'object ' + target.encode() + suffix)
        history.git(self.source, 'update-ref', 'refs/tags/version', tag)
        report = self.build()
        self.verify(report)
        wrong = history.hm.put_object(self.public, 'tag', b'object ' + other.encode() + suffix)
        history.git(self.public, 'update-ref', 'refs/tags/version', wrong)
        history.git(self.public, 'update-ref', 'refs/archive-tags/' + tag, wrong)
        report['tag_map'][tag] = wrong
        next(item for item in report['refs'] if item['ref'] == 'refs/tags/version')['public_oid'] = wrong
        with self.assertRaises(RuntimeError):
            self.verify(report)

    def test_verification_rejects_wrong_direct_blob_ref(self):
        target = self.blob(b'correct document')
        other = self.blob(b'wrong document')
        self.head(self.commit(self.tree([(b'correct.txt', target, b'100644'), (b'wrong.txt', other, b'100644')])))
        history.git(self.source, 'update-ref', 'refs/notes/fixture', target)
        report = self.build()
        self.verify(report)
        history.git(self.public, 'update-ref', 'refs/notes/fixture', other)
        next(item for item in report['refs'] if item['ref'] == 'refs/notes/fixture')['public_oid'] = other
        with self.assertRaises(RuntimeError):
            self.verify(report)

    def test_verification_rejects_additional_noncommit_ref(self):
        blob = self.blob(b'safe document')
        self.head(self.commit(self.tree([(b'document.txt', blob, b'100644')])))
        report = self.build()
        history.git(self.public, 'update-ref', 'refs/notes/unexpected', blob)
        with self.assertRaises(RuntimeError):
            self.verify(report)

    def test_verification_rejects_missing_unreferenced_tag(self):
        head = self.commit(self.empty)
        self.head(head)
        suffix = b'\ntype commit\ntag version\ntagger Fixture <fixture@invalid.local> 1700000000 +0000\n\nrelease\n'
        tag = history.hm.put_object(self.source, 'tag', b'object ' + head.encode() + suffix)
        report = self.build()
        self.verify(report)
        del report['tag_map'][tag]
        history.git(self.public, 'update-ref', '-d', 'refs/archive-tags/' + tag)
        with self.assertRaises(RuntimeError):
            self.verify(report)


if __name__ == '__main__':
    unittest.main()
