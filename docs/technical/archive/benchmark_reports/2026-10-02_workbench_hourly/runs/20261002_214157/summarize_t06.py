"""Report only v2 T06 browser receipts. This never operates a browser or production."""
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RUN = Path(__file__).resolve().parent
VERSION = "2-dom-observer-raf-tail"
CASE_IDS = ("T06_insert", "T06_undo")
METRICS = {"ready_ms": "both_ready_ms", "tail_ms": "raf_tail_ms", "total_ms": "duration_ms"}
SOURCES = {"microtask", "mutation_observer", "raf_fallback"}
BASELINE = "M9B synthetic 1063"
TEXT = "M9C_SYNTHETIC_POSITIVE_" + RUN.name
INSERTED = BASELINE + ", " + TEXT
FIXTURE_ID = "m9c-positive-" + RUN.name
CATEGORY_ID = "m9c-category-" + RUN.name
FRESH_N, WARM_N = 3, 7
TOLERANCE_MS = 0.25


def sha(data):
    return hashlib.sha256(data).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stats(values):
    return {"n": len(values), "raw": values,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None}


def state_issues(state, expected, graph_id, label):
    if not isinstance(state, dict):
        return [label + ":missing_state"]
    checks = {
        "valid_target": state.get("valid") is True,
        "graph": state.get("graph_id") == graph_id,
        "branch": state.get("branch") == "a1",
        "positive_node": state.get("node_id") == 1063,
        "negative_node": state.get("side_node_id") == 1030,
        "negative_guard": state.get("side_unchanged") is True and state.get("side_value") == "",
        "node_exact": state.get("node_value") == expected,
        "bound_input_exact": state.get("bound_input_value") == expected,
        "bound_input_connected": state.get("bound_input_connected") is True,
        "foreground_at_observation": state.get("focused") is True and state.get("hidden") is False,
    }
    return [label + ":" + name for name, ok in checks.items() if not ok]


