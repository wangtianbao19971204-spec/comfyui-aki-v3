import ast
import os
import re
import tempfile
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class FolderPathsStub:
    @staticmethod
    def get_folder_paths(_):
        return []


class LoraDirectoryCompatTests(unittest.TestCase):
    def test_supported_base_model_profiles_are_allowlisted(self):
        path = PLUGIN_DIR / "anima_lora_api.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        selected_nodes = []
        symbol_names = {
            "SUPPORTED_LORA_BASE_MODELS",
            "LORA_BASE_MODEL_ALIASES",
        }
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in symbol_names
                for target in node.targets
            ):
                selected_nodes.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name in {
                "normalize_lora_profile_key",
                "resolve_lora_base_model",
            }:
                selected_nodes.append(node)
        namespace = {}
        exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(path), "exec"), namespace)

        resolve = namespace["resolve_lora_base_model"]
        self.assertEqual(resolve("Anima"), "Anima")
        self.assertEqual(resolve("krea2"), "Krea 2")
        self.assertEqual(resolve("Krea 2"), "Krea 2")
        self.assertEqual(resolve("krea-2"), "Krea 2")
        with self.assertRaises(ValueError):
            resolve("flux")

    def test_public_search_results_keep_only_selected_base_model_versions(self):
        filter_items = load_functions(
            PLUGIN_DIR / "anima_lora_api.py",
            {"_filter_civitai_items_by_base_model"},
            {},
        )["_filter_civitai_items_by_base_model"]
        result = filter_items({
            "items": [{
                "id": 123,
                "modelVersions": [
                    {"id": 1, "baseModel": "Anima"},
                    {"id": 2, "baseModel": "Krea 2"},
                ],
            }],
            "metadata": {"nextCursor": "next"},
        }, "Krea 2")

        self.assertEqual([version["id"] for version in result["items"][0]["modelVersions"]], [2])
        self.assertEqual(result["metadata"]["baseModel"], "Krea 2")

    def test_krea_character_search_uses_category_aware_index_before_public_api(self):
        meili_calls = []
        public_calls = []
        namespace = load_functions(
            PLUGIN_DIR / "anima_lora_api.py",
            {"_search_civitai_loras_uncached"},
            {
                "resolve_lora_base_model": lambda value: value,
                "load_config": lambda: {"civitai_api_key": ""},
                "_search_civitai_loras_meili": lambda *args: (
                    meili_calls.append(args)
                    or {
                        "items": [{"id": 1, "_category": args[2]}],
                        "metadata": {"source": "meili"},
                    }
                ),
                "_read_json_url": lambda *args, **kwargs: public_calls.append((args, kwargs)),
                "_public_api_sort_for_civitai_sort": lambda value: value,
                "_filter_civitai_items_by_base_model": lambda result, _base: result,
                "_compact_public_search_result": lambda result: result,
                "CIVITAI_API_BASE": "https://example.invalid/api/v1",
                "CIVITAI_API_FALLBACK_BASE": "https://fallback.invalid/api/v1",
                "urllib": __import__("urllib"),
            },
        )

        result = namespace["_search_civitai_loras_uncached"](
            category="character",
            base_model="Krea 2",
        )

        self.assertEqual(result["metadata"]["source"], "meili")
        self.assertEqual(meili_calls[0][2], "character")
        self.assertEqual(meili_calls[0][6], "Krea 2")
        self.assertEqual(public_calls, [])

    def test_category_network_failure_never_falls_back_to_unverified_public_tags(self):
        public_calls = []
        namespace = load_functions(
            PLUGIN_DIR / "anima_lora_api.py",
            {"_search_civitai_loras_uncached"},
            {
                "resolve_lora_base_model": lambda value: value,
                "load_config": lambda: {"civitai_api_key": ""},
                "_search_civitai_loras_meili": lambda *args: None,
                "_read_json_url": lambda *args, **kwargs: public_calls.append((args, kwargs)),
                "_public_api_sort_for_civitai_sort": lambda value: value,
                "_filter_civitai_items_by_base_model": lambda result, _base: result,
                "_compact_public_search_result": lambda result: result,
                "CIVITAI_API_BASE": "https://example.invalid/api/v1",
                "CIVITAI_API_FALLBACK_BASE": "https://fallback.invalid/api/v1",
                "urllib": __import__("urllib"),
            },
        )

        result = namespace["_search_civitai_loras_uncached"](
            category="poses",
            base_model="Anima",
        )

        self.assertIsNone(result)
        self.assertEqual(public_calls, [])

    def test_meili_character_results_reject_wrong_categories_and_obvious_styles(self):
        namespace = load_functions(
            PLUGIN_DIR / "anima_lora_api.py",
            {
                "_is_obvious_style_named_character_hit",
                "_search_civitai_loras_meili",
            },
            {
                "re": re,
                "_OBVIOUS_STYLE_NAME_RE": re.compile(
                    r"(?:\bstyle\s*[-_/ ]*\s*lora\b|(?:^|[\s|:/\-\[(])style(?:$|[\s|:/\-\])]))",
                    re.IGNORECASE,
                ),
                "_quote_meili_value": lambda value: repr(value),
                "_meili_sort_for_civitai_sort": lambda _sort: ("models_v9", []),
                "_post_json_url": lambda *_args, **_kwargs: {
                    "results": [{
                        "hits": [
                            {
                                "id": 1,
                                "name": "Named Character",
                                "category": {"name": "character"},
                            },
                            {
                                "id": 2,
                                "name": "Artist Style LoRA",
                                "category": {"name": "character"},
                            },
                            {
                                "id": 3,
                                "name": "Wrong category",
                                "category": {"name": "style"},
                            },
                        ],
                        "estimatedTotalHits": 3,
                    }]
                },
                "_convert_meili_hit": lambda hit, _base: {
                    "id": hit["id"],
                    "_category": hit["category"]["name"],
                },
                "CIVITAI_SEARCH_HOST": "https://search.invalid",
                "CIVITAI_SEARCH_CLIENT_KEY": "test-key",
            },
        )

        result = namespace["_search_civitai_loras_meili"](
            "",
            "",
            "character",
            "Relevancy",
            "",
            40,
            "Krea 2",
        )

        self.assertEqual([item["id"] for item in result["items"]], [1])
        self.assertEqual(result["metadata"]["categoryRejectedCount"], 1)
        self.assertEqual(result["metadata"]["semanticRejectedCount"], 1)

    def test_physical_files_are_deduplicated_across_nested_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            default_root = Path(tmp) / "loras"
            custom_root = default_root / "anima"
            custom_root.mkdir(parents=True)
            model_path = custom_root / "character" / "example.safetensors"
            model_path.parent.mkdir()
            model_path.write_bytes(b"model")

            namespace = load_functions(
                PLUGIN_DIR / "nodes.py",
                {"scan_loras_with_info"},
                {
                    "os": os,
                    "get_lora_root_infos": lambda: [
                        {"path": str(custom_root), "source": "custom"},
                        {"path": str(default_root), "source": "default"},
                    ],
                    "scan_loras_in_directory": lambda root: [
                        str(path.relative_to(root)).replace(os.sep, "/")
                        for path in Path(root).rglob("*.safetensors")
                    ],
                },
            )

            items = namespace["scan_loras_with_info"]()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["source"], "custom")
            self.assertEqual(items[0]["filename"], "character/example.safetensors")

    def test_lora_manager_metadata_exposes_civitai_identity(self):
        normalize = load_functions(
            PLUGIN_DIR / "nodes.py",
            {"normalize_lora_metadata"},
            {},
        )["normalize_lora_metadata"]

        metadata, source = normalize({
            "model_name": "Example model",
            "civitai": {
                "id": 456,
                "modelId": 123,
                "name": "Version A",
                "trainedWords": ["example"],
                "files": [],
                "images": [],
                "model": {"name": "Example model"},
                "creator": {"username": "author"},
            },
        })

        self.assertEqual(source, "lora_manager")
        self.assertEqual(metadata["version"]["id"], 456)
        self.assertEqual(metadata["model"]["id"], 123)
        self.assertEqual(metadata["model"]["creator"]["username"], "author")

    def test_download_subfolder_is_relative_and_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            namespace = load_functions(
                PLUGIN_DIR / "anima_lora_api.py",
                {
                    "normalize_lora_profile_key",
                    "normalize_lora_subfolder",
                    "get_lora_save_dir",
                },
                {
                    "os": os,
                    "re": re,
                    "load_config": lambda: {
                        "custom_lora_dir": tmp,
                        "krea2_lora_dir": os.path.join(tmp, "krea2"),
                    },
                    "LORA_BASE_MODEL_ALIASES": {
                        "anima": "anima",
                        "krea2": "krea2",
                        "krea 2": "krea2",
                        "krea-2": "krea2",
                    },
                    "SUPPORTED_LORA_BASE_MODELS": {
                        "anima": "Anima",
                        "krea2": "Krea 2",
                    },
                    "folder_paths": FolderPathsStub(),
                    "__file__": str(PLUGIN_DIR / "anima_lora_api.py"),
                },
            )

            save_dir = namespace["get_lora_save_dir"]("character/example")
            self.assertEqual(
                os.path.normcase(save_dir),
                os.path.normcase(os.path.join(tmp, "character", "example")),
            )
            self.assertTrue(os.path.isdir(save_dir))
            os.makedirs(os.path.join(tmp, "krea2"), exist_ok=True)
            krea2_save_dir = namespace["get_lora_save_dir"]("style", "Krea 2")
            self.assertEqual(
                os.path.normcase(krea2_save_dir),
                os.path.normcase(os.path.join(tmp, "krea2", "style")),
            )
            with self.assertRaises(ValueError):
                namespace["get_lora_save_dir"]("../outside")
            with self.assertRaises(ValueError):
                namespace["get_lora_save_dir"]("C:/outside")
            with self.assertRaises(ValueError):
                namespace["get_lora_save_dir"]("/outside")
            with self.assertRaises(ValueError):
                namespace["get_lora_save_dir"]("\\\\server\\share")


if __name__ == "__main__":
    unittest.main()
