import hashlib,json,sqlite3
from contextlib import closing
TABLES=('tag_groups','tag_subgroups','tag_tags','workbench_tag_meta','workbench_tag_folder_members','workbench_tag_revision','workbench_tag_text_revision')
def fingerprint(path):
    out={}
    with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)) as db:
        for table in TABLES:
            cols=[r[1] for r in db.execute('pragma table_info('+table+')')]
            h=hashlib.sha256();n=0
            for row in db.execute('select * from '+table+' order by '+','.join('"'+c+'"' for c in cols)):
                h.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n');n+=1
            out[table]={'rows':n,'sha256':h.hexdigest()}
    return out
