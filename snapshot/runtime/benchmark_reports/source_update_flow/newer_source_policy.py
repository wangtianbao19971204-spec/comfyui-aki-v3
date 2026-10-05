"""Reusable exact-body rule for future website and document imports."""
import copy
import re
import unicodedata


def body_key(text):
    value = unicodedata.normalize("NFKC", text or "").replace("_", " ").replace("\\", "")
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return re.sub(r"\s*([,:{}\[\]()])\s*", r"\1", value).strip(", ")


def apply_newer_exact_source(metadata, existing_text, incoming_text, source, preview):
    """Prefer a verified newer exact-body source, preserving unrelated user metadata.

    Caller must verify publisher order and image bytes before calling. Different
    bodies remain a review conflict; this function deliberately rejects them.
    """
    if body_key(existing_text) != body_key(incoming_text):
        raise ValueError("不同正文必须逐项裁决，不能用新来源覆盖")
    if not source.get("dataset") or not source.get("entry_id") or not source.get("release"):
        raise ValueError("新来源缺少固定身份或版本")
    if not preview or not source.get("image_sha256"):
        raise ValueError("新来源图片未经验证")
    updated = copy.deepcopy(metadata)
    history = list(updated.get("external_sources") or [])
    prior = updated.get("external_source")
    if prior and (prior.get("dataset"), prior.get("entry_id")) not in {
        (item.get("dataset"), item.get("entry_id")) for item in history
    }:
        history.append(prior)
    history = [item for item in history if (item.get("dataset"), item.get("entry_id")) !=
               (source["dataset"], source["entry_id"])]
    history.append(copy.deepcopy(source))
    updated["external_sources"] = history
    updated["external_source"] = copy.deepcopy(source)
    updated["preview"] = preview
    return updated
