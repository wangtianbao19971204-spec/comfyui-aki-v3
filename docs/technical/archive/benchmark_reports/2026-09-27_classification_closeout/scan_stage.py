from common import *
import importlib.util

output=HERE/'scan_stage'; output.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('verified_scan',ROOT/'benchmark_reports/2026-09-25_full_coverage/full_coverage_scan.py')
scan=importlib.util.module_from_spec(spec);spec.loader.exec_module(scan)
scan.HERE=output;scan.DATA=HERE/'stage/data.json';scan.PROJECTION=HERE/'stage/semantic_projection.json';scan.SOURCES=HERE/'stage/prompt_selector'
sys.argv=['full_coverage_scan.py','--mode','scan','--label','verified_writeback'];scan.main()
