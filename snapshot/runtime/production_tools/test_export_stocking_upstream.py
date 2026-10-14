"""The public export cannot silently copy private resources or overwrite input."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
from unittest import mock

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
            target.write_bytes((exporter.PLUGIN/'upstream/stocking'/row['file']).read_bytes())
        (self.upstream/'LICENSE').write_bytes((exporter.PLUGIN/'upstream/LICENSE').read_bytes())
        for name in ('README.md','README.en.md'):
            (self.upstream/name).write_text('Original README\n',encoding='utf-8')
        self.showcase = self.root / 'showcase'
        self.showcase.mkdir()
        self.panel = self.showcase / 'reviewed-panel.png'
        self.panel.write_bytes(b'reviewed display asset fixture')
        self.manifest = self.root / 'showcase.json'
        self.manifest.write_text(json.dumps({'upstream_commit': 'f74c8ac0190ec43b2cdfcb13db86f35a83283311', 'files': [{
            'name': self.panel.name, 'bytes': self.panel.stat().st_size,
            'sha256': hashlib.sha256(self.panel.read_bytes()).hexdigest(),
        }]}), encoding='utf-8')
        self.patcher = mock.patch.object(exporter, 'SHOWCASE', self.manifest)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_export_is_allowlisted_and_workflow_has_no_local_assets_or_workbench(self):
        out=self.root/'export'
        (self.showcase/'private-project.json').write_text('do not publish')
        result=exporter.export(self.upstream,out,self.showcase)
        actual={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
        self.assertEqual(actual,{r['path'] for r in result['files']})
        self.assertEqual({p.name for p in (out/'integrations/comfyui/vendor').iterdir()},{'__init__.py','i18n.py'})
        self.assertFalse(any(p.startswith('stocking/') or '/assets/' in p or '/input/' in p for p in actual))
        for row in self.provenance['files']:
            self.assertEqual((out/'integrations/comfyui/upstream/stocking'/row['file']).read_bytes(),
                             (self.upstream/'stocking'/row['file']).read_bytes())
        self.assertEqual(result['dependency_mode'], 'fixed-raw-blob-copy')
        self.assertEqual(result['showcase_upstream_commit'], 'f74c8ac0190ec43b2cdfcb13db86f35a83283311')
        self.assertEqual(result['upstream_commit'], self.provenance['commit'])
        for name in ('studio_document.py', 'guide_solver.py', 'gpu_contours.py',
                     'requirements-cuda13.txt', 'tests/test_guide_solver.py',
                     'tests/test_gpu_contours.py', 'tests/test_request_contract.py',
                     'tests/test_issue3.py', 'tests/test_retention.py'):
            self.assertIn('integrations/comfyui/' + name, actual)
        self.assertFalse(result['upstream_files_modified'])
        self.assertEqual([p for p in actual if p.endswith('.png')],
                         ['integrations/comfyui/docs/images/reviewed-panel.png'])
        self.assertFalse(any('private-project' in p for p in actual))
        for row in result['files']:
            self.assertEqual(hashlib.sha256((out/row['path']).read_bytes()).hexdigest(),row['sha256'])
        flow=json.loads((out/'integrations/comfyui/examples/stocking-repair.json').read_text(encoding='utf-8'))
        self.assertEqual([n['type'] for n in flow['nodes']],['StockingTextureStudio','SaveImage','SaveImage','Note'])
        self.assertEqual(flow['nodes'][0]['widgets_values'],['{}'])
        self.assertIn('Finish any upscaling before importing the final-size image', flow['nodes'][-1]['widgets_values'][0])
        self.assertNotIn('uap_',json.dumps(flow))
        self.assertTrue((out/'integrations/comfyui/README.md').read_text(encoding='utf-8').startswith('> **AI disclosure'))
        self.assertIn('self.project.get("dark_adapt", False)',(out/'integrations/comfyui/studio.py').read_text(encoding='utf-8'))
        self.assertEqual((self.upstream/'README.md').read_text(),'Original README\n')
        self.assertIn(self.provenance['commit'], (out/'README.md').read_text(encoding='utf-8'))
        self.assertFalse((out/'stocking').exists())
        self.assertFalse((out/'.git').exists())
        for relative in ('README.md', 'integrations/comfyui/README.md'):
            readme = out/relative
            text = readme.read_text(encoding='utf-8')
            self.assertIn(self.provenance['commit'], text)
            self.assertNotIn('{{UPSTREAM_COMMIT}}', text)
            self.assertNotIn('feat/comfyui-integration', text)
            self.assertNotIn('wangtianbao19971204-spec/stocking-texture-tool', text)
            for href in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
                link = urlsplit(href)
                if link.scheme or not link.path:
                    continue
                target = (readme.parent/unquote(link.path)).resolve()
                self.assertTrue(out.resolve() in target.parents, (relative, href))
                self.assertTrue(target.exists(), (relative, href))

    def test_existing_destination_is_preserved(self):
        out=self.root/'export';out.mkdir()
        (out/'keep.txt').write_text('keep')
        with self.assertRaises(FileExistsError):exporter.export(self.upstream,out,self.showcase)
        self.assertEqual((out/'keep.txt').read_text(),'keep')
        self.assertEqual(len(list(out.iterdir())),1)

    def test_changed_upstream_is_rejected_before_export(self):
        (self.upstream/'stocking/knit.py').write_text('different')
        with self.assertRaisesRegex(ValueError,'Upstream changed'):
            exporter.export(self.upstream,self.root/'export',self.showcase)
        self.assertFalse((self.root/'export').exists())

    def test_changed_upstream_license_is_rejected_before_export(self):
        (self.upstream/'LICENSE').write_text('different license')
        with self.assertRaisesRegex(ValueError, 'Upstream license changed'):
            exporter.export(self.upstream, self.root/'export', self.showcase)
        self.assertFalse((self.root/'export').exists())

    def test_changed_panel_is_rejected_before_any_output(self):
        self.panel.write_bytes(b'unreviewed replacement')
        with self.assertRaisesRegex(ValueError, 'Showcase changed'):
            exporter.export(self.upstream, self.root/'export', self.showcase)
        self.assertFalse((self.root/'export').exists())

    def test_manifest_cannot_escape_reviewed_directory(self):
        manifest = json.loads(self.manifest.read_text())
        manifest['files'][0]['name'] = '../private.png'
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Invalid showcase filename'):
            exporter.export(self.upstream, self.root/'export', self.showcase)
        self.assertFalse((self.root/'export').exists())


if __name__=='__main__':unittest.main()
