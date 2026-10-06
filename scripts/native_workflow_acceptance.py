"""Preflight or execute an unchanged native UI API export against local ComfyUI.

The default only reads the service/runtime and writes new external evidence.
--execute authorizes one POST to the existing loopback 8188 service. This tool
never compiles UI graphs, changes exported nodes, downloads, clears a queue,
frees models, restarts a service, or overwrites evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import stat
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:8188"
DEFAULT_QA_PREFIX = "_codex_qa/final_acceptance_20261007/"
FORBIDDEN_NODE_TERMS = ("caption", "api", "http", "download", "llm", "python", "shell", "execute", "script")
FORBIDDEN_INPUT_KEYS = {"api_key", "apikey", "token", "cookie", "authorization", "base_url", "endpoint", "url"}
SAFE_OUTPUT_TYPES = {"SaveImage"}
# The suffix identifies the weights' upstream training format, not script
# execution. Reviewed implementation: ComfyUI-Anima-LLLite/nodes.py.
REVIEWED_LOCAL_NODE_NAMES = {"AnimaLLLiteApply_sdscripts"}


class AcceptanceError(RuntimeError):
    pass


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceError("Duplicate JSON key in native export")
        result[key] = value
    return result


def reject_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            properties = part.lstat()
            if part.is_symlink() or getattr(properties, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                raise AcceptanceError("Symlink/junction path is not accepted")


def portable_relative(value: str, *, allow_trailing_slash: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise AcceptanceError("Expected a portable relative path")
    trimmed = value[:-1] if allow_trailing_slash and value.endswith("/") else value
    parts = trimmed.split("/")
    if PurePosixPath(trimmed).is_absolute() or PureWindowsPath(trimmed).is_absolute() or PureWindowsPath(trimmed).drive:
        raise AcceptanceError("Absolute path is forbidden")
    if any(part in ("", ".", "..") or re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((" ", "."))
           or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I) for part in parts):
        raise AcceptanceError("Unsafe relative path component")
    return value


def qa_prefix(value: str) -> str:
    portable_relative(value, allow_trailing_slash=True)
    if not value.startswith("_codex_qa/") or not value.endswith("/") or len(value.split("/")) < 3:
        raise AcceptanceError("QA prefix must be a directory below _codex_qa/")
    return value


def targets_from_arguments(values: list[str]) -> list[str]:
    targets = [part.strip() for value in values for part in value.split(",")]
    if not targets or any(not value for value in targets) or len(targets) != len(set(targets)) or len(targets) > 32:
        raise AcceptanceError("Choose 1--32 distinct output targets")
    return targets


def load_export(path: Path) -> tuple[bytes, dict[str, Any]]:
    reject_links(path)
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise AcceptanceError("Native export must be an ordinary JSON file up to 32 MiB")
    raw = path.read_bytes()
    graph = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=no_duplicate_keys)
    if not isinstance(graph, dict) or not graph:
        raise AcceptanceError("Expected the direct native UI API node dictionary")
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise AcceptanceError("Expected API class_type/inputs nodes; UI workflow graphs are not accepted")
    return raw, graph


def links_in(value: Any):
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int:
        if value[1] < 0:
            raise AcceptanceError("Negative API output slot")
        yield value[0]
    elif isinstance(value, list):
        for item in value:
            yield from links_in(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from links_in(item)


def dependency_closure(graph: dict[str, Any], targets: list[str]) -> dict[str, Any]:
    visited = set()
    visiting = set()

    def visit(node_id: str):
        if node_id in visited:
            return
        if node_id in visiting:
            raise AcceptanceError("Native API dependency cycle")
        if node_id not in graph:
            raise AcceptanceError("Target or linked node is missing from native export")
        visiting.add(node_id)
        for source in links_in(graph[node_id]["inputs"]):
            visit(source)
        visiting.remove(node_id)
        visited.add(node_id)

    for target in targets:
        visit(target)
    # Projection preserves each original node object and its insertion order.
    return {key: node for key, node in graph.items() if key in visited}


def is_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and type(value[1]) is int


def assert_local_inputs(value: Any):
    if isinstance(value, str) and re.search(r"(?:https?|ftp|file|ws|wss)://", value, re.I):
        raise AcceptanceError("URL-bearing executable input is forbidden")
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_INPUT_KEYS or key.lower().endswith(("_api_key", "_endpoint", "_url")):
                raise AcceptanceError("Credential/network input is forbidden")
            assert_local_inputs(child)
    elif isinstance(value, list):
        for child in value:
            assert_local_inputs(child)


def plain_weilin_text(value: Any) -> bool:
    if not isinstance(value, str) or "<wlr:" in value.lower():
        return False
    try:
        json.loads(value)
    except (ValueError, TypeError):
        return True
    return False


def inactive_weilin_dependency(inputs: dict[str, Any]) -> bool:
    # Only the reviewed no-LoRA/no-random literal text path. Linked text could
    # supply <wlr:...> at execution time, so schema STRING alone is insufficient.
    return (inputs.get("auto_random") is False
            and all(inputs.get(field) == "" for field in ("lora_str", "temp_str", "temp_lora_str", "random_template"))
            and plain_weilin_text(inputs.get("positive"))
            and ("opt_text" not in inputs or plain_weilin_text(inputs["opt_text"]))
            and "opt_clip" not in inputs and "opt_model" not in inputs)


def typed_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as error:
        raise AcceptanceError("Execution reference/history must contain finite JSON values") from error


def backend_validation_walk(graph: dict[str, Any], targets: list[str], info: dict[str, Any]) -> list[str]:
    """Match the backend's target-to-dependency declared-input validation walk.

    Flexible optional dictionaries may accept more inputs during execution but
    expose no enumerated keys. Such dynamic edges belong to the unchanged
    execution closure and must not invent queue-time validation conversions.
    """
    visited = set()

    def visit(node_id):
        if node_id in visited:
            return
        if node_id not in graph:
            raise AcceptanceError("Declared validation dependency is missing")
        visited.add(node_id)
        node = graph[node_id]
        fields = info[node["class_type"]].get("input", {})
        declared = set(fields.get("required", {})) | set(fields.get("optional", {}))
        for field in declared:
            value = node["inputs"].get(field)
            if is_link(value):
                visit(value[0])

    for target in targets:
        visit(target)
    return [node_id for node_id in graph if node_id in visited]


def backend_validation_reference(graph: dict[str, Any], info: dict[str, Any], targets: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Predict only execution.validate_inputs' declared literal conversions.

    Preserve submission nodes. The current backend unwraps __value__, then
    casts declared INT/FLOAT/STRING/BOOLEAN values on nodes reached from targets
    through enumerated required/optional links. Unknown dynamic fields, links,
    and nodes outside that validation walk retain their original JSON types.
    """
    expected = copy.deepcopy(graph)
    validated_nodes = set(backend_validation_walk(graph, targets, info))
    changes = []
    casts = {"INT": int, "FLOAT": float, "STRING": str, "BOOLEAN": bool}
    for node_id, node in expected.items():
        if node_id not in validated_nodes:
            continue
        spec = info[node["class_type"]]
        definitions = {**spec.get("input", {}).get("required", {}), **spec.get("input", {}).get("optional", {})}
        for field, definition in definitions.items():
            if field not in node["inputs"] or not isinstance(definition, list) or not definition:
                continue
            original = node["inputs"][field]
            if isinstance(original, list):
                continue
            value = original
            operations = []
            if isinstance(value, dict) and "__value__" in value:
                value = value["__value__"]
                operations.append("unwrap __value__")
            declared = definition[0]
            if isinstance(declared, str) and declared in casts:
                try:
                    value = casts[declared](value)
                except (TypeError, ValueError, OverflowError) as error:
                    raise AcceptanceError("Backend literal conversion would fail: " + node["class_type"] + "." + field) from error
                operations.append(declared)
            if typed_json(value) != typed_json(original):
                node["inputs"][field] = value
                changes.append({"node_id": node_id, "field": field, "operations": operations,
                                "before": original, "after": value})
    typed_json(expected)
    return expected, changes


