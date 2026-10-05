from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_review_html(
    run_dir: Path,
    scores: list[dict[str, Any]],
    character_name: str,
) -> Path:
    cards: list[str] = []
    for item in sorted(
        scores,
        key=lambda row: float(row.get("final_score", 0)),
        reverse=True,
    ):
        candidate = Path(item["candidate"])
        relative = candidate.relative_to(run_dir).as_posix()
        vlm = item.get("vlm") or {}
        problems = "<br>".join(
            html.escape(str(value)) for value in vlm.get("problems", [])
        )
        cards.append(
            f"""
            <article class="card">
              <img src="{html.escape(relative)}" loading="lazy">
              <div class="body">
                <h3>{html.escape(item["job_id"])}</h3>
                <div class="score">{item.get("final_score", 0):.1f}</div>
                <p>{html.escape(str(vlm.get("decision", "未调用 LLM")))}</p>
                <p class="problems">{problems or "无记录问题"}</p>
                <details><summary>完整评分</summary><pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details>
              </div>
            </article>
            """
        )
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(character_name)} 黄金图初筛</title>
<style>
body{{margin:0;background:#111827;color:#e5e7eb;font-family:"Microsoft YaHei",sans-serif}}
header{{position:sticky;top:0;padding:18px 28px;background:#0f172add;backdrop-filter:blur(8px);z-index:2}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px;padding:24px}}
.card{{background:#1f2937;border:1px solid #374151;border-radius:14px;overflow:hidden}}
.card img{{width:100%;height:420px;object-fit:contain;background:#0b1020}}
.body{{padding:14px;position:relative}}h3{{font-size:15px;margin:0 58px 10px 0}}
.score{{position:absolute;right:14px;top:10px;font-size:28px;font-weight:700;color:#fbbf24}}
p{{margin:8px 0;color:#cbd5e1}}.problems{{color:#fca5a5;min-height:44px}}
pre{{white-space:pre-wrap;font-size:11px;color:#cbd5e1}}
</style></head><body>
<header><h1>{html.escape(character_name)} · 机器黄金图初筛</h1>
<p>按总分排序；训练前仍应检查脸、成年感、头身比、发型、服装结构和双枪。</p></header>
<main>{''.join(cards)}</main></body></html>"""
    output = run_dir / "review.html"
    output.write_text(page, encoding="utf-8")
    return output
