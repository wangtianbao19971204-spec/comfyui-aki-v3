from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from .config import load_json


class VLMError(RuntimeError):
    pass


def _resolve_api_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("env:"):
        return os.environ.get(text[4:].strip(), "")
    return text


def _provider(config_path: Path, name: str, model: str) -> dict[str, Any]:
    data = load_json(config_path)
    for provider in data.get("providers", []):
        if provider.get("name") != name:
            continue
        result = deepcopy(provider)
        for rule in result.pop("model_overrides", []) or []:
            pattern = str(rule.get("match") or "")
            if pattern and re.search(pattern, model, re.IGNORECASE):
                result.update(rule.get("set") or {})
                break
        return result
    raise VLMError(f"LLM provider 不存在: {name}")


def _image_data_url(path: Path, max_dimension: int = 1400) -> str:
    with Image.open(path) as source:
        image = source.convert("RGB")
        if max(image.size) > max_dimension:
            image.thumbnail(
                (max_dimension, max_dimension),
                Image.Resampling.LANCZOS,
            )
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict)
            )
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    raise VLMError("LLM 返回中没有可读取的文本")


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise VLMError(f"LLM 未返回 JSON: {cleaned[:500]}")
        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            raise VLMError(f"LLM JSON 解析失败: {cleaned[:800]}") from exc
        if not isinstance(value, dict):
            raise VLMError("LLM JSON 根对象不是 object")
        return value


SYSTEM_PROMPT = """You are a strict character-dataset curator.
Compare the candidate image with the reference images and the supplied visual constitution.
Judge observable facts only. A beautiful image is not acceptable if identity, adult age
presentation, body proportions, hair structure, outfit construction, or required equipment
is wrong. Apply age and anatomy rules species-specifically: when the constitution defines an
adult Lalafell or another youthful-looking fantasy race, a large head, very short limbs,
round youthful face, and small body are required adult racial traits, not evidence that the
character is a human child. Judge adult identity from demeanor, clothing, role, and context.
Penalize normal adult-human proportions, long legs, a curvy hourglass body, or a mature
human facial structure when they contradict the supplied racial constitution. The
EXPECTED VARIABLE CONTENT for the current job overrides default outfit and equipment
states in the constitution. Do not penalize an absent weapon, holster, accessory, or default
garment when the current expected content explicitly makes it absent or optional. Return
strict JSON only. Do not include markdown or hidden reasoning."""


def score_candidate(
    llm_config: dict[str, Any],
    *,
    candidate: Path,
    references: list[Path],
    visual_spec: dict[str, Any],
    expected: dict[str, Any],
    trigger_token: str,
) -> dict[str, Any]:
    provider = _provider(
        Path(llm_config["provider_config"]),
        llm_config["provider"],
        llm_config["model"],
    )
    protocol = str(provider.get("protocol") or "openai_chat")
    if protocol != "openai_chat":
        raise VLMError(
            f"当前自动筛图仅支持 openai_chat provider，实际为 {protocol}"
        )
    if provider.get("supports_vision") is False:
        raise VLMError("所选 provider 被标记为不支持视觉")

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "REFERENCE IMAGES follow. They define identity, not background or pose."
            ),
        }
    ]
    for index, reference in enumerate(references, 1):
        content.append({"type": "text", "text": f"REFERENCE {index}"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(
                        reference,
                        int(llm_config.get("max_image_dimension", 1400)),
                    ),
                    "detail": llm_config.get("image_detail", "high"),
                },
            }
        )
    content.extend(
        [
            {"type": "text", "text": "CANDIDATE IMAGE"},
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(
                        candidate,
                        int(llm_config.get("max_image_dimension", 1400)),
                    ),
                    "detail": llm_config.get("image_detail", "high"),
                },
            },
            {
                "type": "text",
                "text": (
                    "VISUAL CONSTITUTION:\n"
                    + json.dumps(visual_spec, ensure_ascii=False)
                    + "\nEXPECTED VARIABLE CONTENT:\n"
                    + json.dumps(expected, ensure_ascii=False)
                    + f"\nTRIGGER TOKEN: {trigger_token}\n"
                    "For adult_age_score, use the species-specific adult rules in "
                    "the visual constitution. For proportion_score, heavily reward "
                    "the required Lalafell head-to-body ratio and short limbs, and "
                    "heavily penalize ordinary adult-human anatomy.\n"
                    "Return exactly this JSON schema:\n"
                    "{"
                    '"identity_score":0-30,'
                    '"adult_age_score":0-10,'
                    '"proportion_score":0-10,'
                    '"hair_score":0-10,'
                    '"face_eyes_score":0-10,'
                    '"outfit_score":0-10,'
                    '"equipment_score":0-10,'
                    '"technical_score":0-5,'
                    '"information_gain_score":0-5,'
                    '"hard_reject":true|false,'
                    '"decision":"accept|repair|reject",'
                    '"observed_identity":"brief English",'
                    '"problems":["brief Chinese"],'
                    '"repair_suggestions":["brief Chinese"],'
                    f'"caption":"English training caption beginning with {trigger_token}"'
                    "}"
                ),
            },
        ]
    )

    base_url = str(provider.get("base_url") or "").rstrip("/")
    path = str(provider.get("path") or "/chat/completions")
    url = f"{base_url}/{path.lstrip('/')}"
    api_key = _resolve_api_key(provider.get("api_key"))
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers[str(provider.get("api_key_header") or "Authorization")] = (
            f"{provider.get('api_key_prefix', 'Bearer ')}{api_key}"
        )
    headers.update(provider.get("headers") or {})

    payload = {
        "model": llm_config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": float(llm_config.get("temperature", 0.1)),
        "max_tokens": int(llm_config.get("max_tokens", 1800)),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=int(llm_config.get("timeout_seconds", 180)),
        ) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise VLMError(f"LLM HTTP {exc.code}: {body[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise VLMError(f"LLM 连接失败: {exc.reason}") from exc

    result = _parse_json(_extract_text(raw))
    score_fields = (
        "identity_score",
        "adult_age_score",
        "proportion_score",
        "hair_score",
        "face_eyes_score",
        "outfit_score",
        "equipment_score",
        "technical_score",
        "information_gain_score",
    )
    result["rubric_total"] = sum(
        float(result.get(field, 0) or 0) for field in score_fields
    )
    result["provider"] = llm_config["provider"]
    result["model"] = llm_config["model"]
    return result
