"""Measure saved acceptance outputs and make diagnostic contact sheets only."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RUN = Path(__file__).resolve().parent
FONT = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 19)
PARTS = {"hand_yolov9c.pt": "hand", "adetailerFootYolov8x_v20.pt": "foot",
         "face_yolov9c.pt": "face", "Eyeful_v2-Individual.pt": "eye"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def opened(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def sheet(images, labels, path, width=420, height=590):
    canvas = Image.new("RGB", (width * len(images), height + 54), "#20242b")
    draw = ImageDraw.Draw(canvas)
    for index, (image, label) in enumerate(zip(images, labels)):
        preview = image.copy()
        preview.thumbnail((width - 16, height - 16), Image.Resampling.LANCZOS)
        canvas.paste(preview, (index * width + (width - preview.width) // 2,
                              54 + (height - preview.height) // 2))
        draw.text((index * width + 8, 14), label, fill="white", font=FONT)
    canvas.save(path)
    return str(path)


def delta(a, b):
    assert a.size == b.size
    d = np.abs(np.asarray(a).astype(np.int16) - np.asarray(b).astype(np.int16))
    changed = d.max(axis=2) > 0
    return {"changed_pixels": int(changed.sum()), "changed_fraction": float(changed.mean()),
            "mean_absolute_delta": float(d.mean()), "max_absolute_delta": int(d.max())}


records = []
for result_path in sorted((RUN / "results").glob("*.json")):
    result = read(result_path)
    case, job = result["case"], result["job"]
    record = {"case": case, "job": job, "status": result["status"],
              "wall_seconds": result["wall_seconds"], "images": [], "parts": [], "comparisons": []}
    history_path = RUN / "history" / (job + ".json")
    history = read(history_path) if history_path.exists() else {}
    record["cached_nodes"] = [str(n) for k, v in history.get("status", {}).get("messages", [])
                              if k == "execution_cached" for n in v.get("nodes", [])]
    events = read(RUN / "telemetry" / (job + "_progress.json"))
    record["sampling_starts"] = {}
    for event in events:
        if event["type"] == "progress" and event["data"].get("value") == 1:
            nid = str(event["data"].get("node"))
            record["sampling_starts"][nid] = record["sampling_starts"].get(nid, 0) + 1
    samples = read(RUN / "telemetry" / (job + "_system.json"))
    record["peak_process_rss_gib"] = round(max(s["process_rss"] for s in samples) / 2**30, 3)
    record["min_system_available_gib"] = round(min(s["system_available"] for s in samples) / 2**30, 3)
    with (RUN / "telemetry" / (job + "_gpu.csv")).open(encoding="utf-8") as stream:
        gpu = [[float(c.strip()) for c in row[1:]] for row in csv.reader(stream) if len(row) == 5]
    record["peak_gpu_mib"] = max(row[0] for row in gpu)
    record["peak_gpu_utilization_percent"] = max(row[1] for row in gpu)
    if result["status"] != "success":
        record["execution_errors"] = result.get("execution_errors", [])
        records.append(record)
        continue
    graph = read(RUN / "exports" / (case + ".json"))["prompt"]
    output = {item["node_id"]: item for item in result["outputs"] if item["kind"] == "output"}
    for item in output.values():
        with Image.open(item["path"]) as raw:
            record["images"].append({"node_id": item["node_id"], "path": item["path"],
                "size": list(raw.size), "mode": raw.mode,
                "pixel_sha256": hashlib.sha256(raw.tobytes()).hexdigest()})
    finals = [item for nid, item in output.items() if not nid.startswith("qa_")]
    assert len(finals) == 1, (case, finals)
    final_item = finals[0]
    final = opened(final_item["path"])
    base = opened(output["qa_base" if "qa_base" in output else "qa_input"]["path"])
    record["input_size"] = list(base.size)
    record["output_size"] = list(final.size)
    record["final_path"] = final_item["path"]
    if case.endswith("_smoke"):
        record["base_final_delta"] = delta(base, final)
    elif case.endswith("_full"):
        previous = base
        details = [(nid, n) for nid, n in graph.items() if n["class_type"] == "DetailerForEach"]
        details.sort(key=lambda pair: int(pair[0].split(":")[-1]))
        for nid, node in details:
            detector_id = node["inputs"]["segs"][0]
            detector = graph[detector_id]
            provider = graph[detector["inputs"]["bbox_detector"][0]]
            part = PARTS[provider["inputs"]["model_name"].split("/")[-1]]
            current = opened(output["qa_stage_" + nid]["path"])
            mask_item = output["qa_mask_save_" + detector_id]
            mask_image = opened(mask_item["path"]).convert("L")
            mask = np.asarray(mask_image) > 0
            d = np.abs(np.asarray(current).astype(np.int16) - np.asarray(previous).astype(np.int16))
            changed = d.max(axis=2) > 0
            part_record = {"part": part, "detailer_id": nid, "detector_id": detector_id,
                "mask_nonzero_pixels": int(mask.sum()), "mask_bbox": mask_image.getbbox(),
                **delta(previous, current), "changed_inside_mask": int((changed & mask).sum()),
                "changed_outside_mask": int((changed & ~mask).sum()),
                "sampling_starts": record["sampling_starts"].get(nid, 0),
                "interpretation": "Mask and pixel change prove local processing, not correction quality; union masks are not detector counts."}
            if mask.any():
                box = mask_image.getbbox()
                box = (max(0, box[0] - 24), max(0, box[1] - 24),
                       min(base.width, box[2] + 24), min(base.height, box[3] + 24))
                final_box = tuple(round(v * (final.width / base.width if i % 2 == 0 else final.height / base.height))
                                  for i, v in enumerate(box))
                path = RUN / "comparisons" / (case + "_" + part + ".png")
                record["comparisons"].append(sheet([previous.crop(box), current.crop(box),
                    mask_image.crop(box).convert("RGB"), final.crop(final_box)],
                    ["Before " + part, "After " + part, "Union mask", "Final output"], path, 350, 390))
            record["parts"].append(part_record)
            previous = current
        record["upscale_factor"] = [final.width / base.width, final.height / base.height]
        record["upscale_delta_vs_lanczos"] = delta(previous.resize(final.size, Image.Resampling.LANCZOS), final)
        smoke = RUN / "results" / (case.replace("_full", "_smoke") + "_2026100501.json")
        if smoke.exists():
            smoke_base = next(item for item in read(smoke)["outputs"] if item["node_id"] == "qa_base")
            record["smoke_base_delta"] = delta(opened(smoke_base["path"]), base)
        record["comparisons"].append(sheet([base, previous, final],
            ["Base " + str(base.size), "Before upscale", "Final " + str(final.size)],
            RUN / "comparisons" / (case + "_stages.png")))
    else:
        if base.size == final.size:
            record["input_output_delta"] = delta(base, final)
        if case == "ext04":
            box = (330, 270, 430, 420)
            record["shirt_color_spot_check"] = {"xyxy": box,
                "input_mean_rgb": np.asarray(base.crop(box)).mean(axis=(0, 1)).tolist(),
                "output_mean_rgb": np.asarray(final.crop(box)).mean(axis=(0, 1)).tolist(),
                "method": "Fixed center-torso rectangle, not clothing segmentation or identity scoring"}
        if case == "ext05":
            a, b = np.asarray(base).astype(np.int16), np.asarray(final).astype(np.int16)
            changed = np.abs(a - b).max(axis=2) > 0
            crop_mask = np.zeros(changed.shape, dtype=bool)
            crop_mask[128:640, 128:640] = True
            record["crop_check"] = {"xywh": [128, 128, 512, 512],
                "changed_inside": int((changed & crop_mask).sum()),
                "changed_outside": int((changed & ~crop_mask).sum())}
        if case == "ext06":
            with Image.open(final_item["path"]) as raw:
                assert "A" in raw.getbands(), "Transparent output has no alpha channel"
                alpha = np.asarray(raw.getchannel("A"))
                record["alpha_check"] = {"range": [int(alpha.min()), int(alpha.max())],
                    "fully_transparent_pixels": int((alpha == 0).sum()),
                    "partly_transparent_pixels": int(((alpha > 0) & (alpha < 255)).sum()),
                    "fully_opaque_pixels": int((alpha == 255).sum())}
                checker = Image.new("RGBA", raw.size, "#dddddd")
                draw = ImageDraw.Draw(checker)
                for y in range(0, raw.height, 32):
                    for x in range(0, raw.width, 32):
                        if (x // 32 + y // 32) % 2:
                            draw.rectangle((x, y, x + 31, y + 31), fill="#999999")
                final = Image.alpha_composite(checker, raw.convert("RGBA")).convert("RGB")
        if case == "ext07":
            record["center_delta"] = delta(base, final.crop((128, 0, 128 + base.width, base.height)))
            record["unfeathered_center_delta"] = delta(base.crop((32, 0, base.width - 32, base.height)),
                final.crop((160, 0, 128 + base.width - 32, base.height)))
            record["expected_output_size"] = [base.width + 256, base.height]
            record["comparisons"].append(sheet([final.crop((760, 0, 1024, 264)),
                final.crop((760, 660, 1024, 924)), final.crop((0, 720, 264, 984))],
                ["Right upper junction", "Right lower junction", "Left lower junction"],
                RUN / "comparisons" / "ext07_junctions.png", 320, 300))
        if case in {"ext08", "ext09"}:
            record["upscale_factor"] = [final.width / base.width, final.height / base.height]
            record["delta_vs_lanczos"] = delta(base.resize(final.size, Image.Resampling.LANCZOS), final)
            factor = final.width / base.width
            box = (310, 35, 485, 185)
            out_box = tuple(round(v * factor) for v in box)
            record["comparisons"].append(sheet([base.crop(box).resize((700, 600), Image.Resampling.NEAREST),
                final.crop(out_box)], ["Input (nearest display)", "Upscaled face crop"],
                RUN / "comparisons" / (case + "_face.png"), 720, 620))
        record["comparisons"].append(sheet([base, final], ["Input " + str(base.size), "Output " + str(final.size)],
                                               RUN / "comparisons" / (case + "_io.png")))
    records.append(record)

(RUN / "measurements.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([{k: r[k] for k in ("case", "status", "wall_seconds", "parts")} for r in records], ensure_ascii=False))
