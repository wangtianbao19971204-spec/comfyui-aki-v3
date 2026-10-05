"""Local batch review using the workspace's existing Character LoRA Forge checks."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from PIL import Image

parser=argparse.ArgumentParser()
parser.add_argument('--input',type=Path,required=True,help='Folder of PNG candidates; originals are preserved')
parser.add_argument('--output',type=Path,required=True,help='New review folder, outside the input folder')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'character_lora_forge'))
from character_forge.scoring import technical_score
from character_forge.report import write_review_html

source=args.input.resolve();dest=args.output.resolve()
if not source.is_dir():raise NotADirectoryError(source)
if dest==source or source in dest.parents:raise ValueError('Review output must be outside the candidate input folder')
if dest.exists():raise FileExistsError('Use a new output directory to preserve prior reviews')
paths=sorted(source.glob('*.png'))
if not paths:raise ValueError('No PNG candidates found')
(dest/'images').mkdir(parents=True)
scores=[]
for p in paths:
    target=dest/'images'/p.name;shutil.copy2(p,target)
    with Image.open(p) as im:
        width,height=im.size
        try:prompt=json.loads(im.info.get('prompt','{}'))
        except (ValueError,TypeError):prompt={}
    technical=technical_score(p,width,height)
    params=[dict(node_id=nid,**n.get('inputs',{})) for nid,n in prompt.items() if n.get('class_type') in ('KSampler','KSamplerAdvanced')]
    scores.append(dict(job_id=p.name,candidate=str(target),source=str(p),final_score=technical['technical_total'],technical=technical,sampling=params))
(dest/'scores.json').write_text(json.dumps(scores,ensure_ascii=False,indent=2),encoding='utf8')
page=write_review_html(dest,scores,'批量候选')
html=page.read_text(encoding='utf8').replace('黄金图初筛','技术检查').replace('按总分排序；训练前仍应检查脸、成年感、头身比、发型、服装结构和双枪。','技术分不代表内容正确性。逐张检查主体、局部修改、边缘和细节，勾选后导出文件名清单。原图与训练集不会被移动。')
html=html.replace('</header>','<button id="export-selection">导出已选 CSV</button></header>')
html=html.replace('</body>', '''<script>
document.querySelectorAll('.card .body').forEach(card=>{const label=document.createElement('label');const check=document.createElement('input');check.type='checkbox';label.append(check,document.createTextNode(' 保留此图'));card.append(label);});
document.getElementById('export-selection').onclick=()=>{const names=Array.from(document.querySelectorAll('.card')).filter(card=>card.querySelector('input').checked).map(card=>card.querySelector('h3').textContent);const csv='\\ufefffilename\\r\\n'+names.map(name=>'"'+name.replaceAll('"','""')+'"').join('\\r\\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='selected.csv';a.click();URL.revokeObjectURL(url);};
</script></body>''')
page.write_text(html,encoding='utf8')
print(page)
