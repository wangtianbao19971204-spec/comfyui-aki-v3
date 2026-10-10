"""Verify real ComfyUI LoadImage -> texture -> SaveImage against offline parity evidence.

Requires an authorized local service, an empty queue, a completed parity_matrix
directory, and unique QA names. Executes no model nodes and never clears queues.
"""
import argparse
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
    assert re.fullmatch(r"[A-Za-z0-9_-]+", a.label)
    reference = json.loads((a.references/"MATRIX.json").read_text(encoding="utf-8"))
    assert reference["pass_all"]
    a.out.mkdir(parents=True, exist_ok=False)
    client = uuid.uuid4().hex

    def http(path, data=None):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        with urlopen(Request(a.url.rstrip("/")+path, data=raw,
                             headers={"Content-Type": "application/json"}), timeout=30) as r:
            return json.load(r)

    def empty():
        q = http("/queue")
        assert not q["queue_running"] and not q["queue_pending"], "Queue is busy"

    def execute(prompt, name):
        empty()
        (a.out/(name+"-prompt.json")).write_text(json.dumps(prompt, indent=2, ensure_ascii=False), encoding="utf-8")
        pid = http("/prompt", dict(prompt=prompt, client_id=client))["prompt_id"]
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            hist = http("/history/"+pid)
            if pid in hist:
                item = hist[pid]
                assert item["status"]["status_str"] == "success", item["status"]
                (a.out/(name+"-history.json")).write_text(json.dumps(item, indent=2, ensure_ascii=False), encoding="utf-8")
                return pid, item
            time.sleep(0.5)
        raise TimeoutError(pid)

    def saved(item, node):
        info = item["outputs"][node]["images"][0]
        assert info["type"] == "output"
        path = (a.output_dir/info["subfolder"]/info["filename"]).resolve()
        assert path.is_relative_to(a.output_dir.resolve())
        return np.array(Image.open(path)), str(path)

    empty()
    rows = []
    styles = dict(knit="细线", loops="针织", lines="斜单线", grain="加濑风", oily="油光（试验）")
    for fixture in reference["results"]:
        name = fixture["id"]
        assert re.fullmatch(r"[A-Za-z0-9_-]+", name)
        folder = a.references/name
        rgb = np.array(Image.open(folder/"source.png").convert("RGB"))
        data = json.loads((folder/"guides.json").read_text(encoding="utf-8"))
        h, w = rgb.shape[:2]
        selected = np.zeros((h, w), np.uint8)
        for region in data["regions"]:
            for polygon in region["polygons"]:
                cv2.fillPoly(selected, [np.round(polygon).astype(np.int32)], 1)
        image_name = f"{a.label}-{name}.png"
        assert not (a.input_dir/image_name).exists()
        Image.fromarray(rgb).save(a.input_dir/image_name)
        load = dict(class_type="LoadImage", inputs=dict(image=image_name))
        jobs = [(style, False, 0) for style in styles]+[("knit", True, 100), ("knit", True, 100)]
        previous = None
        for i, (style, adapt, bright) in enumerate(jobs):
            guides = json.loads(json.dumps(data))
            for r in guides["regions"]:
                r["id"] += f"-{i}"  # avoid cached repeat execution
            params = dict(image=["1", 0], guides_json=json.dumps(guides, ensure_ascii=False),
                          style=styles[style], density=65, strength=100, auto_strength=True, tilt=32,
                          sparkle_bright=bright, sparkle_even=0, sparkle_depth=0, color_exclude=True,
                          auto_walls=False, depth_mode="近处较亮", seed=20261005, dark_adapt=adapt)
            prompt = {"1": load, "2": dict(class_type="StockingTextureRender", inputs=params)}
            for node, output, suffix in (("3", 0, "finished"), ("4", 1, "layer")):
                prompt[node] = dict(class_type="SaveImage", inputs=dict(images=["2", output],
                    filename_prefix=f"{a.label}/{name}/{i:02d}-{suffix}"))
            pid, item = execute(prompt, f"{name}-{i:02d}")
            result, path = saved(item, "3")
            layer, _ = saved(item, "4")
            expected = np.array(Image.open(folder/f"{style}-bright{bright}-adapt{int(adapt)}.png"))
            assert np.array_equal(result, expected), (name, style, "SaveImage differs from offline reference")
            assert np.array_equal(result[selected == 0], rgb[selected == 0])
            alpha = layer[..., 3:4]/255
            error = float(np.abs(rgb*(1-alpha)+layer[..., :3]*alpha-result).max())
            assert error <= 2, error
            if i == len(jobs)-1:
                assert np.array_equal(previous, result), "Forced repeat differs"
            previous = result
            row = dict(fixture=name, case=i, style=style, dark_adapt=adapt, sparkle_bright=bright,
                       prompt_id=pid, image=path, offline_png_equal=True, outside_changed_pixels=0,
                       changed_pixels=int(np.any(result != rgb, axis=2).sum()), layer_error_8bit=error)
            rows.append(row)
            print(json.dumps({k:v for k,v in row.items() if k not in ("image", "prompt_id")}), flush=True)
    empty()
    report = dict(schema=1, url=a.url, cases=rows, case_count=len(rows), pass_all=True,
                  model_nodes_executed=False, forced_repeat_equal=True)
    (a.out/"ACCEPTANCE.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("url", "label"):
        parser.add_argument("--"+name, required=True)
    for name in ("references", "input-dir", "output-dir", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    run(parser.parse_args())
