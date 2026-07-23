#!/usr/bin/env python3
"""Rewrite SPA ?v= cache keys across frontend/dist after in-place dist patches."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from spa_asset_cache import LEGACY_SPA_ASSET_CACHE_KEYS, SPA_ASSET_CACHE_KEY

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"


def bump_dist_cache_keys() -> int:
    changed_files = 0
    for path in DIST.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        updated = text
        for old in LEGACY_SPA_ASSET_CACHE_KEYS:
            if old == SPA_ASSET_CACHE_KEY:
                continue
            updated = updated.replace(old, SPA_ASSET_CACHE_KEY)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed_files += 1
    return changed_files


def main() -> None:
    count = bump_dist_cache_keys()
    print(f"bumped SPA cache key to {SPA_ASSET_CACHE_KEY} in {count} file(s)")


if __name__ == "__main__":
    main()
