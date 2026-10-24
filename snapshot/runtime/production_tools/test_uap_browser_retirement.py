"""Offline acceptance for browser-node retirement and canonical UAP export.

Run with Python 3.10+: python -X utf8 -B test_uap_browser_retirement.py
Only temporary copies are passed to write-capable CLIs. Production files,
services, queues and model resources are never modified or accessed.
Assertions report structural identifiers rather than workflow prompt content.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import merge_unified_workflow as merge


TOOLS = Path(__file__).resolve().parent
K2_UUID = "945c8bd5-57ab-4054-ae97-da28ca17ccfc"
RETIRED_UUIDS = {
    "a3693025-6d77-52d1-bc21-0606026e75c3",  # a1 [01C] PixAI
    "66bad938-cc35-53bc-bbc4-add4a1c83c60",  # a29 [01C] PixAI
    "c064915a-364c-5684-bd22-e4ed08730e6d",  # a1 [05]
    "38d947f0-68b4-5d72-a27e-60a91f65c23a",  # a29 [05]
}
RETIRED_TYPE = "DanbooruBrowserImportV05"
FIXTURE_ID = 987654321


def subgraph(data, graph_id=K2_UUID):
    return next(item for item in data["definitions"]["subgraphs"] if item["id"] == graph_id)


def usable_link(graph):
    """First embedded link whose origin is a real node that back-references it."""
    for link in graph["links"]:
        origin = link["origin_id"]
        node = next((item for item in graph["nodes"] if item["id"] == origin), None)
        if node and any(link["id"] in (output.get("links") or []) for output in node.get("outputs", [])):
            return link, node
    raise AssertionError("fixture subgraph has no internally-originated link")


def file_hashes(directory):
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*") if path.is_file()
    }


class BrowserRetirementAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {
            "canonical": merge.read_json(merge.CANONICAL_SOURCE),
            "formal": merge.read_json(merge.OPTIMIZED_OUTPUT),
        }
        cls.temp = tempfile.TemporaryDirectory(prefix="uap-browser-retirement-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.runtime = Path(cls.temp.name) / "runtime"
        cls.tools = cls.runtime / "production_tools"
        cls.templates = cls.tools / "templates"
        cls.workflows = cls.runtime / "ComfyUI/user/default/workflows"
        cls.templates.mkdir(parents=True)
        cls.workflows.mkdir(parents=True)
        for name in ("merge_unified_workflow.py", "layout_uap_workbench.py"):
            shutil.copyfile(TOOLS / name, cls.tools / name)
        cls.canonical = cls.templates / merge.CANONICAL_SOURCE.name
        cls.formal = cls.workflows / merge.OPTIMIZED_OUTPUT.name
        shutil.copyfile(merge.CANONICAL_SOURCE, cls.canonical)
        shutil.copyfile(merge.OPTIMIZED_OUTPUT, cls.formal)

    def candidate(self):
        return copy.deepcopy(self.sources["canonical"])

    def strict_errors(self, data):
        return merge.validate(data, forbid_browser_receiver=True)

    def assert_rejected(self, data, diagnostic):
        errors = self.strict_errors(data)
        self.assertTrue(any(diagnostic in item for item in errors),
                        "Strict validation did not reject the structural mutation: " + diagnostic)

    def run_cli(self, name, *args):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(self.tools / name), *map(str, args)],
            cwd=self.runtime, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=False,
        )

    def test_01_formal_and_canonical_pass_strict_validation(self):
        for source_name, data in self.sources.items():
            with self.subTest(source=source_name):
                self.assertEqual(self.strict_errors(data), [])
                graphs = [data, *data["definitions"]["subgraphs"]]
                self.assertTrue(all(item.get("type") != RETIRED_TYPE
                                    for graph in graphs for item in graph["nodes"]),
                                "A retired browser receiver remains in the current workflow")
                node_ids = {item["id"] for item in data["nodes"]}
                self.assertTrue({1148, 1180}.isdisjoint(node_ids),
                                "A retired receiver or its dedicated top-level preview remains")
                self.assertNotIn(10198, {item[0] for item in data["links"]})
                definitions = {item["id"] for item in data["definitions"]["subgraphs"]}
                self.assertEqual(definitions, {K2_UUID}, "only the Krea2 embedded subgraph remains")
                self.assertTrue(definitions.isdisjoint(RETIRED_UUIDS))
                retired_nodes = {1022, 1066, 1074, 1090, 1275}
                self.assertTrue(retired_nodes.isdisjoint(node_ids),
                                "A retired Anima branch node remains in the current workflow")
                branches = {branch.get("id") for branch in data["extra"]["uap_workbench"]["branches"]}
                self.assertEqual(branches, {"k2", "ext04", "ext06", "ext08", "ext09"})
                self.assertEqual(data["extra"]["uap_workbench"]["activeBranch"], "k2")

    def test_02_json_roundtrip_preserves_full_payload(self):
        for source_name, data in self.sources.items():
            with self.subTest(source=source_name):
                restored = json.loads(json.dumps(data, ensure_ascii=False))
                self.assertTrue(restored == data, "Full workflow payload changed during JSON roundtrip")
                self.assertEqual(self.strict_errors(restored), [])

    def test_03_embedded_missing_endpoint_is_rejected(self):
        data = self.candidate()
        subgraph(data)["links"][0]["target_id"] = FIXTURE_ID
        self.assert_rejected(data, "points to missing node")

    def test_04_embedded_missing_output_backlink_is_rejected(self):
        data = self.candidate()
        link, origin = usable_link(subgraph(data))
        output = next(item for item in origin["outputs"] if link["id"] in (item.get("links") or []))
        output["links"].remove(link["id"])
        self.assert_rejected(data, "is absent from its endpoint ports")

    def test_05_missing_virtual_port_backlinks_are_rejected(self):
        for direction in ("inputs", "outputs"):
            with self.subTest(direction=direction):
                data = self.candidate()
                subgraph(data)[direction][0]["linkIds"] = []
                self.assert_rejected(data, "is absent from its endpoint ports")

    def test_06_top_level_receiver_rejected_with_legacy_opt_out(self):
        data = self.candidate()
        data["nodes"].append({"id": FIXTURE_ID, "type": RETIRED_TYPE, "inputs": [], "outputs": []})
        self.assert_rejected(data, "uses retired browser receiver")
        self.assertEqual(merge.validate(data, forbid_browser_receiver=False), [])

    def test_07_embedded_receiver_rejected_with_legacy_opt_out(self):
        data = self.candidate()
        subgraph(data)["nodes"].append({"id": FIXTURE_ID, "type": RETIRED_TYPE, "inputs": [], "outputs": []})
        self.assert_rejected(data, "uses retired browser receiver")
        self.assertEqual(merge.validate(data, forbid_browser_receiver=False), [])

    def test_08_obsolete_branch_saved_mode_is_rejected(self):
        data = self.candidate()
        data["extra"]["uap_workbench"]["branches"][0]["modes"][str(FIXTURE_ID)] = 0
        self.assert_rejected(data, "has obsolete saved mode")

    def test_09_obsolete_branch_node_id_is_rejected(self):
        for missing_id in (FIXTURE_ID, str(FIXTURE_ID)):
            with self.subTest(node_id=missing_id):
                data = self.candidate()
                data["extra"]["uap_workbench"]["branches"][0]["nodeIds"].append(missing_id)
                self.assert_rejected(data, "refers to missing node")

    def test_09b_mixed_string_and_integer_branch_ids_are_valid(self):
        for source_name, source in self.sources.items():
            with self.subTest(source=source_name):
                data = copy.deepcopy(source)
                branch = data["extra"]["uap_workbench"]["branches"][0]
                branch["nodeIds"] = [str(node_id) if index % 2 else int(node_id)
                                     for index, node_id in enumerate(branch["nodeIds"])]
                self.assertEqual(self.strict_errors(data), [])

    def test_10_obsolete_stage_group_is_rejected(self):
        data = self.candidate()
        data["extra"]["uap_workbench"]["branches"][0]["stages"][0]["groups"].append("__retired_browser_fixture__")
        self.assert_rejected(data, "refers to missing group")

    def test_13_canonical_cli_export_is_exact_and_strict_wiring_is_read_only(self):
        candidate = Path(self.temp.name) / "candidates/current.json"
        result = self.run_cli("merge_unified_workflow.py", "--output", candidate)
        self.assertEqual(result.returncode, 0, "Canonical candidate CLI export failed")
        self.assertTrue(candidate.read_bytes() == self.canonical.read_bytes(),
                        "Exported candidate bytes differ from the canonical template")
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["validation"], "passed")
        self.assertFalse(receipt["read_only"])
        before = file_hashes(self.runtime)
        result = self.run_cli("merge_unified_workflow.py", "--validate")
        self.assertEqual(result.returncode, 0, "Read-only formal workflow validation failed")
        self.assertTrue(json.loads(result.stdout)["read_only"])
        self.assertEqual(file_hashes(self.runtime), before)
        rejected_candidate = Path(self.temp.name) / "candidates/rejected.json"
        cases = [
            (self.formal, ("--validate",)),
            (self.canonical, ("--output", rejected_candidate)),
        ]
        for fixture, args in cases:
            with self.subTest(strict_cli=args[0]):
                original = fixture.read_bytes()
                try:
                    mutated = json.loads(original)
                    mutated["nodes"].append({"id": FIXTURE_ID, "type": RETIRED_TYPE, "inputs": [], "outputs": []})
                    fixture.write_text(json.dumps(mutated, ensure_ascii=False), encoding="utf-8")
                    before = file_hashes(self.runtime)
                    result = self.run_cli("merge_unified_workflow.py", *args)
                    self.assertNotEqual(result.returncode, 0, "CLI strict receiver ban was not wired")
                    self.assertIn("uses retired browser receiver", result.stderr)
                    self.assertEqual(file_hashes(self.runtime), before)
                    self.assertFalse(rejected_candidate.exists(), "Rejected workflow was written as a candidate")
                finally:
                    fixture.write_bytes(original)

    def test_14_cli_rejects_existing_and_protected_outputs(self):
        existing = Path(self.temp.name) / "existing.json"
        existing.write_bytes(b"existing candidate must survive\n")
        cases = [
            (existing, "Candidate already exists", ()),
            (self.workflows / "new.json", "Refusing production/template output", ()),
            (self.templates / "new.json", "Refusing production/template output", ()),
            (self.workflows / ".." / "workflows" / "via-parent.json", "Refusing production/template output", ()),
            (self.formal, "Refusing production/template output", ("--legacy-sources",)),
            (self.canonical, "Refusing production/template output", ("--legacy-sources",)),
        ]
        for output, diagnostic, flags in cases:
            with self.subTest(target=output.name, flags=flags):
                before = file_hashes(self.runtime)
                result = self.run_cli("merge_unified_workflow.py", "--output", output, *flags)
                self.assertNotEqual(result.returncode, 0, "A protected export was accepted")
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual(file_hashes(self.runtime), before)
                self.assertTrue(existing.read_bytes() == b"existing candidate must survive\n",
                                "Existing candidate was modified")
        before = file_hashes(self.runtime)
        result = self.run_cli("merge_unified_workflow.py")
        self.assertNotEqual(result.returncode, 0, "Implicit historical rebuild was accepted")
        self.assertEqual(file_hashes(self.runtime), before)

    def test_15_historical_layout_cli_is_retired_without_writes(self):
        before = file_hashes(self.runtime)
        result = self.run_cli("layout_uap_workbench.py")
        self.assertNotEqual(result.returncode, 0, "Historical layout CLI was still active")
        self.assertIn("Historical layout rebuild is retired", result.stderr)
        self.assertEqual(file_hashes(self.runtime), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
