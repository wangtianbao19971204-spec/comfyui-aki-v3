"""Read all OOXML paragraphs, retaining line breaks, structure, and media references."""
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import Counter
import hashlib,json,zipfile

HERE=Path(__file__).resolve().parent
SOURCE=Path('C:/Users/Administrator/Desktop/（解压密码：1984）所长NovelAI个人法典（2026.9.13版，一般所长整理）')
OUT=HERE/'sources/docx'
OUT.mkdir(parents=True,exist_ok=True)
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
summary=[]
for path in sorted(SOURCE.glob('*.docx')):
    paragraphs=[]
    with zipfile.ZipFile(path) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        rels={r.attrib['Id']:dict(r.attrib) for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
        media=[{'name':i.filename,'bytes':i.file_size,'sha256':hashlib.sha256(z.read(i.filename)).hexdigest()} for i in z.infolist() if i.filename.startswith('word/media/')]
        for i,p in enumerate(root.iter(W+'p')):
            text=''.join(n.text or '' if n.tag==W+'t' else '\n' if n.tag in (W+'br',W+'cr') else '\t' if n.tag==W+'tab' else '' for n in p.iter())
            sizes=[int(n.attrib[W+'val']) for n in p.iter(W+'sz') if W+'val' in n.attrib]
            style=p.find(W+'pPr/'+W+'pStyle')
            links=[rels[n.attrib[R+'id']] for n in p.iter(W+'hyperlink') if R+'id' in n.attrib and n.attrib[R+'id'] in rels]
            images=[rels[n.attrib[R+'embed']] for n in p.iter(A+'blip') if R+'embed' in n.attrib and n.attrib[R+'embed'] in rels]
            paragraphs.append({'p':i,'text':text,'size':max(sizes,default=0),'style':style.attrib.get(W+'val') if style is not None else None,'links':links,'images':images})
    result={'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'paragraphs':paragraphs,'media':media}
    (OUT/(path.stem+'.json')).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    summary.append({'file':path.name,'sha256':result['sha256'],'paragraphs':len(paragraphs),'nonempty':sum(bool(p['text'].strip()) for p in paragraphs),'sizes':dict(Counter(p['size'] for p in paragraphs if p['text'].strip())),'media':len(media),'first_lines':[p['text'][:180] for p in paragraphs if p['text'].strip()][:12]})
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
