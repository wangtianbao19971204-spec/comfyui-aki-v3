"""Isolated neutral inference acceptance using current production node parameters."""
import argparse
import copy
import datetime
import hashlib
import json
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageStat
import psutil
import websocket

ROOT = Path(r"G:\ComfyUI-aki-v3")
RUN = Path(__file__).resolve().parent
SCOPE = RUN.parent.parent
LOCK = SCOPE / "run.lock"
OWNER = "01a1061f-c0b3-7f40-8168-1bc0ca82582c"
WF = ROOT / "ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json"
POSITIVE = ("Anime-style full-body illustration of an adult man, 30 years old, short dark hair, "
            "wearing a loose blue athletic T-shirt and gray knee-length sports shorts. "
            "Standing barefoot on a pale indoor gym floor, both feet completely visible, "
            "both open hands visible at his sides, feet apart, relaxed upright pose. "
            "Complete figure from head to toes with space below the feet, front view, "
            "clear face and eyes, clean line art, soft daylight, plain light gray background.")
NEGATIVE = "text, watermark, blurry, cropped, out of frame, duplicate person"
PARTS = ("hand", "foot", "face", "eye")
DIAGNOSTIC_OVERRIDES = {
    "k2_upscale_only": {"mode_type": "None", "seam_fix_mode": "None"},
    "k2_usdu_no_seam": {"seam_fix_mode": "None"},
}
EXPECTED_SHA = "fdbff196324e01296a4bb1ffed6e1a6d38e49cacc7bf0aa59ddeb9983b6e8a1e"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def api(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:8188/" + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc


def idle():
    q = api("queue")
    return not q["queue_running"] and not q["queue_pending"]


def scalar_inputs(node, info):
    schema = info[node["type"]]
    fields = []
    for section in ("required", "optional"):
        for name in schema.get("input_order", {}).get(section, []):
            spec = schema["input"][section][name]
            options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if not options.get("forceInput") and (isinstance(spec[0], list) or spec[0] in {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}):
                fields.append(name)
                if name == "seed":
                    fields.append("control_after_generate")
    values = node.get("widgets_values", [])
    assert len(fields) == len(values), (node["id"], node["type"], fields, len(values))
    return {k: copy.deepcopy(v) for k, v in zip(fields, values) if k != "control_after_generate"}


def api_node(class_type, inputs):
    return {"class_type": class_type, "inputs": inputs}


def build(case, seed, source_image=None):
    if case in DIAGNOSTIC_OVERRIDES or case == "k2_vae_roundtrip":
        assert source_image, "Ablations must reuse the saved Krea2 base image"
    assert digest(WF) == EXPECTED_SHA, "Production workflow changed; rebind before testing"
    wf = read(WF)
    info = api("object_info")
    branch_id = case.split("_")[0]
    branch = next(b for b in wf["extra"]["uap_workbench"]["branches"] if b["id"] == branch_id)
    source_nodes = [n for n in wf["nodes"] if n["id"] in branch["nodeIds"]]
    definitions = {s["id"]: s for s in wf["definitions"]["subgraphs"]}
    graph = {}
    provenance = []

    def from_source(new_id, node, links=None, overrides=None):
        inputs = scalar_inputs(node, info)
        if links:
            inputs.update(links)
        if overrides:
            inputs.update(overrides)
        graph[str(new_id)] = api_node(node["type"], inputs)
        provenance.append({"api_id": str(new_id), "source_id": node["id"], "class_type": node["type"],
                           "overrides": overrides or {}})
        return [str(new_id), 0]

    def single(kind):
        matches = [n for n in source_nodes if n["type"] == kind]
        assert len(matches) == 1, (kind, len(matches))
        return matches[0]

    model = from_source(2, single("UNETLoader"))
    clip = from_source(3, single("CLIPLoader"))
    vae = from_source(4, single("VAELoader"))
    if branch_id != "k2":
        model = from_source(5, single("ModelSamplingAuraFlow"), {"model": model})
    graph["20"] = api_node("CLIPTextEncode", {"clip": clip, "text": POSITIVE})
    graph["21"] = api_node("CLIPTextEncode", {"clip": clip, "text": NEGATIVE})
    job = f"{case}_{seed}"
    prefix = f"_codex_qa/live_acceptance_20261004/{job}"

    def save_image(nid, image_ref, name):
        graph[str(nid)] = api_node("SaveImage", {"images": image_ref, "filename_prefix": f"{prefix}/{name}"})

    if source_image:
        graph["1"] = api_node("LoadImage", {"image": source_image})
        image_ref = ["1", 0]
    else:
        latent = from_source(6, single("EmptyLatentImage"), overrides={"width": 768, "height": 1024, "batch_size": 1})
        sampler = from_source(7, single("KSampler"), {"model": model, "positive": ["20", 0],
                              "negative": ["21", 0], "latent_image": latent}, {"seed": seed})
        graph["8"] = api_node("VAEDecode", {"samples": sampler, "vae": vae})
        image_ref = ["8", 0]
    save_image(900, image_ref, "00_base")
    wanted_parts = ("foot",) if case == "a29_foot" else PARTS if case == "a1_full" else ()
    for part_index, part in enumerate(wanted_parts):
        instance = next(n for n in source_nodes if n.get("properties", {}).get("uap_refinement") == part)
        sg = definitions[instance["type"]]
        bindings = {"image": image_ref, "model": model, "clip": clip, "vae": vae,
                    "positive": ["20", 0], "negative": ["21", 0]}
        links = [l if isinstance(l, dict) else dict(zip(
                 ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type"), l)) for l in sg["links"]]
        by_link = {l["id"]: l for l in links}
        prefix_id = str(instance["id"])

        def resolve(link):
            if link["origin_id"] == -10:
                return bindings[sg["inputs"][link["origin_slot"]]["name"]]
            return [f"{prefix_id}:{link['origin_id']}", link["origin_slot"]]

        detector_id = None
        for node in sg["nodes"]:
            resolved = {inp["name"]: resolve(by_link[inp["link"]]) for inp in node.get("inputs", []) if inp.get("link") is not None}
            nid = f"{prefix_id}:{node['id']}"
            overrides = {"seed": seed + part_index + 1} if node["type"] == "DetailerForEach" else {}
            from_source(nid, node, resolved, overrides)
            if node["type"] == "ImpactSimpleDetectorSEGS":
                detector_id = nid
        image_ref = resolve(next(l for l in links if l["target_id"] == -20 and l["target_slot"] == 0))
        assert detector_id is not None
        mask_id = f"qa:{part}:mask"
        image_id = f"qa:{part}:mask_image"
        graph[mask_id] = api_node("SegsToCombinedMask", {"segs": [detector_id, 0]})
        graph[image_id] = api_node("MaskToImage", {"mask": [mask_id, 0]})
        save_image(f"qa:{part}:mask_save", [image_id, 0], f"mask_{part}")
        save_image(f"qa:{part}:stage_save", image_ref, f"{part_index + 1:02d}_{part}")
    if case.endswith("_full") or case in DIAGNOSTIC_OVERRIDES:
        upscaler = from_source(200, single("UpscaleModelLoader"))
        image_ref = from_source(201, single("UltimateSDUpscale"), {"image": image_ref, "model": model,
                                 "positive": ["20", 0], "negative": ["21", 0], "vae": vae,
                                 "upscale_model": upscaler}, {"seed": seed + 100, **DIAGNOSTIC_OVERRIDES.get(case, {})})
        save_image(950, image_ref, "90_usdu")
    if case == "k2_vae_roundtrip":
        graph["202"] = api_node("VAEEncode", {"pixels": image_ref, "vae": vae})
        graph["203"] = api_node("VAEDecode", {"samples": ["202", 0], "vae": vae})
        save_image(950, ["203", 0], "90_vae_roundtrip")
    for nid, node in graph.items():
        assert node["class_type"] in info
        assert "Lora" not in node["class_type"] and "SegmDetector" not in node["class_type"]
        for name, value in node["inputs"].items():
            if isinstance(value, list):
                assert len(value) == 2 and str(value[0]) in graph, (nid, name, value)
        if node["class_type"] == "CLIPTextEncode":
            assert node["inputs"]["text"] in {POSITIVE, NEGATIVE}
        if node["class_type"] == "DetailerForEach":
            assert node["inputs"].get("wildcard", "") in {"", "hand, detailed fingers", "face, detailed eyes", "eyes, detailed eyes"}, "Unreviewed extra detailer text"
    save(RUN / "prompts" / f"{job}.json", graph)
    save(RUN / "provenance" / f"{job}.json", {
        "workflow_sha256": EXPECTED_SHA, "case": case, "seed": seed, "part_order": wanted_parts,
        "method": "Explicit native API graph with current production scalar parameters and exact selected subgraph links",
        "scope": "Neutral text, fixed seeds, batch=1, 768x1024, no LoRA or optional control, selected parts only; additional QA saves",
        "source_image": source_image, "nodes": provenance,
        "diagnostic_overrides": DIAGNOSTIC_OVERRIDES.get(case, {}),
        "vae_only_roundtrip": case == "k2_vae_roundtrip",
    })
    return graph, job


def guards():
    baseline = read(RUN / "baseline.json")
    checks = [{"path": x["path"], "unchanged": digest(ROOT / x["path"]) == x["sha256"]} for x in baseline["files"]]
    assert all(x["unchanged"] for x in checks), "A guarded production file changed"
    return checks


def prepare():
    assert not LOCK.exists(), "Existing scope lock: inspect owner before continuing"
    assert idle(), "Backend has user work"
    assert digest(WF) == EXPECTED_SHA
    lock = {"owner_thread": OWNER, "run": RUN.name, "status": "live_acceptance", "created_at": datetime.datetime.now().astimezone().isoformat()}
    with LOCK.open("x", encoding="utf-8") as stream:
        json.dump(lock, stream)
    files = read(RUN.parent / "20261004_followup_review/review_snapshot.json")["release_files"]
    save(RUN / "baseline.json", {"files": files, "system": api("system_stats"), "platform": platform.platform(),
                               "listener_pid": 53232, "created_at": lock["created_at"]})
    guards()
    resources = {
        "diffusion_models/Anima/animayume_v15Base.safetensors", "diffusion_models/Anima-2.9B/anima29B_v10_bf16.safetensors",
        "diffusion_models/krea2/DasiwaKrea2TurboRaw_cutedisasterV2Turbo.safetensors",
        "text_encoders/anima_baseV10_txt.safetensors", "text_encoders/qwen3-vl-4b-heretic.safetensors",
        "vae/qwen_image_vae.safetensors", "vae/krea2RealVae_v10.safetensors",
        "upscale_models/OmniSR_X4_DIV2K.safetensors", "sams/sam_vit_b_01ec64.pth",
        "ultralytics/bbox/face_yolov9c.pt", "ultralytics/bbox/hand_yolov9c.pt",
        "ultralytics/bbox/Eyeful_v2-Individual.pt", "ultralytics/bbox/adetailerFootYolov8x_v20.pt",
    }
    manifest = []
    for relative in sorted(resources):
        path = ROOT / "ComfyUI/models" / relative
        assert path.is_file(), str(path)
        print("Hashing " + relative, flush=True)
        stat = path.stat()
        manifest.append({"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest(path)})
        save(RUN / "model_manifest.json", manifest)
    save(RUN / "STATE.json", {"status": "prepared", "owner_thread": OWNER, "scope": "a1/k2 native smoke and full chain; a29 positive foot redraw"})
    print("Preflight prepared; production guarded; no inference submitted.", flush=True)


def outputs_and_metrics(history):
    outputs = []
    for nid, result in history.get("outputs", {}).items():
        for entry in result.get("images", []):
            assert entry["type"] == "output"
            path = ROOT / "ComfyUI/output" / entry.get("subfolder", "") / entry["filename"]
            assert path.resolve().is_relative_to((ROOT / "ComfyUI/output/_codex_qa/live_acceptance_20261004").resolve())
            with Image.open(path) as image:
                record = {"node_id": nid, "path": str(path), "size": list(image.size), "sha256": digest(path)}
                if path.name.startswith("mask_"):
                    mask = image.convert("L")
                    histogram = mask.histogram()
                    record.update(nonzero_pixels=sum(histogram[1:]), bbox=mask.getbbox())
                else:
                    stat = ImageStat.Stat(image.convert("RGB"))
                    record.update(mean=stat.mean, stddev=stat.stddev)
            outputs.append(record)
    return outputs


def run_case(case, seed, source_image):
    assert read(LOCK)["run"] == RUN.name and read(LOCK)["owner_thread"] == OWNER
    guards()
    graph, job = build(case, seed, source_image)
    result_path = RUN / "results" / f"{job}.json"
    if result_path.exists():
        raise RuntimeError("Receipt already exists; do not overwrite a tested attempt")
    assert idle(), "Backend has user work; did not submit or unload"
    api("free", {"unload_models": True, "free_memory": True})
    time.sleep(4)
    assert idle()
    stop = threading.Event()
    samples = []
    events = []

    def observe_progress():
        ws = websocket.create_connection("ws://127.0.0.1:8188/ws?clientId=uap-neutral-live-acceptance", timeout=2)
        try:
            while not stop.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(raw, str):
                    continue
                message = json.loads(raw)
                if message["type"] not in {"executing", "progress", "execution_error", "execution_success"}:
                    continue
                events.append({"timestamp": time.time(), **message})
                data = message["data"]
                if message["type"] == "executing":
                    node = data.get("node")
                    print(json.dumps({"job": job, "executing_node": node, "class_type": graph.get(str(node), {}).get("class_type")}), flush=True)
                elif message["type"] == "progress" and data.get("value") in {1, data.get("max")}:
                    print(json.dumps({"job": job, "node": data.get("node"), "step": data.get("value"), "steps": data.get("max")}), flush=True)
        finally:
            ws.close()

    def sample_system():
        process = psutil.Process(53232)
        while not stop.is_set():
            memory = psutil.virtual_memory()
            samples.append({"timestamp": time.time(), "process_rss": process.memory_info().rss, "system_available": memory.available})
            stop.wait(0.5)

    thread = threading.Thread(target=sample_system, daemon=True)
    progress_thread = threading.Thread(target=observe_progress, daemon=True)
    telemetry_path = RUN / "telemetry" / f"{job}_gpu.csv"
    telemetry_path.parent.mkdir(exist_ok=True)
    telemetry_file = telemetry_path.open("w", encoding="utf-8")
    gpu = subprocess.Popen(["nvidia-smi", "--query-gpu=timestamp,memory.used,utilization.gpu,power.draw,temperature.gpu", "--format=csv,noheader,nounits", "--loop-ms=500"],
                           stdout=telemetry_file, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    thread.start()
    progress_thread.start()
    started = time.monotonic()
    receipt = {"job": job, "case": case, "seed": seed, "source_image": source_image, "status": "submitting"}
    save(RUN / "STATE.json", {"status": "running", **receipt})
    try:
        submission = api("prompt", {"prompt": graph, "client_id": "uap-neutral-live-acceptance"})
        save(RUN / "submissions" / f"{job}.json", submission)
        assert not submission.get("node_errors"), submission
        pid = submission["prompt_id"]
        receipt["prompt_id"] = pid
        receipt["status"] = "running"
        save(RUN / "STATE.json", {"status": "running", **receipt})
        print(json.dumps({"submitted": job, "prompt_id": pid, "nodes": len(graph)}), flush=True)
        history = None
        for attempt in range(360):
            history = api("history/" + pid).get(pid)
            if history:
                break
            if attempt % 4 == 0:
                print(json.dumps({"running": job, "elapsed_seconds": round(time.monotonic() - started)}), flush=True)
            time.sleep(5)
        if history is None:
            receipt["status"] = "timeout_task_left_untouched"
            raise TimeoutError("Inspect live task before any retry")
        save(RUN / "history" / f"{job}.json", history)
        receipt["status"] = history["status"]["status_str"]
        receipt["completed"] = history["status"].get("completed")
        receipt["outputs"] = outputs_and_metrics(history)
        receipt["execution_errors"] = [v for k, v in history["status"].get("messages", []) if k in {"execution_error", "execution_interrupted"}]
    except Exception as exc:
        receipt.setdefault("error", str(exc))
        if receipt["status"] == "submitting":
            receipt["status"] = "submission_error"
        raise
    finally:
        receipt["wall_seconds"] = round(time.monotonic() - started, 3)
        stop.set()
        thread.join(timeout=3)
        progress_thread.join(timeout=3)
        gpu.terminate()
        gpu.wait(timeout=5)
        telemetry_file.close()
        save(RUN / "telemetry" / f"{job}_system.json", samples)
        save(RUN / "telemetry" / f"{job}_progress.json", events)
        if idle():
            api("free", {"unload_models": True, "free_memory": True})
            time.sleep(4)
            receipt["freed_after"] = True
        else:
            receipt["freed_after"] = False
        receipt["guards"] = guards()
        save(result_path, receipt)
        save(RUN / "STATE.json", {"status": "awaiting_visual_review", "latest_job": job, "latest_status": receipt["status"]})
        print(json.dumps(receipt, ensure_ascii=True), flush=True)
    if receipt["status"] != "success":
        raise RuntimeError("Inference did not succeed; inspect saved history")


def finish():
    assert idle(), "Do not finish while backend has queued work"
    api("free", {"unload_models": True, "free_memory": True})
    time.sleep(4)
    gpu = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader"], text=True)
    results = [read(p) for p in sorted((RUN / "results").glob("*.json"))]
    save(RUN / "final_runtime_check.json", {"guards": guards(), "queue": api("queue"), "gpu": gpu.strip(),
                                             "results": [{k: r.get(k) for k in ("job", "prompt_id", "status", "wall_seconds")} for r in results],
                                             "system": api("system_stats")})
    assert read(LOCK)["run"] == RUN.name and read(LOCK)["owner_thread"] == OWNER
    LOCK.unlink()
    save(RUN / "STATE.json", {"status": "inference_complete_pending_final_report", "jobs": len(results), "production_changed": False})
    print("Final unload and guards complete; own run lock removed.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "finish"])
    parser.add_argument("--case", choices=["a1_smoke", "a1_full", "k2_smoke", "k2_full", "a29_foot", "k2_vae_roundtrip", *DIAGNOSTIC_OVERRIDES])
    parser.add_argument("--seed", type=int, default=2026100401)
    parser.add_argument("--source-image")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        run_case(args.case, args.seed, args.source_image)
    else:
        finish()
