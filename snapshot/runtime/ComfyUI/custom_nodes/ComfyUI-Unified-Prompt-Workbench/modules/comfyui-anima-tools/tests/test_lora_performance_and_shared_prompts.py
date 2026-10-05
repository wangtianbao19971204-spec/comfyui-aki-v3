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

    def test_shared_prompt_adapter_filters_classifies_and_deduplicates(self):
        adapter = load_shared_prompt_adapter()
        source_data = {
            "last_modified": "test",
            "categories": [
                {
                    "id": "9e8dc17b-a451-542f-80ec-df510f0657e9",
                    "name": "Anima/姿势/正常/表情与情绪",
                    "prompts": [
                        {
                            "id": "pose-1",
                            "alias": "挥手",
                            "prompt": "waving, smile",
                            "image": "wave.png",
                        },
                        {
                            "id": "pose-duplicate",
                            "alias": "重复挥手",
                            "prompt": " waving , smile ",
                            "image": "",
                        },
                    ],
                },
                {
                    "id": "36f64bfc-0408-50e4-ae5d-673eb9e8506d",
                    "name": "Anima/背景/正常/室内",
                    "prompts": [
                        {"id": "bg-1", "alias": "卧室", "prompt": "bedroom, window"},
                    ],
                },
                {
                    "id": "b8b0c664-f87b-583d-b296-e4f7cc840cb5",
                    "name": "Anima/服装/正常/日常与季节/夏装",
                    "prompts": [
                        {"id": "clothes-1", "alias": "夏装", "prompt": "summer dress"},
                    ],
                },
                {
                    "id": "cat-020e87fd",
                    "name": "Anima/角色/正常/作品角色/测试角色",
                    "prompts": [
                        {
                            "id": "character-1",
                            "alias": "测试角色",
                            "prompt": "specific character, silver hair",
                            "image": "character.png",
                            "updated_at": "character-v2",
                        },
                    ],
                },
                {
                    "id": "new-explicit-category",
                    "name": "Anima/动作/测试/新增动作",
                    "prompts": [
                        {"id": "explicit-1", "alias": "显式新增动作", "prompt": "new explicit pose"},
                    ],
                },
                {
                    "id": "style-quality-category",
                    "name": "待归类/Anima复核/画风质量镜头/质量与正向参数",
                    "prompts": [
                        {
                            "id": "style-quality-1",
                            "alias": "电影质感",
                            "prompt": "masterpiece, cinematic lighting",
                        },
                    ],
                },
                {
                    "id": "new-unmapped-category",
                    "name": "测试/全新任意分类",
                    "prompts": [
                        {"id": "unmapped-1", "alias": "未映射", "prompt": "unmapped prompt"},
                    ],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "data.json"
            source_path.write_text(
                json.dumps(source_data, ensure_ascii=False),
                encoding="utf-8",
            )
            payloads = adapter["_build_shared_prompt_payloads"](
                str(source_path),
                source_path.stat().st_mtime_ns,
            )

        self.assertEqual(payloads["pose"]["count"], 2)
        self.assertEqual(payloads["background"]["count"], 1)
        self.assertEqual(payloads["clothing"]["count"], 1)
        self.assertEqual(payloads["character"]["count"], 1)
        self.assertEqual(payloads["style_quality"]["count"], 1)
        pose_item = next(
            item for item in payloads["pose"]["items"]
            if item["id"] == "weilin:pose:pose-1"
        )
        self.assertEqual(pose_item["categories"], ["WeiLin / 用户动作分类"])
        self.assertEqual(
            pose_item["shared_category_paths"],
            [{
                "levels": [
                    "WeiLin / 用户动作分类",
                    "正常",
                    "表情与情绪",
                ],
                "parent": "WeiLin / 用户动作分类",
                "source": "表情与情绪",
                "source_full": "Anima/姿势/正常/表情与情绪",
                "source_category_id": "9e8dc17b-a451-542f-80ec-df510f0657e9",
            }],
        )
        self.assertTrue(
            pose_item["preview"].startswith(
                "/prompt_selector/preview/wave.png?v="
            ),
        )
        explicit_item = next(
            item for item in payloads["pose"]["items"]
            if item["id"] == "weilin:pose:explicit-1"
        )
        self.assertEqual(
            explicit_item["shared_category_paths"][0]["levels"],
            ["WeiLin / 用户动作分类", "测试", "新增动作"],
        )
        self.assertEqual(payloads["pose"]["unmapped_category_count"], 1)
        self.assertEqual(
            payloads["pose"]["unmapped_categories"][0]["id"],
            "new-unmapped-category",
        )
        self.assertFalse(any(
            item["id"] == "weilin:pose:unmapped-1"
            for item in payloads["pose"]["items"]
        ))
        style_quality_item = payloads["style_quality"]["items"][0]
        self.assertEqual(
            style_quality_item["shared_category_paths"][0]["levels"],
            ["WeiLin / 画风质量镜头", "质量与正向参数"],
        )
        self.assertEqual(
            style_quality_item["source_category"],
            "待归类/Anima复核/画风质量镜头/质量与正向参数",
        )
        character_item = payloads["character"]["items"][0]
        self.assertEqual(character_item["trigger"], "specific character, silver hair")
        self.assertEqual(
            character_item["copyright"],
            "角色/正常/作品角色/测试角色",
        )
        self.assertEqual(
            character_item["preview"],
            "/prompt_selector/preview/character.png?v=character-v2",
        )
        self.assertEqual(
            adapter["_shared_prompt_source_leaf"]("法典/二级/最末级"),
            "二级/最末级",
        )
        self.assertEqual(
            adapter["_shared_prompt_source_leaf"]("法典/口交（类口交／颜射）"),
            "口交（类口交／颜射）",
        )
        self.assertEqual(
            adapter["_shared_prompt_levels_with_source_lineage"](
                ["WeiLin / 成人互动", "性行为"],
                "法典/口交（类口交／颜射）",
                "id",
            ),
            [
                "WeiLin / 成人互动",
                "性行为",
                "法典",
                "口交（类口交／颜射）",
            ],
        )
        self.assertEqual(
            adapter["_shared_prompt_levels_with_source_lineage"](
                ["WeiLin / 用户服装分类", "自建服装", "测试组"],
                "Anima/服装/自建服装/测试组",
                "prefix",
            ),
            ["WeiLin / 用户服装分类", "自建服装", "测试组"],
        )
        self.assertEqual(
            adapter["_shared_prompt_codex_directory_levels"](
                "所长色色NovelAI个人法典(上)/后入/背后位"
            ),
            ["后入", "背后位"],
        )
        self.assertEqual(
            adapter["_shared_prompt_levels_with_source_lineage"](
                ["WeiLin / 成人互动", "体位", "后入", "背身位"],
                "所长色色NovelAI个人法典(上)/后入/背后位",
                "id",
                "source_directory_without_codex_root",
            ),
            ["WeiLin / 后入", "背后位"],
        )
        self.assertEqual(
            adapter["_shared_prompt_levels_with_source_lineage"](
                ["WeiLin / 成人互动", "性行为", "口交/颜射"],
                "所长色色NovelAI个人法典(上)/口交（类口交／颜射）",
                "id",
                "source_directory_without_codex_root",
            ),
            ["WeiLin / 口交（类口交／颜射）"],
        )


if __name__ == "__main__":
    unittest.main()
