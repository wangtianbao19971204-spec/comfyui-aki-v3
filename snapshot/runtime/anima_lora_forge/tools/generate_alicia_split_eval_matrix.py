from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT = Path(r"G:\ComfyUI-aki-v3\anima_lora_forge")
COMFY_ROOT = Path(r"G:\ComfyUI-aki-v3\ComfyUI")
FORGE_ROOT = Path(r"G:\ComfyUI-aki-v3\character_lora_forge")
TEMPLATE = FORGE_ROOT / "templates" / "anima_current_api.json"
BASE_URL = "http://127.0.0.1:8188"

sys.path.insert(0, str(FORGE_ROOT))
from character_forge.comfy import ComfyClient, output_images  # noqa: E402


NEGATIVE = (
    "nsfw, nude, naked, underwear, lingerie, bikini, child, teen, multiple people, "
    "duplicate character, bad anatomy, extra limbs, missing fingers, cropped feet, "
    "text, watermark, signature, worst quality, low quality"
)

FORMS = {
    "ordinary": {
        "trigger": "alcbo7yo260822",
        "lora_dir": "alicia_bell_ordinary_eval",
        "run_root": PROJECT / "runs" / "alicia_bell_ordinary" / "split_evaluation",
        "prompts": {
            "anchor": (
                "masterpiece, best quality, safe, solo, one 23-year-old adult woman, "
                "warm approachable soft oval face, fair warm skin, natural honey-hazel "
                "amber eyes with normal round pupils, loose light-brown champagne "
                "shoulder-length hair with a small side-braid and wine ribbon, fully "
                "clothed, opaque ivory blouse, short teal cardigan, wine-red knee-length "
                "A-line skirt, bare lower legs, brown low ankle boots, full body, neutral "
                "standing pose, plain warm gray studio background, clean anime character art"
            ),
            "identity_portrait": (
                "safe, solo, adult Alicia Bell, close portrait, warm soft oval face, "
                "honey-hazel eyes, loose champagne-brown hair with a small side braid and "
                "wine ribbon, gentle neutral expression, ivory blouse, clean anime portrait"
            ),
            "modern_casual": (
                "safe, solo, adult Alicia Bell, loose champagne-brown hair, fully clothed "
                "in a navy denim jacket, white crew-neck shirt, straight black trousers, "
                "gray socks and white sneakers, walking, full body, modern city sidewalk"
            ),
            "formal": (
                "safe, solo, adult Alicia Bell, loose champagne-brown hair, opaque "
                "midnight-blue tailored blazer, ivory buttoned blouse, matching trousers, "
                "black loafers, poised full-body standing pose, reception interior"
            ),
            "style_watercolor": (
                "safe, solo, adult Alicia Bell, ivory blouse, teal cardigan, wine skirt, "
                "bare lower legs and brown ankle boots, seated reading, full body, delicate "
                "watercolor and ink storybook illustration, pale paper texture"
            ),
            "style_3d": (
                "safe, solo, adult Alicia Bell, ivory blouse, teal cardigan, wine skirt, "
                "bare lower legs and brown ankle boots, full body, polished stylized 3D "
                "anime game render, soft cel-shaded materials"
            ),
            "cross_form_leakage": (
                "safe, solo, adult Alicia Bell, ordinary everyday form, loose champagne-brown "
                "hair, no twin tails, no star hair accessory, no idol outfit, opaque ivory "
                "blouse, teal cardigan, wine skirt, bare lower legs, brown ankle boots, full body"
            ),
        },
    },
    "morning_star": {
        "trigger": "alcbm7yo260822",
        "lora_dir": "alicia_bell_morning_star_eval",
        "run_root": PROJECT / "runs" / "alicia_bell_morning_star" / "split_evaluation",
        "prompts": {
            "anchor": (
                "masterpiece, best quality, safe, solo, one 23-year-old adult woman, Morning "
                "Star form, warm soft oval face, fair warm luminous skin, champagne-gold eyes, "
                "peach rose-gold low twin tails with wine-red ribbons, exactly one small gold "
                "five-point hair star, opaque ivory upper idol dress, plain wine-red collar "
                "knot, short translucent ivory gauze shoulder shawl over opaque clothing, plain "
                "wine-red high-waist bodice, compact opaque ivory bell skirt with solid wine-red "
                "hem, very sheer ivory pantyhose covering both legs and feet, warm skin tone "
                "visible through the fabric, wine-red high heels, full body, neutral standing "
                "pose, plain warm gray studio background, clean anime character art"
            ),
            "identity_portrait": (
                "safe, solo, adult Alicia Bell in Morning Star form, close portrait, peach "
                "rose-gold low twin tails with wine ribbons, champagne-gold eyes, exactly one "
                "small gold five-point hair star, gentle expression, clean anime portrait"
            ),
            "hosiery_absent": (
                "safe, solo, adult Alicia Bell in Morning Star form, canonical ivory and wine "
                "idol dress, bare natural legs and bare feet, no stockings, no pantyhose, full "
                "body, plain studio background, clean anime character art"
            ),
            "hosiery_replaced": (
                "safe, solo, adult Alicia Bell in Morning Star form, canonical ivory and wine "
                "idol dress, opaque plain charcoal tights covering both legs and feet, wine "
                "heels, full body, plain studio background, clean anime character art"
            ),
            "accessory_absent": (
                "safe, solo, adult Alicia Bell in Morning Star form, peach-gold low twin tails "
                "with wine ribbons, no star hair accessory, no hair clip, fully clothed, waist-up "
                "portrait, plain light background, clean anime character art"
            ),
            "accessory_replaced": (
                "safe, solo, adult Alicia Bell in Morning Star form, peach-gold low twin tails "
                "with wine ribbons, one plain oval pearl hair clip instead of a star, fully "
                "clothed, waist-up portrait, plain light background, clean anime character art"
            ),
            "style_watercolor": (
                "safe, solo, adult Alicia Bell in Morning Star form, canonical ivory and wine "
                "idol dress, very sheer ivory pantyhose covering both legs and feet, warm skin "
                "tone visible through the fabric, full body, watercolor and ink storybook art"
            ),
            "style_3d": (
                "safe, solo, adult Alicia Bell in Morning Star form, canonical ivory and wine "
                "idol dress, very sheer ivory pantyhose covering both legs and feet, warm skin "
                "tone visible through the fabric, full body, polished stylized 3D anime render"
            ),
            "cross_form_leakage": (
                "safe, solo, adult Alicia Bell in Morning Star form, peach rose-gold low twin "
                "tails, one gold hair star, no teal cardigan, no ordinary loose hairstyle, "
                "canonical idol outfit and sheer ivory pantyhose, full body"
            ),
        },
    },
}

