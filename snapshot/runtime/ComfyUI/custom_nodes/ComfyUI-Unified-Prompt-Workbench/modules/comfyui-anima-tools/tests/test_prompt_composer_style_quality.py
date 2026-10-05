import ast
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
NODES_PATH = PLUGIN_DIR / "nodes.py"


def load_composer_class(shared_items=None):
    source = NODES_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(NODES_PATH))
    composer_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "AnimaPromptComposer"
    )
    namespace = {
        "get_shared_prompt_payload": lambda kind: {
            "items": list(shared_items or []),
        },
    }
    exec(
        compile(
            ast.Module(body=[composer_node], type_ignores=[]),
            str(NODES_PATH),
            "exec",
        ),
        namespace,
    )
    return namespace["AnimaPromptComposer"], namespace


def configure_local_data(composer):
    data = {
        "data.js": [
            {"id": 1, "name": "Artist A"},
            {"id": 2, "name": "Artist B"},
        ],
        "character_data.js": [
            {"name": "Hero A", "copyright": "Series"},
            {"name": "Hero B", "copyright": "Series"},
        ],
        "clothing_data.js": [
            {"id": "clothing-a", "name": "Clothing A", "tags": "red dress"},
            {"id": "clothing-b", "name": "Clothing B", "tags": "blue coat"},
        ],
        "background_data.js": [
            {"id": "background-a", "name": "Forest", "tags": "forest"},
            {"id": "background-b", "name": "City", "tags": "city"},
        ],
        "pose_data.js": [
            {"id": "pose-a", "name": "Standing", "tags": "standing"},
            {"id": "pose-b", "name": "Sitting", "tags": "sitting"},
        ],
    }
    composer._load_js_array = lambda filename: data[filename]
    composer._load_json_object = lambda _filename: {
        "hero a||series": {"trigger": "hero a trigger"},
        "hero b||series": {"trigger": "hero b trigger"},
    }


class PromptComposerStyleQualityTests(unittest.TestCase):
    def setUp(self):
        self.style_items = [
            {
                "id": "style-a",
                "name": "Cinematic",
                "name_zh": "电影质感",
                "tags": "masterpiece, cinematic lighting",
                "preview": "/preview/style-a.png",
                "source_category": "待归类/Anima复核/画风质量镜头/质量与正向参数",
            },
            {
                "id": "style-b",
                "name": "Watercolor",
                "name_zh": "水彩",
                "tags": "watercolor, traditional media",
                "preview": "/preview/style-b.png",
                "source_category": "待归类/Anima复核/画风质量镜头/媒介与渲染风格",
            },
        ]

    def build_composer(self):
        composer_class, namespace = load_composer_class(self.style_items)
        composer = composer_class()
        configure_local_data(composer)
        return composer, namespace

    def resolve(self, composer, enable_style_quality=True):
        return composer._resolve_prompt_data(
            enable_style_quality,
            True,
            True,
            True,
            True,
            True,
            "trigger",
            2026,
            1,
        )

    def test_input_and_preview_sections_follow_anima_order(self):
        composer, _namespace = self.build_composer()
        self.assertEqual(
            list(composer.INPUT_TYPES()["required"]),
            [
                "enable_style_quality",
                "enable_artist",
                "enable_character",
                "enable_clothing",
                "enable_pose",
                "enable_background",
                "character_detail",
                "seed",
                "artist_count",
                "preview_collapsed",
                "resolved_prompt",
            ],
        )
        self.assertEqual(
            composer.SELECTION_SECTIONS,
            (
                "style_quality",
                "artist",
                "character",
                "clothing",
                "pose",
                "background",
            ),
        )

    def test_resolved_text_uses_anima_prompt_order(self):
        composer, _namespace = self.build_composer()
        selected, text = self.resolve(composer)

        ordered_parts = [
            selected["style_quality"][0]["prompt_parts"][0],
            selected["artist"][0]["prompt_parts"][0],
            selected["character"][0]["trigger_parts"][0],
            selected["clothing"][0]["prompt_parts"][0],
            selected["pose"][0]["prompt_parts"][0],
            selected["background"][0]["prompt_parts"][0],
        ]
        positions = [text.index(part) for part in ordered_parts]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(selected["style_quality"][0]["section"], "style_quality")
        self.assertEqual(
            selected["style_quality"][0]["preview"],
            "/preview/style-a.png" if selected["style_quality"][0]["key"].endswith("style-a") else "/preview/style-b.png",
        )

    def test_style_draw_does_not_change_existing_fixed_seed_results(self):
        composer, _namespace = self.build_composer()
        with_style, _text = self.resolve(composer, True)
        without_style, _text = self.resolve(composer, False)

        for section in ("artist", "character", "clothing", "pose", "background"):
            self.assertEqual(
                [entry["key"] for entry in with_style[section]],
                [entry["key"] for entry in without_style[section]],
                section,
            )
        self.assertEqual(without_style["style_quality"], [])

    def test_disabled_style_quality_does_not_access_shared_database(self):
        composer, namespace = self.build_composer()
        namespace["get_shared_prompt_payload"] = lambda _kind: (_ for _ in ()).throw(
            AssertionError("shared database should not be loaded")
        )

        selected, _text = self.resolve(composer, False)
        self.assertEqual(selected["style_quality"], [])

    def test_workflow_widget_indexes_include_seed_control_widget(self):
        composer, _namespace = self.build_composer()
        self.assertEqual(composer._workflow_widget_index("enable_style_quality"), 0)
        self.assertEqual(composer._workflow_widget_index("enable_pose"), 4)
        self.assertEqual(composer._workflow_widget_index("enable_background"), 5)
        self.assertEqual(composer._workflow_widget_index("resolved_prompt"), 11)


if __name__ == "__main__":
    unittest.main()
