from common import *
import copy, tempfile, unittest
strict=load_script(OLD/'strict_replay.py','strict_test_module')

class StrictReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=HERE);self.root=Path(self.tmp.name)
        self.registry=self.root/'benchmark_reports/2026-09-25_full_coverage/replay_amendments.json'
        self.evidence=self.root/'evidence.json';save(self.evidence,{'review':'precise'})
        self.row={'id':'a','retain_nodes':['old','unrelated']}
        self.ledger=self.root/'ledger.json';save(self.ledger,self.row)
        self.entry={'round':114,'id':'a','prompt_sha256':hashlib.sha256(b'body').hexdigest(),
                    'evidence':{'path':'evidence.json','sha256':sha(self.evidence)},
                    'ledger':{'path':'ledger.json','sha256':sha(self.ledger)},
                    'changes':[{'field':'retain_nodes','target':'old','old':True,'new':False},
                               {'field':'remove_nodes','target':'old','old':False,'new':True}]}
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self):save(self.registry,{'schema':'precise-replay-amendments/v1','entries':[self.entry]})
    def load(self):return strict.load_amendments(self.root,self.registry)
    def run_fixture(self,leaves,missing=False):
        data=self.root/'data.json';save(data,{'categories':[{'prompts':[] if missing else [{'id':'a','prompt':'body'}]}]})
        gate=types.SimpleNamespace(ROOT=self.root,DATA=data,PROJECTION=self.root/'p',ledger_rows=lambda:[(114,'ledger.json',self.row)])
        return strict.run_replay(gate,types.SimpleNamespace(read_projection=lambda p:{}),None,None,152,lambda *a:{'_semantic':{'subcategories':[],'refinements':leaves}})
    def test_preserves_unrelated_assertion(self):
        expected,n=strict.apply_amendment(114,self.row,'body',self.load())
        self.assertEqual(expected['retain_nodes'],{'unrelated'});self.assertEqual(n,2)
    def test_different_round_not_exempt(self):
        expected,n=strict.apply_amendment(115,self.row,'body',self.load())
        self.assertEqual(expected['retain_nodes'],{'old','unrelated'});self.assertEqual(n,0)
    def test_same_round_unrelated_failure_is_blocking(self):self.assertEqual(self.run_fixture([])['failures'],1)
    def test_replacement_assertion_evaluated(self):self.assertEqual(self.run_fixture(['unrelated','old'])['failures'],1)
    def test_correct_replacement_passes(self):self.assertEqual(self.run_fixture(['unrelated'])['failures'],0)
    def test_missing_record_fails(self):self.assertEqual(self.run_fixture([],True)['failures'],1)
    def test_evidence_tamper(self):
        self.evidence.write_text('tamper');self.assertRaises(ValueError,self.load)
    def test_missing_evidence(self):
        self.evidence.unlink();self.assertRaises(FileNotFoundError,self.load)
    def test_ledger_tamper(self):
        self.ledger.write_text('tamper');self.assertRaises(ValueError,self.load)
    def test_body_tamper(self):self.assertRaises(ValueError,strict.apply_amendment,114,self.row,'tamper',self.load())
    def test_wrong_original_membership(self):self.assertRaises(ValueError,strict.apply_amendment,114,{'id':'a'},'body',self.load())
    def test_duplicate_assertion(self):
        self.entry['changes'].append(self.entry['changes'][0]);self.write();self.assertRaises(ValueError,self.load)
    def test_unknown_field(self):
        self.entry['changes'][0]['field']='waive_round';self.write();self.assertRaises(ValueError,self.load)
    def test_non_boolean(self):
        self.entry['changes'][0]['old']='true';self.write();self.assertRaises(ValueError,self.load)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StrictReplayTests))
    save(HERE/'strict_gate_tests.json',{'checks':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful(),'strict_sha256':sha(OLD/'strict_replay.py')})
    sys.exit(0 if result.wasSuccessful() else 1)
