import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from contextlib import redirect_stderr

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "snapshot/runtime/production_tools/connect_standalone_krea2_control.py"
sys.path.insert(0, str(PATH.parent))
spec = importlib.util.spec_from_file_location("standalone_krea2_control", PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class StandaloneKrea2ControlTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((REPO / "tests/fixtures/krea2_control_before.json").read_text(encoding="utf-8"))

    def test_user_nodes_parameters_modes_and_unrelated_wiring_are_preserved(self):
        untouched = copy.deepcopy(self.before)
        after = migration.migrate(self.before)
        self.assertEqual(self.before, untouched, "Migration must not mutate its input")
        self.assertEqual(after["groups"], self.before["groups"])
        self.assertEqual(after["version"], self.before["version"])
        for key, value in self.before["extra"].items():
            self.assertEqual(after["extra"][key], value)
        old = {item["id"]: item for item in self.before["nodes"]}
        new = {item["id"]: item for item in after["nodes"]}
        self.assertEqual([n["id"] for n in after["nodes"][:len(old)]], list(old))
        for node_id, item in old.items():
            for field, value in item.items():
                if field not in ("inputs", "outputs"):
                    self.assertEqual(new[node_id][field], value, (node_id, field))
        rerouted_targets = {(501, 0), (504, 0), (534, 0)}
        new_links = {link[0]: link for link in after["links"]}
        for link in self.before["links"]:
            if (link[3], link[4]) not in rerouted_targets:
                self.assertEqual(new_links[link[0]], link)
        # The user's control weight/strength, pose and RGB mask survive intact.
        self.assertEqual(new[535]["widgets_values"], ["user-control.safetensors", 0.73])
        self.assertEqual(new[506]["widgets_values"], old[506]["widgets_values"])
        self.assertEqual(new[513]["widgets_values"], old[513]["widgets_values"])
        self.assertEqual(new[10]["widgets_values"], old[10]["widgets_values"])

    def test_both_sources_and_optional_erase_reach_encode_and_apply(self):
        after = migration.migrate(self.before)
        r = after["extra"]["krea2_control_routing"]["roles"]
        self.assertEqual(migration.origin(after, r["source"], "input_01"), (449, 0))
        self.assertEqual(migration.origin(after, r["source"], "input_02"), (r["pose_depth"], 0))
        self.assertEqual(migration.origin(after, r["pose_depth"], "image"), (513, 0))
        self.assertEqual(migration.origin(after, r["erase"], "input_01"), (504, 0))
        self.assertEqual(migration.origin(after, r["erase"], "input_02"), (r["source"], 0))
        self.assertEqual(migration.origin(after, 534, "control_image"), (r["erase"], 0))
        self.assertEqual(migration.origin(after, 536, "control_latent"), (534, 0))
        self.assertNotEqual(migration.origin(after, 534, "control_image"), (433, 0))

    def test_mask_composite_and_black_source_use_selected_source_dimensions(self):
        after = migration.migrate(self.before)
        source = after["extra"]["krea2_control_routing"]["roles"]["source"]
        self.assertEqual(migration.origin(after, 501, "image"), (source, 0))
        self.assertEqual(migration.origin(after, 504, "destination"), (source, 0))
        self.assertEqual(migration.origin(after, 502, "width"), (501, 0))
        self.assertEqual(migration.origin(after, 502, "height"), (501, 1))

    def test_rgb_mask_is_preserved_and_erase_defaults_to_explicit_bypass(self):
        after = migration.migrate(self.before)
        r = after["extra"]["krea2_control_routing"]["roles"]
        nodes = {n["id"]: n for n in after["nodes"]}
        self.assertEqual(nodes[r["erase"]]["widgets_values"], ["input_02", "priority", 0])
        self.assertEqual(nodes[r["source"]]["widgets_values"], ["input_01", "priority", 0])
        self.assertEqual(nodes[r["pose_depth"]]["mode"], nodes[513]["mode"])
        self.assertEqual(nodes[r["pose_depth"]]["widgets_values"], nodes[433]["widgets_values"])
        note = nodes[r["note"]]["widgets_values"][0]
        self.assertIn("RGB", note)
        self.assertIn("MASK=1-alpha", note)
        self.assertIn("蒙版编辑器", note)

    def test_every_link_has_consistent_endpoint_and_reverse_references(self):
        after = migration.migrate(self.before)
        nodes = {n["id"]: n for n in after["nodes"]}
        self.assertEqual(len(nodes), len(after["nodes"]))
        ids = [link[0] for link in after["links"]]
        self.assertEqual(len(ids), len(set(ids)))
        for link_id, source, source_slot, target, target_slot, kind in after["links"]:
            out = nodes[source]["outputs"][source_slot]
            incoming = nodes[target]["inputs"][target_slot]
            self.assertIn(link_id, out["links"])
            self.assertEqual(incoming["link"], link_id)
            self.assertIn(out["type"], (kind, "*"))
            self.assertIn(incoming["type"], (kind, "*"))

    def test_idempotence_keeps_subsequent_user_choices_and_custom_depth_settings(self):
        nodes = {n["id"]: n for n in self.before["nodes"]}
        nodes[433]["widgets_values"] = ["user-depth-checkpoint.pth", 768]
        nodes[449]["widgets_values"][0] = "input_02"
        after = migration.migrate(self.before)
        r = after["extra"]["krea2_control_routing"]["roles"]
        updated = {n["id"]: n for n in after["nodes"]}
        self.assertEqual(updated[r["pose_depth"]]["widgets_values"], ["user-depth-checkpoint.pth", 768])
        updated[r["source"]]["widgets_values"][0] = "input_02"
        updated[r["erase"]]["widgets_values"][0] = "input_01"
        self.assertEqual(migration.migrate(after), after)

    def test_unknown_or_custom_wiring_is_rejected_without_mutation(self):
        original = copy.deepcopy(self.before)
        self.before["links"] = [list(link) for link in self.before["links"]]
        link = next(link for link in self.before["links"] if link[3] == 534 and link[4] == 0)
        link[1] = 449
        changed = copy.deepcopy(self.before)
        with self.assertRaisesRegex(ValueError, "Custom legacy wiring"):
            migration.migrate(self.before)
        self.assertEqual(self.before, changed)
        after = migration.migrate(original)
        next(link for link in after["links"] if link[3] == 534 and link[4] == 0)[1] = 433
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            migration.migrate(after)

    def test_cli_cannot_write_a_deployed_runtime_directory(self):
        with mock.patch.object(migration, "ROOT", Path("C:/user-running-instance/runtime")), \
             mock.patch.object(sys, "argv", ["tool", "--write-source"]), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                migration.main()
            self.assertEqual(error.exception.code, 2)

    def test_formal_and_template_keep_independent_data_with_the_same_repaired_route(self):
        sources = []
        for base in ("ComfyUI/user/default/workflows", "production_tools/templates"):
            data = json.loads((REPO / "snapshot/runtime" / base / migration.FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(migration.migrate(data), data)
            migration.validate_routing(data)
            sources.append({n["id"]: n for n in data["nodes"]})
            self.assertEqual(next(n for n in data["nodes"] if n["id"] == 10)["widgets_values"][2:6], [8, 1, "euler", "simple"])
        self.assertNotEqual(sources[0][506]["widgets_values"], sources[1][506]["widgets_values"])
        self.assertNotEqual(sources[0][472]["widgets_values"], sources[1][472]["widgets_values"])


if __name__ == "__main__":
    unittest.main()