def validate_graph(graph: dict[str, Any], targets: list[str], info: dict[str, Any], runtime: Path, prefix: str) -> dict[str, Any]:
    prefix = qa_prefix(prefix)
    output_root = runtime / "ComfyUI/output"
    reject_links(output_root / prefix)
    enum_checks = 0
    for node_id, node in graph.items():
        kind = node["class_type"]
        if kind not in info:
            raise AcceptanceError("Unregistered backend node in target closure: " + kind)
        if kind not in REVIEWED_LOCAL_NODE_NAMES and any(term in kind.lower() for term in FORBIDDEN_NODE_TERMS):
            raise AcceptanceError("Network/caption/executable node forbidden: " + kind)
        assert_local_inputs(node["inputs"])
        spec = info[kind]
        if spec.get("api_node"):
            raise AcceptanceError("API backend node forbidden: " + kind)
        if kind == "AnimaLLLiteApply_sdscripts":
            weights_name = node["inputs"].get("lllite_name")
            if not isinstance(weights_name, str) or not weights_name.endswith(".safetensors"):
                raise AcceptanceError("Reviewed local Anima LLLite dependency requires literal safetensors weights")
        inactive_cleanup = kind == "VRAMCleanup" and node["inputs"].get("offload_model") is False and node["inputs"].get("offload_cache") is False
        if kind == "VRAMCleanup" and not inactive_cleanup:
            raise AcceptanceError("VRAMCleanup dependency requires both offload flags to be literal false")
        inactive_weilin = kind == "WeiLinPromptUI" and inactive_weilin_dependency(node["inputs"])
        if kind == "WeiLinPromptUI" and not inactive_weilin:
            raise AcceptanceError("WeiLinPromptUI dependency requires literal no-LoRA/no-random plain text inputs")
        if spec.get("output_node") and kind not in SAFE_OUTPUT_TYPES and not inactive_cleanup and not inactive_weilin:
            raise AcceptanceError("Only SaveImage output nodes are accepted")
        if kind == "SaveImage":
            filename_prefix = node["inputs"].get("filename_prefix")
            portable_relative(filename_prefix)
            if not filename_prefix.startswith(prefix) or len(filename_prefix) == len(prefix):
                raise AcceptanceError("SaveImage filename_prefix is outside the reviewed QA directory")
            reject_links(output_root / filename_prefix)
        if kind == "LoadImage":
            image = node["inputs"].get("image")
            portable_relative(image)
            source = runtime / "ComfyUI/input" / image
            reject_links(source)
            if not source.is_file():
                raise AcceptanceError("Native export input image is absent")
        definitions = {**spec.get("input", {}).get("required", {}), **spec.get("input", {}).get("optional", {})}
        for field, value in node["inputs"].items():
            definition = definitions.get(field)
            if kind == "DazzleSwitch" and field == "select" and not is_link(value):
                # The reviewed ComfyUI-DazzleSwitch/py/node.py declares only a
                # static sentinel, while VALIDATE_INPUTS admits JS-populated
                # selections. Accept just its two documented sentinels or an
                # actually supplied, non-None input_NN; all other enums,
                # including this node's mode, keep the ordinary strict check.
                sentinel = value in ("(none)", "(none connected)")
                connected = isinstance(value, str) and re.fullmatch(r"input_\d{2}", value) and node["inputs"].get(value) is not None
                if not sentinel and not connected:
                    raise AcceptanceError("DazzleSwitch.select is not a sentinel or connected input_NN")
                enum_checks += 1
                continue
            # LoadImage accepts safe subdirectory paths even though its
            # combo inventory may only enumerate root-level files. Actual safe
            # existence above is the relevant contract for a QA subdirectory.
            if kind == "LoadImage" and field == "image":
                continue
            if definition and isinstance(definition, list) and isinstance(definition[0], list) and not is_link(value):
                choices = definition[0]
                normalize = lambda item: item.replace("\\", "/") if isinstance(item, str) else item
                if normalize(value) not in [normalize(item) for item in choices]:
                    raise AcceptanceError("Native export enum is not currently available: " + kind + "." + field)
                enum_checks += 1
        for value in node["inputs"].values():
            for source in links_in(value):
                if source not in graph:
                    raise AcceptanceError("Unresolved dependency in projected closure")
    for target in targets:
        kind = graph[target]["class_type"]
        if kind not in SAFE_OUTPUT_TYPES or not info[kind].get("output_node"):
            raise AcceptanceError("Target must be a registered SaveImage output")
    return {"nodes": len(graph), "targets": targets, "enum_checks": enum_checks, "local_only": True,
            "qa_prefix": prefix, "native_nodes_inputs_and_parameters_preserved": True}


