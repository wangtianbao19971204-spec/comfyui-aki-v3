"""全量拉 Ray 风格缩略图（optim-images.krea.ai，断点续传 + 失败清单）。"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(r"G:\ComfyUI-aki-v3\benchmark_reports\2026-09-17_krea2_nl_import")
LIST = HERE / "ray_styles_all.jsonl"
PREVIEW = Path(r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\ComfyUI-Unified-Prompt-Workbench\modules"
               r"\WeiLin-Comfyui-Tools-V52-FullPromptSelector\user_data\prompt_selector\preview")
FAILED = HERE / "ray_style_download_failed.jsonl"
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(index_and_style: tuple[int, dict]) -> tuple[int, dict, bool]:
    index, style = index_and_style
    target = PREVIEW / f"ray_style_{index:05d}.webp"
    if target.exists() and target.stat().st_size > 500:
        return index, style, True
    try:
        request = urllib.request.Request(style.get("thumbnail") or "", headers=UA)
        with urllib.request.urlopen(request, timeout=25) as response:
            blob = response.read()
        if len(blob) > 500:
            target.write_bytes(blob)
            return index, style, True
    except Exception:  # noqa: BLE001
        pass
    return index, style, False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    styles = [json.loads(line) for line in LIST.read_text(encoding="utf-8").splitlines() if line.strip()]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    print(f"目标 {len(styles):,} 张 → {PREVIEW}", flush=True)
    started = time.time()
    ok = fail = 0
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for index, style, success in pool.map(fetch, enumerate(styles, 1)):
            if success:
                ok += 1
            else:
                fail += 1
                failures.append({"index": index, "name": style.get("name"),
                                 "name_cn": style.get("name_cn"), "thumbnail": style.get("thumbnail")})
            if index % 250 == 0 or index == len(styles):
                rate = index / max(0.001, time.time() - started)
                print(f"[{index}/{len(styles)}] 成功 {ok:,} 失败 {fail:,} | {rate * 60:.0f} 张/分 | "
                      f"剩余≈{(len(styles) - index) / max(0.01, rate) / 60:.1f} 分", flush=True)
                FAILED.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in failures),
                                  encoding="utf-8")
    print(f"完成：成功 {ok:,}，失败 {fail:,}，用时 {(time.time() - started) / 60:.1f} 分", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
