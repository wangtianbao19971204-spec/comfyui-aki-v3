"""Visual QA contact sheets and flat-background texture measurements."""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RUN = Path(__file__).resolve().parent
PREVIOUS = RUN.parent / "20261004_live_acceptance"
FONT = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 19)
BOX = (884, 340, 1140, 660)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def opened(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def sheet(images, labels, target, full=False):
    width, height = (300, 430) if full else (300, 350)
    canvas = Image.new("RGB", (width * len(images), height + 55), "#20242b")
    draw = ImageDraw.Draw(canvas)
    for i, (im, label) in enumerate(zip(images, labels)):
        im = im.copy()
        im.thumbnail((width - 12, height - 12), Image.Resampling.LANCZOS)
        canvas.paste(im, (i * width + (width - im.width) // 2, 48 + (height - im.height) // 2))
        draw.text((i * width + 8, 14), label, fill="white", font=FONT)
    target.parent.mkdir(exist_ok=True)
    canvas.save(target)


controls = [
    ("OmniSR only", "k2_upscale_only_2026100402"),
    ("Old redraw; no seams", "k2_usdu_no_seam_2026100402"),
    ("Old full USDU", "k2_full_2026100402"),
]
images, labels, records = [], [], []
for label, job in controls:
    receipt = read(PREVIOUS / "results" / f"{job}.json")
    item = next(o for o in receipt["outputs"] if o["node_id"] == "950")
    images.append(opened(item["path"]))
    labels.append(label)
    records.append({"job": job, "path": item["path"], "historical_control": True})

for path in sorted((RUN / "results").glob("*.json")):
    receipt = read(path)
    if receipt["status"] != "success":
        continue
    if receipt["seed"] != 2026100502:
        continue
    item = next((o for o in receipt["outputs"] if o["node_id"] == "950"), None)
    if item is None:
        continue
    image = opened(item["path"])
    if image.size != (1152, 1536):
        continue
    images.append(image)
    labels.append(receipt["case"])
    records.append({"job": receipt["job"], "path": item["path"], "historical_control": False})

for record, image in zip(records, images):
    crop = image.crop(BOX)
    pixels = np.asarray(crop, dtype=np.float32)
    smooth = np.asarray(crop.filter(ImageFilter.GaussianBlur(3)), dtype=np.float32)
    record.update({"background_crop": list(BOX),
                   "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                   "background_rgb_mean": pixels.mean(axis=(0, 1)).tolist(),
                   "background_high_pass_rms": float(np.sqrt(np.mean((pixels - smooth) ** 2))),
                   "interpretation": "Texture proxy only, not an aesthetic quality score or an acceptance criterion"})

for start in range(3, len(images), 3):
    selected = [0, 1, 2] + list(range(start, min(start + 3, len(images))))
    sheet([images[i].crop(BOX) for i in selected], [labels[i] for i in selected], RUN / "comparisons" / f"background_{start}.png")
    sheet([images[i] for i in selected], [labels[i] for i in selected], RUN / "comparisons" / f"full_{start}.png", full=True)

(RUN / "measurements.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([{k: r[k] for k in ("job", "background_high_pass_rms", "background_rgb_mean")} for r in records], indent=2))
