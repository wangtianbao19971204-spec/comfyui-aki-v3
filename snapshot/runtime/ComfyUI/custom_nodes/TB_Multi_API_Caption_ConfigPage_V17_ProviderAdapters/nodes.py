import asyncio
import base64
import io
import json
import os
import re
import html
import hashlib
import time
import threading
import traceback
from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import aiohttp
    from aiohttp import web
except Exception:
    aiohttp = None
    web = None

try:
    from server import PromptServer
except Exception:
    PromptServer = None


ROOT = Path(__file__).resolve().parent
PROVIDERS_PATH = ROOT / "providers.json"
CACHE_PATH = ROOT / "models_cache.json"
CONFIG_HTML_PATH = ROOT / "web" / "config.html"

# In-memory per-node slot result cache. It is intentionally not written to disk,
# so API outputs are not persisted after ComfyUI restarts.
RUNNER_RESULT_CACHE = {}
RUNNER_CACHE_LOCK = threading.Lock()


def _cache_key(node_id):
    return str(node_id or "__unknown_runner__")


def get_runner_cache(node_id):
    key = _cache_key(node_id)
    with RUNNER_CACHE_LOCK:
        data = RUNNER_RESULT_CACHE.get(key, {})
        # copy values so later mutation does not corrupt the cache object
        return {int(k): dict(v) for k, v in data.items()}


def update_runner_cache(node_id, slot, result):
    key = _cache_key(node_id)
    item = dict(result or {})
    item["slot"] = int(slot)
    item["source"] = "cache"
    item["cached_at"] = time.time()
    with RUNNER_CACHE_LOCK:
        RUNNER_RESULT_CACHE.setdefault(key, {})[int(slot)] = item


def remove_runner_cache_slot(node_id, slot):
    key = _cache_key(node_id)
    with RUNNER_CACHE_LOCK:
        if key in RUNNER_RESULT_CACHE:
            RUNNER_RESULT_CACHE[key].pop(int(slot), None)


def clear_runner_cache(node_id=None):
    with RUNNER_CACHE_LOCK:
        if node_id is None:
            RUNNER_RESULT_CACHE.clear()
        else:
            RUNNER_RESULT_CACHE.pop(_cache_key(node_id), None)


def image_fingerprint(image):
    """Stable fingerprint for cache decisions.

    This intentionally depends only on the actual image tensor/array content,
    not on downstream node layout, workflow UI position, or the full prompt JSON.
    """
    try:
        if hasattr(image, "detach"):
            arr = image.detach().cpu().numpy()
        else:
            arr = np.asarray(image)
        arr = np.ascontiguousarray(arr)
        h = hashlib.sha256()
        h.update(str(arr.shape).encode("utf-8"))
        h.update(str(arr.dtype).encode("utf-8"))
        h.update(arr.tobytes())
        return h.hexdigest()
    except Exception:
        return "image_fingerprint_unavailable"


