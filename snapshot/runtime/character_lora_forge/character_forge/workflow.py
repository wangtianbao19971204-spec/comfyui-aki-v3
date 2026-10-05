from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .config import load_json, save_json


def _linked_node_ids(value: Any) -> list[str]:
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    ):
        return [str(value[0])]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(_linked_node_ids(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_linked_node_ids(child))
        return result
    return []


def dependency_closure(
    graph: dict[str, Any],
    target_node_id: str,
) -> dict[str, Any]:
    target = str(target_node_id)
    if target not in graph:
        raise KeyError(f"输出节点不存在: {target}")
    keep: set[str] = set()
    stack = [target]
    while stack:
        node_id = stack.pop()
        if node_id in keep:
            continue
        node = graph.get(node_id)
        if node is None:
            continue
        keep.add(node_id)
        for value in (node.get("inputs") or {}).values():
            stack.extend(_linked_node_ids(value))
    return {node_id: graph[node_id] for node_id in graph if node_id in keep}


def capture_template(
    history_record: dict[str, Any],
    output_node_id: str,
    destination: str | Path,
) -> dict[str, Any]:
    prompt = history_record.get("prompt") or []
    if len(prompt) < 3 or not isinstance(prompt[2], dict):
        raise ValueError("历史记录中没有 API prompt 图")
    graph = dependency_closure(prompt[2], str(output_node_id))

    for node in graph.values():
        if node.get("class_type") == "WeiLinPromptUI":
            positive = (node.get("inputs") or {}).get("positive", "")
            node["inputs"] = {
                "positive": positive,
                "auto_random": False,
                "lora_str": "",
                "temp_str": "",
                "temp_lora_str": "",
                "random_template": "",
            }

    payload = {
        "schema_version": 1,
        "captured_from_prompt_id": history_record.get("prompt_id"),
        "output_node_id": str(output_node_id),
        "graph": graph,
    }
    save_json(Path(destination), payload)
    return payload


def _set_binding(
    graph: dict[str, Any],
    binding: dict[str, str],
    value: Any,
) -> None:
    node_id = str(binding["node"])
    input_name = binding["input"]
    if node_id not in graph:
        raise KeyError(f"工作流模板缺少绑定节点 {node_id}")
    graph[node_id].setdefault("inputs", {})[input_name] = value


def _inject_reference(
    graph: dict[str, Any],
    *,
    model_source: list[Any],
    switch_node: str,
    reference_filename: str,
    strength: float,
    lllite_name: str,
    max_dimension: int,
) -> None:
    load_id = "900001"
    scale_id = "900002"
    control_id = "900003"
    graph[load_id] = {
        "inputs": {"image": reference_filename},
        "class_type": "LoadImage",
        "_meta": {"title": "[FORGE] Master reference"},
    }
    graph[scale_id] = {
        "inputs": {
            "image": [load_id, 0],
            "upscale_method": "lanczos",
            "largest_size": int(max_dimension),
        },
        "class_type": "ImageScaleToMaxDimension",
        "_meta": {"title": "[FORGE] Reference resize"},
    }
    graph[control_id] = {
        "inputs": {
            "model": model_source,
            "image": [scale_id, 0],
            "lllite_name": lllite_name,
            "strength": float(strength),
            "start_percent": 0.0,
            "end_percent": 1.0,
            "preserve_wrapper": True,
        },
        "class_type": "AnimaLLLiteApply",
        "_meta": {"title": "[FORGE] Character reference LLLite"},
    }
    switch = graph[str(switch_node)].setdefault("inputs", {})
    switch["input_02"] = [control_id, 0]


def build_prompt_graph(
    template_path: str | Path,
    config: dict[str, Any],
    job: dict[str, Any],
    *,
    filename_prefix: str,
    reference_filename: str | None = None,
) -> dict[str, Any]:
    template = load_json(Path(template_path))
    graph = copy.deepcopy(template["graph"])
    comfy = config["comfyui"]
    bindings = comfy["bindings"]

    _set_binding(graph, bindings["positive"], job["positive"])
    _set_binding(graph, bindings["negative"], job["negative"])
    _set_binding(graph, bindings["seed"], int(job["seed"]))
    _set_binding(graph, bindings["width"], int(job["width"]))
    _set_binding(graph, bindings["height"], int(job["height"]))

    generation = config["generation"]
    if bindings.get("model") and generation.get("unet_name"):
        _set_binding(graph, bindings["model"], generation["unet_name"])
    if bindings.get("lora_anchor"):
        _set_binding(
            graph,
            bindings["lora_anchor"],
            generation.get("anchor_loras", ""),
        )
    if bindings.get("lora_style"):
        style_loras = generation["styles"][job["style_id"]].get("loras", "")
        _set_binding(graph, bindings["lora_style"], style_loras)
    if bindings.get("lora_character"):
        _set_binding(
            graph,
            bindings["lora_character"],
            generation.get("character_loras", ""),
        )

    output_node_id = str(bindings["output"]["node"])
    output = graph[output_node_id]
    images_input = output.get("inputs", {}).get("images")
    output["class_type"] = "SaveImage"
    output["inputs"] = {
        "images": images_input,
        "filename_prefix": filename_prefix,
    }
    output["_meta"] = {"title": "[FORGE] Save candidate"}

    if reference_filename and job.get("reference_strength", 0) > 0:
        reference = comfy["reference_control"]
        source_node = str(reference["model_source_node"])
        _inject_reference(
            graph,
            model_source=[source_node, int(reference.get("model_output_slot", 0))],
            switch_node=str(reference["switch_node"]),
            reference_filename=reference_filename,
            strength=float(job["reference_strength"]),
            lllite_name=reference["lllite_name"],
            max_dimension=int(reference.get("max_dimension", 1024)),
        )
    return graph
