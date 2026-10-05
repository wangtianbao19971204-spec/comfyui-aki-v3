"""解开 3549 moodboard 小包 → 统计风格 JSON 数量与结构 → 出风格清单。"""
from __future__ import annotations

import json
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
ZIP = HERE / "ray_styles" / "3237838.zip"
OUT_DIR = HERE / "ray_styles" / "extracted"
LIST = HERE / "ray_styles_3549.jsonl"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        jsons = [name for name in names if name.lower().endswith(".json")]
        print(f"压缩包内文件 {len(names)} 个，其中 json {len(jsons)} 个")
        rows: list[dict] = []
        keys_counter: Counter = Counter()
        for name in jsons:
            try:
                data = json.loads(archive.read(name).decode("utf-8", "replace"))
            except Exception as error:  # noqa: BLE001
                print("  解析失败：", name, error)
                continue
            if isinstance(data, dict):
                keys_counter.update(data.keys())
            rows.append({"file": Path(name).name, "data": data})
    LIST.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    print(f"有效风格 JSON：{len(rows):,} 个 → {LIST.name}")
    print("字段出现次数：", dict(keys_counter.most_common(12)))
    for row in rows[:3]:
        print("\n---", row["file"])
        text = json.dumps(row["data"], ensure_ascii=False, indent=1)
        print(text[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
