"""Reuse the publisher's read-only Word parser; preserve complete multiline bodies."""
from pathlib import Path
import sys,json,importlib.util
from docx import Document
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=Path('C:/Users/Administrator/Desktop/（解压密码：1984）所长NovelAI个人法典（2026.9.13版，一般所长整理）')
tools=ROOT/'benchmark_reports/2026-09-15_tag_folder_classification/repo_src/NovelAI-Tag-main/tools'
sys.path.insert(0,str(tools))
spec=importlib.util.spec_from_file_location('publisher_convert',tools/'convert.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
all_items=[]
for file in sorted(SOURCE.glob('*.docx')):
    rows=module.parse_standard_docx_items(Document(str(file)))
    for i,row in enumerate(rows):row.update(source_file=file.name,source_entry=i)
    all_items.extend(rows)
    print(file.name,len(rows),flush=True)
(HERE/'sources/docx/entries.json').write_text(json.dumps(all_items,ensure_ascii=False,indent=1),encoding='utf-8')
print('TOTAL',len(all_items))
