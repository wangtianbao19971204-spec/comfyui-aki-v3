from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LAYOUT_DIRS = (
    "00_source",
    "01_visual_spec",
    "02_master_refs",
    "03_seed_v0",
    "04_v0_outputs/candidates",
    "05_dataset_v1",
    "06_rejected",
    "07_tests",
    "08_models",
    "09_workflows",
    "runs",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def resolve_path(base: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    config = load_json(config_path)
    base = config_path.parent
    config["_config_path"] = str(config_path)
    config["_project_dir"] = str(base)

    comfy = config.setdefault("comfyui", {})
    comfy["workflow_template"] = str(
        resolve_path(base, comfy["workflow_template"])
    )
    if comfy.get("root"):
        comfy["root"] = str(resolve_path(base, comfy["root"]))

    llm = config.setdefault("selection", {}).setdefault("llm", {})
    if llm.get("provider_config"):
        llm["provider_config"] = str(
            resolve_path(base, llm["provider_config"])
        )

    references = config.setdefault("references", [])
    for item in references:
        item["path"] = str(resolve_path(base, item["path"]))

    return config


def ensure_layout(config: dict[str, Any]) -> Path:
    project_dir = Path(config["_project_dir"])
    for relative in LAYOUT_DIRS:
        (project_dir / relative).mkdir(parents=True, exist_ok=True)
    return project_dir


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe to persist in run manifests."""
    result = {
        key: value
        for key, value in config.items()
        if not key.startswith("_")
    }
    return json.loads(json.dumps(result, ensure_ascii=False))
