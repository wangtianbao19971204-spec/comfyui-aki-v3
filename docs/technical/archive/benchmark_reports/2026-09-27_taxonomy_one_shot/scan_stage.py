from common import *

label=sys.argv[1];out=HERE/label;out.mkdir(exist_ok=False)
scan=load_script(OLD/'full_coverage_scan.py','one_shot_scan')
scan.HERE=out
if 'live' not in label:
    scan.SOURCES=STAGE;scan.DATA=HERE/'stage/data.json';scan.PROJECTION=HERE/'stage/semantic_projection.json'
sys.argv=['full_coverage_scan.py','--mode','scan','--label',label]
scan.main()
