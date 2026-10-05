"""Fail-closed helpers for the round-135 batch-2 two-file release.

This module is deliberately side-effect free on import.  It centralizes the
operation-level allowlist, the exact 76,831-record scan scope, staged semantic
loading, minimal-delta checks, and durable receipt helpers used by stage,
preflight, restart, and live verification.
"""

from __future__ import annotations

import copy
import ctypes
from functools import lru_cache
import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sys
import subprocess
import time
import types
from typing import Any, Callable

import psutil

BATCH = Path(__file__).resolve().parent
ROOT = BATCH.parents[1]
REPORTS = ROOT / "benchmark_reports"
EXTENSION = REPORTS / "2026-09-20_consecutive_extension"
FIRST_AUDIT = REPORTS / "2026-09-20_consecutive_audit"
PREVIOUS = REPORTS / "2026-09-23_consecutive_round135_batch1_controlled_radius"
_HISTORICAL_SPEC = importlib.util.spec_from_file_location(
    "round135_batch2_inherited_historical_amendment",
    PREVIOUS / "historical_replay_amendment.py",
)
if _HISTORICAL_SPEC is None or _HISTORICAL_SPEC.loader is None:
    raise ImportError("cannot load inherited historical replay amendment")
_HISTORICAL_MODULE = importlib.util.module_from_spec(_HISTORICAL_SPEC)
_HISTORICAL_SPEC.loader.exec_module(_HISTORICAL_MODULE)
apply_historical_replay_amendment = _HISTORICAL_MODULE.apply_historical_replay_amendment
MODULE = (
    ROOT
    / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules"
    / "WeiLin-Comfyui-Tools-V52-FullPromptSelector"
)
SELECTOR = MODULE / "prompt_selector"
DATA = MODULE / "user_data/prompt_selector/data.json"
PROJECTION = MODULE / "user_data/prompt_selector/semantic_projection.json"
SEMANTIC = SELECTOR / "semantic_refinements.py"
CANDIDATE_SEMANTIC = BATCH / "semantic_refinements_candidate.py"
CANDIDATE_RECEIPT = BATCH / "semantic_candidate_receipt.json"
RULES = BATCH / "context_parent_rules.py"
MANIFEST_PATH = BATCH / "operation_manifest.json"
BASELINE_PATH = BATCH / "baseline_rebase.json"
AMENDMENT_PATH = BATCH / "contract_amendment.json"
CONTRACT_VALIDATION = BATCH / "contract_validation.json"
INVENTORY_DIR = REPORTS / "2026-09-23_consecutive_round135_batch2_expression_gaze_pose_inventory"
INVENTORY = INVENTORY_DIR / "candidate_inventory.jsonl"
LEDGER = INVENTORY_DIR / "fulltext_review_ledger.jsonl"
ELIGIBILITY_RESOLUTION = INVENTORY_DIR / "eligibility_resolution.json"
SECOND_PASS_REVIEW = INVENTORY_DIR / "second_pass_review_receipt.json"

STAGE_RECEIPT = BATCH / "parent_corrections_staged.json"
PATCH_RECEIPT = BATCH / "parent_patch_minimal.json"
INTEGRITY_RECEIPT = BATCH / "staged_integrity.json"
PREFLIGHT_RECEIPT = BATCH / "release_preflight.json"
APPLIED_RECEIPT = BATCH / "parent_corrections_applied.json"
LIVE_RECEIPT = BATCH / "live_verification.json"
BACKEND_CONTROL = BATCH / "backend_generation_in_progress.json"
BACKEND_MANIFEST = BATCH / "backend_generation_success.json"
BACKEND_OUTPUT_NAMES = (
    "backend_linkage_full.json",
    "expected_index.json",
    "expected_count_queries.json",
)
BACKEND_CANDIDATE = BATCH.parent / f"{BATCH.name}_backend_candidate"
ATTEMPTS_DIR = BATCH / "attempts"
PRIOR_BASELINE_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery"
PRIOR_BASELINE_RECOVERY_RECEIPT_DIR = PRIOR_BASELINE_RECOVERY_DIR / "receipts"
PRIOR_BASELINE_SERVICE_RECEIPT = PRIOR_BASELINE_RECOVERY_RECEIPT_DIR / "production_started.json"
PRIOR_BASELINE_RECOVERY_RESULT = PRIOR_BASELINE_RECOVERY_RECEIPT_DIR / "baseline_service_recovery.json"
PRIOR_BASELINE_STDOUT = PRIOR_BASELINE_RECOVERY_DIR / "logs" / "baseline_service.out.log"
PRIOR_BASELINE_STDERR = PRIOR_BASELINE_RECOVERY_DIR / "logs" / "baseline_service.err.log"
FAILED_BASELINE_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery_002"
FAILED_BASELINE_RECOVERY_RECEIPT_DIR = FAILED_BASELINE_RECOVERY_DIR / "receipts"
FAILED_BASELINE_RECOVERY_RESULT = FAILED_BASELINE_RECOVERY_RECEIPT_DIR / "baseline_service_recovery.json"
FAILED_BASELINE_PRIOR_OBSERVATION = FAILED_BASELINE_RECOVERY_RECEIPT_DIR / "prior_recovery_observation.json"
FAILED_BASELINE_LAUNCH_INTENT = FAILED_BASELINE_RECOVERY_RECEIPT_DIR / "launch_intent.json"
FAILED_BASELINE_STDOUT = FAILED_BASELINE_RECOVERY_DIR / "logs" / "baseline_service.out.log"
FAILED_BASELINE_STDERR = FAILED_BASELINE_RECOVERY_DIR / "logs" / "baseline_service.err.log"
FAILED_GEN3_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery_003"
FAILED_GEN3_RECOVERY_RECEIPT_DIR = FAILED_GEN3_RECOVERY_DIR / "receipts"
FAILED_GEN3_RECOVERY_RESULT = FAILED_GEN3_RECOVERY_RECEIPT_DIR / "baseline_service_recovery.json"
FAILED_GEN3_PRIOR_OBSERVATION = FAILED_GEN3_RECOVERY_RECEIPT_DIR / "prior_recovery_observation.json"
FAILED_GEN3_LAUNCH_INTENT = FAILED_GEN3_RECOVERY_RECEIPT_DIR / "launch_intent.json"
FAILED_GEN3_STDOUT = FAILED_GEN3_RECOVERY_DIR / "logs" / "baseline_service.out.log"
FAILED_GEN3_STDERR = FAILED_GEN3_RECOVERY_DIR / "logs" / "baseline_service.err.log"
FAILED_GEN4_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery_004"
FAILED_GEN4_RECOVERY_RECEIPT_DIR = FAILED_GEN4_RECOVERY_DIR / "receipts"
FAILED_GEN4_RECOVERY_RESULT = FAILED_GEN4_RECOVERY_RECEIPT_DIR / "baseline_service_recovery.json"
FAILED_GEN4_PRIOR_OBSERVATION = FAILED_GEN4_RECOVERY_RECEIPT_DIR / "prior_recovery_observation.json"
FAILED_GEN4_LAUNCH_INTENT = FAILED_GEN4_RECOVERY_RECEIPT_DIR / "launch_intent.json"
FAILED_GEN4_STDOUT = FAILED_GEN4_RECOVERY_DIR / "logs" / "baseline_service.out.log"
FAILED_GEN4_STDERR = FAILED_GEN4_RECOVERY_DIR / "logs" / "baseline_service.err.log"
FAILED_GEN5_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery_005"
FAILED_GEN5_RECOVERY_RECEIPT_DIR = FAILED_GEN5_RECOVERY_DIR / "receipts"
FAILED_GEN5_RECOVERY_RESULT = FAILED_GEN5_RECOVERY_RECEIPT_DIR / "baseline_service_recovery.json"
FAILED_GEN5_PRIOR_OBSERVATION = FAILED_GEN5_RECOVERY_RECEIPT_DIR / "prior_recovery_observation.json"
FAILED_GEN5_LAUNCH_INTENT = FAILED_GEN5_RECOVERY_RECEIPT_DIR / "launch_intent.json"
FAILED_GEN5_STDOUT = FAILED_GEN5_RECOVERY_DIR / "logs" / "baseline_service.out.log"
FAILED_GEN5_STDERR = FAILED_GEN5_RECOVERY_DIR / "logs" / "baseline_service.err.log"
FAILED_GEN6_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery_006"
FAILED_GEN6_RECEIPT_DIR = FAILED_GEN6_RECOVERY_DIR / "receipts"
FAILED_GEN6_RESULT = FAILED_GEN6_RECEIPT_DIR / "baseline_service_recovery.json"
FAILED_GEN6_OBSERVATION = FAILED_GEN6_RECEIPT_DIR / "prior_recovery_observation.json"
FAILED_GEN6_INTENT = FAILED_GEN6_RECEIPT_DIR / "launch_intent.json"
FAILED_GEN6_STDOUT = FAILED_GEN6_RECOVERY_DIR / "logs" / "baseline_service.out.log"
FAILED_GEN6_STDERR = FAILED_GEN6_RECOVERY_DIR / "logs" / "baseline_service.err.log"
BASELINE_RECOVERY_DIR = ATTEMPTS_DIR / "pre_attempt_002_baseline_recovery_007"
BASELINE_RECOVERY_RECEIPT_DIR = BASELINE_RECOVERY_DIR / "receipts"
BASELINE_SERVICE_RECEIPT = BASELINE_RECOVERY_RECEIPT_DIR / "production_started.json"
BASELINE_RECOVERY_RESULT = BASELINE_RECOVERY_RECEIPT_DIR / "baseline_service_recovery.json"
BASELINE_PRIOR_OBSERVATION = BASELINE_RECOVERY_RECEIPT_DIR / "prior_recovery_observation.json"
BASELINE_LAUNCH_INTENT = BASELINE_RECOVERY_RECEIPT_DIR / "launch_intent.json"
BASELINE_STDOUT = BASELINE_RECOVERY_DIR / "logs" / "baseline_service.out.log"
BASELINE_STDERR = BASELINE_RECOVERY_DIR / "logs" / "baseline_service.err.log"

WINDOWS_BREAKAWAY_FLAGS = 0x01000208
WINDOWS_BREAKAWAY_MASK = 0x01000000
WINDOWS_DETACHED_PROCESS = 0x00000008
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

CHILD_HANDSHAKE_NONCE_ENV = "CODEX_ROUND135_CHILD_HANDSHAKE_NONCE"
CHILD_HANDSHAKE_RECEIPT_ENV = "CODEX_ROUND135_CHILD_HANDSHAKE_RECEIPT"
CHILD_HANDSHAKE_PYTHONPATH_PRESENT_ENV = "CODEX_ROUND135_CHILD_HANDSHAKE_PYTHONPATH_PRESENT"
CHILD_HANDSHAKE_PYTHONPATH_VALUE_ENV = "CODEX_ROUND135_CHILD_HANDSHAKE_PYTHONPATH_VALUE"
CHILD_HANDSHAKE_BOOTSTRAP_SOURCE = r'''import ctypes
import json
import os
from pathlib import Path
import sys

_NONCE = "CODEX_ROUND135_CHILD_HANDSHAKE_NONCE"
_RECEIPT = "CODEX_ROUND135_CHILD_HANDSHAKE_RECEIPT"
_PATH_PRESENT = "CODEX_ROUND135_CHILD_HANDSHAKE_PYTHONPATH_PRESENT"
_PATH_VALUE = "CODEX_ROUND135_CHILD_HANDSHAKE_PYTHONPATH_VALUE"
_nonce = os.environ.get(_NONCE)
_receipt = os.environ.get(_RECEIPT)
_path_present = os.environ.get(_PATH_PRESENT)
_path_value = os.environ.get(_PATH_VALUE)
_payload = {"nonce": _nonce, "pid": os.getpid()}
try:
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("per_process_user_time", ctypes.c_longlong),
            ("per_job_user_time", ctypes.c_longlong),
            ("limit_flags", wintypes.DWORD),
            ("minimum_working_set", ctypes.c_size_t),
            ("maximum_working_set", ctypes.c_size_t),
            ("active_process_limit", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel.GetProcessTimes.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
    )
    _kernel.GetProcessTimes.restype = wintypes.BOOL
    _created = _FILETIME()
    _exited = _FILETIME()
    _kernel_file = _FILETIME()
    _user_file = _FILETIME()
    if not _kernel.GetProcessTimes(
        _kernel.GetCurrentProcess(), ctypes.byref(_created), ctypes.byref(_exited),
        ctypes.byref(_kernel_file), ctypes.byref(_user_file),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    _filetime = (_created.high << 32) | _created.low
    _payload["create_time_filetime"] = _filetime
    _payload["create_time"] = _filetime / 10000000.0 - 11644473600.0

    _kernel.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    _kernel.GetModuleFileNameW.restype = wintypes.DWORD
    _image = ctypes.create_unicode_buffer(32768)
    _image_length = _kernel.GetModuleFileNameW(None, _image, len(_image))
    if not _image_length:
        raise ctypes.WinError(ctypes.get_last_error())
    _kernel.GetCommandLineW.restype = wintypes.LPWSTR
    _raw = _kernel.GetCommandLineW()

    _in_job = wintypes.BOOL()
    _kernel.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    _kernel.IsProcessInJob.restype = wintypes.BOOL
    if not _kernel.IsProcessInJob(_kernel.GetCurrentProcess(), None, ctypes.byref(_in_job)):
        raise ctypes.WinError(ctypes.get_last_error())
    _job_flags = None
    if _in_job.value:
        _kernel.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        )
        _kernel.QueryInformationJobObject.restype = wintypes.BOOL
        _limits = _BASIC_LIMIT()
        _returned = wintypes.DWORD()
        if not _kernel.QueryInformationJobObject(
            None, 2, ctypes.byref(_limits), ctypes.sizeof(_limits), ctypes.byref(_returned),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        _job_flags = int(_limits.limit_flags)

    _payload.update({
        "schema": "round135-child-startup-handshake/v1",
        "executable": str(Path(sys.executable).resolve()),
        "image_path": str(Path(_image.value).resolve()),
        "raw_command_line": _raw,
        "argv": list(sys.argv),
        "cwd": str(Path.cwd().resolve()),
        "is_process_in_job": bool(_in_job.value),
        "job_limit_flags": _job_flags,
    })
except BaseException as _error:
    _payload["handshake_error"] = repr(_error)
finally:
    _bootstrap_dir = os.path.normcase(os.path.realpath(os.path.dirname(__file__)))
    if _path_present == "1":
        os.environ["PYTHONPATH"] = _path_value or ""
        _restored_path = os.environ.get("PYTHONPATH")
    else:
        os.environ.pop("PYTHONPATH", None)
        _restored_path = None
    for _key in (_NONCE, _RECEIPT, _PATH_PRESENT, _PATH_VALUE):
        os.environ.pop(_key, None)
    sys.path[:] = [
        _path for _path in sys.path
        if os.path.normcase(os.path.realpath(_path or os.getcwd())) != _bootstrap_dir
    ]
    _payload["marker_environment_cleared"] = all(
        _key not in os.environ for _key in (_NONCE, _RECEIPT, _PATH_PRESENT, _PATH_VALUE)
    )
    _payload["restored_pythonpath"] = _restored_path
    _payload["bootstrap_path_removed_from_sys_path"] = all(
        os.path.normcase(os.path.realpath(_path or os.getcwd())) != _bootstrap_dir
        for _path in sys.path
    )
try:
    _temporary_receipt = _receipt + ".tmp"
    with open(_temporary_receipt, "x", encoding="utf-8", newline="\n") as _stream:
        json.dump(_payload, _stream, ensure_ascii=False, sort_keys=True)
        _stream.write("\n")
        _stream.flush()
        os.fsync(_stream.fileno())
    os.replace(_temporary_receipt, _receipt)
except BaseException:
    pass
'''
CHILD_HANDSHAKE_BOOTSTRAP_SHA256 = hashlib.sha256(CHILD_HANDSHAKE_BOOTSTRAP_SOURCE.encode("utf-8")).hexdigest()

