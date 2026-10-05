"""Ray 风格：统计总条数 + 缩略图可达性抽检。"""
from __future__ import annotations

import json
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
LIST = HERE / "ray_styles_3549.jsonl"
IMG_DIR = HERE / "ray_style_previews"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def main() -> int:
    rows = [json.loads(line) for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]
    styles: list[dict] = []
    per_file: Counter = Counter()
    for row in rows:
        data = row["data"]
        items = data if isinstance(data, list) else [data]
        per_file[row["file"]] = len(items)
        for item in items:
            if isinstance(item, dict):
                styles.append({**item, "_file": row["file"]})
    print(f"风格 JSON 文件 {len(rows)} 个；风格条目合计 {len(styles):,}")
    print(f"有 prompt：{sum(1 for s in styles if s.get('prompt')):,}；"
          f"有中文名：{sum(1 for s in styles if s.get('name_cn')):,}；"
          f"有缩略图：{sum(1 for s in styles if s.get('thumbnail')):,}")
    print("最大的 5 个分组：")
    for name, count in per_file.most_common(5):
        print(f"   {name[:52]:<54} {count:,}")

    IMG_DIR.mkdir(exist_ok=True)
    ok = 0
    picked = styles[:10]
    for index, style in enumerate(picked, 1):
        url = style.get("thumbnail") or ""
        try:
            blob = get(url)
            (IMG_DIR / f"test_{index:02d}.webp").write_bytes(blob)
            ok += 1
            print(f"   ✓ {style.get('name_cn') or style.get('name')}  {len(blob) // 1024} KB")
        except Exception as error:  # noqa: BLE001
            print(f"   ✗ {style.get('name')[:40]} → {error}")
    print(f"\n缩略图抽检：{ok}/{len(picked)} 成功，样例落在 {IMG_DIR.name}")
    (HERE / "ray_styles_all.jsonl").write_text(
        "\n".join(json.dumps(style, ensure_ascii=False) for style in styles), encoding="utf-8")
    print("汇总清单：ray_styles_all.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
