#!/usr/bin/env python3
"""Generate three Rosasha reaction-pack candidate sets from a recent ComfyUI graph."""

from __future__ import annotations

import argparse
import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_PROMPT = (
    "rsrs_anima, masterpiece, best quality, very aesthetic, safe, solo, "
    "one 23-year-old adult Lalafell woman, single character reaction portrait, "
    "one and only one character, one face only, centered composition, "
    "emerald green eyes, honey-blonde fluffy curls, exactly one high side ponytail, "
    "exactly one large black ribbon, short close-fitting leaf-shaped ears, "
    "fully clothed, opaque crimson-and-ivory high-collar blouse, shoulders completely covered, "
    "clean bold outline, polished anime reaction illustration, plain soft pastel background, "
    "clean empty corners, highly readable expression, consistent character design"
)

NEGATIVE_PROMPT = (
    "multiple characters, multiple people, multiple faces, extra face, duplicate face, "
    "secondary face, floating head, floating face, tiny character, miniature character, "
    "corner character, inset portrait, picture-in-picture, small sticker, multiple stickers, "
    "sticker sheet, emoji, emoji icons, decorative icons, corner decoration, mascot, collage, "
    "split panel, multiple views, character sheet, expression sheet, speech bubble, text, letters, "
    "logo, watermark, signature, artist name, nsfw, nude, naked, topless, bottomless, cleavage, "
    "bare shoulders, underwear, lingerie, bikini, transparent clothes, erotic, suggestive, lewd, "
    "child, baby, ordinary human proportions, long face, long neck, long elf ears, twin ponytails, "
    "two ponytails, extra bow, missing ribbon, wrong eye color, black hair, extra arms, extra hands, "
    "extra fingers, fused fingers, malformed hands, cropped head, blurry, low quality, worst quality"
)

EXPRESSIONS = [
    ("01_hello", "waist-up portrait, smiling brightly, raising one hand and waving hello"),
    ("02_happy", "head-and-shoulders portrait, bright cheerful smile, sparkling open eyes, rosy cheeks"),
    ("03_laugh", "head-and-shoulders portrait, laughing joyfully, eyes tightly closed, wide smiling mouth"),
    ("04_angry", "head-and-shoulders portrait, angry puffed cheeks, furrowed eyebrows, cute frustrated expression"),
    ("05_sad", "head-and-shoulders portrait, sad aggrieved expression, watery eyes, tears about to fall"),
    ("06_shocked", "head-and-shoulders portrait, extremely surprised, very wide eyes, small round open mouth"),
    ("07_confused", "head-and-shoulders portrait, confused curious expression, head tilted, one eyebrow raised"),
    ("08_deadpan", "head-and-shoulders portrait, deadpan expression, half-lidded eyes, flat unimpressed mouth"),
    ("09_sleepy", "head-and-shoulders portrait, peaceful sleepy smile, closed eyes, cheek resting on clasped hands"),
    ("10_sorry", "waist-up portrait, apologetic expression, watery worried eyes, hands held together"),
    (
        "11_cooking",
        "waist-up portrait, wearing a clean red cooking apron over the long-sleeved outfit, "
        "happily stirring one small steaming cooking pot with a wooden spoon",
    ),
    (
        "12_delicious",
        "waist-up portrait, holding one small tasting spoon, delighted sparkling eyes, "
        "eyes gently closed, pleased smile, enjoying delicious food",
    ),
]


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def dependency_closure(graph: dict, output_node: str) -> dict:
    needed: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in needed:
            return
        if node_id not in graph:
            raise KeyError(f"Missing dependency node: {node_id}")
        needed.add(node_id)
        for value in graph[node_id].get("inputs", {}).values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and value[0] in graph
            ):
                visit(value[0])

    visit(output_node)
    return {node_id: copy.deepcopy(graph[node_id]) for node_id in needed}


def configure_graph(graph: dict, prompt: str, seed: int, batch_size: int) -> dict:
    graph["107"]["inputs"]["positive"] = prompt
    graph["107"]["inputs"]["auto_random"] = False
    graph["107"]["inputs"]["lora_str"] = ""
    graph["107"]["inputs"]["temp_str"] = "[]"
    graph["107"]["inputs"]["temp_lora_str"] = ""
    graph["6"]["inputs"]["text"] = NEGATIVE_PROMPT

    for node_id in ("384", "390"):
        graph[node_id]["inputs"]["text"] = ""
        graph[node_id]["inputs"]["loras"] = {"__value__": []}

    graph["385"]["inputs"]["text"] = "<lora:rosasha_anima_r32_v1:0.90>"
    graph["385"]["inputs"]["loras"] = {
        "__value__": [
            {
                "name": "rosasha_anima_r32_v1",
                "strength": 0.9,
                "active": True,
                "expanded": False,
                "clipStrength": 0.9,
                "locked": False,
            }
        ]
    }
    graph["519"]["inputs"].update({"width": 1024, "height": 1024, "batch_size": batch_size})
    graph["542"]["inputs"]["seed"] = seed
    return graph


