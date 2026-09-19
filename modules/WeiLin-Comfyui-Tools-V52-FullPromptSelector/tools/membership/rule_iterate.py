"""规则自审计迭代：6 轮，每轮修一类问题并输出指标轨迹。

指标：规则数 / 同键重复规则数 / 含噪声词的规则数 / 平均归属数 / 零归属率 / 命中片段含噪声词比例
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from per_entry_theme import EN as EN_BASE, denoise  # noqa: E402

DB = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
          r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\userdatas_zh_CN_tags.db")
OUT_MD = HERE / "规则迭代轨迹_20260919.md"
OUT_JSON = HERE / "规则迭代最终规则_20260919.json"
COMBO = re.compile(r"一键NSFW|一键模式")

# 噪声/模板词：任何提示词都有，不能作为主题线索
NOISE = ["no text", "watermark", "signature", "quality", "resolution", "official art", "uncensored",
         "absurdres", "masterpiece", "best quality", "very aesthetic", "detailed", "detailed",
         "light", "shadow", "particles", "year", "artist", "artstyle", "style"]


def load_texts() -> list[str]:
    with sqlite3.connect(str(DB)) as con:
        groups = {row[0]: row[1] for row in con.execute("select id_index, name from tag_groups")}
        subs = {row[0]: (row[1], row[2]) for row in
                con.execute("select id_index, group_id, name from tag_subgroups")}
        return [denoise(text) for sid, text in con.execute("select subgroup_id, text from tag_tags")
                if not COMBO.search(groups.get(subs.get(sid, (None, ""))[0], ""))]


def metrics(rules: list[tuple[str, str, str]], bodies: list[str]) -> dict:
    keys = Counter(f"{theme}›{sub}" for theme, sub, _ in rules)
    dup_keys = sum(1 for key, count in keys.items() if count > 1)
    noisy = sum(1 for _theme, _sub, pattern in rules
                if any(word in pattern.lower() for word in NOISE))
    total = len(bodies)
    membership_total = zero = 0
    generic_hits = 0
    for body in bodies:
        hits = []
        for theme, sub, pattern in rules:
            match = re.search(pattern, body, re.I)
            if not match:
                continue
            label = f"{theme}›{sub}"
            if label in hits:
                continue
            hits.append(label)
            if any(word in match.group(0).lower() for word in NOISE):
                generic_hits += 1
        membership_total += len(hits)
        if not hits:
            zero += 1
    return {"规则数": len(rules), "同键重复规则": dup_keys, "含噪声词的规则": noisy,
            "平均归属数": round(membership_total / max(1, total), 2),
            "零归属率": f"{zero / max(1, total) * 100:.1f}%",
            "命中含噪声词比例": f"{generic_hits / max(1, membership_total) * 100:.1f}%"}


def round1(rules):
    """合并同 (主题›小分类) 的多条规则。"""
    merged: dict[tuple[str, str], list[str]] = defaultdict(list)
    for theme, sub, pattern in rules:
        merged[(theme, sub)].append(pattern)
    return [(theme, sub, "|".join(patterns)) for (theme, sub), patterns in merged.items()]


def strip_noise(pattern: str) -> str:
    out = pattern
    for word in NOISE:
        out = re.sub(rf"\|?\b{re.escape(word)}\b\|?", "|", out, flags=re.I)
    out = re.sub(r"\|\|+", "|", out).strip("|")
    return out or r"$^"


def round2(rules):
    """从模式里剥掉噪声词。"""
    return [(theme, sub, strip_noise(pattern)) for theme, sub, pattern in rules]


def round3(rules):
    """跨领域词归位：职业词移出服饰；去掉审查标记。"""
    moved = []
    for theme, sub, pattern in rules:
        if (theme, sub) == ("服饰", "通用"):
            pattern = re.sub(r"\|?\b(maid|nurse|idol)\b", "", pattern, flags=re.I).strip("|")
            pattern = re.sub(r"\|\|+", "|", pattern)
        moved.append((theme, sub, pattern or r"$^"))
    moved.append(("角色", "职业", r"\b(maid|nurse|idol|teacher|student|knight|ninja|witch|police)\b"))
    return moved


def round4(rules):
    """收窄"场景›背景"：只要结构性场景词。"""
    return [(theme, sub,
             r"\b(background|scenery|wall|window|ceiling|floor|room interior|distant)\b"
             if (theme, sub) == ("场景", "背景") else pattern)
            for theme, sub, pattern in rules]


def round5(rules):
    """外貌›身体 去掉手部词（归 动作›手部）。"""
    out = []
    for theme, sub, pattern in rules:
        if (theme, sub) == ("外貌", "身体"):
            pattern = re.sub(r"\|?\b(hand|hands|finger|fingers)\b", "", pattern, flags=re.I).strip("|")
            pattern = re.sub(r"\|\|+", "|", pattern)
        out.append((theme, sub, pattern or r"$^"))
    return out


def round6(rules):
    """最后一遍：再扫噪声词 + 丢掉空模式。"""
    return [(theme, sub, strip_noise(pattern)) for theme, sub, pattern in rules
            if pattern.strip("|$^ ")]


def main() -> int:
    bodies = load_texts()
    rules = list(EN_BASE)
    trajectory = [("R0 初始", metrics(rules, bodies))]
    for index, transform in enumerate([round1, round2, round3, round4, round5, round6], 1):
        rules = transform(rules)
        trajectory.append((f"R{index} {transform.__doc__.splitlines()[0][:18]}", metrics(rules, bodies)))
        print(f"R{index}: {trajectory[-1][1]}", flush=True)
    lines = ["# 规则自审计迭代轨迹（6 轮）", "",
             "| 轮次 | 规则数 | 同键重复 | 含噪声词规则 | 平均归属数 | 零归属率 | 命中含噪声词比例 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, stat in trajectory:
        lines.append(f"| {name} | {stat['规则数']} | {stat['同键重复规则']} | {stat['含噪声词的规则']} | "
                     f"{stat['平均归属数']} | {stat['零归属率']} | {stat['命中含噪声词比例']} |")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps([{"theme": t, "sub": s, "pattern": p} for t, s, p in rules],
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"落盘：{OUT_MD.name} / {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
