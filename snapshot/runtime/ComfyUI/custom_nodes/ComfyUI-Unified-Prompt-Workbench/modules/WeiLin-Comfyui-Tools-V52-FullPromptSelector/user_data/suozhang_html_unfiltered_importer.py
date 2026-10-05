#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suozhang / generic HTML -> Prompt Selector shared preset database importer.

V50: unfiltered content importer.
- No keyword/content safety filtering is performed by this script.
- It only removes obvious webpage noise/empty text and skips duplicate prompt text.
- It writes the Prompt Selector shared database files used by the Danbooru Gallery plugin.

Default source folder:
    weilin_tools_pkg/user_data/suozhang_html_sources/

Default database targets:
    danbooru_gallery_pkg/py/prompt_selector/data.json
    danbooru_gallery_pkg/js/prompt_selector/data.json
    danbooru_gallery_pkg/py/prompt_selector/default.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html as html_lib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from datetime import datetime
from collections import Counter, defaultdict
from uuid import uuid5, NAMESPACE_URL
import zipfile

TOOL_VERSION = "V50-html-unfiltered-tool"

DEFAULT_ORIGINAL_CATEGORY_NAMES = {
    "默认/其他", "默认/画师串", "默认/角色", "服装", "r18姿势", "普通姿势"
}

PAGE_TITLE_MAP = [
    (re.compile(r"常规", re.I), "所长常规NovelAI个人法典"),
    (re.compile(r"色色.*[（(]上[)）]", re.I), "所长色色NovelAI个人法典(上)"),
    (re.compile(r"色色.*[（(]下[)）]", re.I), "所长色色NovelAI个人法典(下)"),
]

SKIP_LINE_PATTERNS = [
    r"^PS\d*[:：]", r"^作者[:：]", r"^Note$", r"^Tip$", r"^Previous$", r"^Next$",
    r"^On this page$", r"^Table of contents$", r"^Section titled", r"^————+$",
    r"^\s*复制\s*$", r"^\s*copy\s*$", r"^\s*返回顶部\s*$",
]

SKIP_TEXT_CONTAINS = [
    "请于【】处添加角色与画风", "本法典早期大部分", "Ctrl+F", "CTRL+F",
    "添加好友时", "特别感谢", "证明所长法典今日", "法典为无偿", "NovelAi-Bot指南",
    "This page is available", "Edit page", "Last updated",
]

TAG_LIKE_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_:\-/.]*")


