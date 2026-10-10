"""The public export cannot silently copy private resources or overwrite input."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import export_stocking_upstream as exporter


class ExportContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.upstream=self.root/'upstream'
        self.upstream.mkdir()
        self.provenance=json.loads((exporter.PLUGIN/'UPSTREAM.json').read_text(encoding='utf-8'))
        for row in self.provenance['files']:
            target=self.upstream/'stocking'/row['file']
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((exporter.PLUGIN/'vendor'/row['file']).read_bytes())
        for name in ('README.md','README.en.md'):
            (self.upstream/name).write_text('Original README\n',encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_export_is_allowlisted_and_workflow_has_no_local_assets_or_workbench(self):
        out=self.root/'export'
        result=exporter.export(self.upstream,out)
        actual={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
        self.assertEqual(actual,{r['path'] for r in result['files']})
        self.assertEqual({p.name for p in (out/'integrations/comfyui/vendor').iterdir()},{'__init__.py','i18n.py'})
        self.assertFalse(any(p.startswith('stocking/') or '/assets/' in p or '/input/' in p for p in actual))
        for row in result['files']:
            self.assertEqual(hashlib.sha256((out/row['path']).read_bytes()).hexdigest(),row['sha256'])
        flow=json.loads((out/'integrations/comfyui/examples/stocking-repair.json').read_text(encoding='utf-8'))
        self.assertEqual([n['type'] for n in flow['nodes']],['StockingTextureStudio','SaveImage','SaveImage','Note'])
        self.assertEqual(flow['nodes'][0]['widgets_values'],['{}'])
        self.assertNotIn('uap_',json.dumps(flow))
        self.assertTrue((out/'integrations/comfyui/README.md').read_text(encoding='utf-8').startswith('> **AI disclosure'))
        self.assertIn('self.project.get("dark_adapt", False)',(out/'integrations/comfyui/studio.py').read_text(encoding='utf-8'))
        self.assertEqual((self.upstream/'README.md').read_text(),'Original README\n')
        for name in ('README.md', 'README.en.md'):
            # Public presentation must preserve the complete original README.
            self.assertTrue((out/name).read_text(encoding='utf-8').endswith('Original README\n'))

    def test_existing_destination_is_preserved(self):
        out=self.root/'export';out.mkdir()
        (out/'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):exporter.export(self.upstream,out)
        self.assertEqual((out/'keep.txt').read_text(),'keep')
        self.assertEqual(len(list(out.iterdir())),1)

    def test_changed_upstream_is_rejected_before_export(self):
        (self.upstream/'stocking/knit.py').write_text('different')
        with self.assertRaisesRegex(ValueError,'Upstream changed'):
            exporter.export(self.upstream,self.root/'export')
        self.assertFalse((self.root/'export').exists())


if __name__=='__main__':unittest.main()
