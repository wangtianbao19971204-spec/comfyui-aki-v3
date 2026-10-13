"""Connect the erased line art back into the Krea2 control chain.

Measured defect: [05C7] ImageCompositeMasked (node 1147) produces the erased line art, but its
only consumer is the preview 1155. The Krea2 depth source switch 130160 took input_01 from 1191
(the depth of the reference image), so the erase never reached the control image.

This migration repoints 130160.input_01 from 1191 to 1147, so the switch becomes:
  input_01 = erased line art (the same path the Anima branch uses)
  input_02 = VNCCS pose depth
Node 1147's own source is the line-art switch 1157, so selecting a different line-art
preprocessor upstream still feeds through, and nothing else is touched.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("UAP统一生产工作台_v2.json",)
DIRECTORIES = ("ComfyUI/user/default/workflows", "production_tools/templates")
SWITCH = 130160
ERASED = 1147
PREVIOUS = 1191


def migrate(data):
    result = copy.deepcopy(data)
    nodes = {node["id"]: node for node in result["nodes"]}
    switch = nodes.get(SWITCH)
    if switch is None:
        raise ValueError(f"root node {SWITCH} is missing")
    link_style = "list" if any(isinstance(item, list) for item in result["links"]) else "dict"

    def entry(link):
        if link_style == "list":
            return {"id": link[0], "origin": link[1], "origin_slot": link[2],
                    "target": link[3], "target_slot": link[4]}
        return {"id": link["id"], "origin": link["origin_id"], "origin_slot": link["origin_slot"],
                "target": link["target_id"], "target_slot": link["target_slot"]}

    def rewrite(link, origin):
        if link_style == "list":
            link[1] = origin
        else:
            link["origin_id"] = origin

    changes = []
    target_port = None
    for index, port in enumerate(switch.get("inputs", [])):
        if port.get("name") == "input_01":
            target_port = (index, port)
            break
    if target_port is None:
        raise ValueError(f"node {SWITCH} has no input_01")
    index, port = target_port
    link_id = port.get("link")
    current = None
    for link in result["links"]:
        info = entry(link)
        if info["id"] == link_id:
            current = (link, info)
            break
    if current is None:
        raise ValueError(f"input_01 of {SWITCH} is not linked")
    link, info = current
    if info["origin"] == ERASED:
        return result, {"changed": False, "note": "input_01 already comes from the erased line art",
                        "scope": "node 130160 input_01"}
    if info["origin"] != PREVIOUS:
        raise ValueError(f"input_01 of {SWITCH} comes from {info['origin']}, expected {PREVIOUS}")
    origin_node = nodes[PREVIOUS]
    for output in origin_node.get("outputs", []):
        if isinstance(output.get("links"), list) and link_id in output["links"]:
            output["links"].remove(link_id)
    target_node = nodes[ERASED]
    for output in target_node.get("outputs", []):
        if isinstance(output.get("links"), list):
            output["links"].append(link_id)
            break
    rewrite(link, ERASED)
    changes.append({"link": link_id, "field": "origin", "before": PREVIOUS, "after": ERASED,
                    "target": f"{SWITCH}.input_01", "target_slot": index})
    audit = {"changed": True, "changes": changes,
             "switch": {"input_01": "1147 erased line art", "input_02": "130161 VNCCS pose depth"},
             "scope": "only the origin of the link feeding 130160.input_01"}
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