def clean_text(text: str) -> str:
    text = html_lib.unescape(text or "").replace("\xa0", " ")
    text = re.sub(r"\s*Section titled [“\"].*?[”\"]\s*", " ", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def clean_heading(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" #：:") or "未命名分类"


def is_obvious_noise(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    for pat in SKIP_LINE_PATTERNS:
        if re.search(pat, s, re.I):
            return True
    for frag in SKIP_TEXT_CONTAINS:
        if frag in s:
            return True
    # Very short pure punctuation / heading anchors.
    if len(s) <= 2 and not re.search(r"[a-zA-Z0-9\u4e00-\u9fff]", s):
        return True
    return False


def is_probably_prompt_text(text: str, permissive: bool = True) -> bool:
    """Noise filter only. This is not a content/safety filter."""
    s = (text or "").strip()
    if is_obvious_noise(s):
        return False
    if not permissive:
        comma = s.count(",") + s.count("，")
        ascii_tag_chars = sum(ch.isascii() and (ch.isalpha() or ch in "_:,{}[]()\\/.-0123456789") for ch in s)
        return comma >= 1 and ascii_tag_chars >= 8
    # Permissive: preserve almost everything that looks like an actual prompt/tag block.
    if any(sym in s for sym in [",", "，", "::", "{{", "}}", "[[", "]]", "char1", "char2", "artist:"]):
        return True
    if len(TAG_LIKE_RE.findall(s)) >= 2 and len(s) >= 8:
        return True
    # Keep Chinese-only custom prompt prose when it is long enough and not obvious site text.
    if re.search(r"[\u4e00-\u9fff]", s) and len(s) >= 10:
        return True
    return False


class MainBlockParser(HTMLParser):
    def __init__(self, require_main: bool):
        super().__init__(convert_charrefs=True)
        self.require_main = require_main
        self.capture_depth = 0 if require_main else 1
        self.found_main = False
        self.blocks = []  # list[(tag, text)]
        self.current_tag = None
        self.current_buf = []
        self.title_buf = []
        self.in_title = False
        self.skip_depth = 0

    @staticmethod
    def _attrs_dict(attrs):
        return {k.lower(): (v or "") for k, v in attrs}

    def _is_main_start(self, tag: str, attrs: dict) -> bool:
        cls = attrs.get("class", "")
        role = attrs.get("role", "")
        return tag == "main" or "sl-markdown-content" in cls or role == "main"

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = self._attrs_dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if tag == "title":
            self.in_title = True
            self.title_buf = []
        if self.require_main:
            if self.capture_depth == 0 and self._is_main_start(tag, attrs):
                self.capture_depth = 1
                self.found_main = True
            elif self.capture_depth > 0:
                self.capture_depth += 1
        else:
            self.capture_depth += 1
        if self.capture_depth > 0 and self.skip_depth == 0:
            if tag in {"h1", "h2", "h3", "h4", "p", "pre", "blockquote", "li"}:
                # Flush a broken previous block defensively.
                if self.current_tag and self.current_buf:
                    self._flush_current()
                self.current_tag = tag
                self.current_buf = []
            elif tag == "br" and self.current_tag:
                self.current_buf.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if self.skip_depth > 0:
            if tag in {"script", "style", "noscript", "svg"}:
                self.skip_depth -= 1
            return
        if self.current_tag == tag:
            self._flush_current()
        if self.capture_depth > 0:
            self.capture_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title_buf.append(data)
        if self.skip_depth == 0 and self.capture_depth > 0 and self.current_tag:
            self.current_buf.append(data)

    def _flush_current(self):
        text = clean_text("".join(self.current_buf))
        if text:
            self.blocks.append((self.current_tag, text))
        self.current_tag = None
        self.current_buf = []

    @property
    def title(self) -> str:
        return clean_heading("".join(self.title_buf))


def parse_blocks_from_html(html_text: str):
    # Prefer main / markdown content. If the saved page has no recognizable main container, parse whole doc.
    p = MainBlockParser(require_main=True)
    p.feed(html_text)
    if p.found_main and p.blocks:
        return p.blocks, p.title
    p2 = MainBlockParser(require_main=False)
    p2.feed(html_text)
    return p2.blocks, p2.title or p.title


def source_title_from_filename(path: Path, html_title: str = "") -> str:
    raw = html_title or path.stem
    raw = re.sub(r"\s*[|｜_-]\s*NovelAi-Bot指南.*$", "", raw, flags=re.I)
    raw = re.sub(r"\s*_\s*NovelAi-Bot指南.*$", "", raw, flags=re.I)
    raw = raw.replace("NovalAI", "NovelAI").replace("NovalAi", "NovelAI").replace("NovelAi", "NovelAI")
    for pat, name in PAGE_TITLE_MAP:
        if pat.search(raw) or pat.search(path.name):
            return name
    return clean_heading(raw) or path.stem


def parse_html_file(path: Path, source_override: str = "", permissive: bool = True):
    html_text = path.read_text("utf-8", errors="ignore")
    blocks, html_title = parse_blocks_from_html(html_text)
    source = source_override or source_title_from_filename(path, html_title)
    entries = []
    current_h2 = "默认/其他"
    current_h3 = None
    current_h3_texts = []
    h2_direct = []
    h2_had_h3 = False

    def flush_h3():
        nonlocal current_h3, current_h3_texts
        if current_h3:
            texts = [t for t in current_h3_texts if is_probably_prompt_text(t, permissive=permissive)]
            if texts:
                prompt = "\n".join(texts).strip()
                entries.append({
                    "source": source,
                    "category": current_h2,
                    "alias": current_h3,
                    "prompt": prompt,
                    "kind": "h3",
                    "file": str(path),
                })
        current_h3 = None
        current_h3_texts = []

    def flush_h2_direct():
        nonlocal h2_direct, h2_had_h3
        texts = [t for t in h2_direct if is_probably_prompt_text(t, permissive=permissive)]
        if texts and not h2_had_h3:
            if len(texts) == 1:
                entries.append({
                    "source": source,
                    "category": current_h2,
                    "alias": current_h2,
                    "prompt": texts[0],
                    "kind": "h2_direct",
                    "file": str(path),
                })
            else:
                for i, t in enumerate(texts, 1):
                    alias = f"{current_h2}-{i:02d}"
                    m = re.match(r"^[0-9０-９]+[，,、.]\s*(.*)$", t)
                    entries.append({
                        "source": source,
                        "category": current_h2,
                        "alias": alias,
                        "prompt": (m.group(1).strip() if m else t),
                        "kind": "h2_line",
                        "file": str(path),
                    })
        h2_direct = []

    for tag, text in blocks:
        if tag == "h1":
            # Do not use h1 as category. It is normally the page title.
            continue
        if tag == "h2":
            flush_h3(); flush_h2_direct()
            current_h2 = clean_heading(text) or "默认/其他"
            current_h3 = None
            h2_direct = []
            h2_had_h3 = False
        elif tag in {"h3", "h4"}:
            flush_h3()
            current_h3 = clean_heading(text)
            current_h3_texts = []
            h2_had_h3 = True
        elif tag in {"p", "pre", "blockquote", "li"}:
            if current_h3:
                current_h3_texts.append(text)
            else:
                h2_direct.append(text)
    flush_h3(); flush_h2_direct()
    return entries


def norm_prompt(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def deterministic_id(prefix: str, text: str) -> str:
    return str(uuid5(NAMESPACE_URL, prefix + "|" + text))


def find_plugin_root(start: Path) -> Path:
    """Find the WeiLin root that owns user_data/prompt_selector."""
    start = start.resolve()
    candidates = [start] + list(start.parents)

    # Direct/ancestor WeiLin layouts.
    for c in candidates:
        if (c / "user_data" / "prompt_selector").exists():
            return c
        if (c / "weilin_tools_pkg" / "user_data" / "prompt_selector").exists():
            return c / "weilin_tools_pkg"

    # Split-plugin layout: find a sibling WeiLin folder under custom_nodes.
    for c in candidates:
        try:
            children = list(c.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and (child / "user_data" / "prompt_selector").exists():
                return child

    raise FileNotFoundError(
        "找不到 WeiLin 的 user_data/prompt_selector。"
        "请确认 WeiLin 插件完整安装，或使用 --plugin-root 指向 WeiLin 插件根目录。"
    )

def collect_html_sources(source: Path, temp_dir: Path):
    html_files = []
    if not source.exists():
        return []
    if source.is_file() and source.suffix.lower() in {".html", ".htm"}:
        html_files.append(source)
    elif source.is_file() and source.suffix.lower() == ".zip":
        target = temp_dir / source.stem
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source, "r") as z:
            z.extractall(target)
        html_files.extend(sorted(target.rglob("*.html")))
        html_files.extend(sorted(target.rglob("*.htm")))
    elif source.is_dir():
        for p in sorted(source.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".html", ".htm"}:
                html_files.append(p)
            elif p.is_file() and p.suffix.lower() == ".zip":
                target = temp_dir / p.stem
                target.mkdir(parents=True, exist_ok=True)
                try:
                    with zipfile.ZipFile(p, "r") as z:
                        z.extractall(target)
                    html_files.extend(sorted(target.rglob("*.html")))
                    html_files.extend(sorted(target.rglob("*.htm")))
                except zipfile.BadZipFile:
                    pass
    # Ignore browser resource folders if any html-like fragments are saved there.
    unique = []
    seen = set()
    for p in html_files:
        ps = str(p.resolve())
        if ps in seen:
            continue
        if "_files" in p.parts:
            continue
        seen.add(ps)
        unique.append(p)
    return unique


def data_paths_for_root(root: Path):
    """Return the WeiLin-owned Prompt Selector database paths."""
    owned = root / "user_data" / "prompt_selector"
    owned.mkdir(parents=True, exist_ok=True)
    return [
        owned / "data.json",
        owned / "default.json",
    ]

def load_base_data(paths):
    for p in paths:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("categories", [])
                return data, p
    return {"version": TOOL_VERSION, "settings": {"language": "zh-CN", "separator": ", ", "save_selection": True}, "categories": []}, None


def backup_existing(paths, backup_dir: Path):
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in paths:
        if p.exists():
            rel = p.name
            # include parent hints so duplicate names do not collide
            hint = "__".join(p.parts[-4:])
            dst = backup_dir / hint
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            copied.append(str(dst))
    return copied


def remove_imported_categories(data: dict, source_prefixes=None, tag_marker="V50-HTML无过滤导入"):
    """Optional cleanup: removes categories/prompts previously generated by this tool."""
    source_prefixes = source_prefixes or []
    new_categories = []
    removed_categories = 0
    removed_prompts = 0
    for cat in data.get("categories", []):
        name = cat.get("name", "")
        if any(name.startswith(prefix + "/") for prefix in source_prefixes):
            removed_categories += 1
            removed_prompts += len(cat.get("prompts", []))
            continue
        prompts = []
        for p in cat.get("prompts", []):
            tags = p.get("tags") or []
            if tag_marker in tags:
                removed_prompts += 1
            else:
                prompts.append(p)
        cat["prompts"] = prompts
        new_categories.append(cat)
    data["categories"] = new_categories
    return removed_categories, removed_prompts


def sort_categories(data: dict):
    original, rest = [], []
    for cat in data.get("categories", []):
        (original if cat.get("name") in DEFAULT_ORIGINAL_CATEGORY_NAMES else rest).append(cat)
    rest.sort(key=lambda c: c.get("name", ""))
    data["categories"] = original + rest


def import_entries(data: dict, entries, now: str):
    existing_norms = set()
    for cat in data.get("categories", []):
        for prompt in cat.get("prompts", []):
            n = norm_prompt(prompt.get("prompt", ""))
            if n:
                existing_norms.add(n)

    cat_map = {cat.get("name"): cat for cat in data.get("categories", [])}

    def get_cat(name: str):
        if name in cat_map:
            return cat_map[name]
        cat = {
            "id": deterministic_id("html-import-category", name),
            "name": name,
            "updated_at": now,
            "prompts": [],
        }
        data.setdefault("categories", []).append(cat)
        cat_map[name] = cat
        return cat

    reports = []
    imported = duplicate_existing = duplicate_new = skipped_empty = 0
    seen_new = set()
    alias_counter = defaultdict(Counter)

    for i, e in enumerate(entries, 1):
        source = e.get("source") or "HTML导入"
        category = e.get("category") or "默认/其他"
        full_category = f"{source}/{category}"
        alias_base = (e.get("alias") or "未命名条目").strip() or "未命名条目"
        prompt_text = e.get("prompt") or ""
        n = norm_prompt(prompt_text)
        status = ""
        reason = ""
        if not n:
            skipped_empty += 1
            status = "skipped"
            reason = "empty_prompt"
        elif n in existing_norms:
            duplicate_existing += 1
            status = "duplicate_existing"
            reason = "normalized_prompt_text_already_exists"
        elif n in seen_new:
            duplicate_new += 1
            status = "duplicate_new"
            reason = "normalized_prompt_text_repeated_in_current_html_batch"
        else:
            cat = get_cat(full_category)
            alias_counter[full_category][alias_base] += 1
            alias = alias_base if alias_counter[full_category][alias_base] == 1 else f"{alias_base} #{alias_counter[full_category][alias_base]}"
            prompt_obj = {
                "id": deterministic_id("html-import-prompt", f"{full_category}|{alias}|{n[:512]}"),
                "alias": alias,
                "prompt": prompt_text,
                "description": f"HTML导入；来源：{source}；分类：{category}；原条目：{alias_base}",
                "image": "",
                "tags": ["HTML导入", "所长法典", source, category, e.get("kind", ""), "V50-HTML无过滤导入"],
                "favorite": False,
                "template": False,
                "created_at": now,
                "updated_at": now,
                "usage_count": 0,
                "last_used": None,
            }
            cat.setdefault("prompts", []).append(prompt_obj)
            seen_new.add(n)
            existing_norms.add(n)
            imported += 1
            status = "imported"
        reports.append({
            "index": i,
            "source": source,
            "category": category,
            "full_category": full_category,
            "alias": alias_base,
            "kind": e.get("kind", ""),
            "status": status,
            "reason": reason,
            "prompt_length": len(prompt_text),
            "file": e.get("file", ""),
            "prompt_preview": re.sub(r"\s+", " ", prompt_text)[:300],
        })

    summary = {
        "raw_candidate_entries": len(entries),
        "raw_unique_prompt_texts": len({norm_prompt(e.get("prompt", "")) for e in entries if norm_prompt(e.get("prompt", ""))}),
        "raw_by_source": dict(Counter(e.get("source", "HTML导入") for e in entries)),
        "raw_source_h2_categories": len({(e.get("source", ""), e.get("category", "")) for e in entries}),
        "imported": imported,
        "duplicate_existing": duplicate_existing,
        "duplicate_new": duplicate_new,
        "skipped_empty": skipped_empty,
    }
    return reports, summary


def write_report(report_rows, summary, report_dir: Path, ts: str):
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"suozhang_html_unfiltered_import_report_{ts}.csv"
    json_path = report_dir / f"suozhang_html_unfiltered_import_summary_{ts}.json"
    cols = ["index", "source", "category", "full_category", "alias", "kind", "status", "reason", "prompt_length", "file", "prompt_preview"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(report_rows)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return csv_path, json_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="HTML -> Prompt Selector shared preset database importer, no keyword/content filtering.")
    ap.add_argument("--source", default=None, help="HTML/HTM file, ZIP file, or folder containing HTML/ZIP files. Default: ./suozhang_html_sources")
    ap.add_argument("--plugin-root", default=None, help="WeiLin plugin root containing user_data/prompt_selector. Auto-detected by default.")
    ap.add_argument("--strict-tag-detect", action="store_true", help="Use stricter prompt-looking detection. Default is permissive.")
    ap.add_argument("--replace-imported", action="store_true", help="Before import, remove categories/prompts previously generated by this V50 tool for the same source prefixes.")
    ap.add_argument("--dry-run", action="store_true", help="Parse and report only; do not write database files.")
    args = ap.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    root = Path(args.plugin_root).resolve() if args.plugin_root else find_plugin_root(script_dir)
    source = Path(args.source).resolve() if args.source else (script_dir / "suozhang_html_sources")
    data_paths = data_paths_for_root(root)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    now = datetime.now().isoformat(timespec="seconds")

    with tempfile.TemporaryDirectory(prefix="html_import_") as tmp:
        html_files = collect_html_sources(source, Path(tmp))
        if not html_files:
            print(f"[ERROR] 没有找到 HTML/HTM 文件。source={source}")
            print("把 .html/.htm 或包含 html 的 .zip 放进 suozhang_html_sources 后再运行。")
            return 2
        entries = []
        per_file = []
        for fp in html_files:
            try:
                parsed = parse_html_file(fp, permissive=not args.strict_tag_detect)
                entries.extend(parsed)
                per_file.append({"file": str(fp), "entries": len(parsed)})
                print(f"[PARSE] {fp.name}: {len(parsed)} entries")
            except Exception as exc:
                per_file.append({"file": str(fp), "entries": 0, "error": repr(exc)})
                print(f"[WARN] 解析失败: {fp} -> {exc}")

    data, loaded_from = load_base_data(data_paths)
    source_prefixes = sorted({e.get("source", "HTML导入") for e in entries})
    removed_categories = removed_prompts = 0
    if args.replace_imported:
        removed_categories, removed_prompts = remove_imported_categories(data, source_prefixes=source_prefixes)

    reports, summary = import_entries(data, entries, now)
    summary.update({
        "tool_version": TOOL_VERSION,
        "source_path": str(source),
        "plugin_root": str(root),
        "loaded_from": str(loaded_from) if loaded_from else "new_empty_data",
        "html_files": per_file,
        "html_file_count": len(html_files),
        "mode": "dry_run" if args.dry_run else "write",
        "filtering": "none; only empty/noise text and exact duplicate prompt text are skipped",
        "strict_tag_detect": bool(args.strict_tag_detect),
        "replace_imported": bool(args.replace_imported),
        "removed_categories_before_import": removed_categories,
        "removed_prompts_before_import": removed_prompts,
    })

    final_category_count = len(data.get("categories", []))
    final_prompt_count = sum(len(c.get("prompts", [])) for c in data.get("categories", []))
    summary["final_category_count"] = final_category_count
    summary["final_prompt_count"] = final_prompt_count

    report_dir = script_dir / "suozhang_html_import_reports"
    csv_path, json_path = write_report(reports, summary, report_dir, ts)

    if not args.dry_run:
        backup_dir = script_dir / "prompt_selector_data_backups" / ts
        backup_existing(data_paths, backup_dir)
        data["version"] = "5.0-html-unfiltered-tool"
        data["last_modified"] = now
        data.setdefault("settings", {})
        data["settings"]["suozhang_html_unfiltered_import"] = {
            "tool_version": TOOL_VERSION,
            "last_imported_at": now,
            "source_path": str(source),
            "raw_candidate_entries": summary["raw_candidate_entries"],
            "imported": summary["imported"],
            "duplicate_existing": summary["duplicate_existing"],
            "duplicate_new": summary["duplicate_new"],
            "filtering": summary["filtering"],
            "category_strategy": "HTML title or filename / H2 heading; H3/H4 heading becomes alias; following paragraphs/list/pre become prompt",
            "dedupe": "normalized exact prompt text across existing data and current batch",
        }
        sort_categories(data)
        for path in data_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"[WRITE] 已写入共享预设库：{len(data_paths)} 个文件")
        print(f"[BACKUP] 原数据库备份：{backup_dir}")
    else:
        print("[DRY-RUN] 未写入数据库。")

    print("\n========== IMPORT SUMMARY ==========")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[REPORT] CSV: {csv_path}")
    print(f"[REPORT] JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
