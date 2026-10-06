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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import technical_catalog as catalog

ARCHIVE_README_TEXT = (
    "# 历史技术参考归档\n\n"
    "这里保存经过显式清单、内容哈希和凭据门禁审核的技术原件副本。\n"
    "它们不是当前部署源，也不因归档而获得执行授权；旧脚本可能包含固定路径、日期、PID、发布或回滚操作。\n"
    "需要复用时先在唯一主 Git 中审查与适配，再按现行维护流程验证。\n\n"
    "归档文件的原相对路径、SHA-256 和角色见 `../../../governance/technical-archive.json`。\n"
    "仓外原件不移动、不删除；private reference、缺失 fixture、模型、缓存和媒体没有被此工具备份。\n"
    "归档完整不表示依赖闭合、冷启动或实际功能验收通过。\n")


class TechnicalCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("scripts/example.py", "pass\n")
        self.write("docs/technical/README.md", "# Index\n[Feature](sample.md)\n")
        self.write("docs/technical/sample.md", "# Example\n\n## 实现\n[Code](../../scripts/example.py)\n\n## 验证\nOnly fixture.\n\n## 变更记录\n2026-10-05\n")
        self.data = {"schema": 1, "indexes": ["docs/technical/README.md"], "features": [
            {"id": "sample", "document": "docs/technical/sample.md", "implementation": ["scripts/example.py"],
             "tests": [], "evidence": [], "examples": ["docs/technical/sample.md"],
             "watch": ["scripts/"], "acceptance": "checked-source"}]}
        self.save_catalog()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def save_catalog(self):
        self.write(catalog.CATALOG, json.dumps(self.data, ensure_ascii=False))

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def init(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", "--", "scripts", "docs")
        self.git("commit", "-qm", "fixture")

    def test_valid_and_read_only(self):
        before = (self.root / catalog.CATALOG).read_bytes()
        self.assertTrue(catalog.check(self.root)["pass"])
        self.assertEqual(before, (self.root / catalog.CATALOG).read_bytes())

    def test_missing_implementation_rejected(self):
        (self.root / "scripts/example.py").unlink()
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_missing_examples_cannot_claim_complete_handoff(self):
        for value in (None, [], "docs/technical/sample.md"):
            with self.subTest(value=value):
                self.data["features"][0]["examples"] = value
                self.save_catalog()
                self.assertFalse(catalog.check(self.root)["pass"])

    def test_staged_examples_must_be_in_the_prospective_commit(self):
        self.init()
        self.write("examples/asset.json", "{}\n")
        self.data["features"][0]["examples"] = ["examples/asset.json"]
        self.save_catalog()
        self.git("add", "--", catalog.CATALOG)
        self.assertFalse(catalog.check(self.root, staged=True)["pass"])
        self.git("add", "--", "examples/asset.json")
        self.assertTrue(catalog.check(self.root, staged=True)["pass"])
        (self.root / "examples/asset.json").unlink()
        self.assertTrue(catalog.check(self.root, staged=True)["pass"])

    def test_data_governance_and_examples_require_owned_updates(self):
        self.init()
        self.data["features"][0]["watch"].extend([
            "governance/", "examples/", "snapshot/library/", "snapshot/inventory/"])
        self.save_catalog()
        self.git("add", "--", catalog.CATALOG)
        for name in ("governance/policy.json", "examples/asset.json",
                     "snapshot/library/part.json", "snapshot/inventory/resources.json"):
            self.write(name, "{}\n")
            self.git("add", "--", name)
        result = catalog.check(self.root, staged=True, enforce_changes=True)
        self.assertFalse(result["pass"])
        self.assertIn("sample: source changed without its technical update note", result["errors"])
        self.write("docs/technical/changes/sample/2026-10-06.md",
                   "# Change 2026-10-06\nDocumented resource format, validation and remaining limits.\n")
        self.git("add", "--", "docs/technical/changes/sample/2026-10-06.md")
        self.assertTrue(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])

    def test_duplicate_identity_rejected(self):
        self.data["features"].append(dict(self.data["features"][0]))
        self.save_catalog()
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_undocumented_acceptance_rejected(self):
        self.data["features"][0]["acceptance"] = "all-live-pass"
        self.save_catalog()
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_paths_and_globs_rejected(self):
        for name in ("../secret", "G:/secret", "/secret", "a\\b", "a//b", "a/./b", ".git/config", "a/*.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                catalog.relative(name)

    def test_missing_link_rejected(self):
        self.write("docs/technical/README.md", "[Gone](absent.md)\n")
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_absolute_and_escaping_links_rejected(self):
        for target in ("G:/ComfyUI/private.json", "../../../../secret", "/etc/passwd", "%2e%2e/%2e%2e/%2e%2e/outside"):
            self.write("docs/technical/README.md", "[Bad](" + target + ")\n")
            self.assertFalse(catalog.check(self.root)["pass"])

    def test_code_fence_commands_not_links(self):
        self.write("docs/technical/README.md", "```text\n[example](../missing.md)\n```\n")
        self.assertTrue(catalog.check(self.root)["pass"])

    def test_undated_feature_rejected(self):
        self.write("docs/technical/sample.md", "# Example\n\n## 实现\n\n## 验证\n\n## 更新\n")
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_untracked_reference_rejected(self):
        self.init()
        self.write("scripts/new.py", "pass\n")
        self.data["features"][0]["implementation"].append("scripts/new.py")
        self.save_catalog()
        self.assertFalse(catalog.check(self.root, require_tracked=True)["pass"])

    def test_staged_document_required_and_reads_index(self):
        self.init()
        self.write("scripts/example.py", "print('changed')\n")
        self.git("add", "--", "scripts/example.py")
        self.assertFalse(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])
        path = self.root / "docs/technical/sample.md"
        self.write("docs/technical/sample.md", path.read_text(encoding="utf-8") + "\n2026-10-06: changed.\n")
        self.assertFalse(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])
        self.git("add", "--", "docs/technical/sample.md")
        self.assertTrue(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])

    def test_immutable_feature_note_satisfies_change(self):
        self.init()
        self.write("scripts/example.py", "print('changed')\n")
        self.write("docs/technical/changes/sample/2026-10-06.md", "# Change 2026-10-06\nNew behavior and verification, with remaining limitations recorded.\n")
        self.git("add", "--", "scripts/example.py", "docs/technical/changes/sample/2026-10-06.md")
        self.assertTrue(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])

    def test_empty_change_note_cannot_bypass_contract(self):
        self.init()
        self.write("scripts/example.py", "print('changed')\n")
        self.write("docs/technical/changes/sample/2026-10-06.md", "")
        self.git("add", "--", "scripts/example.py", "docs/technical/changes/sample/2026-10-06.md")
        self.assertFalse(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])

    def test_directory_links_supported(self):
        self.write("docs/technical/README.md", "[Tools](../../scripts/)\n")
        self.assertTrue(catalog.check(self.root)["pass"])
        self.init()
        self.assertTrue(catalog.check(self.root, staged=True)["pass"])

    def test_prospective_commit_index_is_used(self):
        self.init()
        alternate = str(self.root / "prospective-index")
        with patch.dict(os.environ, {"GIT_INDEX_FILE": alternate}):
            self.git("read-tree", "HEAD")
            self.write("scripts/example.py", "print('changed')\n")
            self.git("add", "--", "scripts/example.py")
            self.assertFalse(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])
        self.assertTrue(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])

    def test_unowned_source_rejected(self):
        self.init()
        self.write("database/migrate.py", "pass\n")
        self.git("add", "--", "database/migrate.py")
        self.assertFalse(catalog.check(self.root, staged=True, enforce_changes=True)["pass"])

    def test_staged_without_enforcement_is_structural(self):
        self.init()
        self.assertTrue(catalog.check(self.root, staged=True)["pass"])
        with self.assertRaises(ValueError):
            catalog.check(self.root, enforce_changes=True)

    def test_tests_and_hooks_need_owned_technical_updates(self):
        self.init()
        for name in ("tests/test_new.py", ".githooks/pre-commit", ".github/workflows/check.yml"):
            self.write(name, "fixture\n")
            self.git("add", "--", name)
        result = catalog.check(self.root, staged=True, enforce_changes=True)
        self.assertFalse(result["pass"])
        self.assertEqual(sum("No technical owner" in e for e in result["errors"]), 3)

    def make_archive(self, data=b"raise RuntimeError('archived sources must never execute')\n"):
        source = "benchmark_reports/example.py"
        target = catalog.ARCHIVE + "/" + source
        path = self.root / target
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        (self.root / catalog.ARCHIVE_README).write_bytes(ARCHIVE_README_TEXT.encode("utf-8"))
        provenance = {"schema": 1, "role": "historical_reference_not_deployable", "files": [{
            "source": source, "path": target, "role": "implementation",
            "sha256": hashlib.sha256(data).hexdigest()}]}
        self.write(catalog.ARCHIVE_REGISTRY, json.dumps(provenance))
        return provenance, path

    def stage_archive(self):
        self.git("add", "--", catalog.ARCHIVE, catalog.ARCHIVE_REGISTRY)

    def test_archive_is_optional_but_tree_and_registry_are_paired(self):
        self.assertTrue(catalog.check(self.root)["pass"])
        (self.root / catalog.ARCHIVE).mkdir()
        self.assertFalse(catalog.check(self.root)["pass"])
        (self.root / catalog.ARCHIVE).rmdir()
        self.write(catalog.ARCHIVE_REGISTRY, json.dumps({
            "schema": 1, "role": "historical_reference_not_deployable", "files": []}))
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_verifies_inert_bytes_without_executing_or_modifying(self):
        _, path = self.make_archive()
        before = {name: (self.root / name).read_bytes() for name in (
            catalog.ARCHIVE_REGISTRY, catalog.ARCHIVE_README, path.relative_to(self.root).as_posix())}
        result = catalog.check(self.root)
        self.assertTrue(result["pass"], result["errors"])
        self.assertEqual(result["archive_files"], 1)
        self.assertGreaterEqual(result["referenced_files"], 7)
        for name, data in before.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_archive_byte_drift_and_fixed_readme_drift_rejected(self):
        _, path = self.make_archive()
        before = path.read_bytes()
        path.write_bytes(before + b"\n")
        self.assertTrue(any("SHA-256 mismatch" in error for error in catalog.check(self.root)["errors"]))
        path.write_bytes(before)
        (self.root / catalog.ARCHIVE_README).write_bytes(b"not the fixed tool README")
        self.assertTrue(any("SHA-256 mismatch" in error for error in catalog.check(self.root)["errors"]))

    def test_archive_unknown_and_missing_files_rejected(self):
        _, path = self.make_archive()
        unknown = path.with_name("unknown.txt")
        unknown.write_bytes(b"not registered")
        self.assertFalse(catalog.check(self.root)["pass"])
        unknown.unlink()
        path.unlink()
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_schema_mapping_roles_hash_and_canonical_source_checked(self):
        original, _ = self.make_archive()
        invalid = [[], {**original, "schema": True}, {**original, "schema": 2},
                   {**original, "role": "deployed"}, {**original, "extra": True},
                   {**original, "files": {}}, {**original, "files": ["not a record"]}]
        for key, value in (("role", "private_reference"), ("sha256", "f" * 63),
                           ("sha256", "A" * 64), ("path", "elsewhere/example.py"),
                           ("path", catalog.ARCHIVE + "/other.py"), ("unexpected", "extra")):
            item = copy.deepcopy(original)
            item["files"][0][key] = value
            invalid.append(item)
        for source in ("../outside.py", "/outside.py", "G:/outside.py", "a\\b.py", "a//b.py",
                       "a/./b.py", "a/nul.json", "a/file. /b.py", "a/ｂ.py", ".git/config", "README.md"):
            item = copy.deepcopy(original)
            item["files"][0].update(source=source, path=catalog.ARCHIVE + "/" + source)
            invalid.append(item)
        for number, value in enumerate(invalid):
            with self.subTest(case=number):
                self.write(catalog.ARCHIVE_REGISTRY, json.dumps(value))
                self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_duplicate_rows_aliases_and_json_keys_rejected(self):
        original, _ = self.make_archive()
        for case_alias in (False, True):
            value = copy.deepcopy(original)
            second = dict(value["files"][0])
            if case_alias:
                second["source"] = second["source"].upper()
                second["path"] = catalog.ARCHIVE + "/" + second["source"]
            value["files"].append(second)
            self.write(catalog.ARCHIVE_REGISTRY, json.dumps(value))
            self.assertFalse(catalog.check(self.root)["pass"])
        raw = json.dumps(original).replace('"schema": 1', '"schema": 1, "schema": 1')
        self.write(catalog.ARCHIVE_REGISTRY, raw)
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_missing_readme_and_directory_instead_of_file_rejected(self):
        _, path = self.make_archive()
        readme = self.root / catalog.ARCHIVE_README
        original = readme.read_bytes()
        readme.unlink()
        self.assertFalse(catalog.check(self.root)["pass"])
        readme.write_bytes(original)
        path.unlink()
        path.mkdir()
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_symlink_files_registry_and_directory_rejected(self):
        _, path = self.make_archive()
        outside = self.root / "outside.py"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("Symlinks unavailable")
        self.assertFalse(catalog.check(self.root)["pass"])
        path.unlink()
        path.write_bytes(outside.read_bytes())
        registry = self.root / catalog.ARCHIVE_REGISTRY
        saved_registry = self.root / "outside-registry.json"
        registry.rename(saved_registry)
        registry.symlink_to(saved_registry)
        self.assertFalse(catalog.check(self.root)["pass"])
        registry.unlink()
        saved_registry.rename(registry)
        linked_directory = path.parent.with_name("linked")
        linked_directory.symlink_to(path.parent, target_is_directory=True)
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_hardlinked_file_rejected(self):
        _, path = self.make_archive()
        os.link(path, self.root / "hardlink.py")
        self.assertFalse(catalog.check(self.root)["pass"])

    def test_archive_require_tracked_covers_registry_readme_and_payload(self):
        self.init()
        _, path = self.make_archive()
        result = catalog.check(self.root, require_tracked=True)
        for name in (catalog.ARCHIVE_REGISTRY, catalog.ARCHIVE_README, path.relative_to(self.root).as_posix()):
            self.assertIn("Not tracked: " + name, result["errors"])
        self.git("add", "--", catalog.ARCHIVE)
        self.assertFalse(catalog.check(self.root, require_tracked=True)["pass"])
        self.git("add", "--", catalog.ARCHIVE_REGISTRY)
        self.assertTrue(catalog.check(self.root, require_tracked=True)["pass"])

    def test_archive_staged_view_uses_index_registry_readme_and_payload(self):
        self.init()
        _, path = self.make_archive()
        self.stage_archive()
        original = path.read_bytes()
        path.write_bytes(b"unstaged content")
        self.write(catalog.ARCHIVE_REGISTRY, "invalid unstaged JSON")
        (self.root / catalog.ARCHIVE_README).write_bytes(b"unstaged README")
        self.assertTrue(catalog.check(self.root, staged=True, require_tracked=True)["pass"])
        self.assertFalse(catalog.check(self.root)["pass"])
        self.git("add", "--", path.relative_to(self.root).as_posix())
        path.write_bytes(original)
        self.assertFalse(catalog.check(self.root, staged=True)["pass"])

    def test_archive_staged_pair_and_unregistered_file_checks(self):
        self.init()
        _, path = self.make_archive()
        self.git("add", "--", catalog.ARCHIVE)
        self.assertFalse(catalog.check(self.root, staged=True)["pass"])
        self.git("add", "--", catalog.ARCHIVE_REGISTRY)
        self.assertTrue(catalog.check(self.root, staged=True)["pass"])
        unknown = path.with_name("unknown.py")
        unknown.write_bytes(b"extra")
        self.git("add", "--", unknown.relative_to(self.root).as_posix())
        unknown.unlink()
        self.assertFalse(catalog.check(self.root, staged=True)["pass"])

    def test_archive_staged_symlink_and_gitlink_modes_rejected(self):
        self.init()
        _, path = self.make_archive()
        self.stage_archive()
        name = path.relative_to(self.root).as_posix()
        blob = self.git("rev-parse", ":" + name).decode().strip()
        self.git("update-index", "--cacheinfo", "120000," + blob + "," + name)
        self.assertFalse(catalog.check(self.root, staged=True)["pass"])
        commit = self.git("rev-parse", "HEAD").decode().strip()
        self.git("update-index", "--cacheinfo", "160000," + commit + "," + name)
        self.assertFalse(catalog.check(self.root, staged=True)["pass"])

    def test_archive_prospective_index_is_preserved(self):
        self.init()
        _, path = self.make_archive()
        alternate = str(self.root / "archive-prospective-index")
        with patch.dict(os.environ, {"GIT_INDEX_FILE": alternate}):
            self.git("read-tree", "HEAD")
            self.stage_archive()
            result = catalog.check(self.root, staged=True)
            self.assertTrue(result["pass"], result["errors"])
            self.assertEqual(result["archive_files"], 1)
            path.write_bytes(b"changed archive")
            self.git("add", "--", path.relative_to(self.root).as_posix())
            self.assertFalse(catalog.check(self.root, staged=True)["pass"])
        result = catalog.check(self.root, staged=True)
        self.assertTrue(result["pass"])
        self.assertEqual(result["archive_files"], 0)

    def test_archive_reads_are_bounded_in_both_views(self):
        self.init()
        _, path = self.make_archive(b"0123456789")
        self.stage_archive()
        name = path.relative_to(self.root).as_posix()
        for staged in (False, True):
            with self.subTest(staged=staged), self.assertRaisesRegex(ValueError, "byte limit"):
                catalog.archive_bytes(catalog.View(self.root, staged), name, 9)


if __name__ == "__main__":
    unittest.main()
