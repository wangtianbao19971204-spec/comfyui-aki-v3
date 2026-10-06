"""Offline profile and current saved-reference regressions; no live service I/O."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import validate_profiles as profiles


TOOLS = Path(__file__).resolve().parent
SNAPSHOT = TOOLS.parent
REPOSITORY = SNAPSHOT.parents[1] if SNAPSHOT.name == "runtime" and SNAPSHOT.parent.name == "snapshot" else SNAPSHOT / "maintenance/comfyui"


def fixture(path, modules=(), unregistered=()):
    return {"path": path, "modules": list(modules), "types": list(unregistered),
            "unregistered": list(unregistered)}


class ProfileScopeRegression(unittest.TestCase):
    def test_lean_selects_six_tools_and_release_but_not_new_detail_extension(self):
        workflows = [fixture(f"workflows/生产扩展_{number:02d}_fixture.json") for number in range(1, 12)]
        workflows += [fixture("workflows/生产套件_99_释放模型显存_v2.json"),
                      fixture("workflows/UAP统一生产工作台_v2.json")]
        selected = list(profiles.selected_workflows("lean", workflows))
        self.assertEqual([Path(item["path"]).name for item in selected],
                         [f"生产扩展_{number:02d}_fixture.json" for number in range(4, 10)]
                         + ["生产套件_99_释放模型显存_v2.json"])

    def test_production_still_includes_extension_ten_for_dependency_checks(self):
        workflow = fixture("workflows/生产扩展_10_部位细化_Anima.json")
        self.assertEqual(list(profiles.selected_workflows("production", [workflow])), [workflow])
        self.assertEqual(list(profiles.selected_workflows("diagnostic", [workflow])), [workflow])

    def test_lean_does_not_report_foreign_extension_dependencies(self):
        plugins = ["ComfyUI-Anima-LLLite", "comfyui-krea2edit", "ComfyUI-Olm-DragCrop",
                   "ComfyUI-RMBG", "comfyui_memory_cleanup"]
        inventory = {"checked_at": "fixture", "module_manifest": {"modules": []},
                     "workflows": [fixture("生产扩展_04_Krea2_指令编辑.json", ["custom_nodes.comfyui-krea2edit"]),
                                   fixture("生产套件_99_释放模型显存_v2.json", ["custom_nodes.comfyui_memory_cleanup"]),
                                   fixture("生产扩展_10_部位细化_Anima.json", ["custom_nodes.ComfyUI-Impact-Pack"],
                                           ["FixtureUnsupportedDetailer"])]}
        launch = {"args": ["--disable-all-custom-nodes", "--whitelist-custom-nodes", *plugins]}
        with tempfile.TemporaryDirectory(prefix="lean-profile-regression-") as temporary:
            root = Path(temporary)
            for name in plugins:
                (root / "ComfyUI/custom_nodes" / name).mkdir(parents=True)
            with patch.object(profiles, "ROOT", root), patch.object(profiles.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(launch))):
                result = profiles.validate(inventory, {"lean": plugins})
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(len(result["profiles"]["lean"]["workflows"]), 2)

    def test_saved_primary_suite_navigation_uses_existing_exact_groups(self):
        names = ("生产套件_01_Anima原版_LoRA生产_v2.json", "生产套件_02_Anima2.9B_动漫生产_v2.json",
                 "生产套件_03_Krea2_一体化生产_v2.json")
        for relative in ("ComfyUI/user/default/workflows", "production_tools/templates"):
            for name in names:
                with self.subTest(directory=relative, workflow=name):
                    workflow = json.loads((SNAPSHOT / relative / name).read_text(encoding="utf8"))
                    titles = {group["title"] for group in workflow["groups"]}
                    targets = workflow["extra"]["qgn_navigation_groups"]
                    self.assertTrue(targets)
                    self.assertEqual([item["groupName"] for item in targets if item["groupName"] not in titles], [])

    def test_edit_template_lora_resolves_to_current_catalogue_identity(self):
        workflow = json.loads((TOOLS / "templates/生产扩展_04_Krea2_指令编辑.json").read_text(encoding="utf8"))
        node = next(item for item in workflow["nodes"] if item["id"] == 13)
        self.assertEqual(node["type"], "LoraLoaderModelOnly")
        selected = "ComfyUI/models/loras/" + node["widgets_values"][0].replace("\\", "/")
        catalogue = json.loads((REPOSITORY / "snapshot/inventory/model_sources.json").read_text(encoding="utf8"))
        items = catalogue.get("assets", catalogue.get("models", catalogue.get("entries", [])))
        matches = [item for item in items if item.get("current_path", item.get("path")) == selected]
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]["observed_present"])
        self.assertEqual(node["widgets_values"][1], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