def stable_json_fingerprint(data):
    try:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = repr(data)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def runner_slot_signature(image_sig, system_prompt, user_prompt, slot, provider, model, timeout_seconds, temperature, max_tokens):
    provider_safe = dict(provider or {})
    if "api_key" in provider_safe:
        provider_safe["api_key_sha256"] = hashlib.sha256(str(provider_safe.pop("api_key") or "").encode("utf-8")).hexdigest()
    payload = {
        "image": image_sig,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "slot": int(slot),
        "provider": provider_safe,
        "model": model,
        "timeout_seconds": int(timeout_seconds),
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    return stable_json_fingerprint(payload)


def _read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_providers():
    data = _read_json(PROVIDERS_PATH, {"providers": []})
    cache = _read_json(CACHE_PATH, {"providers": {}})
    providers = data.get("providers", [])
    for p in providers:
        cached = cache.get("providers", {}).get(p.get("name", ""), [])
        merged = []
        for m in (p.get("models") or []):
            if m and m not in merged:
                merged.append(m)
        for m in cached:
            if m and m not in merged:
                merged.append(m)
        p["models"] = merged
    return {"providers": providers}


def get_provider(name):
    data = load_providers()
    for p in data.get("providers", []):
        if p.get("name") == name:
            return p
    return None


def provider_names():
    names = [p.get("name") for p in load_providers().get("providers", []) if p.get("name")]
    return names or ["<none>"]


def models_for_provider(provider_name):
    p = get_provider(provider_name)
    models = []
    if p:
        models = [m for m in p.get("models", []) if m]
    return ["<manual>"] + models if models else ["<manual>"]


def resolve_api_key(value):
    if not value:
        return ""
    value = str(value).strip()
    if value.lower().startswith("env:"):
        return os.environ.get(value[4:].strip(), "")
    return value


PLUGIN_VERSION = "17.1-response-cache-fix"

PROTOCOL_ALIASES = {
    "openai": "openai_chat",
    "openai_chat_completions": "openai_chat",
    "openai_compatible": "openai_chat",
    "chat_completions": "openai_chat",
    "responses": "openai_responses",
    "openai_response": "openai_responses",
    "anthropic": "anthropic_messages",
    "claude": "anthropic_messages",
    "gemini": "gemini_generate_content",
    "google": "gemini_generate_content",
    "google_gemini": "gemini_generate_content",
}


def normalize_protocol(provider):
    raw = str(
        (provider or {}).get("protocol")
        or (provider or {}).get("type")
        or "openai_chat"
    ).strip().lower()
    return PROTOCOL_ALIASES.get(raw, raw)


def apply_model_overrides(provider, model):
    """Return a copy of provider config with the first matching model rule applied.

    Rule format:
      {"match": "claude", "set": {"image_order": "image_first"}}
    The match value is a case-insensitive regular expression.
    """
    result = deepcopy(provider or {})
    rules = result.pop("model_overrides", []) or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        pattern = str(rule.get("match") or "").strip()
        if not pattern:
            continue
        try:
            matched = re.search(pattern, str(model or ""), re.IGNORECASE)
        except re.error:
            matched = None
        if not matched:
            continue
        settings = rule.get("set")
        if not isinstance(settings, dict):
            settings = {k: v for k, v in rule.items() if k not in ("match", "set")}
        result.update(deepcopy(settings))
        break
    return result


def _to_uint8_image_array(image):
    if hasattr(image, "detach"):
        arr = image.detach().cpu().numpy()
    else:
        arr = np.asarray(image)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim not in (2, 3):
        raise ValueError(f"Unsupported image array shape: {getattr(arr, 'shape', None)}")

    if arr.dtype == np.uint8:
        out = arr
    else:
        arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
        max_value = float(np.max(arr)) if arr.size else 0.0
        if max_value <= 1.5:
            arr = arr * 255.0
        out = np.clip(arr, 0, 255).astype(np.uint8)

    if out.ndim == 3 and out.shape[-1] == 1:
        out = out[..., 0]
    if out.ndim == 3 and out.shape[-1] not in (3, 4):
        raise ValueError(f"Unsupported channel count: {out.shape[-1]}")
    return out


def _encode_pil_image(pil, image_format, quality):
    buf = io.BytesIO()
    fmt = image_format.upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt == "JPEG":
        if pil.mode not in ("RGB", "L"):
            pil = pil.convert("RGB")
        pil.save(buf, format="JPEG", quality=int(quality), optimize=True)
        mime = "image/jpeg"
    elif fmt == "WEBP":
        if pil.mode not in ("RGB", "RGBA", "L"):
            pil = pil.convert("RGB")
        pil.save(buf, format="WEBP", quality=int(quality), method=6)
        mime = "image/webp"
    else:
        fmt = "PNG"
        pil.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    return pil, buf.getvalue(), fmt, mime


def image_to_blob(image, provider=None):
    """Convert a ComfyUI IMAGE to a provider-ready Base64 image object.

    Provider options:
      image_format: jpeg | png | webp | auto (default jpeg)
      max_image_side: proportional long-edge limit (default 1536, 0 disables)
      jpeg_quality / image_quality: 1..100 (default 92)
      max_image_bytes: post-encoding target; oversized images are reduced (default 6000000)
    """
    provider = provider or {}
    arr = _to_uint8_image_array(image)
    pil = Image.fromarray(arr)
    original_width, original_height = pil.size

    max_side = int(provider.get("max_image_side", 1536) or 0)
    if max_side > 0 and max(pil.size) > max_side:
        scale = max_side / float(max(pil.size))
        new_size = (
            max(1, int(round(pil.width * scale))),
            max(1, int(round(pil.height * scale))),
        )
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        pil = pil.resize(new_size, resampling)

    requested_format = str(provider.get("image_format") or "jpeg").strip().lower()
    if requested_format == "auto":
        requested_format = "png" if pil.mode in ("RGBA", "LA") else "jpeg"
    if requested_format not in ("jpeg", "jpg", "png", "webp"):
        requested_format = "jpeg"

    quality = int(provider.get("jpeg_quality", provider.get("image_quality", 92)) or 92)
    quality = max(20, min(100, quality))
    max_bytes = int(provider.get("max_image_bytes", 6000000) or 0)

    encoded_pil, raw, final_format, mime_type = _encode_pil_image(pil, requested_format, quality)

    # Keep payloads manageable across middlewares. First reduce quality, then dimensions.
    if max_bytes > 0 and len(raw) > max_bytes:
        if final_format in ("JPEG", "WEBP"):
            for candidate_quality in (85, 78, 70, 62, 54, 46):
                encoded_pil, raw, final_format, mime_type = _encode_pil_image(
                    encoded_pil, final_format, min(quality, candidate_quality)
                )
                quality = min(quality, candidate_quality)
                if len(raw) <= max_bytes:
                    break

        resize_rounds = 0
        while len(raw) > max_bytes and min(encoded_pil.size) > 256 and resize_rounds < 5:
            ratio = max(0.55, min(0.9, (max_bytes / float(len(raw))) ** 0.5 * 0.95))
            new_size = (
                max(1, int(round(encoded_pil.width * ratio))),
                max(1, int(round(encoded_pil.height * ratio))),
            )
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            encoded_pil = encoded_pil.resize(new_size, resampling)
            encoded_pil, raw, final_format, mime_type = _encode_pil_image(
                encoded_pil, final_format, quality
            )
            resize_rounds += 1

    b64 = base64.b64encode(raw).decode("ascii")
    return {
        "base64": b64,
        "mime_type": mime_type,
        "byte_size": len(raw),
        "base64_chars": len(b64),
        "width": encoded_pil.width,
        "height": encoded_pil.height,
        "original_width": original_width,
        "original_height": original_height,
        "format": final_format,
        "quality": quality if final_format in ("JPEG", "WEBP") else None,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _join_url(base_url, path):
    path = str(path or "").strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return str(base_url or "").rstrip("/") + "/" + path.lstrip("/")


def _gemini_model_id(model):
    value = str(model or "").strip()
    if value.startswith("models/"):
        value = value[len("models/"):]
    return value


def _auth_headers(provider, protocol):
    headers = dict((provider or {}).get("headers") or {})
    headers.setdefault("Content-Type", "application/json")
    api_key = resolve_api_key((provider or {}).get("api_key", ""))
    if not api_key:
        return headers

    explicit_header = str((provider or {}).get("api_key_header") or "").strip()
    if explicit_header:
        prefix = str((provider or {}).get("api_key_prefix") or "").strip()
        headers.setdefault(explicit_header, f"{prefix} {api_key}".strip())
    elif protocol == "anthropic_messages":
        headers.setdefault("x-api-key", api_key)
    elif protocol == "gemini_generate_content":
        headers.setdefault("x-goog-api-key", api_key)
    else:
        headers.setdefault("Authorization", f"Bearer {api_key}")

    if protocol == "anthropic_messages":
        headers.setdefault(
            "anthropic-version",
            str((provider or {}).get("anthropic_version") or "2023-06-01"),
        )
    return headers


def _ordered_parts(image_part, text_part, image_order):
    if image_part is None:
        return [text_part]
    return [text_part, image_part] if image_order == "text_first" else [image_part, text_part]


def _sanitize_system_prompt(value):
    text = str(value or "")
    text = re.sub(
        r"\s*If no image is attached or readable,\s*output exactly:\s*IMAGE_NOT_RECEIVED\.?\s*",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def build_provider_request(provider, model, system_prompt, user_prompt, temperature, max_tokens, image_blob=None):
    effective = apply_model_overrides(provider, model)
    protocol = normalize_protocol(effective)
    base_url = str(effective.get("base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError(f"Provider {effective.get('name', '')} has no base_url")

    if image_blob is not None and effective.get("supports_vision") is False:
        raise RuntimeError(f"Model is configured as text-only: {model}")

    system = _sanitize_system_prompt(system_prompt or "You are an anime image analyst.")
    prompt = user_prompt or "Analyze the image."
    image_order = str(effective.get("image_order") or "image_first").strip().lower()
    headers = _auth_headers(effective, protocol)

    if protocol == "openai_chat":
        path = effective.get("path") or "/chat/completions"
        url = _join_url(base_url, path)
        messages = []
        if system and not effective.get("omit_system_role", False):
            messages.append({"role": "system", "content": system})

        if image_blob is None:
            user_content = prompt
        else:
            image_url = {"url": f"data:{image_blob['mime_type']};base64,{image_blob['base64']}"}
            detail = effective.get("image_detail")
            if detail in ("auto", "low", "high"):
                image_url["detail"] = detail
            image_part = {"type": "image_url", "image_url": image_url}
            text_part = {"type": "text", "text": prompt}
            user_content = _ordered_parts(image_part, text_part, image_order)
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
        }
        token_field = str(effective.get("max_tokens_field") or "max_tokens").strip()
        if token_field and token_field.lower() not in ("none", "omit", "false"):
            payload[token_field] = int(max_tokens)

    elif protocol == "openai_responses":
        path = effective.get("path") or "/responses"
        url = _join_url(base_url, path)
        content = [{"type": "input_text", "text": prompt}]
        if image_blob is not None:
            image_part = {
                "type": "input_image",
                "image_url": f"data:{image_blob['mime_type']};base64,{image_blob['base64']}",
            }
            detail = effective.get("image_detail")
            if detail in ("auto", "low", "high"):
                image_part["detail"] = detail
            text_part = content[0]
            content = _ordered_parts(image_part, text_part, image_order)
        payload = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": int(max_tokens),
        }
        if system:
            payload["instructions"] = system
        if effective.get("send_temperature", True):
            payload["temperature"] = float(temperature)

    elif protocol == "anthropic_messages":
        path = effective.get("path") or "/messages"
        url = _join_url(base_url, path)
        text_part = {"type": "text", "text": prompt}
        image_part = None
        if image_blob is not None:
            image_part = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_blob["mime_type"],
                    "data": image_blob["base64"],
                },
            }
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": _ordered_parts(image_part, text_part, image_order),
            }],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if system:
            payload["system"] = system

    elif protocol == "gemini_generate_content":
        path = effective.get("path") or "/models/{model}:generateContent"
        path = str(path).replace("{model}", _gemini_model_id(model))
        url = _join_url(base_url, path)
        text_part = {"text": prompt}
        image_part = None
        if image_blob is not None:
            image_part = {
                "inlineData": {
                    "mimeType": image_blob["mime_type"],
                    "data": image_blob["base64"],
                }
            }
        payload = {
            "contents": [{
                "role": "user",
                "parts": _ordered_parts(image_part, text_part, image_order),
            }],
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": int(max_tokens),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

    else:
        raise RuntimeError(
            f"Unsupported provider protocol: {protocol}. "
            "Supported: openai_chat, openai_responses, anthropic_messages, gemini_generate_content"
        )

    extra = effective.get("extra_payload") or {}
    if isinstance(extra, dict):
        payload.update(deepcopy(extra))

    return {
        "protocol": protocol,
        "url": url,
        "headers": headers,
        "payload": payload,
        "provider": effective,
        "image_order": image_order,
    }


def _response_text_value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("value"), str):
        return value["value"]
    return ""


