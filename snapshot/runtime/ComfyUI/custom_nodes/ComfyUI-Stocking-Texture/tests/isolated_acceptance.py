"""Exercise a newly materialized, CPU-only local ComfyUI texture instance.

Creates a synthetic image only in the supplied isolated input folder; never uses port 8188.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

import numpy as np
from PIL import Image


def run(url, runtime, prompt_file, output):
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port or parsed.port == 8188:
        raise ValueError("Use an explicit localhost isolation port other than 8188")
    if parsed.path not in ("", "/") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Expected a plain local ComfyUI URL")
    runtime = runtime.resolve()
    receipt = runtime / "RESTORE_RECEIPT.json"
    if not receipt.is_file() or not json.loads(receipt.read_text(encoding="utf-8")).get("pass"):
        raise ValueError("A successful fresh materialization receipt is required")
    output = output.resolve()
    if output.exists():
        raise ValueError("Acceptance report must be new")
    input_dir, output_dir = runtime / "ComfyUI/input", runtime / "ComfyUI/output"
    input_dir.mkdir(parents=True, exist_ok=True)
    fixture = input_dir / "stocking-example.png"
    if fixture.exists():
        raise ValueError("Retain previous fixture; use another new validation tree")
    h, w = 160, 128
    yy, xx = np.mgrid[:h, :w]
    rgb = np.stack((0.30 + xx / 1600, 0.27 + yy / 2000, 0.25 + xx / 2100), axis=2)
    Image.fromarray(np.round(rgb * 255).astype(np.uint8)).save(fixture)

    def http(path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(url.rstrip("/") + path, data=data,
                          headers={"Content-Type": "application/json"} if data is not None else {})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    info = http("/object_info")
    assert all(name in info for name in ("StockingTextureGuides", "StockingTextureRender", "SaveImage"))
    queue = http("/queue")
    assert not queue.get("queue_running") and not queue.get("queue_pending")
    template = json.loads(prompt_file.read_text(encoding="utf-8"))
    client = uuid.uuid4().hex

    def execute(prompt):
        queued = http("/prompt", {"prompt": prompt, "client_id": client})
        assert not queued.get("node_errors"), queued.get("node_errors")
        pid = queued["prompt_id"]
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            history = http("/history/" + pid)
            if pid in history:
                item = history[pid]
                assert item["status"]["status_str"] == "success", item["status"]
                return pid, item
            time.sleep(0.2)
        raise TimeoutError("Isolated texture execution timed out")

    def saved(item, node):
        descriptor = item["outputs"][node]["images"][0]
        assert descriptor["type"] == "output"
        path = (output_dir / descriptor["subfolder"] / descriptor["filename"]).resolve()
        if not path.is_relative_to(output_dir.resolve()):
            raise ValueError("Unexpected output path")
        with Image.open(path) as image:
            return np.array(image), path.relative_to(output_dir).as_posix()

    _, baseline_item = execute({"1": template["1"], "4": {
        "class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "Stocking/reference"}}})
    baseline, _ = saved(baseline_item, "4")
    selected = np.zeros((h, w), bool); selected[10:150, 15:113] = True
    records = []
    for style in ("细线", "针织", "斜单线", "加濑风", "油光（试验）"):
        prompt = json.loads(json.dumps(template))
        prompt["3"]["inputs"].update(style=style, color_exclude=False, auto_strength=False)
        for name, suffix in (("4", "finished"), ("5", "layer"), ("6", "problems")):
            prompt[name]["inputs"]["filename_prefix"] = f"Stocking/{len(records)}_{suffix}"
        pid, item = execute(prompt)
        result, full_name = saved(item, "4")
        layer, layer_name = saved(item, "5")
        assert result.shape == baseline.shape and layer.shape == (h, w, 4)
        assert np.array_equal(result[~selected], baseline[~selected])
        assert np.all(layer[~selected, 3] == 0)
        assert np.any(result[selected] != baseline[selected])
        a = layer[..., 3:4] / 255
        composite = baseline * (1 - a) + layer[..., :3] * a
        error = float(np.abs(composite - result).max())
        assert error <= 2.0, error  # SaveImage independently quantizes RGB and alpha to 8 bit.
        records.append({"style": style, "prompt_id": pid, "success": True,
                        "changed_pixels": int(np.any(result != baseline, axis=2).sum()),
                        "outside_changed_pixels": 0, "layer_mode": "RGBA",
                        "png_composite_max_error_8bit": error, "finished": full_name, "layer": layer_name})
    _, repeat = execute(json.loads(json.dumps(prompt)))
    result2, _ = saved(repeat, "4")
    assert np.array_equal(result, result2)
    queue = http("/queue")
    assert not queue.get("queue_running") and not queue.get("queue_pending")
    report = {"schema": 1, "time_utc": datetime.now(timezone.utc).isoformat(), "pass": True,
              "mode": "isolated-comfyui-cpu-synthetic", "registered_nodes": ["StockingTextureGuides", "StockingTextureRender"],
              "styles": records, "repeat_identical": True, "queue_empty": True,
              "models_loaded": False, "production_deployed": False,
              "limitations": ["Synthetic fixture only; real illustration quality and browser gestures are separate checks"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.url, args.runtime, args.prompt_file, args.report)
