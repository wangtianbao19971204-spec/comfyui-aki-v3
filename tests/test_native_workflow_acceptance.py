"""Native export acceptance guards, using synthetic paths/service and no GPU."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_workflow_acceptance as acceptance


EMPTY = {"queue_running": [], "queue_pending": []}
PREFIX = "_codex_qa/final_acceptance_20261007/"
INFO = {
    "FixtureLocalImage": {"input": {"required": {"width": ["INT"]}, "optional": {"cfg": ["FLOAT"], "enabled": ["BOOLEAN"]}}, "output": ["IMAGE"]},
    "SaveImage": {"output_node": True, "input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING"]}}},
    "PreviewImage": {"output_node": True, "input": {"required": {"images": ["IMAGE"]}}},
    "LoadImage": {"input": {"required": {"image": [["root.png"]]}}, "output": ["IMAGE"]},
    "UNETLoader": {"input": {"required": {"unet_name": [["current.safetensors"]]}}},
    "ExternalAPI": {"api_node": True, "input": {}},
    "LocalCaption": {"input": {}},
    "WriteUserDatabase": {"output_node": True, "input": {}},
    "DazzleSwitch": {"input": {"required": {"select": [["(none connected)"]], "mode": [["priority", "strict", "sequential"]]},
                                  "optional": {"input_01": ["*"], "input_02": ["*"]}}, "output": ["*", "INT"]},
    "VRAMCleanup": {"output_node": True, "input": {"required": {"offload_model": ["BOOLEAN"], "offload_cache": ["BOOLEAN"]},
                                                      "optional": {"anything": ["*"]}}, "output": ["*"]},
    "WeiLinPromptUI": {"output_node": True, "input": {"required": {"positive": ["STRING"], "auto_random": ["BOOLEAN"]},
                        "optional": {field: ["STRING"] for field in ("lora_str", "temp_str", "temp_lora_str", "random_template")}}, "output": ["STRING"]},
    "AnimaLLLiteApply_sdscripts": {"input": {"required": {"lllite_name": [["current.safetensors", "local.pt"]]}}, "output": ["MODEL"]},
}


def graph():
    return {"1": {"class_type": "FixtureLocalImage", "inputs": {"width": 16}, "_meta": {"title": "Original title"}},
            "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": PREFIX + "stage"}},
            "4": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": PREFIX + "final"}},
            "99": {"class_type": "ExternalAPI", "inputs": {"url": "https://example.invalid"}}}


class FakeClient:
    def __init__(self, runtime, *, foreign_before=False, foreign_during=False, failure=False, linger=False):
        self.runtime = runtime
        self.foreign_before = foreign_before
        self.foreign_during = foreign_during
        self.failure = failure
        self.linger = linger
        self.calls = []
        self.posted = None
        self.queue_after_post = 0

    def request(self, path, payload=None):
        self.calls.append((path, copy.deepcopy(payload)))
        if path == "/object_info":
            return copy.deepcopy(INFO)
        if path == "/queue":
            if self.posted is None:
                return {"queue_running": [[0, "user-job"]], "queue_pending": []} if self.foreign_before else copy.deepcopy(EMPTY)
            self.queue_after_post += 1
            own = [[0, self.posted["prompt_id"]]] if self.queue_after_post == 1 or self.linger and self.queue_after_post == 2 else []
            return {"queue_running": own, "queue_pending": [[1, "user-job"]] if self.foreign_during else []}
        if path == "/prompt":
            self.posted = copy.deepcopy(payload)
            return {"prompt_id": payload["prompt_id"], "node_errors": {}}
        if path.startswith("/history/"):
            if self.failure:
                history = {"outputs": {}, "status": {"completed": False, "status_str": "error", "messages": [["execution_error", {"exception_type": "FixtureFailure"}]]}}
            else:
                from PIL import Image
                folder = self.runtime / "ComfyUI/output" / PREFIX
                folder.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (16, 8), (20, 40, 60, 0)).save(folder / "fixture.png")
                history = {"prompt": [0, self.posted["prompt_id"], self.posted["prompt"]],
                           "outputs": {target: {"images": [{"type": "output", "subfolder": PREFIX.rstrip("/"), "filename": "fixture.png"}]} for target in self.posted["partial_execution_targets"]},
                           "status": {"completed": True, "status_str": "success", "messages": []}}
            return {self.posted["prompt_id"]: history}
        raise AssertionError(path)


class NativeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-workflow-acceptance-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.runtime = self.base / "runtime"
        (self.runtime / "ComfyUI/input/_codex_qa").mkdir(parents=True)
        (self.runtime / "python").mkdir()
        self.export = self.base / "export.json"
        self.export.write_text(json.dumps(graph(), ensure_ascii=False, indent=3), encoding="utf8")
        self.original = self.export.read_bytes()
        self.identity = {"pid": 456, "create_time": 1.25, "executable": str(self.runtime / "python/python.exe"),
                         "cwd": str(self.runtime / "ComfyUI"), "listener_pids": [456]}

    def run_case(self, *, client=None, execute=False, identity_reader=None, **kwargs):
        return acceptance.run_acceptance(runtime=self.runtime, evidence=self.base / "evidence", export=self.export,
                  expected_pid=456, expected_create_time=1.25, targets=["3", "4"], case="fixture", execute=execute,
                  client=client or FakeClient(self.runtime), identity_reader=identity_reader or (lambda *args: copy.deepcopy(self.identity)),
                  sleeper=lambda seconds: None, **kwargs)

    def test_target_projection_preserves_original_nodes_and_ignores_unreachable_api(self):
        original = graph()
        result = acceptance.dependency_closure(original, ["3", "4"])
        self.assertEqual(list(result), ["1", "3", "4"])
        self.assertIs(result["1"], original["1"])
        self.assertEqual(original, graph())
        self.assertTrue(acceptance.validate_graph(result, ["3", "4"], INFO, self.runtime, PREFIX)["local_only"])

    def test_repeated_or_comma_targets_are_supported_without_duplicates(self):
        self.assertEqual(acceptance.targets_from_arguments(["3,4", "5"]), ["3", "4", "5"])
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.targets_from_arguments(["3", "3"])

    def test_missing_dependencies_are_refused(self):
        candidate = graph()
        candidate["3"]["inputs"]["images"] = ["missing", 0]
        with self.assertRaisesRegex(acceptance.AcceptanceError, "missing"):
            acceptance.dependency_closure(candidate, ["3"])

    def test_dependency_cycles_are_refused(self):
        candidate = graph()
        candidate["1"]["inputs"]["other"] = ["3", 0]
        with self.assertRaisesRegex(acceptance.AcceptanceError, "cycle"):
            acceptance.dependency_closure(candidate, ["3"])

    def test_reachable_caption_and_api_nodes_are_refused(self):
        for kind in ("ExternalAPI", "LocalCaption"):
            with self.subTest(kind=kind):
                candidate = acceptance.dependency_closure(graph(), ["3"])
                candidate["1"] = {"class_type": kind, "inputs": {}}
                with self.assertRaisesRegex(acceptance.AcceptanceError, "forbidden"):
                    acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_url_or_credential_input_is_refused_even_on_local_class(self):
        for fields in ({"reference": "https://example.invalid/image.png"}, {"api_key": "synthetic-only"}):
            with self.subTest(fields=list(fields)):
                candidate = acceptance.dependency_closure(graph(), ["3"])
                candidate["1"]["inputs"].update(fields)
                with self.assertRaisesRegex(acceptance.AcceptanceError, "forbidden"):
                    acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_exact_reviewed_sdscripts_lllite_class_with_current_safetensors_is_valid(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["1"] = {"class_type": "AnimaLLLiteApply_sdscripts", "inputs": {"lllite_name": "current.safetensors"}}
        self.assertTrue(acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)["local_only"])

    def test_sdscripts_lllite_exception_does_not_allow_similar_script_classes(self):
        for kind in ("AnimaLLLiteApply_sdscripts_extra", "RunScript", "sdscripts"):
            candidate = acceptance.dependency_closure(graph(), ["3"])
            candidate["1"] = {"class_type": kind, "inputs": {}}
            local_info = {**INFO, kind: {"input": {}}}
            with self.assertRaisesRegex(acceptance.AcceptanceError, "forbidden"):
                acceptance.validate_graph(candidate, ["3"], local_info, self.runtime, PREFIX)

    def test_sdscripts_lllite_exception_keeps_registered_model_enum_strict(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["1"] = {"class_type": "AnimaLLLiteApply_sdscripts", "inputs": {"lllite_name": "stale.safetensors"}}
        with self.assertRaisesRegex(acceptance.AcceptanceError, "enum"):
            acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_sdscripts_lllite_exception_refuses_nonsafetensors_link_or_api_schema(self):
        for value in ("local.pt", ["3", 0], None):
            candidate = acceptance.dependency_closure(graph(), ["3"])
            candidate["1"] = {"class_type": "AnimaLLLiteApply_sdscripts", "inputs": {"lllite_name": value}}
            with self.assertRaisesRegex(acceptance.AcceptanceError, "literal safetensors"):
                acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)
        candidate["1"]["inputs"]["lllite_name"] = "current.safetensors"
        local_info = copy.deepcopy(INFO)
        local_info["AnimaLLLiteApply_sdscripts"]["api_node"] = True
        with self.assertRaisesRegex(acceptance.AcceptanceError, "API backend"):
            acceptance.validate_graph(candidate, ["3"], local_info, self.runtime, PREFIX)

    def test_output_prefix_escape_and_device_paths_are_refused(self):
        for value in ("production/final", PREFIX + "../escape", "C:/outside", "_codex_qa/final_acceptance_20261007/NUL"):
            with self.subTest(value=value):
                candidate = acceptance.dependency_closure(graph(), ["3"])
                candidate["3"]["inputs"]["filename_prefix"] = value
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_non_image_output_nodes_are_refused(self):
        candidate = {"3": {"class_type": "WriteUserDatabase", "inputs": {}}}
        with self.assertRaisesRegex(acceptance.AcceptanceError, "Only"):
            acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_preview_output_is_refused_to_keep_targets_inside_qa_output(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["3"] = {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}}
        with self.assertRaisesRegex(acceptance.AcceptanceError, "Only SaveImage"):
            acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_existing_qa_input_subdirectory_is_valid_despite_root_combo(self):
        (self.runtime / "ComfyUI/input/_codex_qa/input.png").write_bytes(b"fixture")
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["1"] = {"class_type": "LoadImage", "inputs": {"image": "_codex_qa/input.png"}}
        self.assertTrue(acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)["local_only"])

    def test_stale_model_enum_is_refused(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "old.safetensors"}}
        with self.assertRaisesRegex(acceptance.AcceptanceError, "enum"):
            acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_dazzle_switch_only_documented_sentinels_or_connected_slot_are_valid(self):
        for selected in ("(none)", "(none connected)", "input_02"):
            with self.subTest(selected=selected):
                candidate = acceptance.dependency_closure(graph(), ["3"])
                candidate["2"] = {"class_type": "DazzleSwitch", "inputs": {"select": selected, "mode": "priority", "input_02": ["1", 0]}}
                candidate["3"]["inputs"]["images"] = ["2", 0]
                self.assertTrue(acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)["local_only"])

    def test_dazzle_switch_disconnected_or_malformed_selection_is_refused(self):
        for selected in ("arbitrary", "input_1", "input_001", "input_03", "input_02"):
            with self.subTest(selected=selected):
                candidate = acceptance.dependency_closure(graph(), ["3"])
                candidate["2"] = {"class_type": "DazzleSwitch", "inputs": {"select": selected, "mode": "priority", "input_02": None}}
                candidate["3"]["inputs"]["images"] = ["2", 0]
                with self.assertRaisesRegex(acceptance.AcceptanceError, "connected input_NN"):
                    acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_dazzle_switch_dynamic_select_does_not_bypass_mode_enum(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["2"] = {"class_type": "DazzleSwitch", "inputs": {"select": "input_02", "mode": "unknown-mode", "input_02": ["1", 0]}}
        candidate["3"]["inputs"]["images"] = ["2", 0]
        with self.assertRaisesRegex(acceptance.AcceptanceError, "DazzleSwitch.mode"):
            acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_inactive_vram_cleanup_passthrough_dependency_is_valid(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["2"] = {"class_type": "VRAMCleanup", "inputs": {"offload_model": False, "offload_cache": False, "anything": ["1", 0]}}
        candidate["3"]["inputs"]["images"] = ["2", 0]
        self.assertTrue(acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)["local_only"])

    def test_vram_cleanup_true_link_numeric_or_missing_flags_are_refused(self):
        for flags in ({"offload_model": True, "offload_cache": False},
                      {"offload_model": False, "offload_cache": True},
                      {"offload_model": ["1", 0], "offload_cache": False},
                      {"offload_model": 0, "offload_cache": False},
                      {"offload_model": False}):
            with self.subTest(flags=flags):
                candidate = acceptance.dependency_closure(graph(), ["3"])
                candidate["2"] = {"class_type": "VRAMCleanup", "inputs": {**flags, "anything": ["1", 0]}}
                candidate["3"]["inputs"]["images"] = ["2", 0]
                with self.assertRaisesRegex(acceptance.AcceptanceError, "literal false"):
                    acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_inactive_vram_cleanup_cannot_be_target(self):
        candidate = {"2": {"class_type": "VRAMCleanup", "inputs": {"offload_model": False, "offload_cache": False}}}
        with self.assertRaisesRegex(acceptance.AcceptanceError, "Target must"):
            acceptance.validate_graph(candidate, ["2"], INFO, self.runtime, PREFIX)

    def weilin_candidate(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["2"] = {"class_type": "WeiLinPromptUI", "inputs": {"positive": "plain neutral portrait", "auto_random": False,
            "lora_str": "", "temp_str": "", "temp_lora_str": "", "random_template": ""}}
        candidate["1"]["inputs"]["text"] = ["2", 0]
        return candidate

    def test_inactive_weilin_plain_literal_text_dependency_is_valid(self):
        for opt_text in (None, "", "plain neutral prefix"):
            with self.subTest(opt_text=opt_text):
                candidate = self.weilin_candidate()
                if opt_text is not None:
                    candidate["2"]["inputs"]["opt_text"] = opt_text
                self.assertTrue(acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)["local_only"])

    def test_weilin_random_lora_flags_and_missing_empty_fields_are_refused(self):
        cases = [{"auto_random": value} for value in (True, 0, ["1", 0])]
        cases += [{field: "nonempty"} for field in ("lora_str", "temp_str", "temp_lora_str", "random_template")]
        cases += [{field: None} for field in ("auto_random", "lora_str", "temp_str", "temp_lora_str", "random_template")]
        for fields in cases:
            with self.subTest(fields=fields):
                candidate = self.weilin_candidate()
                for field, value in fields.items():
                    if value is None:
                        del candidate["2"]["inputs"][field]
                    else:
                        candidate["2"]["inputs"][field] = value
                with self.assertRaisesRegex(acceptance.AcceptanceError, "no-LoRA/no-random"):
                    acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_weilin_json_wlr_or_linked_text_is_refused(self):
        for field in ("positive", "opt_text"):
            for value in ('{"prompt":"neutral","lora":[]}', "<wlr:fixture:1:1>", ["1", 0], 7):
                with self.subTest(field=field, value=value):
                    candidate = self.weilin_candidate()
                    candidate["2"]["inputs"][field] = value
                    with self.assertRaisesRegex(acceptance.AcceptanceError, "no-LoRA/no-random"):
                        acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_weilin_clip_or_model_dependencies_are_outside_literal_text_contract(self):
        for field in ("opt_clip", "opt_model"):
            candidate = self.weilin_candidate()
            candidate["2"]["inputs"][field] = ["1", 0]
            with self.assertRaisesRegex(acceptance.AcceptanceError, "no-LoRA/no-random"):
                acceptance.validate_graph(candidate, ["3"], INFO, self.runtime, PREFIX)

    def test_inactive_weilin_cannot_be_target(self):
        candidate = self.weilin_candidate()
        with self.assertRaisesRegex(acceptance.AcceptanceError, "Target must"):
            acceptance.validate_graph(candidate, ["2"], INFO, self.runtime, PREFIX)

    def test_backend_reference_only_coerces_declared_literals_and_preserves_submission(self):
        candidate = acceptance.dependency_closure(graph(), ["3"])
        candidate["1"]["inputs"].update(width=16.0, cfg={"__value__": 7}, enabled=False, unknown=7,
                                        unknown_wrapper={"__value__": 2})
        original = copy.deepcopy(candidate)
        expected, changes = acceptance.backend_validation_reference(candidate, INFO, ["3"])
        self.assertEqual(candidate, original)
        self.assertIs(type(expected["1"]["inputs"]["width"]), int)
        self.assertIs(type(expected["1"]["inputs"]["cfg"]), float)
        self.assertIs(expected["1"]["inputs"]["enabled"], False)
        self.assertEqual(expected["1"]["inputs"]["unknown_wrapper"], {"__value__": 2})
        self.assertEqual(expected["3"]["inputs"]["images"], ["1", 0])
        self.assertEqual({row["field"] for row in changes}, {"width", "cfg"})

    def test_backend_reference_rejects_failed_or_nonfinite_literal_conversion(self):
        for fields in ({"width": "invalid"}, {"cfg": float("inf")}):
            candidate = acceptance.dependency_closure(graph(), ["3"])
            candidate["1"]["inputs"].update(fields)
            with self.assertRaises(acceptance.AcceptanceError):
                acceptance.backend_validation_reference(candidate, INFO, ["3"])

    def dynamic_validation_candidate(self):
        # Serializing a FlexibleOptionalInputType with no actual keys yields
        # optional={}; execution accepts dynamic, while validation ignores it.
        local_info = copy.deepcopy(INFO)
        local_info["FixtureFlexibleInputs"] = {"input": {"required": {}, "optional": {}}, "output": ["IMAGE"]}
        local_info["FixtureWrappedData"] = {"input": {"required": {"data": ["LORAS"]}}, "output": ["*"]}
        candidate = {"1": {"class_type": "FixtureFlexibleInputs", "inputs": {"dynamic": ["2", 0]}},
                     "2": {"class_type": "FixtureWrappedData", "inputs": {"data": {"__value__": []}}},
                     "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": PREFIX + "stage"}}}
        return candidate, local_info

    def test_dynamic_optional_edge_does_not_enter_declared_validation_walk(self):
        candidate, local_info = self.dynamic_validation_candidate()
        self.assertEqual(set(acceptance.dependency_closure(candidate, ["3"])), {"1", "2", "3"})
        self.assertEqual(acceptance.backend_validation_walk(candidate, ["3"], local_info), ["1", "3"])

    def test_wrapped_input_outside_validation_walk_keeps_raw_submitted_dict(self):
        candidate, local_info = self.dynamic_validation_candidate()
        expected, changes = acceptance.backend_validation_reference(candidate, local_info, ["3"])
        self.assertEqual(acceptance.typed_json(expected), acceptance.typed_json(candidate))
        self.assertIs(type(expected["2"]["inputs"]["data"]), dict)
        self.assertEqual(changes, [])

    def test_wrapped_input_on_declared_dependency_is_unwrapped(self):
        candidate, local_info = self.dynamic_validation_candidate()
        local_info["FixtureFlexibleInputs"]["input"]["optional"]["dynamic"] = ["*"]
        expected, changes = acceptance.backend_validation_reference(candidate, local_info, ["3"])
        self.assertEqual(acceptance.backend_validation_walk(candidate, ["3"], local_info), ["1", "2", "3"])
        self.assertEqual(expected["2"]["inputs"]["data"], [])
        self.assertIs(type(candidate["2"]["inputs"]["data"]), dict)
        self.assertEqual([(row["node_id"], row["field"]) for row in changes], [("2", "data")])

    def test_history_of_dynamic_unvalidated_input_must_keep_its_original_type(self):
        candidate, local_info = self.dynamic_validation_candidate()
        expected, _ = acceptance.backend_validation_reference(candidate, local_info, ["3"])
        rewritten = copy.deepcopy(candidate)
        rewritten["2"]["inputs"]["data"] = []
        self.assertNotEqual(acceptance.typed_json(expected), acceptance.typed_json(rewritten))

    def test_duplicate_export_json_keys_are_refused(self):
        self.export.write_text('{"1":{},"1":{}}', encoding="utf8")
        with self.assertRaisesRegex(acceptance.AcceptanceError, "Duplicate"):
            acceptance.load_export(self.export)

    def test_default_preflight_does_not_submit_and_copies_raw_export(self):
        client = FakeClient(self.runtime)
        result = self.run_case(client=client)
        self.assertTrue(result["pass"])
        self.assertFalse(result["submitted"])
        self.assertFalse(any(path == "/prompt" for path, payload in client.calls))
        self.assertEqual((self.base / "evidence/native-export.json").read_bytes(), self.original)
        self.assertEqual(self.export.read_bytes(), self.original)

    def test_nonempty_initial_queue_is_refused_without_post_or_evidence(self):
        client = FakeClient(self.runtime, foreign_before=True)
        with self.assertRaisesRegex(acceptance.AcceptanceError, "foreign"):
            self.run_case(client=client, execute=True)
        self.assertFalse(any(path == "/prompt" for path, payload in client.calls))
        self.assertFalse((self.base / "evidence").exists())

    def test_execute_submits_once_preserves_nodes_history_and_rgba_metrics(self):
        client = FakeClient(self.runtime)
        result = self.run_case(client=client, execute=True)
        self.assertTrue(result["pass"], result)
        self.assertEqual(sum(path == "/prompt" for path, payload in client.calls), 1)
        self.assertEqual(client.posted["prompt"], acceptance.dependency_closure(graph(), ["3", "4"]))
        self.assertEqual(client.posted["partial_execution_targets"], ["3", "4"])
        self.assertEqual(result["image_count"], 2)
        self.assertEqual(result["image_metrics"][0]["alpha_range"], [0, 0])
        self.assertTrue((self.base / "evidence/history.json").is_file())
        self.assertEqual(self.export.read_bytes(), self.original)
        self.assertTrue(all(path in ("/queue", "/object_info", "/prompt") or path.startswith("/history/") for path, payload in client.calls))

    def test_completed_job_waits_to_leave_queue_without_reposting(self):
        client = FakeClient(self.runtime, linger=True)
        result = self.run_case(client=client, execute=True)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["queue_after"], EMPTY)
        self.assertEqual(sum(path == "/prompt" for path, payload in client.calls), 1)

    def test_service_identity_drift_blocks_post(self):
        calls = []
        def identity_reader(*args):
            calls.append(args)
            value = copy.deepcopy(self.identity)
            if len(calls) > 1:
                value["create_time"] = 2.0
            return value
        client = FakeClient(self.runtime)
        with self.assertRaisesRegex(acceptance.AcceptanceError, "drifted"):
            self.run_case(client=client, execute=True, identity_reader=identity_reader)
        self.assertFalse(any(path == "/prompt" for path, payload in client.calls))

    def test_service_identity_drift_after_post_reports_failure_without_reposting(self):
        calls = []
        def identity_reader(*args):
            calls.append(args)
            value = copy.deepcopy(self.identity)
            if len(calls) >= 4:
                value["create_time"] = 2.0
            return value
        client = FakeClient(self.runtime)
        result = self.run_case(client=client, execute=True, identity_reader=identity_reader)
        self.assertFalse(result["pass"])
        self.assertTrue(result["submitted"])
        self.assertIn("drifted", result["error"])
        self.assertEqual(sum(path == "/prompt" for path, payload in client.calls), 1)

    def test_uncertain_submission_is_never_retried_and_history_confirms_it(self):
        class UncertainClient(FakeClient):
            def request(self, path, payload=None):
                result = super().request(path, payload)
                if path == "/prompt":
                    raise TimeoutError("Synthetic transport uncertainty")
                return result
        client = UncertainClient(self.runtime)
        result = self.run_case(client=client, execute=True)
        self.assertFalse(result["pass"])
        self.assertTrue(result["submitted"])
        self.assertEqual(result["submission_outcome"], "accepted_confirmed_from_history")
        self.assertEqual(sum(path == "/prompt" for path, payload in client.calls), 1)

    def test_real_identity_guard_checks_executable_cwd_creation_and_listener(self):
        process = SimpleNamespace(create_time=lambda: 1.25, exe=lambda: str(self.runtime / "python/python.exe"),
                                  cwd=lambda: str(self.runtime / "ComfyUI"))
        listener = SimpleNamespace(pid=456, status="LISTEN", laddr=SimpleNamespace(port=8188))
        psutil_fixture = SimpleNamespace(Process=lambda pid: process, CONN_LISTEN="LISTEN", net_connections=lambda kind: [listener])
        with patch.dict(sys.modules, {"psutil": psutil_fixture}):
            self.assertEqual(acceptance.read_identity(self.runtime, 456, 1.25)["create_time"], 1.25)
            with self.assertRaisesRegex(acceptance.AcceptanceError, "creation time"):
                acceptance.read_identity(self.runtime, 456, 2.0)
            listener.pid = 789
            with self.assertRaisesRegex(acceptance.AcceptanceError, "listener"):
                acceptance.read_identity(self.runtime, 456, 1.25)
            listener.pid = 456
            process.cwd = lambda: str(self.base / "elsewhere")
            with self.assertRaisesRegex(acceptance.AcceptanceError, "executable/cwd"):
                acceptance.read_identity(self.runtime, 456, 1.25)

    def test_nonfinite_wait_timeout_is_refused(self):
        with self.assertRaises(acceptance.AcceptanceError):
            self.run_case(timeout=float("nan"))

    def test_foreign_queue_after_submit_reports_failure_without_manipulating_jobs(self):
        client = FakeClient(self.runtime, foreign_during=True)
        result = self.run_case(client=client, execute=True)
        self.assertFalse(result["pass"])
        self.assertIn("foreign", result["error"])
        self.assertTrue(result["submitted"])
        self.assertEqual(sum(path == "/prompt" for path, payload in client.calls), 1)
        self.assertFalse(result["queue_cleared"])

    def test_backend_error_retains_complete_history_and_errors(self):
        client = FakeClient(self.runtime, failure=True)
        result = self.run_case(client=client, execute=True)
        self.assertFalse(result["pass"])
        self.assertTrue((self.base / "evidence/history.json").is_file())
        errors = json.loads((self.base / "evidence/execution-errors.json").read_text(encoding="utf8"))
        self.assertEqual(errors[0][0], "execution_error")

    def test_successful_history_with_wrong_prompt_uuid_is_refused(self):
        class WrongHistoryClient(FakeClient):
            def request(self, path, payload=None):
                response = super().request(path, payload)
                if path.startswith("/history/"):
                    response[self.posted["prompt_id"]]["prompt"][1] = "another-job"
                return response
        result = self.run_case(client=WrongHistoryClient(self.runtime), execute=True)
        self.assertFalse(result["pass"])
        self.assertIn("prompt identity", result["error"])
        self.assertTrue((self.base / "evidence/history.json").exists())

    def test_successful_history_with_rewritten_execution_graph_is_refused(self):
        class RewrittenHistoryClient(FakeClient):
            def request(self, path, payload=None):
                response = super().request(path, payload)
                if path.startswith("/history/"):
                    response[self.posted["prompt_id"]]["prompt"][2] = copy.deepcopy(self.posted["prompt"])
                    response[self.posted["prompt_id"]]["prompt"][2]["1"]["inputs"]["width"] = 32
                return response
        result = self.run_case(client=RewrittenHistoryClient(self.runtime), execute=True)
        self.assertFalse(result["pass"])
        self.assertIn("history graph differs", result["error"])
        self.assertFalse((self.base / "evidence/image-metrics.json").exists())

    def test_successful_history_accepts_declared_float_coercion_without_rewriting_submission(self):
        candidate = graph()
        candidate["1"]["inputs"]["cfg"] = 7
        self.export.write_text(json.dumps(candidate), encoding="utf8")
        class FloatHistoryClient(FakeClient):
            def request(self, path, payload=None):
                response = super().request(path, payload)
                if path.startswith("/history/"):
                    history_graph = copy.deepcopy(self.posted["prompt"])
                    history_graph["1"]["inputs"]["cfg"] = 7.0
                    response[self.posted["prompt_id"]]["prompt"][2] = history_graph
                return response
        client = FloatHistoryClient(self.runtime)
        result = self.run_case(client=client, execute=True)
        self.assertTrue(result["pass"], result)
        self.assertIs(type(client.posted["prompt"]["1"]["inputs"]["cfg"]), int)
        self.assertTrue(result["history_graph_matches_backend_validation_reference"])
        self.assertEqual(result["backend_literal_coercions"][0]["field"], "cfg")
        self.assertTrue((self.base / "evidence/backend-validation-reference.json").exists())

    def test_successful_history_rejects_bool_numeric_substitution(self):
        candidate = graph()
        candidate["1"]["inputs"]["enabled"] = False
        self.export.write_text(json.dumps(candidate), encoding="utf8")
        class NumericHistoryClient(FakeClient):
            def request(self, path, payload=None):
                response = super().request(path, payload)
                if path.startswith("/history/"):
                    history_graph = copy.deepcopy(self.posted["prompt"])
                    history_graph["1"]["inputs"]["enabled"] = 0
                    response[self.posted["prompt_id"]]["prompt"][2] = history_graph
                return response
        result = self.run_case(client=NumericHistoryClient(self.runtime), execute=True)
        self.assertFalse(result["pass"])
        self.assertIn("history graph differs", result["error"])
        self.assertFalse((self.base / "evidence/image-metrics.json").exists())

    def test_successful_history_rejects_type_drift_outside_declared_backend_conversion(self):
        class IncorrectIntegerHistoryClient(FakeClient):
            def request(self, path, payload=None):
                response = super().request(path, payload)
                if path.startswith("/history/"):
                    history_graph = copy.deepcopy(self.posted["prompt"])
                    history_graph["1"]["inputs"]["width"] = 16.0
                    response[self.posted["prompt_id"]]["prompt"][2] = history_graph
                return response
        result = self.run_case(client=IncorrectIntegerHistoryClient(self.runtime), execute=True)
        self.assertFalse(result["pass"])
        self.assertIn("history graph differs", result["error"])

    def test_successful_history_without_prompt_is_refused(self):
        class NoPromptHistoryClient(FakeClient):
            def request(self, path, payload=None):
                response = super().request(path, payload)
                if path.startswith("/history/"):
                    del response[self.posted["prompt_id"]]["prompt"]
                return response
        result = self.run_case(client=NoPromptHistoryClient(self.runtime), execute=True)
        self.assertFalse(result["pass"])
        self.assertIn("prompt identity", result["error"])

    def test_only_requested_qa_save_outputs_are_measured(self):
        from PIL import Image
        folder = self.runtime / "ComfyUI/output" / PREFIX
        folder.mkdir(parents=True)
        Image.new("RGB", (8, 8), (30, 60, 90)).save(folder / "final.png")
        history = {"outputs": {"3": {"images": [{"type": "output", "subfolder": PREFIX.rstrip("/"), "filename": "final.png"}]},
                               "intermediate": {"images": [{"type": "temp", "filename": "internal-preview.png"}]}}}
        result = acceptance.image_metrics(history, self.runtime, PREFIX, ["3"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["node_id"], "3")

    def test_evidence_cannot_overwrite_prior_runs(self):
        (self.base / "evidence").mkdir()
        with self.assertRaisesRegex(acceptance.AcceptanceError, "already exists"):
            self.run_case()

    def test_evidence_cannot_be_written_inside_runtime(self):
        with self.assertRaisesRegex(acceptance.AcceptanceError, "outside"):
            acceptance.run_acceptance(runtime=self.runtime, evidence=self.runtime / "receipt", export=self.export,
                     expected_pid=456, targets=["3"], case="fixture")

    def test_execution_requires_expected_creation_time(self):
        with self.assertRaisesRegex(acceptance.AcceptanceError, "creation time"):
            acceptance.run_acceptance(runtime=self.runtime, evidence=self.base / "evidence", export=self.export,
                     expected_pid=456, targets=["3"], case="fixture", execute=True)

    def test_transport_endpoint_allowlist_refuses_queue_mutations_and_remote_urls(self):
        client = acceptance.LocalClient()
        for path, payload in (("https://example.invalid", None), ("/queue", {"clear": True}), ("/free", {}), ("/interrupt", {})):
            with self.subTest(path=path):
                with self.assertRaises(acceptance.AcceptanceError):
                    client.request(path, payload)

    def test_history_path_escape_is_refused_before_image_read(self):
        history = {"outputs": {"3": {"images": [{"type": "output", "subfolder": "../", "filename": "user.png"}]}}}
        with self.assertRaises(acceptance.AcceptanceError):
            acceptance.image_metrics(history, self.runtime, PREFIX)

    def test_native_windows_history_subfolder_is_normalized_without_mutating_history(self):
        from PIL import Image
        folder = self.runtime / "ComfyUI/output" / PREFIX
        folder.mkdir(parents=True)
        Image.new("RGB", (8, 8), (30, 60, 90)).save(folder / "native.png")
        history = {"outputs": {"3": {"images": [{"type": "output", "subfolder": PREFIX.rstrip("/").replace("/", "\\"), "filename": "native.png"}]}}}
        original = copy.deepcopy(history)
        result = acceptance.image_metrics(history, self.runtime, PREFIX, ["3"])
        self.assertEqual(result[0]["relative_path"], PREFIX + "native.png")
        self.assertEqual(result[0]["size"], [8, 8])
        self.assertEqual(history, original)

    def test_windows_history_unc_drive_absolute_traversal_and_qa_escape_are_refused(self):
        for subfolder in (r"\\server\share", r"C:\outside", r"C:outside", r"\_codex_qa\final_acceptance_20261007",
                          PREFIX.replace("/", "\\") + r"..\outside", "/absolute", r"\\?\C:\outside",
                          r"_codex_qa\elsewhere", PREFIX.replace("/", "\\") + "NUL", None):
            with self.subTest(subfolder=subfolder):
                history = {"outputs": {"3": {"images": [{"type": "output", "subfolder": subfolder, "filename": "native.png"}]}}}
                with patch("PIL.Image.open") as opened:
                    with self.assertRaises(acceptance.AcceptanceError):
                        acceptance.image_metrics(history, self.runtime, PREFIX, ["3"])
                    opened.assert_not_called()

    def test_windows_history_normalization_does_not_allow_filename_separators(self):
        for filename in (r"nested\native.png", "nested/native.png", r"C:\native.png", "../native.png"):
            with self.subTest(filename=filename):
                history = {"outputs": {"3": {"images": [{"type": "output", "subfolder": PREFIX.rstrip("/").replace("/", "\\"), "filename": filename}]}}}
                with self.assertRaises(acceptance.AcceptanceError):
                    acceptance.image_metrics(history, self.runtime, PREFIX, ["3"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