EXPECTED_ELIGIBLE = 76831
EXPECTED_TOTALS = {
    "changed_records": 201,
    "parent_slots_added": 206,
    "parent_slots_removed": 0,
    "refinement_nodes_added": 8,
    "refinement_nodes_removed": 0,
}
EXPECTED_PENDING = 4
EXPECTED_TRANSFORM_MARKERS = (
    "version_2026-09-23.27",
    "mouth_eyes.parted_add_parted_mouth",
)
EXPECTED_CONTEXT_CASES = (
    "wide_hyphen", "wide_space", "wide_style_only", "wide_style_template",
    "wide_style_and_subject", "wide_eyes_not_admitted", "wide_negative_weight",
    "wide_written_quote", "shouting_visible", "shouting_speech_bubble_head",
    "shouting_reflection_head", "shouting_no_humans_sound",
    "shouting_no_human_effect", "shouting_no_human_voice",
    "shouting_no_human_but_visible_subject", "shouting_unrelated_portrait",
    "shouting_written_plain", "shouting_negative_weight", "screaming_not_admitted",
    "looking_ahead_closed_eyes", "looking_ahead_plain", "looking_ahead_negative",
    "facing_forward_not_admitted", "forward_not_admitted", "hand_front",
    "arm_front", "foot_front", "limb_negative", "parted_mouth_parent_node",
    "parted_mouth_existing_parent", "parted_lips_inherited",
    "mouth_parted_not_admitted", "parted_mouth_negative",
)
SUPPLEMENTAL_EXCLUSION_LEDGERS = (
    "2026-09-20_consecutive_motion_recall/boundary_extra_ledger.jsonl",
    "2026-09-20_consecutive_object_contexts/refinement_review_ledger.jsonl",
    "2026-09-20_consecutive_parent_contexts/impact_review_ledger.jsonl",
    "2026-09-20_consecutive_parent_contexts/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_attribute_relations/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_attribute_relations/parent_supplement_review_ledger.jsonl",
    "2026-09-21_consecutive_camera_recall/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_context_completion/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_context_precision/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_context_precision/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_evidence_recall/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_evidence_recall/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_language_contexts/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_language_contexts/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_literal_core/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_material_contexts/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_object_boundaries/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_prose_recall/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_prose_recall/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_prose_recall/supplement_review_ledger.jsonl",
    "2026-09-21_consecutive_prose_scene/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_relation_recall/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_relation_recall/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_role_scene/impact_review_ledger.jsonl",
    "2026-09-21_consecutive_role_scene/sparse_parent_review_ledger.jsonl",
    "2026-09-21_consecutive_scene_recall/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_structured_recall/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_subject_contexts/refinement_review_ledger.jsonl",
    "2026-09-21_consecutive_tag_guards/impact_review_ledger.jsonl",
)
EXPECTED_COLLECTION_KINDS = (
    "pose", "clothing", "background", "character", "artist",
    "style_quality", "tag", "model", "image", "resource",
)
EXPECTED_CLASS_ROUTES = {
    "artist_style": "artist",
    "identity": "character",
    "appearance": "character",
    "clothing_accessory": "clothing",
    "pose_action": "pose",
    "expression_gaze": "pose",
    "background_environment": "background",
    "composition_camera": "style_quality",
    "lighting_color": "style_quality",
    "style_medium": "style_quality",
    "quality_detail": "style_quality",
}