def parse_provider_response(protocol, data):
    parsed = {
        "text": "",
        "finish_reason": None,
        "response_status": None,
        "refusal": None,
        "provider_error": None,
        "blocked_reason": None,
        "tool_calls": False,
        "invalid_response": False,
        "empty": True,
    }
    if not isinstance(data, dict):
        parsed.update({
            "provider_error": "Response JSON must be an object",
            "invalid_response": True,
        })
        return parsed
    if data.get("error") not in (None, "", {}):
        parsed["provider_error"] = data.get("error")
        return parsed

    texts = []

    if protocol == "openai_chat":
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            parsed.update({"invalid_response": True, "provider_error": "Missing choices[0]"})
            return parsed
        choice = choices[0]
        parsed["finish_reason"] = choice.get("finish_reason")
        parsed["response_status"] = data.get("status")
        message = choice.get("message")
        if isinstance(message, dict):
            refusal = _response_text_value(message.get("refusal"))
            if refusal:
                parsed["refusal"] = refusal
            parsed["tool_calls"] = bool(message.get("tool_calls") or message.get("function_call"))
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "").strip().lower()
                    if block_type == "refusal":
                        value = _response_text_value(block.get("refusal") or block.get("text") or block.get("content"))
                        if value:
                            parsed["refusal"] = value
                        continue
                    if block_type not in ("", "text", "output_text"):
                        continue
                    value = _response_text_value(block.get("text") or block.get("content"))
                    if value:
                        texts.append(value)
            elif content is not None:
                parsed["invalid_response"] = True
        elif isinstance(choice.get("text"), str):
            texts.append(choice["text"])
        else:
            parsed.update({"invalid_response": True, "provider_error": "Missing assistant message"})
            return parsed

        if not texts and isinstance(choice.get("text"), str):
            texts.append(choice["text"])

    elif protocol == "openai_responses":
        parsed["response_status"] = data.get("status")
        incomplete = data.get("incomplete_details") if isinstance(data.get("incomplete_details"), dict) else {}
        parsed["finish_reason"] = incomplete.get("reason") or data.get("status")
        refusal = _response_text_value(data.get("refusal"))
        if refusal:
            parsed["refusal"] = refusal
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            texts.append(data["output_text"])
        else:
            output = data.get("output")
            if not isinstance(output, list):
                parsed["invalid_response"] = True
            else:
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    item_type = str(item.get("type") or "").strip().lower()
                    if item_type in ("reasoning", "thinking", "analysis"):
                        continue
                    if item_type in ("function_call", "tool_call", "computer_call"):
                        parsed["tool_calls"] = True
                        continue
                    item_refusal = _response_text_value(item.get("refusal"))
                    if item_refusal:
                        parsed["refusal"] = item_refusal
                    if item_type not in ("", "message"):
                        continue
                    content = item.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        block_type = str(block.get("type") or "").strip().lower()
                        if block_type == "refusal":
                            value = _response_text_value(block.get("refusal") or block.get("text"))
                            if value:
                                parsed["refusal"] = value
                            continue
                        if block_type not in ("", "text", "output_text"):
                            continue
                        value = _response_text_value(block.get("text"))
                        if value:
                            texts.append(value)

    elif protocol == "anthropic_messages":
        parsed["finish_reason"] = data.get("stop_reason")
        parsed["response_status"] = data.get("type")
        content = data.get("content")
        if not isinstance(content, list):
            parsed["invalid_response"] = True
        else:
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type == "tool_use":
                    parsed["tool_calls"] = True
                elif block_type == "text":
                    value = _response_text_value(block.get("text"))
                    if value:
                        texts.append(value)

    elif protocol == "gemini_generate_content":
        feedback = data.get("promptFeedback") if isinstance(data.get("promptFeedback"), dict) else {}
        parsed["blocked_reason"] = feedback.get("blockReason")
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            if not parsed["blocked_reason"]:
                parsed["invalid_response"] = True
        elif not isinstance(candidates[0], dict):
            parsed["invalid_response"] = True
        else:
            candidate = candidates[0]
            parsed["finish_reason"] = candidate.get("finishReason")
            content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
            parts = content.get("parts")
            if not isinstance(parts, list):
                parsed["invalid_response"] = True
            else:
                for part in parts:
                    if not isinstance(part, dict) or part.get("thought") is True:
                        continue
                    if part.get("functionCall") is not None:
                        parsed["tool_calls"] = True
                    value = _response_text_value(part.get("text"))
                    if value:
                        texts.append(value)

    else:
        parsed.update({
            "provider_error": f"Unsupported response protocol: {protocol}",
            "invalid_response": True,
        })
        return parsed

    parsed["text"] = "\n".join(texts).strip()
    parsed["empty"] = not bool(parsed["text"])
    return parsed


def extract_provider_text(protocol, data):
    return parse_provider_response(protocol, data)["text"]


_MISSING_IMAGE_PATTERNS = [
    r"^\s*image[\s_-]*not[\s_-]*received[.!]?\s*$",
    r"\b(?:i\s+)?(?:did(?:n['’]?t| not)|do not|don['’]?t|cannot|can['’]?t|could not)\s+(?:receive|see|view|access|find)\s+(?:an?|the|any)?\s*image\b",
    r"\bno\s+image\s+(?:was\s+)?(?:provided|attached|received|included|available)\b",
    r"\bplease\s+(?:upload|attach|provide|send)\s+(?:an?|the)\s+image\b",
    r"(?:没有|未)收到.{0,12}(?:图片|图像)",
    r"(?:没有|未)提供.{0,12}(?:图片|图像)",
    r"无法(?:看到|查看|访问|读取).{0,12}(?:图片|图像)",
    r"请(?:上传|附上|提供|发送).{0,12}(?:图片|图像)",
]

_REFUSAL_PATTERNS = [
    r"\b(?:i\s+)?(?:can(?:not|['’]t)|won['’]t)\s+(?:help|assist)\s+with\s+(?:that|this|the)\s+image\b",
    r"\b(?:i\s+)?(?:can(?:not|['’]t)|won['’]t)\s+(?:help|assist)\s+with\s+(?:that|this|the|your)\s+(?:request|content)\b",
    r"\bsorry\b.{0,80}\b(?:can(?:not|['’]t)|won['’]t)\s+(?:help|assist)\b",
]


def response_reports_missing_image(text):
    value = str(text or "").strip()
    if not value:
        return False
    # Strong phrases only; limiting length reduces accidental matches in long analyses.
    sample = value[:1500]
    return any(re.search(pattern, sample, re.IGNORECASE | re.DOTALL) for pattern in _MISSING_IMAGE_PATTERNS)


def response_reports_refusal(text):
    value = str(text or "").strip()
    if not value:
        return False
    sample = value[:1500]
    return any(re.search(pattern, sample, re.IGNORECASE | re.DOTALL) for pattern in _REFUSAL_PATTERNS)



def _remove_agent_prefix(text):
    text = str(text or "").strip()
    # Common wrappers from Grok / aggregator multi-agent traces.
    text = re.sub(r"(?is)^>\s*\*\*\s*agent\s*\d+\s*\*\*\s*(?:说|says?)\s*:\s*", "", text).strip()
    text = re.sub(r"(?is)^agent\s*\d+\s*(?:说|says?)\s*:\s*", "", text).strip()
    return text


def _strip_known_prefix(line):
    line = _remove_agent_prefix(line)
    line = line.strip()
    line = re.sub(r"^[-*•>\s]+", "", line).strip()
    line = re.sub(r"^\*+|\*+$", "", line).strip()
    prefixes = [
        r"final\s+suggested\s+one[-\s]*line\s+prompt",
        r"final\s+one[-\s]*line\s+prompt",
        r"final\s+proposed\s+prompt\s+for\s+anima",
        r"final\s+proposed\s+prompt",
        r"final\s+suggested\s+prompt",
        r"final\s+prompt",
        r"final\s+output",
        r"proposed\s+full\s+single[-\s]*line\s+output",
        r"proposed\s+output\s+prompt",
        r"proposed\s+output",
        r"proposed\s+prompt",
        r"polished\s+output\s+ready",
        r"refined\s+full\s+one[-\s]*line\s+output\s+based\s+on\s+principles",
        r"refined\s+for\s+two\s+statements",
        r"positive\s+prompt",
        r"final\s+clip",
        r"answer",
        r"tags?",
        r"danbooru\s+tags?",
        r"key\s+tags?",
    ]
    changed = True
    while changed:
        changed = False
        for pref in prefixes:
            new_line = re.sub(rf"(?is)^\s*{pref}\s*[:：-]\s*", "", line).strip()
            if new_line != line:
                line = new_line
                changed = True
    return line.strip().strip('"').strip("'")


def _looks_like_prompt(line):
    if not line:
        return False
    line = _strip_known_prefix(line)
    if not line:
        return False
    low = line.lower()
    if low.startswith(("[error]", "[timeout]", "[skipped]")):
        return True
    # Reject meta/analysis lines even if they mention prompt keywords.
    bad_starts = (
        "image analysis", "suggested tags", "natural language part", "key details", "to make it", 
        "analyzing", "generating", "constructing", "finalizing", "crafting", "compiling", "refining",
        "the image", "this image", "content summary", "artistic style", "comparison table",
    )
    if low.startswith(bad_starts):
        return False
    comma_count = line.count(",")
    anchors = (
        "masterpiece", "best quality", "score_7", "1girl", "1boy", "solo", "anime illustration",
        "black_hair", "white_sweater", "pantyhose", "standing_sex", "doggystyle", "ahegao",
        "black hair", "white sweater", "anime",
    )
    # A usable Anima hybrid prompt should have enough tags OR a known prompt anchor plus sentence body.
    if comma_count >= 5 and any(a in low for a in anchors):
        return True
    return any(a in low for a in anchors) and comma_count >= 2 and (";" in line or "." in line)


def _score_prompt_candidate(line, final_hint=False):
    line = _strip_known_prefix(line)
    if not _looks_like_prompt(line):
        return -999
    low = line.lower()
    score = 0
    score += min(line.count(","), 35)
    if ";" in line: score += 8
    if "." in line: score += 4
    if any(x in low for x in ("final", "positive prompt", "final clip")) or final_hint: score += 40
    if low.startswith(("1girl", "masterpiece", "score_7", "best quality", "anime illustration")): score += 15
    if re.search(r"\b(agent\s*\d+|analyzing|suggested tags|image analysis|proposed output prompt|final suggested one-line prompt)\b", low): score -= 15
    # Prefer concise one-line prompts, not huge transcripts.
    if len(line) > 1800: score -= 20
    if len(line) < 60: score -= 20
    return score


def _without_reasoning_blocks(text):
    cleaned = re.sub(r"(?is)<think>.*?</think>", "\n", str(text or ""))
    return re.sub(r"(?is)<think[^>]*>.*\Z", "\n", cleaned)


