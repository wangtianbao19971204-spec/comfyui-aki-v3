import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import snapshot


class RegisteredSourcesTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'production_tools').mkdir()
        (root / 'production_tools/profiles.json').write_text('{"production": []}')
        (root / 'anima_lora_forge').mkdir()
        (root / 'anima_lora_forge/forge.py').write_text('# maintained source\n')
        (root / 'anima_lora_forge/config.json').write_text('{}')
        records = [{"source": name, "path": 'runtime/' + name, "kind": 'file', "sha256": '0' * 64}
                   for name in ['anima_lora_forge/forge.py', 'anima_lora_forge/config.json']]
        manifest = root / 'registered.json'
        manifest.write_text(json.dumps({"files": records}))
        return manifest

    def test_registered_extension_sources_survive_capture_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.fixture(root)
            selected, omitted, plugins = snapshot.selected_sources(root, manifest)
            self.assertIn('anima_lora_forge/forge.py', selected)
            self.assertNotIn('anima_lora_forge/config.json', selected)
            self.assertIn('anima_lora_forge/config.json', [x['path'] for x in omitted])
            self.assertEqual(plugins, [])

    def test_registered_missing_source_not_resurrected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.fixture(root)
            (root / 'anima_lora_forge/forge.py').unlink()
            selected, _, _ = snapshot.selected_sources(root, manifest)
            self.assertNotIn('anima_lora_forge/forge.py', selected)

    def test_registered_path_escape_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.fixture(root)
            data = json.loads(manifest.read_text())
            data['files'][0]['source'] = '../outside.py'
            manifest.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                snapshot.selected_sources(root, manifest)


if __name__ == '__main__':
    unittest.main()
