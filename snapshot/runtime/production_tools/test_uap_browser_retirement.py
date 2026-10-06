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
INPUT_UUID = "337bd605-fc7a-4bc5-a609-dac988131dee"
OUTPUT_UUID = "ff03cc8b-4bec-4d36-aab2-e85581ba4ef3"
A1_UUID = "a3693025-6d77-52d1-bc21-0606026e75c3"
A29_UUID = "66bad938-cc35-53bc-bbc4-add4a1c83c60"
RETIRED_TYPE = "DanbooruBrowserImportV05"
FIXTURE_ID = 987654321


def subgraph(data, graph_id=A1_UUID):
    return next(item for item in data["definitions"]["subgraphs"] if item["id"] == graph_id)


def node(graph, node_id):
    return next(item for item in graph["nodes"] if item["id"] == node_id)


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

    def assert_pixai_interface(self, graph_id, tagger_id, wrapper_id, preview_id,
                               input_link_id, export_link_id, external_link_id):
        for source_name, data in self.sources.items():
            with self.subTest(source=source_name):
                graph = subgraph(data, graph_id)
                self.assertEqual(graph["inputs"][0]["id"], INPUT_UUID)
                self.assertEqual(graph["inputs"][0]["type"], "IMAGE")
                self.assertEqual(graph["inputs"][0]["linkIds"], [input_link_id])
                self.assertEqual(graph["outputs"][0]["id"], OUTPUT_UUID)
                self.assertEqual(graph["outputs"][0]["name"], "merged_tags")
                self.assertEqual(graph["outputs"][0]["type"], "STRING")
                self.assertEqual(graph["outputs"][0]["linkIds"], [export_link_id])
                self.assertEqual(node(graph, tagger_id)["type"], "PixAITagger")
                self.assertEqual(node(graph, tagger_id)["inputs"][0]["name"], "image")
                self.assertEqual(node(graph, tagger_id)["inputs"][0]["link"], input_link_id)
                self.assertEqual(graph["inputNode"]["id"], -10)
                self.assertEqual(graph["outputNode"]["id"], -20)
                incoming = next(item for item in graph["links"] if item["id"] == input_link_id)
                self.assertEqual(
                    tuple(incoming[key] for key in ("origin_id", "origin_slot", "target_id", "target_slot", "type")),
                    (-10, 0, tagger_id, 0, "IMAGE"),
                )
                exported = next(item for item in graph["links"] if item["id"] == export_link_id)
                self.assertEqual(
                    tuple(exported[key] for key in ("origin_id", "origin_slot", "target_id", "target_slot", "type")),
                    (tagger_id, 0, -20, 0, "STRING"),
                )
                wrapper = node(data, wrapper_id)
                self.assertEqual(wrapper["type"], graph_id)
                self.assertEqual(wrapper["outputs"][0]["name"], "merged_tags")
                self.assertEqual(wrapper["outputs"][0]["type"], "STRING")
                self.assertEqual(wrapper["outputs"][0]["links"], [external_link_id])
                outgoing = [item for item in data["links"] if item[1] == wrapper_id]
                self.assertEqual([tuple(item[:6]) for item in outgoing],
                                 [(external_link_id, wrapper_id, 0, preview_id, 0, "STRING")])
                preview = node(data, preview_id)
                self.assertEqual(preview["type"], "ShowText|pysssss")
                self.assertEqual(preview["inputs"][0]["link"], external_link_id)
                self.assertTrue(all(not output.get("links") for output in preview["outputs"]),
                                "Tag preview must not feed a generation node")

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
                self.assertNotIn(1074, {item["id"] for item in data["groups"]})
                self.assertIn(1074, node_ids, "The legitimate A29 node sharing the retired group ID was removed")
                for graph_id, retired_ids in ((A1_UUID, {104000, 104001}), (A29_UUID, {114000, 114001})):
                    self.assertTrue(retired_ids.isdisjoint({item["id"] for item in subgraph(data, graph_id)["nodes"]}),
                                    "An embedded receiver or its dedicated preview remains")

    def test_02_json_roundtrip_preserves_full_payload(self):
        for source_name, data in self.sources.items():
            with self.subTest(source=source_name):
                restored = json.loads(json.dumps(data, ensure_ascii=False))
                self.assertTrue(restored == data, "Full workflow payload changed during JSON roundtrip")
                self.assertEqual(self.strict_errors(restored), [])

    def test_03_a1_pixai_uuid_and_preview_only_export(self):
        self.assert_pixai_interface(A1_UUID, 104003, 1003, 1028, 308003, 308004, 10012)

    def test_04_a29_pixai_uuid_and_preview_only_export(self):
        self.assert_pixai_interface(A29_UUID, 114003, 1066, 1098, 328003, 328004, 10104)

    def test_05_top_level_receiver_rejected_with_legacy_opt_out(self):
        data = self.candidate()
        data["nodes"].append({"id": FIXTURE_ID, "type": RETIRED_TYPE, "inputs": [], "outputs": []})
        self.assert_rejected(data, "uses retired browser receiver")
        self.assertEqual(merge.validate(data, forbid_browser_receiver=False), [])

    def test_06_embedded_receiver_rejected_with_legacy_opt_out(self):
        data = self.candidate()
        subgraph(data)["nodes"].append({"id": FIXTURE_ID, "type": RETIRED_TYPE, "inputs": [], "outputs": []})
        self.assert_rejected(data, "uses retired browser receiver")
        self.assertEqual(merge.validate(data, forbid_browser_receiver=False), [])

    def test_07_embedded_missing_endpoint_is_rejected(self):
        data = self.candidate()
        subgraph(data)["links"][0]["target_id"] = FIXTURE_ID
        self.assert_rejected(data, "points to missing node")

    def test_08_embedded_missing_output_backlink_is_rejected(self):
        data = self.candidate()
        node(subgraph(data), 104003)["outputs"][0]["links"].remove(308004)
        self.assert_rejected(data, "is absent from its endpoint ports")

    def test_09_missing_virtual_port_backlinks_are_rejected(self):
        for direction in ("inputs", "outputs"):
            with self.subTest(direction=direction):
                data = self.candidate()
                subgraph(data)[direction][0]["linkIds"] = []
                self.assert_rejected(data, "is absent from its endpoint ports")

    def test_10_obsolete_branch_saved_mode_is_rejected(self):
        data = self.candidate()
        data["extra"]["uap_workbench"]["branches"][0]["modes"][str(FIXTURE_ID)] = 0
        self.assert_rejected(data, "has obsolete saved mode")

    def test_11_obsolete_branch_node_id_is_rejected(self):
        data = self.candidate()
        data["extra"]["uap_workbench"]["branches"][0]["nodeIds"].append(FIXTURE_ID)
        self.assert_rejected(data, "refers to missing node")

    def test_12_obsolete_stage_group_is_rejected(self):
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
