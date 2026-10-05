import ast
import unittest
from pathlib import Path


def load_prompt_node_classes():
    nodes_path = Path(__file__).resolve().parents[1] / "nodes.py"
    source = nodes_path.read_text(encoding="utf-8")
    prompt_node_source = source.split("class AnimaPromptComposer:", 1)[0]
    namespace = {}
    exec(compile(prompt_node_source, str(nodes_path), "exec"), namespace)
    return namespace["AnimaPromptPlus"], namespace["AnimaPromptPlusClipEncode"]


def load_queue_resolver():
    nodes_path = Path(__file__).resolve().parents[1] / "nodes.py"
    tree = ast.parse(nodes_path.read_text(encoding="utf-8"), filename=str(nodes_path))
    names = {
        "_set_selector_workflow_widget_value",
        "_resolve_anima_prompt_plus_clip_nodes",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    widget_order = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SELECTOR_WIDGET_ORDERS" for target in node.targets)
    )
    namespace = {}
    exec(
        compile(ast.Module(body=[widget_order, *functions], type_ignores=[]), str(nodes_path), "exec"),
        namespace,
    )
    return namespace["_resolve_anima_prompt_plus_clip_nodes"]


class FakeClip:
    def __init__(self):
        self.tokenized_text = None
        self.encoded_tokens = None

    def tokenize(self, text):
        self.tokenized_text = text
        return {"tokens": text}

    def encode_from_tokens_scheduled(self, tokens):
        self.encoded_tokens = tokens
        return [["conditioning", {"pooled_output": "pooled"}]]


class AnimaPromptPlusClipEncodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prompt_plus, cls.clip_encode = load_prompt_node_classes()
        cls.queue_resolver = staticmethod(load_queue_resolver())

    def prompt_values(self):
        return {
            "quality_prompt": "masterpiece",
            "artist_tags": "by Example Artist",
            "character_tags": "hero",
            "clothing_tags": "red coat",
            "pose_tags": "standing",
            "background_tags": "city",
            "extra_prompt": "dramatic light",
            "separator": ", ",
        }

    def test_original_prompt_plus_output_is_unchanged(self):
        result = self.prompt_plus().compose_prompt(**self.prompt_values())

        self.assertEqual(
            result["result"][0],
            "masterpiece, @Example Artist, hero, red coat, standing, city, dramatic light, ",
        )

    def test_clip_node_encodes_and_records_resolved_positive_prompt(self):
        clip = FakeClip()
        extra_pnginfo = {"workflow": {"nodes": []}}

        result = self.clip_encode().encode_prompt(
            clip=clip,
            extra_pnginfo=extra_pnginfo,
            unique_id="42",
            **self.prompt_values(),
        )

        expected_text = "masterpiece, @Example Artist, hero, red coat, standing, city, dramatic light, "
        self.assertEqual(clip.tokenized_text, expected_text)
        self.assertEqual(clip.encoded_tokens, {"tokens": expected_text})
        self.assertEqual(result["result"][0], [["conditioning", {"pooled_output": "pooled"}]])
        self.assertEqual(result["result"][1], expected_text)
        self.assertEqual(extra_pnginfo["anima_prompt"]["42"], {"positive": expected_text})
        self.assertEqual(result["ui"]["anima_selector_tags"][0]["artist_tags"], "by Example Artist")

    def test_clip_node_keeps_metadata_text_internal(self):
        required = self.clip_encode.INPUT_TYPES()["required"]

        self.assertNotIn("text", required)

    def test_queue_resolver_writes_random_values_and_standard_text_input(self):
        prompt = {
            "7": {
                "class_type": "AnimaPromptPlusClipEncode",
                "inputs": self.prompt_values(),
            }
        }
        workflow_node = {
            "id": 7,
            "widgets_values": ["old"] * 9,
        }
        extra_pnginfo = {"workflow": {"nodes": [workflow_node]}}

        updates = self.queue_resolver(
            prompt,
            extra_pnginfo,
            self.prompt_plus(),
        )

        expected_text = "masterpiece, @Example Artist, hero, red coat, standing, city, dramatic light, "
        self.assertEqual(prompt["7"]["inputs"]["text"], expected_text)
        self.assertEqual(workflow_node["widgets_values"], ["old"] * 9)
        self.assertEqual(updates["7"]["artist_tags"], "by Example Artist")
        self.assertNotIn("text", updates["7"])
        self.assertEqual(extra_pnginfo["anima_prompt"]["7"], {"positive": expected_text})

    def test_clip_input_is_required_at_runtime(self):
        with self.assertRaisesRegex(RuntimeError, "clip input is invalid"):
            self.clip_encode().encode_prompt(
                clip=None,
                **self.prompt_values(),
            )


if __name__ == "__main__":
    unittest.main()