def _extract_prompt_candidates(text):
    """Return prompt-like candidates from raw model output, including multi-agent traces."""
    candidates = []
    if not text:
        return candidates
    src = html.unescape(str(text)).replace("\r\n", "\n").replace("\r", "\n")

    # Preserve the content after the final closed think block as a strong candidate area.
    low = src.lower()
    if "</think>" in low:
        idx = low.rfind("</think>")
        tail = _without_reasoning_blocks(src[idx + len("</think>"):]).strip()
        if tail:
            candidates.append((tail, True))

    visible = _without_reasoning_blocks(src)

    # Extract explicit labeled prompt fragments, including Agent N lines.
    label_pat = re.compile(
        r"(?is)(?:^|\n|>)\s*(?:\*\*\s*)?(?:agent\s*\d+\s*(?:说|says?)\s*:\s*)?"
        r"(?:\*\*\s*)?(final\s+suggested\s+one[-\s]*line\s+prompt|final\s+one[-\s]*line\s+prompt|final\s+proposed\s+prompt(?:\s+for\s+anima)?|final\s+prompt|positive\s+prompt|final\s+clip|polished\s+output\s+ready|refined\s+for\s+two\s+statements|proposed\s+output\s+prompt|proposed\s+full\s+single[-\s]*line\s+output|proposed\s+output\s+line)"
        r"\s*[:：-]\s*(.+?)(?=\n\s*(?:>|\*\*?\s*agent\s*\d+|[A-Z][A-Za-z ]{3,40}\s*>|Finalizing|Generating|Constructing|Crafting|Compiling|Refining|</think>|$))"
    )
    for m in label_pat.finditer(visible):
        candidates.append((m.group(2).strip(), True))

    # Remove code fences for line-based extraction after reasoning blocks are gone.
    cleaned = visible
    cleaned = re.sub(r"(?is)```(?:\w+)?\s*|```", "\n", cleaned)

    for raw_line in cleaned.split("\n"):
        line = _remove_agent_prefix(raw_line)
        line = _strip_known_prefix(line)
        if _looks_like_prompt(line):
            candidates.append((line, False))

    # Also split by common Agent markers inside a single unbroken line.
    chunks = re.split(r"(?is)>\s*\*\*\s*agent\s*\d+\s*\*\*\s*(?:说|says?)\s*:\s*", src)
    for c in chunks:
        if c not in visible:
            continue
        c = _strip_known_prefix(c)
        if _looks_like_prompt(c):
            candidates.append((c, False))

    return candidates


def clean_model_output(raw):
    """Best-effort cleanup for reasoning/multi-agent wrappers returned by some APIs.

    V16 is stricter than V14: it treats `Agent 1/2/3` blocks as a transcript and
    extracts only the final prompt-like line. The raw API response is still kept
    as raw_text in debug_json.
    """
    if raw is None:
        return ""
    s0 = html.unescape(str(raw)).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s0:
        return ""
    if s0.lower().lstrip().startswith(("[error]", "[timeout]", "[skipped]")):
        return s0

    candidates = _extract_prompt_candidates(s0)
    if candidates:
        # Choose the best explicit/final prompt candidate. If scores tie, prefer the last candidate.
        best = None
        best_score = -1000
        for idx, (cand, final_hint) in enumerate(candidates):
            cand = _strip_known_prefix(cand)
            cand = re.sub(r"(?is)<think>.*?</think>", " ", cand)
            cand = re.sub(r"(?is)</?think[^>]*>", " ", cand)
            cand = re.sub(r"(?is)```(?:\w+)?\s*|```", " ", cand)
            cand = re.sub(r"\s*\n\s*", " ", cand)
            cand = re.sub(r"\s{2,}", " ", cand).strip()
            cand = re.sub(r"(?i)^\s*(?:agent\s*\d+\s*(?:说|says?)\s*:\s*)+", "", cand).strip()
            score = _score_prompt_candidate(cand, final_hint=final_hint) + idx * 0.01
            if score <= -999 and not final_hint:
                continue
            if score > best_score:
                best_score = score
                best = cand
        if best:
            s = best
        else:
            s = _without_reasoning_blocks(s0)
    else:
        s = _without_reasoning_blocks(s0)

    # Final cleanup: remove residual agent/meta prefixes and collapse to one line.
    s = _remove_agent_prefix(s)
    s = _strip_known_prefix(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"[#`]+", "", s)
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = re.sub(r"(?i)^(tags?|key tags?|danbooru tags?)\s*[:：]\s*", "", s).strip()
    # If labels still survived, remove them once more.
    s = _strip_known_prefix(s)
    return s

def send_status(node_id, status):
    if PromptServer is None:
        return
    try:
        PromptServer.instance.send_sync(
            "tb_multi_api_caption_v16_status",
            {"node_id": str(node_id), "status": status}
        )
    except Exception:
        pass


async def fetch_models_for_provider(provider):
    if aiohttp is None:
        return {"ok": False, "error": "aiohttp is not available", "models": []}
    protocol = normalize_protocol(provider)
    base_url = (provider.get("base_url") or "").rstrip("/")
    endpoint = provider.get("models_endpoint") or "/models"
    url = _join_url(base_url, endpoint)
    headers = _auth_headers(provider, protocol)
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as resp:
            raw = await resp.text()
            if resp.status >= 400:
                return {"ok": False, "error": f"HTTP {resp.status}: {raw[:1000]}", "models": []}
            try:
                data = json.loads(raw)
            except Exception:
                return {"ok": False, "error": "Invalid JSON from models endpoint", "models": []}

    models = []
    candidates = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            candidates = data["data"]
        elif isinstance(data.get("models"), list):
            candidates = data["models"]
    elif isinstance(data, list):
        candidates = data

    for item in candidates:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
        else:
            model_id = None
        if model_id:
            model_id = str(model_id)
            if protocol == "gemini_generate_content" and model_id.startswith("models/"):
                model_id = model_id[len("models/"):]
            models.append(model_id)
    models = sorted(set(models))
    return {"ok": True, "models": models, "protocol": protocol, "url": url}


def run_async_in_new_thread(coro_factory):
    box = {"ok": False, "value": None, "error": None}

    def target():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            box["value"] = loop.run_until_complete(coro_factory())
            box["ok"] = True
        except Exception as e:
            box["error"] = e
            box["traceback"] = traceback.format_exc()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()
    if box["ok"]:
        return box["value"]
    raise box["error"]


async def call_multimodal_provider(slot, provider, model, image, system_prompt, user_prompt, timeout_seconds, temperature, max_tokens, node_id, status_state):
    started = time.perf_counter()
    status_state["models"][slot - 1].update({"status": "running", "seconds": None})
    send_status(node_id, status_state)

    protocol = normalize_protocol(provider)
    request_spec = None
    image_blob = None
    http_status = None
    try:
        effective = apply_model_overrides(provider, model)
        image_blob = image_to_blob(image, effective)
        request_spec = build_provider_request(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            image_blob=image_blob,
        )
        protocol = request_spec["protocol"]
        timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                request_spec["url"],
                headers=request_spec["headers"],
                json=request_spec["payload"],
            ) as resp:
                http_status = resp.status
                raw = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}: {raw[:1500]}")
                try:
                    data = json.loads(raw)
                except Exception:
                    raise RuntimeError(f"Invalid JSON response: {raw[:1500]}")

        parsed_response = parse_provider_response(protocol, data)
        raw_text = str(parsed_response.get("text") or "")
        text = clean_model_output(raw_text)
        missing_image = response_reports_missing_image(text)
        refusal_text = str(parsed_response.get("refusal") or "").strip()
        text_refusal = response_reports_refusal(text)
        finish_reason = str(parsed_response.get("finish_reason") or "").strip()
        finish_key = re.sub(r"[\s-]+", "_", finish_reason.lower())
        response_status = str(parsed_response.get("response_status") or "").strip()
        status_key = re.sub(r"[\s-]+", "_", response_status.lower())
        blocked_reason = str(parsed_response.get("blocked_reason") or "").strip()
        blocked_key = re.sub(r"[\s-]+", "_", blocked_reason.lower())
        fail_on_missing = request_spec["provider"].get("fail_on_missing_image", True)

        elapsed = round(time.perf_counter() - started, 3)
        result = {
            "slot": slot,
            "enabled": True,
            "provider": provider.get("name", ""),
            "model": model,
            "protocol": protocol,
            "http_status": http_status,
            "seconds": elapsed,
            "text": text,
            "raw_text": raw_text,
            "finish_reason": finish_reason or None,
            "response_status": response_status or None,
            "blocked_reason": blocked_reason or None,
            "request_url": request_spec["url"],
            "image_order": request_spec.get("image_order"),
            "image": {k: v for k, v in image_blob.items() if k != "base64"},
        }
        filtered_reasons = {
            "content_filter", "content_filtered", "safety", "blocked", "recitation",
            "prohibited_content", "sensitive", "image_safety",
        }
        truncated_reasons = {"length", "max_tokens", "max_output_tokens", "incomplete"}
        tool_reasons = {"tool_calls", "tool_call", "function_call", "tool_use"}
        provider_error = parsed_response.get("provider_error")

        if parsed_response.get("invalid_response"):
            result.update({
                "status": "error",
                "error_kind": "invalid_response",
                "error": str(provider_error or "Provider returned an invalid response structure")[:1000],
            })
        elif provider_error:
            detail = json.dumps(provider_error, ensure_ascii=False) if isinstance(provider_error, (dict, list)) else str(provider_error)
            result.update({
                "status": "error",
                "error_kind": "provider_error",
                "error": detail[:1000],
            })
        elif refusal_text or blocked_key or finish_key in filtered_reasons or status_key in filtered_reasons:
            reason = refusal_text or blocked_reason or finish_reason or response_status or "Provider refused the request"
            result.update({
                "status": "error",
                "error_kind": "refusal" if refusal_text else "filtered",
                "error": reason[:1000],
            })
        elif finish_key in truncated_reasons or status_key == "incomplete":
            result.update({
                "status": "error",
                "error_kind": "truncated",
                "error": f"Provider response was incomplete: {finish_reason or response_status}",
            })
        elif parsed_response.get("tool_calls") and (not text or finish_key in tool_reasons):
            result.update({
                "status": "error",
                "error_kind": "unsupported_response",
                "error": "Provider returned a tool call instead of a caption",
            })
        elif text_refusal:
            result.update({
                "status": "error",
                "error_kind": "refusal",
                "error": text[:1000],
            })
        elif missing_image and fail_on_missing:
            result.update({
                "status": "no_image",
                "error_kind": "missing_image",
                "error": "Model response indicates that the image was not received",
            })
        elif not text:
            result.update({
                "status": "error",
                "error_kind": "empty_response",
                "error": "Provider returned no usable text",
            })
        else:
            result["status"] = "success"

        status_state["models"][slot - 1].update(result)
        send_status(node_id, status_state)
        return result

    except asyncio.TimeoutError:
        elapsed = round(time.perf_counter() - started, 3)
        result = {
            "slot": slot,
            "enabled": True,
            "provider": provider.get("name", ""),
            "model": model,
            "protocol": protocol,
            "status": "timeout",
            "seconds": elapsed,
            "error": f"Timeout after {timeout_seconds}s",
            "text": f"[TIMEOUT] {model} after {timeout_seconds}s",
        }
        if image_blob:
            result["image"] = {k: v for k, v in image_blob.items() if k != "base64"}
        status_state["models"][slot - 1].update(result)
        send_status(node_id, status_state)
        return result
    except Exception as e:
        elapsed = round(time.perf_counter() - started, 3)
        result = {
            "slot": slot,
            "enabled": True,
            "provider": provider.get("name", ""),
            "model": model,
            "protocol": protocol,
            "status": "error",
            "seconds": elapsed,
            "error": f"{type(e).__name__}: {e}",
            "text": f"[ERROR] {model}: {type(e).__name__}: {e}",
        }
        if http_status is not None:
            result["http_status"] = http_status
        if request_spec:
            result["request_url"] = request_spec.get("url")
            result["image_order"] = request_spec.get("image_order")
        if image_blob:
            result["image"] = {k: v for k, v in image_blob.items() if k != "base64"}
        status_state["models"][slot - 1].update(result)
        send_status(node_id, status_state)
        return result


