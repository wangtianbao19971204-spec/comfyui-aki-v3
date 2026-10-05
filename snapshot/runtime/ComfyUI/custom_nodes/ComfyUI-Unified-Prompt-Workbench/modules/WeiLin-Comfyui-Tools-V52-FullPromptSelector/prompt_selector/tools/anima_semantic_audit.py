import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.request
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
PLUGIN_DIR = PROMPT_SELECTOR_DIR.parent
sys.path.insert(0, str(PROMPT_SELECTOR_DIR))

from anima_tag_classifier import (  # noqa: E402
    SOURCE_ADULT_LOWER,
    SOURCE_ADULT_UPPER,
    SOURCE_REGULAR,
    classify_prompt,
    load_contract,
)


REFERENCE_SOURCES = (
    (
        SOURCE_REGULAR,
        "https://nai4.top/%E6%B3%95%E5%85%B8/%E6%89%80%E9%95%BF%E5%B8%B8%E8%A7%84novalai%E4%B8%AA%E4%BA%BA%E6%B3%95%E5%85%B8/",
    ),
    (
        SOURCE_ADULT_UPPER,
        "https://nai4.top/%E6%B3%95%E5%85%B8/%E6%89%80%E9%95%BF%E8%89%B2%E8%89%B2novalai%E4%B8%AA%E4%BA%BA%E6%B3%95%E5%85%B8%E4%B8%8A/",
    ),
    (
        SOURCE_ADULT_LOWER,
        "https://nai4.top/%E6%B3%95%E5%85%B8/%E6%89%80%E9%95%BF%E8%89%B2%E8%89%B2novalai%E4%B8%AA%E4%BA%BA%E6%B3%95%E5%85%B8%E4%B8%8B/",
    ),
)


