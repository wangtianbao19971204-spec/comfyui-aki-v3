import copy
import importlib.util
import json
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / 'snapshot/runtime/production_tools/simplify_anima_control.py'
spec = importlib.util.spec_from_file_location('simplify_anima_control', PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class AnimaControlWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.before = json.loads((REPO/'tests/fixtures/anima_control_before.json').read_text(encoding='utf-8'))

    def test_compact_graph_preserves_user_inputs_and_other_nodes(self):
        original = copy.deepcopy(self.before)
        after = migration.migrate(self.before)
        self.assertEqual(self.before, original)
        self.assertEqual(after['nodes'][-1], self.before['nodes'][-1])
        pose, light, advanced = after['definitions']['subgraphs']
        self.assertEqual(len(pose['nodes']), 9)
        self.assertEqual(len(advanced['nodes']), 8)
        self.assertEqual(len([n for n in pose['nodes'] if n['type']=='AIO_Preprocessor']), 1)
        pre = next(n for n in pose['nodes'] if n['type']=='AIO_Preprocessor')
        self.assertEqual(pre['widgets_values'], ['DepthAnythingV2Preprocessor',1024])
        old_nodes = {n['id']: n for g in self.before['definitions']['subgraphs'] for n in g['nodes']}
        for g in (pose, light, advanced):
            for n in g['nodes']:
                old = old_nodes.get(n['id'])
                if old and old['type'] == n['type']:
                    self.assertEqual(n.get('widgets_values'),old.get('widgets_values'),n['type'])
        self.assertEqual(next(n for n in pose['nodes'] if n['type']=='AnimaLLLiteApply')['widgets_values'],[1,0,1])
        self.assertEqual(next(n for n in light['nodes'] if n['type']=='AnimaLLLiteApply')['widgets_values'],[0.94,0,1])
        self.assertTrue(all(n['mode']==2 for n in after['nodes'][:2]))
        self.assertEqual(migration.migrate(after),after)

    def test_port_references_and_types_are_consistent(self):
        after = migration.migrate(self.before)
        all_ids = [n['id'] for g in [after,*after['definitions']['subgraphs']] for n in g['nodes']]
        self.assertEqual(len(all_ids),len(set(all_ids)))
        for g in after['definitions']['subgraphs']:
            nodes = {n['id']:n for n in g['nodes']}
            for link in g['links']:
                start = g['inputs'][link['origin_slot']] if link['origin_id']==-10 else nodes[link['origin_id']]['outputs'][link['origin_slot']]
                end = g['outputs'][link['target_slot']] if link['target_id']==-20 else nodes[link['target_id']]['inputs'][link['target_slot']]
                self.assertEqual(start['type'],link['type'])
                self.assertEqual(end['type'],link['type'])
                self.assertIn(link['id'],start.get('links',start.get('linkIds',[])))
                self.assertIn(link['id'],end.get('linkIds',[end.get('link')]))

    def test_custom_preprocessor_settings_require_review(self):
        pose = self.before['definitions']['subgraphs'][0]
        next(n for n in pose['nodes'] if n['type']=='DepthAnythingV2Preprocessor')['widgets_values'][0]='custom.pth'
        with self.assertRaisesRegex(ValueError,'Custom preprocessing'):
            migration.migrate(self.before)

    def test_solid_mask_ports_match_current_native_input_order(self):
        advanced = migration.migrate(self.before)['definitions']['subgraphs'][-1]
        solid = next(n for n in advanced['nodes'] if n['type']=='SolidMask')
        self.assertEqual([p['name'] for p in solid['inputs']], ['value','width','height'])
        self.assertIsNone(solid['inputs'][0]['link'])
        self.assertEqual([link['target_slot'] for link in advanced['links'] if link['target_id']==solid['id']], [1,2])

    def test_other_anima_branch_is_not_migrated(self):
        self.before['extra']['uap_workbench']={'branches':[{'id':'a29','nodeIds':[]}]}
        self.assertEqual(migration.migrate(self.before),self.before)

    def test_all_four_sources_are_idempotent_and_keep_legacy_anima(self):
        for base in ('ComfyUI/user/default/workflows','production_tools/templates'):
            for filename in migration.FILES:
                data=json.loads((REPO/'snapshot/runtime'/base/filename).read_text(encoding='utf-8'))
                self.assertEqual(migration.migrate(data),data)
                owners=[n for n in data['nodes'] if n.get('properties',{}).get('uap_native_lllite')]
                self.assertEqual(len(owners),2)
                if filename.startswith('UAP'):
                    a1=next(b for b in data['extra']['uap_workbench']['branches'] if b['id']=='a1')
                    self.assertFalse(any(n['id'] in a1['nodeIds'] for n in owners))


if __name__ == '__main__': unittest.main()
