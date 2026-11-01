"""Review-bound three-way source-body adoption into a new private SQLite stage.

No live writes, identity merges, source-map cleanup, image changes or server
operations. A separately approved legacy representation retains proven edits.
"""
from __future__ import annotations

import argparse
import ast
import copy
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

from audit_current import equal
import stage_current as C
import stage_maintenance as M

SAFE = "default_tail_all_signals_invariant"
QUALITY = "default_tail_only_quality_node_removed_nonquality_primary"
MANUAL_KEEP = "adopt_current_source_body_preserve_classification"
MANUAL_CHANGE = "adopt_current_source_body_with_agent_reviewed_classification"
SPACE = "explicit_ascii_spaces_after_comma_only"
LEGACY_URL = "legacy_url_cleaned_main"
LEGACY_URL_PURE_SHA256 = "03f92cbc04f119d3d4d8b2b5a0b19095c4f072aad2ba8d1127f1aa2da7ad2ce8"
URL_CLAUSE = re.compile(r"\d+(?:\.\d+)?::artist:\s*[\"']?https?://[^\"',]*[\"']?::\s*,?\s*", re.I)
URL_BARE = re.compile(r"[\"']?https?://[^\"',\s]*[\"']?,?\s*", re.I)
SCHEMA = "historical-body-maintenance-review/v1"
require = M.require


def clean_legacy_url_main(text: str) -> str:
    """Exact 2026-09-19 maintenance operation; never an implicit normalizer."""
    cleaned = URL_CLAUSE.sub("", text or "")
    if "http" in cleaned:
        cleaned = URL_BARE.sub("", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip().strip(",").strip()


def checkpoint_prompts(path):
    """Read one physical prompt at a time from the approved older native export."""
    decoder, pattern = json.JSONDecoder(), re.compile(r'"prompts"\s*:\s*\[')
    buffer, position, inside, ended = "", 0, False, False
    with Path(path).open(encoding="utf-8-sig") as stream:
        while True:
            if not inside:
                found = pattern.search(buffer, position)
                if found:
                    position, inside = found.end(), True
                elif ended:
                    return
                else:
                    chunk = stream.read(65536)
                    buffer, position, ended = buffer[max(position, len(buffer) - 128):] + chunk, 0, not chunk
                    continue
            while position < len(buffer) and buffer[position] in " \t\r\n,":
                position += 1
            if position < len(buffer) and buffer[position] == "]":
                position, inside = position + 1, False
                continue
            try:
                prompt, position = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                chunk = stream.read(65536)
                require(bool(chunk), "older physical checkpoint is truncated")
                buffer, position = buffer[position:] + chunk, 0
                continue
            if isinstance(prompt, dict):
                yield prompt


def prepare_legacy_url_proofs(selected, bound):
    """Pin original code/manifest and prove the maintained C in a real old store."""
    checkpoints = {}
    for pid, item in selected.items():
        proof = item.get("proof") or {}
        if proof.get("representation", "raw_main_tags") != LEGACY_URL:
            require(proof.get("representation", "raw_main_tags") == "raw_main_tags", "unknown body representation")
            continue
        require(item["cohort"] == MANUAL_KEEP and item.get("manual", {}).get("representation") == LEGACY_URL,
                "legacy URL representation requires an explicit preserve-decision manual review")
        evidence = proof.get("legacy_url_cleanup")
        require(isinstance(evidence, dict), "legacy URL proof is missing")
        for key in ("source_script", "source_manifest", "physical_checkpoint"):
            require(isinstance(evidence.get(key), str) and bool(evidence[key]), "legacy URL evidence path is missing")
            path = str(Path(evidence[key]).resolve())
            require(path in bound and bound[path] == evidence.get(key + "_sha256"), "legacy URL evidence is not review-bound")
        text = Path(evidence["source_script"]).read_text(encoding="utf-8")
        tree = ast.parse(text)
        nodes = [n for n in tree.body if
                 (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"URL_CLAUSE", "URL_BARE"} for t in n.targets))
                 or (isinstance(n, ast.FunctionDef) and n.name == "clean_url")]
        pure = "\n\n".join(ast.get_source_segment(text, n) for n in nodes)
        require(len(nodes) == 3 and text_hash(pure) == evidence.get("pure_function_sha256") == LEGACY_URL_PURE_SHA256,
                "legacy URL transform differs from the exact approved original function")
        # Original top-level code is never imported or executed.
        manifest = C.read(evidence["source_manifest"])
        matches = [r for r in manifest.get("url_cleanup", {}).get("resource", []) if r.get("id") == pid]
        require(len(matches) == 1 and matches[0].get("after") == proof["before_body"]
                and clean_legacy_url_main(matches[0].get("before")) == proof["before_body"], "legacy cleanup manifest does not prove this maintained body")
        item["legacy_manifest"] = matches[0]
        path = str(Path(evidence["physical_checkpoint"]).resolve())
        checkpoints.setdefault(path, {})[pid] = proof["before_body"]
    for path, expected in checkpoints.items():
        found = set()
        for prompt in checkpoint_prompts(path):
            pid = prompt.get("id")
            if pid in expected:
                require(pid not in found and prompt.get("prompt") == expected[pid], "older physical checkpoint does not retain the exact maintained body")
                found.add(pid)
        require(found == set(expected), "older physical checkpoint owner is missing")


