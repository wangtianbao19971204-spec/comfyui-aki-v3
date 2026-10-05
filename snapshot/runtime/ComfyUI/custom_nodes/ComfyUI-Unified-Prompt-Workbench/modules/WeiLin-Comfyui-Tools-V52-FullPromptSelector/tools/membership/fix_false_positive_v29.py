"""第 29 轮：撤掉放宽边界后引入的误匹配（角色›种族 / 道具›器物）。

精查（audit_boundary_added.py）发现：
  角色›种族：`honoka_(summer_angel_on_the_shore)_(doa)`、`yamada_elf`、`dragon_miku`
             —— 种族词藏在角色名/服装名里，不是真的种族
  道具›器物：`camera_operator_partner`、`food_on_face`、`plant_hair`、`against_glass`
             —— 物件词藏在别的词里

修法：这两条轴**忽略括号内的命中**；另外要求命中词不能是「专名的一部分」——
用打分：命中前后若紧邻另一个词、且不是常见搭配后缀，就判否。

本脚本只做「撤除」：把这两条轴按新口径重算，与现状比对，只删新增且不合格的。
用法： python fix_false_positive_v29.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from hashlib import md5
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BENCH))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
import rebuild_action_scene_v11 as V11  # noqa: E402

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "误匹配修复_v29_20260919.md"
SAMPLE = 25

# 这两条轴要收严
TARGETS = {
    "角色›种族": (r"\b(dragon|elf|demon|angel|catgirl|fox girl|beast|monster|robot|mecha|"
                r"slime|vampire|dragonborn|kemono|dog girl|animal ears)\b"),
    "道具›器物": (r"\b(book|books|cup|glass|bottle|food|cake|fruit|camera|phone|umbrella|"
                r"balloon|plant|knife|gun|sword|staff|box|bag|doll|teddy bear)\b"),
    "角色›职业": (r"\b(maid|nurse|idol|teacher|student|knight|ninja|witch|police|"
                r"office lady|flight attendant|scientist)\b"),
}
# 这些后缀说明命中词是真的在描述主体（种族/器物），保留
RACE_SUFFIX = ("girl", "boy", "man", "woman", "male", "female", "person", "guy",
               "horns", "wings", "tail", "ears", "skin", "form", "king", "queen",
               "lord", "slayer", "race", "creature", "girls", "boys")
OBJECT_SUFFIX = ("cup", "glass", "bottle", "box", "bag", "doll", "knife", "gun",
                 "sword", "staff", "book", "cake", "fruit", "camera", "phone",
                 "umbrella", "balloon", "plant", "food", "stack", "set",
                 "collection", "rack", "shelf", "case", "holder", "stand",
                 "pile", "container", "toy", "item")
# 命中词前面是这些词 → 它在描述位置/关系，不是器物
PREPOSITION = ("against", "on", "in", "at", "through", "behind", "under",
               "over", "with", "of", "for", "into", "onto", "near", "beside")
# 职业词后面跟这些 → 它是在修饰服饰/身体，不是在说职业
JOB_REJECT_SUFFIX = ("hat", "cap", "dress", "outfit", "uniform", "costume", "clothes",
                     "ears", "eyes", "tail", "horns", "wings", "skin", "office",
                     "room", "cafe", "shop", "gloves", "sleeves", "shoes", "boots")


def widen_all(p: str) -> str:
    out = p.replace(r"\b", "")
    return "(?<![a-z0-9])(?:" + out + r")(?![a-z0-9])"


PAREN = re.compile(r"\([^()]*\)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    compiled = {}
    for label, p in TARGETS.items():
        compiled[label] = (re.compile(p, re.I), re.compile(widen_all(p), re.I))

    con = sqlite3.connect(str(DB))
    try:
        gdb = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {}

        drop = []
        samples = []
        for u, s, text in rows:
            e = subs.get(s)
            area = gdb.get(e[0], "") if e else ""
            doc = meta.get(u)
            if COMBO.search(area) or doc is None:
                continue
            body = denoise(text)
            no_paren = PAREN.sub(" ", body)          # 忽略括号内容
            for label, (rx_old, rx_new) in compiled.items():
                if label not in (doc.get("themes") or []):
                    continue
                if rx_old.search(body):
                    continue                          # 旧规则本来就命中 → 保留
                m = rx_new.search(no_paren)
                ok = False
                if m is None:
                    continue      # 这条轴的归属不是正则给的（可能来自 danbooru 清单），别动
                if m:
                    after = no_paren[m.end():m.end() + 22]
                    # 库里下划线和空格混用，两个都要认（`witch_hat` 与 `witch hat`）
                    nx = re.match(r"[ _]+([a-z0-9']+)", after)
                    if label == "角色›种族":
                        # 词尾（后面不是另一个词）且整条很短 → 也算，如 eastern_dragon
                        tail_ok = (nx is None) and len(re.findall(r"[a-z0-9']+",
                                                                  no_paren.split(",")[0])) <= 3
                        ok = bool(nx and nx.group(1) in RACE_SUFFIX) or tail_ok
                    elif label == "角色›职业":
                        # 词尾且条目很短（qi_maid / wa_maid）算命中；后面跟服饰词则否（witch_hat）
                        tail_ok = (nx is None) and len(re.findall(r"[a-z0-9']+",
                                                                  no_paren.split(",")[0])) <= 3
                        ok = bool(nx and nx.group(1) not in JOB_REJECT_SUFFIX) or tail_ok
                    else:
                        before = re.search(r"([a-z0-9']+)_$", no_paren[:m.start()])
                        if before and before.group(1) in PREPOSITION:
                            ok = False
                        else:
                            ok = (not nx) or nx.group(1) in OBJECT_SUFFIX
                if not ok:
                    drop.append((u, label))
                    if len(samples) < SAMPLE * 3:
                        samples.append((body[:56], label, m.group(0) if m else "（括号内）",
                                        md5(u.encode()).hexdigest()))

        cnt = Counter(l for _u, l in drop)
        print(f"要撤除的误匹配：{len(drop):,}")
        for k, v in cnt.most_common():
            print(f"   {k}: {v}")
        print()
        for t, l, hit, _h in sorted(samples, key=lambda x: x[3])[:16]:
            print(f"   [{l}] {t[:44]:<46} ← {hit}")

        L = ["# 误匹配修复（v29）", "", f"- 撤除 {len(drop):,} 条", "",
             "| 轴 | 撤除 |", "| --- | --- |"]
        for k, v in cnt.most_common():
            L.append(f"| {k} | {v:,} |")
        L += ["", "## 撤除样例", "", "| 文本 | 轴 | 命中词 |", "| --- | --- | --- |"]
        for t, l, hit, _h in sorted(samples, key=lambda x: x[3])[:SAMPLE * 2]:
            L.append(f"| {t} | {l} | `{hit}` |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply or not drop:
            print("dry-run 或无需改动。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_fp_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)

        by_uuid = {}
        for u, label in drop:
            by_uuid.setdefault(u, []).append(label)
        updates = []
        for u, labels in by_uuid.items():
            d = dict(meta.get(u) or {})
            d["themes"] = [x for x in (d.get("themes") or []) if x not in labels]
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已撤除（涉及 {len(updates):,} 条记录）")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
