from update_common import *
import importlib.util
label=sys.argv[1];out=HERE/label;out.mkdir(exist_ok=False)
path=ROOT/'benchmark_reports/2026-09-25_full_coverage/full_coverage_scan.py'
spec=importlib.util.spec_from_file_location('update_scan',path);scan=importlib.util.module_from_spec(spec);spec.loader.exec_module(scan)
scan.HERE=out
if 'live' not in label:scan.DATA=STAGE/'data.json';scan.PROJECTION=STAGE/'semantic_projection.json';scan.SOURCES=STAGE/'prompt_selector'
sys.argv=['full_coverage_scan.py','--mode','scan','--label',label];scan.main()