def read_identity(runtime: Path, expected_pid: int, expected_create_time: float | None = None) -> dict[str, Any]:
    import psutil
    process = psutil.Process(expected_pid)
    created = process.create_time()
    executable = Path(process.exe()).resolve()
    cwd = Path(process.cwd()).resolve()
    expected_executable = (runtime / "python/python.exe").resolve()
    expected_cwd = (runtime / "ComfyUI").resolve()
    if executable != expected_executable or cwd != expected_cwd:
        raise AcceptanceError("Expected PID does not own the reviewed runtime executable/cwd")
    if expected_create_time is not None and created != expected_create_time:
        raise AcceptanceError("Expected service creation time changed")
    listeners = {entry.pid for entry in psutil.net_connections(kind="tcp")
                 if entry.status == psutil.CONN_LISTEN and entry.laddr.port == 8188}
    if listeners != {expected_pid}:
        raise AcceptanceError("8188 listener identity is not the expected process")
    return {"pid": expected_pid, "create_time": created, "executable": str(executable), "cwd": str(cwd),
            "listener_pids": sorted(listeners)}


def assert_same_identity(before: dict[str, Any], after: dict[str, Any]):
    if before != after:
        raise AcceptanceError("Service identity drifted during acceptance")


def queue_ids(queue: dict[str, Any]) -> set[str]:
    if not isinstance(queue, dict) or not {"queue_running", "queue_pending"} <= set(queue):
        raise AcceptanceError("Malformed queue response")
    result = set()
    for key in ("queue_running", "queue_pending"):
        if not isinstance(queue.get(key), list):
            raise AcceptanceError("Malformed queue collection")
        for row in queue[key]:
            if not isinstance(row, list) or len(row) < 2 or not isinstance(row[1], str):
                raise AcceptanceError("Malformed queue entry")
            result.add(row[1])
    return result


