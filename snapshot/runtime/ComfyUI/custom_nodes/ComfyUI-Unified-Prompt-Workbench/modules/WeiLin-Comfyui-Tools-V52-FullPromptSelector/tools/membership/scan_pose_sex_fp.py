"""第六轮：量两个具体误判的规模。
  A) 成人›性交 里的 `from behind`：到底是体位还是镜头角度？
  B) 动作›姿态 里的 `on back / on stomach / on side`：前面是不是身体部位词（mole on stomach）？
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402

REPORT = HERE / "体位镜头误判_20260919.md"
BODY_BEFORE = ("mole", "bruise", "tattoo", "mark", "marks", "scar", "scars", "stain",
               "stains", "birthmark", "piercing", "bandage", "bandaid", "cum", "hickey",
               "sunburn", "burn", "wound", "cut", "cuts", "spot", "spots", "dirt")


def main() -> int:
    con = sqlite3.connect(str(DB))
    rows = con.execute("select t_uuid, text from tag_tags").fetchall()
    meta = {}
    for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
        try:
            meta[u] = json.loads(b)
        except Exception:
            meta[u] = {}

    sex_only = []      # 只靠 from behind 进 成人›性交 的
    sex_words = re.compile(r"(?<![a-z0-9])(sex|vaginal|penetration|cowgirl position|"
                           r"mating press|missionary|straddling|spitroast)(?![a-z0-9])", re.I)
    fb = re.compile(r"(?<![a-z0-9])from[ _]+behind(?![a-z0-9])", re.I)
    pose_words = re.compile(r"(?<![a-z0-9])(on back|on stomach|on side)(?![a-z0-9])", re.I)
    body_ctx = []

    for u, text in rows:
        d = meta.get(u)
        if d is None:
            continue
        body = denoise(text)
        if "成人›性交" in (d.get("themes") or []) and fb.search(body) and not sex_words.search(body):
            sex_only.append((body[:66], md5(u.encode()).hexdigest()))
        if "动作›姿态" in (d.get("themes") or []):
            for m in pose_words.finditer(body):
                prev = re.search(r"([a-z0-9']+)[ _]+$", body[:m.start()])
                if prev and prev.group(1) in BODY_BEFORE:
                    body_ctx.append((body[:66], m.group(0), prev.group(1), md5(u.encode()).hexdigest()))
                    break

    print(f"A) 只靠 from behind 进 性交 的：{len(sex_only)}")
    for t, _h in sorted(sex_only, key=lambda x: x[1])[:14]:
        print("   ", t)
    print(f"B) 姿态里 on back/stomach/side 前面是身体部位词的：{len(body_ctx)}")
    for t, hit, prev, _h in sorted(body_ctx, key=lambda x: x[3])[:14]:
        print(f"    {prev}+{hit}  ← {t}")

    L = ["# 体位 / 镜头、姿态 / 身体部位 误判", "",
         f"## A. 只靠 `from behind` 进「成人›性交」（{len(sex_only)} 条）", "",
         "这些多半是镜头角度 `from behind`，不是体位：", ""]
    for t, _h in sorted(sex_only, key=lambda x: x[1])[:40]:
        L.append(f"- {t}")
    L += ["", f"## B. 「动作›姿态」里 on back/stomach/side 前是身体部位词（{len(body_ctx)} 条）", ""]
    for t, hit, prev, _h in sorted(body_ctx, key=lambda x: x[3])[:40]:
        L.append(f"- `{prev} + {hit}` ← {t}")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"落盘：{REPORT.name}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
