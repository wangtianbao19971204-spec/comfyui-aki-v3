"""Bind the one historical replay expectation superseded by release .51."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT_PATH = HERE / "historical_replay_amendment.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    assert path.is_relative_to(ROOT.resolve()), path
    return path


CONTRACT = json.loads(CONTRACT_PATH.read_bytes())
assert CONTRACT["schema"] == "round135-batch1-historical-replay-amendment/v1"
BINDING = CONTRACT["binding"]
DECISION = CONTRACT["published_decision"]
CHANGE = CONTRACT["expectation_change"]

LEDGER_PATH = workspace_path(BINDING["ledger_path"])
PATCH_PATH = workspace_path(DECISION["patch_path"])
COMMIT_PATH = workspace_path(DECISION["commit_receipt_path"])
LIVE_PATH = workspace_path(DECISION["live_receipt_path"])
assert sha256(LEDGER_PATH) == BINDING["ledger_sha256"]
assert sha256(PATCH_PATH) == DECISION["patch_sha256"]
assert sha256(COMMIT_PATH) == DECISION["commit_receipt_sha256"]
assert sha256(LIVE_PATH) == DECISION["live_receipt_sha256"]

patch_document = json.loads(PATCH_PATH.read_bytes())
commit_receipt = json.loads(COMMIT_PATH.read_bytes())
live_receipt = json.loads(LIVE_PATH.read_bytes())
assert patch_document["schema"] == "identity-residue-parent-patch/v1"
assert commit_receipt["schema"] == "identity-residue-stage-receipt/v1"
assert commit_receipt["status"] == "committed"
assert live_receipt["passed"] is True
assert commit_receipt["after_sha256"] == live_receipt["data_sha256"] == DECISION["data_sha256"]

matching_patches = [row for row in patch_document["patches"] if row["id"] == BINDING["id"]]
assert len(matching_patches) == 1
PUBLISHED_PATCH = matching_patches[0]
assert PUBLISHED_PATCH["category_id"] == BINDING["category_id"]
assert PUBLISHED_PATCH["source_text_sha256"] == BINDING["prompt_sha256"]
assert PUBLISHED_PATCH["removed"] == [CHANGE["value"]]
assert PUBLISHED_PATCH["added"] == []
assert CHANGE["value"] in PUBLISHED_PATCH["before"]
assert CHANGE["value"] not in PUBLISHED_PATCH["after"]


def apply_historical_replay_amendment(round_number: int, review: dict) -> tuple[dict, bool]:
    if review.get("id") != BINDING["id"]:
        return review, False
    assert round_number == BINDING["round"]
    assert review["n"] == BINDING["review_number"]
    assert review["category_id"] == BINDING["category_id"]
    assert review["prompt_sha256"] == BINDING["prompt_sha256"]
    assert CHANGE["field"] == "retain_parents"
    assert review.get("retain_parents", []).count(CHANGE["value"]) == 1
    updated = copy.deepcopy(review)
    updated["retain_parents"] = [
        value for value in updated["retain_parents"] if value != CHANGE["value"]
    ]
    for key, value in review.items():
        if key != "retain_parents":
            assert updated[key] == value
    return updated, True


def evidence_summary() -> dict:
    return {
        "schema": CONTRACT["schema"],
        "contract_sha256": sha256(CONTRACT_PATH),
        "round": BINDING["round"],
        "id": BINDING["id"],
        "category_id": BINDING["category_id"],
        "prompt_sha256": BINDING["prompt_sha256"],
        "removed_historical_retain_parent": CHANGE["value"],
        "published_patch_sha256": DECISION["patch_sha256"],
        "committed_receipt_sha256": DECISION["commit_receipt_sha256"],
        "live_receipt_sha256": DECISION["live_receipt_sha256"],
        "published_data_sha256": DECISION["data_sha256"],
    }