def assert_queue(queue: dict[str, Any], own_prompt_id: str | None = None):
    ids = queue_ids(queue)
    if ids - ({own_prompt_id} if own_prompt_id else set()):
        raise AcceptanceError("User/foreign queue work detected; no further acceptance submission is allowed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AcceptanceError("Loopback response redirect refused")


class LocalClient:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path: str, payload: dict | None = None):
        allowed = path in ("/queue", "/object_info") or bool(re.fullmatch(r"/history/[0-9a-f-]{36}", path)) or path == "/prompt" and payload is not None
        if not allowed or payload is not None and path != "/prompt":
            raise AcceptanceError("Endpoint is outside the local acceptance allowlist")
        request = urllib.request.Request(ORIGIN + path, data=json.dumps(payload, ensure_ascii=False).encode("utf8") if payload is not None else None,
                                         headers={"Content-Type": "application/json"}, method="POST" if payload is not None else "GET")
        with self.opener.open(request, timeout=30) as response:
            return json.load(response)


def write_new(path: Path, value: Any):
    with path.open("x", encoding="utf8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def image_metrics(history: dict[str, Any], runtime: Path, prefix: str, targets: list[str] | None = None) -> list[dict[str, Any]]:
    from PIL import Image, ImageStat
    results = []
    for node_id, output in history.get("outputs", {}).items():
        if targets is not None and node_id not in targets:
            continue
        for entry in output.get("images", []):
            kind = entry.get("type")
            if kind != "output":
                raise AcceptanceError("Requested SaveImage history must use QA output storage")
            filename = portable_relative(entry.get("filename"))
            if "/" in filename:
                raise AcceptanceError("History filename must be a basename")
            subfolder = entry.get("subfolder", "")
            if not isinstance(subfolder, str):
                raise AcceptanceError("History subfolder must be a relative path string")
            # Native SaveImage uses the host's path separator in history.
            # Normalize only this response field, then keep every path guard;
            # export paths and history filename basenames remain strict.
            subfolder = subfolder.replace("\\", "/")
            if subfolder:
                portable_relative(subfolder)
            relative = ((subfolder + "/") if subfolder else "") + filename
            if kind == "output" and not relative.startswith(prefix):
                raise AcceptanceError("History output is outside reviewed QA prefix")
            root = runtime / "ComfyUI" / kind
            path = root / relative
            reject_links(path)
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                raise AcceptanceError("History output path is absent or outside its runtime root")
            with Image.open(path) as image:
                stats = ImageStat.Stat(image.convert("RGB"))
                item = {"node_id": node_id, "type": kind, "relative_path": relative,
                        "sha256": digest(path), "bytes": path.stat().st_size, "size": list(image.size),
                        "mode": image.mode, "rgb_mean": stats.mean, "rgb_stddev": stats.stddev}
                if "A" in image.getbands():
                    alpha = image.getchannel("A")
                    item.update(alpha_range=list(alpha.getextrema()), transparent_pixels=alpha.histogram()[0])
                results.append(item)
    return results


def run_acceptance(*, runtime: Path, evidence: Path, export: Path, expected_pid: int,
                   targets: list[str], case: str, prefix: str = DEFAULT_QA_PREFIX,
                   expected_create_time: float | None = None, execute: bool = False,
                   timeout: float = 1800, poll_interval: float = 2,
                   client=None, identity_reader=read_identity, sleeper=time.sleep, monotonic=time.monotonic) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", case):
        raise AcceptanceError("Case must be a short lowercase identifier")
    if expected_pid <= 0 or not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(poll_interval) or not 0 < poll_interval <= 30:
        raise AcceptanceError("Invalid PID/timeout/poll interval")
    if expected_create_time is not None and (not math.isfinite(expected_create_time) or expected_create_time <= 0):
        raise AcceptanceError("Invalid expected service creation time")
    if execute and expected_create_time is None:
        raise AcceptanceError("Execution requires the exact expected service creation time")
    runtime, evidence, export = Path(runtime).absolute(), Path(evidence).absolute(), Path(export).absolute()
    for path in (runtime, evidence, export):
        reject_links(path)
    if not runtime.is_dir() or evidence.resolve().is_relative_to(runtime.resolve()) or evidence.resolve().is_relative_to(REPOSITORY.resolve()):
        raise AcceptanceError("Evidence must be a fresh external directory outside runtime and repository")
    if evidence.exists():
        raise AcceptanceError("Evidence already exists; prior runs cannot be overwritten or resumed implicitly")
    raw, full_graph = load_export(export)
    if len(targets) != len(set(targets)) or not targets:
        raise AcceptanceError("Choose distinct output targets")
    graph = dependency_closure(full_graph, targets)
    client = client or LocalClient()
    before = identity_reader(runtime, expected_pid, expected_create_time)
    queue_before = client.request("/queue")
    assert_queue(queue_before)
    info = client.request("/object_info")
    preflight = validate_graph(graph, targets, info, runtime, prefix)
    expected_backend_graph, backend_coercions = backend_validation_reference(graph, info, targets)
    backend_validation_nodes = backend_validation_walk(graph, targets, info)
    assert_same_identity(before, identity_reader(runtime, expected_pid, before["create_time"]))
    assert_queue(client.request("/queue"))
    evidence.mkdir(parents=True, exist_ok=False)
    with (evidence / "native-export.json").open("xb") as stream:
        stream.write(raw)
    write_new(evidence / "closure.json", graph)
    write_new(evidence / "backend-validation-reference.json", {"graph": expected_backend_graph,
              "coercions": backend_coercions, "validation_node_ids": backend_validation_nodes,
              "contract": "current target recursion through enumerated required/optional links, then declared literal casts and __value__ unwrap"})
    write_new(evidence / "preflight.json", {"pass": True, "case": case, "execute_authorized": execute,
              "export_sha256": hashlib.sha256(raw).hexdigest(), "closure_sha256": digest(evidence / "closure.json"),
              "backend_reference_sha256": digest(evidence / "backend-validation-reference.json"),
              "backend_literal_coercions": backend_coercions,
              "backend_validation_node_ids": backend_validation_nodes,
              "service_identity": before, "queue_before": queue_before, **preflight})
    result = {"schema": 1, "case": case, "checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "preflight_passed", "pass": True, "submitted": False,
              "native_export_sha256": hashlib.sha256(raw).hexdigest(), "targets": targets,
              "closure_nodes": len(graph), "service_identity_before": before, "queue_before": queue_before,
              "queue_cleared": False, "service_restarted": False, "models_freed": False,
              "native_export_modified": False, "formal_workflow_modified": False,
              "quality_certification": False}
    if not execute:
        result["service_identity_after"] = identity_reader(runtime, expected_pid, before["create_time"])
        assert_same_identity(before, result["service_identity_after"])
        result["queue_after"] = client.request("/queue")
        assert_queue(result["queue_after"])
        write_new(evidence / "result.json", result)
        return result
    prompt_id = str(uuid.uuid4())
    request = {"prompt": graph, "prompt_id": prompt_id, "client_id": "native-acceptance-" + case,
               "partial_execution_targets": targets,
               "extra_data": {"native_acceptance_case": case, "native_export_sha256": hashlib.sha256(raw).hexdigest()}}
    write_new(evidence / "submission-request.json", request)
    try:
        # Recheck after writing receipts and immediately before the sole POST.
        assert_same_identity(before, identity_reader(runtime, expected_pid, before["create_time"]))
        assert_queue(client.request("/queue"))
        result.update(status="submission_attempted", prompt_id=prompt_id, submission_attempted=True)
        submission = client.request("/prompt", request)
        write_new(evidence / "submission-response.json", submission)
        if submission.get("prompt_id") != prompt_id or submission.get("error"):
            result["submission_outcome"] = "rejected_or_unexpected_response"
            raise AcceptanceError("Backend rejected or returned an unexpected prompt identity")
        result.update(submitted=True, status="running", submission_outcome="accepted")
        deadline = monotonic() + timeout
        while True:
            assert_same_identity(before, identity_reader(runtime, expected_pid, before["create_time"]))
            queue = client.request("/queue")
            assert_queue(queue, prompt_id)
            history_response = client.request("/history/" + prompt_id)
            history = history_response.get(prompt_id)
            if history is not None:
                write_new(evidence / "history.json", history_response)
                status = history.get("status", {})
                errors = [message for message in status.get("messages", []) if isinstance(message, list) and message and message[0] in ("execution_error", "execution_interrupted")]
                write_new(evidence / "execution-errors.json", errors)
                result["backend_status"] = status
                if not status.get("completed") or status.get("status_str") != "success" or errors:
                    raise AcceptanceError("Native GPU execution did not complete successfully; full history retained")
                actual_prompt = history.get("prompt")
                if not isinstance(actual_prompt, list) or len(actual_prompt) < 3 or actual_prompt[1] != prompt_id:
                    raise AcceptanceError("History prompt identity is missing or differs from the submitted UUID")
                if typed_json(actual_prompt[2]) != typed_json(expected_backend_graph):
                    raise AcceptanceError("Backend history graph differs from the unchanged closure's declared validation reference")
                result["history_prompt_identity_matches"] = True
                result["history_graph_matches_backend_validation_reference"] = True
                result["backend_literal_coercions"] = backend_coercions
                metrics = image_metrics(history, runtime, prefix, targets)
                if not metrics:
                    raise AcceptanceError("Successful history contains no verified image output")
                if any(not history.get("outputs", {}).get(target, {}).get("images") for target in targets):
                    raise AcceptanceError("A requested output target did not return an image")
                write_new(evidence / "image-metrics.json", metrics)
                result.update(status="execution_passed", image_count=len(metrics), image_metrics=metrics,
                              history_sha256=digest(evidence / "history.json"))
                break
            if monotonic() >= deadline:
                raise AcceptanceError("Execution wait expired; the backend was left untouched")
            sleeper(poll_interval)
        while True:
            result["service_identity_after"] = identity_reader(runtime, expected_pid, before["create_time"])
            assert_same_identity(before, result["service_identity_after"])
            result["queue_after"] = client.request("/queue")
            assert_queue(result["queue_after"], prompt_id)
            if not queue_ids(result["queue_after"]):
                break
            if monotonic() >= deadline:
                raise AcceptanceError("Completed job has not left the queue; service left untouched")
            sleeper(poll_interval)
        result["pass"] = True
    except Exception as error:
        result.update(status="failed_or_interrupted", **{"pass": False}, error_type=type(error).__name__, error=str(error))
        if result.get("submission_attempted") and not result["submitted"]:
            result.setdefault("submission_outcome", "unknown_do_not_resubmit")
        if isinstance(error, urllib.error.HTTPError):
            body = error.read().decode("utf8", errors="replace")
            write_new(evidence / "http-error.json", {"status": error.code, "body": body})
            if error.code in (400, 401, 403):
                result["submission_outcome"] = "http_rejected"
        # Only observational diagnostics. Never retry a POST or manipulate jobs.
        try:
            result["service_identity_after"] = identity_reader(runtime, expected_pid, before["create_time"])
            assert_same_identity(before, result["service_identity_after"])
            result["queue_after"] = client.request("/queue")
            history_response = client.request("/history/" + prompt_id)
            if prompt_id in history_response and not result["submitted"]:
                result.update(submitted=True, submission_outcome="accepted_confirmed_from_history")
            if prompt_id in history_response and not (evidence / "history.json").exists():
                write_new(evidence / "history.json", history_response)
        except Exception as diagnostic_error:
            result["diagnostic_error_type"] = type(diagnostic_error).__name__
    write_new(evidence / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True, help="Fresh external per-case directory")
    parser.add_argument("--expected-pid", type=int, required=True)
    parser.add_argument("--expected-create-time", type=float, help="Exact psutil creation time from the current service identity")
    parser.add_argument("--export", type=Path, required=True, dest="export_file", help="Direct native Export (API) JSON dictionary")
    parser.add_argument("--target", action="append", required=True, help="Output node ID; repeat or comma-separate for a joint target closure")
    parser.add_argument("--case", required=True)
    parser.add_argument("--qa-prefix", default=DEFAULT_QA_PREFIX)
    parser.add_argument("--execute", action="store_true", help="Explicitly authorize one local submission; otherwise preflight only")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=2)
    args = parser.parse_args()
    try:
        result = run_acceptance(runtime=args.runtime, evidence=args.evidence, export=args.export_file,
                                expected_pid=args.expected_pid, expected_create_time=args.expected_create_time,
                                targets=targets_from_arguments(args.target), case=args.case, prefix=args.qa_prefix,
                                execute=args.execute, timeout=args.timeout, poll_interval=args.poll_interval)
    except Exception as error:
        print(json.dumps({"pass": False, "status": "preflight_refused", "error_type": type(error).__name__, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"pass": result["pass"], "status": result["status"], "submitted": result["submitted"],
                      "case": result["case"], "targets": result["targets"], "closure_nodes": result["closure_nodes"],
                      "image_count": result.get("image_count", 0), "evidence": str(args.evidence)}, ensure_ascii=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
