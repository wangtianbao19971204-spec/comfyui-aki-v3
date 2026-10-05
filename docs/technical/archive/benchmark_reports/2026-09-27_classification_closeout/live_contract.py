from common import *
import importlib.util

path=ROOT/'benchmark_reports/2026-09-25_full_coverage/g6_current_source_contract.py'
spec=importlib.util.spec_from_file_location('verified_live_contract',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
mod.HERE=HERE
sys.argv=['g6_current_source_contract.py','--label','live_query_contract'];sys.exit(mod.main())
