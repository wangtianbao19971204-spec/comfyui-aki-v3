"""动作 / 场景 精确重建（v11 定稿，试跑不写库）。

清单来源：`danbooru_tag_groups/parsed.json`（由 in-app browser 批量抓取的 193 个
Danbooru wiki 页），做法是「精确短语拼装」，绝不删词改规则（历史两次事故的根因）。

迭代轨迹（每一轮都由抽样人工核验后决定去留）：
  v8  首版：直接套 posture / gestures / locations 清单
        -> 抽样发现 `v` 命中一切 v 开头词；feet 清单里全是袜子鞋子；office lady / studio ghibli 误伤
  v9  短语长度断言（单词短语 >= 4 字符）+ 弱词表 + 物件后缀判否 + 腿部改用 posture 腿/膝/脚段落
  v10 追加 `eye_contact` 剔除、`pool` 地点歧义剔除、场景物件后缀（chair/eyes）
      抽样改成按 id 哈希均匀随机（原先是 DB 顺序前 N 条，有偏差）
  v11 场景规则不看括号内容（`neon (blue ocean)` / `bunker hill (azur lane)` 这类角色名）
       曾被尝试又被否决：按「专名前一词也大写」判否，结果误伤 `West Lake in Hangzhou`
       这类真地点（净收益为负），因此不采用。

断言：任一主题规则命中率 > 30% 即判失败（人物数量 / 外貌属面类，天然高命中，豁免）。
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
from rebuild_action_scene_v8 import (  # noqa: E402
    DB, COMBO, denoise, load_wiki, load_old_rules, section_tags,
)

VERSION = "v11"
OUT_JSONL = HERE / f"全库_面与主题_{VERSION}_20260919.jsonl"
OUT_RULES = HERE / "最终规则_v3_20260919.json"
REPORT = HERE / f"动作场景重建_{VERSION}_20260919.md"
SAMPLES = HERE / f"动作场景抽样_{VERSION}_每类32条_20260919.md"

MAX_RATE = 0.30
SAMPLE_PER_CLASS = 32
FACET_EXEMPT = ("人物数量", "外貌")

WEAK_PHRASES = {
    "v", "w", "x", "s",
    "folded", "split", "yoga", "floating", "pose", "poses",
    "eye contact", "natural", "object", "alone",
}
MIN_SINGLE_TOKEN = 4

# 会命中「同名单词但不是地点」的词
AMBIGUOUS_PLACES = {
    "office", "studio", "water", "plain", "stream", "nature", "park",
    "field", "hall", "court", "bar", "club", "ring", "stage", "pool",
}

# 短语后接这些名词 = 修饰物/身体部件，不是动作或地点
OBJECT_SUFFIX = (
    "scarf", "hair", "hair_strand", "strand", "strands", "cloth", "clothes", "clothing",
    "skirt", "dress", "sleeve", "sleeves", "ribbon", "petal", "petals", "leaf", "leaves",
    "paper", "light", "spark", "sparks", "sparkle", "sparkles", "feather", "feathers",
    "fabric", "bubble", "bubbles", "smoke", "cloud", "clouds", "snow", "dust", "sand",
    "ash", "flame", "flames", "particle", "particles", "string", "strings", "rope",
    "chair", "mat", "towel", "umbrella", "eyes",
)

PAREN_RE = re.compile(r"[\(\（][^\)\）]{0,60}[\)\）]")


def keep_phrase(p: str) -> bool:
    p = (p or "").strip().lower()
    if not p or p.startswith("!") or p.startswith("tag_group:"):
        return False
    if p in WEAK_PHRASES:
        return False
    toks = [t for t in re.split(r"[ _]+", p) if t]
    if not toks:
        return False
    if len(toks) == 1 and len(toks[0]) < MIN_SINGLE_TOKEN:
        return False
    return True


def phrase_pattern(phrases, extra=""):
    parts = []
    for p in phrases:
        if not keep_phrase(p):
            continue
        toks = [re.escape(t) for t in re.split(r"[ _]+", p.strip().lower()) if t]
        parts.append(r"[ _]+".join(toks))
    if extra:
        parts.append(extra)
    parts = sorted(set(parts), key=len, reverse=True)
    if not parts:
        return r"(?!x)x"
    guard = r"(?![ _]+(?:" + "|".join(OBJECT_SUFFIX) + r")(?![a-z0-9]))"
    return r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])" + guard


def scene_body(body: str) -> str:
    """场景规则去掉括号内容，避免角色名里的地名（blue ocean / mission relaxation）误判。"""
    return PAREN_RE.sub(" ", body)


def build_rules(wiki):
    posture = wiki["tag_group:posture"]["tags"]
    gestures = wiki["tag_group:gestures"]["tags"]

    legs = []
    for s in wiki["tag_group:posture"]["sections"]:
        if any(k in s["section"].lower()
               for k in ("leg location", "knee location", "foot position")):
            legs.extend(s["tags"])
    legs = sorted(set(legs))

    indoor = [t for t in section_tags(wiki, "tag_group:locations", "indoors")
              if t not in AMBIGUOUS_PLACES]
    outdoor = [t for t in section_tags(wiki, "tag_group:locations", "natural settings")
               if t not in AMBIGUOUS_PLACES]

    return [
        ("动作", "姿态", phrase_pattern(posture), len([p for p in posture if keep_phrase(p)])),
        ("动作", "手势", phrase_pattern(gestures), len([p for p in gestures if keep_phrase(p)])),
        ("动作", "腿部", phrase_pattern(legs), len([p for p in legs if keep_phrase(p)])),
        ("场景", "室内", phrase_pattern(indoor), len(indoor)),
        ("场景", "室外", phrase_pattern(outdoor, extra=r"outdoors"), len(outdoor) + 1),
    ]


def rank(uid: str) -> str:
    """抽样用：按 id 哈希排序，避免 DB 顺序带来的偏差。"""
    return md5(uid.encode("utf-8", "ignore")).hexdigest()


def main() -> int:
    wiki = load_wiki()
    new_rules = build_rules(wiki)
    old_rules, dropped = load_old_rules()
    rules = old_rules + [(t, s, p) for t, s, p, _n in new_rules]
    # (theme, sub, 正则, 是否使用「去括号正文」)
    compiled = [(t, s, re.compile(p, re.I), t == "场景") for t, s, p in rules]

    with sqlite3.connect(str(DB)) as con:
        groups = {r[0]: r[1] for r in con.execute("select id_index, name from tag_groups")}
        subs = {r[0]: (r[1], r[2]) for r in con.execute(
            "select id_index, group_id, name from tag_subgroups")}
        rows = con.execute("select t_uuid, subgroup_id, text from tag_tags").fetchall()

    stats: Counter = Counter()
    samples: dict[str, list[dict]] = {}
    total = zero = 0
    new_labels = {f"{t}›{s}" for t, s, _p, _n in new_rules}

    with OUT_JSONL.open("w", encoding="utf-8") as handle:
        for uuid, subgroup_id, text in rows:
            entry = subs.get(subgroup_id)
            area = groups.get(entry[0], "") if entry else ""
            if COMBO.search(area):
                continue
            total += 1
            body = denoise(text)
            fbody = scene_body(body)
            hits: list[str] = []
            for theme, sub, pattern, uses_scene_body in compiled:
                m = pattern.search(fbody if uses_scene_body else body)
                if not m:
                    continue
                label = f"{theme}›{sub}"
                if label in hits:
                    continue
                hits.append(label)
                stats[label] += 1
                if label in new_labels:
                    bucket = samples.setdefault(label, [])
                    bucket.append({"key": rank(uuid), "text": body[:120], "hit": m.group(0),
                                   "leaf": entry[1] if entry else "", "area": area})
                    bucket.sort(key=lambda x: x["key"])
                    del bucket[SAMPLE_PER_CLASS:]
            if not hits:
                zero += 1
            handle.write(json.dumps({"id": uuid, "source": area,
                                     "leaf": entry[1] if entry else "",
                                     "memberships": hits, "text": (text or "")[:150]},
                                    ensure_ascii=False) + "\n")

    violations = [(lbl, c) for lbl, c in stats.items()
                  if c / total > MAX_RATE and not lbl.startswith(FACET_EXEMPT)]

    lines = [f"# 动作 / 场景 精确重建（{VERSION} 定稿，试跑未写库）", "",
             f"- 参与 tag：{total:,}（已排除一键组合区）",
             f"- 零归属：{zero:,}（{zero / total * 100:.1f}%）",
             f"- 替换掉的旧规则：{', '.join(dropped)}",
             f"- 主题规则命中率断言（≤{MAX_RATE:.0%}）："
             f"{'通过' if not violations else '**违规** ' + str(violations)}", "",
             "## 新规则短语数 / 命中", "",
             "| 规则 | 短语数 | 命中 | 命中率 |", "| --- | --- | --- | --- |"]
    for t, s, _p, n in new_rules:
        lbl = f"{t}›{s}"
        c = stats[lbl]
        lines.append(f"| {lbl} | {n} | {c:,} | {c / total * 100:.2f}% |")
    lines += ["", "## 全量规则命中", "", "| 规则 | 命中 | 命中率 |", "| --- | --- | --- |"]
    for lbl, c in stats.most_common():
        lines.append(f"| {lbl} | {c:,} | {c / total * 100:.2f}% |")
    lines += ["", "## 已知残留", "",
              "- `bunker hill (azur lane)`、`neon (blue ocean)` 这类角色名仍会命中 场景›室外"
              "（全库约 6 条，库内文本已小写，无法用大小写判专名）。",
              "- 抽样文件见：" + SAMPLES.name,
              "- 规则文件见：" + OUT_RULES.name]
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    s_lines = [f"# 动作 / 场景 抽样（每类 {SAMPLE_PER_CLASS} 条，按 id 哈希随机）", ""]
    for t, s, _p, _n in new_rules:
        lbl = f"{t}›{s}"
        s_lines += [f"## {lbl}  （命中 {stats[lbl]:,}）", "",
                    "| # | 文本 | 命中短语 | 来源 | 叶子 |", "| --- | --- | --- | --- | --- |"]
        for i, x in enumerate(samples.get(lbl, []), 1):
            s_lines.append(f"| {i} | {x['text'].replace('|', '/')} | `{x['hit']}` | "
                           f"{x['area']} | {x['leaf']} |")
        s_lines.append("")
    SAMPLES.write_text("\n".join(s_lines), encoding="utf-8")

    OUT_RULES.write_text(json.dumps(
        [{"theme": t, "sub": s, "pattern": p} for t, s, p in rules],
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"参与 {total:,}；零归属 {zero:,}（{zero / total * 100:.1f}%）")
    print(f"断言违规：{violations if violations else '无'}")
    for t, s, _p, n in new_rules:
        lbl = f"{t}›{s}"
        print(f"  {lbl:<10} 短语{n:>4}  命中 {stats[lbl]:>7,} ({stats[lbl] / total * 100:>5.2f}%)")
    print(f"落盘：{OUT_JSONL.name} / {OUT_RULES.name} / {REPORT.name} / {SAMPLES.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
