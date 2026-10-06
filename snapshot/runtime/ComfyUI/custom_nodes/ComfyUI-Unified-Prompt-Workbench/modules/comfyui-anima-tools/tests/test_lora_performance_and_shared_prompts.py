import ast
import hashlib
import json
import os
import re
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]


class _RoutesStub:
    def get(self, *_args, **_kwargs):
        return lambda function: function

    def post(self, *_args, **_kwargs):
        return lambda function: function


class _PromptServerStub:
    instance = type("Instance", (), {"routes": _RoutesStub()})()


def load_shared_prompt_adapter():
    path = PLUGIN_DIR / "nodes.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    start = next(
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_SHARED_PROMPT_KINDS"
            for target in node.targets
        )
    )
    end = next(
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "ANIMADEX_CHARACTER_SEARCH_API"
            for target in node.targets
        )
    )
    selected = [node for node in tree.body if start <= node.lineno < end]
    namespace = {
        "os": os,
        "re": re,
        "json": json,
        "hashlib": hashlib,
        "threading": threading,
        "urllib": urllib,
        "PromptServer": _PromptServerStub,
        "__file__": str(path),
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace


class LoraPerformanceAndSharedPromptTests(unittest.TestCase):
    def test_search_uses_light_fields_cache_and_non_blocking_route(self):
        api_source = (PLUGIN_DIR / "anima_lora_api.py").read_text(encoding="utf-8")
        nodes_source = (PLUGIN_DIR / "nodes.py").read_text(encoding="utf-8")
        frontend_source = (PLUGIN_DIR / "js" / "anima_lora_selector.js").read_text(encoding="utf-8")

        tree = ast.parse(api_source)
        search_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_search_civitai_loras_meili"
        )
        search_source = ast.get_source_segment(api_source, search_node)

        self.assertNotIn('"descriptionHtml"', search_source)
        self.assertNotIn('"versions"', search_source)
        self.assertIn('"images.url"', search_source)
        self.assertIn("def _load_civitai_cached_response", api_source)
        self.assertIn("stale-refreshing", api_source)
        self.assertRegex(
            nodes_source,
            r"await asyncio\.to_thread\(\s*search_civitai_loras",
        )
        self.assertIn('miss_mode in {"redirect", "direct"}', nodes_source)
        self.assertIn('miss: "redirect"', frontend_source)

    def test_reviewed_shared_adapter_preserves_identity_and_source_bytes(self):
        import importlib.util
        import sys
        import types
        from unittest.mock import patch

        helper_dir = PLUGIN_DIR.parent / "WeiLin-Comfyui-Tools-V52-FullPromptSelector" / "prompt_selector"
        package_name = "isolated_shared_adapter_helpers"
        package = types.ModuleType(package_name)
        package.__path__ = [str(helper_dir)]
        with patch.dict(sys.modules, {package_name: package}):
            projection = __import__(package_name + ".semantic_projection", fromlist=["binding"])
            adapter = load_shared_prompt_adapter()
            source = {"last_modified": "fixture", "categories": [{
                "id": "source-fixture", "name": "Fixture/source", "prompts": [
                    {"id": "pose-a", "alias": "Wave", "prompt": "waving, smile", "image": "wave.png", "favorite": True},
                    {"id": "pose-b", "alias": "Wave variant", "prompt": " waving , smile "},
                    {"id": "character-a", "alias": "Hero", "prompt": "specific character, silver hair", "updated_at": "v2", "image": "hero.png"},
                    {"id": "pending-a", "alias": "Unreviewed", "prompt": "pending token"},
                    {"id": "negative-a", "alias": "Negative", "prompt": "bad anatomy"},
                ],
            }]}
            category = source["categories"][0]
            decisions = {}
            for prompt in category["prompts"]:
                if prompt["id"] == "pending-a":
                    continue
                decisions[prompt["id"]] = {
                    "binding": projection.binding(category, prompt), "disposition": "reviewed",
                    "manual_search_eligible": True, "random_pool_eligible": True,
                    "strict_model_pool_eligible": True, "content_type": "fragment",
                    "usage": "negative" if prompt["id"] == "negative-a" else "positive",
                    "primary_class": "identity" if prompt["id"] == "character-a" else "pose_action",
                    "subcategories": ["作品角色"] if prompt["id"] == "character-a" else ["手势与肢体动作"],
                    "taxonomy_version": "fixture-v1",
                }
            document = {"schema": "S4-semantic-projection-v1", "decisions": decisions}
            adapter["_load_semantic_projection_runtime"] = lambda _path: (projection, document)
            before = json.dumps(source, ensure_ascii=False, sort_keys=True)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "data.json"
                path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf8")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                payloads = adapter["_build_shared_prompt_payloads"](str(path), path.stat().st_mtime_ns)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertEqual(json.dumps(source, ensure_ascii=False, sort_keys=True), before)
            poses = payloads["pose"]["items"]
            self.assertEqual([item["id"] for item in poses], ["weilin:pose:pose-a", "weilin:pose:pose-b"])
            self.assertEqual([item["tags"] for item in poses], ["waving, smile", " waving , smile "])
            self.assertTrue(poses[0]["favorite"])
            self.assertEqual(poses[0]["_semantic"]["subcategory_owners"], {"手势与肢体动作": "pose_action"})
            self.assertEqual(poses[0]["shared_category_paths"][0]["levels"], ["WeiLin / 动作与姿势", "手势与肢体动作"])
            self.assertEqual(payloads["pose"]["pending_prompt_ids"], ["pending-a"])
            self.assertEqual(payloads["pose"]["reviewed_nonfragment_count"], 1)
            self.assertFalse(any("pending-a" in item["id"] or "negative-a" in item["id"]
                                 for payload in payloads.values() for item in payload["items"]))
            character = payloads["character"]["items"][0]
            self.assertEqual(character["trigger"], "specific character, silver hair")
            self.assertEqual(character["copyright"], "Fixture/source")
            self.assertEqual(character["preview"], "/prompt_selector/preview/hero.png?v=v2")
            self.assertEqual(character["source_category_id"], "source-fixture")
            filtered = adapter["_build_shared_prompt_payloads"](
                "fixture", 1, source_data=source, source_sha256="fixture-hash",
                category_filter='shared-filters:["shared-source:missing-source"]')
            self.assertTrue(all(payload["count"] == 0 for payload in filtered.values()))
            category["prompts"][0]["prompt"] = "edited after review"
            changed = adapter["_build_shared_prompt_payloads"]("fixture", 1, source_data=source)
            self.assertIn("pose-a", changed["pose"]["pending_prompt_ids"])
            self.assertEqual(changed["pose"]["count"], 1)

    def test_source_lineage_compatibility_helpers(self):
        adapter = load_shared_prompt_adapter()
        self.assertEqual(adapter["_shared_prompt_source_leaf"]("Fixture/二级/最末级"), "二级/最末级")
        self.assertEqual(adapter["_shared_prompt_levels_with_source_lineage"](
            ["WeiLin / 用户服装分类", "自建服装", "测试组"], "Anima/服装/自建服装/测试组", "prefix"),
            ["WeiLin / 用户服装分类", "自建服装", "测试组"])


if __name__ == "__main__":
    unittest.main()
