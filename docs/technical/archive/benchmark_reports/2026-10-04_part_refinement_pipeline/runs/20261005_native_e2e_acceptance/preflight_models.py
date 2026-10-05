"""Hash the exact local assets referenced by the native export matrix."""
from pathlib import Path

from acceptance import ROOT, RUN, api, runner

BINDINGS = {
    "UNETLoader": ("unet_name", "diffusion_models"),
    "CLIPLoader": ("clip_name", "text_encoders"),
    "VAELoader": ("vae_name", "vae"),
    "UpscaleModelLoader": ("model_name", "upscale_models"),
    "SAMLoader": ("model_name", "sams"),
    "UltralyticsDetectorProvider": ("model_name", "ultralytics"),
    "LoraLoaderModelOnly": ("lora_name", "loras"),
    "AnimaLLLiteApply_sdscripts": ("lllite_name", "controlnet"),
}
info = api("object_info")
assets = {}
for export_path in sorted((RUN / "exports").glob("*.json")):
    export = runner.read(export_path)
    for nid, node in export["prompt"].items():
        kind = node["class_type"]
        assert kind in info, (export_path.name, nid, kind)
        if kind in BINDINGS:
            key, folder = BINDINGS[kind]
            name = node["inputs"][key]
            assert isinstance(name, str)
            path = ROOT / "ComfyUI/models" / folder / name
            assert path.is_file(), path
            assets.setdefault(path, []).append(export["case"])
for name in ("BiRefNet_lite.safetensors", "birefnet_lite.py", "BiRefNet_config.py", "config.json"):
    path = ROOT / "ComfyUI/models/RMBG/BiRefNet" / name
    assert path.is_file(), path
    assets.setdefault(path, []).append("ext06")
manifest = []
for path, cases in sorted(assets.items()):
    print("Hashing " + str(path.relative_to(ROOT)), flush=True)
    stat = path.stat()
    manifest.append({"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                     "sha256": runner.digest(path), "cases": sorted(set(cases))})
    runner.save(RUN / "model_manifest.json", manifest)
reference = ROOT / "ComfyUI/output/_codex_qa/live_acceptance_20261004/k2_full_2026100402/00_base_00001_.png"
runner.save(RUN / "preflight.json", {"passed": True, "model_assets": len(manifest),
    "exports": 12, "reference_image": str(reference), "reference_sha256": runner.digest(reference),
    "reference_visually_reviewed": "Neutral clothed adult male, blue T-shirt and gray shorts, indoor gym",
    "all_models_local_no_download_required": True})
print("Preflight passed: all native classes registered and exact model assets locally available.", flush=True)
