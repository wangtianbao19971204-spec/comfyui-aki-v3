"""Pure, offline naming rules for reviewed model-source catalogue entries.

Only explicitly selected public sidecar fields are returned.  This module does
not read files, move weights, infer compatibility from model-title keywords,
or publish the free-form notes, descriptions, images, or authentication fields.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any, Mapping
from urllib.parse import urlsplit


FAMILY_LABELS = {
    "anima": "Anima",
    "anima-2.9b": "Anima-2.9B",
    "krea2": "Krea2",
    "qwen-image-2.1": "Qwen-Image-2.1",
    "sam3.1": "SAM3.1",
    "other": "Other",
}
LORA_CATEGORIES = frozenset({
    "光影与色彩", "姿势与动作", "服装与配饰", "概念与效果", "滑块与调节",
    "画风与画师", "细节与修复", "角色与人物", "背景与场景", "控制与编辑",
    "自训角色", "其他与待核",
})

# These identities were individually verified by the retained-finished-weight
# cleanup receipt.  Their original v1/r32 names are existing release names.
LOCAL_FINISHED = {
    "alicia_bell_morning_star_anima29_r32_v1.safetensors": (
        "anima-2.9b", "Alicia Bell 晨星 r32", "v1"),
    "alicia_bell_morning_star_anima_r32_v1.safetensors": (
        "anima", "Alicia Bell 晨星 r32", "v1"),
    "alicia_bell_ordinary_anima_r32_v1.safetensors": (
        "anima", "Alicia Bell 普通形态 r32", "v1"),
    "rosasha_anima_r32_v1.safetensors": (
        "anima", "Rosasha r32", "v1"),
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    return value or None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def sanitize_component(value: str, *, max_length: int = 50) -> str:
    """Make a readable Unicode Windows component; never interpret it as a path."""
    if not isinstance(value, str) or max_length < 1:
        raise ValueError("A text component and positive maximum length are required")
    value = unicodedata.normalize("NFKC", value)
    value = "".join(
        char for char in value
        if not unicodedata.category(char).startswith("C")
    )
    value = re.sub(r'[<>:"/\\|?*]', "-", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"-{2,}", "-", value).strip(" .-_")
    value = value[:max_length].rstrip(" .-_")
    if not value or value in {".", ".."}:
        value = "unnamed"
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value):
        value = "_" + value
    return value[:max_length].rstrip(" .") or "unnamed"


def _source(asset: Mapping[str, Any]) -> Mapping[str, Any]:
    sources = asset.get("sources")
    if not isinstance(sources, list):
        return {}
    sources = [item for item in sources if isinstance(item, Mapping)]
    return next((item for item in sources if item.get("provider") == "civitai"
                 and _integer(item.get("version_id"))), sources[0] if sources else {})


def _family(asset: Mapping[str, Any], metadata: Mapping[str, Any], path: PurePosixPath,
            civitai: Mapping[str, Any], organization: Mapping[str, Any]) -> str:
    # Version-level bases describe the selected weights; multi-family model
    # titles/tags do not.  Generic Civitai "Anima" is refined only by a 2.9B
    # version field, reviewed organization, or the already reviewed split root.
    bases = [_text(civitai.get("baseModel")), _text(metadata.get("base_model")),
             _text(asset.get("family"))]
    for base in bases:
        if not base:
            continue
        normalized = re.sub(r"[ _-]", "", base).casefold()
        if "anima2.9b" in normalized:
            return "anima-2.9b"
        if normalized.startswith("krea2"):
            return "krea2"
        if normalized.startswith("anima"):
            version = _text(civitai.get("name")) or ""
            reviewed_family = _text(organization.get("family")) or ""
            if ("2.9b" in version.casefold() or "2.9b" in reviewed_family.casefold()
                    or any(part.casefold() == "anima-2.9b" for part in path.parts)):
                return "anima-2.9b"
            return "anima"
    # SAM lives in a checkpoint loader root but is an auxiliary segmenter.
    if path.name.casefold() == "sam3.1_multiplex_fp16.safetensors":
        return "sam3.1"
    if path.name.casefold() == "qwen-image-2.1-uc-bf16.gguf":
        return "qwen-image-2.1"
    reviewed_family = (_text(organization.get("family")) or "").casefold()
    for slug, label in FAMILY_LABELS.items():
        if reviewed_family in {slug, label.casefold()}:
            return slug
    return "other"


def _category(asset: Mapping[str, Any], path: PurePosixPath,
              organization: Mapping[str, Any], family: str,
              civitai: Mapping[str, Any]) -> str:
    if family == "sam3.1":
        return "目标检测与分割"
    if asset.get("kind") != "lora":
        return "图像生成" if family != "other" else "其他与待核"
    if _mapping(asset.get("derivation")).get("kind") == "local_training":
        return "自训角色"
    for field in ("category", "group", "purpose"):
        value = _text(organization.get(field))
        if value in LORA_CATEGORIES:
            return value
    # Preserve the established reviewed groups; broad Civitai "character" or
    # "concept" tags alone have previously misclassified styles and clothing.
    for part in reversed(path.parts[:-1]):
        if part in LORA_CATEGORIES:
            return part
    if (_text(_mapping(civitai.get("model")).get("type")) or "").casefold() == "controlnet":
        return "控制与编辑"
    return "其他与待核"


def _precision(metadata: Mapping[str, Any], civitai: Mapping[str, Any],
               organization: Mapping[str, Any], source: Mapping[str, Any],
               path: PurePosixPath) -> str | None:
    aliases = {"bf16": "BF16", "fp16": "FP16", "fp32": "FP32", "fp8": "FP8",
               "fp8_mixed": "FP8-Mixed", "fp8_scaled": "FP8-Scaled",
               "int8": "INT8", "int4": "INT4", "nvfp4": "NVFP4",
               "int8-convrot": "INT8-ConvRot"}
    file_id = _integer(source.get("file_id"))
    files = civitai.get("files")
    if isinstance(files, list) and file_id:
        selected = next((item for item in files if isinstance(item, Mapping)
                         and _integer(item.get("id")) == file_id), {})
        fp = _text(_mapping(selected.get("metadata")).get("fp"))
        if fp and fp.casefold() in aliases:
            precision = aliases[fp.casefold()]
            if precision == "INT8" and re.search(r"int8[ _-]*convrot", path.stem, re.I):
                return "INT8-ConvRot"
            return precision
    reviewed = _text(organization.get("precision"))
    if reviewed and reviewed.casefold() in aliases:
        return aliases[reviewed.casefold()]
    # This exactly bound HF filename declares the retained GGUF encoding.
    if path.name.casefold() == "qwen-image-2.1-uc-bf16.gguf":
        return "BF16"
    return None


def build_standardization(asset: Mapping[str, Any],
                          metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a public naming plan, preserving original source catalogue identity.

    Callers supply the catalogue asset and locally read JSON sidecar.  The
    original `path` is never changed here.  Deleted historical entries and
    resources outside LoRA/checkpoint/diffusion-model scope are rejected.
    """
    if asset.get("kind") not in {"lora", "checkpoint", "diffusion_model"}:
        raise ValueError("Not a LoRA/checkpoint/diffusion-model catalogue asset")
    if asset.get("observed_present") is not True:
        raise ValueError("Deleted or absent historical assets cannot be standardized")
    original_path = _text(asset.get("path"))
    if not original_path or "\\" in original_path:
        raise ValueError("Expected a relative POSIX catalogue path")
    path = PurePosixPath(original_path)
    if path.is_absolute() or ".." in path.parts or path.parts[:2] != ("ComfyUI", "models"):
        raise ValueError("Catalogue path is outside the model tree")
    roots = {"lora": "loras", "checkpoint": "checkpoints", "diffusion_model": "diffusion_models"}
    if len(path.parts) < 4 or path.parts[2] != roots[asset["kind"]]:
        raise ValueError("Catalogue kind and loader root do not agree")
    if path.suffix.casefold() not in {".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin"}:
        raise ValueError("Unsupported model suffix")
    metadata = _mapping(metadata)
    civitai = _mapping(metadata.get("civitai"))
    organization = _mapping(metadata.get("organization"))
    source = _source(asset)
    local = _mapping(asset.get("derivation")).get("kind") == "local_training"
    if not local and source.get("provider") == "civitai":
        expected_version = _integer(source.get("version_id"))
        sidecar_version = _integer(civitai.get("id"))
        if expected_version and sidecar_version and expected_version != sidecar_version:
            raise ValueError("Sidecar version is not the catalogue's selected version")
        expected_model = _integer(source.get("model_id"))
        sidecar_model = _integer(civitai.get("modelId"))
        if expected_model and sidecar_model and expected_model != sidecar_model:
            raise ValueError("Sidecar model is not the catalogue's selected model")
    family = _family(asset, metadata, path, civitai, organization)
    category = _category(asset, path, organization, family, civitai)
    model = _mapping(civitai.get("model"))
    display_name = _text(model.get("name")) or _text(organization.get("official_name"))
    version = _text(civitai.get("name")) or _text(organization.get("version"))
    # Strip only the local organization prefix/suffix from fallback labels.
    if not display_name:
        display_name = _text(metadata.get("model_name")) or path.stem
        display_name = re.sub(r"^【[^】]*】", "", display_name).strip()
        display_name = display_name.split(" · ", 1)[0].strip()
    if local:
        if path.name not in LOCAL_FINISHED:
            raise ValueError("Local training entry is not a reviewed finished release")
        family, display_name, version = LOCAL_FINISHED[path.name]
    precision = _precision(metadata, civitai, organization, source, path)
    identity = {
        "provider": "local_training" if local else source.get("provider"),
        "model_id": None if local else _integer(source.get("model_id")),
        "version_id": None if local else _integer(source.get("version_id")),
        "file_id": None if local else _integer(source.get("file_id")),
        "revision": None if local else _text(source.get("revision")),
    }
    components = [FAMILY_LABELS[family], sanitize_component(display_name)]
    if version:
        components.append(sanitize_component(version))
    if precision:
        components.append(precision)
    if identity["version_id"]:
        components.append("cv" + str(identity["version_id"]))
        if identity["file_id"]:
            components.append("f" + str(identity["file_id"]))
    elif identity["revision"]:
        components.append("rev" + sanitize_component(identity["revision"], max_length=12))
    else:
        digest = asset.get("local_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError("Source without version/revision needs a verified content identity")
        components.append("sha" + digest[:12].lower())
    if local:
        source_identity = "local_training:sha256=" + str(asset["local_sha256"]).lower()
    elif identity["version_id"]:
        source_identity = "civitai:" + ",".join(
            label + "=" + str(identity[field])
            for label, field in (("model", "model_id"), ("version", "version_id"), ("file", "file_id"))
            if identity[field] is not None
        )
    elif identity["revision"]:
        page_url = _text(source.get("page_url")) or ""
        repository = urlsplit(page_url).path.strip("/")
        source_identity = str(identity["provider"] or "upstream") + ":" + repository + "@" + identity["revision"]
    else:
        source_identity = str(identity["provider"] or "unresolved") + ":sha256=" + str(asset["local_sha256"]).lower()
    filename = "__".join(components) + path.suffix.lower()
    target = PurePosixPath("ComfyUI", "models", roots[asset["kind"]], family, category, filename)
    evidence = ["snapshot/inventory/model_sources.json"]
    if metadata:
        evidence.append(str(path.with_suffix(".metadata.json")))
    if local:
        evidence.append("docs/receipts/model_checkpoint_cleanup_20261007.json")
    return {
        "family_slug": family,
        "family_label": FAMILY_LABELS[family],
        "category": category,
        "display_name": display_name,
        "version": version,
        "precision": precision,
        "source_identity": source_identity,
        "target_path": str(target),
        "evidence": evidence,
    }
