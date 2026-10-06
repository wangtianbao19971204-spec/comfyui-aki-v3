"""Run the two fixture-only Gallery contracts without importing ComfyUI packages.

Requires installed pytest. All database fixtures and collection files are created
in a temporary directory; no online service or plugin __init__ is imported.
"""
from pathlib import Path
import os
import tempfile

import pytest


def main():
    tests = Path(__file__).resolve().parent
    names = ("test_weilin_tag_bridge", "test_tag_translation_runtime")
    with tempfile.TemporaryDirectory(prefix="gallery-isolated-tests-") as directory:
        root = Path(directory)
        wrapper = root / "test_gallery_contracts.py"
        lines = ["import importlib.util", "import sys"]
        for name in names:
            path = tests / (name + ".py")
            lines += [f"spec = importlib.util.spec_from_file_location({name!r}, {str(path)!r})",
                      "module = importlib.util.module_from_spec(spec)",
                      "sys.modules[spec.name] = module",
                      "spec.loader.exec_module(module)",
                      "for name, value in vars(module).items():",
                      "    if name.startswith('test_') or hasattr(value, '_pytestfixturefunction') or hasattr(value, '_fixture_function'):",
                      "        if name in globals(): raise RuntimeError('Duplicate test or fixture: ' + name)",
                      "        globals()[name] = value"]
        wrapper.write_text("\n".join(lines) + "\n", encoding="utf8")
        previous = os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        try:
            return pytest.main([str(wrapper), "-q", "-p", "no:cacheprovider",
                                "--rootdir=" + str(root), "--basetemp=" + str(root / "fixtures")])
        finally:
            if previous is None:
                os.environ.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
            else:
                os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = previous


if __name__ == "__main__":
    raise SystemExit(main())