SEEDS = {
    "anchor": 260831,
    "identity_portrait": 260832,
    "modern_casual": 260833,
    "formal": 260834,
    "style_watercolor": 260835,
    "style_3d": 260836,
    "cross_form_leakage": 260837,
    "hosiery_absent": 260838,
    "hosiery_replaced": 260839,
    "accessory_absent": 260840,
    "accessory_replaced": 260841,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def lora_path(config: dict[str, Any], step: int) -> Path:
    return COMFY_ROOT / "models" / "loras" / "anima" / "character" / config["lora_dir"] / f"step{step:04d}.safetensors"


def lora_name(config: dict[str, Any], step: int) -> str:
    return f"anima\\character\\{config['lora_dir']}\\step{step:04d}.safetensors"


def build_graph(config: dict[str, Any], step: int, strength: float, prompt_id: str, prefix: str) -> dict[str, Any]:
    graph = copy.deepcopy(json.loads(TEMPLATE.read_text(encoding="utf-8"))["graph"])
    graph["2"]["inputs"]["unet_name"] = "Anima\\anima_baseV10.safetensors"
    positive = f"{config['trigger']}, {config['prompts'][prompt_id]}"
    graph["107"]["inputs"]["positive"] = positive
    graph["6"]["inputs"]["text"] = NEGATIVE
    for node_id in ("112", "384", "385", "390"):
        graph.pop(node_id, None)
    graph["900010"] = {
        "inputs": {"model": ["2", 0], "lora_name": lora_name(config, step), "strength_model": strength},
        "class_type": "LoraLoaderModelOnly",
        "_meta": {"title": "Alicia split evaluation LoRA"},
    }
    graph["167"]["inputs"]["model"] = ["900010", 0]
    graph["6"]["inputs"]["clip"] = ["165", 0]
    graph["134"]["inputs"]["clip"] = ["165", 0]
    graph["519"]["inputs"].update({"width": 1024, "height": 1024, "batch_size": 1})
    graph["542"]["inputs"]["seed"] = SEEDS[prompt_id]
    graph["10"]["inputs"].update({"steps": 30, "cfg": 4.5, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0})
    images = graph["13"]["inputs"]["images"]
    graph["13"] = {"inputs": {"images": images, "filename_prefix": prefix}, "class_type": "SaveImage"}
    return graph


def wait_for_prompt(client: ComfyClient, prompt_id: str, timeout_seconds: int = 1200) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            record = client.history(prompt_id=prompt_id).get(prompt_id)
        except (TimeoutError, OSError):
            time.sleep(2)
            continue
        if record and record.get("status", {}).get("completed"):
            if record["status"].get("status_str") != "success":
                raise RuntimeError(f"ComfyUI job failed: {json.dumps(record['status'], ensure_ascii=False)[:3000]}")
            return record
        time.sleep(1.5)
    raise RuntimeError(f"ComfyUI job timed out: {prompt_id}")


def jobs(
    config: dict[str, Any],
    phase: str,
    steps: list[int],
    control_strengths: list[float],
) -> list[tuple[int, float, str]]:
    if phase == "sweep":
        return [(step, 0.8, "anchor") for step in steps]
    result = [
        (step, strength, prompt_id)
        for step in steps
        for strength in control_strengths
        for prompt_id in config["prompts"]
    ]
    result.extend((step, strength, "anchor") for step in steps for strength in (0.6, 1.0))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--form", choices=tuple(FORMS), required=True)
    parser.add_argument("--phase", choices=("sweep", "controls"), required=True)
    parser.add_argument("--steps", default="100,200,300,400")
    parser.add_argument("--control-strengths", default="0.8")
    args = parser.parse_args()
    config = FORMS[args.form]
    steps = [int(value) for value in args.steps.split(",") if value.strip()]
    control_strengths = [
        float(value) for value in args.control_strengths.split(",") if value.strip()
    ]
    for step in steps:
        if not lora_path(config, step).is_file():
            raise SystemExit(f"Missing evaluation LoRA: {lora_path(config, step)}")

    output_dir = config["run_root"] / args.phase
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {
        "schema_version": 1, "form": args.form, "phase": args.phase, "records": []
    }
    existing = {record["job_key"] for record in manifest["records"]}
    client = ComfyClient(BASE_URL, comfy_root=COMFY_ROOT, timeout=120)
    for step, strength, prompt_id in jobs(config, args.phase, steps, control_strengths):
        job_key = f"step{step:04d}_s{str(strength).replace('.', 'p')}_{prompt_id}"
        destination = output_dir / f"{job_key}.png"
        if job_key in existing and destination.is_file():
            continue
        graph = build_graph(config, step, strength, prompt_id, f"alicia_split_eval/{args.form}/{args.phase}/{job_key}")
        comfy_prompt_id = client.queue_prompt(graph)
        record = wait_for_prompt(client, comfy_prompt_id)
        images = output_images(record)
        if len(images) != 1:
            raise RuntimeError(f"Expected one output for {job_key}, found {len(images)}")
        client.copy_output_image(images[0], destination)
        manifest["records"].append({
            "job_key": job_key,
            "form": args.form,
            "checkpoint_step": step,
            "checkpoint_path": str(lora_path(config, step).resolve()),
            "checkpoint_sha256": sha256_file(lora_path(config, step)),
            "lora_strength": strength,
            "prompt_id": prompt_id,
            "positive": f"{config['trigger']}, {config['prompts'][prompt_id]}",
            "negative": NEGATIVE,
            "seed": SEEDS[prompt_id],
            "sampler": "euler", "scheduler": "simple", "steps": 30, "cfg": 4.5,
            "width": 1024, "height": 1024,
            "comfy_prompt_id": comfy_prompt_id,
            "output_path": str(destination.resolve()),
            "output_sha256": sha256_file(destination),
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        atomic_json(manifest_path, manifest)
        print(f"completed {job_key}", flush=True)
    print(json.dumps({"form": args.form, "phase": args.phase, "count": len(manifest["records"]), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
