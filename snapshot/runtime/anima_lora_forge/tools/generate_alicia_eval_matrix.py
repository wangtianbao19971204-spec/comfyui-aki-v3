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
RUN = PROJECT / "runs" / "alicia_bell" / "alicia_bell_calibration_400_v1"
EVAL_ROOT = RUN / "evaluation"
LORA_ROOT = COMFY_ROOT / "models" / "loras" / "anima" / "character" / "alicia_bell_eval"
BASE_URL = "http://127.0.0.1:8188"

sys.path.insert(0, str(FORGE_ROOT))
from character_forge.comfy import ComfyClient, output_images  # noqa: E402


NEGATIVE = (
    "nsfw, nude, naked, topless, bottomless, nipples, areola, genitals, "
    "underwear, lingerie, bikini, transparent main clothes, erotic, lewd, "
    "child, teen, schoolgirl, multiple people, duplicate character, bad anatomy, "
    "extra limbs, missing fingers, cropped feet, text, watermark, signature, "
    "artist name, worst quality, low quality"
)

SWEEP_PROMPTS = {
    "ordinary_anchor": {
        "seed": 260817,
        "positive": (
            "alcbl7yo260817, masterpiece, best quality, safe, solo, one adult woman, "
            "ordinary Alicia Bell form, warm approachable soft oval face, fair warm skin, "
            "natural honey-hazel amber eyes with normal round pupils, loose light-brown "
            "champagne hair with a small side-braid accent, fully clothed, opaque ivory "
            "high-collar long-sleeve blouse, short teal shoulder shawl, opaque wine-red "
            "knee-length A-line skirt, dark brown opaque tights, brown low ankle boots, "
            "full body, neutral standing pose, plain warm gray studio background, "
            "clean anime character art"
        ),
    },
    "morning_star_anchor": {
        "seed": 260818,
        "positive": (
            "alcbl7yo260817, masterpiece, best quality, safe, solo, one adult woman, "
            "Morning Star form, warm approachable soft oval face, fair warm skin, "
            "champagne-gold eyes with normal round pupils, peach rose-gold low twin tails "
            "with wine-red ribbons, exactly one small gold five-point hair star, fully "
            "clothed, opaque ivory upper idol dress, plain wine-red collar knot, short "
            "translucent ivory gauze shoulder shawl over opaque clothing, plain wine-red "
            "high-waist bodice, compact opaque ivory bell skirt with solid wine-red hem, "
            "plain sheer ivory stockings, wine-red high heels, full body, neutral standing "
            "pose, plain warm gray studio background, clean anime character art"
        ),
    },
}

