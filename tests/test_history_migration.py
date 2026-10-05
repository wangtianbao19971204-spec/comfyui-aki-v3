import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/history_migration.py"
SPEC = importlib.util.spec_from_file_location("history_migration", SCRIPT)
history = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history)


class HistoryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.git"
        subprocess.run(["git", "init", "--bare", str(self.source)], check=True, capture_output=True)
        self.empty_tree = history.put_object(self.source, "tree", b"")

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, tree, parents=(), message=b"fixture\n", signature=False):
        header = b"tree " + tree.encode()
        for parent in parents:
            header += b"\nparent " + parent.encode()
        header += b"\nauthor Test <test@invalid.local> 1700000000 +0000\ncommitter Test <test@invalid.local> 1700000000 +0000"
        if signature:
            header += b"\ngpgsig -----BEGIN PGP SIGNATURE-----\n synthetic-signature\n -----END PGP SIGNATURE-----"
        return history.put_object(self.source, "commit", header + b"\n\n" + message)

    def ref(self, name, oid):
        history.git(self.source, "update-ref", name, oid)

    def build(self, redactions=None):
        return history.build_public_repository(self.source, self.root / "public.git", self.root / "report.json", redactions)

    def test_preserves_unmodified_commits_and_annotated_tag(self):
        base = self.commit(self.empty_tree)
        top = self.commit(self.empty_tree, [base])
        tag = history.put_object(self.source, "tag", f"object {top}\ntype commit\ntag v1\ntagger Test <test@invalid.local> 1700000000 +0000\n\nrelease\n".encode())
        self.ref("refs/heads/master", top)
        self.ref("refs/tags/v1", tag)
        report = self.build()
        self.assertEqual(report["commit_map"], {base: base, top: top})
        self.assertEqual(history.git(self.root / "public.git", "rev-parse", "refs/tags/v1").stdout.strip().decode(), tag)

    def test_exact_redaction_parent_graph_and_unreachable_commit(self):
        secret = b"LOCAL_TEST_CREDENTIAL_123456789"
        original = b'api_key = "' + secret + b'"\nkeep = "unchanged"\n'
        blob = history.put_object(self.source, "blob", original)
        tree = history.put_object(self.source, "tree", b"100644 node.py\0" + bytes.fromhex(blob))
        base = self.commit(self.empty_tree)
        changed = self.commit(tree, [base], signature=True)
        descendant = self.commit(self.empty_tree, [changed], b"descendant\n")
        orphan = self.commit(self.empty_tree, [base], b"unreferenced\n")
        self.ref("refs/heads/master", descendant)
        rule = {blob: {"value_sha256": hashlib.sha256(secret).hexdigest(), "replacement": b"REDACTED_API_KEY", "expected_occurrences": 1}}
        report = self.build(rule)
        mapping = report["commit_map"]
        self.assertEqual(report["source_original_commit_count"], 4)
        self.assertEqual(report["public_commit_count"], 4)
        self.assertEqual(mapping[base], base)
        self.assertEqual(mapping[orphan], orphan)
        self.assertNotEqual(mapping[changed], changed)
        self.assertNotEqual(mapping[descendant], descendant)
        self.assertEqual(report["source_fully_unreachable_commits"], 1)
        self.assertEqual(report["recovered_tips"], {orphan: orphan})
        self.assertEqual(report["stripped_invalid_signatures"][0]["removed_headers"], ["gpgsig"])
        destination = self.root / "public.git"
        self.assertNotIn(blob, history.object_metadata(destination))
        self.assertEqual(history.git(destination, "show", f"{mapping[changed]}:node.py").stdout, b'api_key = "REDACTED_API_KEY"\nkeep = "unchanged"\n')
        self.assertIn(b"parent " + mapping[changed].encode(), history.git(destination, "cat-file", "-p", mapping[descendant]).stdout)
        self.assertEqual(history.git(self.source, "cat-file", "-p", blob).stdout, original)
        receipt = history.verify_mapping(self.source, destination, report)
        self.assertEqual(receipt["commits_verified"], 4)
        self.assertTrue(receipt["only_known_blob_changes"])

    def test_reflog_only_commit_is_recovered(self):
        base = self.commit(self.empty_tree)
        lost = self.commit(self.empty_tree, [base], b"previous\n")
        history.git(self.source, "config", "core.logAllRefUpdates", "true")
        self.ref("refs/heads/master", lost)
        self.ref("refs/heads/master", base)
        report = self.build()
        self.assertEqual(report["source_reflog_only_commits"], 1)
        self.assertEqual(report["source_fully_unreachable_commits"], 0)
        self.assertEqual(report["recovered_tips"], {lost: lost})

    def test_rejects_destination_overwrite(self):
        base = self.commit(self.empty_tree)
        self.ref("refs/heads/master", base)
        (self.root / "public.git").mkdir()
        with self.assertRaises(ValueError):
            self.build()

    def test_refuses_wrong_secret_hash(self):
        fixture = b'LOCAL_TEST_CREDENTIAL_123456789'
        payload = b'api_key = "' + fixture + b'"\n'
        with self.assertRaises(ValueError):
            history.redact_blob(payload, {"value_sha256": "0" * 64, "replacement": b"REDACTED_API_KEY", "expected_occurrences": 1})

    def test_public_token_and_query_redaction_are_exact(self):
        value = b"LOCAL_TEST_QUERY_CREDENTIAL_123"
        rule = {"value_sha256": hashlib.sha256(value).hexdigest(), "replacement": b"", "expected_occurrences": 1}
        assignment = b'public_token = "' + value + b'"\nuntouched = "notes"\n'
        query = b'url = "https://example.invalid/file?access_token=' + value + b'&page=1"\n'
        self.assertEqual(history.redact_blob(assignment, rule), b'public_token = ""\nuntouched = "notes"\n')
        self.assertEqual(history.redact_blob(query, rule), b'url = "https://example.invalid/file?access_token=&page=1"\n')

    def test_merge_parent_order_and_changed_annotated_tag(self):
        value = b"LOCAL_TEST_API_CREDENTIAL_987654"
        blob = history.put_object(self.source, "blob", b'api_key = "' + value + b'"\n')
        tree = history.put_object(self.source, "tree", b"100644 node.py\0" + bytes.fromhex(blob))
        base = self.commit(self.empty_tree)
        left = self.commit(tree, [base], b"left\n")
        right = self.commit(self.empty_tree, [base], b"right\n")
        merge = self.commit(self.empty_tree, [left, right], b"merge\n")
        tag = history.put_object(self.source, "tag", f"object {merge}\ntype commit\ntag v2\ntagger Test <test@invalid.local> 1700000000 +0000\n\nrelease annotation\n".encode())
        self.ref("refs/heads/master", merge)
        self.ref("refs/tags/v2", tag)
        rule = {blob: {"value_sha256": hashlib.sha256(value).hexdigest(), "replacement": b"", "expected_occurrences": 1}}
        report = self.build(rule)
        mapping = report["commit_map"]
        destination = self.root / "public.git"
        payload = history.git(destination, "cat-file", "-p", mapping[merge]).stdout
        actual_parents = [line[7:].decode() for line in payload.splitlines() if line.startswith(b"parent ")]
        self.assertEqual(actual_parents, [mapping[left], mapping[right]])
        public_tag = history.git(destination, "cat-file", "-p", "refs/tags/v2").stdout
        self.assertTrue(public_tag.startswith(b"object " + mapping[merge].encode() + b"\n"))
        self.assertTrue(public_tag.endswith(b"\n\nrelease annotation\n"))

    def test_single_archive_copies_exact_git_bytes(self):
        base = self.commit(self.empty_tree)
        self.ref("refs/heads/master", base)
        before = history.inventory_files(self.source)
        target = self.root / "private.git"
        receipt = history.backup_single(self.source, target, self.root / "private-manifest.json")
        self.assertTrue(receipt["byte_identical"])
        self.assertEqual(before, history.inventory_files(target))
        self.assertEqual(before, history.inventory_files(self.source))

    def test_tree_parser_keeps_filename_bytes(self):
        oid = "1" * 40
        header = b"100644 name with spaces.py\0"
        self.assertEqual(list(history.tree_entries(header + bytes.fromhex(oid))), [(header, oid, b"100644")])

    def test_archive_has_bounded_parents_and_complete_ancestry(self):
        base = self.commit(self.empty_tree)
        branches = [self.commit(self.empty_tree, [base], f"branch {number}\n".encode()) for number in range(5)]
        self.ref("refs/heads/master", branches[0])
        report = self.build()
        destination = self.root / "public.git"
        receipt = history.aggregate_history(destination, report, self.root / "archive.json", parent_limit=2)
        self.assertEqual(receipt["source_graph_tips"], 5)
        self.assertEqual(receipt["source_public_commits"], 6)
        self.assertEqual(receipt["maximum_parent_count"], 2)
        self.assertTrue(receipt["all_mapped_commits_reachable"])
        self.assertEqual(history.git(destination, "rev-parse", "HEAD").stdout.decode().strip(), branches[0])
        with self.assertRaises(ValueError):
            history.aggregate_history(destination, report, self.root / "archive-again.json")

    def test_new_path_rejects_parent_escape(self):
        allowed = self.root / "allowed"
        allowed.mkdir()
        with self.assertRaises(ValueError):
            history.validate_new_path(allowed / ".." / "escaped", parent=allowed)

    def test_single_tip_archive_still_uses_empty_tree(self):
        blob = history.put_object(self.source, "blob", b"fixture\n")
        tree = history.put_object(self.source, "tree", b"100644 example.txt\0" + bytes.fromhex(blob))
        base = self.commit(tree)
        self.ref("refs/heads/master", base)
        report = self.build()
        destination = self.root / "public.git"
        receipt = history.aggregate_history(destination, report, self.root / "archive.json")
        self.assertEqual(receipt["aggregate_commits_created"], 1)
        self.assertEqual(receipt["archive_reachable_commits"], 2)
        self.assertEqual(history.git(destination, "rev-parse", receipt["archive_commit"] + "^{tree}").stdout.decode().strip(), self.empty_tree)


if __name__ == "__main__":
    unittest.main()