def text_hash(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lines(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def owner_id(row):
    require(row.get("owner", {}).get("store") == "library", "body adoption is library-only")
    return row["owner"]["target_id"]


def strip_with_approved_module(node, module, bodies):
    """Execute the frozen, hash-bound site function; never translate its parser."""
    executable = str(node) if node else shutil.which("node")
    require(executable is not None, "Node is required for the approved website parser")
    runner = ("import fs from 'node:fs';"
              "const code=fs.readFileSync(process.argv[1],'utf8');"
              "const m=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));"
              "const values=JSON.parse(fs.readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(values.map(v=>m.stripNaiDefaultTags(v))));")
    result = subprocess.run([executable, "--input-type=module", "-e", runner, str(module)],
                            input=json.dumps(bodies, ensure_ascii=True), encoding="utf-8", stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    require(result.returncode == 0, "approved website parser execution failed")
    try:
        values = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError("approved website parser returned invalid data") from None
    require(isinstance(values, list) and len(values) == len(bodies) and all(isinstance(v, str) for v in values),
            "approved website parser returned invalid values")
    return values


def signals(category, payload, decision, text):
    P, T, R = (C.native(n) for n in ("semantic_projection", "semantic_taxonomy", "semantic_refinements"))
    candidate = {**payload, "prompt": text}
    subs = P.selector_subcategories(decision, candidate)
    selected = R.extract_refinements(text, subs,
        enable_soft_modifier_cues=P.soft_light_modifier_cue_allowed(decision, category, candidate, subs))
    all_nodes = R.extract_refinements(text, list(T.SUBCATEGORY_PARENTS), enable_soft_modifier_cues=True)
    return {"counts": T.original_count_markers(text), "subcategories": subs,
            "selected": sorted(set(selected)), "all": sorted(set(all_nodes))}


def classify_guard(category, before, after_text, cohort, manual=None, additional_status=None):
    P, T = C.native("semantic_projection"), C.native("semantic_taxonomy")
    decision = before.get("_classification")
    require(isinstance(decision, dict) and decision.get("binding") == P.binding(category, before), "old classification binding is invalid")
    if cohort == SPACE:
        require(isinstance(additional_status, str) and additional_status != "user_confirmed"
                and decision.get("semantic_review_status") == additional_status, "whitespace body's original review status is not explicitly bound")
    else:
        require(decision.get("semantic_review_status") == "codex_import", "body update must preserve the codex_import review status")
    require(decision.get("manual_search_eligible") is True and decision.get("random_pool_eligible") is False
            and decision.get("strict_model_pool_eligible") is False and decision.get("model_scope") == "unknown",
            "body update would alter eligibility policy")
    require(isinstance(after_text, str) and bool(after_text.strip()) and after_text != before["prompt"], "current source body is empty or unchanged")
    require(not any((ord(c) < 32 and c not in "\t\r\n") or ord(c) == 127 for c in after_text), "current body has unsupported control characters")
    a, b = signals(category, before, decision, before["prompt"]), signals(category, before, decision, after_text)
    removed, added = set(a["all"]) - set(b["all"]), set(b["all"]) - set(a["all"])
    require(a["counts"] == b["counts"], "native person-count markers changed")
    require((set(a["all"]) - {"quality.quality"}) == (set(b["all"]) - {"quality.quality"}), "native non-quality signals changed")
    require(a["subcategories"] == b["subcategories"], "stored selector subcategories changed with the proposed body")
    require((set(a["selected"]) - {"quality.quality"}) == (set(b["selected"]) - {"quality.quality"}), "selected non-quality refinements changed")
    if cohort in (SAFE, SPACE):
        require(a == b, "approved invariant cohort has a native signal delta")
    elif cohort == QUALITY:
        require(decision.get("primary_class") != "quality_detail" and removed == {"quality.quality"} and not added,
                "quality-loss cohort is not exactly a non-quality-primary quality-node removal")
    else:
        require(manual is not None and manual.get("agent_fulltext_manual_review_performed") is True
                and manual.get("human_user_confirmation") is False, "manual case lacks an honest agent review")
        require(removed == set(manual.get("native_signal_nodes_removed", [])) and not added,
                "manual review's native signal delta changed")
    after_decision = copy.deepcopy(decision)
    if manual is not None:
        expected_before = copy.deepcopy(manual["classification_before"])
        expected_before.pop("binding", None)
        actual = copy.deepcopy(decision); actual.pop("binding", None)
        require(equal(expected_before, actual), "manual classification baseline changed")
        if cohort == MANUAL_CHANGE:
            after_decision = copy.deepcopy(manual["proposed_classification_without_binding"])
            require(after_decision.get("primary_class") in T.CLASS_LABELS, "manual classification primary is invalid")
            require(after_decision.get("semantic_review_status") == decision["semantic_review_status"]
                    and after_decision.get("manual_search_eligible") is True
                    and after_decision.get("random_pool_eligible") is False
                    and after_decision.get("strict_model_pool_eligible") is False
                    and after_decision.get("model_scope") == decision["model_scope"], "manual review promoted eligibility or invented confirmation")
        else:
            proposed = copy.deepcopy(manual["proposed_classification_without_binding"])
            proposed.pop("binding", None)
            require(equal(actual, proposed), "preserve-classification manual case contains an undeclared decision change")
    return after_decision, {"before": a, "after": b, "removed": sorted(removed), "added": sorted(added)}


def check_inputs(args):
    review = C.read(args.review)
    require(review.get("schema") == SCHEMA and review.get("approved") is True, "body maintenance lacks explicit root approval")
    require(isinstance(review.get("inputs"), dict) and review["inputs"], "body review inputs are not bound")
    bound = {str(Path(p).resolve()): digest for p, digest in review["inputs"].items()}
    for path, digest in bound.items():
        require(C.file_hash(path) == digest, "approved body review input drift")
    for name in ("library", "tags", "cohorts", "candidates", "source_ledger", "manual_review", "strip_module"):
        require(str(Path(getattr(args, name)).resolve()) in bound, "required body input is not approved: " + name)
    if getattr(args, "review_sha256", None):
        require(C.file_hash(args.review) == args.review_sha256, "body approval hash changed")
    cohort_rows, proof_rows = read_lines(args.cohorts), read_lines(args.candidates)
    cohorts = {owner_id(r): r for r in cohort_rows}
    proofs = {owner_id(r): r for r in proof_rows}
    require(len(cohorts) == len(cohort_rows) and len(proofs) == len(proof_rows), "duplicate owner in cohort/three-way evidence")
    manual_doc = C.read(args.manual_review)
    for path, digest in manual_doc.get("input_files", {}).items():
        require(C.file_hash(path) == digest, "agent manual-review evidence changed")
    manual = {owner_id(r): r for r in manual_doc.get("rows", [])}
    selected = {}
    approved_cohorts = review.get("approved_cohorts") or {}
    require(set(approved_cohorts) <= {SAFE, QUALITY}, "unapproved automatic cohort")
    for cohort, count in approved_cohorts.items():
        rows = {pid: row for pid, row in cohorts.items() if row["cohort"] == cohort}
        require(len(rows) == count, "approved cohort count changed")
        for pid in rows:
            require(pid in proofs, "approved body lacks three-way evidence")
            selected[pid] = {"cohort": cohort, "proof": proofs[pid], "cohort_row": cohorts[pid], "manual": None}
    approved_manual = review.get("approved_manual_owners") or []
    require(len(approved_manual) == len(set(approved_manual)), "duplicate manual owner approval")
    for pid in approved_manual:
        require(pid in manual and pid in proofs and pid not in selected, "manual body approval lacks unique evidence")
        row = manual[pid]
        require(row["recommendation"] in (MANUAL_KEEP, MANUAL_CHANGE), "held manual source cannot be adopted")
        selected[pid] = {"cohort": row["recommendation"], "proof": proofs[pid], "cohort_row": cohorts.get(pid), "manual": row}
    held = set(review.get("held_owners") or [])
    require(not held.intersection(selected), "held body owner entered adoption")
    require({pid for pid, row in manual.items() if row["recommendation"].startswith("hold")} <= held, "manual syntax hold must remain explicit")
    extras = review.get("additional_whitespace_sources") or []
    for row in extras:
        pid = owner_id(row)
        require(pid not in selected and pid not in held and row.get("expected_removed_spaces", 0) > 0,
                "additional whitespace source is not an independent approval")
        selected[pid] = {"cohort": SPACE, "additional": row, "manual": None, "cohort_row": None}
    require(selected and len(selected) == review["expected"]["owners"], "approved owner count differs")
    require(sum(v["cohort"] == QUALITY for v in selected.values()) == review["expected"]["quality_node_losses"], "approved quality-loss count differs")
    require(sum(v["cohort"] == MANUAL_CHANGE for v in selected.values()) == review["expected"]["manual_classification_updates"], "manual classification count differs")
    legacy = review.get("approved_legacy_url_cleaned_owners") or []
    require(len(legacy) == len(set(legacy)) and set(legacy) == {
        pid for pid, item in selected.items() if item.get("proof", {}).get("representation") == LEGACY_URL
    }, "legacy URL representation lacks an exact independent owner approval")
    return review, selected


def load_historical(path):
    result = {}
    for row in read_lines(path):
        require(row["source"] not in result, "duplicate historical source identity")
        require(C.digest(row["before_raw"]) == row["old_raw_sha256"] and C.digest(row["after_raw"]) == row["new_raw_sha256"],
                "historical source bytes do not match their approved hashes")
        result[row["source"]] = row
    return result


def source_index(books):
    return {dataset + ":" + eid: (dataset, eid, entry) for dataset, book in books.items() for eid, entry in book["entries"].items()}


def prove_sources(conn, selected, books, historical, release, bound=None):
    """Independently examine every current source, never select by equal body."""
    entries = source_index(books)
    physical = {pid: cid for pid, cid in conn.execute("SELECT id,category_id FROM prompts")}
    row = conn.execute("SELECT value FROM library_meta WHERE key='_source_to_canonical'").fetchone()
    mapping = json.loads(row[0]) if row else {}
    native = {}
    for source, (_, eid, _) in entries.items():
        alias = "codex-" + eid; record = mapping.get(alias)
        native[source] = record["canonical_id"] if isinstance(record, dict) and record.get("canonical_id") in physical else alias if alias in physical else None
    explicit = {}
    for pid, raw in conn.execute("SELECT id,payload FROM prompts"):
        for variant in M.source_refs(json.loads(raw)):
            if not variant.get("dataset") or not variant.get("entry_id"):
                continue
            source = variant["dataset"] + ":" + variant["entry_id"]
            if source in entries and native[source] is None:
                explicit.setdefault(source, set()).add(pid)
    actual = {pid: set() for pid in selected}
    for source, target in native.items():
        if target in selected:
            actual[target].add(source)
        elif target is None:
            choices = explicit.get(source, set())
            if choices.intersection(selected):
                require(len(choices) == 1, "ambiguous actual source provenance affects a body owner")
                actual[next(iter(choices))].add(source)
    categories = {cid: json.loads(raw) for cid, raw in conn.execute("SELECT id,payload FROM categories")}
    prepare_legacy_url_proofs(selected, bound or {})
    for pid, item in selected.items():
        if item["cohort"] == SPACE:
            row = item["additional"]; source = row["source"]
            require(source in historical and source in entries, "additional source is absent from bound data")
            old, new = historical[source]["before_raw"], entries[source][2]
            require(not old.get("characterPrompts") and not new.get("characterPrompts") and not old.get("images") and not new.get("images"), "additional whitespace case contains a character/per-image bundle")
            proof = {"owner": row["owner"], "before_body": old["tags"], "after_candidate_body": new["tags"],
                     "old_component_sources": [{"source": source, "dataset": entries[source][0], "before": old["tags"], "after": new["tags"],
                                                "old_raw_sha256": C.digest(old), "current_raw_sha256": C.digest(new)}]}
            item["proof"] = proof
            payload = json.loads(conn.execute("SELECT payload FROM prompts WHERE id=?", (pid,)).fetchone()[0])
            witness = {"source": source, "dataset": entries[source][0], "entry_id": entries[source][1],
                       "owner": {"store": "library", "target_id": pid}, "owner_method": row.get("owner_method")}
            M.verify_owner(conn, mapping, categories, witness, historical[source], payload)
            if native[source] is None and source not in actual[pid]:
                actual[pid].add(source)  # Bound accepted-registry witness, not a body match.
        proof = item["proof"]
        require(not proof.get("eligible_other_source_main_conflicts") and not proof.get("held_other_source_main_conflicts")
                and not proof.get("ambiguous_provenance_bindings"), "three-way evidence contains unresolved ownership conflicts")
        a, b = proof["before_body"], proof["after_candidate_body"]
        legacy = proof.get("representation") == LEGACY_URL
        require(isinstance(a, str) and isinstance(b, str) and b.strip(), "invalid approved source body")
        if item.get("cohort_row"):
            cr = item["cohort_row"]
            require(cr["before_body_sha256"] == text_hash(a) and cr["after_body_sha256"] == text_hash(b), "cohort body hashes disagree")
        require(proof.get("before_body_sha256", text_hash(a)) == text_hash(a)
                and proof.get("after_candidate_body_sha256", text_hash(b)) == text_hash(b), "three-way body hashes disagree")
        for component in proof["old_component_sources"]:
            source = component["source"]
            require(source in historical and source in entries, "historical body source is absent")
            h = historical[source]; current = entries[source][2]
            C.require_native_owner(conn, mapping, categories, entries[source][1],
                {"store": "library", "target_id": pid, "match": "explicit"})
            require(equal(h["after_raw"], current) and h["new_release"] == release, "historical ledger does not match current source")
            old_main, current_main = h["before_raw"].get("tags"), current.get("tags")
            require(component["before"] == old_main and component["after"] == current_main
                    and component["old_raw_sha256"] == h["old_raw_sha256"]
                    and component["current_raw_sha256"] == C.digest(current), "adoption is not the exact same historical/current raw main field")
            if legacy:
                require(item["legacy_manifest"]["before"] == old_main and a == clean_legacy_url_main(old_main)
                        and b == clean_legacy_url_main(current_main) and "http" not in b.casefold(),
                        "legacy URL adoption does not preserve the exact maintained representation")
            else:
                require(component["before"] == a and component["after"] == b,
                        "adoption is not the exact same historical/current raw main field")
            require(source in actual[pid], "historical component is not owned by this native record")
        require(actual[pid], "body owner has no current source identity")
        for source in actual[pid]:
            main = entries[source][2].get("tags")
            require((clean_legacy_url_main(main) if legacy else main) == b,
                    "another current source bound to this owner has a different main body representation")
        if item["cohort"] != SPACE:
            bound = proof["current_bound_sources"]
            require({r["source"] for r in bound} == actual[pid], "all-source ownership evidence is incomplete or changed")
            for r in bound:
                raw_main = entries[r["source"]][2].get("tags")
                require(r["main_tags"] == raw_main and r["main_sha256"] == text_hash(raw_main)
                        and r["source_raw_sha256"] == C.digest(entries[r["source"]][2]), "current bound-source proof is stale")
                require((r.get("stored_main_text") == b and r.get("stored_main_sha256") == text_hash(b)) if legacy else r["main_tags"] == b,
                        "stored body representation is not explicitly bound")
        item["source_ids"] = sorted(actual[pid])
    return entries, categories


def verify_payload(before, after, category, decision, body):
    allowed = {"prompt", "_classification", "_external_source", "_external_sources"}
    require(equal({k: v for k, v in before.items() if k not in allowed}, {k: v for k, v in after.items() if k not in allowed}), "body stage changed personal/preview/identity fields")
    require(after["prompt"] == body, "body is not the approved exact current main string")
    C.validate_history(before, after, True)
    expected = copy.deepcopy(decision); expected["binding"] = C.binding(category, after)
    require(equal(after.get("_classification"), expected), "classification decision differs from approved preservation/manual review")
    old = before.get("_external_source"); new = after.get("_external_source")
    if old is None:
        require(("_external_source" in before) == ("_external_source" in after) and new is None, "body stage invented a primary source")
    else:
        require(isinstance(new, dict) and M.same_source(new, old.get("dataset"), old.get("entry_id")), "primary source identity changed")


def validate_database(base, staged, changes, stamp):
    with closing(C.connect(base, True)) as a, closing(C.connect(staged, True)) as b:
        require(M.schema(a) == M.schema(b), "body stage changed library schema")
        ids = set(changes)
        old_max = a.execute("SELECT coalesce(max(seq),0) FROM library_journal").fetchone()[0]
        require(b.execute("SELECT value FROM library_meta WHERE key='last_modified'").fetchone() == (C.packed(stamp),), "body revision was not refreshed")
        for table in M.tables(a):
            if table == "prompts":
                require(C.table_hash(a, table, ids, "id") == C.table_hash(b, table, ids, "id"), "unapproved body row changed")
                require(a.execute("SELECT count(*) FROM prompts").fetchone() == b.execute("SELECT count(*) FROM prompts").fetchone(), "body adoption added/deleted/merged identities")
            elif table == "library_meta":
                require(C.table_hash(a, table, {"last_modified"}, "key") == C.table_hash(b, table, {"last_modified"}, "key"), "body stage changed maps/settings/history")
            elif table == "library_journal":
                require(a.execute("SELECT * FROM library_journal ORDER BY seq").fetchall() == b.execute("SELECT * FROM library_journal WHERE seq<=? ORDER BY seq", (old_max,)).fetchall(), "old body journal changed")
                rows = b.execute("SELECT prompt_id,category_id,before,after,op FROM library_journal WHERE seq>?", (old_max,)).fetchall()
                require(len(rows) == len(ids) and {r[0] for r in rows} == ids, "body journal scope differs")
                for pid, cid, before, after, op in rows:
                    change = changes[pid]
                    require(cid == change["category_id"] and op == "update" and before == change["before_raw"] and equal(json.loads(after), change["after"]), "body undo snapshots differ")
            elif table == "sqlite_sequence":
                old = dict(a.execute("SELECT name,seq FROM sqlite_sequence")); expected = dict(old)
                expected["library_journal"] = max(old.get("library_journal", 0), old_max) + len(ids)
                require(dict(b.execute("SELECT name,seq FROM sqlite_sequence")) == expected, "unrelated body-stage sequence changed")
            else:
                require(C.table_hash(a, table) == C.table_hash(b, table), "unaffected body-stage table changed: " + table)
        for pid, change in changes.items():
            row = b.execute("SELECT category_id,payload FROM prompts WHERE id=?", (pid,)).fetchone()
            require(row[0] == change["category_id"] and equal(json.loads(row[1]), change["after"]), "stored body differs from declared adoption")
            verify_payload(change["before"], change["after"], change["category"], change["decision"], change["body"])
        require(b.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "body-stage SQLite integrity failed")


def stage(args):
    output = Path(args.output).resolve()
    require(not output.exists() and all(output != Path(p).resolve() and output not in Path(p).resolve().parents
            for p in (args.review, args.library, args.tags, args.web, args.cohorts, args.candidates, args.source_ledger, args.manual_review, args.strip_module)), "body output must be a new isolated directory")
    review, selected = check_inputs(args)
    before_inputs = {str(Path(p).resolve()): C.file_hash(p) for p in (args.review, args.library, args.tags)}
    catalog = C.read(Path(args.web) / "codexes.json")
    release, books, website_receipts = M.load_web(Path(args.web).resolve(), review, {r["id"] for r in catalog})
    historical = load_historical(args.source_ledger)
    changes, registry, signal_receipts = {}, [], []
    with closing(C.connect(args.library, True)) as conn:
        entries, categories = prove_sources(conn, selected, books, historical, release,
            {str(Path(p).resolve()): digest for p, digest in review["inputs"].items()})
        parser_ids = [pid for pid, item in selected.items() if item["cohort"] in (SAFE, QUALITY)]
        stripped = strip_with_approved_module(getattr(args, "node", None), args.strip_module,
                    [selected[pid]["proof"]["before_body"] for pid in parser_ids])
        for pid, value in zip(parser_ids, stripped):
            require(value == selected[pid]["proof"]["after_candidate_body"], "current main field is not the exact approved website default-tail result")
        for pid, item in selected.items():
            row = conn.execute("SELECT category_id,payload FROM prompts WHERE id=?", (pid,)).fetchone()
            require(row is not None, "approved body owner is missing")
            cid, raw = row; before = json.loads(raw); a, b = item["proof"]["before_body"], item["proof"]["after_candidate_body"]
            require(before.get("prompt") == a, "actual maintained body is no longer exact historical A")
            if item["cohort"] == SPACE:
                require(re.sub(r"(?<=,) +", "", a) == b and len(a) - len(b) == item["additional"]["expected_removed_spaces"], "additional body is not exactly the declared ASCII comma-space removal")
            manual = item.get("manual")
            if manual:
                require(manual["before_body"] == a and manual["after_candidate_body"] == b
                        and manual["before_body_sha256"] == text_hash(a) and manual["after_body_sha256"] == text_hash(b), "manual source bodies differ from bound evidence")
            decision, delta = classify_guard(categories[cid], before, b, item["cohort"], manual,
                item.get("additional", {}).get("review_status"))
            if item["proof"].get("representation") == LEGACY_URL:
                require(delta["before"] == delta["after"], "legacy URL representation must preserve all native signals")
            # Keep current snapshots and the primary in their original order;
            # an unchanged primary remains retained in place.
            after = copy.deepcopy(before)
            after["prompt"] = b
            appended = 0
            for source in item["source_ids"]:
                dataset, eid, entry = entries[source]
                existing = [v for v in M.source_refs(after) if M.same_source(v, dataset, eid) and equal(v.get("raw_entry"), entry)]
                legacy = item["proof"].get("representation") == LEGACY_URL
                if not existing or legacy:
                    v = C.variant(dataset, entry, release); v["dataset_title"] = books[dataset]["meta"].get("title") or "原站说明"
                    if legacy:
                        v["stored_body_maintenance"] = {"representation": LEGACY_URL, "before_body": a, "after_body": b,
                            "transform_pure_sha256": LEGACY_URL_PURE_SHA256,
                            "legacy_cleanup": copy.deepcopy(item["proof"]["legacy_url_cleanup"]),
                            "historical_raw_sources": [{"source": c["source"], "raw_entry": copy.deepcopy(historical[c["source"]]["before_raw"])}
                                for c in item["proof"]["old_component_sources"]]}
                    after = M.append_variant(after, v); appended += 1
                registry.append({"source": source, "dataset": dataset, "entry_id": eid, "target_id": pid, "store": "library",
                                 "source_sha256": C.digest(entry), "body_sha256": text_hash(b), "current_raw_snapshot_verified": True,
                                 "stored_body_representation": LEGACY_URL if legacy else "raw_main_tags",
                                 "stored_body_equals_raw_main": b == entry.get("tags")})
            after["_classification"] = copy.deepcopy(decision)
            after["_classification"]["binding"] = C.binding(categories[cid], after)
            verify_payload(before, after, categories[cid], decision, b)
            changes[pid] = {"category_id": cid, "category": categories[cid], "before_raw": raw, "before": before,
                            "after": after, "decision": decision, "body": b, "cohort": item["cohort"]}
            signal_receipts.append({"target_id": pid, "cohort": item["cohort"], "before_body_sha256": text_hash(a), "after_body_sha256": text_hash(b),
                                    "signals": delta, "current_sources": item["source_ids"], "source_snapshots_appended": appended,
                                    "human_confirmation_invented": False})
    output.mkdir(parents=True)
    C.backup(args.library, output / "library.sqlite3")
    stamp = datetime.now(timezone.utc).isoformat()
    with closing(C.connect(output / "library.sqlite3")) as conn:
        for pid, change in changes.items():
            conn.execute("UPDATE prompts SET payload=? WHERE id=?", (C.packed(change["after"]), pid))
            conn.execute("INSERT INTO library_journal(at,op,prompt_id,category_id,before,after) VALUES (?,?,?,?,?,?)",
                         (stamp, "update", pid, change["category_id"], change["before_raw"], C.packed(change["after"])))
        conn.execute("UPDATE library_meta SET value=? WHERE key='last_modified'", (C.packed(stamp),))
        conn.commit(); C.export_document(conn, output / "data.json")
        sync = C.native("shared_sync")
        with closing(C.connect(args.tags, True)) as tags:
            pairs = sync.build_pairs(tags.execute("SELECT t_uuid,text FROM tag_tags"),
                                     ((pid, json.loads(raw).get("prompt")) for pid, raw in conn.execute("SELECT id,payload FROM prompts")))
        C.save(output / "shared_pairs.json", {"version": sync.PAIR_VERSION, "generated_at": stamp, "library_revision": stamp, **pairs})
    store = C.native("library_store").LibraryStore(output / "library.sqlite3")
    try:
        require(store.verify_document_equals(C.read(output / "data.json")).get("equal") is True, "body export differs from native library")
    finally:
        store.close()
    validate_database(args.library, output / "library.sqlite3", changes, stamp)
    require(all(C.file_hash(path) == digest for path, digest in before_inputs.items()), "body staging modified a readonly input")
    for item in registry:
        payload = changes[item["target_id"]]["after"]
        require(any(M.same_source(v, item["dataset"], item["entry_id"]) and equal(v.get("raw_entry"), entries[item["source"]][2])
                    for v in M.source_refs(payload)), "current full source snapshot missing after body adoption")
    result = {"passed": True, "revision": stamp, "source_release": release, "updated_library": len(changes),
              "current_source_rows_verified": len(registry), "new_resources": 0, "identity_merges": 0,
              "manual_classification_updates": sum(c["cohort"] == MANUAL_CHANGE for c in changes.values()),
              "declared_quality_loss_cohort": sum(c["cohort"] == QUALITY for c in changes.values()),
              "additional_whitespace_owners": sum(c["cohort"] == SPACE for c in changes.values()),
              "source_snapshots_appended": sum(r["source_snapshots_appended"] for r in signal_receipts),
              "personal_fields_and_original_maps_unchanged": True, "tag_writes": 0, "dictionary_writes": 0,
              "production_modified": False, "website_files": website_receipts, "inputs": before_inputs,
              "held_owners": review.get("held_owners", []), "human_review_claimed": False}
    C.save(output / "stage_review.json", review); C.save(output / "source_registry.json", registry)
    C.save(output / "body_signal_receipts.json", signal_receipts); C.save(output / "stage_validation.json", result)
    C.save(output / "stage_summary.json", {**result, "outputs": {p.name: C.file_hash(p) for p in output.iterdir() if p.is_file() and not p.name.endswith(("-wal", "-shm"))}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "library", "tags", "web", "cohorts", "candidates", "source-ledger", "manual-review", "strip-module", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--review-sha256"); parser.add_argument("--node", type=Path)
    result = stage(parser.parse_args())
    print(json.dumps({k: result[k] for k in ("passed", "updated_library", "current_source_rows_verified", "production_modified")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