CONTROL_PROMPTS = {
    **SWEEP_PROMPTS,
    "ordinary_modern_casual": {
        "seed": 260819,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, ordinary Alicia Bell form, "
            "honey-hazel eyes, loose champagne-brown hair, fully clothed in a navy denim "
            "jacket, opaque white crew-neck shirt, straight black trousers, gray socks and "
            "white sneakers, walking pose, full body, quiet modern city sidewalk, clean "
            "anime character art, no cape, no skirt"
        ),
    },
    "ordinary_formal": {
        "seed": 260820,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, ordinary Alicia Bell form, "
            "honey-hazel eyes, loose champagne-brown hair, fully clothed in an opaque "
            "midnight-blue tailored blazer, ivory buttoned blouse, matching ankle-length "
            "trousers, black socks and black loafers, poised standing pose, full body, "
            "plain reception interior, polished anime illustration, no cape, no red skirt"
        ),
    },
    "morning_star_adventure": {
        "seed": 260821,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, Morning Star form, peach-gold "
            "low twin tails with wine ribbons, one small gold five-point hair star, "
            "champagne eyes, fully clothed in an opaque burgundy travel tunic with long "
            "ivory sleeves, black fitted trousers, dark opaque socks and brown knee-high "
            "boots, one plain leather belt pouch, full body, calm adventure stance, simple "
            "stone path, fantasy RPG anime concept art, no idol skirt, no shoulder gauze"
        ),
    },
    "morning_star_fantasy_role": {
        "seed": 260822,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, Morning Star form, peach-gold "
            "low twin tails with wine ribbons, one small gold five-point hair star, "
            "champagne eyes, fully clothed as a fantasy court mage in an opaque ivory "
            "high-collar coat, wine-red waist sash, long dark teal skirt, opaque black "
            "tights and wine ankle boots, holding one closed spellbook, full body, quiet "
            "library alcove, watercolor storybook illustration, no idol dress"
        ),
    },
    "accessory_absent": {
        "seed": 260823,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, Morning Star form, peach-gold "
            "low twin tails with wine-red ribbons, champagne eyes, no star hair accessory, "
            "no hair clip, fully clothed in an opaque coral cardigan, ivory blouse, dark "
            "wine midi skirt, opaque tights and brown ankle boots, waist-up portrait, plain "
            "light background, clean anime character art"
        ),
    },
    "accessory_replaced": {
        "seed": 260824,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, Morning Star form, peach-gold "
            "low twin tails with wine-red ribbons, champagne eyes, one plain oval pearl "
            "hair clip instead of a star, fully clothed in an opaque coral cardigan, ivory "
            "blouse, dark wine midi skirt, opaque tights and brown ankle boots, waist-up "
            "portrait, plain light background, clean anime character art"
        ),
    },
    "style_watercolor": {
        "seed": 260825,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, ordinary Alicia Bell form, "
            "honey-hazel eyes, loose champagne-brown hair, fully clothed in an ivory blouse, "
            "teal shawl, wine skirt, dark tights and brown boots, seated reading, full body, "
            "delicate watercolor and ink storybook illustration, pale paper texture"
        ),
    },
    "style_3d": {
        "seed": 260826,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, ordinary Alicia Bell form, "
            "honey-hazel eyes, loose champagne-brown hair, fully clothed in an ivory blouse, "
            "teal shawl, wine skirt, dark tights and brown boots, standing pose, full body, "
            "polished stylized 3D anime game render, soft cel-shaded materials"
        ),
    },
    "style_graphic_novel": {
        "seed": 260827,
        "positive": (
            "alcbl7yo260817, safe, solo, adult Alicia Bell, Morning Star form, peach-gold "
            "low twin tails with wine ribbons, one small gold five-point hair star, fully "
            "clothed in an opaque ivory blouse, wine vest, black trousers and wine boots, "
            "dynamic walking pose, full body, crisp graphic-novel ink and flat color style"
        ),
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_template() -> dict[str, Any]:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))["graph"]


def lora_name(step: int) -> str:
    return (
        "anima\\character\\alicia_bell_eval\\"
        f"alicia_bell_r32_step{step:04d}.safetensors"
    )


def lora_path(step: int) -> Path:
    return LORA_ROOT / f"alicia_bell_r32_step{step:04d}.safetensors"


def build_graph(step: int, strength: float, prompt: dict[str, Any], prefix: str) -> dict[str, Any]:
    graph = copy.deepcopy(load_template())
    graph["2"]["inputs"]["unet_name"] = "Anima\\anima_baseV10.safetensors"
    graph["107"]["inputs"]["positive"] = prompt["positive"]
    graph["6"]["inputs"]["text"] = NEGATIVE
    for node_id in ("112", "384", "385", "390"):
        graph.pop(node_id, None)
    graph["900010"] = {
        "inputs": {
            "model": ["2", 0],
            "lora_name": lora_name(step),
            "strength_model": strength,
        },
        "class_type": "LoraLoaderModelOnly",
        "_meta": {"title": "Alicia evaluation LoRA"},
    }
    graph["167"]["inputs"]["model"] = ["900010", 0]
    graph["6"]["inputs"]["clip"] = ["165", 0]
    graph["134"]["inputs"]["clip"] = ["165", 0]
    graph["519"]["inputs"].update({"width": 1024, "height": 1024, "batch_size": 1})
    graph["542"]["inputs"]["seed"] = int(prompt["seed"])
    graph["10"]["inputs"].update({
        "steps": 30,
        "cfg": 4.5,
        "sampler_name": "euler",
        "scheduler": "simple",
        "denoise": 1.0,
    })
    images = graph["13"]["inputs"]["images"]
    graph["13"] = {
        "inputs": {"images": images, "filename_prefix": prefix},
        "class_type": "SaveImage",
        "_meta": {"title": "Alicia evaluation output"},
    }
    return graph


