"""Summarize recorded fresh-page UI timings only; no browser or production writes."""
import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RUN = Path(__file__).resolve().parent
EXPECTED_CASES = ["T01", "T03", "T02", "T04", "T05_artist"]
LABELS = {
    "T01": "新页控制台首次显式重新打开（已自动展开/预渲染）",
    "T03": "新页控制台首次筛选：尺寸",
    "T02": "新页统一工作区首次打开",
    "T04": "新页跨来源首次搜索：hoodie",
    "T05_artist": "新页搜索后返回控制台，首次打开画师",
}
CACHE_MODES = {
    "T01": "fresh_page_first_explicit_reopen",
    "T03": "fresh_page_first_use",
    "T02": "fresh_page_first_use",
    "T04": "fresh_page_first_query",
    "T05_artist": "fresh_page_first_artist_use_after_search",
}
SEARCH_ENDPOINTS = {
    "/prompt_selector/library/prompts": "q",
    "/prompt_selector/tags/page": "q",
    "/api/lm/loras/list": "search",
    "/api/lm/checkpoints/list": "search",
    "/api/lm/embeddings/list": "search",
}


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def evidence(path):
    return {"path": str(path), "sha256": sha_bytes(path.read_bytes())} if path.exists() else None


def stats(values):
    return {"n": len(values), "raw": values,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def sample_issues(sample, expected_pages):
    issues = []
    case = sample.get("case_id")
    if case not in EXPECTED_CASES:
        return ["unexpected_case_id"]
    if type(sample.get("page_round")) is not int or sample["page_round"] not in expected_pages:
        issues.append("page_round_not_in_expected_range")
    if sample.get("cache_mode") != CACHE_MODES[case]:
        issues.append("cache_mode_does_not_match_scene")
    if sample.get("status") != "ready_after_two_animation_frames":
        issues.append("not_completed_ready_sample")
    if sample.get("focused") is not True or sample.get("hidden") is not False:
        issues.append("not_foreground_at_completion")
    duration, dom = sample.get("duration_ms"), sample.get("dom_duration_ms")
    if not (finite_number(duration) and finite_number(dom) and duration >= dom >= 0):
        issues.append("invalid_duration_or_dom_duration")
    requests = sample.get("requests")
    if not isinstance(requests, list) or not all(isinstance(r, dict) for r in requests):
        issues.append("invalid_request_array")
        requests = []
    if case == "T01" and not (sample.get("auto_open_observed") is True and sample.get("pre_rendered") is True):
        issues.append("T01_missing_auto_open_and_pre_rendered_truth")
    if case == "T03" and sample.get("value") != "尺寸":
        issues.append("T03_query_not_expected")
    if case == "T04":
        if sample.get("query") != "hoodie" or sample.get("value") != "hoodie":
            issues.append("T04_query_not_expected")
        matching = set()
        for request in requests:
            url = urlsplit(request.get("path", ""))
            key = SEARCH_ENDPOINTS.get(url.path)
            if key and parse_qs(url.query).get(key) == ["hoodie"]:
                matching.add(url.path)
        if matching != set(SEARCH_ENDPOINTS):
            issues.append("T04_missing_current_query_five_source_resource_evidence_possible_stale_ready")
    if case == "T05_artist" and sample.get("preconditions") != "return_to_console_after_global_search":
        issues.append("artist_missing_return_to_console_precondition")
    return issues


def request_summary(samples):
    data, images, other, totals = [], [], [], []
    for sample in samples:
        counts = Counter(r.get("initiator") for r in sample["requests"])
        data.append(counts["fetch"] + counts["xmlhttprequest"])
        images.append(counts["img"])
        totals.append(len(sample["requests"]))
        other.append(totals[-1] - data[-1] - images[-1])
    return {"data_fetch_xhr": stats(data), "images_img": stats(images),
            "other": stats(other), "total": stats(totals)}


def write_json(path, value):
    assert path.parent == RUN
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-pages", type=int, default=3)
    args = parser.parse_args()
    if args.expected_pages < 1:
        parser.error("--expected-pages must be positive")
    pages = list(range(1, args.expected_pages + 1))
    path = RUN / "fresh_timings.json"
    raw = path.read_bytes() if path.exists() else None
    document = json.loads(raw.decode("utf-8-sig")) if raw is not None else []
    samples = document.get("samples", []) if isinstance(document, dict) else document
    if not isinstance(samples, list):
        raise ValueError("fresh_timings.json must be a sample list or an object with samples")
    # A runner may attach an explicit same-call UI trace for missing metadata.
    # Preserve the original sample and all timing checks; accept no inferred trace.
    supplements = {}
    supplement_errors = []
    for receipt_path in sorted(RUN.glob("page*_artist_precondition_receipt.json")):
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8-sig"))
        index = receipt.get("source_index")
        valid_index = type(index) is int and 0 <= index < len(samples) and isinstance(samples[index], dict)
        sample = samples[index] if valid_index else {}
        matches = (valid_index and sample.get("case_id") == "T05_artist"
                   and sample.get("preconditions") is None
                   and sample.get("cache_mode") == CACHE_MODES["T05_artist"]
                   and sample.get("page_round") == receipt.get("page_round")
                   and receipt.get("preconditions") == "return_to_console_after_global_search"
                   and receipt.get("sample_preserved") is True
                   and isinstance(receipt.get("evidence"), str) and bool(receipt["evidence"].strip())
                   and bool(receipt.get("tab")) and bool(receipt.get("recorded_at")))
        if not matches or index in supplements:
            supplement_errors.append({"path": str(receipt_path), "reason": "supplement_not_unique_or_not_bound_to_missing_artist_metadata"})
            continue
        supplements[index] = {"path": str(receipt_path), "sha256": sha_bytes(receipt_bytes),
                              "source_sample_index": index,
                              "source_sample_sha256": sha_bytes(json.dumps(sample, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
                              "raw_sample_unchanged": True, "receipt": receipt}
    index_by_pair = defaultdict(list)
    for index, sample in enumerate(samples):
        if isinstance(sample, dict):
            index_by_pair[(str(sample.get("case_id")), str(sample.get("page_round")))].append(index)
    accepted = defaultdict(list)
    rejected = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            rejected.append({"source_index": index, "issues": ["sample_not_object"], "sample": sample})
            continue
        issues = sample_issues(sample, pages)
        if index in supplements and "artist_missing_return_to_console_precondition" in issues:
            issues.remove("artist_missing_return_to_console_precondition")
        if len(index_by_pair[(str(sample.get("case_id")), str(sample.get("page_round")))]) != 1:
            issues.append("duplicate_scene_page_pair_all_duplicates_excluded_no_fastest_selection")
        if issues:
            rejected.append({"source_index": index, "issues": issues, "sample": sample})
        else:
            accepted[sample["case_id"]].append((index, sample))
    cases = []
    for case in EXPECTED_CASES:
        pairs = sorted(accepted[case], key=lambda pair: pair[1]["page_round"])
        group = [sample for _, sample in pairs]
        rounds = [sample["page_round"] for sample in group]
        cases.append({"case_id": case, "label": LABELS[case], "cache_mode": CACHE_MODES[case],
                      "expected_n": args.expected_pages, "accepted_n": len(group),
                      "complete": rounds == pages, "page_rounds": rounds,
                      "missing_page_rounds": [page for page in pages if page not in rounds],
                      "source_sample_indices": [index for index, _ in pairs],
                      "duration_ms": stats([s["duration_ms"] for s in group]),
                      "dom_duration_ms": stats([s["dom_duration_ms"] for s in group]),
                      "requests": request_summary(group), "raw_samples": group})
        cases[-1]["supplemental_precondition_evidence"] = [supplements[index] for index, _ in pairs if index in supplements]
    observed_orders = {}
    order_errors = []
    for page in pages:
        order = [s.get("case_id") for s in samples if isinstance(s, dict) and s.get("page_round") == page and s.get("case_id") in EXPECTED_CASES]
        observed_orders[str(page)] = order
        if order != EXPECTED_CASES[:len(order)]:
            order_errors.append({"page_round": page, "observed": order, "expected_order": EXPECTED_CASES})
    complete = all(case["complete"] for case in cases) and not rejected and not order_errors and not supplement_errors
    status = "complete_fresh_timing_collection_only" if complete else "incomplete"
    notes = [
        "Only fresh timing collection is summarized; T06 files are deliberately not read and no parameter correctness result is inferred.",
        "T01 is the first explicit console REOPEN after automatic initial rendering/opening. It is not cold construction or the page's first console display.",
        "Fresh pages share normal HTTP/browser/service caches. No cache-cleared or whole-system cold-start claim is supported.",
        "Fixed sequence: import isolated fixture, allow automatic console open, hide console, T01, T03, clear console filter, T02, T04, return to console, T05_artist.",
        "Artist is first use on that page AFTER global search and return to console; shared modules and data services may already be warm.",
        "T04 requires the five hoodie source requests in its measurement interval. This rejects the prior zero-request same-query stale-ready evidence; preceding empty-query/old-results absence remains a separate browser precondition record.",
        "duration_ms is page event capture to DOM readiness plus two requestAnimationFrame callbacks. Two rAF is a paint-opportunity proxy, not physical pixel presentation; tool and screenshot roundtrip are outside the measurement.",
        "Resource counts cover completed same-origin ResourceTiming entries starting in the interval, excluding /api/jobs. Unfinished and external-origin requests may be absent. Data=fetch/XHR; images=img.",
        "Focused/hidden flags are checked at sample completion, not throughout the entire measured interval.",
        "The production-sized fixture uses short synthetic prompts; this does not establish production long-text performance or model-generation speed.",
        "Report raw values, n, median and min/max only. Three pages are descriptive; no p95 or statistical-significance claim is made.",
        "Missing and invalid samples are retained as missing/rejected. A partial n does not satisfy the three-page target; duplicates are not resolved by choosing the fastest sample.",
        "Missing artist precondition metadata may be supplied only by an explicit runner receipt bound to the exact source index/page; receipt and sample SHA are recorded, and the original sample stays byte-preserved in its source file.",
        "Heap snapshot values are not analyzed here; this report does not establish memory stability or no leaks.",
    ]
    result = {"run_id": RUN.name, "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "status": status, "collection_complete": complete, "expected_pages": pages,
              "expected_total_samples": args.expected_pages * len(EXPECTED_CASES),
              "source_total_samples": len(samples), "accepted_total_samples": sum(c["accepted_n"] for c in cases),
              "source": {"path": str(path), "sha256": sha_bytes(raw) if raw is not None else None},
              "generator_sha256": sha_bytes(Path(__file__).read_bytes()),
              "supporting_evidence": {"fixture": evidence(RUN / "M9c_perf_workflow.json"),
                                      "measurement_script": evidence(RUN / "browser_measurement.js"),
                                      "executed_sources": evidence(RUN / "executed_sources.json")},
              "cases": cases, "rejected_samples": rejected, "observed_case_order_by_page": observed_orders,
              "supplemental_precondition_receipts": list(supplements.values()), "supplement_errors": supplement_errors,
              "order_errors": order_errors, "limitations": notes,
              "T06": {"status": "not_in_this_summary", "read": False}}
    if raw is not None and path.read_bytes() != raw:
        raise RuntimeError("fresh_timings.json changed during summary; rerun against its completed snapshot")
    json_path = RUN / "fresh_timings_summary.json"
    text_path = RUN / "fresh_timings_summary.txt"
    write_json(json_path, result)
    lines = ["M9c 独立新页计时汇总", "时间：" + result["created_at"],
             f"状态：{status}；有效 {result['accepted_total_samples']}/{result['expected_total_samples']}，T06未读取/未汇总。",
             "按页面序号保留原始样本；单位ms。部分n只作当前进度，不代表三页目标完成。", "",
             "场景 | n/目标 | 主耗时原始值 | 中位数 [最小,最大] | 缺失页"]
    for case in cases:
        s = case["duration_ms"]
        values = ", ".join(f"{v:.1f}" for v in s["raw"]) or "无"
        stats_text = f"{s['median']:.1f} [{s['min']:.1f},{s['max']:.1f}]" if s["n"] else "无"
        lines.append(f"{case['case_id']} {case['label']} | {s['n']}/{args.expected_pages} | {values} | {stats_text} | {case['missing_page_rounds']}")
    lines += ["", "缓存和准备边界：",
              "1. T01为导入后已自动展开、已render的控制台首次显式重新打开，不是冷首构建。",
              "2. 同一顺序：T01→T03→清空控制台筛选→T02→T04→返回控制台→画师首次打开。画师的共享依赖已受前置操作影响。",
              "3. 新页面保留正常HTTP/浏览器/服务缓存，不声称完全冷启动。",
              "4. T04只有记录本轮hoodie五来源请求才纳入；空查询且旧结果不存在的前置条件仍需浏览器证据。",
              "5. 主耗时为页面内部事件到DOM就绪后双rAF，是绘制机会代理；工具往返/截图不包含在内。",
              "6. 请求只统计窗口内已完成同源ResourceTiming，排除/api/jobs；data与img分列，不等同全部网络请求。",
              "7. 三页只报告raw/n/median/min/max，不报P95或显著性。短合成文本不代表长提示词负载。",
              "8. 样本末尾可见/焦点标记不代表全程焦点追踪；本报告不作内存或T06参数准确性验收。",
              f"9. 无效样本数：{len(rejected)}；顺序异常：{len(order_errors)}；原因及原始样本保存在JSON，不挑最快或静默补数。",
              f"10. 显式前置条件补充收据：{len(supplements)}；每份绑定原始下标/页号与sample SHA，原始时长和字段未改。收据问题：{len(supplement_errors)}。",
              "", "各场景DOM就绪与请求分解："]
    for case in cases:
        lines.append(f"{case['case_id']}: DOM raw={case['dom_duration_ms']['raw']}; data={case['requests']['data_fetch_xhr']['raw']}; img={case['requests']['images_img']['raw']}; other={case['requests']['other']['raw']}")
    lines += ["", "原始文件SHA256：" + str(result["source"]["sha256"]),
              "JSON SHA256：" + sha_bytes(json_path.read_bytes())]
    assert text_path.parent == RUN
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "accepted": result["accepted_total_samples"],
                      "expected": result["expected_total_samples"], "rejected": len(rejected),
                      "order_errors": len(order_errors), "outputs": [str(json_path), str(text_path)]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
