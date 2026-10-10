"""Run a fixed, authorized image through an existing local ComfyUI texture service.

Use an isolated instance first. Writes only uniquely named QA inputs/outputs and
an evidence directory; never clears queues, loads models, or edits source images.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

import cv2
import numpy as np
from PIL import Image


def run(a):
    assert urlparse(a.url).hostname in ("localhost", "127.0.0.1")
    assert re.fullmatch(r"[a-zA-Z0-9_-]+", a.label)
    a.out.mkdir(parents=True, exist_ok=False)
    source = np.array(Image.open(a.image).convert("RGB"))
    h, w = source.shape[:2]
    data = json.loads(a.guides.read_text(encoding="utf-8"))
    assert (data["width"], data["height"]) == (w, h)
    selected = np.zeros((h, w), np.uint8)
    for r in data["regions"]:
        assert r["polygons"], "This acceptance requires explicit polygons"
        for p in r["polygons"]:
            cv2.fillPoly(selected, [np.round(p).astype(np.int32)], 1)
    image_name = a.label + ".png"
    input_path = a.input_dir / image_name
    assert not input_path.exists(), "QA input name is already used"
    Image.fromarray(source).save(input_path)
    client = uuid.uuid4().hex

    def http(path, payload=None):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        with urlopen(Request(a.url.rstrip("/") + path, data=raw,
                             headers={"Content-Type": "application/json"}), timeout=30) as response:
            return json.load(response)

    def empty():
        queue = http("/queue")
        assert not queue["queue_running"] and not queue["queue_pending"], "Queue is not empty"

    def execute(prompt, name):
        empty()
        (a.out / (name + "-prompt.json")).write_text(json.dumps(prompt, ensure_ascii=False, indent=2), encoding="utf-8")
        pid = http("/prompt", dict(prompt=prompt, client_id=client))["prompt_id"]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            hist = http("/history/" + pid)
            if pid in hist:
                item = hist[pid]
                assert item["status"]["status_str"] == "success", item["status"]
                (a.out / (name + "-history.json")).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
                return pid, item
            time.sleep(0.25)
        raise TimeoutError(pid)

    def saved(item, node):
        d = item["outputs"][node]["images"][0]
        assert d["type"] == "output"
        path = (a.output_dir / d["subfolder"] / d["filename"]).resolve()
        assert path.is_relative_to(a.output_dir.resolve())
        return np.array(Image.open(path)), str(path)

    empty()
    contract = http("/object_info/StockingTextureRender")["StockingTextureRender"]
    assert contract["input"]["optional"]["dark_adapt"][1]["default"] is True
    load = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    _, reference = execute({"1": load, "4": {"class_type": "SaveImage", "inputs": {
        "images": ["1", 0], "filename_prefix": a.label + "/reference"}}}, "reference")
    baseline, _ = saved(reference, "4")
    cases = []
    for style in ("细线", "针织", "斜单线", "加濑风", "油光（试验）"):
        cases.append((style, dict(dark_adapt=True)))
        if style in ("细线", "针织", "斜单线"):
            cases.extend([(style, dict(dark_adapt=False)),
                          (style, dict(dark_adapt=True, density=65, strength=160, auto_strength=False))])
    cases += [("细线", dict(strength=0, auto_strength=False)),
              ("细线", dict(sparkle_bright=100)), ("细线", dict(sparkle_bright=100))]
    records, outputs = [], []
    for i, (style, overrides) in enumerate(cases):
        guides = json.loads(json.dumps(data))
        for r in guides["regions"]:
            r["id"] += f"-{i}"  # make repeated renders execute and solve afresh
        params = dict(image=["1", 0], guides_json=json.dumps(guides, ensure_ascii=False),
                      style=style, density=100, strength=100, auto_strength=True, tilt=32,
                      sparkle_bright=0, sparkle_even=0, sparkle_depth=0, color_exclude=True,
                      auto_walls=False, depth_mode="近处较亮", seed=20261009, dark_adapt=True)
        params.update(overrides)
        prompt = {"1": load, "3": {"class_type": "StockingTextureRender", "inputs": params}}
        for node, output, suffix in (("4", 0, "finished"), ("5", 1, "layer"), ("6", 3, "problems")):
            prompt[node] = {"class_type": "SaveImage", "inputs": {
                "images": ["3", output], "filename_prefix": f"{a.label}/{i:02d}-{suffix}"}}
        pid, item = execute(prompt, f"{i:02d}")
        result, path = saved(item, "4")
        layer, layer_path = saved(item, "5")
        assert layer.shape == (h, w, 4)
        assert np.array_equal(result[selected == 0], baseline[selected == 0])
        assert not layer[..., 3][selected == 0].any()
        alpha = layer[..., 3:4] / 255
        error = float(np.abs(baseline * (1-alpha) + layer[..., :3] * alpha - result).max())
        assert error <= 2.0, error
        changed = int(np.any(result != baseline, axis=2).sum())
        if params["strength"] == 0:
            assert changed == 0
        elif params["dark_adapt"]:
            assert changed > 0
        records.append(dict(case=i, style=style, settings=overrides, prompt_id=pid,
                            changed_pixels=changed, outside_changed_pixels=0,
                            composite_error_8bit=error, image=path, layer=layer_path))
        outputs.append(result)
        print(json.dumps({k:records[-1][k] for k in ("case", "style", "changed_pixels", "composite_error_8bit")}), flush=True)
    assert np.array_equal(outputs[-1], outputs[-2]), "Forced recomputation was not deterministic"
    empty()
    report = dict(schema=1, source_sha256=hashlib.sha256(a.image.read_bytes()).hexdigest(),
                  url=a.url, cases=records, case_count=len(records), pass_all=True,
                  forced_repeat_equal=True, model_nodes_executed=False)
    (a.out / "ACCEPTANCE.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("url", "label"):
        p.add_argument("--" + name, required=True)
    for name in ("input-dir", "output-dir", "image", "guides", "out"):
        p.add_argument("--" + name, required=True, type=Path)
    run(p.parse_args())