def wait_for_prompt(client: ComfyClient, prompt_id: str, timeout_seconds: int = 1200) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            history = client.history(prompt_id=prompt_id)
            last_error = None
        except (TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(2)
            continue
        record = history.get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("completed"):
                if status.get("status_str") != "success":
                    raise RuntimeError(
                        f"ComfyUI job failed {prompt_id}: "
                        f"{json.dumps(status.get('messages', []), ensure_ascii=False)[:3000]}"
                    )
                return record
        time.sleep(1.5)
    detail = f"; last polling error: {last_error}" if last_error else ""
    raise RuntimeError(f"ComfyUI job timed out: {prompt_id}{detail}")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def jobs_for_phase(phase: str, steps: list[int]) -> list[tuple[int, float, str, dict[str, Any]]]:
    if phase == "sweep":
        return [(step, 0.8, key, prompt) for step in steps for key, prompt in SWEEP_PROMPTS.items()]
    jobs: list[tuple[int, float, str, dict[str, Any]]] = []
    for step in steps:
        jobs.extend((step, 0.8, key, prompt) for key, prompt in CONTROL_PROMPTS.items())
        for strength in (0.6, 1.0):
            jobs.extend((step, strength, key, prompt) for key, prompt in SWEEP_PROMPTS.items())
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("sweep", "controls"), required=True)
    parser.add_argument("--steps", default="100,200,300,400")
    args = parser.parse_args()
    steps = [int(value) for value in args.steps.split(",") if value.strip()]
    for step in steps:
        if not lora_path(step).is_file():
            raise SystemExit(f"Missing evaluation LoRA: {lora_path(step)}")

    output_dir = EVAL_ROOT / args.phase
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_version": 1, "phase": args.phase, "records": []}
    existing = {record["job_key"] for record in manifest["records"]}
    client = ComfyClient(BASE_URL, comfy_root=COMFY_ROOT, timeout=120)

    for step, strength, prompt_id, prompt in jobs_for_phase(args.phase, steps):
        strength_tag = str(strength).replace(".", "p")
        job_key = f"step{step:04d}_s{strength_tag}_{prompt_id}"
        destination = output_dir / f"{job_key}.png"
        if job_key in existing and destination.is_file():
            continue
        prefix = f"alicia_lora_eval/{args.phase}/{job_key}"
        prompt_graph = build_graph(step, strength, prompt, prefix)
        comfy_prompt_id = client.queue_prompt(prompt_graph)
        record = wait_for_prompt(client, comfy_prompt_id, timeout_seconds=1200)
        images = output_images(record)
        if len(images) != 1:
            raise RuntimeError(f"Expected one output for {job_key}, found {len(images)}")
        client.copy_output_image(images[0], destination)
        manifest["records"].append({
            "job_key": job_key,
            "checkpoint_step": step,
            "checkpoint_path": str(lora_path(step).resolve()),
            "checkpoint_sha256": sha256_file(lora_path(step)),
            "lora_strength": strength,
            "prompt_id": prompt_id,
            "positive": prompt["positive"],
            "negative": NEGATIVE,
            "seed": prompt["seed"],
            "sampler": "euler",
            "scheduler": "simple",
            "steps": 30,
            "cfg": 4.5,
            "width": 1024,
            "height": 1024,
            "comfy_prompt_id": comfy_prompt_id,
            "output_path": str(destination.resolve()),
            "output_sha256": sha256_file(destination),
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        atomic_json(manifest_path, manifest)
        print(f"completed {job_key}", flush=True)
    print(json.dumps({"phase": args.phase, "count": len(manifest["records"]), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
