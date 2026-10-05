from common import *
import ast
generator=ROOT/'benchmark_reports/2026-09-25_taxonomy_convergence/reviewer_backend_v3/verify_g6.py'
tree=ast.parse(generator.read_text(encoding='utf-8'))
function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_73_fixture')
ns={'Path':Path,'ROOT':ROOT,'CAND':STAGE,'prod':STAGE,'sha':sha,'types':types,'importlib':importlib,'sys':sys}
exec(compile(ast.Module([function],type_ignores=[]),str(generator),'exec'),ns)
result=ns['run_73_fixture'](STAGE)
assert result['count']==73
save(HERE/'stage_query_fixtures.json',dict(result,passed=True,source_sha256=sha(STAGE/'semantic_refinements.py')))
print('STAGE_QUERY_FIXTURES_OK',result['count'])