def wait_for_history(base_url: str, prompt_id: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = request_json(base_url, f"/history/{prompt_id}")
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("completed"):
                return entry
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI task failed: {json.dumps(status, ensure_ascii=False)}")
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def download_outputs(base_url: str, entry: dict, output_dir: Path, stem: str) -> list[Path]:
    image_records: list[dict] = []
    for output in entry.get("outputs", {}).values():
        image_records.extend(output.get("images", []))
    if not image_records:
        raise RuntimeError(f"No images returned for {stem}")

    saved: list[Path] = []
    for index, record in enumerate(image_records, start=1):
        query = urllib.parse.urlencode(
            {
                "filename": record["filename"],
                "subfolder": record.get("subfolder", ""),
                "type": record.get("type", "temp"),
            }
        )
        destination = output_dir / f"{stem}_candidate_{index}.png"
        with urllib.request.urlopen(base_url.rstrip("/") + "/view?" + query, timeout=60) as response:
            destination.write_bytes(response.read())
        saved.append(destination)
    return saved


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def make_contact_sheet(files: list[Path], destination: Path, title: str) -> None:
    thumb = 384
    label_height = 46
    columns = 3
    rows = 4
    title_height = 64
    canvas = Image.new("RGB", (columns * thumb, title_height + rows * (thumb + label_height)), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = load_font(28)
    label_font = load_font(20)
    draw.text((20, 16), title, fill="black", font=title_font)
    for index, path in enumerate(files):
        row, column = divmod(index, columns)
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
            x = column * thumb + (thumb - image.width) // 2
            y = title_height + row * (thumb + label_height) + (thumb - image.height) // 2
            canvas.paste(image, (x, y))
        label = path.name.split("_candidate_")[0]
        draw.text(
            (column * thumb + 12, title_height + row * (thumb + label_height) + thumb + 8),
            label,
            fill="black",
            font=label_font,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=95)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8188")
    parser.add_argument("--source-prompt-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_history = request_json(args.base_url, f"/history/{args.source_prompt_id}")
    source_entry = source_history[args.source_prompt_id]
    source_graph = source_entry["prompt"][2]
    base_graph = dependency_closure(source_graph, "13")

    manifest = {
        "source_prompt_id": args.source_prompt_id,
        "base_url": args.base_url,
        "lora": "rosasha_anima_r32_v1",
        "lora_strength": 0.9,
        "resolution": [1024, 1024],
        "candidates_per_expression": args.candidates,
        "negative_prompt": NEGATIVE_PROMPT,
        "jobs": [],
    }

    for expression_index, (name, suffix) in enumerate(EXPRESSIONS, start=1):
        prompt = BASE_PROMPT + ", " + suffix
        seed = 202607270000 + expression_index * 1000
        graph = configure_graph(copy.deepcopy(base_graph), prompt, seed, args.candidates)
        response = request_json(args.base_url, "/prompt", {"prompt": graph})
        prompt_id = response["prompt_id"]
        print(f"SUBMITTED {expression_index:02d}/{len(EXPRESSIONS)} {name} {prompt_id}", flush=True)
        entry = wait_for_history(args.base_url, prompt_id, args.timeout_seconds)
        saved = download_outputs(args.base_url, entry, output_dir, name)
        manifest["jobs"].append(
            {
                "name": name,
                "suffix": suffix,
                "seed": seed,
                "prompt_id": prompt_id,
                "files": [path.name for path in saved],
            }
        )
        print(f"COMPLETED {expression_index:02d}/{len(EXPRESSIONS)} {name} files={len(saved)}", flush=True)

    manifest_path = output_dir / "generation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for candidate_index in range(1, args.candidates + 1):
        files = [
            output_dir / f"{name}_candidate_{candidate_index}.png"
            for name, _ in EXPRESSIONS
        ]
        make_contact_sheet(
            files,
            output_dir.parent / f"comfyui_set_{candidate_index}_contact.png",
            f"Rosasha ComfyUI candidate set {candidate_index}",
        )
    print(f"DONE output={output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
