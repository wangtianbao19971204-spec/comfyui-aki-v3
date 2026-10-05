"""Pair each conservative-band output with its own pure-upscale reference."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RUN = Path(__file__).resolve().parent
FONT = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 21)
DEST = RUN / "comparisons"
DEST.mkdir(exist_ok=True)

paths = list((RUN / "results").glob("conservative_band_*.json"))
paths += list((RUN / "results").glob("default_size_full_*.json"))
for result_path in sorted(paths):
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "success"
    pairs = []
    for nid, label in (("905", "Pure OmniSR reference"), ("950", "Band Pass / redraw 0.03 / seam 0.03")):
        item = next(x for x in result["outputs"] if x["node_id"] == nid)
        with Image.open(item["path"]) as image:
            pairs.append((image.convert("RGB"), label))
    width, height = pairs[0][0].size
    assert pairs[1][0].size == (width, height)
    for region, box in {
        "full": (0, 0, width, height),
        "upper": (width // 4, 0, width * 3 // 4, height // 3),
        "center_seam": (width // 4, 3 * height // 5, width * 3 // 4, 4 * height // 5),
        "hands": (width // 4, 2 * height // 5, width * 3 // 4, 3 * height // 5),
        "feet": (width // 4, 4 * height // 5, width * 3 // 4, height),
    }.items():
        crops = [(image.crop(box), label) for image, label in pairs]
        cell_width, cell_height = crops[0][0].size
        canvas = Image.new("RGB", (cell_width * 2, cell_height + 48), "#20242b")
        draw = ImageDraw.Draw(canvas)
        for index, (crop, label) in enumerate(crops):
            canvas.paste(crop, (index * cell_width, 48))
            draw.text((index * cell_width + 10, 10), label, fill="white", font=FONT)
        canvas.save(DEST / f"{result['job']}_{region}.png")
    print(result["job"])