def sample_issues(sample, graph_id, file_page):
    if not isinstance(sample, dict):
        return ["sample_not_object"]
    issues = []
    case = sample.get("case_id")
    if sample.get("collector_version") != VERSION:
        issues.append("wrong_protocol_version")
    if case not in CASE_IDS:
        issues.append("unexpected_case_id")
    if sample.get("cohort") not in ("fresh", "warm"):
        issues.append("unexpected_cohort")
    if type(sample.get("page")) is not int or sample["page"] != file_page:
        issues.append("sample_page_does_not_match_filename")
    if type(sample.get("iteration")) is not int or sample["iteration"] < 1:
        issues.append("invalid_iteration")
    elif sample.get("cohort") == "fresh" and sample["iteration"] != 1:
        issues.append("fresh_must_be_iteration_1")
    elif sample.get("cohort") == "warm" and sample["iteration"] not in range(1, WARM_N + 1):
        issues.append("warm_iteration_outside_1_to_7")
    if sample.get("status") != "ready_after_two_animation_frames":
        issues.append("not_completed_ready_sample")
    if sample.get("click_trusted") is not True:
        issues.append("click_not_trusted")
    if sample.get("blocked") != []:
        issues.append("blocked_request_during_sample")
    if case in CASE_IDS:
        expected_before, expected_final = (BASELINE, INSERTED) if case == "T06_insert" else (INSERTED, BASELINE)
        issues.extend(state_issues(sample.get("before"), expected_before, graph_id, "before"))
        issues.extend(state_issues(sample.get("final"), expected_final, graph_id, "final"))
    numeric = ("start_ms", "end_ms", "node_ready_ms", "bound_input_ready_ms", "both_ready_ms",
               "raf_tail_ms", "duration_ms", "paint_opportunity_ms")
    good_numbers = all(finite(sample.get(key)) and sample[key] >= 0 for key in numeric)
    if not good_numbers:
        issues.append("missing_or_invalid_timing_number")
    else:
        ready, tail, total = sample["both_ready_ms"], sample["raf_tail_ms"], sample["duration_ms"]
        if abs(ready + tail - total) > TOLERANCE_MS:
            issues.append("ready_plus_tail_not_equal_total")
        if abs(sample["end_ms"] - sample["start_ms"] - total) > TOLERANCE_MS:
            issues.append("start_end_not_equal_total")
        if abs(sample["paint_opportunity_ms"] - total) > TOLERANCE_MS:
            issues.append("paint_proxy_not_equal_total")
        if max(sample["node_ready_ms"], sample["bound_input_ready_ms"]) > ready + TOLERANCE_MS:
            issues.append("component_ready_after_both_ready")
    if any(sample.get(key) not in SOURCES for key in ("node_ready_source", "bound_input_ready_source", "both_ready_source")):
        issues.append("missing_v2_ready_observation_source")
    tails = sample.get("raf_tails")
    completed_tails = [t for t in tails if isinstance(t, dict) and not t.get("invalidated")
                       and finite(t.get("first_wait_ms")) and finite(t.get("second_wait_ms"))] if isinstance(tails, list) else []
    if not completed_tails:
        issues.append("missing_v2_raf_callback_tail_evidence")
    if type(sample.get("ready_resets")) is not int or sample["ready_resets"] < 0:
        issues.append("missing_ready_reset_counter")
    requests = sample.get("synthetic_requests")
    if not isinstance(requests, list):
        issues.append("missing_synthetic_request_evidence")
    else:
        for request in requests:
            if not isinstance(request, dict) or request.get("synthetic") is not True:
                issues.append("unexpected_non_synthetic_request")
                continue
            parsed = urlsplit(request.get("path", ""))
            method = request.get("method")
            if method == "POST":
                if parsed.path != "/prompt_selector/prompts/mark_used" or request.get("fixture_id") != FIXTURE_ID:
                    issues.append("unexpected_synthetic_write_target")
            elif method == "GET":
                if parsed.path not in {"/prompt_selector/library/index", "/prompt_selector/library/prompts", "/prompt_selector/library/prompt"}:
                    issues.append("unexpected_synthetic_read_path")
                if parsed.path == "/prompt_selector/library/prompt" and parse_qs(parsed.query).get("prompt_id") != [FIXTURE_ID]:
                    issues.append("unexpected_detail_id")
            else:
                issues.append("unexpected_synthetic_method")
    return issues


def descriptive_flags(entries, key):
    values = [e["sample"][key] for e in entries]
    if not values:
        return {"method": "no_samples", "observations": []}
    middle = statistics.median(values)
    low, high = None, None
    if len(values) >= 4:
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
        spread = q3 - q1
        low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
    flags = []
    for entry, value in zip(entries, values):
        reasons = []
        if low is not None and value < low:
            reasons.append("below_descriptive_1.5_IQR_fence")
        if high is not None and value > high:
            reasons.append("above_descriptive_1.5_IQR_fence")
        if middle > 0 and value >= 2 * middle:
            reasons.append("at_least_twice_group_median")
        if middle > 0 and value <= 0.5 * middle:
            reasons.append("at_most_half_group_median")
        if reasons:
            flags.append({"source_file": entry["source_file"], "source_index": entry["source_index"],
                          "page": entry["sample"]["page"], "iteration": entry["sample"]["iteration"],
                          "value_ms": value, "reasons": reasons, "retained_in_statistics": True})
    return {"method": "For n>=4: inclusive-quartile 1.5-IQR descriptive fences; all n: >=2x or <=0.5x median observations. No inferential or trimming claim.",
            "median_ms": middle, "lower_fence_ms": low, "upper_fence_ms": high, "observations": flags}


