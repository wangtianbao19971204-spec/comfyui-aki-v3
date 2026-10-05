from common import *
import tempfile

gate=load_script(OLD/'release_gate.py','exact_contract_test')
with tempfile.TemporaryDirectory(dir=HERE) as tmp:
    tmp=Path(tmp);gate.DATA=tmp/'data.json';gate.PROJECTION=tmp/'projection.json';gate.BASELINE=tmp/'baseline.json'
    save(gate.DATA,{'categories':[{'prompts':[{'id':'one','prompt':'1girl','_classification':{}}]}]})
    save(gate.BASELINE,{'query_results':[{'total':1,'filter_counts':{'detail':{},'subcategory':{},'theme':{},'count':{'1girl':1}}}]})
    p=types.SimpleNamespace(read_projection=lambda x:{})
    t=types.SimpleNamespace(SUBCATEGORY_PARENTS=['parent'],semantic_themes=lambda s:[])
    checks=[]
    for name,parents,leaves,themes,dd,dp,dt,want in [
        ('equal',[],[],[],{},{},{},True),
        ('declared_missing_leaf',[],[],[],{'leaf':1},{},{},False),
        ('declared_missing_parent',[],[],[],{},{'parent':1},{},False),
        ('declared_missing_theme',[],[],[],{},{},{'theme':1},False),
        ('undeclared_leaf',[],['leaf'],[],{},{},{},False),
        ('exact_leaf',[],['leaf'],[],{'leaf':1},{},{},True),
        ('wrong_size',[],['leaf'],[],{'leaf':2},{},{},False),
    ]:
        result=gate.run_contract(p,None,t,dd,lambda *a:{'_semantic':{'subcategories':parents,'refinements':leaves,'theme_ids':themes}},dp,dt)
        assert result['passed']==want,name
        checks.append({'name':name,'passed':True})
save(HERE/'exact_contract_tests.json',{'checks':checks,'passed':True,'gate_sha256':sha(OLD/'release_gate.py')})
print('EXACT_CONTRACT_TESTS_OK',len(checks))