def infer_requested_slots(prompt, unique_id):
    """
    If the current prompt contains consumers of this node's result_N outputs,
    run those slots only. If consumers reference aggregate outputs or there are
    no consumers, run all enabled slots.

    Output index map:
      0-4 result_1..result_5
      5 successful_results
      6 status_report
      7 debug_json
    """
    if not prompt or unique_id is None:
        return None, "no_prompt_run_all_enabled"

    uid = str(unique_id)
    result_slots = set()
    aggregate_requested = False
    consumer_count = 0

    try:
        for nid, node in prompt.items():
            if str(nid) == uid:
                continue
            inputs = (node or {}).get("inputs", {})
            for val in inputs.values():
                # Comfy prompt input link usually: [source_node_id, output_index]
                if isinstance(val, list) and len(val) >= 2 and str(val[0]) == uid:
                    consumer_count += 1
                    try:
                        out_idx = int(val[1])
                    except Exception:
                        continue
                    if 0 <= out_idx <= 4:
                        result_slots.add(out_idx + 1)
                    else:
                        aggregate_requested = True
                # Some custom nodes may nest inputs
                elif isinstance(val, dict):
                    for vv in val.values():
                        if isinstance(vv, list) and len(vv) >= 2 and str(vv[0]) == uid:
                            consumer_count += 1
                            try:
                                out_idx = int(vv[1])
                            except Exception:
                                continue
                            if 0 <= out_idx <= 4:
                                result_slots.add(out_idx + 1)
                            else:
                                aggregate_requested = True
    except Exception:
        return None, "parse_failed_run_all_enabled"

    if aggregate_requested:
        return None, "aggregate_output_run_all_enabled"
    if result_slots:
        return sorted(result_slots), "downstream_result_outputs"
    if consumer_count == 0:
        return None, "node_itself_run_all_enabled"
    return None, "fallback_run_all_enabled"




