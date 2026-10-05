import ast
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
NODES_PATH = PLUGIN_DIR / "nodes.py"


def load_selector_classes():
    source = NODES_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(NODES_PATH))
    selected_names = {
        "_anima_selector_tags_result",
        "AnimaStyleQualitySelector",
        "AnimaStyleQualitySelectorPlus",
    }
    selected = [
        node
        for node in tree.body
        if getattr(node, "name", "") in selected_names
    ]
    namespace = {}
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(NODES_PATH), "exec"),
        namespace,
    )
    return namespace


class StyleQualitySelectorTests(unittest.TestCase):
    def test_base_selector_outputs_text_and_execution_sync_payload(self):
        namespace = load_selector_classes()
        selector = namespace["AnimaStyleQualitySelector"]()

        result = selector.process_tags(
            "_raw_:cinematic lighting, masterpiece",
            "append",
            "portrait",
        )

        self.assertEqual(
            result["result"],
            ("cinematic lighting, masterpiece, portrait, ",),
        )
        self.assertEqual(
            result["ui"]["anima_selector_tags"],
            [{
                "style_quality_tags": "_raw_:cinematic lighting, masterpiece",
            }],
        )
        self.assertIn(
            "style_quality_tags",
            selector.INPUT_TYPES()["required"],
        )

    def test_base_selector_override_ignores_connected_prompt(self):
        selector = load_selector_classes()["AnimaStyleQualitySelector"]()
        result = selector.process_tags("masterpiece", "override", "portrait")
        self.assertEqual(result["result"], ("masterpiece, ",))

    def test_plus_selector_uses_configured_separator(self):
        selector = load_selector_classes()["AnimaStyleQualitySelectorPlus"]()
        result = selector.process_tags(
            "masterpiece, _raw_:rim light",
            "portrait",
            " | ",
        )
        self.assertEqual(result["result"], ("masterpiece, rim light | portrait",))

    def test_random_draw_uses_style_quality_shared_payload(self):
        source = NODES_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(NODES_PATH))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_selector_random_text"
        )
        namespace = {
            "get_shared_prompt_payload": lambda _kind: {
                "items": [{
                    "id": "style-1",
                    "name": "Cinematic",
                    "name_zh": "电影质感",
                    "tags": "masterpiece, cinematic lighting",
                    "source_category": "待归类/Anima复核/画风质量镜头/质量与正向参数",
                    "preview": "/preview/style-1.png",
                }],
            },
        }
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), str(NODES_PATH), "exec"),
            namespace,
        )

        class Composer:
            @staticmethod
            def _split_prompt_tokens(value):
                return [part.strip() for part in str(value).split(",") if part.strip()]

        text, selected = namespace["_selector_random_text"](
            Composer(),
            "style_quality",
        )
        self.assertEqual(text, "masterpiece, cinematic lighting, ")
        self.assertEqual(selected[0]["section"], "style_quality")
        self.assertEqual(selected[0]["title"], "电影质感")


if __name__ == "__main__":
    unittest.main()
