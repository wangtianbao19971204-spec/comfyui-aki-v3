"""把近似名候选按性质归类，方便人工判定。"""
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = []
for line in (HERE / "近似名候选_20260919.md").read_text(encoding="utf-8").splitlines():
    if line.startswith("|") and "官方名" not in line and "---" not in line:
        p = [x.strip() for x in line.strip("|").split("|")]
        if len(p) >= 4:
            rows.append(p)

WRAP = re.compile(r"^\s*[{[]|::")
kind = Counter()
groups = {}
for tx, head, cand, pc in rows:
    if WRAP.search(head):
        k = "权重/括号包裹"
    elif re.search(r"[a-z]\)\s*\d", head) or re.search(r"[a-zA-Z]\(", head):
        k = "缺空格 / 缺逗号"
    elif head.lower() != head or "'" in head:
        k = "大小写 / 撇号"
    else:
        k = "其它（疑似拼写错）"
    kind[k] += 1
    groups.setdefault(k, []).append((head, cand.strip("`"), pc))

print("候选总数:", len(rows))
for k, v in kind.most_common():
    print(f"   {k:<18} {v}")
print()
for k in groups:
    print(f"--- {k} 样例 ---")
    for head, cand, pc in groups[k][:8]:
        print(f"   {head[:40]:<42} ≈ {cand[:30]:<32} (作品量 {pc})")
    print()