def parse_requested_slots_value(value):
    """
    Frontend can set requested_slots before queue.
    Returns (target_slots, reason). target_slots None means run all enabled.
    target_slots [] means run nothing.
    """
    if value is None:
        return None, "requested_slots_auto"
    text = str(value).strip().lower()
    if not text or text == "auto":
        return None, "requested_slots_auto"
    if text in ("all", "*"):
        return None, "frontend_requested_all"
    if text in ("none", "skip", "skipped"):
        return [], "frontend_requested_none"
    slots = []
    for part in text.replace(";", ",").replace("|", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("slot_"):
            part = part[5:]
        if part.startswith("slot"):
            part = part[4:]
        try:
            n = int(part)
        except Exception:
            continue
        if 1 <= n <= 5 and n not in slots:
            slots.append(n)
    if slots:
        return slots, "frontend_requested_slots"
    return None, "requested_slots_unparsed_run_all_enabled"

class TB_Multi_API_Caption_SmartRunner_V16:
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        providers = provider_names()
        # Use first provider's models as initial choices; JS will update dynamically.
        first = providers[0]
        models = models_for_provider(first)
        required = {
            "image": ("IMAGE",),
            "system_prompt": ("STRING", {
                "default": "You are an Anima prompt generator. Return the final prompt only. Never reveal chain of thought, hidden reasoning, agent dialogue, markdown, headings, citations, analysis, tables, or explanations.",
                "multiline": True
            }),
            "user_prompt": ("STRING", {
                "default": "Analyze the input image and output exactly one single-line Anima hybrid prompt. Format: comma-separated anime tags first, then two concise natural-language English sentences on the same line. Output only that final line. No markdown. No headings. No bullets. No <think>. No Agent messages. No analysis. No citations. No extra line breaks.",
                "multiline": True
            }),
        }
        for i in range(1, 6):
            required[f"enable_{i}"] = ("BOOLEAN", {"default": i <= 3})
            required[f"slot_{i}_provider"] = (providers,)
            required[f"slot_{i}_model"] = (models,)
        required.update({
            "requested_slots": ("STRING", {"default": "auto", "multiline": False}),
            "accumulate_results": ("BOOLEAN", {"default": True}),
            "timeout_seconds": ("INT", {"default": 180, "min": 10, "max": 900, "step": 10}),
            "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 2.0, "step": 0.05}),
            "max_tokens": ("INT", {"default": 2048, "min": 128, "max": 32000, "step": 128}),
            "force_always_run": ("BOOLEAN", {"default": False}),
            "run_id": ("INT", {"default": 1, "min": 0, "max": 999999999, "step": 1}),
        })
        return {
            "required": required,
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("result_1", "result_2", "result_3", "result_4", "result_5", "successful_results", "status_report", "debug_json")
    FUNCTION = "run"
    CATEGORY = "TB/API"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get("force_always_run"):
            return float("nan")
        # Stable cache marker. Downstream layout/widget edits must not invalidate this API node.
        # The full workflow PROMPT is deliberately excluded because it changes when downstream UI changes.
        data = {k: v for k, v in kwargs.items() if k not in ("prompt", "unique_id")}
        if "image" in data:
            data["image"] = image_fingerprint(data["image"])
        return stable_json_fingerprint(data)

    def run(self, image, system_prompt, user_prompt,
            enable_1, slot_1_provider, slot_1_model,
            enable_2, slot_2_provider, slot_2_model,
            enable_3, slot_3_provider, slot_3_model,
            enable_4, slot_4_provider, slot_4_model,
            enable_5, slot_5_provider, slot_5_model,
            requested_slots, accumulate_results, timeout_seconds, temperature, max_tokens, force_always_run, run_id,
            unique_id=None, prompt=None):

        start_all = time.perf_counter()
        parsed_slots, parsed_reason = parse_requested_slots_value(requested_slots)
        if str(requested_slots or "").strip().lower() in ("", "auto"):
            target_slots, target_reason = infer_requested_slots(prompt, unique_id)
        else:
            target_slots, target_reason = parsed_slots, parsed_reason

        slot_data = [
            {"slot": 1, "enable": enable_1, "provider_name": slot_1_provider, "model": slot_1_model},
            {"slot": 2, "enable": enable_2, "provider_name": slot_2_provider, "model": slot_2_model},
            {"slot": 3, "enable": enable_3, "provider_name": slot_3_provider, "model": slot_3_model},
            {"slot": 4, "enable": enable_4, "provider_name": slot_4_provider, "model": slot_4_model},
            {"slot": 5, "enable": enable_5, "provider_name": slot_5_provider, "model": slot_5_model},
        ]

        image_sig = image_fingerprint(image)
        cache_before = get_runner_cache(unique_id) if accumulate_results else {}

        status_state = {
            "overall_status": "running",
            "target_reason": target_reason,
            "target_slots": target_slots if target_slots is not None else "all_enabled",
            "total_seconds": None,
            "models": []
        }

        initial_results = []
        tasks_specs = []
        attempted_slots = set()
        expected_signature_by_slot = {}
        for s in slot_data:
            slot = s["slot"]
            selected_by_output = target_slots is not None and slot in target_slots
            should_run = selected_by_output or (target_slots is None and bool(s["enable"]))
            if should_run:
                attempted_slots.add(slot)
            provider = get_provider(s["provider_name"])
            model = s["model"]
            input_signature = None
            if provider and provider.get("name") != "<none>" and model and model != "<manual>":
                input_signature = runner_slot_signature(
                    image_sig=image_sig,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    slot=slot,
                    provider=provider,
                    model=model,
                    timeout_seconds=timeout_seconds,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                expected_signature_by_slot[slot] = input_signature

            if not should_run:
                item = {
                    "slot": slot,
                    "enabled": bool(s["enable"]),
                    "provider": s["provider_name"],
                    "model": model,
                    "status": "skipped",
                    "seconds": 0,
                    "text": f"[SKIPPED] slot {slot} not requested"
                }
                initial_results.append(item)
                status_state["models"].append(dict(item))
                continue

            if not provider or provider.get("name") == "<none>":
                item = {
                    "slot": slot,
                    "enabled": bool(s["enable"]),
                    "provider": s["provider_name"],
                    "model": model,
                    "status": "error",
                    "seconds": 0,
                    "error": "Provider not found",
                    "text": f"[ERROR] slot {slot}: provider not found"
                }
                initial_results.append(item)
                status_state["models"].append(dict(item))
                continue

            if not model or model == "<manual>":
                item = {
                    "slot": slot,
                    "enabled": bool(s["enable"]),
                    "provider": s["provider_name"],
                    "model": model,
                    "status": "skipped",
                    "seconds": 0,
                    "text": f"[SKIPPED] slot {slot}: no model selected"
                }
                initial_results.append(item)
                status_state["models"].append(dict(item))
                continue

            cached = cache_before.get(slot) if accumulate_results and not force_always_run else None
            if (cached and cached.get("input_signature") == input_signature
                    and cached.get("run_id") == int(run_id)):
                item = dict(cached)
                item.update({
                    "slot": slot,
                    "enabled": bool(s["enable"]),
                    "provider": s["provider_name"],
                    "model": model,
                    "status": "success",
                    "source": "cache",
                    "seconds": item.get("seconds", 0),
                })
                initial_results.append(item)
                status_state["models"].append(dict(item))
                continue

            placeholder = {
                "slot": slot,
                "enabled": bool(s["enable"]),
                "provider": s["provider_name"],
                "model": model,
                "status": "queued",
                "seconds": None,
                "text": ""
            }
            initial_results.append(placeholder)
            status_state["models"].append(dict(placeholder))
            tasks_specs.append((slot, provider, model, input_signature))

        send_status(unique_id, status_state)

        async def runner():
            if aiohttp is None:
                # Mark all queued as error
                out = []
                for item in initial_results:
                    if item["status"] == "queued":
                        item = dict(item)
                        item.update({"status": "error", "seconds": 0, "error": "aiohttp not available", "text": "[ERROR] aiohttp not available"})
                    out.append(item)
                return out

            tasks = {}
            signature_by_slot = {}
            for slot, provider, model, input_signature in tasks_specs:
                signature_by_slot[slot] = input_signature
                task = call_multimodal_provider(
                    slot=slot,
                    provider=provider,
                    model=model,
                    image=image,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    timeout_seconds=timeout_seconds,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    node_id=unique_id,
                    status_state=status_state
                )
                tasks[slot] = asyncio.create_task(task)

            completed_by_slot = {}
            if tasks:
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                for slot, result in zip(tasks.keys(), results):
                    if isinstance(result, Exception):
                        completed_by_slot[slot] = {
                            "slot": slot,
                            "status": "error",
                            "seconds": None,
                            "error": f"{type(result).__name__}: {result}",
                            "text": f"[ERROR] slot {slot}: {type(result).__name__}: {result}"
                        }
                    else:
                        result = dict(result)
                        result["input_signature"] = signature_by_slot.get(slot)
                        result["run_id"] = int(run_id)
                        completed_by_slot[slot] = result

            final = []
            for item in initial_results:
                if item["slot"] in completed_by_slot:
                    final.append(completed_by_slot[item["slot"]])
                else:
                    final.append(item)
            return final

        current_results = run_async_in_new_thread(runner)

        # Optional accumulated result memory:
        # - Requested slots update their cache on success and clear stale cache on failure.
        # - Non-requested enabled slots can contribute their latest cached success.
        # - Disabled slots are not included from cache unless they were explicitly requested this run.
        results = []
        enabled_by_slot = {s["slot"]: bool(s["enable"]) for s in slot_data}

        for item in current_results:
            slot = int(item.get("slot", 0) or 0)
            is_attempted = slot in attempted_slots
            item = dict(item)

            if accumulate_results and is_attempted:
                if item.get("status") == "success" and item.get("source") == "cache":
                    results.append(item)
                    continue
                if item.get("status") == "success":
                    item["source"] = "current"
                    update_runner_cache(unique_id, slot, item)
                else:
                    # A fresh failed attempt should not silently leave stale data in the judge input.
                    remove_runner_cache_slot(unique_id, slot)
                results.append(item)
                continue

            expected_signature = expected_signature_by_slot.get(slot)
            if (accumulate_results and not is_attempted and enabled_by_slot.get(slot, False)
                    and slot in cache_before and expected_signature
                    and cache_before[slot].get("input_signature") == expected_signature):
                cached = dict(cache_before[slot])
                cached["slot"] = slot
                cached["status"] = "success"
                cached["source"] = "cache"
                cached.setdefault("seconds", 0)
                results.append(cached)
            else:
                if (accumulate_results and not is_attempted and enabled_by_slot.get(slot, False)
                        and slot in cache_before):
                    remove_runner_cache_slot(unique_id, slot)
                results.append(item)

        cache_after = get_runner_cache(unique_id) if accumulate_results else {}

        total_seconds = round(time.perf_counter() - start_all, 3)
        success = [r for r in results if r.get("status") == "success"]
        errors = [r for r in results if r.get("status") in ("error", "timeout", "no_image")]
        skipped = [r for r in results if r.get("status") == "skipped"]

        debug = {
            "plugin_version": PLUGIN_VERSION,
            "overall_status": "finished",
            "target_reason": target_reason,
            "target_slots": target_slots if target_slots is not None else "all_enabled",
            "accumulate_results": bool(accumulate_results),
            "force_always_run": bool(force_always_run),
            "run_id": int(run_id),
            "attempted_slots": sorted(attempted_slots),
            "cache_slots": sorted(int(k) for k in cache_after.keys()),
            "total_seconds": total_seconds,
            "success_count": len(success),
            "failed_count": len(errors),
            "skipped_count": len(skipped),
            "models": results
        }
        send_status(unique_id, debug)

        texts = []
        for r in results:
            texts.append(r.get("text") or "")
        while len(texts) < 5:
            texts.append("")

        successful_results = json.dumps(success, ensure_ascii=False, indent=2)

        lines = [
            f"Overall: finished | target={debug['target_slots']} | reason={target_reason} | total {total_seconds}s | success {len(success)} | failed {len(errors)} | skipped {len(skipped)}"
        ]
        for r in results:
            if r.get("status") == "success" and r.get("source") == "cache":
                mark = "CACHED"
            else:
                mark = {"success": "OK", "error": "ERR", "timeout": "TIMEOUT", "no_image": "NOIMG", "skipped": "SKIP", "queued": "QUEUE"}.get(r.get("status"), r.get("status"))
            lines.append(f"slot {r.get('slot')}: {mark} | {r.get('seconds')}s | {r.get('provider')} | {r.get('model')}")
            if r.get("error"):
                lines.append(f"  error: {r.get('error')}")
        status_report = "\n".join(lines)
        debug_json = json.dumps(debug, ensure_ascii=False, indent=2)

        return (texts[0], texts[1], texts[2], texts[3], texts[4], successful_results, status_report, debug_json)


class TB_Build_Anima_Judge_Prompt_V16:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "successful_results": ("STRING", {"multiline": True, "default": ""}),
                "extra_instruction": ("STRING", {
                    "multiline": True,
                    "default": "Generate a final Anima hybrid prompt. Use only successful model results. Keep the final prompt one line."
                })
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("judge_prompt",)
    FUNCTION = "run"
    CATEGORY = "TB/API"

    def run(self, successful_results, extra_instruction):
        prompt = f"""You are an Anima prompt judge and merger.

You will receive multiple successful vision-model outputs for the same image.

Rules:
1. Use only the provided successful results.
2. Keep visual elements confirmed by multiple models.
3. Down-rank details that appear in only one model unless they are clearly important.
4. Remove conflicts and do not invent character names, series names, or artist names.
5. Create an Anima-friendly hybrid prompt: a few anime tags first, followed by at least two natural-language English sentences.
6. Normal tags use lowercase words and spaces, not underscores. score_7 keeps its underscore.
7. The positive prompt should start with: masterpiece, best quality, score_7, safe,

Output:
【Model Comparison CN】
【Final Anima Positive Prompt】
【Final Negative Prompt】
【Final CLIP】

Extra instruction:
{extra_instruction}

Successful model results JSON:
{successful_results}
"""
        return (prompt,)



def _build_anima_judge_prompt_from_results(successful_results, extra_instruction):
    return f"""You are an Anima prompt judge and merger.

You will receive multiple successful vision-model outputs for the same image.

Rules:
1. Use only the provided successful model results.
2. Keep visual elements confirmed by multiple models.
3. Down-rank details that appear in only one model unless they are clearly important.
4. Remove conflicts and do not invent character names, series names, or artist names.
5. Create an Anima-friendly hybrid prompt: a few anime tags first, followed by at least two natural-language English sentences.
6. Normal tags use lowercase words and spaces, not underscores. score_7 keeps its underscore.
7. The positive prompt should start with: masterpiece, best quality, score_7, safe,
8. If only one model result is available, state in the Chinese comparison that cross-model verification was not possible, then still generate a usable prompt.
9. If no successful result is available, output a failure explanation and do not invent a prompt.

Output:
【Model Comparison CN】
【Final Anima Positive Prompt】
【Final Negative Prompt】
【Final CLIP】

Extra instruction:
{extra_instruction}

Successful model results JSON:
{successful_results}
"""


def _collect_results_from_result_slots(result_items, status_report=""):
    """
    Convert individual result_1..result_5 strings into the same JSON shape as successful_results.
    Empty strings and obvious skipped/error strings are ignored.
    """
    successes = []
    for i, text in enumerate(result_items, start=1):
        text = (text or "").strip()
        if not text:
            continue
        lower = text.lower()
        if lower.startswith("[skipped]") or lower.startswith("[error]") or lower.startswith("[timeout]"):
            continue
        successes.append({
            "slot": i,
            "status": "success",
            "seconds": None,
            "text": text
        })
    return json.dumps({
        "source": "individual_result_inputs",
        "status_report": status_report or "",
        "results": successes
    }, ensure_ascii=False, indent=2)


class TB_Build_Anima_Judge_Prompt_MultiInput_V16:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "result_1": ("STRING", {"multiline": True, "default": ""}),
                "result_2": ("STRING", {"multiline": True, "default": ""}),
                "result_3": ("STRING", {"multiline": True, "default": ""}),
                "result_4": ("STRING", {"multiline": True, "default": ""}),
                "result_5": ("STRING", {"multiline": True, "default": ""}),
                "status_report": ("STRING", {"multiline": True, "default": ""}),
                "extra_instruction": ("STRING", {
                    "multiline": True,
                    "default": "Generate a final Anima hybrid prompt. Use only successful model results. Keep the final prompt one line."
                })
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("judge_prompt",)
    FUNCTION = "run"
    CATEGORY = "TB/API"

    def run(self, result_1, result_2, result_3, result_4, result_5, status_report, extra_instruction):
        successful_results = _collect_results_from_result_slots(
            [result_1, result_2, result_3, result_4, result_5],
            status_report=status_report
        )
        return (_build_anima_judge_prompt_from_results(successful_results, extra_instruction),)




# ---------------- API Judge Node ----------------

DEFAULT_ANIMA_NEGATIVE = (
    "worst quality, low quality, score_1, score_2, score_3, artist name, "
    "lowres, blurry, jpeg artifacts, bad anatomy, bad hands, extra fingers, missing fingers, "
    "fused fingers, malformed hands, extra arms, extra legs, deformed body, bad face, "
    "asymmetrical eyes, watermark, text, logo, duplicate, cropped, out of frame"
)


def _normalize_successful_results_for_judge(successful_results, mode="raw_text_only"):
    """Prepare upstream outputs for the judge LLM.

    The runner keeps both:
      - text: best-effort preview / optional rule-cleaned text
      - raw_text: original model response, including <think>, Agent transcripts, labels, etc.

    V16 deliberately lets the judge LLM perform semantic cleanup and fusion.
    """
    raw = (successful_results or "").strip()
    if not raw:
        return "[]"
    try:
        data = json.loads(raw)
    except Exception:
        return raw

    if isinstance(data, dict):
        items = data.get("results") or data.get("models") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "success":
            continue
        raw_text = str(item.get("raw_text") or item.get("text") or "").strip()
        preview_text = str(item.get("text") or "").strip()
        entry = {
            "slot": item.get("slot"),
            "provider": item.get("provider"),
            "model": item.get("model"),
            "seconds": item.get("seconds"),
            "source": item.get("source", "current"),
        }
        if mode == "clean_text_only":
            entry["model_output"] = preview_text
        elif mode == "both_raw_and_preview":
            entry["raw_model_output"] = raw_text
            entry["preview_text"] = preview_text
        else:
            entry["raw_model_output"] = raw_text
        out.append(entry)
    return json.dumps(out, ensure_ascii=False, indent=2)


def _build_judge_user_prompt(successful_results, extra_instruction, judge_input_mode="raw_text_only"):
    prepared = _normalize_successful_results_for_judge(successful_results, judge_input_mode)
    return f"""You are an Anima prompt judge, transcript cleaner, and merger.

You will receive raw outputs from multiple vision models for the same image. Some outputs may contain multi-agent transcripts, <think> blocks, reasoning notes, labels such as Agent 1/2/3, Proposed prompt, Final prompt, or several candidate prompts. Treat all upstream model outputs as noisy raw material, not as final answers.

Input data:
{prepared}

Your task:
1. For each model output, internally clean it: ignore <think> blocks, hidden reasoning, Agent dialogue, markdown, citations, tables, and analysis prose.
2. Extract each model's best candidate prompt or visual facts. If several candidates exist, prefer the final/refined/polished candidate, but do not blindly trust one model.
3. Compare all successful model outputs. Keep visual elements confirmed by multiple models. Down-rank single-model details unless they are central and plausible.
4. Resolve conflicts. Do not invent character names, series names, artist names, or invisible details.
5. Generate one final Anima-friendly hybrid prompt.

Anima prompt rules:
1. Use a hybrid style: anime tags first, followed by natural-language English description.
2. Start the positive prompt with: masterpiece, best quality, score_7, safe,
3. Use lowercase normal tags with spaces, not underscores. Keep score_7 with the underscore.
4. The final positive prompt must be one line only.
5. The final negative prompt must be one line only.
6. If only one successful model result exists, say in Chinese that cross-model verification was not possible.
7. If no successful model result exists, return an empty positive prompt and explain the failure in Chinese.

Extra instruction:
{extra_instruction}

Return STRICT JSON only, no markdown, no code fence, with exactly these keys:
{{
  "model_comparison": "中文。说明每个模型输出质量、共同点、冲突点、哪些内容被保留/丢弃。",
  "final_positive_prompt": "one-line English Anima hybrid prompt",
  "final_negative_prompt": "one-line English negative prompt",
  "cn_review": "中文。说明最终提示词的主体、外观、服装、动作、场景、光影、风格、无法确认内容。"
}}
"""


def _extract_message_content(data):
    # Legacy helper retained for third-party imports; OpenAI Chat fallback.
    return extract_provider_text("openai_chat", data)


async def call_text_provider(provider, model, system_prompt, user_prompt, timeout_seconds, temperature, max_tokens):
    if aiohttp is None:
        raise RuntimeError("aiohttp is not available")
    request_spec = build_provider_request(
        provider=provider,
        model=model,
        system_prompt=system_prompt or "You are an Anima prompt judge and merger. Return strict JSON only.",
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        image_blob=None,
    )
    timeout = aiohttp.ClientTimeout(total=float(timeout_seconds))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            request_spec["url"],
            headers=request_spec["headers"],
            json=request_spec["payload"],
        ) as resp:
            raw = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {raw[:1500]}")
            try:
                data = json.loads(raw)
            except Exception:
                raise RuntimeError(f"Invalid JSON response: {raw[:1500]}")
    return extract_provider_text(request_spec["protocol"], data)


async def call_text_openai_compatible(provider, model, system_prompt, user_prompt, timeout_seconds, temperature, max_tokens):
    # Backward-compatible name; the implementation now supports every configured protocol.
    return await call_text_provider(
        provider, model, system_prompt, user_prompt,
        timeout_seconds, temperature, max_tokens,
    )


def _parse_judge_response(raw):
    result = {
        "model_comparison": "",
        "final_positive_prompt": "",
        "final_negative_prompt": DEFAULT_ANIMA_NEGATIVE,
        "cn_review": ""
    }
    text = (raw or "").strip()
    if not text:
        result["cn_review"] = "综合分析模型返回为空。"
        return result

    # Strip code fences if the model ignored JSON-only instruction.
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    # Try direct JSON, then JSON object substring.
    candidates = [text]
    a = text.find("{")
    b = text.rfind("}")
    if a != -1 and b != -1 and b > a:
        candidates.append(text[a:b+1])
    for c in candidates:
        try:
            data = json.loads(c)
            if isinstance(data, dict):
                for k in result:
                    if data.get(k):
                        result[k] = str(data.get(k)).strip()
                if not result["final_negative_prompt"]:
                    result["final_negative_prompt"] = DEFAULT_ANIMA_NEGATIVE
                return result
        except Exception:
            pass

    # Fallback: preserve raw response for review and try rough marker parsing.
    import re
    def grab(label):
        patterns = [
            rf"【{re.escape(label)}】\s*(.*?)(?=\n【|\Z)",
            rf"{re.escape(label)}\s*[:：]\s*(.*?)(?=\n[A-Z][A-Za-z ]+[:：]|\Z)",
        ]
        for pat in patterns:
            m = re.search(pat, raw, re.S)
            if m:
                return m.group(1).strip()
        return ""

    result["model_comparison"] = grab("Model Comparison CN") or grab("model_comparison")
    result["final_positive_prompt"] = grab("Final Anima Positive Prompt") or grab("final_positive_prompt") or ""
    result["final_negative_prompt"] = grab("Final Negative Prompt") or grab("final_negative_prompt") or DEFAULT_ANIMA_NEGATIVE
    result["cn_review"] = grab("CN Review") or grab("cn_review") or ("综合分析模型未返回标准 JSON，以下为原始内容：\n" + raw)
    return result


class TB_Anima_Prompt_Judge_API_V16:
    @classmethod
    def INPUT_TYPES(cls):
        providers = provider_names()
        first = providers[0]
        models = models_for_provider(first)
        return {
            "required": {
                "successful_results": ("STRING", {"multiline": True, "default": ""}),
                "judge_provider": (providers,),
                "judge_model": (models,),
                "judge_system_prompt": ("STRING", {
                    "multiline": True,
                    "default": "You are an expert Anima prompt judge and merger. Return strict JSON only."
                }),
                "extra_instruction": ("STRING", {
                    "multiline": True,
                    "default": "Generate the final Anima hybrid prompt. Use all raw successful model outputs as noisy evidence. The judge model should clean multi-agent/reasoning transcripts itself, compare the useful facts, and output final prompts only."
                }),
                "judge_input_mode": (["raw_text_only", "both_raw_and_preview", "clean_text_only"], {"default": "raw_text_only"}),
                "timeout_seconds": ("INT", {"default": 180, "min": 10, "max": 900, "step": 10}),
                "temperature": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 2.0, "step": 0.05}),
                "max_tokens": ("INT", {"default": 4096, "min": 512, "max": 32000, "step": 256}),
                "force_always_run": ("BOOLEAN", {"default": False}),
                "run_id": ("INT", {"default": 1, "min": 0, "max": 999999999, "step": 1}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("final_positive_prompt", "final_negative_prompt", "cn_review", "model_comparison", "raw_response", "judge_prompt", "status_report")
    FUNCTION = "run"
    CATEGORY = "TB/API"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if kwargs.get("force_always_run"):
            return float("nan")
        # Stable cache marker. Increase run_id manually when you intentionally want a fresh API call.
        data = {k: v for k, v in kwargs.items() if k != "unique_id"}
        return stable_json_fingerprint(data)

    def run(self, successful_results, judge_provider, judge_model, judge_system_prompt, extra_instruction, judge_input_mode,
            timeout_seconds, temperature, max_tokens, force_always_run, run_id, unique_id=None):
        started = time.perf_counter()
        provider = get_provider(judge_provider)
        if not provider or provider.get("name") == "<none>":
            msg = f"[ERROR] Judge provider not found: {judge_provider}"
            return ("", DEFAULT_ANIMA_NEGATIVE, msg, msg, msg, "", msg)
        if not judge_model or judge_model == "<manual>":
            msg = "[ERROR] Judge model is not selected. Add a model in the config page and select it."
            return ("", DEFAULT_ANIMA_NEGATIVE, msg, msg, msg, "", msg)

        # Validate successful_results enough to avoid hallucinating when all upstream calls failed.
        raw_results = (successful_results or "").strip()
        if not raw_results or raw_results in ("[]", "{}"):
            msg = "没有可用的成功模型结果；综合分析未执行。"
            return ("", DEFAULT_ANIMA_NEGATIVE, msg, msg, "", "", msg)

        judge_prompt = _build_judge_user_prompt(raw_results, extra_instruction, judge_input_mode=judge_input_mode)

        async def runner():
            return await call_text_openai_compatible(
                provider=provider,
                model=judge_model,
                system_prompt=judge_system_prompt,
                user_prompt=judge_prompt,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_tokens=max_tokens
            )

        try:
            raw_response = run_async_in_new_thread(runner)
            parsed = _parse_judge_response(raw_response)
            elapsed = round(time.perf_counter() - started, 3)
            status_report = f"Judge finished | {elapsed}s | {judge_provider} | {judge_model}"
            return (
                parsed.get("final_positive_prompt", ""),
                parsed.get("final_negative_prompt", DEFAULT_ANIMA_NEGATIVE),
                parsed.get("cn_review", ""),
                parsed.get("model_comparison", ""),
                raw_response,
                judge_prompt,
                status_report,
            )
        except asyncio.TimeoutError:
            elapsed = round(time.perf_counter() - started, 3)
            msg = f"[TIMEOUT] Judge model {judge_model} after {timeout_seconds}s | elapsed {elapsed}s"
            return ("", DEFAULT_ANIMA_NEGATIVE, msg, msg, msg, judge_prompt, msg)
        except Exception as e:
            elapsed = round(time.perf_counter() - started, 3)
            msg = f"[ERROR] Judge model {judge_model}: {type(e).__name__}: {e} | elapsed {elapsed}s"
            return ("", DEFAULT_ANIMA_NEGATIVE, msg, msg, msg, judge_prompt, msg)


# ---------------- Routes ----------------

def _register_routes():
    if PromptServer is None or web is None:
        return
    app = PromptServer.instance.app

    async def config_page(request):
        return web.Response(text=CONFIG_HTML_PATH.read_text(encoding="utf-8"), content_type="text/html")

    async def api_get_providers(request):
        return web.json_response(load_providers())

    async def api_save_providers(request):
        data = await request.json()
        if "providers" not in data or not isinstance(data["providers"], list):
            return web.json_response({"ok": False, "error": "Invalid providers JSON"}, status=400)
        _write_json(PROVIDERS_PATH, data)
        return web.json_response({"ok": True, "message": "providers.json saved"})

    async def api_fetch_models(request):
        body = await request.json()
        name = body.get("provider")
        provider = get_provider(name)
        if not provider:
            return web.json_response({"ok": False, "error": f"Provider not found: {name}", "models": []})
        try:
            result = await fetch_models_for_provider(provider)
            if result.get("ok"):
                cache = _read_json(CACHE_PATH, {"providers": {}})
                cache.setdefault("providers", {})[name] = result.get("models", [])
                _write_json(CACHE_PATH, cache)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"{type(e).__name__}: {e}", "models": []})

    async def api_clear_cache(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        node_id = body.get("node_id")
        if node_id in (None, "", "all", "*"):
            clear_runner_cache(None)
            return web.json_response({"ok": True, "cleared": "all"})
        clear_runner_cache(node_id)
        return web.json_response({"ok": True, "cleared": str(node_id)})

    routes = [
        ("GET", "/tb_multi_api_caption_v16/config", config_page),
        ("GET", "/tb_multi_api_caption_v16/api/providers", api_get_providers),
        ("POST", "/tb_multi_api_caption_v16/api/providers", api_save_providers),
        ("POST", "/tb_multi_api_caption_v16/api/fetch_models", api_fetch_models),
        ("POST", "/tb_multi_api_caption_v16/api/clear_cache", api_clear_cache),
    ]

    existing = set()
    try:
        for r in app.router.routes():
            try:
                existing.add((r.method, r.resource.canonical))
            except Exception:
                pass
    except Exception:
        pass

    for method, path, handler in routes:
        try:
            if (method, path) in existing:
                continue
            if method == "GET":
                app.router.add_get(path, handler)
            elif method == "POST":
                app.router.add_post(path, handler)
        except Exception:
            pass


_register_routes()


NODE_CLASS_MAPPINGS = {
    "TB_Multi_API_Caption_SmartRunner_V16": TB_Multi_API_Caption_SmartRunner_V16,
    "TB_Build_Anima_Judge_Prompt_V16": TB_Build_Anima_Judge_Prompt_V16,
    "TB_Build_Anima_Judge_Prompt_MultiInput_V16": TB_Build_Anima_Judge_Prompt_MultiInput_V16,
    "TB_Anima_Prompt_Judge_API_V16": TB_Anima_Prompt_Judge_API_V16,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TB_Multi_API_Caption_SmartRunner_V16": "TB Multi API Caption Runner · 多供应商视觉适配版 V17",
    "TB_Build_Anima_Judge_Prompt_V16": "TB Build Anima Judge Prompt · JSON综合版",
    "TB_Build_Anima_Judge_Prompt_MultiInput_V16": "TB Build Anima Judge Prompt · 多输入综合版",
    "TB_Anima_Prompt_Judge_API_V16": "TB Anima Prompt Judge · 多协议融合 V17",
}
