"""Build neutral, writable acceptance fixtures without copying personal libraries."""
from pathlib import Path
import hashlib
import json
import sqlite3
import struct
import zlib

report = Path(__file__).resolve().parent
out = report / 'candidate_data'
out.mkdir(exist_ok=True)
db_path = out / 'tags.db'
if db_path.exists():
    raise SystemExit('Candidate database already exists; refusing to replace it.')

types = [
    ('fragment', '提示词片段'), ('tag', '基础 Tag'), ('anima_artist', 'Anima画师'),
    ('krea_mood', 'Krea2情绪版'), ('artist_string', '画师串'), ('plan', '提示词方案'),
]
features = ['normal', 'long_body', 'no_image', 'broken_image', 'same_title', 'editable_boundary']
cards = []
queries = []
for slug, label in types:
    for number, feature in enumerate(features, 1):
        identity = f'qa-{slug}-{number:02d}'
        title = f'QA {slug} {number:02d} sky' if feature != 'same_title' else 'QA shared sky'
        body = f'blue sky, soft light, {slug}, example {number}'
        if feature == 'long_body':
            body += ', ' + ', '.join(f'neutral detail {index}' for index in range(80))
        cards.append({'id': identity, 'type': slug, 'type_label': label, 'feature': feature,
                      'title': title, 'aliases': [f'QA {slug} alias {number:02d}'],
                      'body': body, 'image': 'missing.png' if feature == 'broken_image'
                      else 'thumb_64.png' if feature not in ('no_image', 'long_body') else '',
                      'favorite': False, 'notes': '', 'usage': 'positive',
                      'editable': feature != 'editable_boundary'})
    for kind, number, query in [
        ('exact', 1, f'QA {slug} 01 sky'), ('prefix', 2, f'QA {slug} 02'),
        ('alias', 3, f'QA {slug} alias 03'), ('body', 4, f'{slug}, example 4'),
    ]:
        queries.append({'id': f'q-{slug}-{kind}', 'query': query, 'scope': slug,
                        'expected_id': f'qa-{slug}-{number:02d}', 'constraint': kind})

queries += [
    {'id': 'q-cross-name', 'query': 'QA shared sky', 'scope': 'all', 'constraint': 'six distinct IDs'},
    {'id': 'q-cross-alias', 'query': 'alias 03', 'scope': 'all', 'constraint': 'six alias hits'},
    {'id': 'q-tag-spaces', 'query': 'blue sky', 'scope': 'tag', 'constraint': 'blue_sky equivalent in Tag only'},
    {'id': 'q-empty-filter', 'query': 'no such neutral item', 'scope': 'plan', 'constraint': 'empty with clear filter'},
    {'id': 'q-long-body', 'query': 'neutral detail 79', 'scope': 'all', 'expected_id': 'qa-fragment-02',
     'constraint': 'long body remains intact'},
    {'id': 'q-mixed', 'query': '晴空 sky', 'scope': 'all', 'constraint': 'mixed input is literal'},
]
assert len(cards) == 36 and len(queries) == 30

native = []
with sqlite3.connect(db_path) as conn:
    conn.executescript('''
        CREATE TABLE tag_groups(id_index INTEGER PRIMARY KEY,name TEXT,color TEXT,create_time INTEGER,p_uuid TEXT);
        CREATE TABLE tag_subgroups(id_index INTEGER PRIMARY KEY,group_id INTEGER,name TEXT,color TEXT,create_time INTEGER,p_uuid TEXT,g_uuid TEXT);
        CREATE TABLE tag_tags(id_index INTEGER PRIMARY KEY,subgroup_id INTEGER,text TEXT,desc TEXT,color TEXT,create_time INTEGER,t_uuid TEXT,g_uuid TEXT);
        CREATE INDEX idx_tag_tags_text ON tag_tags(text);
        CREATE INDEX idx_tag_tags_create_time ON tag_tags(create_time);
    ''')
    for group in range(1, 4):
        conn.execute('INSERT INTO tag_groups VALUES (?,?,?,?,?)',
                     (group, f'QA area {group}', '', group, f'qa-area-{group}'))
        conn.execute('INSERT INTO tag_subgroups VALUES (?,?,?,?,?,?,?)',
                     (group, group, f'QA native {group}', '', group, f'qa-area-{group}', f'qa-folder-{group}'))
    for index in range(193):
        group = index % 3 + 1
        identity = f'qa-native-{index+1:03d}'
        text = 'QA193 blue_sky shared' if index in (0, 1, 2) else f'QA193 blue_sky item {index+1:03d}'
        native.append({'id': identity, 'group': group, 'text': text})
        conn.execute('INSERT INTO tag_tags VALUES (?,?,?,?,?,?,?,?)',
                     (index+1, group, text, 'neutral acceptance tag', '', index+1, identity, f'qa-folder-{group}'))
    for offset, card in enumerate(cards[6:12], 194):
        group = offset % 3 + 1
        conn.execute('INSERT INTO tag_tags VALUES (?,?,?,?,?,?,?,?)',
                     (offset, group, card['body'], card['title'], '', offset, card['id'], f'qa-folder-{group}'))

performance = []
for index in range(3000):
    length = (40, 120, 300)[index % 3]
    body = (f'blue sky neutral sample {index:04d} soft light ' * 8)[:length]
    performance.append({'id': f'qa-perf-{index:04d}', 'title': f'QA performance {index:04d}',
                        'body': body, 'image': 'thumb_64.png'})

def save_json(name, value):
    path = out / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'file': name, 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

# One deterministic local image; browser caching keeps the 3000-row fixture small.
pixel = bytes((110, 135, 207, 255))
raw = b''.join(b'\0' + pixel * 64 for _ in range(64))
def chunk(kind, payload):
    return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload) & 0xffffffff)
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 64, 64, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
(out / 'thumb_64.png').write_bytes(png)

files = [save_json('cards_36.json', cards), save_json('queries_30.json', queries),
         save_json('native_193.json', native), save_json('performance_3000.json', performance)]
files += [{'file': 'tags.db', 'bytes': db_path.stat().st_size,
           'sha256': hashlib.sha256(db_path.read_bytes()).hexdigest()},
          {'file': 'thumb_64.png', 'bytes': len(png), 'sha256': hashlib.sha256(png).hexdigest()}]
manifest = {'purpose': 'M0 neutral acceptance data; isolated from production',
            'counts': {'cards': 36, 'queries': 30, 'native_prefix_hits': 193, 'performance': 3000},
            'native_query': 'QA193', 'native_page_expected': [80, 160, 193], 'files': files}
(out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(manifest['counts'], ensure_ascii=False))
