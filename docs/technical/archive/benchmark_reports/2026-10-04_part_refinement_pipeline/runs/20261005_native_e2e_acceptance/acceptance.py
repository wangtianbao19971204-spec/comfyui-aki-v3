"""Run browser-exported neutral UAP graphs against the unchanged local backend."""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import psutil
from PIL import Image, ImageStat

ROOT = Path(r"G:\ComfyUI-aki-v3")
RUN = Path(__file__).resolve().parent
SCOPE = RUN.parent.parent
OWNER = "01a1061f-c0b3-7f40-8168-1bc0ca82582c"
RELEASE = RUN.parent / "20261005_workflow_product_repair"
OUTPUT = ROOT / "ComfyUI/output/_codex_qa/native_e2e_20261005"
EXPECTED_SHA = "c00cab75d4c4264376b355d735de87fa96077c0e23889252bc763de1921e6f2a"
SPEC = importlib.util.spec_from_file_location("neutral_runner", RUN.parent / "20261004_live_acceptance/acceptance.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
runner.RUN = RUN
runner.EXPECTED_SHA = EXPECTED_SHA
native_api = runner.api
current_targets = []


def api(path, payload=None):
    if path == "prompt":
        payload = {**payload, "partial_execution_targets": current_targets}
    return native_api(path, payload)


def outputs_and_metrics(history):
    records = []
    for nid, output in history.get("outputs", {}).items():
        for entry in output.get("images", []):
            kind = entry["type"]
            assert kind in {"output", "temp"}
            path = ROOT / "ComfyUI" / kind / entry.get("subfolder", "") / entry["filename"]
            if kind == "output":
                assert path.resolve().is_relative_to(OUTPUT.resolve()), path
            with Image.open(path) as image:
                stat = ImageStat.Stat(image.convert("RGB"))
                record = {"node_id": nid, "path": str(path), "kind": kind,
                          "size": list(image.size), "mode": image.mode,
                          "sha256": runner.digest(path), "mean": stat.mean, "stddev": stat.stddev}
                if "mask_" in path.name:
                    mask = image.convert("L")
                    histogram = mask.histogram()
                    record.update(nonzero_pixels=sum(histogram[1:]), bbox=mask.getbbox())
                if "A" in image.getbands():
                    alpha = image.getchannel("A")
                    record.update(alpha_range=list(alpha.getextrema()), alpha_bbox=alpha.getbbox(),
                                  transparent_pixels=alpha.histogram()[0])
                records.append(record)
    return records


def build(case, seed, source_image=None):
    global current_targets
    assert not source_image, "Inputs are bound in browser exports"
    export = runner.read(RUN / "exports" / (case + ".json"))
    assert export["source_sha"] == EXPECTED_SHA
    graph = export["prompt"]
    current_targets = export["targets"]
    assert current_targets and all(str(i) in graph for i in current_targets)
    info = api("object_info")
    reachable = set()

    def visit(nid):
        nid = str(nid)
        if nid in reachable:
            return
        reachable.add(nid)
        for value in graph[nid]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int) and str(value[0]) in graph:
                visit(value[0])

    for nid in current_targets:
        visit(nid)
    for nid in reachable:
        node = graph[nid]
        assert node["class_type"] in info, (nid, node["class_type"])
        assert not any(term in node["class_type"].lower() for term in ("caption", "api_", "_api", "pixai")), node["class_type"]
        assert node["class_type"] not in {"SegmDetectorSEGS", "DetailerForEachPipe"}, "Excluded region branch must stay disabled"
        if node["class_type"] == "SaveImage":
            assert node["inputs"]["filename_prefix"].startswith("_codex_qa/native_e2e_20261005/")
    job = f"{case}_{seed}"
    runner.save(RUN / "prompts" / (job + ".json"), graph)
    runner.save(RUN / "provenance" / (job + ".json"), {k: v for k, v in export.items() if k != "prompt"})
    return graph, job


def prepare():
    assert not (RUN / "baseline.json").exists(), "Do not overwrite the baseline"
    assert not runner.LOCK.exists() and runner.idle(), "Another owner or user job exists"
    guard = runner.read(RELEASE / "final_guard.json")
    files = [{"path": item["path"], "sha256": item["actual"]} for item in guard["files"]]
    for item in files:
        assert runner.digest(ROOT / item["path"]) == item["sha256"], item["path"]
    assert runner.digest(runner.WF) == EXPECTED_SHA
    listeners = {c.pid for c in psutil.net_connections(kind="tcp")
                 if c.status == psutil.CONN_LISTEN and c.laddr.port == 8188}
    assert listeners == {53232} and psutil.pid_exists(51312)
    now = datetime.datetime.now().astimezone().isoformat()
    with runner.LOCK.open("x", encoding="utf-8") as stream:
        json.dump({"owner_thread": OWNER, "run": RUN.name, "status": "native_e2e_acceptance", "started_at": now}, stream)
    runner.save(RUN / "baseline.json", {"files": files, "workflow_sha256": EXPECTED_SHA,
        "time": now, "listeners": [53232], "qwen_pid": 51312, "system": api("system_stats"),
        "gpu": subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader"], text=True).strip()})
    for folder in ("exports", "results", "prompts", "provenance", "telemetry", "history", "submissions", "comparisons"):
        (RUN / folder).mkdir(exist_ok=True)
    shutil.copy2(SCOPE / "STATE.json", RUN / "parent_state_before.json")
    runner.save(RUN / "STATE.json", {"status": "prepared", "production_modified": False,
        "scope": "12 cases: three native main smoke, three refinement/upscale runs, six image tools; neutral inputs only"})
    print(json.dumps({"prepared": True, "guards": len(files), "queue": "0/0", "workflow_sha": EXPECTED_SHA}))


runner.api = api
runner.build = build
runner.outputs_and_metrics = outputs_and_metrics

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--case")
    parser.add_argument("--seed", type=int, default=2026100501)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        assert runner.read(RUN / "preflight.json")["passed"]
        listeners = {c.pid for c in psutil.net_connections(kind="tcp")
                     if c.status == psutil.CONN_LISTEN and c.laddr.port == 8188}
        assert listeners == {53232} and psutil.pid_exists(51312)
        runner.run_case(args.case, args.seed, None)