RISK = re.compile(
    r"\b(?:toddler|infant|baby|loli|lolicon|shota|mesugaki|child|children|"
    r"underage|teen|young boy|teenage(?:r|rs)?|aged.down|little (?:girl|boy))\b|"
    r"\b(?:age\s*(?:[0-9]|1[0-7])\b|(?:[0-9]|1[0-7])[ -]+years?[ -]+old\b|"
    r"junior high school\b)|未成年|幼女|幼童|小正太|萝莉",
    re.I,
)
MINOR_CATEGORY = re.compile(r"小孩|幼女|幼童|正太|萝莉|未成年")
RULE_PREFILTER = re.compile(
    r"\bwide[ -]eyed\b|\bshouting\b|\blooking ahead\b|"
    r"\b(?:hand|arm|foot) to front\b|\bparted mouth\b",
    re.I,
)
# These are the only lexical gates introduced by the candidate refinement
# source.  Parent deltas independently force a before/after node comparison.
# Keeping this semantic gate exact avoids running the expensive extractor for
# every unrelated occurrence of a device or the verb "clinging".
NODE_PREFILTER = re.compile(
    r"\bparted mouth\b",
    re.I,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def normalized_prefilter_text(body: Any) -> str:
    """Mirror the lossless lexical normalization used by semantic parsing.

    This intentionally stays broader than the actual rules: prefilters may do
    extra work, but they must never skip a record whose normalized positive
    parts can trigger a batch-local parent or refinement delta.
    """
    return re.sub(r"\s+", " ", str(body or "").replace("\\", "").replace("_", " "))


def sha256_path(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def windows_job_status(process_handle=None) -> dict[str, Any]:
    """Return current-process or child Job membership and parent limits.

    Job queries deliberately fail closed.  A child whose membership cannot be
    queried is not treated as detached.
    """

    if os.name != "nt":
        raise OSError("Windows Job APIs are required for detached service launch")
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    handle = process_handle
    if handle is None:
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel32.GetCurrentProcess()
    in_job = wintypes.BOOL()
    if not kernel32.IsProcessInJob(handle, None, ctypes.byref(in_job)):
        raise ctypes.WinError(ctypes.get_last_error())
    flags = None
    if in_job.value:
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        limits = BasicLimitInformation()
        returned = wintypes.DWORD()
        if not kernel32.QueryInformationJobObject(
            None, 2, ctypes.byref(limits), ctypes.sizeof(limits), ctypes.byref(returned),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        flags = int(limits.LimitFlags)
    return {"in_job": bool(in_job.value), "limit_flags": flags}


def process_create_time_filetime(pid: int) -> int:
    """Return a process creation timestamp as its exact Windows FILETIME ticks."""

    if os.name != "nt":
        raise OSError("Windows process identity APIs are required")
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime), ctypes.POINTER(FileTime),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        created, exited, kernel_time, user_time = FileTime(), FileTime(), FileTime(), FileTime()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel_time), ctypes.byref(user_time),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return (int(created.high) << 32) | int(created.low)
    finally:
        kernel32.CloseHandle(handle)


def process_is_in_job(pid: int) -> bool:
    """Query a process by PID, propagating access denied and API failures."""

    if os.name != "nt":
        raise OSError("Windows Job APIs are required for detached service launch")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return bool(windows_job_status(handle)["in_job"])
    finally:
        kernel32.CloseHandle(handle)


def _spawned_identity_alive(pid: int, create_time: float, process_factory, pid_exists_func) -> bool:
    if not pid_exists_func(pid):
        return False
    try:
        return process_factory(pid).create_time() == create_time
    except psutil.NoSuchProcess:
        return False


def _cleanup_spawned_process(child, create_time: float, process_factory, pid_exists_func) -> dict:
    """Terminate, fall back to kill, and confirm the exact spawned identity exited."""

    result = {"terminate_attempted": False, "kill_fallback_attempted": False, "exit_confirmed": False}
    if child.poll() is not None:
        try:
            result["exit_confirmed"] = not _spawned_identity_alive(
                child.pid, create_time, process_factory, pid_exists_func,
            )
        except BaseException as error:
            result["identity_check_error"] = repr(error)
        return result

    process = None
    try:
        process = process_factory(child.pid)
        if process.create_time() != create_time:
            result["identity_mismatch"] = True
            return result
    except psutil.NoSuchProcess:
        if child.poll() is not None:
            result["exit_confirmed"] = not _spawned_identity_alive(
                child.pid, create_time, process_factory, pid_exists_func,
            )
            return result
        result["process_lookup_error"] = "NoSuchProcess while Popen still reports running"
    except BaseException as error:
        result["process_lookup_error"] = repr(error)

    if child.poll() is None:
        result["terminate_attempted"] = True
        try:
            (process.terminate if process is not None else child.terminate)()
        except BaseException as error:
            result["terminate_error"] = repr(error)
        try:
            (process.wait if process is not None else child.wait)(timeout=15)
        except BaseException as error:
            result["terminate_wait_error"] = repr(error)
    if child.poll() is None:
        result["kill_fallback_attempted"] = True
        try:
            (process.kill if process is not None else child.kill)()
        except BaseException as error:
            result["kill_error"] = repr(error)
        try:
            (process.wait if process is not None else child.wait)(timeout=15)
        except BaseException as error:
            result["kill_wait_error"] = repr(error)
    if child.poll() is not None:
        try:
            result["exit_confirmed"] = not _spawned_identity_alive(
                child.pid, create_time, process_factory, pid_exists_func,
            )
        except BaseException as error:
            result["identity_check_error"] = repr(error)
    return result


class DetachedSpawnError(RuntimeError):
    """Launch failed after Popen; expose the exact child for durable cleanup evidence."""

    def __init__(self, message, *, child, create_time, args, cwd, cleanup, launch_isolation=None):
        super().__init__(message)
        self.child = child
        self.create_time = create_time
        self.command_args = list(args)
        self.cwd = cwd
        self.cleanup = cleanup
        self.launch_isolation = copy.deepcopy(launch_isolation)


def prepare_child_startup_handshake(
    environment: dict[str, str], *, args: list[str], cwd: str, allowed_log_dir: Path,
    process_factory=psutil.Process,
    child_job_query=process_is_in_job,
    child_creation_filetime_query=process_create_time_filetime,
) -> tuple[dict[str, Any], Callable[[Any], dict[str, Any]]]:
    """Prepare one-shot sitecustomize injection under the owning attempt logs."""

    allowed = Path(allowed_log_dir).resolve()
    attempts = ATTEMPTS_DIR.resolve()
    require(allowed.is_dir() and allowed.is_relative_to(attempts), "child handshake directory escaped attempts")
    nonce = secrets.token_hex(24)
    workspace = allowed / f".child-handshake-{nonce}"
    bootstrap = workspace / "sitecustomize.py"
    report = workspace / "handshake.json"
    original_present = "PYTHONPATH" in environment
    original_pythonpath = environment.get("PYTHONPATH")
    marker_names = (
        CHILD_HANDSHAKE_NONCE_ENV, CHILD_HANDSHAKE_RECEIPT_ENV,
        CHILD_HANDSHAKE_PYTHONPATH_PRESENT_ENV, CHILD_HANDSHAKE_PYTHONPATH_VALUE_ENV,
    )
    original_markers = {name: (name in environment, environment.get(name)) for name in marker_names}
    context = {
        "nonce": nonce,
        "workspace": workspace,
        "bootstrap": bootstrap,
        "report": report,
        "report_tmp": report.with_name(report.name + ".tmp"),
        "bootstrap_sha256": CHILD_HANDSHAKE_BOOTSTRAP_SHA256,
        "pythonpath_before_present": original_present,
        "pythonpath_before": original_pythonpath,
        "args": list(args),
        "cwd": str(Path(cwd).resolve()),
    }
    # Finish every fallible context calculation before creating the workspace.
    # From this point onward, any failure is inside the rollback-protected block.
    workspace.mkdir()
    try:
        with bootstrap.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(CHILD_HANDSHAKE_BOOTSTRAP_SOURCE)
            stream.flush()
            os.fsync(stream.fileno())
        require(sha256_path(bootstrap) == CHILD_HANDSHAKE_BOOTSTRAP_SHA256, "child handshake bootstrap source SHA drift")
        environment["PYTHONPATH"] = str(workspace) + (os.pathsep + original_pythonpath if original_present and original_pythonpath else "")
        environment[CHILD_HANDSHAKE_NONCE_ENV] = nonce
        environment[CHILD_HANDSHAKE_RECEIPT_ENV] = str(report)
        environment[CHILD_HANDSHAKE_PYTHONPATH_PRESENT_ENV] = "1" if original_present else "0"
        environment[CHILD_HANDSHAKE_PYTHONPATH_VALUE_ENV] = original_pythonpath or ""
    except BaseException as prepare_error:
        if original_present:
            environment["PYTHONPATH"] = original_pythonpath
        else:
            environment.pop("PYTHONPATH", None)
        for name, (was_present, value) in original_markers.items():
            if was_present:
                environment[name] = value
            else:
                environment.pop(name, None)
        try:
            cleanup_child_startup_handshake(context)
        except BaseException as cleanup_error:
            cleanup_error_text = repr(cleanup_error)
            try:
                prepare_error.handshake_workspace_cleanup_error = cleanup_error_text
            except BaseException:
                pass
            try:
                prepare_error.add_note(f"child handshake workspace rollback also failed: {cleanup_error_text}")
            except BaseException:
                pass
        raise

    def verify(child) -> dict[str, Any]:
        deadline = time.monotonic() + 20
        try:
            while not report.is_file() and time.monotonic() < deadline:
                if child.poll() is not None:
                    raise AssertionError(f"child exited before startup handshake: {child.returncode}")
                time.sleep(0.05)
            require(report.is_file() and not report.is_symlink(), "child startup handshake timed out or report is linked")
            raw_report = report.read_bytes()
            child_report = json.loads(raw_report)
            require(child_report.get("schema") == "round135-child-startup-handshake/v1", "child handshake schema drift")
            require("handshake_error" not in child_report, f"child handshake failed: {child_report.get('handshake_error')}")
            require(child_report.get("nonce") == nonce, "child handshake nonce mismatch")
            require(child_report.get("pid") == child.pid, "child handshake PID mismatch")
            process = process_factory(child.pid)
            create_time = process.create_time()
            create_time_filetime = child_creation_filetime_query(child.pid)
            require(child_report.get("create_time_filetime") == create_time_filetime, "child handshake raw create-time mismatch")
            reported_create_time = child_report.get("create_time")
            require(type(reported_create_time) in (int, float) and abs(reported_create_time - create_time) <= 0.01, "child handshake diagnostic create-time drift")
            expected_executable = str(Path(args[0]).resolve())
            require(child_report.get("executable") == expected_executable, "child sys.executable mismatch")
            require(child_report.get("image_path") == str(Path(process.exe()).resolve()) == expected_executable, "child executable image mismatch")
            require(child_report.get("argv") == list(args[1:]), "child parsed argv mismatch")
            require(process.cmdline() == list(args), "child psutil command line mismatch")
            expected_raw = subprocess.list2cmdline(args)
            require(child_report.get("raw_command_line") == expected_raw, "child raw command line mismatch")
            require(child_report.get("cwd") == context["cwd"], "child cwd mismatch")
            require(Path(process.cwd()).resolve() == Path(context["cwd"]), "child process cwd mismatch")
            require(child_report.get("marker_environment_cleared") is True, "child handshake environment marker was not cleared")
            require(child_report.get("bootstrap_path_removed_from_sys_path") is True, "child handshake path remains on sys.path")
            require(child_report.get("restored_pythonpath") == original_pythonpath, "child did not restore original PYTHONPATH")
            in_job = child_report.get("is_process_in_job")
            job_flags = child_report.get("job_limit_flags")
            require(isinstance(in_job, bool), "child Job membership is missing")
            parent_view = child_job_query(child.pid)
            require(parent_view is in_job, "parent and child Job membership reports disagree")
            if in_job:
                require(type(job_flags) is int, "child Job limit flags are unavailable")
                require(job_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0, "child Job has KILL_ON_JOB_CLOSE")
            else:
                require(job_flags is None or type(job_flags) is int, "child Job limit flags have an invalid type")
            verification = {
                "schema": "round135-child-startup-handshake-receipt/v1",
                "nonce": nonce,
                "bootstrap_sha256": context["bootstrap_sha256"],
                "bootstrap_relative_path": str(bootstrap.resolve()),
                "report_sha256": hashlib.sha256(raw_report).hexdigest(),
                "pythonpath_before_present": original_present,
                "pythonpath_before": original_pythonpath,
                "pythonpath_restored": child_report.get("restored_pythonpath"),
                "child_report": child_report,
                "parent_verified_pid": child.pid,
                "parent_verified_create_time": create_time,
                "parent_verified_create_time_filetime": create_time_filetime,
                "parent_verified_executable": expected_executable,
                "parent_verified_args": list(args),
                "parent_verified_cwd": context["cwd"],
                "parent_job_membership_agreed": True,
                "child_job_contract_verified": True,
            }
        except BaseException as verification_error:
            try:
                cleanup_child_startup_handshake(context)
            except BaseException as cleanup_error:
                cleanup_error_text = repr(cleanup_error)
                try:
                    verification_error.handshake_workspace_cleanup_error = cleanup_error_text
                except BaseException:
                    pass
                try:
                    verification_error.add_note(
                        f"child handshake workspace cleanup also failed: {cleanup_error_text}"
                    )
                except BaseException:
                    pass
            raise
        cleanup_child_startup_handshake(context)
        return verification

    return context, verify


def cleanup_child_startup_handshake(context: dict[str, Any]) -> None:
    workspace = Path(os.path.abspath(context["workspace"]))
    allowed = workspace.parent.resolve(strict=True)
    require(workspace.parent == allowed, "child handshake cleanup parent is not a direct resolved log directory")
    require(workspace.name == f".child-handshake-{context['nonce']}", "child handshake workspace name drift")
    bootstrap = workspace / "sitecustomize.py"
    expected_paths = {
        "bootstrap": bootstrap,
        "report_tmp": workspace / "handshake.json.tmp",
        "report": workspace / "handshake.json",
    }
    for key, expected in expected_paths.items():
        require(Path(os.path.abspath(context[key])) == expected, f"child handshake {key} path drift")
    if not os.path.lexists(workspace):
        return
    require(not workspace.is_symlink(), "child handshake workspace is a symlink")
    is_junction = getattr(workspace, "is_junction", None)
    require(not (callable(is_junction) and is_junction()), "child handshake workspace is a junction")
    require(workspace.is_dir(), "child handshake workspace is not a regular directory")
    resolved_workspace = workspace.resolve(strict=True)
    require(resolved_workspace == allowed / workspace.name and resolved_workspace.parent == allowed, "child handshake workspace escaped its owning log directory")
    for key in ("bootstrap", "report_tmp", "report"):
        path = Path(context[key])
        if os.path.lexists(path):
            require(not path.is_dir() or path.is_symlink(), f"child handshake {key} unexpectedly became a directory")
            path.unlink()
    cache_dir = workspace / "__pycache__"
    if os.path.lexists(cache_dir):
        require(not cache_dir.is_symlink() and cache_dir.is_dir(), "child handshake bytecode cache is not a regular directory")
        import importlib.util

        valid_bytecode = {
            Path(importlib.util.cache_from_source(str(bootstrap), optimization=optimization)).absolute()
            for optimization in ("", "1", "2")
        }
        entries = list(cache_dir.iterdir())
        require(all(entry.absolute() in valid_bytecode and entry.is_file() and not entry.is_symlink() for entry in entries), "child handshake bytecode cache contains unexpected entries")
        for entry in entries:
            entry.unlink()
        cache_dir.rmdir()
    if os.path.lexists(workspace):
        require(not any(workspace.iterdir()), "child handshake workspace contains unexpected entries")
        workspace.rmdir()


def launch_detached_windows(
    args: list[str], cwd: str, stdout, stderr, *,
    popen_factory=subprocess.Popen,
    parent_job_query=windows_job_status,
    child_job_query=process_is_in_job,
    process_factory=psutil.Process,
    pid_exists_func=psutil.pid_exists,
    child_handshake_func: Callable[[Any], dict[str, Any]] | None = None,
):
    """Spawn a service only when its inherited Job cannot kill it on close."""

    parent = parent_job_query()
    require(isinstance(parent, dict) and isinstance(parent.get("in_job"), bool), "parent Job status is unavailable")
    parent_flags = parent.get("limit_flags")
    if parent["in_job"]:
        require(isinstance(parent_flags, int), "parent Job flags are unavailable")
    if parent["in_job"] and parent_flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
        require(parent_flags & (JOB_OBJECT_LIMIT_BREAKAWAY_OK | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK),
                "parent Job disallows breakaway; refusing service spawn")
        creationflags = WINDOWS_BREAKAWAY_FLAGS
        strategy = "breakaway"
    else:
        creationflags = WINDOWS_DETACHED_PROCESS | WINDOWS_CREATE_NEW_PROCESS_GROUP
        strategy = "inherit_safe_job"
    child = popen_factory(
        args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        close_fds=True, creationflags=creationflags,
    )
    create_time = None
    try:
        child_process = process_factory(child.pid)
        create_time = child_process.create_time()
        try:
            child_image_path = str(Path(child_process.exe()).resolve())
        except Exception:
            child_image_path = None
        handshake = child_handshake_func(child) if child_handshake_func is not None else None
        in_job = child_job_query(child.pid)
        if handshake is None:
            require(in_job is False, "spawned service remains in a Windows Job without child handshake evidence")
        else:
            child_report = handshake["child_report"]
            require(child_report.get("is_process_in_job") is in_job, "child Job membership changed after handshake")
            flags = child_report.get("job_limit_flags")
            if in_job:
                require(type(flags) is int, "child Job flags are unavailable")
                require(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0, "child Job has KILL_ON_JOB_CLOSE")
        metadata = {
            "requested_creationflags": creationflags,
            "applied_creationflags": creationflags,
            "launch_strategy": strategy,
            "parent_job_in_job": parent["in_job"],
            "parent_job_limit_flags": parent_flags,
            "child_is_process_in_job": in_job,
            "child_job_limit_flags": None if handshake is None else handshake["child_report"].get("job_limit_flags"),
            "child_create_time_filetime": None if handshake is None else handshake["parent_verified_create_time_filetime"],
            "child_detached_verified": not in_job,
            "child_job_contract_verified": handshake is not None,
            "child_create_time": create_time,
            "child_image_path": child_image_path,
            "child_handshake": handshake,
            "verification": "child sitecustomize self-handshake plus parent PID/create-time/args/cwd and IsProcessInJob check",
        }
        setattr(child, "round135_launch_isolation", metadata)
        return child
    except BaseException as launch_error:
        cleanup = None
        if create_time is not None:
            try:
                cleanup = _cleanup_spawned_process(child, create_time, process_factory, pid_exists_func)
            except BaseException as cleanup_error:
                cleanup = {"exit_confirmed": False, "cleanup_error": repr(cleanup_error)}
        else:
            terminate_attempted = False
            kill_attempted = False
            try:
                if child.poll() is None:
                    terminate_attempted = True
                    child.terminate()
                    child.wait(timeout=15)
            except BaseException:
                try:
                    if child.poll() is None:
                        kill_attempted = True
                        child.kill()
                        child.wait(timeout=15)
                except BaseException:
                    pass
            cleanup = {
                "terminate_attempted": terminate_attempted,
                "kill_fallback_attempted": kill_attempted,
                "exit_confirmed": child.poll() is not None,
            }
        metadata = getattr(child, "round135_launch_isolation", None)
        raise DetachedSpawnError(
            f"detached launch verification failed: {launch_error!r}; cleanup={cleanup!r}",
            child=child, create_time=create_time, args=args, cwd=cwd,
            cleanup=cleanup, launch_isolation=metadata,
        ) from launch_error


def _verify_launch_flags(metadata: dict[str, Any]) -> None:
    strategy = metadata.get("launch_strategy")
    if strategy is None:
        # Archived attempts predate the safe-Job inheritance strategy.
        expected = WINDOWS_BREAKAWAY_FLAGS
    elif strategy == "breakaway":
        expected = WINDOWS_BREAKAWAY_FLAGS
        require(metadata.get("parent_job_in_job") is True, "breakaway parent Job drift")
        require(type(metadata.get("parent_job_limit_flags")) is int, "breakaway parent limits missing")
        require(metadata["parent_job_limit_flags"] & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                "breakaway strategy used without a kill-on-close parent")
    elif strategy == "inherit_safe_job":
        expected = WINDOWS_DETACHED_PROCESS | WINDOWS_CREATE_NEW_PROCESS_GROUP
        if metadata.get("parent_job_in_job"):
            flags = metadata.get("parent_job_limit_flags")
            require(type(flags) is int and flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0,
                    "inherited parent Job is not safe")
    else:
        raise AssertionError(f"unknown launch strategy: {strategy!r}")
    require(metadata.get("requested_creationflags") == expected, "requested Windows flags drift")
    require(metadata.get("applied_creationflags") == expected, "applied Windows flags drift")


def launch_isolation_for_child(child, *, child_job_query=None) -> dict[str, Any]:
    metadata = getattr(child, "round135_launch_isolation", None)
    require(isinstance(metadata, dict), "spawn did not provide a detached launch receipt")
    _verify_launch_flags(metadata)
    in_job = metadata.get("child_is_process_in_job")
    require(isinstance(in_job, bool), "child Job membership is missing")
    handshake = metadata.get("child_handshake")
    if handshake is None:
        require(in_job is False, "child is in a Windows Job without a self-handshake")
        require(metadata.get("child_detached_verified") is True, "child detachment was not verified")
    else:
        require(metadata.get("child_job_contract_verified") is True, "child Job contract was not verified")
        require(handshake.get("schema") == "round135-child-startup-handshake-receipt/v1", "child handshake receipt schema drift")
        require(handshake.get("bootstrap_sha256") == CHILD_HANDSHAKE_BOOTSTRAP_SHA256, "child handshake bootstrap SHA drift")
        child_report = handshake.get("child_report", {})
        require(child_report.get("is_process_in_job") is in_job, "child handshake Job membership drift")
        flags = child_report.get("job_limit_flags")
        if in_job:
            require(type(flags) is int, "child Job flags are unavailable")
            require(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0, "child Job has KILL_ON_JOB_CLOSE")
    create_time = metadata.get("child_create_time")
    require(type(create_time) in (int, float) and create_time > 0, "verified child create_time is missing")
    if child_job_query is not None:
        require(child_job_query(int(child.pid)) is in_job, "live child Job membership drift")
    return copy.deepcopy(metadata)


def verify_launch_isolation(receipt: dict, *, child_job_query=process_is_in_job) -> dict:
    metadata = receipt.get("launch_isolation")
    require(isinstance(metadata, dict), "service receipt lacks detached launch contract")
    _verify_launch_flags(metadata)
    in_job = metadata.get("child_is_process_in_job")
    require(isinstance(in_job, bool), "receipt lacks child Job membership")
    handshake = metadata.get("child_handshake")
    if handshake is None:
        require(in_job is False and metadata.get("child_detached_verified") is True, "receipt lacks detached verification")
    else:
        require(metadata.get("child_job_contract_verified") is True, "receipt lacks child Job contract verification")
        require(handshake.get("schema") == "round135-child-startup-handshake-receipt/v1", "receipt child handshake schema drift")
        require(handshake.get("bootstrap_sha256") == CHILD_HANDSHAKE_BOOTSTRAP_SHA256, "receipt child handshake code drift")
        report = handshake.get("child_report", {})
        nonce = handshake.get("nonce")
        require(isinstance(nonce, str) and bool(nonce.strip()), "receipt child handshake nonce is missing")
        require(report.get("nonce") == nonce, "receipt child handshake nonce drift")
        canonical_report = (json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        require(
            handshake.get("report_sha256") == hashlib.sha256(canonical_report).hexdigest(),
            "receipt child handshake report SHA drift",
        )
        require(report.get("is_process_in_job") is in_job, "receipt child Job membership drift")
        require(handshake.get("parent_verified_pid") == receipt.get("pid"), "receipt handshake PID drift")
        require(handshake.get("parent_verified_create_time") == receipt.get("create_time"), "receipt handshake create-time drift")
        require(handshake.get("parent_verified_create_time_filetime") == metadata.get("child_create_time_filetime"), "receipt handshake raw create-time drift")
        require(type(metadata.get("child_create_time_filetime")) is int and metadata["child_create_time_filetime"] > 0, "receipt lacks exact child FILETIME identity")
        require(handshake.get("parent_verified_args") == receipt.get("args"), "receipt handshake args drift")
        require(handshake.get("parent_verified_cwd") == str(Path(receipt.get("cwd", "")).resolve()), "receipt handshake cwd drift")
        require(report.get("pid") == receipt.get("pid"), "child self-reported PID drift")
        report_create_time = report.get("create_time")
        receipt_create_time = receipt.get("create_time")
        require(
            type(report_create_time) in (int, float) and type(receipt_create_time) in (int, float)
            and abs(report_create_time - receipt_create_time) <= 0.01,
            "child self-reported diagnostic create-time drift",
        )
        require(report.get("create_time_filetime") == handshake.get("parent_verified_create_time_filetime"), "child raw create-time drift")
        expected_executable = str(Path(receipt.get("args", [""])[0]).resolve())
        require(handshake.get("parent_verified_executable") == expected_executable, "receipt handshake executable drift")
        require(report.get("executable") == report.get("image_path") == expected_executable, "child self-reported executable drift")
        require(report.get("argv") == list(receipt.get("args", [])[1:]), "child self-reported argv drift")
        require(report.get("raw_command_line") == subprocess.list2cmdline(receipt.get("args", [])), "child self-reported raw command drift")
        require(report.get("cwd") == str(Path(receipt.get("cwd", "")).resolve()), "child self-reported cwd drift")
        require(report.get("marker_environment_cleared") is True, "child handshake markers were not cleared")
        require(report.get("bootstrap_path_removed_from_sys_path") is True, "child bootstrap path remains on sys.path")
        require(report.get("restored_pythonpath") == handshake.get("pythonpath_before"), "child PYTHONPATH restoration receipt drift")
        flags = report.get("job_limit_flags")
        if in_job:
            require(type(flags) is int, "receipt child Job flags are unavailable")
            require(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0, "receipt child Job has KILL_ON_JOB_CLOSE")
    actual = child_job_query(int(receipt["pid"]))
    require(actual is in_job, "live service Job membership drift")
    return metadata


def verify_live_service_identity(
    receipt: dict, *, process_factory=psutil.Process,
    listener_func=None, comfyui_process_func=None,
    child_job_query=process_is_in_job,
    process_filetime_func=process_create_time_filetime,
) -> dict[str, Any]:
    """Verify the PID/create-time/args/cwd identity, unique listener, and detachment."""

    process = process_factory(int(receipt["pid"]))
    require(process.pid == receipt["pid"], "live service PID drift")
    require(process.create_time() == receipt["create_time"], "live service create-time drift")
    require(process.cmdline() == receipt["args"], "live service args drift")
    require(Path(process.cwd()).resolve() == Path(receipt["cwd"]).resolve(), "live service cwd drift")
    launch = verify_launch_isolation(receipt, child_job_query=child_job_query)
    live_create_time_filetime = None
    if launch.get("child_handshake") is not None:
        live_create_time_filetime = process_filetime_func(int(receipt["pid"]))
        require(live_create_time_filetime == launch.get("child_create_time_filetime"), "live service exact FILETIME identity drift")
    if listener_func is not None:
        require(listener_func(8188) == {("127.0.0.1", 8188, receipt["pid"])}, "8188 listener is not unique to the service")
    if comfyui_process_func is not None:
        require(comfyui_process_func() == {receipt["pid"]}, "service is not the unique ComfyUI main.py process")
    return {
        "pid": receipt["pid"], "create_time": receipt["create_time"],
        "create_time_filetime": live_create_time_filetime,
        "args": receipt["args"], "cwd": receipt["cwd"],
        "launch_isolation": launch,
    }


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classification_sha256(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tcp_listener_bindings(port: int = 8188) -> set[tuple[str, int, int | None]]:
    """Return every TCP listener on ``port`` across IPv4 and IPv6."""

    bindings: set[tuple[str, int, int | None]] = set()
    for connection in psutil.net_connections(kind="tcp"):
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        address = str(getattr(connection.laddr, "ip", connection.laddr[0]))
        local_port = int(getattr(connection.laddr, "port", connection.laddr[1]))
        if local_port == port:
            bindings.add((address, local_port, connection.pid))
    return bindings


def comfyui_main_pids(process_iter=psutil.process_iter) -> set[int]:
    """Find every visible ``ComfyUI/main.py`` process, from any checkout.

    All command arguments are inspected so flags such as ``python -u`` cannot
    hide the script position.  Access failures propagate to keep callers from
    claiming exclusivity without a complete process-table view.
    """

    owners: set[int] = set()
    for process in process_iter():
        try:
            process_name = (process.name() or "").casefold()
            if not process_name.startswith(("python", "pypy")):
                continue
            command = process.cmdline() or []
            for raw_argument in command[1:]:
                if not raw_argument or str(raw_argument).startswith("-"):
                    continue
                candidate = Path(str(raw_argument))
                if candidate.name.casefold() != "main.py":
                    continue
                if not candidate.is_absolute():
                    candidate = Path(process.cwd()) / candidate
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if resolved.name.casefold() == "main.py" and resolved.parent.name.casefold().startswith("comfyui"):
                    owners.add(int(process.pid))
                    break
        except psutil.NoSuchProcess:
            continue
    return owners


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_bytes())


GEN1_IDENTITY = (30340, 1790167492.9343352)
FAILED_GEN2_IDENTITY = (9068, 1790170774.0551012)
FAILED_GEN3_IDENTITY = (30108, 1790177025.8938968)
FAILED_GEN4_IDENTITY = (4820, 1790178679.197517)
FAILED_GEN5_IDENTITY = (21256, 1790179435.065915)
FAILED_GEN6_IDENTITY = (17832, 1790179744.280789)


def _baseline_sha256() -> dict[str, str]:
    baseline = read_json(BASELINE_PATH)["rebased_baseline"]
    return {
        "data": baseline["data_sha256"],
        "semantic_refinements": baseline["semantic_refinements_sha256"],
    }


def _exact_receipt_tree(directory: Path, *, log_names: set[str], receipt_names: set[str], label: str) -> None:
    directory = Path(directory)
    require(not directory.is_symlink() and directory.is_dir(), f"{label} directory missing or linked")
    logs = directory / "logs"
    receipts = directory / "receipts"
    require(not logs.is_symlink() and logs.is_dir(), f"{label} log directory missing or linked")
    require(not receipts.is_symlink() and receipts.is_dir(), f"{label} receipt directory missing or linked")
    require({entry.name for entry in directory.iterdir()} == {"logs", "receipts"}, f"{label} has unexpected top-level entries")
    require({entry.name for entry in logs.iterdir()} == log_names, f"{label} log tree drift")
    require({entry.name for entry in receipts.iterdir()} == receipt_names, f"{label} receipt tree drift")
    for entry in (*logs.iterdir(), *receipts.iterdir()):
        require(not entry.is_symlink() and entry.is_file(), f"{label} contains a linked or non-file artifact: {entry}")


def verify_gen1_evidence(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Verify the exact immutable successful generation-1 recovery tree."""

    directory = PRIOR_BASELINE_RECOVERY_DIR if directory is None else Path(directory)
    require(directory.resolve() == PRIOR_BASELINE_RECOVERY_DIR.resolve(), "generation-1 directory path drift")
    paths = {
        "production_started": PRIOR_BASELINE_SERVICE_RECEIPT,
        "baseline_service_recovery": PRIOR_BASELINE_RECOVERY_RESULT,
        "stdout": PRIOR_BASELINE_STDOUT,
        "stderr": PRIOR_BASELINE_STDERR,
    }
    _exact_receipt_tree(
        directory, log_names={PRIOR_BASELINE_STDOUT.name, PRIOR_BASELINE_STDERR.name},
        receipt_names={PRIOR_BASELINE_SERVICE_RECEIPT.name, PRIOR_BASELINE_RECOVERY_RESULT.name},
        label="generation-1 evidence",
    )
    expected = _baseline_sha256()
    started = read_json(PRIOR_BASELINE_SERVICE_RECEIPT)
    result = read_json(PRIOR_BASELINE_RECOVERY_RESULT)
    require(started.get("schema") == "round135-batch2-baseline-service-start/v1", "generation-1 start schema drift")
    require(started.get("mode") == "pre_attempt_002_baseline_recovery", "generation-1 mode drift")
    require(started.get("release_attempt") == 2, "generation-1 release attempt drift")
    require((started.get("pid"), started.get("create_time")) == GEN1_IDENTITY, "generation-1 identity drift")
    require(started.get("source_after_sha256") == expected["data"], "generation-1 data baseline drift")
    require(started.get("semantic_refinements_after_sha256") == expected["semantic_refinements"], "generation-1 semantic baseline drift")
    require(started.get("logs", {}).get("stdout_path") == str(paths["stdout"].resolve()), "generation-1 stdout path drift")
    require(started.get("logs", {}).get("stderr_path") == str(paths["stderr"].resolve()), "generation-1 stderr path drift")
    require(started.get("logs", {}).get("hash_status") == "process_running_hash_not_final", "generation-1 log status drift")
    require(started.get("logs", {}).get("final_sha256") is None, "generation-1 logs were sealed unexpectedly")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "generation-1 result schema drift")
    require(result.get("release_attempt") == 2, "generation-1 result attempt drift")
    require(result.get("passed") is True and result.get("service_restored") is True, "generation-1 recovery was not successful")
    require(result.get("production_files_mutated") is False, "generation-1 mutated production files")
    require(result.get("before_sha256") == result.get("after_sha256") == expected, "generation-1 before/after baseline drift")
    require(result.get("new_pid") == started["pid"], "generation-1 result PID drift")
    require(result.get("production_started_receipt") == str(PRIOR_BASELINE_SERVICE_RECEIPT.resolve()), "generation-1 result path drift")
    require(result.get("production_started_receipt_sha256") == sha256_path(PRIOR_BASELINE_SERVICE_RECEIPT), "generation-1 start hash chain drift")
    facts = {}
    for name, path in paths.items():
        facts[name] = {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256_path(path)}
    return facts


def verify_failed_gen2_evidence(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Verify the exact immutable failed generation-2 attempt and its gen-1 chain."""

    directory = FAILED_BASELINE_RECOVERY_DIR if directory is None else Path(directory)
    require(directory.resolve() == FAILED_BASELINE_RECOVERY_DIR.resolve(), "failed generation-2 directory path drift")
    paths = {
        "prior_recovery_observation": FAILED_BASELINE_PRIOR_OBSERVATION,
        "launch_intent": FAILED_BASELINE_LAUNCH_INTENT,
        "baseline_service_recovery": FAILED_BASELINE_RECOVERY_RESULT,
        "stdout": FAILED_BASELINE_STDOUT,
        "stderr": FAILED_BASELINE_STDERR,
    }
    _exact_receipt_tree(
        directory, log_names={FAILED_BASELINE_STDOUT.name, FAILED_BASELINE_STDERR.name},
        receipt_names={FAILED_BASELINE_PRIOR_OBSERVATION.name, FAILED_BASELINE_LAUNCH_INTENT.name, FAILED_BASELINE_RECOVERY_RESULT.name},
        label="failed generation-2 evidence",
    )
    expected = _baseline_sha256()
    gen1 = verify_gen1_evidence()
    observation = read_json(FAILED_BASELINE_PRIOR_OBSERVATION)
    intent = read_json(FAILED_BASELINE_LAUNCH_INTENT)
    result = read_json(FAILED_BASELINE_RECOVERY_RESULT)
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "failed generation-2 result schema drift")
    require(result.get("recovery_generation") == 2 and result.get("release_attempt") == 2, "failed generation-2 identity drift")
    require(result.get("passed") is False and result.get("service_restored") is False, "failed generation-2 must remain a failed recovery")
    require(result.get("production_files_mutated") is False, "failed generation-2 mutated production files")
    require(result.get("before_sha256") == result.get("after_sha256") == expected, "failed generation-2 baseline drift")
    require(result.get("active_recovery_dir") == str(directory.resolve()), "failed generation-2 active path drift")
    cleanup = result.get("child_cleanup")
    require(isinstance(cleanup, dict) and cleanup.get("exit_confirmed") is True, "failed generation-2 child cleanup is unconfirmed")
    identity = result.get("child_identity")
    require(isinstance(identity, dict), "failed generation-2 child identity missing")
    require((identity.get("pid"), identity.get("create_time")) == FAILED_GEN2_IDENTITY, "failed generation-2 child identity drift")
    require(result.get("prior_recovery_observation") == str(FAILED_BASELINE_PRIOR_OBSERVATION.resolve()), "failed generation-2 observation path drift")
    observation_sha = sha256_path(FAILED_BASELINE_PRIOR_OBSERVATION)
    require(result.get("prior_recovery_observation_sha256") == observation_sha, "failed generation-2 observation SHA chain drift")
    require(observation.get("schema") == "round135-batch2-prior-baseline-observation/v1", "failed generation-2 observation schema drift")
    require(observation.get("recovery_generation") == 2, "failed generation-2 observation generation drift")
    require(observation.get("prior_recovery_dir") == str(PRIOR_BASELINE_RECOVERY_DIR.resolve()), "failed generation-2 prior directory drift")
    require(observation.get("prior_identity") == {"pid": GEN1_IDENTITY[0], "create_time": GEN1_IDENTITY[1]}, "failed generation-2 prior identity drift")
    require(observation.get("prior_identity_absent") is True, "failed generation-2 did not attest generation-1 identity absence")
    require(observation.get("listener_8188_empty") is True and observation.get("comfyui_processes_empty") is True, "failed generation-2 inherited runtime residue")
    require(observation.get("baseline_sha256") == expected, "failed generation-2 observation baseline drift")
    prior_files = observation.get("prior_files")
    require(isinstance(prior_files, dict) and set(prior_files) == set(gen1), "failed generation-2 generation-1 allowlist drift")
    for name, facts in gen1.items():
        require(prior_files[name] == facts, f"failed generation-2 does not bind generation-1 {name}")
    gen1_sha_by_name = {name: facts["sha256"] for name, facts in gen1.items()}
    require(result.get("prior_evidence_sha256") == gen1_sha_by_name, "failed generation-2 prior evidence chain drift")
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1", "failed generation-2 intent schema drift")
    require(intent.get("recovery_generation") == 2, "failed generation-2 intent generation drift")
    require(intent.get("active_recovery_dir") == str(directory.resolve()), "failed generation-2 intent active path drift")
    require(intent.get("prior_recovery_observation") == str(FAILED_BASELINE_PRIOR_OBSERVATION.resolve()), "failed generation-2 intent observation path drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha, "failed generation-2 intent observation SHA drift")
    require(intent.get("prior_evidence_sha256") == gen1_sha_by_name, "failed generation-2 intent prior evidence drift")
    require(intent.get("baseline_sha256") == expected, "failed generation-2 intent baseline drift")
    require(intent.get("requested_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "failed generation-2 flags drift")
    empty_sha = hashlib.sha256(b"").hexdigest()
    facts = {}
    for name, path in paths.items():
        digest = sha256_path(path)
        size = path.stat().st_size
        if name in ("stdout", "stderr"):
            require(size == 0 and digest == empty_sha, f"failed generation-2 log is not empty: {path}")
        facts[name] = {"path": str(path.resolve()), "bytes": size, "sha256": digest}
    return facts


def verify_failed_gen3_evidence(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    """Verify the immutable failed generation-3 recovery and its gen-1/gen-2 chain."""

    directory = FAILED_GEN3_RECOVERY_DIR if directory is None else Path(directory)
    require(directory.resolve() == FAILED_GEN3_RECOVERY_DIR.resolve(), "failed generation-3 directory path drift")
    paths = {
        "prior_recovery_observation": FAILED_GEN3_PRIOR_OBSERVATION,
        "launch_intent": FAILED_GEN3_LAUNCH_INTENT,
        "baseline_service_recovery": FAILED_GEN3_RECOVERY_RESULT,
        "stdout": FAILED_GEN3_STDOUT,
        "stderr": FAILED_GEN3_STDERR,
    }
    _exact_receipt_tree(
        directory, log_names={FAILED_GEN3_STDOUT.name, FAILED_GEN3_STDERR.name},
        receipt_names={FAILED_GEN3_PRIOR_OBSERVATION.name, FAILED_GEN3_LAUNCH_INTENT.name, FAILED_GEN3_RECOVERY_RESULT.name},
        label="failed generation-3 evidence",
    )
    expected = _baseline_sha256()
    gen1 = verify_gen1_evidence()
    gen2 = verify_failed_gen2_evidence()
    prior_sha = {facts["path"]: facts["sha256"] for collection in (gen1, gen2) for facts in collection.values()}
    observation = read_json(FAILED_GEN3_PRIOR_OBSERVATION)
    intent = read_json(FAILED_GEN3_LAUNCH_INTENT)
    result = read_json(FAILED_GEN3_RECOVERY_RESULT)
    require(observation.get("schema") == "round135-batch2-baseline-generation3-observation/v1", "failed generation-3 observation schema drift")
    require(observation.get("recovery_generation") == 3, "failed generation-3 observation generation drift")
    require(observation.get("active_recovery_dir") == str(directory.resolve()), "failed generation-3 observation path drift")
    require(observation.get("prior_evidence_sha256") == prior_sha, "failed generation-3 observation evidence chain drift")
    require(observation.get("both_prior_identities_absent") is True, "failed generation-3 prior identity check missing")
    require(observation.get("listener_8188_empty") is True and observation.get("comfyui_processes_empty") is True, "failed generation-3 inherited runtime residue")
    require(observation.get("baseline_before_sha256") == observation.get("baseline_after_sha256") == expected, "failed generation-3 observation baseline drift")
    observation_sha = sha256_path(FAILED_GEN3_PRIOR_OBSERVATION)
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1", "failed generation-3 intent schema drift")
    require(intent.get("recovery_generation") == 3, "failed generation-3 intent generation drift")
    require(intent.get("active_recovery_dir") == str(directory.resolve()), "failed generation-3 intent path drift")
    require(intent.get("prior_recovery_observation") == str(FAILED_GEN3_PRIOR_OBSERVATION.resolve()), "failed generation-3 intent observation path drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha, "failed generation-3 intent observation SHA drift")
    require(intent.get("prior_evidence_sha256") == prior_sha, "failed generation-3 intent evidence chain drift")
    require(intent.get("baseline_sha256") == expected, "failed generation-3 intent baseline drift")
    require(intent.get("requested_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "failed generation-3 intent flags drift")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "failed generation-3 result schema drift")
    require(result.get("recovery_generation") == 3 and result.get("release_attempt") == 2, "failed generation-3 result identity drift")
    require(result.get("passed") is False and result.get("service_restored") is False, "failed generation-3 must remain failed")
    require(result.get("production_files_mutated") is False, "failed generation-3 mutated production files")
    require(result.get("before_sha256") == result.get("after_sha256") == expected, "failed generation-3 baseline drift")
    require(result.get("active_recovery_dir") == str(directory.resolve()), "failed generation-3 result path drift")
    require(result.get("prior_recovery_observation") == str(FAILED_GEN3_PRIOR_OBSERVATION.resolve()), "failed generation-3 result observation path drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha, "failed generation-3 result observation SHA drift")
    require(result.get("prior_evidence_sha256") == prior_sha, "failed generation-3 result evidence chain drift")
    cleanup = result.get("child_cleanup")
    identity = result.get("child_identity")
    require(isinstance(cleanup, dict) and cleanup.get("exit_confirmed") is True, "failed generation-3 child cleanup unconfirmed")
    require(isinstance(identity, dict) and (identity.get("pid"), identity.get("create_time")) == FAILED_GEN3_IDENTITY, "failed generation-3 child identity drift")
    empty_sha = hashlib.sha256(b"").hexdigest()
    facts = {}
    for name, path in paths.items():
        digest = sha256_path(path)
        size = path.stat().st_size
        if name in ("stdout", "stderr"):
            require(size > 0, f"failed generation-3 log unexpectedly empty: {path}")
        facts[name] = {"path": str(path.resolve()), "bytes": size, "sha256": digest}
    return facts


def verify_failed_gen4_evidence() -> dict[str, dict[str, Any]]:
    """Seal the failed sandboxed generation-4 attempt without rewriting it."""

    paths = {
        "prior_recovery_observation": FAILED_GEN4_PRIOR_OBSERVATION,
        "launch_intent": FAILED_GEN4_LAUNCH_INTENT,
        "baseline_service_recovery": FAILED_GEN4_RECOVERY_RESULT,
        "stdout": FAILED_GEN4_STDOUT,
        "stderr": FAILED_GEN4_STDERR,
    }
    _exact_receipt_tree(
        FAILED_GEN4_RECOVERY_DIR,
        log_names={FAILED_GEN4_STDOUT.name, FAILED_GEN4_STDERR.name},
        receipt_names={FAILED_GEN4_PRIOR_OBSERVATION.name, FAILED_GEN4_LAUNCH_INTENT.name,
                       FAILED_GEN4_RECOVERY_RESULT.name},
        label="failed generation-4 evidence",
    )
    gen1 = verify_gen1_evidence()
    gen2 = verify_failed_gen2_evidence()
    gen3 = verify_failed_gen3_evidence()
    prior_sha = {facts["path"]: facts["sha256"] for group in (gen1, gen2, gen3) for facts in group.values()}
    expected = _baseline_sha256()
    observation = read_json(FAILED_GEN4_PRIOR_OBSERVATION)
    intent = read_json(FAILED_GEN4_LAUNCH_INTENT)
    result = read_json(FAILED_GEN4_RECOVERY_RESULT)
    require(observation.get("schema") == "round135-batch2-baseline-generation4-observation/v1", "failed generation-4 observation schema drift")
    require(observation.get("recovery_generation") == 4 and observation.get("active_recovery_dir") == str(FAILED_GEN4_RECOVERY_DIR.resolve()), "failed generation-4 observation identity drift")
    require(observation.get("prior_evidence_sha256") == prior_sha and observation.get("failed_generation3_files") == gen3, "failed generation-4 prior evidence drift")
    require(observation.get("baseline_before_sha256") == observation.get("baseline_after_sha256") == expected, "failed generation-4 observation baseline drift")
    require(observation.get("listener_8188_empty") is True and observation.get("comfyui_processes_empty") is True, "failed generation-4 prelaunch residue")
    observation_sha = sha256_path(FAILED_GEN4_PRIOR_OBSERVATION)
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1" and intent.get("recovery_generation") == 4, "failed generation-4 launch intent identity drift")
    require(intent.get("active_recovery_dir") == str(FAILED_GEN4_RECOVERY_DIR.resolve()), "failed generation-4 launch intent path drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha and intent.get("prior_evidence_sha256") == prior_sha, "failed generation-4 launch intent evidence drift")
    require(intent.get("baseline_sha256") == expected, "failed generation-4 launch intent baseline drift")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "failed generation-4 result schema drift")
    require(result.get("recovery_generation") == 4 and result.get("release_attempt") == 2, "failed generation-4 result identity drift")
    require(result.get("passed") is False and result.get("service_restored") is False, "failed generation-4 must stay failed")
    require(result.get("production_files_mutated") is False and result.get("before_sha256") == result.get("after_sha256") == expected, "failed generation-4 production drift")
    require(result.get("active_recovery_dir") == str(FAILED_GEN4_RECOVERY_DIR.resolve()), "failed generation-4 result path drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha and result.get("prior_evidence_sha256") == prior_sha, "failed generation-4 result evidence drift")
    cleanup = result.get("child_cleanup")
    identity = result.get("child_identity")
    require(isinstance(cleanup, dict) and cleanup.get("exit_confirmed") is True, "failed generation-4 child cleanup unconfirmed")
    require(isinstance(identity, dict) and (identity.get("pid"), identity.get("create_time")) == FAILED_GEN4_IDENTITY, "failed generation-4 child identity drift")
    require(not (FAILED_GEN4_RECOVERY_RECEIPT_DIR / "production_started.json").exists(), "failed generation-4 has a production start receipt")
    facts = {}
    for name, path in paths.items():
        digest = sha256_path(path)
        size = path.stat().st_size
        require(name not in ("stdout", "stderr") or size > 0, f"failed generation-4 log unexpectedly empty: {path}")
        facts[name] = {"path": str(path.resolve()), "bytes": size, "sha256": digest}
    return facts


def verify_failed_gen5_evidence() -> dict[str, dict[str, Any]]:
    """Seal the failed Job-isolated generation-5 launch."""

    paths = {
        "prior_recovery_observation": FAILED_GEN5_PRIOR_OBSERVATION,
        "launch_intent": FAILED_GEN5_LAUNCH_INTENT,
        "baseline_service_recovery": FAILED_GEN5_RECOVERY_RESULT,
        "stdout": FAILED_GEN5_STDOUT,
        "stderr": FAILED_GEN5_STDERR,
    }
    _exact_receipt_tree(
        FAILED_GEN5_RECOVERY_DIR,
        log_names={FAILED_GEN5_STDOUT.name, FAILED_GEN5_STDERR.name},
        receipt_names={FAILED_GEN5_PRIOR_OBSERVATION.name, FAILED_GEN5_LAUNCH_INTENT.name,
                       FAILED_GEN5_RECOVERY_RESULT.name},
        label="failed generation-5 evidence",
    )
    gen1 = verify_gen1_evidence()
    gen2 = verify_failed_gen2_evidence()
    gen3 = verify_failed_gen3_evidence()
    gen4 = verify_failed_gen4_evidence()
    prior_sha = {facts["path"]: facts["sha256"] for group in (gen1, gen2, gen3, gen4) for facts in group.values()}
    expected = _baseline_sha256()
    observation = read_json(FAILED_GEN5_PRIOR_OBSERVATION)
    intent = read_json(FAILED_GEN5_LAUNCH_INTENT)
    result = read_json(FAILED_GEN5_RECOVERY_RESULT)
    require(observation.get("schema") == "round135-batch2-baseline-generation5-observation/v1", "failed generation-5 observation schema drift")
    require(observation.get("recovery_generation") == 5 and observation.get("active_recovery_dir") == str(FAILED_GEN5_RECOVERY_DIR.resolve()), "failed generation-5 observation identity drift")
    require(observation.get("prior_evidence_sha256") == prior_sha and observation.get("failed_generation4_files") == gen4, "failed generation-5 prior evidence drift")
    require(observation.get("baseline_before_sha256") == observation.get("baseline_after_sha256") == expected, "failed generation-5 observation baseline drift")
    require(observation.get("listener_8188_empty") is True and observation.get("comfyui_processes_empty") is True, "failed generation-5 prelaunch residue")
    observation_sha = sha256_path(FAILED_GEN5_PRIOR_OBSERVATION)
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1" and intent.get("recovery_generation") == 5, "failed generation-5 launch intent identity drift")
    require(intent.get("active_recovery_dir") == str(FAILED_GEN5_RECOVERY_DIR.resolve()), "failed generation-5 launch intent path drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha and intent.get("prior_evidence_sha256") == prior_sha, "failed generation-5 launch intent evidence drift")
    require(intent.get("baseline_sha256") == expected, "failed generation-5 launch intent baseline drift")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "failed generation-5 result schema drift")
    require(result.get("recovery_generation") == 5 and result.get("release_attempt") == 2, "failed generation-5 result identity drift")
    require(result.get("passed") is False and result.get("service_restored") is False, "failed generation-5 must stay failed")
    require(result.get("production_files_mutated") is False and result.get("before_sha256") == result.get("after_sha256") == expected, "failed generation-5 production drift")
    require(result.get("active_recovery_dir") == str(FAILED_GEN5_RECOVERY_DIR.resolve()), "failed generation-5 result path drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha and result.get("prior_evidence_sha256") == prior_sha, "failed generation-5 result evidence drift")
    cleanup = result.get("child_cleanup")
    identity = result.get("child_identity")
    require(isinstance(cleanup, dict) and cleanup.get("exit_confirmed") is True, "failed generation-5 child cleanup unconfirmed")
    require(isinstance(identity, dict) and (identity.get("pid"), identity.get("create_time")) == FAILED_GEN5_IDENTITY, "failed generation-5 child identity drift")
    require("child Job has KILL_ON_JOB_CLOSE" in result.get("error", ""), "failed generation-5 cause drift")
    require(not (FAILED_GEN5_RECOVERY_RECEIPT_DIR / "production_started.json").exists(), "failed generation-5 has a production start receipt")
    empty_sha = hashlib.sha256(b"").hexdigest()
    facts = {}
    for name, path in paths.items():
        digest = sha256_path(path)
        size = path.stat().st_size
        if name in ("stdout", "stderr"):
            require(size == 0 and digest == empty_sha, f"failed generation-5 log is not empty: {path}")
        facts[name] = {"path": str(path.resolve()), "bytes": size, "sha256": digest}
    return facts


def verify_baseline_generation2_chain(
    started_path: Path | None = None,
    result_path: Path | None = None,
    observation_path: Path | None = None,
    intent_path: Path | None = None,
) -> dict[str, str]:
    """Verify active recovery generation 2 and return its immutable evidence map."""

    # Bind defaults at call time so controlled tests and recovery tooling can
    # safely redirect the module's active evidence paths.
    started_path = BASELINE_SERVICE_RECEIPT if started_path is None else Path(started_path)
    result_path = BASELINE_RECOVERY_RESULT if result_path is None else Path(result_path)
    observation_path = BASELINE_PRIOR_OBSERVATION if observation_path is None else Path(observation_path)
    intent_path = BASELINE_LAUNCH_INTENT if intent_path is None else Path(intent_path)

    expected_paths = {
        "started": BASELINE_SERVICE_RECEIPT,
        "result": BASELINE_RECOVERY_RESULT,
        "observation": BASELINE_PRIOR_OBSERVATION,
        "intent": BASELINE_LAUNCH_INTENT,
    }
    actual_paths = {
        "started": Path(started_path), "result": Path(result_path),
        "observation": Path(observation_path), "intent": Path(intent_path),
    }
    for name, path in actual_paths.items():
        require(path.resolve() == expected_paths[name].resolve(), f"baseline generation-2 path drift: {name}")
        require(path.is_file() and not path.is_symlink(), f"baseline generation-2 receipt missing or linked: {path}")
    active_directories = (
        BASELINE_RECOVERY_DIR,
        BASELINE_RECOVERY_DIR / "logs",
        BASELINE_RECOVERY_RECEIPT_DIR,
        PRIOR_BASELINE_RECOVERY_DIR,
        PRIOR_BASELINE_RECOVERY_DIR / "logs",
        PRIOR_BASELINE_RECOVERY_RECEIPT_DIR,
    )
    require(all(not path.is_symlink() for path in active_directories), "baseline recovery directory contains a link")
    started = read_json(actual_paths["started"])
    result = read_json(actual_paths["result"])
    observation = read_json(actual_paths["observation"])
    intent = read_json(actual_paths["intent"])
    require(started.get("schema") == "round135-batch2-baseline-service-start/v1", "baseline start schema drift")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "baseline result schema drift")
    require(started.get("recovery_generation") == result.get("recovery_generation") == 2, "baseline recovery generation drift")
    baseline = read_json(BASELINE_PATH)["rebased_baseline"]
    expected_baseline = {
        "data": baseline["data_sha256"],
        "semantic_refinements": baseline["semantic_refinements_sha256"],
    }
    require(started.get("mode") == "pre_attempt_002_baseline_recovery_002", "baseline start mode drift")
    require(result.get("passed") is True and result.get("service_restored") is True, "baseline generation-2 recovery failed")
    require(result.get("production_files_mutated") is False, "baseline recovery mutated production files")
    require(result.get("before_sha256") == result.get("after_sha256") == expected_baseline, "baseline recovery SHA drift")
    require(started.get("source_after_sha256") == expected_baseline["data"], "baseline data SHA drift")
    require(started.get("semantic_refinements_after_sha256") == expected_baseline["semantic_refinements"], "baseline semantic SHA drift")
    require(result.get("new_pid") == started.get("pid"), "baseline PID receipt chain drift")
    require(result.get("production_started_receipt") == str(actual_paths["started"].resolve()), "baseline result path drift")
    require(result.get("production_started_receipt_sha256") == sha256_path(actual_paths["started"]), "baseline start receipt hash drift")
    require(started.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "baseline active directory drift")
    require(result.get("active_recovery_dir") == started.get("active_recovery_dir"), "baseline recovery directory chain drift")
    require(started.get("prior_recovery_observation") == str(actual_paths["observation"].resolve()), "prior observation path drift")
    require(result.get("prior_recovery_observation") == started.get("prior_recovery_observation"), "prior observation chain drift")
    observation_sha = sha256_path(actual_paths["observation"])
    require(started.get("prior_recovery_observation_sha256") == observation_sha, "prior observation SHA drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha, "result observation SHA drift")
    require(observation.get("schema") == "round135-batch2-prior-baseline-observation/v1", "prior observation schema drift")
    require(observation.get("recovery_generation") == 2, "prior observation generation drift")
    require(observation.get("prior_recovery_dir") == str(PRIOR_BASELINE_RECOVERY_DIR.resolve()), "prior recovery path drift")
    require(observation.get("prior_identity_absent") is True, "prior process identity absence not attested")
    require(observation.get("exit_reason") == "unknown", "prior process exit reason was inferred")
    require(observation.get("shutdown_or_crash_conclusion") is None, "prior observation makes an unsupported exit conclusion")
    prior_paths = {
        "production_started": PRIOR_BASELINE_SERVICE_RECEIPT,
        "baseline_service_recovery": PRIOR_BASELINE_RECOVERY_RESULT,
        "stdout": PRIOR_BASELINE_STDOUT,
        "stderr": PRIOR_BASELINE_STDERR,
    }
    prior_evidence = observation.get("prior_files")
    require(isinstance(prior_evidence, dict) and set(prior_evidence) == set(prior_paths), "prior evidence allowlist drift")
    evidence_map: dict[str, str] = {}
    for name, path in prior_paths.items():
        facts = prior_evidence[name]
        require(path.is_file() and not path.is_symlink(), f"prior evidence missing or linked: {path}")
        require(facts.get("path") == str(path.resolve()), f"prior evidence path drift: {name}")
        require(facts.get("bytes") == path.stat().st_size, f"prior evidence byte count drift: {name}")
        digest = sha256_path(path)
        require(facts.get("sha256") == digest, f"prior evidence SHA drift: {name}")
        evidence_map[str(path.resolve())] = digest
    prior_started = read_json(PRIOR_BASELINE_SERVICE_RECEIPT)
    require(observation.get("prior_identity") == {
        "pid": prior_started.get("pid"), "create_time": prior_started.get("create_time"),
    }, "prior identity tuple drift")
    prior_result = read_json(PRIOR_BASELINE_RECOVERY_RESULT)
    require(prior_result.get("production_started_receipt_sha256") == evidence_map[str(PRIOR_BASELINE_SERVICE_RECEIPT.resolve())], "prior receipt chain drift")
    require(started.get("prior_evidence_sha256") == {
        name: facts["sha256"] for name, facts in prior_evidence.items()
    }, "start prior evidence map drift")
    require(result.get("prior_evidence_sha256") == started.get("prior_evidence_sha256"), "result prior evidence map drift")
    require(started.get("launch_intent") == str(actual_paths["intent"].resolve()), "launch intent path drift")
    intent_sha = sha256_path(actual_paths["intent"])
    require(started.get("launch_intent_sha256") == intent_sha, "launch intent SHA drift")
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1", "launch intent schema drift")
    require(intent.get("recovery_generation") == 2, "launch intent generation drift")
    require(intent.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "launch intent active directory drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha, "launch intent observation chain drift")
    require(intent.get("prior_evidence_sha256") == started.get("prior_evidence_sha256"), "launch intent prior evidence drift")
    require(intent.get("requested_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "launch intent flags drift")
    require(started.get("launch_isolation") == result.get("launch_isolation"), "launch isolation receipt chain drift")
    require(started["launch_isolation"].get("requested_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "baseline launch requested flags drift")
    require(started["launch_isolation"].get("applied_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "baseline launch applied flags drift")
    require(started["launch_isolation"].get("child_is_process_in_job") is False, "baseline child Job status drift")
    require(started["launch_isolation"].get("child_detached_verified") is True, "baseline detachment was not attested")
    parent_in_job = started["launch_isolation"].get("parent_job_in_job")
    parent_flags = started["launch_isolation"].get("parent_job_limit_flags")
    require(isinstance(parent_in_job, bool), "parent Job membership fact missing")
    if parent_in_job:
        require(isinstance(parent_flags, int), "parent Job flags missing")
        require(parent_flags & (JOB_OBJECT_LIMIT_BREAKAWAY_OK | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK), "parent Job disallowed breakaway")
    evidence_map.update({
        str(actual_paths["observation"].resolve()): observation_sha,
        str(actual_paths["started"].resolve()): sha256_path(actual_paths["started"]),
        str(actual_paths["result"].resolve()): sha256_path(actual_paths["result"]),
        str(actual_paths["intent"].resolve()): intent_sha,
    })
    return evidence_map


def verify_baseline_generation3_chain(
    *,
    process_factory=psutil.Process,
    listener_func=tcp_listener_bindings,
    comfyui_process_func=comfyui_main_pids,
    child_job_query=process_is_in_job,
    verify_live: bool = True,
) -> dict[str, str]:
    """Verify successful generation 3 plus its immutable generation-1/2 chain.

    The active service logs are required to exist in the exact layout, but are
    intentionally excluded from the returned seal because the service is live.
    """

    gen1 = verify_gen1_evidence()
    failed_gen2 = verify_failed_gen2_evidence()
    _exact_receipt_tree(
        BASELINE_RECOVERY_DIR,
        log_names={BASELINE_STDOUT.name, BASELINE_STDERR.name},
        receipt_names={
            BASELINE_PRIOR_OBSERVATION.name, BASELINE_LAUNCH_INTENT.name,
            BASELINE_SERVICE_RECEIPT.name, BASELINE_RECOVERY_RESULT.name,
        },
        label="active generation-3 evidence",
    )
    expected = _baseline_sha256()
    observation = read_json(BASELINE_PRIOR_OBSERVATION)
    intent = read_json(BASELINE_LAUNCH_INTENT)
    started = read_json(BASELINE_SERVICE_RECEIPT)
    result = read_json(BASELINE_RECOVERY_RESULT)
    require(observation.get("schema") == "round135-batch2-baseline-generation3-observation/v1", "generation-3 observation schema drift")
    require(observation.get("recovery_generation") == 3, "generation-3 observation generation drift")
    require(observation.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-3 observation path drift")
    require(observation.get("generation1_files") == gen1, "generation-3 observation does not bind exact generation-1 evidence")
    require(observation.get("failed_generation2_files") == failed_gen2, "generation-3 observation does not bind exact failed generation-2 evidence")
    require(observation.get("generation1_identity") == {"pid": GEN1_IDENTITY[0], "create_time": GEN1_IDENTITY[1]}, "generation-3 old identity drift")
    require(observation.get("failed_generation2_identity") == {"pid": FAILED_GEN2_IDENTITY[0], "create_time": FAILED_GEN2_IDENTITY[1]}, "generation-3 failed child identity drift")
    require(observation.get("both_prior_identities_absent") is True, "generation-3 did not verify both prior identities absent")
    identity_facts = observation.get("prior_identity_observations")
    require(isinstance(identity_facts, dict) and set(identity_facts) == {"generation1", "failed_generation2"}, "generation-3 identity observation map drift")
    for name, expected_identity in (
        ("generation1", GEN1_IDENTITY), ("failed_generation2", FAILED_GEN2_IDENTITY),
    ):
        facts = identity_facts[name]
        require(facts.get("pid") == expected_identity[0] and facts.get("create_time") == expected_identity[1], f"generation-3 {name} identity fact drift")
        require(facts.get("identity_absent") is True, f"generation-3 {name} identity is not absent")
        require(isinstance(facts.get("pid_exists"), bool), f"generation-3 {name} PID observation missing")
        require(isinstance(facts.get("pid_reused_with_different_create_time"), bool), f"generation-3 {name} PID reuse observation missing")
        require(facts["pid_reused_with_different_create_time"] is facts["pid_exists"], f"generation-3 {name} PID reuse conclusion drift")
    require(observation.get("listener_8188_empty") is True and observation.get("comfyui_processes_empty") is True, "generation-3 prelaunch residue was present")
    require(observation.get("baseline_before_sha256") == observation.get("baseline_after_sha256") == expected, "generation-3 observation baseline drift")
    prior_evidence_sha = {
        facts["path"]: facts["sha256"]
        for collection in (gen1, failed_gen2)
        for facts in collection.values()
    }
    require(observation.get("prior_evidence_sha256") == prior_evidence_sha, "generation-3 observation SHA map drift")
    observation_sha = sha256_path(BASELINE_PRIOR_OBSERVATION)

    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1", "generation-3 intent schema drift")
    require(intent.get("recovery_generation") == 3, "generation-3 intent generation drift")
    require(intent.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-3 intent path drift")
    require(intent.get("prior_recovery_observation") == str(BASELINE_PRIOR_OBSERVATION.resolve()), "generation-3 intent observation path drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha, "generation-3 intent observation SHA drift")
    require(intent.get("prior_evidence_sha256") == prior_evidence_sha, "generation-3 intent evidence map drift")
    require(intent.get("baseline_sha256") == expected, "generation-3 intent baseline drift")
    require(intent.get("requested_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "generation-3 intent flags drift")

    require(started.get("schema") == "round135-batch2-baseline-service-start/v1", "generation-3 start schema drift")
    require(started.get("recovery_generation") == 3 and started.get("release_attempt") == 2, "generation-3 start generation/attempt drift")
    require(started.get("mode") == "pre_attempt_002_baseline_recovery_003", "generation-3 start mode drift")
    require(started.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-3 start path drift")
    require(started.get("prior_recovery_observation") == str(BASELINE_PRIOR_OBSERVATION.resolve()), "generation-3 start observation path drift")
    require(started.get("prior_recovery_observation_sha256") == observation_sha, "generation-3 start observation SHA drift")
    require(started.get("prior_evidence_sha256") == prior_evidence_sha, "generation-3 start evidence map drift")
    require(started.get("launch_intent") == str(BASELINE_LAUNCH_INTENT.resolve()), "generation-3 start intent path drift")
    require(started.get("launch_intent_sha256") == sha256_path(BASELINE_LAUNCH_INTENT), "generation-3 start intent SHA drift")
    require(started.get("source_after_sha256") == expected["data"], "generation-3 data baseline drift")
    require(started.get("semantic_refinements_after_sha256") == expected["semantic_refinements"], "generation-3 semantic baseline drift")
    require((started.get("pid"), started.get("create_time")) != GEN1_IDENTITY, "generation-1 process identity was reused")
    require((started.get("pid"), started.get("create_time")) != FAILED_GEN2_IDENTITY, "failed generation-2 child identity was reused")
    require(started.get("launch_isolation") == result.get("launch_isolation"), "generation-3 launch isolation chain drift")
    logs = started.get("logs", {})
    require(logs.get("stdout_path") == str(BASELINE_STDOUT.resolve()), "generation-3 stdout path drift")
    require(logs.get("stderr_path") == str(BASELINE_STDERR.resolve()), "generation-3 stderr path drift")
    require(logs.get("hash_status") == "process_running_hash_not_final" and logs.get("final_sha256") is None, "generation-3 live logs must remain unsealed")

    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "generation-3 result schema drift")
    require(result.get("recovery_generation") == 3 and result.get("release_attempt") == 2, "generation-3 result generation/attempt drift")
    require(result.get("passed") is True and result.get("service_restored") is True, "generation-3 recovery did not pass")
    require(result.get("production_files_mutated") is False, "generation-3 mutated production files")
    require(result.get("before_sha256") == result.get("after_sha256") == expected, "generation-3 before/after baseline drift")
    require(result.get("new_pid") == started.get("pid"), "generation-3 PID chain drift")
    require(result.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-3 result path drift")
    require(result.get("prior_recovery_observation") == str(BASELINE_PRIOR_OBSERVATION.resolve()), "generation-3 result observation path drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha, "generation-3 result observation SHA drift")
    require(result.get("prior_evidence_sha256") == prior_evidence_sha, "generation-3 result evidence map drift")
    require(result.get("production_started_receipt") == str(BASELINE_SERVICE_RECEIPT.resolve()), "generation-3 started path drift")
    require(result.get("production_started_receipt_sha256") == sha256_path(BASELINE_SERVICE_RECEIPT), "generation-3 started SHA drift")
    require(started.get("launch_isolation", {}).get("requested_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "generation-3 requested flags drift")
    require(started.get("launch_isolation", {}).get("applied_creationflags") == WINDOWS_BREAKAWAY_FLAGS, "generation-3 applied flags drift")
    require(started.get("launch_isolation", {}).get("child_job_contract_verified") is True, "generation-3 child Job contract drift")

    require(verify_gen1_evidence() == gen1, "generation-1 evidence changed during generation-3 verification")
    require(verify_failed_gen2_evidence() == failed_gen2, "failed generation-2 evidence changed during generation-3 verification")
    evidence_map = {
        facts["path"]: facts["sha256"]
        for collection in (gen1, failed_gen2)
        for facts in collection.values()
    }
    evidence_map[str(BASELINE_PRIOR_OBSERVATION.resolve())] = observation_sha
    evidence_map[str(BASELINE_LAUNCH_INTENT.resolve())] = sha256_path(BASELINE_LAUNCH_INTENT)
    evidence_map[str(BASELINE_SERVICE_RECEIPT.resolve())] = sha256_path(BASELINE_SERVICE_RECEIPT)
    evidence_map[str(BASELINE_RECOVERY_RESULT.resolve())] = sha256_path(BASELINE_RECOVERY_RESULT)
    if verify_live:
        verify_live_service_identity(
            started, process_factory=process_factory, listener_func=listener_func,
            comfyui_process_func=comfyui_process_func, child_job_query=child_job_query,
        )
    else:
        verify_launch_isolation(
            started,
            child_job_query=lambda pid: started["launch_isolation"]["child_is_process_in_job"],
        )
    return evidence_map


def verify_failed_gen6_evidence() -> dict[str, dict[str, Any]]:
    """Seal the failed generation-6 child without reusing its directory."""
    paths = {
        "prior_recovery_observation": FAILED_GEN6_OBSERVATION,
        "launch_intent": FAILED_GEN6_INTENT,
        "baseline_service_recovery": FAILED_GEN6_RESULT,
        "stdout": FAILED_GEN6_STDOUT,
        "stderr": FAILED_GEN6_STDERR,
    }
    _exact_receipt_tree(
        FAILED_GEN6_RECOVERY_DIR,
        log_names={FAILED_GEN6_STDOUT.name, FAILED_GEN6_STDERR.name},
        receipt_names={FAILED_GEN6_OBSERVATION.name, FAILED_GEN6_INTENT.name,
                       FAILED_GEN6_RESULT.name},
        label="failed generation-6 evidence",
    )
    groups = (verify_gen1_evidence(), verify_failed_gen2_evidence(),
              verify_failed_gen3_evidence(), verify_failed_gen4_evidence(),
              verify_failed_gen5_evidence())
    prior_sha = {facts["path"]: facts["sha256"] for group in groups for facts in group.values()}
    expected = _baseline_sha256()
    observation = read_json(FAILED_GEN6_OBSERVATION)
    intent = read_json(FAILED_GEN6_INTENT)
    result = read_json(FAILED_GEN6_RESULT)
    require(observation.get("schema") == "round135-batch2-baseline-generation6-observation/v1",
            "failed generation-6 observation schema drift")
    require(observation.get("recovery_generation") == 6 and
            observation.get("active_recovery_dir") == str(FAILED_GEN6_RECOVERY_DIR.resolve()),
            "failed generation-6 observation identity drift")
    require(observation.get("prior_evidence_sha256") == prior_sha,
            "failed generation-6 prior evidence drift")
    require(observation.get("baseline_before_sha256") == observation.get("baseline_after_sha256") == expected,
            "failed generation-6 baseline drift")
    observation_sha = sha256_path(FAILED_GEN6_OBSERVATION)
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1" and
            intent.get("recovery_generation") == 6 and
            intent.get("prior_recovery_observation_sha256") == observation_sha and
            intent.get("prior_evidence_sha256") == prior_sha and
            intent.get("baseline_sha256") == expected, "failed generation-6 intent drift")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1" and
            result.get("recovery_generation") == 6 and result.get("release_attempt") == 2,
            "failed generation-6 result identity drift")
    require(result.get("passed") is False and result.get("service_restored") is False and
            result.get("production_files_mutated") is False and
            result.get("before_sha256") == result.get("after_sha256") == expected,
            "failed generation-6 result drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha and
            result.get("prior_evidence_sha256") == prior_sha and
            result.get("child_cleanup", {}).get("exit_confirmed") is True and
            "child Job has KILL_ON_JOB_CLOSE" in result.get("error", ""),
            "failed generation-6 cause or cleanup drift")
    require(not (FAILED_GEN6_RECEIPT_DIR / "production_started.json").exists(),
            "failed generation-6 has a production start receipt")
    facts = {}
    for name, path in paths.items():
        size = path.stat().st_size
        require(name not in ("stdout", "stderr") or size == 0,
                "failed generation-6 log unexpectedly changed")
        facts[name] = {"path": str(path.resolve()), "bytes": size, "sha256": sha256_path(path)}
    return facts


def verify_baseline_generation7_chain(
    *, process_factory=psutil.Process, listener_func=tcp_listener_bindings,
    comfyui_process_func=comfyui_main_pids, child_job_query=process_is_in_job,
    verify_live: bool = True,
) -> dict[str, str]:
    """Verify active generation 7 and bind every immutable failed recovery."""

    gen1 = verify_gen1_evidence()
    gen2 = verify_failed_gen2_evidence()
    failed_gen3 = verify_failed_gen3_evidence()
    failed_gen4 = verify_failed_gen4_evidence()
    failed_gen5 = verify_failed_gen5_evidence()
    failed_gen6 = verify_failed_gen6_evidence()
    _exact_receipt_tree(
        BASELINE_RECOVERY_DIR, log_names={BASELINE_STDOUT.name, BASELINE_STDERR.name},
        receipt_names={BASELINE_PRIOR_OBSERVATION.name, BASELINE_LAUNCH_INTENT.name,
                       BASELINE_SERVICE_RECEIPT.name, BASELINE_RECOVERY_RESULT.name},
        label="active generation-7 evidence",
    )
    observation = read_json(BASELINE_PRIOR_OBSERVATION)
    intent = read_json(BASELINE_LAUNCH_INTENT)
    started = read_json(BASELINE_SERVICE_RECEIPT)
    result = read_json(BASELINE_RECOVERY_RESULT)
    expected = _baseline_sha256()
    prior_sha = {facts["path"]: facts["sha256"] for group in (gen1, gen2, failed_gen3, failed_gen4, failed_gen5, failed_gen6) for facts in group.values()}
    require(observation.get("schema") == "round135-batch2-baseline-generation7-observation/v1", "generation-7 observation schema drift")
    require(observation.get("recovery_generation") == 7, "generation-7 observation generation drift")
    require(observation.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-7 observation path drift")
    require(observation.get("failed_generation3_files") == failed_gen3 and observation.get("failed_generation4_files") == failed_gen4 and observation.get("failed_generation5_files") == failed_gen5, "generation-6 failed evidence drift")
    require(observation.get("failed_generation6_files") == failed_gen6, "generation-7 failed generation-6 evidence drift")
    require(observation.get("prior_evidence_sha256") == prior_sha, "generation-7 observation prior SHA chain drift")
    require(observation.get("both_prior_identities_absent") is True, "generation-5 did not attest prior identities absent")
    require(observation.get("listener_8188_empty") is True and observation.get("comfyui_processes_empty") is True, "generation-5 prelaunch residue")
    require(observation.get("baseline_before_sha256") == observation.get("baseline_after_sha256") == expected, "generation-5 observation baseline drift")
    observation_sha = sha256_path(BASELINE_PRIOR_OBSERVATION)
    require(intent.get("schema") == "round135-batch2-baseline-launch-intent/v1" and intent.get("recovery_generation") == 7, "generation-7 intent identity drift")
    require(intent.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-4 intent path drift")
    require(intent.get("prior_recovery_observation") == str(BASELINE_PRIOR_OBSERVATION.resolve()), "generation-4 intent observation path drift")
    require(intent.get("prior_recovery_observation_sha256") == observation_sha, "generation-4 intent observation SHA drift")
    require(intent.get("prior_evidence_sha256") == prior_sha and intent.get("baseline_sha256") == expected, "generation-4 intent evidence/baseline drift")
    require(started.get("schema") == "round135-batch2-baseline-service-start/v1", "generation-4 start schema drift")
    require(started.get("recovery_generation") == 7 and started.get("release_attempt") == 2, "generation-7 start identity drift")
    require(started.get("mode") == "pre_attempt_002_baseline_recovery_007", "generation-7 mode drift")
    require(started.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-4 start path drift")
    require(started.get("prior_recovery_observation_sha256") == observation_sha, "generation-4 start observation SHA drift")
    require(started.get("prior_evidence_sha256") == prior_sha, "generation-4 start evidence chain drift")
    require(started.get("launch_intent_sha256") == sha256_path(BASELINE_LAUNCH_INTENT), "generation-4 intent SHA drift")
    require(started.get("source_after_sha256") == expected["data"] and started.get("semantic_refinements_after_sha256") == expected["semantic_refinements"], "generation-4 production baseline drift")
    require(started.get("launch_isolation") == result.get("launch_isolation"), "generation-4 isolation receipt drift")
    require(result.get("schema") == "round135-batch2-baseline-service-recovery/v1", "generation-4 result schema drift")
    require(result.get("recovery_generation") == 7 and result.get("release_attempt") == 2, "generation-7 result identity drift")
    require(result.get("passed") is True and result.get("service_restored") is True, "generation-7 recovery did not pass")
    require(result.get("production_files_mutated") is False and result.get("before_sha256") == result.get("after_sha256") == expected, "generation-4 production mutation/baseline drift")
    require(result.get("new_pid") == started.get("pid") and result.get("active_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "generation-4 PID/path chain drift")
    require(result.get("prior_recovery_observation_sha256") == observation_sha and result.get("prior_evidence_sha256") == prior_sha, "generation-4 result evidence chain drift")
    require(result.get("production_started_receipt_sha256") == sha256_path(BASELINE_SERVICE_RECEIPT), "generation-4 start receipt SHA drift")
    launch = started.get("launch_isolation", {})
    require(launch.get("launch_strategy") == "inherit_safe_job" and
            launch.get("requested_creationflags") == 0x208 and
            launch.get("child_job_limit_flags") == 0,
            "generation-7 launch did not inherit a safe Job")
    logs = started.get("logs", {})
    require(logs.get("stdout_path") == str(BASELINE_STDOUT.resolve()) and logs.get("stderr_path") == str(BASELINE_STDERR.resolve()), "generation-4 log paths drift")
    require(logs.get("hash_status") == "process_running_hash_not_final" and logs.get("final_sha256") is None, "generation-4 live logs must remain unsealed")
    evidence_map = dict(prior_sha)
    for path in (BASELINE_PRIOR_OBSERVATION, BASELINE_LAUNCH_INTENT, BASELINE_SERVICE_RECEIPT, BASELINE_RECOVERY_RESULT):
        evidence_map[str(path.resolve())] = sha256_path(path)
    if verify_live:
        verify_live_service_identity(started, process_factory=process_factory, listener_func=listener_func,
                                     comfyui_process_func=comfyui_process_func, child_job_query=child_job_query)
    else:
        verify_launch_isolation(started, child_job_query=lambda pid: started["launch_isolation"]["child_is_process_in_job"])
    return evidence_map


def verify_stage_generation7_receipts(stage: dict, *, verify_live: bool = True) -> dict[str, str]:
    evidence = verify_baseline_generation7_chain(verify_live=verify_live)
    retry = stage.get("previous_attempt_recovery")
    require(isinstance(retry, dict), "stage lacks a previous-attempt recovery lineage")
    require(retry.get("release_attempt") == 1 and retry.get("recovery_generation") == 7, "stage does not bind recovery generation 7")
    require(retry.get("active_baseline_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "stage points at an inactive recovery directory")
    require(retry.get("baseline_service_recovery_receipt") == str(BASELINE_RECOVERY_RESULT.resolve()), "stage generation-4 result path drift")
    require(retry.get("prior_recovery_observation") == str(BASELINE_PRIOR_OBSERVATION.resolve()), "stage generation-4 observation path drift")
    baseline_receipts = stage.get("baseline_receipts")
    require(isinstance(baseline_receipts, dict), "stage baseline receipts are missing")
    for path, digest in evidence.items():
        require(baseline_receipts.get(path) == digest, f"stage omits generation-4 recovery-chain evidence: {path}")
    return evidence


def verify_stage_generation3_receipts(stage: dict, *, verify_live: bool = True) -> dict[str, str]:
    """Reject a stage unless it names and seals the active generation-3 chain."""

    evidence = verify_baseline_generation3_chain(verify_live=verify_live)
    retry = stage.get("previous_attempt_recovery")
    require(isinstance(retry, dict), "stage lacks a previous-attempt recovery lineage")
    require(retry.get("release_attempt") == 1, "stage retry release attempt drift")
    require(retry.get("recovery_generation") == 3, "stage does not bind recovery generation 3")
    require(retry.get("active_baseline_recovery_dir") == str(BASELINE_RECOVERY_DIR.resolve()), "stage points at an inactive recovery directory")
    require(retry.get("baseline_service_recovery_receipt") == str(BASELINE_RECOVERY_RESULT.resolve()), "stage recovery result path drift")
    require(retry.get("prior_recovery_observation") == str(BASELINE_PRIOR_OBSERVATION.resolve()), "stage prior observation path drift")
    baseline_receipts = stage.get("baseline_receipts")
    require(isinstance(baseline_receipts, dict), "stage baseline receipts are missing")
    for path, digest in evidence.items():
        require(baseline_receipts.get(path) == digest, f"stage omits recovery-chain evidence: {path}")
    return evidence


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json_atomic(path: Path, payload: Any) -> None:
    path = Path(path)
    temporary = path.with_name("." + path.name + ".tmp")
    require(not os.path.lexists(temporary), f"ambiguous receipt temporary: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException as write_error:
        if os.path.lexists(temporary):
            try:
                temporary.unlink()
            except BaseException as cleanup_error:
                cleanup_error_text = repr(cleanup_error)
                try:
                    write_error.json_temp_cleanup_error = cleanup_error_text
                except BaseException:
                    pass
                try:
                    write_error.add_note(
                        f"receipt temporary cleanup also failed: {cleanup_error_text}"
                    )
                except BaseException:
                    pass
        raise


def run_with_exact_artifact_journal(paths, operation):
    """On failure remove only exact paths absent at entry, deepest paths first."""

    selected = [Path(path).absolute() for path in paths]
    require(len(set(selected)) == len(selected), "artifact journal path collision")
    existed_at_entry = {path: os.path.lexists(path) for path in selected}
    try:
        return operation()
    except BaseException:
        for path in sorted(selected, key=lambda value: len(value.parts), reverse=True):
            if existed_at_entry[path] or not os.path.lexists(path):
                continue
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            except OSError:
                # A path that gained unexpected contents is preserved for inspection.
                pass
        raise


def core_contract() -> tuple[dict, dict, dict]:
    manifest = read_json(MANIFEST_PATH)
    baseline = read_json(BASELINE_PATH)
    amendment = read_json(AMENDMENT_PATH)
    require(manifest["schema"] == "round135-batch2-operation-manifest/v1", "manifest schema drift")
    require(baseline["schema"] == "round135-batch2-baseline-rebase/v1", "baseline schema drift")
    require(amendment["schema"] == "round135-batch2-contract-amendment/v1", "amendment schema drift")
    require(manifest["expected_totals"] == EXPECTED_TOTALS, "fixed totals drift")
    require(manifest["baseline_data_sha256"] == baseline["rebased_baseline"]["data_sha256"], "data baseline mismatch")
    require(manifest["baseline_semantic_sha256"] == baseline["rebased_baseline"]["semantic_refinements_sha256"], "semantic baseline mismatch")
    require(amendment["resolution"]["authorized_records"] == EXPECTED_TOTALS["changed_records"], "resolution record total drift")
    evidence_paths = {
        "inventory": INVENTORY,
        "ledger": LEDGER,
        "eligibility_resolution": ELIGIBILITY_RESOLUTION,
        "second_pass_review": SECOND_PASS_REVIEW,
    }
    evidence_hash_keys = {
        "inventory": "inventory_file_sha256",
        "ledger": "ledger_file_sha256",
        "eligibility_resolution": "eligibility_resolution_sha256",
        "second_pass_review": "second_pass_review_sha256",
    }
    for name, evidence in evidence_paths.items():
        require((ROOT / manifest["evidence"][name]).resolve() == evidence.resolve(), f"manifest evidence path drift: {name}")
        require(evidence.is_file(), f"missing contract evidence: {name}")
        require(sha256_path(evidence) == manifest["evidence"][evidence_hash_keys[name]], f"manifest evidence drift: {name}")
        if name in amendment["evidence"]:
            require((ROOT / amendment["evidence"][name]).resolve() == evidence.resolve(), f"amendment evidence path drift: {name}")
            require(sha256_path(evidence) == amendment["evidence"][name + "_sha256"], f"contract evidence drift: {name}")

    inventory = read_jsonl(INVENTORY)
    ledger = read_jsonl(LEDGER)
    resolution = read_json(ELIGIBILITY_RESOLUTION)
    second_pass = read_json(SECOND_PASS_REVIEW)
    require(len(inventory) == len(ledger) == 212, "frozen evidence row count drift")
    require(second_pass["totals"] == {
        "covered": 212, "authorized": 201, "blocked": 11,
        "parent_operations": 206, "node_operations": 8, "new_flags": 0,
    }, "second-pass frozen totals drift")
    ordered_ids = [row["id"] for row in inventory]
    candidate_ids_sha256 = hashlib.sha256("\n".join(ordered_ids).encode("utf-8")).hexdigest()
    require(candidate_ids_sha256 == manifest["evidence"]["candidate_ids_sha256"], "frozen candidate ID order hash drift")
    require(candidate_ids_sha256 == resolution["baseline"]["candidate_ids_sha256"], "resolution candidate ID order hash drift")
    require(len(set(ordered_ids)) == 212, "duplicate frozen inventory ID")

    decisions = resolution["decisions"]
    require(len({row["review_no"] for row in decisions}) == len(decisions), "duplicate resolution review number")
    resolution_by_no = {row["review_no"]: row for row in decisions}
    operation_by_no = {row["review_no"]: row for row in manifest["operations"]}
    blockers = manifest["candidate_contract"]["blocked_exact_bindings"]
    blocker_by_no = {row["review_no"]: row for row in blockers}
    require(len(operation_by_no) == len(manifest["operations"]) == 201, "duplicate manifest review number")
    require(len(blocker_by_no) == len(blockers) == 11, "duplicate blocker review number")
    require(set(operation_by_no).isdisjoint(blocker_by_no), "authorized and blocked review numbers overlap")
    require(set(operation_by_no) | set(blocker_by_no) == set(range(1, 213)), "frozen review partition is not exact")

    authorized_ids: list[str] = []
    blocked_ids: list[str] = []
    for index, (frozen, review) in enumerate(zip(inventory, ledger, strict=True), start=1):
        require(review["review_no"] == review["inventory_row"] == index, f"frozen row order drift: {index}")
        require(frozen["id"] == review["id"], f"frozen ID mismatch: {index}")
        require(frozen["prompt_sha256"] == review["prompt_sha256"], f"frozen prompt binding mismatch: {index}")
        if review["verdict"] == "accept":
            final = "accept"
        else:
            require(index in resolution_by_no, f"missing resolution row: {index}")
            resolved = resolution_by_no[index]
            require(resolved["id"] == review["id"] and resolved["prompt_sha256"] == review["prompt_sha256"], f"resolution binding drift: {index}")
            require(resolved["original_verdict"] == review["verdict"], f"resolution original verdict drift: {index}")
            final = resolved["final_decision"]
        if final == "accept":
            require(index in operation_by_no, f"authorized frozen row absent from manifest: {index}")
            operation = operation_by_no[index]
            require(operation["id"] == frozen["id"] and operation["prompt_sha256"] == frozen["prompt_sha256"], f"authorized manifest binding drift: {index}")
            require(operation["parents_before"] == frozen["parents_before"], f"authorized parent baseline drift: {index}")
            require(operation["parent_add"] == frozen["parent_add"] and operation["node_add"] == frozen["node_add"], f"authorized operation drift: {index}")
            authorized_ids.append(frozen["id"])
        else:
            require(index in blocker_by_no and index in resolution_by_no, f"blocked frozen row absent from blocker contract: {index}")
            blocker = blocker_by_no[index]
            resolved = resolution_by_no[index]
            for key in ("id", "prompt_sha256"):
                require(blocker[key] == frozen[key] == resolved[key], f"blocked binding drift: {index}:{key}")
            for key in ("decision", "block_class", "reason"):
                source_key = "final_decision" if key == "decision" else key
                require(blocker[key] == resolved[source_key], f"blocked decision drift: {index}:{key}")
            blocked_ids.append(frozen["id"])
    require(authorized_ids == manifest["candidate_contract"]["expected_rule_candidate_ids"], "authorized candidate order drift")
    require(set(authorized_ids).isdisjoint(blocked_ids) and set(authorized_ids) | set(blocked_ids) == set(ordered_ids), "frozen ID partition is not exact")
    for name in (
        "historical_replay_amendment.json",
        "historical_replay_amendment.py",
        "verify_historical_replay_amendment.py",
    ):
        local_copy = BATCH / name
        inherited = PREVIOUS / name
        require(local_copy.is_file() and inherited.is_file(), f"historical amendment source missing: {name}")
        require(local_copy.read_bytes() == inherited.read_bytes(), f"local/inherited historical amendment split-brain: {name}")
    return manifest, baseline, amendment


def planned_paths(manifest: dict) -> dict[str, Path]:
    paths = {
        key: (ROOT / value).resolve()
        for key, value in manifest["transaction_contract"]["planned_artifacts"].items()
    }
    require(paths["staged_data"].parent == DATA.parent.resolve(), "staged data not beside source")
    require(paths["staged_semantic_refinements"].parent == SEMANTIC.parent.resolve(), "staged semantic not beside source")
    require(paths["data_backup"].is_relative_to(BATCH.resolve()), "data backup escaped batch")
    require(paths["semantic_refinements_backup"].is_relative_to(BATCH.resolve()), "semantic backup escaped batch")
    require(len(set(paths.values())) == len(paths), "planned artifact paths collide")
    return paths


def release_attempt_dir(release_attempt: int) -> Path:
    require(isinstance(release_attempt, int) and release_attempt > 0, "invalid release attempt number")
    path = (ATTEMPTS_DIR / f"attempt_{release_attempt:03d}").resolve()
    require(path.parent == ATTEMPTS_DIR.resolve(), "release attempt path escaped attempts directory")
    return path


def load_candidate_contract(*, require_receipt: bool = True) -> dict:
    manifest, baseline, _ = core_contract()
    expected_before = baseline["rebased_baseline"]["semantic_refinements_sha256"]
    require(sha256_path(SEMANTIC) == expected_before, "production semantic source drift")
    require(CANDIDATE_SEMANTIC.is_file(), "missing batch-local semantic_refinements_candidate.py")
    compile(CANDIDATE_SEMANTIC.read_text(encoding="utf-8"), str(CANDIDATE_SEMANTIC), "exec")
    after = sha256_path(CANDIDATE_SEMANTIC)
    require(after != expected_before, "semantic candidate is byte-identical to baseline")
    result = {
        "source_path": str(SEMANTIC.resolve()),
        "candidate_path": str(CANDIDATE_SEMANTIC.resolve()),
        "before_sha256": expected_before,
        "after_sha256": after,
    }
    if require_receipt:
        require(CANDIDATE_RECEIPT.is_file(), "missing semantic_candidate_receipt.json")
        receipt = read_json(CANDIDATE_RECEIPT)
        require(receipt["schema"] == "round135-batch2-semantic-candidate/v1", "semantic receipt schema drift")
        require(receipt["before_sha256"] == expected_before, "semantic lineage before hash drift")
        require(receipt["after_sha256"] == after, "semantic lineage after hash drift")
        require((ROOT / receipt["source_path"]).resolve() == SEMANTIC.resolve(), "semantic lineage source path drift")
        require((ROOT / receipt["candidate_path"]).resolve() == CANDIDATE_SEMANTIC.resolve(), "semantic lineage candidate path drift")
        require(receipt["production_mutated"] is False, "semantic receipt claims production mutation")
        require(receipt["replacement_count"] == 2, "semantic replacement count drift")
        require(tuple(receipt["transform_markers"]) == EXPECTED_TRANSFORM_MARKERS, "semantic transform marker contract drift")
        result["receipt_sha256"] = sha256_path(CANDIDATE_RECEIPT)
        result["transform_markers"] = receipt["transform_markers"]
    planned_paths(manifest)
    return result


def load_semantic(path: Path, package_name: str):
    package = types.ModuleType(package_name)
    package.__path__ = [str(BATCH), str(SELECTOR)]
    sys.modules[package_name] = package
    name = package_name + ".semantic_refinements"
    # Staged semantic sources deliberately use a .tmp suffix.  Bind an
    # explicit source loader so Python does not reject the verified source
    # solely because it has not yet replaced the production .py file.
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    require(spec is not None and spec.loader is not None, f"cannot load semantic source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # A single record is intentionally evaluated several times by the parent,
    # node and planned-operation checks.  Cache those pure semantic functions
    # exactly as the independently validated full-corpus scanner does.
    module._positive_parts = lru_cache(maxsize=8192)(module._positive_parts)
    uncached_extract = module.extract_refinements
    cached_extract = lru_cache(maxsize=16384)(
        lambda body, parents: uncached_extract(body, list(parents))
    )
    module.extract_refinements = (
        lambda body, parents: cached_extract(body, tuple(sorted(parents)))
    )
    return module


def load_projection(package_name: str):
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        package.__path__ = [str(SELECTOR)]
        sys.modules[package_name] = package
    name = package_name + ".semantic_projection"
    spec = importlib.util.spec_from_file_location(name, SELECTOR / "semantic_projection.py")
    require(spec is not None and spec.loader is not None, "cannot load semantic projection")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_rules():
    require(RULES.is_file(), "missing batch-local context_parent_rules.py")
    spec = importlib.util.spec_from_file_location("round135_batch2_context_parent_rules", RULES)
    require(spec is not None and spec.loader is not None, "cannot load batch rules")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("candidates", "additions", "planned_node_changes"):
        require(callable(getattr(module, name, None)), f"batch rules missing {name}")
    require(callable(getattr(module.previous, "candidates", None)), "previous rules missing candidates")
    require(callable(getattr(module.previous, "additions", None)), "previous rules missing additions")
    return module


def historical_exclusion_ledger_paths() -> list[Path]:
    """Return the frozen ledger allowlist used by the 76,831-row scan.

    The previous implementation globbed every file ending in ``ledger.jsonl``.
    That let an unrelated future review silently shrink the release corpus.
    Round ledgers are accepted only from the two established round directories
    through round 134.  Older supplemental ledgers that already contributed
    safety exclusions to the frozen scan are enumerated individually.
    """

    ledger_files: list[Path] = []
    for directory in (FIRST_AUDIT, EXTENSION):
        require(directory.is_dir(), f"historical ledger directory missing: {directory}")
        for path in sorted(directory.glob("round_*_ledger.jsonl")):
            match = re.fullmatch(r"round_(\d+)_ledger\.jsonl", path.name)
            require(match is not None, f"unexpected historical ledger name: {path}")
            if int(match.group(1)) <= 134:
                ledger_files.append(path)
    require(ledger_files and any(path.name == "round_134_ledger.jsonl" for path in ledger_files), "historical exclusion scope does not reach round 134")
    require(not any(path.name == "round_135_ledger.jsonl" for path in ledger_files), "round 135 entered historical exclusions")
    supplemental = [(REPORTS / relative).resolve() for relative in SUPPLEMENTAL_EXCLUSION_LEDGERS]
    require(len(supplemental) == len(set(supplemental)) == 29, "supplemental exclusion ledger allowlist drift")
    require(all(path.is_file() and path.is_relative_to(REPORTS.resolve()) for path in supplemental), "supplemental exclusion ledger missing or escaped reports")
    ledger_files.extend(supplemental)
    require(len(ledger_files) == len(set(ledger_files)), "historical exclusion ledger path collision")
    return ledger_files


def historical_excluded_ids() -> set[str]:
    """Load only the sealed historical exclusion allowlist."""

    excluded: set[str] = set()
    ledger_files = historical_exclusion_ledger_paths()
    for path in ledger_files:
        for row in read_jsonl(path):
            if row.get("verdict") == "excluded" and isinstance(row.get("id"), str):
                excluded.add(row["id"])
    require(len(excluded) == 147, f"historical exclusion identity count drift: {len(excluded)}")
    return excluded


def eligible_records(data: dict, projection, document: dict):
    excluded = historical_excluded_ids()
    checked = 0
    for category in data["categories"]:
        name = category.get("name", "")
        if name.split("/")[0].strip() == "🔞一键模式" or MINOR_CATEGORY.search(name):
            continue
        for prompt in category.get("prompts", []):
            decision = projection.decision_for(document, category, prompt)
            usage = decision.get("declared_usage", decision.get("usage"))
            if (
                not decision.get("manual_search_eligible")
                or decision.get("semantic_review_status") == "user_confirmed"
                or usage == "negative"
                or decision.get("primary_class") == "artist_style"
                or prompt["id"] in excluded
                or RISK.search(prompt.get("prompt", "").replace("_", " "))
                or re.search(r"\bschool days\b", prompt.get("prompt", ""), re.I)
            ):
                continue
            checked += 1
            yield category, prompt, decision
    require(checked == EXPECTED_ELIGIBLE, f"eligible scan count {checked} != {EXPECTED_ELIGIBLE}")


def flatten_operations(rows: list[dict]) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for row in rows:
        for key in ("parent_add", "parent_remove", "node_add", "node_remove"):
            for value in row.get(key, []):
                item = (row["id"], key, value)
                require(item not in result, f"duplicate operation: {item}")
                result.add(item)
    return result


def exact_operation_set(manifest: dict) -> set[tuple[str, str, str, str, str, str]]:
    """Return the operation allowlist with every immutable record binding."""

    result: set[tuple[str, str, str, str, str, str]] = set()
    for row in manifest["operations"]:
        for kind in ("parent_add", "parent_remove", "node_add", "node_remove"):
            for value in row.get(kind, []):
                item = (
                    row["id"], row["category_id"], row["prompt_sha256"],
                    row["classification_before_sha256"], kind, value,
                )
                require(item not in result, f"duplicate bound operation: {item}")
                result.add(item)
    return result


def expected_rule_operation_set(manifest: dict) -> set[tuple[str, str, str, str, str, str]]:
    result = exact_operation_set(manifest)
    require({item[0] for item in result} == set(manifest["candidate_contract"]["expected_rule_candidate_ids"]), "rule-ID contract drift")
    return result


def scan_rule_operations(
    data: dict,
    projection,
    projection_document: dict,
    baseline_semantic,
    candidate_semantic,
    rules,
) -> dict:
    operations: set[tuple[str, str, str, str, str, str]] = set()
    records: dict[str, dict] = {}
    manifest = read_json(MANIFEST_PATH)
    blockers = manifest["candidate_contract"]["blocked_exact_bindings"]
    blocker_by_id = {row["id"]: row for row in blockers}
    require(len(blocker_by_id) == len(blockers) == 11, "blocked exact-binding identity drift")
    data_records = record_map(data)
    blocked_verified: set[str] = set()
    for blocker in blockers:
        key = (blocker["id"], blocker["category_id"])
        require(key in data_records, f"blocked record missing: {key}")
        blocked_prompt = data_records[key]
        require(prompt_sha256(blocked_prompt.get("prompt", "")) == blocker["prompt_sha256"], f"blocked prompt drift: {blocker['id']}")
        require(classification_sha256(blocked_prompt["_classification"]) == blocker["classification_before_sha256"], f"blocked classification drift: {blocker['id']}")
        blocked_verified.add(blocker["id"])
    semantic_blocked_seen: set[str] = set()
    checked = 0
    for category, prompt, decision in eligible_records(data, projection, projection_document):
        checked += 1
        body = prompt.get("prompt", "")
        prefilter_body = normalized_prefilter_text(body)
        if not RULE_PREFILTER.search(prefilter_body) and not NODE_PREFILTER.search(prefilter_body):
            continue
        if prompt["id"] in blocker_by_id:
            binding = blocker_by_id[prompt["id"]]
            require(prompt_sha256(body) == binding["prompt_sha256"], f"eligibility block prompt drift: {prompt['id']}")
            require(category["id"] == binding["category_id"], f"eligibility block category drift: {prompt['id']}")
            require(classification_sha256(prompt["_classification"]) == binding["classification_before_sha256"], f"blocked classification drift: {prompt['id']}")
            if binding["block_class"] == "semantic":
                semantic_blocked_seen.add(prompt["id"])
            continue
        parents = list(projection.selector_subcategories(decision, prompt))
        previous_removed = set(rules.previous.candidates(body, parents, baseline_semantic))
        previous_added = set(rules.previous.additions(body, parents, baseline_semantic))
        removed = [
            value for value in rules.candidates(body, parents, candidate_semantic)
            if value in parents and value not in previous_removed
        ]
        added = [
            value for value in rules.additions(body, parents, candidate_semantic)
            if value not in parents and value not in previous_added
        ]
        require(len(removed) == len(set(removed)), f"duplicate parent remove: {prompt['id']}")
        require(len(added) == len(set(added)), f"duplicate parent add: {prompt['id']}")
        parents_after = [value for value in parents if value not in set(removed)] + added
        node_add: list[str] = []
        node_remove: list[str] = []
        if removed or added or NODE_PREFILTER.search(prefilter_body):
            nodes_before = set(baseline_semantic.extract_refinements(body, parents))
            nodes_after = set(candidate_semantic.extract_refinements(body, parents_after))
            node_add = sorted(nodes_after - nodes_before)
            node_remove = sorted(nodes_before - nodes_after)
            planned = rules.planned_node_changes(body, parents_after, candidate_semantic)
            require(set(planned) == {"add", "remove"}, f"invalid planned node shape: {prompt['id']}")
            # Intentions may include a removal whose parent rule removes the parent;
            # the actual semantic diff remains authoritative and must contain it.
            require(set(planned["add"]) <= set(node_add), f"planned node add absent: {prompt['id']}")
            planned_remove = set(planned["remove"])
            require(planned_remove <= set(node_remove) | nodes_before, f"planned node remove absent: {prompt['id']}")
        if removed or added or node_add or node_remove:
            require(prompt["id"] not in records, f"duplicate scan ID: {prompt['id']}")
            classification_before = classification_sha256(prompt["_classification"])
            records[prompt["id"]] = {
                "id": prompt["id"],
                "category_id": category["id"],
                "prompt_sha256": prompt_sha256(body),
                "classification_before_sha256": classification_before,
                "parent_add": added,
                "parent_remove": removed,
                "node_add": node_add,
                "node_remove": node_remove,
            }
            for kind, values in (
                ("parent_add", added), ("parent_remove", removed),
                ("node_add", node_add), ("node_remove", node_remove),
            ):
                operations.update(
                    (
                        prompt["id"], category["id"], prompt_sha256(body),
                        classification_before, kind, value,
                    )
                    for value in values
                )
    expected = expected_rule_operation_set(manifest)
    require(operations == expected, f"rule operation set differs: extra={sorted(operations-expected)} missing={sorted(expected-operations)}")
    expected_ids = set(manifest["candidate_contract"]["expected_rule_candidate_ids"])
    require(set(records) == expected_ids, f"rule candidate IDs differ: {sorted(set(records)^expected_ids)}")
    semantic_blockers = {row["id"] for row in blockers if row["block_class"] == "semantic"}
    require(semantic_blocked_seen == semantic_blockers, f"semantic blockers not observed by eligible scan: {sorted(semantic_blockers-semantic_blocked_seen)}")
    require(blocked_verified == set(blocker_by_id), "not every blocker exact binding was verified")
    return {
        "eligible_records": checked,
        "candidate_ids": sorted(records),
        "operation_count": len(operations),
        "operations": [list(item) for item in sorted(operations)],
        "records": records,
        "blocked_binding_ids": sorted(blocked_verified),
        "semantic_blocked_ids": sorted(semantic_blocked_seen),
    }


def record_map(document: dict) -> dict[tuple[str, str], dict]:
    result: dict[tuple[str, str], dict] = {}
    for category in document["categories"]:
        for prompt in category.get("prompts", []):
            key = (prompt["id"], category["id"])
            require(key not in result, f"duplicate record binding: {key}")
            result[key] = prompt
    return result


def apply_manifest(document: dict, manifest: dict, baseline_semantic, candidate_semantic) -> list[dict]:
    records = record_map(document)
    patches: list[dict] = []
    for operation in manifest["operations"]:
        key = (operation["id"], operation["category_id"])
        require(key in records, f"manifest record missing: {key}")
        prompt = records[key]
        require(prompt_sha256(prompt["prompt"]) == operation["prompt_sha256"], f"prompt drift: {operation['id']}")
        before_classification = copy.deepcopy(prompt["_classification"])
        require(classification_sha256(before_classification) == operation["classification_before_sha256"], f"classification drift: {operation['id']}")
        before = list(before_classification["subcategories"])
        require(before == operation["parents_before"], f"parent order drift: {operation['id']}")
        require(set(operation["parent_remove"]) <= set(before), f"missing parent removal: {operation['id']}")
        require(not set(operation["parent_add"]) & set(before), f"parent add already present: {operation['id']}")
        after = [value for value in before if value not in set(operation["parent_remove"])] + list(operation["parent_add"])
        prompt["_classification"]["subcategories"] = after
        nodes_before = sorted(set(baseline_semantic.extract_refinements(prompt["prompt"], before)))
        nodes_after = sorted(set(candidate_semantic.extract_refinements(prompt["prompt"], after)))
        require(set(nodes_after) - set(nodes_before) == set(operation["node_add"]), f"node additions drift: {operation['id']}")
        require(set(nodes_before) - set(nodes_after) == set(operation["node_remove"]), f"node removals drift: {operation['id']}")
        patches.append({
            "review_no": operation["review_no"],
            "id": operation["id"],
            "category_id": operation["category_id"],
            "source_text_sha256": operation["prompt_sha256"],
            "classification_before_sha256": operation["classification_before_sha256"],
            "classification_before": before_classification,
            "classification_after": copy.deepcopy(prompt["_classification"]),
            "before": before,
            "after": after,
            "removed": list(operation["parent_remove"]),
            "added": list(operation["parent_add"]),
            "nodes_before": nodes_before,
            "nodes_after": nodes_after,
            "node_removed": list(operation["node_remove"]),
            "node_added": list(operation["node_add"]),
            "operation_sources": operation["operation_sources"],
        })
    require(flatten_operations([
        {
            "id": row["id"],
            "parent_add": row["added"], "parent_remove": row["removed"],
            "node_add": row["node_added"], "node_remove": row["node_removed"],
        } for row in patches
    ]) == flatten_operations(manifest["operations"]), "applied operations differ from manifest")
    return patches


def assert_minimal_data_delta(before: dict, after: dict, patches: list[dict]) -> None:
    require(before.keys() == after.keys(), "top-level data keys changed")
    before_records = record_map(before)
    after_records = record_map(after)
    require(before_records.keys() == after_records.keys(), "record identity set changed")
    patch_map = {(row["id"], row["category_id"]): row for row in patches}
    changed: set[tuple[str, str]] = set()
    for key in before_records:
        left = before_records[key]
        right = after_records[key]
        if key not in patch_map:
            require(left == right, f"non-target record changed: {key}")
            continue
        patch = patch_map[key]
        restored = copy.deepcopy(right)
        restored["_classification"] = copy.deepcopy(patch["classification_before"])
        require(restored == left, f"target changed outside classification: {key}")
        require(right["_classification"] == patch["classification_after"], f"target classification differs from patch: {key}")
        changed.add(key)
    require(changed == set(patch_map), "not every patch changed one record")
    normalized = copy.deepcopy(after)
    normalized_records = record_map(normalized)
    for key, patch in patch_map.items():
        normalized_records[key]["_classification"] = copy.deepcopy(patch["classification_before"])
    require(normalized == before, "non-target document field changed")


def assert_patch_totals(patches: list[dict]) -> dict:
    totals = {
        "changed_records": len(patches),
        "parent_slots_added": sum(len(row["added"]) for row in patches),
        "parent_slots_removed": sum(len(row["removed"]) for row in patches),
        "refinement_nodes_added": sum(len(row["node_added"]) for row in patches),
        "refinement_nodes_removed": sum(len(row["node_removed"]) for row in patches),
    }
    require(totals == EXPECTED_TOTALS, f"patch totals drift: {totals}")
    return totals


def assert_complete_index_contract(index: dict) -> dict:
    require(index["review_counts"]["pending"] == EXPECTED_PENDING, "pending count drift")
    groups = index["selector_groups"]
    mappings = index["selector_class_kinds"]
    require(tuple(groups) == EXPECTED_COLLECTION_KINDS, "selector group kinds incomplete")
    require(all(isinstance(groups[kind], list) and groups[kind] for kind in EXPECTED_COLLECTION_KINDS), "empty selector group")
    require(mappings == EXPECTED_CLASS_ROUTES, "selector class route drift")
    return {
        "pending": EXPECTED_PENDING,
        "selector_group_kinds": len(groups),
        "selector_class_mappings": len(mappings),
        "contract_items": 1 + len(groups) + len(mappings),
        "passed": True,
    }


def _verify_seal_state(
    sealed: dict,
    *,
    required_paths: set[Path],
    allowed_root: Path,
    consumed_sha256: dict[Path, str] | None = None,
    expected_consumed_sha256: dict[Path, str] | None = None,
) -> dict:
    """Verify a complete seal or its exact post-``os.replace`` state.

    A staged file is *consumed* by ``os.replace``: its bytes move to the
    production path and the staged path must disappear.  That expected absence
    is different from immutable-artifact drift, so callers must explicitly
    provide the two consumed paths and their preflight-bound hashes.
    """

    require(isinstance(sealed, dict) and sealed, "empty preflight seal")
    root = allowed_root.resolve()

    def lexical_path(raw_path: str | Path, label: str) -> Path:
        path = Path(os.path.abspath(os.fspath(raw_path)))
        require(path.is_absolute() and path.is_relative_to(root), f"{label} escaped workspace: {path}")
        require(path.parent.resolve().is_relative_to(root), f"{label} parent escaped workspace: {path}")
        return path

    entries: dict[Path, str] = {}
    for raw_path, expected in sealed.items():
        require(isinstance(raw_path, str) and isinstance(expected, str), "invalid preflight seal entry")
        require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"invalid sealed SHA-256: {raw_path}")
        path = lexical_path(raw_path, "sealed path")
        require(path not in entries, f"duplicate sealed path: {path}")
        entries[path] = expected

    required = {lexical_path(path, "required sealed path") for path in required_paths}
    require(required <= set(entries), f"preflight seal missing release definitions: {sorted(map(str, required - set(entries)))}")

    consumed: dict[Path, str] = {}
    if consumed_sha256 is not None:
        require(isinstance(consumed_sha256, dict) and len(consumed_sha256) == 2, "exactly two consumed staged artifacts required")
        for raw_path, expected in consumed_sha256.items():
            path = lexical_path(raw_path, "consumed staged path")
            require(path not in consumed, f"duplicate consumed staged path: {path}")
            require(path in entries, f"consumed staged path missing from preflight seal: {path}")
            require(entries[path] == expected, f"consumed staged SHA-256 differs from preflight seal: {path}")
            consumed[path] = expected
        require(
            isinstance(expected_consumed_sha256, dict) and len(expected_consumed_sha256) == 2,
            "exact expected consumed staged artifacts required",
        )
        expected_consumed: dict[Path, str] = {}
        for raw_path, expected in expected_consumed_sha256.items():
            path = lexical_path(raw_path, "expected consumed staged path")
            require(path not in expected_consumed, f"duplicate expected consumed staged path: {path}")
            expected_consumed[path] = expected
        require(consumed == expected_consumed, "consumed staged artifacts differ from exact planned paths/hashes")
    else:
        require(expected_consumed_sha256 is None, "expected consumed artifacts supplied for complete seal")

    for path, expected in entries.items():
        if path in consumed:
            require(not os.path.lexists(path), f"consumed staged artifact unexpectedly exists: {path}")
        else:
            require(not path.is_symlink(), f"immutable sealed artifact may not be a symlink: {path}")
            require(path.is_file() and sha256_path(path) == expected, f"sealed artifact drift: {path}")

    return {
        "mode": "post_atomic_consumption" if consumed_sha256 is not None else "complete_pre_transaction",
        "sealed_artifacts": len(entries),
        "immutable_artifacts_verified": len(entries) - len(consumed),
        "consumed_artifacts_absent": len(consumed),
        "consumed_sha256": {str(path): expected for path, expected in consumed.items()},
        "passed": True,
    }


def verify_preflight_seal(preflight: dict) -> dict:
    """Require every preflight-sealed artifact to exist with its sealed hash."""

    return _verify_seal_state(
        preflight["sealed_artifact_sha256"],
        required_paths=set(release_definition_paths()),
        allowed_root=ROOT,
    )


def verify_preflight_seal_after_consumption(
    preflight: dict,
    consumed_sha256: dict[Path, str],
) -> dict:
    """Verify immutable seals and exact absence of two atomically consumed stages."""

    manifest = read_json(MANIFEST_PATH)
    paths = planned_paths(manifest)
    expected_consumed = {
        paths["staged_data"]: preflight["after_sha256"]["data"],
        paths["staged_semantic_refinements"]: preflight["after_sha256"]["semantic_refinements"],
    }
    return _verify_seal_state(
        preflight["sealed_artifact_sha256"],
        required_paths=set(release_definition_paths()),
        allowed_root=ROOT,
        consumed_sha256=consumed_sha256,
        expected_consumed_sha256=expected_consumed,
    )


def release_definition_paths() -> list[Path]:
    names = (
        "baseline_rebase.json", "contract_amendment.json", "operation_manifest.json", "build_manifest.py",
        "DESIGN.md", "context_parent_rules.py", "semantic_refinements_candidate.py",
        "semantic_candidate_receipt.json", "setup_receipt.json", "setup.py", "validate_contracts.py", "contract_validation.json",
        "scan.py", "rule_scan_summary.json", "rule_candidates.jsonl",
        "verify_contexts.py", "context_verification.json",
        "check_new_rules.py", "new_rules_check.json",
        "compare_full_semantics.py", "full_semantic_compare.json",
        "transaction_common.py", "stage.py", "verify_staged_pipeline.py",
        "verify_linkage_backend.py", "preflight.py", "recover_baseline_service.py",
        "restart_production.py", "verify_live.py",
        "test_dual_transaction_readonly.py", "inspect_taxonomy_state.py", "write_taxonomy_catalog.py",
        "historical_replay_amendment.json", "historical_replay_amendment.py",
        "verify_historical_replay_amendment.py",
    )
    paths = [BATCH / name for name in names]
    paths.extend([
        REPORTS / "2026-09-23_consecutive_round135_batch2_expression_gaze_pose_inventory/candidate_inventory.jsonl",
        REPORTS / "2026-09-23_consecutive_round135_batch2_expression_gaze_pose_inventory/fulltext_review_ledger.jsonl",
        REPORTS / "2026-09-23_consecutive_round135_batch2_expression_gaze_pose_inventory/eligibility_resolution.json",
        REPORTS / "2026-09-23_consecutive_round135_batch2_expression_gaze_pose_inventory/second_pass_review_receipt.json",
        PREVIOUS / "historical_replay_amendment.json",
        PREVIOUS / "historical_replay_amendment.py",
        PREVIOUS / "historical_replay_amendment_verification.json",
    ])
    paths.extend(historical_exclusion_ledger_paths())
    require(all(path.is_file() for path in paths), "release definition file missing")
    require(len({path.resolve() for path in paths}) == len(paths), "release definition path collision")
    return paths


def historical_round_rows_through_134() -> list[dict]:
    """Return amended main ledgers through 134, never round 135."""

    amendment_path = REPORTS / "2026-09-23_consecutive_backlog_wave1/review_amendments.py"
    spec = importlib.util.spec_from_file_location("round135_batch2_review_amendments", amendment_path)
    require(spec is not None and spec.loader is not None, "cannot load review amendments")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows: list[dict] = []
    files: list[Path] = []
    for folder in (FIRST_AUDIT, EXTENSION):
        for path in sorted(folder.glob("round_*_ledger.jsonl")):
            match = re.fullmatch(r"round_(\d+)_ledger\.jsonl", path.name)
            require(match is not None, f"unexpected round ledger name: {path}")
            round_number = int(match.group(1))
            if round_number <= 134:
                files.append(path)
                for row in read_jsonl(path):
                    amended = module.amend_review(row)
                    amended, _ = apply_historical_replay_amendment(round_number, amended)
                    rows.append(amended)
    require(files and max(int(re.search(r"round_(\d+)", path.name).group(1)) for path in files) == 134, "historical replay does not end at round 134")
    require(not any("round_135" in str(path) for path in files), "round 135 entered historical replay")

    previous = REPORTS / "2026-09-23_consecutive_backlog_wave1"
    costume = read_json(previous / "costume_ears_amendment.json")
    definition = read_json(previous / "definition_amendment.json")
    stockings = read_json(previous / "stockings_definition_amendment.json")
    for row in rows:
        if row["id"] == costume["id"]:
            require(row["prompt_sha256"] == costume["prompt_sha256"], "costume amendment binding drift")
            row.clear(); row.update(copy.deepcopy(costume))
        if row["id"] == definition["id"]:
            require(row["prompt_sha256"] == definition["prompt_sha256"], "definition amendment binding drift")
            row["remove_nodes"] = [node for node in row.get("remove_nodes", []) if node != definition["node"]]
        if row["id"] == stockings["id"]:
            require(row["prompt_sha256"] == stockings["prompt_sha256"], "stockings amendment binding drift")
            row["remove_nodes"] = []
    return rows


def replay_history_through_134(data: dict, projection, projection_document: dict, semantic) -> int:
    rows = historical_round_rows_through_134()
    by_id = {row["id"]: row for row in rows}
    excluded = {row["id"] for row in rows if row.get("verdict") == "excluded"}
    seen: set[str] = set()
    for category in data["categories"]:
        for prompt in category.get("prompts", []):
            row = by_id.get(prompt["id"])
            if row is None or row["id"] in excluded:
                continue
            require(category["id"] == row["category_id"], f"historical category drift: {row['id']}")
            require(prompt_sha256(prompt["prompt"]) == row["prompt_sha256"], f"historical prompt drift: {row['id']}")
            decision = projection.decision_for(projection_document, category, prompt)
            parents = projection.selector_subcategories(decision, prompt)
            nodes = set(semantic.extract_refinements(prompt["prompt"], parents))
            if row.get("verdict") == "clean":
                expected = row.get("target_expected_present", True)
                require((row["target_parent"] in parents) == expected, f"historical clean parent drift: {row['id']}")
                if row.get("target_node"):
                    require((row["target_node"] in nodes) == expected, f"historical clean node drift: {row['id']}")
            require(not set(row.get("remove", [])) & set(parents), f"historical parent removal regressed: {row['id']}")
            require(set(row.get("add", [])) <= set(parents), f"historical parent addition lost: {row['id']}")
            require(not set(row.get("remove_nodes", [])) & nodes, f"historical node removal regressed: {row['id']}")
            require(set(row.get("add_nodes", [])) <= nodes, f"historical node addition lost: {row['id']}")
            require(set(row.get("retain_nodes", [])) <= nodes, f"historical retained node lost: {row['id']}")
            require(set(row.get("retain_parents", [])) <= set(parents), f"historical retained parent lost: {row['id']}")
            seen.add(row["id"])
    expected = set(by_id) - excluded
    require(expected <= seen, f"historical replay records missing: {sorted(expected-seen)[:5]}")
    return len(seen)
