"""Read-only evidence gate for a website + Word source update batch.

This gate never writes production files or starts/stops ComfyUI. A batch's
import/release implementation must produce the named receipts first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


RECEIPTS = {
    "documents": "document_coverage_receipt.json",
    "stage": "data_validation.json",
    "images": "image_link_validation.json",
    "history": "historical_compatibility.json",
    "classification": "scan_adjudication.json",
    "contract": "stage_contract.json",
    "preflight": "preflight.json",
    "release": "release_receipt.json",
    "live": "live_acceptance.json",
    "live_query": "live_query_contract.json",
    "state": "EXECUTION_STATE.json",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check(manifest: dict, manifest_path: Path, phase: str, current_pointer: Path | None, require_current: bool, current_gap: Path | None = None):
    errors, observations = [], {}

    def require(ok, message):
        if not ok:
            errors.append(message)

    base = (manifest_path.parent / manifest["batch_dir"]).resolve()
    require(manifest.get("schema") == "source-update-batch/v1", "批次清单版本不支持")
    require(not require_current or current_pointer is not None, "要求当前全站交付时必须提供当前网页指针")
    web = base / "sources/web"
    docs = base / "sources/docx"
    pinned = manifest["web_release"]
    require(web.is_dir(), "网站快照目录缺失")
    for name, expected in manifest["source_files"].items():
        path = base / name
        require(path.is_file(), f"来源文件缺失: {name}")
        if path.is_file():
            require(sha(path) == expected, f"来源哈希变化: {name}")
    actual_files = {str(p.relative_to(base)).replace("\\", "/") for folder in (web, docs) for p in folder.glob("*.json")}
    require(set(manifest["source_files"]) == actual_files, "冻结来源清单未覆盖当前全部网页/Word 文件")
    pointer = read(web / "current.json")
    catalog = read(web / "codexes.json")
    website_manifest = read(web / "manifest.json")
    require(pointer.get("release") == pinned, "固定网站版本与指针不符")
    require(website_manifest.get("contentHash", "").startswith(pinned.removeprefix("r-")), "网站清单版本不符")
    require(len(catalog) == manifest["dataset_count"], "资料集数量不符")
    total, imaged = 0, 0
    source_ids = set()
    image_ids = set()
    image_extras = {}
    for meta in catalog:
        name = meta["id"] + (".external.json" if (web / (meta["id"] + ".external.json")).exists() else ".json")
        path = web / name
        require(path.is_file(), f"资料集缺失: {name}")
        if not path.is_file():
            continue
        if name in website_manifest.get("files", {}):
            require(sha(path) == website_manifest["files"][name]["sha256"], f"网站清单哈希不符: {name}")
        entries = read(path)["entries"]
        total += len(entries)
        imaged += sum(bool(e.get("image")) for e in entries)
        for entry in entries:
            key = meta["id"] + ":" + entry["id"]
            require(key not in source_ids, f"网站来源 ID 重复: {key}")
            source_ids.add(key)
            if entry.get("image"):
                image_ids.add(key)
                image_extras[key] = max(0, len(entry.get("images") or []) - 1)
    observations.update(web_release=pinned, web_rows=total, web_imaged_rows=imaged)
    require(total == manifest["web_rows"], "网站实读条数与冻结批次不符")
    require(imaged == manifest["web_imaged_rows"], "网站带图条数与冻结批次不符")

    doc_summary = read(docs / "summary.json")
    require(len(doc_summary) == manifest["document_count"], "Word 文件数量不符")
    for item in doc_summary:
        require(item["sha256"] == manifest["document_sha256"].get(item["file"]), f"Word 原件哈希记录不符: {item['file']}")
    require(set(manifest["document_sha256"]) == {d["file"] for d in doc_summary}, "Word 文件清单不完整")
    doc_rows = read(docs / "entries.json")
    observations["document_rows"] = len(doc_rows)
    require(len(doc_rows) == manifest["document_rows"], "Word 解析条数不符")
    if manifest.get("original_documents"):
        for name, spec in manifest["original_documents"].items():
            path = Path(spec["path"])
            require(path.is_file() and sha(path) == spec["sha256"], f"Word 原件缺失或变化: {name}")
    else:
        observations["original_documents"] = "仅有历史提取收据；新批次必须提供原件路径和哈希"
        require(manifest.get("historical_replay") is True, "新批次缺少 Word 原件哈希验证")

    registry_path = base / "source_registry.json"
    require(registry_path.is_file(), "逐项来源处置清单缺失")
    included_imaged = excluded_imaged = extra_images = 0
    if registry_path.is_file():
        registry = read(registry_path)
        keys = [r["source"] for r in registry]
        require(len(keys) == total and set(keys) == source_ids, "逐项来源处置未覆盖网站实读记录")
        require(len(set(keys)) == len(keys), "逐项来源处置有重复 ID")
        require(all(r.get("disposition") for r in registry), "逐项来源处置有空结论")
        observations["source_registry_rows"] = len(keys)
        for row in registry:
            if row["source"] in image_ids:
                if row["disposition"] in ("excluded", "no_prompt_content"):
                    excluded_imaged += 1
                else:
                    included_imaged += 1
                    extra_images += image_extras[row["source"]]
        require(included_imaged + excluded_imaged == imaged, "带图来源处置与网站不一致")
        observations.update(included_imaged_rows=included_imaged, excluded_imaged_rows=excluded_imaged, additional_source_images=extra_images)

    def receipt(key):
        path = base / RECEIPTS[key]
        require(path.is_file(), f"收据缺失: {key}")
        return read(path) if path.is_file() else {}

    document = receipt("documents")
    require(document.get("passed") is True and document.get("unresolved") == 0, "Word 对照未闭合")
    require(document.get("entries") == manifest["document_rows"], "Word 收据条数不符")
    if phase in ("stage", "delivery"):
        stage = receipt("stage")
        images = receipt("images")
        history = receipt("history")
        classification = receipt("classification")
        contract = receipt("contract")
        preflight = receipt("preflight")
        for name, value in (("结构", stage), ("图片", images), ("历史", history), ("分类扫描", classification), ("索引契约", contract), ("发布预检", preflight)):
            require(value.get("passed") is True, f"{name}收据未通过")
        data_hash = stage.get("data_sha256")
        for name, value in (("图片", images), ("历史", history), ("分类扫描", classification), ("索引契约", contract)):
            require(value.get("data_sha256") == data_hash, f"{name}未绑定同一份暂存数据")
        require(preflight.get("stage_sha256", {}).get("data.json") == data_hash, "预检未绑定暂存数据")
        for name, expected in preflight.get("stage_sha256", {}).items():
            path = base / "stage" / ("prompt_selector/" + name if name.endswith(".py") else name)
            require(path.is_file() and sha(path) == expected, f"暂存文件变化: {name}")
        bound = preflight.get("bound_files", {})
        for name in ("source_registry.json", "data_validation.json", "document_coverage_receipt.json", "image_link_validation.json"):
            matches = [digest for path, digest in bound.items() if path.replace("\\", "/").endswith("/" + name)]
            require(len(matches) == 1 and sha(base / name) == matches[0], f"预检未绑定收据: {name}")
        require(images.get("failures") == 0, "图片校验有失败")
        require(images.get("source_rows_with_verified_preview") == included_imaged, "可纳入带图记录的首图未逐项覆盖")
        if manifest.get("review", {}).get("image_scope") == "all_images":
            require(images.get("all_source_images_verified") == included_imaged + extra_images, "全图交付缺少逐张验证")
        require(classification.get("new_unresolved_flags") == 0, "分类新增未决标记未清零")
        require(manifest.get("review", {}).get("source_hold") is True, "来源保留审核未签收")
        require(manifest.get("review", {}).get("classification") is True, "分类全文审核未签收")
        require(manifest.get("review", {}).get("image_scope") in ("first_preview", "all_images"), "未声明图片交付范围")
        observations["stage_data_sha256"] = data_hash
        observations["first_preview_rows"] = images.get("source_rows_with_verified_preview")
    if phase == "delivery":
        release = receipt("release")
        live = receipt("live")
        live_query = receipt("live_query")
        state = receipt("state")
        require(release.get("passed") is True and release.get("phase") == "accepted" and release.get("applied") is True, "发布事务未验收")
        require(live.get("passed") is True and live.get("index_equal_to_staged_rebuild") is True, "线上逐项/索引验收失败")
        require(live_query.get("passed") is True, "线上查询合同失败")
        require(state.get("status") == "accepted" and state.get("passed") is True, "最终状态未交付")
        require((base / "backup").is_dir(), "回滚备份缺失")
        observations["release_phase"] = release.get("phase")

    if current_pointer:
        current = read(current_pointer)
        current_release = current.get("release", current.get("current_release"))
        observations["current_release"] = current_release
        observations["source_drift"] = current_release != pinned
        if current_release != pinned:
            observations["scope_note"] = "本次只证明固定版本；当前网页新增内容需要新批次"
            require(not require_current, "当前网页版本已变化，不能宣称当前全站已交付")
    if current_gap:
        gap = read(current_gap)
        rows_path = current_gap.parent / gap["rows_file"]
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        require(gap["old_release"] == pinned, "当前差量的基线版本与批次不符")
        require(not current_pointer or gap["current_release"] == observations["current_release"], "当前差量与当前指针不符")
        require(len(rows) == gap["new_image_entries"], "当前差量逐项清单不完整")
        require(len({r["source"] for r in rows}) == len(rows), "当前差量来源 ID 重复")
        require(all(r.get("source_entry_sha256") and r.get("website_image_not_in_prior_release") for r in rows), "当前差量缺来源哈希或新图证据")
        observations["current_new_image_rows"] = len(rows)
    return {"passed": not errors, "phase": phase, "historical_replay": manifest.get("historical_replay", False), "observations": observations, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--phase", choices=("intake", "stage", "delivery"), default="delivery")
    parser.add_argument("--current-pointer", type=Path)
    parser.add_argument("--current-gap", type=Path)
    parser.add_argument("--require-current", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(read(args.manifest), args.manifest.resolve(), args.phase, args.current_pointer, args.require_current, args.current_gap)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
