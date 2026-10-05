"""Frozen-input Krea2 USDU tests; production files stay hash guarded."""
import argparse
import copy
import datetime
import importlib.util
import json
from pathlib import Path
import shutil

from PIL import Image, ImageStat

RUN = Path(__file__).resolve().parent
PREVIOUS = RUN.parent / "20261004_live_acceptance"
ROOT = Path(r"G:\ComfyUI-aki-v3")
SCOPE = RUN.parent.parent
OUTPUT = ROOT / "ComfyUI/output/_codex_qa/k2_usdu_repair_20261004"
SOURCE = "_codex_qa/live_acceptance_20261004/k2_full_2026100402/00_base_00001_.png [output]"
spec = importlib.util.spec_from_file_location("prior_acceptance", PREVIOUS / "acceptance.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.RUN = RUN
runner.LOCK = SCOPE / "run.lock"

CASES = {
    "vae_tiles_only": {"denoise": 0.0, "seam_fix_mode": "None"},
    "steps8_no_seam": {"steps": 8, "seam_fix_mode": "None"},
    "denoise20_no_seam": {"denoise": 0.20, "seam_fix_mode": "None"},
    "normal_no_seam": {"scheduler": "normal", "seam_fix_mode": "None"},
    "denoise03_no_seam": {"denoise": 0.03, "seam_fix_mode": "None"},
    "conservative_full": {"denoise": 0.03, "seam_fix_denoise": 0.03},
    "conservative_band": {"denoise": 0.03, "seam_fix_denoise": 0.03, "seam_fix_mode": "Band Pass"},
    "new_base": {},
    "default_size_full": {},
}


def build(case, seed, source_image=None):
    if case == "default_size_full":
        graph = copy.deepcopy(runner.read(PREVIOUS / "prompts/k2_full_2026100402.json"))
        workflow = runner.read(runner.WF)
        dimensions = next(n for n in workflow["nodes"] if n["id"] == 1205)["widgets_values"]
        graph["6"]["inputs"].update(dict(zip(("width", "height", "batch_size"), dimensions)))
        graph["7"]["inputs"]["seed"] = seed
        graph["201"]["inputs"].update(CASES["conservative_band"])
        graph["201"]["inputs"]["seed"] = seed + 100
        graph["210"] = copy.deepcopy(graph["201"])
        graph["210"]["inputs"].update({"mode_type": "None", "seam_fix_mode": "None"})
        job = f"{case}_{seed}"
        prefix = f"_codex_qa/k2_usdu_repair_20261004/{job}"
        graph["905"] = runner.api_node("SaveImage", {"images": ["210", 0], "filename_prefix": f"{prefix}/10_upscale_reference"})
        graph["900"]["inputs"]["filename_prefix"] = f"{prefix}/00_input"
        graph["950"]["inputs"]["filename_prefix"] = f"{prefix}/90_output"
        runner.save(RUN / "prompts" / f"{job}.json", graph)
        runner.save(RUN / "provenance" / f"{job}.json", {"source_graph": str(PREVIOUS / "prompts/k2_full_2026100402.json"),
                    "source_dimensions_node": 1205, "dimensions": dimensions, "base_seed": seed,
                    "usdu_seed": seed + 100, "overrides": CASES["conservative_band"], "neutral_prompt_unchanged": True})
        return graph, job
    if case == "new_base":
        graph = runner.read(PREVIOUS / "prompts/k2_smoke_2026100401.json")
        graph["7"]["inputs"]["seed"] = seed
        job = f"{case}_{seed}"
        graph["900"]["inputs"]["filename_prefix"] = f"_codex_qa/k2_usdu_repair_20261004/{job}/00_base"
        runner.save(RUN / "prompts" / f"{job}.json", graph)
        runner.save(RUN / "provenance" / f"{job}.json", {"source_graph": str(PREVIOUS / "prompts/k2_smoke_2026100401.json"), "new_seed": seed, "neutral_prompt_unchanged": True})
        return graph, job
    source_image = source_image or SOURCE
    graph = copy.deepcopy(runner.read(PREVIOUS / "prompts/k2_usdu_no_seam_2026100402.json"))
    original_usdu = runner.read(PREVIOUS / "prompts/k2_full_2026100402.json")["201"]
    graph["201"] = copy.deepcopy(original_usdu)
    graph["201"]["inputs"]["image"] = ["1", 0]
    graph["201"]["inputs"].update(CASES[case])
    graph["201"]["inputs"]["seed"] = seed
    graph["1"]["inputs"]["image"] = source_image
    if case in {"conservative_full", "conservative_band"}:
        graph["210"] = copy.deepcopy(graph["201"])
        graph["210"]["inputs"].update({"mode_type": "None", "seam_fix_mode": "None"})
        graph["905"] = runner.api_node("SaveImage", {"images": ["210", 0], "filename_prefix": f"_codex_qa/k2_usdu_repair_20261004/{case}_{seed}/10_upscale_reference"})
    job = f"{case}_{seed}"
    for nid, name in (("900", "00_input"), ("950", "90_output")):
        graph[nid]["inputs"]["filename_prefix"] = f"_codex_qa/k2_usdu_repair_20261004/{job}/{name}"
    runner.save(RUN / "prompts" / f"{job}.json", graph)
    runner.save(RUN / "provenance" / f"{job}.json", {
        "source_graph": str(PREVIOUS / "prompts/k2_full_2026100402.json"),
        "source_image": source_image,
        "overrides": CASES[case],
        "usdu_seed": seed,
        "production_modified": False,
    })
    return graph, job


def outputs_and_metrics(history):
    records = []
    for nid, output in history.get("outputs", {}).items():
        for entry in output.get("images", []):
            assert entry["type"] == "output"
            path = ROOT / "ComfyUI/output" / entry.get("subfolder", "") / entry["filename"]
            assert path.resolve().is_relative_to(OUTPUT.resolve())
            with Image.open(path) as image:
                stat = ImageStat.Stat(image.convert("RGB"))
                records.append({"node_id": nid, "path": str(path), "size": list(image.size),
                                "sha256": runner.digest(path), "mean": stat.mean, "stddev": stat.stddev})
    return records


def prepare():
    assert not runner.LOCK.exists(), "Scope already has an owner"
    assert runner.idle(), "User work is queued; do not acquire/unload"
    baseline = runner.read(PREVIOUS / "baseline.json")
    for item in baseline["files"]:
        path = ROOT / item["path"]
        assert runner.digest(path) == item["sha256"], f"Production drift: {path}"
    with runner.LOCK.open("x", encoding="utf-8") as stream:
        json.dump({"owner_thread": runner.OWNER, "run": RUN.name, "status": "isolated_k2_repair",
                   "created_at": datetime.datetime.now().astimezone().isoformat()}, stream)
    runner.save(RUN / "baseline.json", baseline)
    for item in baseline["files"]:
        target = RUN / "before" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item["path"], target)
        assert runner.digest(target) == item["sha256"]
    previous_models = runner.read(PREVIOUS / "model_manifest.json")
    selected = []
    for item in previous_models:
        if any(name in item["path"] for name in ("DasiwaKrea2TurboRaw", "qwen3-vl-4b-heretic", "krea2RealVae", "OmniSR")):
            assert runner.digest(Path(item["path"])) == item["sha256"], "Tested weight changed"
            selected.append(item)
    runner.save(RUN / "model_manifest.json", selected)
    runner.save(RUN / "STATE.json", {"status": "prepared", "finding": "K2-USDU-001", "production_modified": False})
    print("New isolated run prepared; six production files backed up; four weights rehashed.", flush=True)


runner.build = build
runner.outputs_and_metrics = outputs_and_metrics

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "finish"])
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--seed", type=int, default=2026100502)
    parser.add_argument("--source-image")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        runner.run_case(args.case, args.seed, args.source_image)
    else:
        runner.finish()
