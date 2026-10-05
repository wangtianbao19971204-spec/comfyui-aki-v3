"""第 33 轮：修两处具体误判。

A) 成人›性交 里的 `from behind` 其实是**镜头角度**（danbooru 的体位叫 `sex from behind`）。
   改成 `sex from behind` + 补上 `doggystyle`。
B) 动作›姿态 里的 `on back / on stomach / on side` 会被
   `cum on stomach`、`mole on stomach`、`scar on back` 这类**身体部位描述**误触发。
   加负向断言：前面是身体部位/痕迹词时不算姿态。

用法： python fix_pose_sex_v33.py [--apply]
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")))
from rebuild_action_scene_v8 import DB, COMBO, denoise  # noqa: E402
from fix_boundary_v21 import widen_pattern  # noqa: E402

ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
            r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data")
REPORT = HERE / "体位姿态误判修复_v33_20260919.md"
SAMPLE = 25

SEX_OLD = (r"\b(sex|vaginal|penetration|cowgirl position|mating press|from behind|"
           r"missionary|straddling|spitroast)\b")
SEX_NEW = (r"\b(sex|vaginal|penetration|cowgirl position|mating press|sex from behind|"
           r"doggystyle|missionary|straddling|spitroast)\b")
POSE = (r"\b(on back|on stomach|on side|lying|sitting|standing)\b")
BODY_BEFORE = ("mole", "bruise", "tattoo", "mark", "marks", "scar", "scars", "stain",
               "stains", "birthmark", "piercing", "bandage", "bandaid", "cum",
               "hickey", "sunburn", "burn", "wound", "cut", "cuts", "spot", "spots",
               "dirt", "blood", "semen")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rx_sex_old = re.compile(widen_pattern(SEX_OLD), re.I)
    rx_sex_new = re.compile(widen_pattern(SEX_NEW), re.I)
    rx_pose = re.compile(widen_pattern(POSE), re.I)
    ONX = re.compile(r"(?<![a-z0-9])(?:on[ _]+back|on[ _]+stomach|on[ _]+side)(?![a-z0-9])", re.I)

    def pose_ok(body: str) -> bool:
        """去掉「身体部位 + on X」之后，还剩不剩真正的姿态词。"""
        kept = body
        for m in ONX.finditer(body):
            prev = re.search(r"([a-z0-9']+)[ _]+$", body[:m.start()])
            if prev and prev.group(1) in BODY_BEFORE:
                kept = kept.replace(m.group(0), " ", 1)
        return bool(rx_pose.search(kept))

    # 自检
    for text, want, rx, name in (
            ("wide shot from behind, from above", False, rx_sex_new, "sex-new"),
            ("sex from behind, doggystyle", True, rx_sex_new, "sex-new"),
            ("mole on stomach, blush", False, None, "pose2"),
            ("lying, on stomach", True, None, "pose2"),
            ("cum on stomach", False, None, "pose2"),
            ("on back, spread legs", True, None, "pose2")):
        got = pose_ok(text) if rx is None else bool(rx.search(text))
        if got != want:
            print(f"自检失败 {name}: {text!r} 期望 {want} 实际 {got}")
            return 1
    print("自检 6 项全过")

    con = sqlite3.connect(str(DB))
    try:
        rows = con.execute("select t_uuid, text from tag_tags").fetchall()
        meta = {}
        for u, b in con.execute("select tag_uuid, data from workbench_tag_meta"):
            try:
                meta[u] = json.loads(b)
            except Exception:
                meta[u] = {}

        # A) 性交：旧命中但新规则不命中 → 撤除
        drop_sex, samp_sex = [], []
        for u, text in rows:
            d = meta.get(u)
            if d is None or "成人›性交" not in (d.get("themes") or []):
                continue
            body = denoise(text)
            if rx_sex_old.search(body) and not rx_sex_new.search(body):
                drop_sex.append(u)
                if len(samp_sex) < SAMPLE * 3:
                    m = rx_sex_old.search(body)
                    samp_sex.append((body[:60], m.group(0), md5(u.encode()).hexdigest()))

        # B) 姿态：只靠「身体部位 + on X」进去的 → 撤除
        drop_pose, samp_pose = [], []
        for u, text in rows:
            d = meta.get(u)
            if d is None or "动作›姿态" not in (d.get("themes") or []):
                continue
            body = denoise(text)
            hit = rx_pose.search(body)
            if not hit:
                continue
            if not pose_ok(body):
                drop_pose.append(u)
                if len(samp_pose) < SAMPLE * 3:
                    samp_pose.append((body[:60], hit.group(0), md5(u.encode()).hexdigest()))

        print(f"A) 撤除 成人›性交：{len(drop_sex):,}")
        for t, hit, _h in sorted(samp_sex, key=lambda x: x[2])[:8]:
            print(f"    {t[:52]:<54} ← {hit}")
        print(f"B) 撤除 动作›姿态：{len(drop_pose):,}")
        for t, hit, _h in sorted(samp_pose, key=lambda x: x[2])[:8]:
            print(f"    {t[:52]:<54} ← {hit}")

        L = ["# 体位 / 姿态误判修复（v33）", "",
             f"- 成人›性交 撤除 {len(drop_sex):,}（`from behind` 是镜头角度）",
             f"- 动作›姿态 撤除 {len(drop_pose):,}（`cum/mole on stomach` 这类）", "",
             "## A 样例", "", "| 文本 | 命中 |", "| --- | --- |"]
        for t, hit, _h in sorted(samp_sex, key=lambda x: x[2])[:SAMPLE]:
            L.append(f"| {t} | `{hit}` |")
        L += ["", "## B 样例", "", "| 文本 | 命中 |", "| --- | --- |"]
        for t, hit, _h in sorted(samp_pose, key=lambda x: x[2])[:SAMPLE]:
            L.append(f"| {t} | `{hit}` |")
        REPORT.write_text("\n".join(L), encoding="utf-8")
        print(f"落盘：{REPORT.name}")

        if not args.apply:
            print("dry-run，未改动。加 --apply 执行。")
            return 0
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = ROOT / "prompt_selector_data_backups" / f"fix_posesex_{stamp}"
        safe.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DB, safe / "userdatas_zh_CN_tags.db")
        print("已备份：", safe)
        by_uuid = {}
        for u in drop_sex:
            by_uuid.setdefault(u, []).append("成人›性交")
        for u in drop_pose:
            by_uuid.setdefault(u, []).append("动作›姿态")
        updates = []
        for u, labels in by_uuid.items():
            d = dict(meta.get(u) or {})
            d["themes"] = [x for x in (d.get("themes") or []) if x not in labels]
            updates.append((u, json.dumps(d, ensure_ascii=False)))
        con.executemany("insert or replace into workbench_tag_meta (tag_uuid, data) "
                        "values (?,?)", updates)
        con.execute("update workbench_tag_revision set value = value + 1 where id = 1")
        con.commit()
        print(f"已处理 {len(updates):,} 条")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
