"""Exercise the real synchronization reader against the API filename contract."""
import ast
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / 'snapshot/runtime/ComfyUI/custom_nodes/vnccs-utils'


def load_sync_reader():
    api = ast.parse((PLUGIN / 'api/pose_library.py').read_text(encoding='utf8'))
    node = ast.parse((PLUGIN / 'nodes/pose_studio.py').read_text(encoding='utf8'))
    pattern = next(n for n in api.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SAFE_ID_RE' for t in n.targets))
    sanitizer = next(n for n in api.body if isinstance(n, ast.FunctionDef) and n.name == 'sanitize_node_id')
    reader = next(n for n in ast.walk(node) if isinstance(n, ast.FunctionDef) and n.name == '_wait_for_frontend_sync')
    namespace = {'re': re, 'os': os, 'json': json}
    exec(compile(ast.Module(body=[pattern, sanitizer, reader], type_ignores=[]), '<sync-reader>', 'exec'), namespace)
    return namespace


class PoseSyncTests(unittest.TestCase):
    def test_nested_execution_id_uses_upload_filename(self):
        scope = load_sync_reader()
        with tempfile.TemporaryDirectory() as directory:
            folders = types.SimpleNamespace(get_temp_directory=lambda: directory)
            for node_id in ('111001', '1067:111001', '1067:44:111001'):
                with self.subTest(node_id=node_id), patch.dict(sys.modules, folder_paths=folders):
                    target = Path(directory) / f"vnccs_debug_{scope['sanitize_node_id'](node_id)}.json"
                    payload = {'node_id': node_id, 'captured_images': ['test-capture']}
                    target.write_text(json.dumps(payload), encoding='utf8')
                    result = scope['_wait_for_frontend_sync'](None, node_id, time.time(), timeout=0.1)
                    self.assertEqual(result, payload)
                    self.assertFalse(target.exists())

    def test_old_capture_is_not_used(self):
        scope = load_sync_reader()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'vnccs_debug_1067_111001.json'
            target.write_text('{}', encoding='utf8')
            os.utime(target, (1, 1))
            with patch.dict(sys.modules, folder_paths=types.SimpleNamespace(get_temp_directory=lambda: directory)):
                self.assertIsNone(scope['_wait_for_frontend_sync'](None, '1067:111001', time.time(), timeout=0.01))
            self.assertTrue(target.exists())


if __name__ == '__main__':
    unittest.main()