def normalize_alias(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def fetch_reference_aliases(cache_dir):
    aliases = defaultdict(set)
    page_stats = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for index, (source, url) in enumerate(REFERENCE_SOURCES, start=1):
        cache_path = cache_dir / f"source-{index}.json"
        entries = None
        raw_size = 0
        cache_state = "hit"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("source") == source and cached.get("url") == url:
                    entries = cached.get("entries")
                    raw_size = int(cached.get("source_bytes") or 0)
            except (OSError, ValueError, TypeError):
                entries = None
        if not isinstance(entries, list):
            cache_state = "miss"
            last_error = None
            for attempt in range(1, 4):
                try:
                    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    raw = urllib.request.urlopen(request, timeout=120).read()
                    raw_size = len(raw)
                    soup = BeautifulSoup(raw, "html.parser")
                    section = ""
                    entries = []
                    for heading in soup.find_all(["h2", "h3"]):
                        text = heading.get_text(" ", strip=True)
                        if heading.name == "h2":
                            section = text
                            continue
                        if section and text:
                            entries.append([text, section])
                    cache_path.write_text(
                        json.dumps({
                            "source": source,
                            "url": url,
                            "source_bytes": raw_size,
                            "entries": entries,
                        }, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    if attempt < 3:
                        time.sleep(attempt * 2)
            if last_error is not None:
                page_stats.append({
                    "source": source,
                    "url": url,
                    "error": str(last_error),
                    "cache": "unavailable",
                    "entry_headings": 0,
                })
                continue
        for alias, section in entries:
            aliases[normalize_alias(alias)].add((source, section))
        page_stats.append({
            "source": source,
            "url": url,
            "bytes": raw_size,
            "cache": cache_state,
            "entry_headings": len(entries),
        })
    return aliases, page_stats


def source_context_from_category(category_name):
    normalized = str(category_name or "").replace("／", "/")
    for source in (SOURCE_REGULAR, SOURCE_ADULT_UPPER, SOURCE_ADULT_LOWER):
        prefix = source + "/"
        if normalized.startswith(prefix):
            return source, normalized[len(prefix):].split("/", 1)[0]
    return "", ""


def source_context_for_prompt(prompt, category_name, reference_aliases):
    category_source, category_section = source_context_from_category(category_name)
    matches = set(reference_aliases.get(normalize_alias(prompt.get("alias")), set()))
    if category_source:
        source_matches = {item for item in matches if item[0] == category_source}
        if len(source_matches) == 1:
            return next(iter(source_matches)), "reference_alias"
        return (category_source, category_section), "current_source_category"
    if len(matches) == 1:
        return next(iter(matches)), "reference_alias"
    return ("", ""), "unresolved"


def summarize_decisions(decisions):
    by_status = Counter()
    by_root = Counter()
    by_target = Counter()
    current_anima = 0
    proposed_anima = 0
    auto_changes = 0
    examples = defaultdict(list)
    category_distributions = defaultdict(Counter)

    for decision in decisions:
        status = decision["status"]
        root = decision["root"] or "none"
        target = decision["target"]
        current_category = decision["current_category"]
        by_status[status] += 1
        by_root[root] += 1
        by_target[target] += 1
        if current_category.startswith("Anima/"):
            current_anima += 1
        if target.startswith("Anima/"):
            proposed_anima += 1
        if status == "auto" and target != current_category:
            auto_changes += 1
        category_distributions[current_category][f"{status}\x1f{target}"] += 1
        example_key = f"{status}\x1f{target}"
        if len(examples[example_key]) < 4:
            examples[example_key].append({
                "id": decision["prompt_id"],
                "alias": decision["alias"],
                "current_category": current_category,
                "confidence": decision["confidence"],
                "margin": decision["margin"],
                "reasons": decision["reasons"],
            })

    category_audit = []
    for category, distribution in category_distributions.items():
        if not category.startswith("Anima/"):
            continue
        proposed = []
        for key, count in distribution.most_common():
            status, target = key.split("\x1f", 1)
            proposed.append({"status": status, "target": target, "count": count})
        category_audit.append({
            "category": category,
            "prompt_count": sum(distribution.values()),
            "proposed": proposed,
            "distinct_targets": len({item["target"] for item in proposed}),
        })
    category_audit.sort(key=lambda item: (-item["distinct_targets"], -item["prompt_count"], item["category"]))

    return {
        "by_status": dict(by_status.most_common()),
        "by_root": dict(by_root.most_common()),
        "top_targets": dict(by_target.most_common(80)),
        "current_anima_prompts": current_anima,
        "proposed_anima_prompts": proposed_anima,
        "auto_category_changes": auto_changes,
        "existing_anima_category_audit": category_audit,
        "examples": dict(examples),
    }


def main():
    parser = argparse.ArgumentParser(description="Dry-run WeiLin -> Anima semantic classification.")
    parser.add_argument(
        "--data",
        type=Path,
        default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    source_bytes = args.data.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    data = json.loads(source_bytes)
    contract = load_contract()
    report_dir = args.data.parent / "classification_reports"
    reference_aliases, page_stats = fetch_reference_aliases(report_dir / "reference_cache")

    decisions = []
    context_counts = Counter()
    for category in data.get("categories", []):
        category_name = str(category.get("name") or "")
        for prompt in category.get("prompts", []):
            (source, section), context_method = source_context_for_prompt(
                prompt,
                category_name,
                reference_aliases,
            )
            context_counts[context_method] += 1
            result = classify_prompt(
                prompt,
                current_category=category_name,
                reference_source=source,
                reference_section=section,
                contract=contract,
            )
            decision = result.to_dict()
            decision.update({
                "prompt_id": str(prompt.get("id") or ""),
                "alias": str(prompt.get("alias") or ""),
                "current_category": category_name,
                "context_method": context_method,
            })
            decisions.append(decision)

    summary = summarize_decisions(decisions)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run",
        "contract_version": contract["contract_version"],
        "source_data": {
            "path": str(args.data),
            "sha256": source_hash,
            "last_modified": data.get("last_modified", ""),
            "prompt_count": len(decisions),
        },
        "reference_pages": page_stats,
        "reference_context_counts": dict(context_counts.most_common()),
        "summary": summary,
        "legacy_category_actions": contract.get("legacy_category_actions", []),
        "decisions": decisions,
    }

    if args.output is None:
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output = report_dir / f"anima-semantic-dry-run-{timestamp}.json"
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps({
        "report": str(args.output),
        "source_sha256": source_hash,
        "reference_context_counts": report["reference_context_counts"],
        "summary": {
            key: summary[key]
            for key in (
                "by_status",
                "by_root",
                "current_anima_prompts",
                "proposed_anima_prompts",
                "auto_category_changes",
            )
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
