"""Read LM's exact-resource trigger record without writing either provider's data."""
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path


def read_lm_trigger_words(file_path):
    if not file_path or not os.path.isfile(file_path):
        return None
    resource = os.path.normcase(os.path.abspath(file_path)).replace("\\", "/")
    sidecar = Path(os.path.splitext(file_path)[0] + ".metadata.json")
    if not sidecar.is_file():
        return None
    try:
        raw = sidecar.read_bytes()
        data = json.loads(raw)
        civitai = data.get("civitai")
        if not isinstance(civitai, dict) or "trainedWords" not in civitai:
            return None
        words = civitai["trainedWords"]
        if not isinstance(words, list) or any(not isinstance(word, str) for word in words):
            raise ValueError("Invalid trainedWords")
    except (OSError, ValueError, TypeError, AttributeError):
        return {"source": "lm_unavailable", "words": [], "resource": resource,
                "label": "LoRA Manager 记录暂不可读，请检查元数据", "revision": None}
    override = civitai.get("trainedWordsOverride") is True
    return {"source": "lm_user_override" if override else "lm_existing",
            "words": list(words), "resource": resource,
            "label": "LoRA Manager · 用户维护" if override else "LoRA Manager · 既有维护值，来源未确认",
            "revision": hashlib.sha256(raw).hexdigest()}


def overlay_trigger_authority(info_data, file_path):
    """Return a transient read view. Original WeiLin candidates stay on disk unchanged."""
    result = dict(info_data)
    authority = read_lm_trigger_words(file_path)
    result["triggerSourceLabel"] = "WeiLin 兼容候选 · 来源未确认"
    if authority is None:
        return result
    result["triggerAuthority"] = authority
    result["triggerSourceLabel"] = authority["label"]
    result["triggerCandidates"] = {"source": "weilin_cache",
                                   "loraWorks": info_data.get("loraWorks", ""),
                                   "trainedWords": deepcopy(info_data.get("trainedWords", []))}
    result["trainedWords"] = [{"word": word, "source": authority["source"]}
                              for word in authority["words"]]
    result["loraWorks"] = ", ".join(authority["words"])
    return result