def main():
    workflow_path = RUN / "M9c_perf_workflow.json"
    workflow_bytes = workflow_path.read_bytes()
    workflow = json.loads(workflow_bytes.decode("utf-8-sig"))
    graph_id = workflow["id"]
    nodes = {n["id"]: n for n in workflow["nodes"]}
    assert nodes[1063]["widgets_values_named"]["positive"] == BASELINE
    assert nodes[1030]["widgets_values_named"]["text"] == ""
    source_bytes, snapshots, all_entries, document_issues = {}, {}, [], []
    for path in sorted(RUN.glob("t06_page*_v2.json")):
        match = re.fullmatch(r"t06_page(\d+)_v2\.json", path.name)
        if not match:
            continue
        source_bytes[path.name] = path.read_bytes()
        doc = json.loads(source_bytes[path.name].decode("utf-8-sig"))
        snapshots[path.name] = doc
        page = int(match.group(1))
        if not isinstance(doc, dict) or doc.get("collector_version") != VERSION:
            document_issues.append({"source_file": path.name, "issues": ["document_wrong_protocol_v2_required"]})
            continue
        fixture = doc.get("fixture", {})
        bad_fixture = any(fixture.get(k) != v for k, v in {"id": FIXTURE_ID, "category_id": CATEGORY_ID,
                          "baseline": BASELINE, "prompt": TEXT, "inserted": INSERTED}.items())
        checks = fixture.get("checks", {})
        bad_fixture = bad_fixture or any(checks.get(k) is not True for k in ("category_count_matches", "detail_matches", "one_positive_item", "synthetic_only"))
        if bad_fixture:
            document_issues.append({"source_file": path.name, "issues": ["document_fixture_mismatch_or_failed_checks"]})
            continue
        end_issues = []
        if doc.get("active") is not None:
            end_issues.append("collector_still_active_at_snapshot")
        if doc.get("blocked") != []:
            end_issues.append("snapshot_has_blocked_T06_requests_review_required")
        end_issues.extend(state_issues(doc.get("current"), BASELINE, graph_id, "snapshot_current_after_undo"))
        if end_issues:
            document_issues.append({"source_file": path.name, "issues": end_issues})
        for index, sample in enumerate(doc.get("samples", [])):
            all_entries.append({"source_file": path.name, "source_index": index,
                                "sample": sample, "issues": sample_issues(sample, graph_id, page)})
    counts = Counter((e["sample"].get("cohort"), e["sample"].get("case_id"), e["sample"].get("page"), e["sample"].get("iteration"))
                     for e in all_entries if isinstance(e["sample"], dict))
    for entry in all_entries:
        sample = entry["sample"]
        if isinstance(sample, dict) and counts[(sample.get("cohort"), sample.get("case_id"), sample.get("page"), sample.get("iteration"))] != 1:
            entry["issues"].append("duplicate_sample_identity_all_copies_excluded_no_fastest_selection")
    accepted = [e for e in all_entries if not e["issues"]]
    rejected = [e for e in all_entries if e["issues"]]
    groups = []
    for cohort, expected_n in (("fresh", FRESH_N), ("warm", WARM_N)):
        for case in CASE_IDS:
            entries = sorted([e for e in accepted if e["sample"]["cohort"] == cohort and e["sample"]["case_id"] == case],
                             key=lambda e: (e["sample"]["page"], e["sample"]["iteration"]))
            pages = sorted({e["sample"]["page"] for e in entries})
            iterations = [e["sample"]["iteration"] for e in entries]
            correct_shape = (len(pages) == FRESH_N and iterations == [1] * FRESH_N) if cohort == "fresh" else (len(pages) == 1 and iterations == list(range(1, WARM_N + 1)))
            groups.append({"cohort": cohort, "case_id": case, "expected_n": expected_n, "n": len(entries),
                           "complete": len(entries) == expected_n and correct_shape, "pages": pages, "iterations": iterations,
                           "metrics": {name: stats([e["sample"][key] for e in entries]) for name, key in METRICS.items()},
                           "readiness_sources": dict(Counter(e["sample"]["both_ready_source"] for e in entries)),
                           "descriptive_outlier_flags": {name: descriptive_flags(entries, key) for name, key in METRICS.items()},
                           "all_samples_untrimmed": entries})
    pairing_issues = []
    pairs = defaultdict(list)
    for entry in accepted:
        s = entry["sample"]
        pairs[(s["cohort"], s["page"], s["iteration"])].append(entry)
    for (cohort, page, iteration), entries in pairs.items():
        by_case = {e["sample"]["case_id"]: e["sample"] for e in entries}
        if set(by_case) != set(CASE_IDS):
            pairing_issues.append({"cohort": cohort, "page": page, "iteration": iteration, "reason": "missing_insert_or_undo_pair"})
        elif by_case["T06_insert"]["end_ms"] > by_case["T06_undo"]["start_ms"]:
            pairing_issues.append({"cohort": cohort, "page": page, "iteration": iteration, "reason": "undo_precedes_insert_completion"})
    for cohort in ("fresh", "warm"):
        pair_groups = [g for g in groups if g["cohort"] == cohort]
        if pair_groups[0]["pages"] != pair_groups[1]["pages"] or pair_groups[0]["iterations"] != pair_groups[1]["iterations"]:
            pairing_issues.append({"cohort": cohort, "reason": "insert_undo_population_does_not_match"})
    complete = all(g["complete"] for g in groups) and not rejected and not document_issues and not pairing_issues
    notes = [
        "Only exact t06_page<number>_v2.json files are read. Old page1_t06, t06_preliminary*, CPU-profile and version-1 receipts are not timing inputs.",
        "Accepted samples require the v2 protocol on document and sample, trusted click, exact graph/branch/target identity, before/final node and bound-input strings, and unchanged negative node 1030 with empty text.",
        "fresh means one first insert/undo pair on each of three distinct pages. warm means seven complete iterations on one page after preparation; the two cohorts are never pooled.",
        "ready_ms is click-to-observed simultaneous exact node/input readiness. MutationObserver checkpoints or active-only rAF fallback provide an upper bound, not the precise assignment execution timestamp.",
        "tail_ms is time from observed ready to the final callback endpoint. The two rAF callback waits remain in each raw sample; a long tail is not insertion/undo execution cost and does not prove physical pixels were presented.",
        "total_ms=ready_ms+tail_ms; arithmetic is checked within 0.25ms. No tool roundtrip or screenshot interval is added to these internal clocks.",
        "All valid slow/fast observations remain in raw arrays and statistics. Descriptive flags use inclusive 1.5-IQR fences only for n>=4 and median-ratio observations for all n. No trimming, p95 or statistical significance is claimed.",
        "Synthetic list/detail and mark_used responses isolate frontend operations. These are not production backend lookup/persistence latency measurements.",
        "Bound-input visibility is recorded but not required during the modal; it remains the captured target. A visible return-to-UAP mirror check and cleanup receipt are separate final acceptance evidence.",
        "Focus/visibility recorded at before/final snapshots is not continuous focus logging. The collector invalidates observed document-hidden states during its active checks.",
        "This report does not modify production, STATE, the run lock or browser. It does not substitute for final formal-data guards and cleanup acceptance.",
    ]
    result = {"run_id": RUN.name, "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "status": "complete_v2_t06_measurement_collection_only" if complete else "incomplete_or_invalid",
              "collection_complete": complete, "collector_version": VERSION,
              "expected_per_action": {"fresh": FRESH_N, "warm": WARM_N},
              "expected_total_samples": 2 * (FRESH_N + WARM_N), "accepted_samples": len(accepted),
              "source_files": {name: {"sha256": sha(data), "bytes": len(data)} for name, data in source_bytes.items()},
              "workflow_sha256": sha(workflow_bytes), "generator_sha256": sha(Path(__file__).read_bytes()),
              "exact_guard_contract": {"graph_id": graph_id, "branch": "a1", "positive_node": 1063,
                                       "negative_node": 1030, "negative_value": "", "baseline": BASELINE, "inserted": INSERTED},
              "groups": groups, "rejected_samples": rejected, "document_issues": document_issues,
              "pairing_issues": pairing_issues, "limitations": notes,
              "snapshot_end_states": {name: {key: doc.get(key) for key in ("current", "active", "cleaned", "wrapper_active")}
                                      for name, doc in snapshots.items() if isinstance(doc, dict)}}
    for name, data in source_bytes.items():
        if (RUN / name).read_bytes() != data:
            raise RuntimeError(name + " changed while summarizing; rerun after its snapshot is saved")
    assert workflow_path.read_bytes() == workflow_bytes
    json_path, text_path = RUN / "t06_summary.json", RUN / "t06_summary.txt"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8")) == result
    lines = ["M9c T06 v2 隔离插入/撤销计时汇总", "时间：" + result["created_at"],
             f"状态：{result['status']}；有效 {len(accepted)}/{result['expected_total_samples']}。",
             "仅t06_page数字_v2.json；旧preliminary、page1_t06和CPU-profile未混入。", "",
             "cohort/动作 | n/目标 | ready中位数[min,max] | tail中位数[min,max] | total中位数[min,max]"]
    for group in groups:
        columns = []
        for metric in METRICS:
            s = group["metrics"][metric]
            columns.append(f"{s['median']:.1f} [{s['min']:.1f},{s['max']:.1f}]" if s["n"] else "无")
        lines.append(f"{group['cohort']}/{group['case_id']} | {group['n']}/{group['expected_n']} | " + " | ".join(columns))
    lines += ["", "全部原始值（ms，按页号/iteration排序，不剔除慢样本）："]
    for group in groups:
        lines.append(f"{group['cohort']}/{group['case_id']}; pages={group['pages']}; iterations={group['iterations']}")
        for metric in METRICS:
            lines.append(f"  {metric}: {group['metrics'][metric]['raw']}")
    lines += ["", "描述性离群标记（全部保留在统计中）："]
    flagged = 0
    for group in groups:
        for metric, info in group["descriptive_outlier_flags"].items():
            for item in info["observations"]:
                flagged += 1
                lines.append(f"{group['cohort']}/{group['case_id']} {metric}, page={item['page']} iteration={item['iteration']} {item['value_ms']:.1f}ms: {','.join(item['reasons'])}")
    if not flagged:
        lines.append("当前规则未标记；全部raw仍保留。")
    lines += ["", "边界：",
              "ready是节点和绑定输入精确值被观察到的时间上界，不等于赋值指令耗时。tail是其后的rAF回调等待，不当作插入执行时间或已绘制像素。",
              "fresh每动作3页，warm每动作同页7次，分别统计；n小，仅raw/n/median/min/max，不报P95或显著性。",
              "离群仅描述：n>=4用inclusive四分位1.5IQR界；另列>=2倍或<=0.5倍中位数，不剔除。",
              "正向节点1063与绑定输入逐字校验；负向节点1030保持空字符串；图身份、a1分支、trusted click和协议v2均检查。",
              "资料详情/mark_used为合成响应，只代表前端操作，不代表真实后端持久化性能。",
              "绑定输入在弹窗期间可隐藏；返回UAP可见镜像、清理与正式资料守卫仍需单独验收。",
              f"拒收样本={len(rejected)}；文档问题={len(document_issues)}；配对问题={len(pairing_issues)}。详见JSON完整证据，不静默补数。",
              "", "JSON SHA256：" + sha(json_path.read_bytes())]
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "accepted": len(accepted), "expected": result["expected_total_samples"],
                      "rejected": len(rejected), "document_issues": len(document_issues), "pairing_issues": len(pairing_issues),
                      "outputs": [str(json_path), str(text_path)]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
