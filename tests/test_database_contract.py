import contextlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("database_contract", REPO / "database/tools/contract.py")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


class DatabaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="comfyui-db-contract-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        shutil.copytree(REPO / "database", self.repo / "database")

    def test_checked_schema_and_fictional_fixtures(self):
        result = contract.check(self.repo)
        self.assertTrue(result["pass"])
        self.assertEqual(sum(item["tables"] for item in result["databases"].values()), 17)

    def test_empty_initializer_leaves_all_tables_empty(self):
        self.assertTrue(contract.initialize("empty-v1", repo=self.repo)["pass"])
        receipt = contract.read_json(self.repo / "local/database-checks/empty-v1/DATABASE_RECEIPT.json")
        self.assertEqual(len(receipt["databases"]), 3)
        self.assertFalse(any(value for item in receipt["databases"].values() for value in item["rows"].values()))

    def test_fixtures_exercise_membership_flags_and_revision_triggers(self):
        contract.initialize("fixture-v1", fixtures=True, repo=self.repo)
        path = self.repo / "local/database-checks/fixture-v1/userdatas_zh_CN_tags.db"
        with contextlib.closing(sqlite3.connect(str(path))) as conn:
            self.assertEqual(conn.execute("SELECT tag_uuid,g_uuid FROM workbench_tag_folder_members").fetchall(),
                             [("fixture-tag-001", "fixture-subgroup-001")])
            self.assertEqual(conn.execute("SELECT commas,words FROM workbench_tag_string_flags").fetchall(), [(1, 2)])
            revision = conn.execute("SELECT value FROM workbench_tag_revision WHERE id=1").fetchone()[0]
            conn.execute("UPDATE tag_tags SET text=? WHERE t_uuid=?", ("blue sky, soft light, clouds", "fixture-tag-001"))
            self.assertGreater(conn.execute("SELECT value FROM workbench_tag_revision WHERE id=1").fetchone()[0], revision)
            self.assertEqual(conn.execute("SELECT commas,words FROM workbench_tag_string_flags").fetchall(), [(2, 3)])
            conn.rollback()

    def test_refuses_existing_target_even_empty(self):
        path = self.repo / "local/database-checks/existing"
        path.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            contract.initialize("existing", repo=self.repo)

    def test_refuses_paths_and_reserved_windows_names(self):
        for name in ("../production", "a/b", "a\\b", "C:production", "C:/production", "", "NUL", "con", "LPT1"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                contract.sandbox(self.repo, name)
        for path in ("../escape", "a/../escape", "/absolute", "C:/absolute", "a\\b", "./a"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                contract.confined(self.repo, path)

    def test_rejects_linked_sandbox(self):
        target = self.repo / "outside"
        target.mkdir()
        try:
            (self.repo / "local").symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Platform does not permit directory symlink creation")
        with self.assertRaises(ValueError):
            contract.initialize("linked", repo=self.repo)
        self.assertEqual(list(target.iterdir()), [])

    def test_schema_drift_fails_before_creation(self):
        schema = self.repo / "database/schema/v1/userdatas_zh_CN_history.sql"
        schema.write_text(schema.read_text(encoding="utf-8") + "\nCREATE TABLE unreviewed(id);\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            contract.initialize("must-not-exist", repo=self.repo)
        self.assertFalse((self.repo / "local/database-checks/must-not-exist").exists())

    def test_read_only_verification_detects_changed_database(self):
        contract.initialize("drift", fixtures=True, repo=self.repo)
        path = self.repo / "local/database-checks/drift/userdatas_zh_CN_history.db"
        with contextlib.closing(sqlite3.connect(str(path))) as conn:
            conn.execute("UPDATE history SET name=?", ("Changed fixture",))
            conn.commit()
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            contract.verify("drift", repo=self.repo)
        self.assertEqual(path.read_bytes(), before)

    def test_declarative_baseline_refuses_attach_and_data_statements(self):
        with contextlib.closing(sqlite3.connect(":memory:")) as conn:
            for sql in ("ATTACH DATABASE 'elsewhere' AS extra;\n", "INSERT INTO t VALUES(1);\n", "CREATE TABLE copied AS SELECT 1;\n"):
                with self.subTest(sql=sql), self.assertRaises(ValueError):
                    contract.execute_ddl(conn, sql)

    def test_statement_framer_handles_trigger_and_multiline_literal(self):
        sql = "CREATE TABLE t(value TEXT);\nCREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET value='semi;colon'; END;\nINSERT INTO t VALUES('line one\nCREATE TABLE not_a_schema;');\n"
        statements = list(contract.statements(sql.splitlines(keepends=True)))
        self.assertEqual(len(statements), 3)
        self.assertTrue(statements[2].startswith("INSERT"))

    def test_verified_sql_extraction_ignores_rows_and_detects_corruption(self):
        sql = "BEGIN TRANSACTION;\nCREATE TABLE t(value TEXT);\nINSERT INTO t VALUES('line one\nCREATE TABLE not_a_schema;');\nCOMMIT;\n".encode()
        directory = self.repo / "example-snapshot/sql"
        directory.mkdir(parents=True)
        payloads = [sql[:62], sql[62:]]
        parts = []
        for index, payload in enumerate(payloads):
            name = f"{index:05}.part"
            (directory / name).write_bytes(payload)
            parts.append({"path": name, "bytes": len(payload), "sha256": contract.digest(payload)})
        entry = {"path": "sql", "parts": parts, "sql_bytes": len(sql), "sql_sha256": contract.digest(sql)}
        ddl = contract.verified_dump_ddl(directory.parent, entry)
        self.assertEqual(ddl, "CREATE TABLE t(value TEXT);\n")
        (directory / parts[0]["path"]).write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            contract.verified_dump_ddl(directory.parent, entry)

    def test_unknown_migration_version_fails_closed(self):
        path = self.repo / "database/migrations/index.json"
        plan = contract.read_json(path)
        plan["current_version"] = 2
        path.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(ValueError):
            contract.load_contract(self.repo)

    def test_external_asset_examples_are_portable_and_not_payloads(self):
        examples = REPO / "examples/external-assets"
        locations = contract.read_json(examples / "locations.json")
        self.assertFalse(locations["payloads_in_git"])
        seen = set()
        for entry in locations["directories"]:
            path = entry["path"]
            self.assertTrue(path.startswith("ComfyUI/"))
            self.assertNotIn(":", path)
            self.assertNotIn("..", Path(path).parts)
            self.assertNotIn(path, seen)
            seen.add(path)
        example = contract.read_json(examples / "asset-record.example.json")
        self.assertTrue(example["example_only"])
        self.assertFalse(list(examples.rglob("*.safetensors")))
        self.assertFalse(list(examples.rglob("*.pt")))
        self.assertFalse(list(examples.rglob("*.gguf")))

    def test_preview_svg_is_small_self_contained_vector(self):
        path = REPO / "examples/external-assets/preview.example.svg"
        self.assertLess(path.stat().st_size, 8192)
        root = ET.parse(path).getroot()
        self.assertEqual(root.attrib["viewBox"], "0 0 640 400")
        for node in root.iter():
            self.assertNotIn(node.tag.rsplit("}", 1)[-1], {"script", "image", "foreignObject"})
            self.assertFalse(any(key.lower().startswith("on") for key in node.attrib))
            self.assertFalse(any("http:" in value or "https:" in value for value in node.attrib.values()))


if __name__ == "__main__":
    unittest.main()
