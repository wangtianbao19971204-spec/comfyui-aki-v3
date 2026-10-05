from __future__ import annotations

from pathlib import Path

import markdown


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "report"
SOURCE = REPORT_DIR / "三模型详细对比报告.md"
TARGET = REPORT_DIR / "三模型详细对比报告.html"


def main() -> int:
    body = markdown.markdown(
        SOURCE.read_text(encoding="utf-8"),
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": True}},
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ComfyUI 三模型工作流详细对比报告 - Anima 2.9B 版</title>
<style>
:root {{ color-scheme: light; --ink:#1b1f24; --muted:#59636e; --line:#d7dce2; --accent:#8e3d72; --paper:#ffffff; --wash:#f4f6f8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--wash); color:var(--ink); font-family:"Microsoft YaHei","Segoe UI",sans-serif; line-height:1.72; letter-spacing:0; }}
main {{ width:min(1120px, calc(100% - 32px)); margin:24px auto 64px; padding:48px 64px; background:var(--paper); border:1px solid var(--line); }}
h1 {{ font-size:34px; line-height:1.25; margin:0 0 28px; }}
h2 {{ font-size:25px; line-height:1.35; margin:48px 0 18px; padding-bottom:8px; border-bottom:2px solid var(--ink); }}
h3 {{ font-size:19px; line-height:1.4; margin:32px 0 12px; color:#29313a; }}
p {{ margin:10px 0; }}
a {{ color:#1a5b88; text-underline-offset:3px; }}
a.headerlink {{ color:#aeb6bf; text-decoration:none; margin-left:8px; font-size:.7em; }}
blockquote {{ margin:20px 0; padding:14px 18px; border-left:4px solid var(--accent); background:#f8f3f7; color:#3f3540; }}
table {{ width:100%; border-collapse:collapse; margin:18px 0 26px; font-size:14px; display:block; overflow-x:auto; }}
th,td {{ border:1px solid var(--line); padding:9px 11px; text-align:left; vertical-align:top; }}
th {{ background:#edf0f3; font-weight:700; white-space:nowrap; }}
tbody tr:nth-child(even) {{ background:#fafbfc; }}
code {{ font-family:"Cascadia Mono",Consolas,monospace; font-size:.92em; background:#edf0f3; padding:2px 5px; border-radius:3px; }}
pre {{ overflow:auto; padding:16px; background:#1f252b; color:#edf1f5; border-radius:4px; line-height:1.5; }}
pre code {{ color:inherit; background:transparent; padding:0; }}
img {{ display:block; max-width:100%; height:auto; margin:22px auto 30px; border:1px solid var(--line); }}
ul,ol {{ padding-left:26px; }}
li {{ margin:5px 0; }}
hr {{ border:0; border-top:1px solid var(--line); margin:40px 0; }}
@media (max-width:760px) {{ main {{ width:100%; margin:0; padding:28px 18px 48px; border:0; }} h1 {{ font-size:28px; }} h2 {{ font-size:22px; }} }}
@media print {{ body {{ background:white; }} main {{ width:100%; margin:0; padding:0; border:0; }} a {{ color:inherit; }} h2 {{ break-after:avoid; }} table,img,pre {{ break-inside:avoid; }} }}
</style>
</head>
<body><main>{body}</main></body>
</html>
"""
    TARGET.write_text(html, encoding="utf-8")
    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
