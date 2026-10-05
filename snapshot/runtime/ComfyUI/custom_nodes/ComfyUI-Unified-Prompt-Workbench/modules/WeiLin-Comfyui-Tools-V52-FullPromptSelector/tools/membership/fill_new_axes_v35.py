"""第 35 轮：新开 动作›行为 / 画面 系列 / 生物，并把剩下的干净分组接完。

按章节精确取用（sex_acts 的 Ageplay / Body Types / Gender Play / Mutilation 四段是"相关词"，
会带进 loli/shota/giantess/amputee，**不接**）。

用法： python fill_new_axes_v35.py [--write]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
import rebuild_action_scene_v11 as V11  # noqa: E402
from rebuild_action_scene_v11 import phrase_pattern  # noqa: E402
import rebuild_action_scene_v12 as V12  # noqa: E402

V11.MIN_SINGLE_TOKEN = 3
OUT = HERE / "全库_面与主题_v35_20260919.jsonl"
REPORT = HERE / "新轴与补漏_v35_20260919.md"
SAMPLE = 12
FACETS = {"人物数量›在场人数", "外貌›面部", "外貌›发型", "外貌›身体",
          "成人›露出", "状态›半脱"}

# 命中词后面跟这些 → 它是在说印花/纹理，不是在说那个东西本身
PRINTY = ("print", "prints", "pattern", "patterns", "patterned", "texture",
          "motif", "decal", "sticker", "wallpaper")
BODY_PARTS = ("armpit", "neck", "palm", "wrist", "ankle", "knee", "elbow",
              "forehead", "cheek", "chin", "finger", "toe", "leg", "arm")
# 命中词后面跟这些 → 它是在修饰某个物件/部位
OBJECTY = ("pipe", "band", "ring", "dress", "outfit", "skirt", "shirt", "coat",
           "ear", "ears", "tail", "horns", "girl", "boy", "pose", "cutout",
           "fluff", "head", "hat", "cap", "costume", "plush", "stuffed")


def rejected(label: str, body: str, m) -> bool:
    """按轴做后置过滤：命中词是不是在修饰别的东西。"""
    nxt = re.match(r"[ _]+([a-z0-9']+)", body[m.end():m.end() + 22])
    prev = re.search(r"([a-z0-9']+)[ _]+$", body[max(0, m.start() - 26):m.start()])
    hit = m.group(0).lower().replace("_", " ")
    if label.startswith("生物›") or label in ("画面›打光", "画面›配色", "画面›图案",
                                            "动作›行为"):
        # ① 命中词自己就以 print/pattern 结尾（floral print）
        # ② 后面跟着 print/pattern（tiger_print）
        if hit.split()[-1] in PRINTY or (nxt and nxt.group(1) in PRINTY):
            return True
        if nxt and nxt.group(1) in OBJECTY:
            return True
    if label.startswith("生物›") and prev and prev.group(1) in (
            "holding", "stuffed", "plush", "toy", "fake", "print", "pattern"):
        return True
    if label == "画面›构图" and prev and prev.group(1).endswith("ing"):
        return True
    if label == "画面›技法" and prev and prev.group(1) in BODY_PARTS:
        return True
    return False

# 轴 → [(分组, 包含章节关键词 or None, 排除章节关键词 or ())]
PLAN = {
    "动作›行为": [("verbs_and_gerunds", ("list of tagged verbs", "list of tagged gerunds"), ())],
    "画面›构图": [("image_composition", ("view angle", "perspective", "framing the body",
                                     "composition", "subject matter"), ())],
    "画面›技法": [("image_composition", ("techniques", "styles", "format", "flaws"), ())],
    "画面›图案": [("image_composition", ("patterns",), ())],
    "画面›打光": [("lighting", None, ("see also",))],
    "画面›配色": [("colors", None, ("see also",))],
    "画面›氛围": [("subjective", None, ("exceptions",))],
    "生物›动物": [("cats", ("main", "misc", "breeds", "colors", "markings",
                          "feline relatives", "cats do"), ()),
               ("dogs", ("main", "misc", "breeds", "colors", "markings", "dogs do"), ()),
               ("birds", ("main", "misc", "breeds", "colors", "birds do"), ())],
    "生物›传说": [("legendary_creatures", ("type", "culture-specific", "miscellaneous"), ())],
    "生物›植物": [("flowers", None, ("see also",))],
    "成人›性交": [("sex_acts", ("group sex", "penetration", "same-sex", "roles"), ()),
                ("sexual_positions", None, ("see also",))],
    "成人›前戏": [("sex_acts", ("stimulation", "breasts", "before sex"), ())],
    "成人›特殊": [("sex_acts", ("bondage and discipline", "cum play", "rape", "smother",
                             "miscellaneous fetishes", "scat and urination",
                             "animal play", "incest"), ()),
                ("bdsm_and_torture", ("bdsm plays", "bondage", "ties", "torture",
                                      "devices", "clamps", "marks", "torture techniques",
                                      "beating", "clothing", "locations", "psychological"), ())],
    "成人›露出": [("nudity", None, ("see also",)),
                ("sex_acts", ("exhibitionism",), ())],
    "服饰›通用": [("sexual_attire", None, ("see also",))],
    "道具›器物": [("food_tags", None, ("see also",)), ("technology", None, ("see also",)),
                ("water", None, ("see also",)), ("fire", None, ("see also",)),
                ("cards", None, ("see also",))],
    "动作›手部": [("holding_tags", None, ("see also",))],
}


def pick(wiki, slug, inc, exc):
    out = []
    for sec in wiki[slug]["sections"]:
        name = sec["section"].lower()
        if inc and not any(k in name for k in inc):
            continue
        if exc and any(k in name for k in exc):
            continue
        for t in sec["tags"]:
            if not t.startswith(("tag_group:", "list_of_")):
                out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    wiki = json.loads((BENCH / "danbooru_tag_groups" / "parsed.json").read_text(encoding="utf-8"))

    plans = {}
    for label, specs in PLAN.items():
        ph = []
        for slug, inc, exc in specs:
            key = f"tag_group:{slug}"
            if key not in wiki:
                continue
            ph += pick(wiki, key, inc, exc)
        plans[label] = phrase_pattern(V12.prep(sorted(set(ph))))
    compiled = {k: re.compile(v, re.I) for k, v in plans.items()}
    for k, rx in compiled.items():
        print(f"  {k:<12} 短语 {rx.pattern.count('|') + 1:>4}")

    with sqlite3.connect(str(DB)) as con:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {"themes": [], "facets": []}

    changed = 0
    added = Counter()
    samples = defaultdict(list)
    out_lines = []
    for u, s, text in rows:
        e = subs.get(s)
        area = gdb.get(e[0], "") if e else ""
        doc = meta.get(u)
        if COMBO.search(area) or doc is None:
            continue
        if doc.get("themes") or doc.get("facets"):
            out_lines.append(json.dumps(
                {"id": u, "source": area, "leaf": e[1] if e else "",
                 "themes": doc.get("themes", []), "facets": doc.get("facets", []),
                 "series": doc.get("series"), "text": (text or "")[:150]},
                ensure_ascii=False))
            continue
        body = denoise(text)
        scene = V12.scene_body(body)
        themes, facets = [], []
        for label, rx in compiled.items():
            target = scene if label.startswith("场景›") else body
            m = None
            for cand in rx.finditer(target):
                if not rejected(label, target, cand):
                    m = cand
                    break
            if not m:
                continue
            (facets if label in FACETS else themes).append(label)
            added[label] += 1
            if len(samples[label]) < SAMPLE:
                st = max(0, m.start() - 22)
                samples[label].append(("…" + target[st:m.end() + 16] + "…", m.group(0),
                                       md5(u.encode()).hexdigest()))
        if themes or facets:
            changed += 1
        out_lines.append(json.dumps(
            {"id": u, "source": area, "leaf": e[1] if e else "",
             "themes": themes, "facets": facets, "text": (text or "")[:150]},
            ensure_ascii=False))

    if args.write:
        OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    L = ["# 新轴与补漏（v35）", "", f"- 补上的零归属：{changed:,}", "",
         "| 轴 | 补到 |", "| --- | --- |"]
    for k in compiled:
        L.append(f"| {k} | {added[k]:,} |")
    L += ["", "## 抽样", ""]
    for k in compiled:
        L.append(f"**{k}**")
        L.append("")
        for ctx, hit, _h in sorted(samples[k], key=lambda x: x[2])[:SAMPLE]:
            L.append(f"- `{hit}` ← {ctx}")
        L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"补上 {changed:,} 条零归属")
    for k in compiled:
        print(f"   {k:<12} +{added[k]:,}")
    print(f"落盘：{REPORT.name}{'；快照 ' + OUT.name if args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
