"""Switch the Krea2 branch's base model to the non-distilled Krea2-Anime v2.0.

The comparison round showed the depth ControlNet-LoRA is effective with that base while
the Turbo base barely responds, and a Turbo run at LoRA strength 4 collapses into noise.
This migration writes the base model change together with the sampler settings that base
needs, because 8 steps at CFG 1 is a Turbo setting and would produce poor images here.

Only the Krea2 branch nodes are touched; everything else keeps its values, and the audit
records every before/after pair so the change can be reverted exactly.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("UAP统一生产工作台_v2.json",)
DIRECTORIES = ("ComfyUI/user/default/workflows", "production_tools/templates")

UNET = 1183
SAMPLER = 1200
BASE_MODEL = ('krea2\\图像生成\\Krea2__Krea2-Anime__v2.0__BF16__cv3357716__f3246945.safetensors')
SETTINGS = {"steps": 24, "cfg": 3.5, "sampler_name": "euler", "scheduler": "normal",
            "denoise": 1, "control_after_generate": "randomize"}


def migrate(data):
    result = copy.deepcopy(data)
    nodes = {node["id"]: node for node in result["nodes"]}
    for required in (UNET, SAMPLER):
        if required not in nodes:
            raise ValueError(f"root node {required} is missing; the Krea2 branch moved")
    changes = []

    def set_widget(node_id, name, value):
        node = nodes[node_id]
        widgets = node.get("widgets_values")
        if node["type"] == "UNETLoader":
            before = widgets[0]
            widgets[0] = value
        else:
            names = ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"]
            index = names.index(name)
            before = widgets[index]
            widgets[index] = value
        changes.append({"node": node_id, "type": node["type"], "widget": name,
                        "before": before, "after": value})

    set_widget(UNET, "unet_name", BASE_MODEL)
    for name, value in SETTINGS.items():
        if name == "control_after_generate":
            continue
        set_widget(SAMPLER, name, value)

    branch = next(item for item in result["extra"]["uap_workbench"]["branches"] if item["id"] == "k2")
    audit = {"branch": "k2", "branch_nodes": len(branch["nodeIds"]), "changes": changes,
             "scope": "Krea2 base model and sampler settings only; LoRA stack, prompts, seeds, sizes, "
                      "control strength and all other branches keep their values"}
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-source", action="store_true")
    args = parser.parse_args()
    for directory in DIRECTORIES:
        for name in FILES:
            path = ROOT / directory / name
            raw = path.read_text(encoding="utf-8")
            indent = len(raw.splitlines()[1]) - len(raw.splitlines()[1].lstrip())
            before = json.loads(raw)
            after, audit = migrate(before)
            print(json.dumps({"file": str(path.relative_to(ROOT)), "changed": before != after,
                              "written": args.write_source, "audit": audit}, ensure_ascii=False))
            if args.write_source and before != after:
                payload = (json.dumps(after, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
                if b"\r\n" in raw.encode("utf-8"):
                    payload = payload.replace(b"\n", b"\r\n")
                path.write_bytes(payload)


if __name__ == "__main__":
    main()
