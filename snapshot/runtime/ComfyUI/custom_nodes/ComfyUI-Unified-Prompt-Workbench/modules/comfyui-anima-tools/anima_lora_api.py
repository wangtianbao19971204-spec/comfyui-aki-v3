"""Anima LoRA API integration for ComfyUI Anima Tools.

Provides backend API wrappers, config loading/saving, and background downloader.
"""

import json
import hashlib
import http.client
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import folder_paths

# Red C is the preferred public API/download origin for this integration.  Keep
# the historical constant names because external workflows/tests may import
# them, but make their primary/fallback meaning explicit through the values.
CIVITAI_API_BASE = "https://civitai.red/api/v1"
CIVITAI_API_FALLBACK_BASE = "https://civitai.com/api/v1"
CIVITAI_SEARCH_HOST = "https://search-new.civitai.com"
# Public browser search key embedded by Civitai's own frontend for InstantSearch.
CIVITAI_SEARCH_CLIENT_KEY = "8c46eb2508e21db1e9828a97968d91ab1ca1caa5f70a00e88a2ba1e286603b61"
USER_AGENT = "ComfyUI-Anima-Tools/1.0"
VALID_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
SUPPORTED_LORA_BASE_MODELS = {
    "anima": "Anima",
    "krea2": "Krea 2",
}
LORA_BASE_MODEL_ALIASES = {
    "anima": "anima",
    "krea2": "krea2",
    "krea 2": "krea2",
    "krea-2": "krea2",
}

# Thread-safe download tracking
_DOWNLOAD_JOBS = {}
_DOWNLOAD_JOBS_LOCK = threading.Lock()
_CIVITAI_CACHE_VERSION = "v8-red-primary-preview-original-fallback"
_CIVITAI_SEARCH_CACHE_TTL = 2 * 60 * 60
_CIVITAI_SEARCH_STALE_TTL = 14 * 24 * 60 * 60
_CIVITAI_MODEL_CACHE_TTL = 7 * 24 * 60 * 60
_CIVITAI_RESPONSE_CACHE = {}
_CIVITAI_RESPONSE_CACHE_LOCK = threading.Lock()
_CIVITAI_REFRESHING = set()


def normalize_lora_profile_key(value: str = "Anima") -> str:
    clean_value = str(value or "Anima").strip().lower()
    profile_key = LORA_BASE_MODEL_ALIASES.get(clean_value)
    if not profile_key:
        supported = ", ".join(SUPPORTED_LORA_BASE_MODELS.values())
        raise ValueError(f"Unsupported LoRA base model. Supported values: {supported}")
    return profile_key


def _extract_civitai_image_id(image_url: str) -> str:
    if not image_url or "civitai" not in image_url:
        match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(image_url or ""), re.I)
        return match.group(0) if match else ""
    parsed = urllib.parse.urlparse(image_url)
    parts = [part for part in parsed.path.split("/") if part]
    if "civitai-media-cache" in parts:
        idx = parts.index("civitai-media-cache")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", parsed.path, re.I)
    return match.group(0) if match else ""


def get_civitai_preview_image_url(image_url: str, width: int = 512) -> str:
    """Uses Civitai's source image route instead of guessing a B2 derivative."""
    clean_url = str(image_url or "").strip()
    if not clean_url:
        return ""

    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        clean_url,
        re.IGNORECASE,
    ):
        return f"https://image-b2.civitai.com/file/civitai-media-cache/{clean_url}/original"

    try:
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.hostname and parsed.hostname.lower() == "image.civitai.com":
            optimized_path = re.sub(
                r"/(?:original=true|width=\d+)(?=/)",
                f"/width={max(1, int(width))}",
                parsed.path,
                count=1,
                flags=re.IGNORECASE,
            )
            if optimized_path != parsed.path:
                return urllib.parse.urlunparse(parsed._replace(path=optimized_path))
    except (TypeError, ValueError):
        pass

    return clean_url


def open_civitai_preview_url(request, timeout: int = 30):
    """Opens a Civitai image with a LoRA-specific or isolated OS proxy."""
    configured_proxy = str(load_config().get("civitai_image_proxy") or "").strip()
    if configured_proxy:
        proxies = {"http": configured_proxy, "https": configured_proxy}
    else:
        proxies = {
            scheme: value
            for scheme, value in urllib.request.getproxies().items()
            if scheme in {"http", "https"} and value
        }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    return opener.open(request, timeout=timeout)


def _safe_lora_filename(name: str, fallback_id: int | str = "") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "")).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)[:140].strip()
    if not cleaned:
        cleaned = f"civitai_lora_{fallback_id or int(time.time())}"
    if not cleaned.lower().endswith(".safetensors"):
        cleaned += ".safetensors"
    return cleaned


def get_config_path() -> str:
    """Gets the path to the anima_lora_config.json configuration file."""
    try:
        user_dir = folder_paths.get_user_directory()
    except AttributeError:
        user_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "user"))
        if not os.path.exists(user_dir):
            user_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "user"))
    
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "anima_lora_config.json")


_LORA_CONFIG_CACHE = None


def load_config() -> dict:
    """Loads configuration dictionary."""
    global _LORA_CONFIG_CACHE
    if _LORA_CONFIG_CACHE is not None:
        return _LORA_CONFIG_CACHE
    path = get_config_path()
    default_config = {
        "custom_lora_dir": "",
        "krea2_lora_dir": "",
        "civitai_api_key": "",
        "civitai_image_proxy": ""
    }
    if not os.path.exists(path):
        _LORA_CONFIG_CACHE = default_config
        return default_config
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                _LORA_CONFIG_CACHE = {**default_config, **data}
                return _LORA_CONFIG_CACHE
    except Exception as e:
        print(f"[Anima Tools] Error loading config: {e}")
    _LORA_CONFIG_CACHE = default_config
    return default_config


def save_config(config: dict) -> bool:
    """Saves configuration dictionary."""
    global _LORA_CONFIG_CACHE
    path = get_config_path()
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        _LORA_CONFIG_CACHE = config
        return True
    except Exception as e:
        print(f"[Anima Tools] Error saving config: {e}")
        return False


def _get_civitai_cache_dir() -> str:
    cache_dir = os.path.join(os.path.dirname(get_config_path()), "anima_tools", "civitai_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _civitai_cache_key(kind: str, payload: dict) -> str:
    serialized = json.dumps(
        {"version": _CIVITAI_CACHE_VERSION, "kind": kind, "payload": payload},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _civitai_cache_path(cache_key: str) -> str:
    return os.path.join(_get_civitai_cache_dir(), f"{cache_key}.json")


def _load_civitai_cached_response(cache_key: str) -> tuple[dict | None, float]:
    with _CIVITAI_RESPONSE_CACHE_LOCK:
        memory_entry = _CIVITAI_RESPONSE_CACHE.get(cache_key)
    if memory_entry:
        return memory_entry.get("result"), float(memory_entry.get("timestamp") or 0)

    path = _civitai_cache_path(cache_key)
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        result = entry.get("result")
        timestamp = float(entry.get("timestamp") or 0)
        if isinstance(result, dict) and timestamp > 0:
            with _CIVITAI_RESPONSE_CACHE_LOCK:
                _CIVITAI_RESPONSE_CACHE[cache_key] = {
                    "result": result,
                    "timestamp": timestamp,
                }
            return result, timestamp
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return None, 0


def _save_civitai_cached_response(cache_key: str, result: dict) -> None:
    if not isinstance(result, dict):
        return
    timestamp = time.time()
    entry = {"timestamp": timestamp, "result": result}
    path = _civitai_cache_path(cache_key)
    tmp_path = f"{path}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, path)
        with _CIVITAI_RESPONSE_CACHE_LOCK:
            _CIVITAI_RESPONSE_CACHE[cache_key] = entry
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _mark_civitai_cache_result(result: dict, state: str, age: float = 0) -> dict:
    marked = dict(result)
    metadata = dict(marked.get("metadata") or {})
    metadata["cacheState"] = state
    metadata["cacheAgeSeconds"] = max(0, int(age))
    marked["metadata"] = metadata
    return marked


def _civitai_api_source_metadata(api_base: str, source: str = "public-api") -> dict:
    """Builds additive source metadata without changing legacy source labels."""
    clean_base = str(api_base or "").rstrip("/")
    try:
        source_host = urllib.parse.urlparse(clean_base).netloc.lower()
    except Exception:
        source_host = ""
    return {
        "source": source,
        "sourceHost": source_host,
        "sourceBaseUrl": clean_base,
        "sourceRole": "primary" if clean_base == CIVITAI_API_BASE.rstrip("/") else "fallback",
    }


def _mark_civitai_model_source(result: dict, api_base: str) -> dict:
    marked = dict(result)
    marked["_anima_source"] = _civitai_api_source_metadata(api_base)
    return marked


def _is_valid_civitai_model_detail(result: dict | None) -> bool:
    if not isinstance(result, dict) or result.get("error"):
        return False
    return bool(result.get("id") or result.get("name") or result.get("modelVersions"))


def normalize_lora_subfolder(subfolder: str) -> str:
    raw_value = str(subfolder or "").replace("\\", "/").strip()
    if not raw_value:
        return ""
    if raw_value.startswith("/") or os.path.isabs(raw_value) or re.match(r"^[A-Za-z]:", raw_value):
        raise ValueError("LoRA subfolder must be relative")
    value = raw_value.strip("/")
    parts = [part.strip() for part in value.split("/") if part.strip()]
    if any(part in (".", "..") for part in parts):
        raise ValueError("Invalid LoRA subfolder")
    if any(re.search(r'[<>:"|?*\x00-\x1f]', part) for part in parts):
        raise ValueError("Invalid LoRA subfolder")
    return "/".join(parts)


def get_lora_save_dir(subfolder: str = "", base_model: str = "Anima") -> str:
    """Resolves directory path where downloaded LoRA models should be saved."""
    profile_key = normalize_lora_profile_key(base_model)
    config = load_config()
    config_key = "custom_lora_dir" if profile_key == "anima" else "krea2_lora_dir"
    custom_dir = str(config.get(config_key, "") or "").strip()
    if custom_dir and os.path.isdir(custom_dir):
        base_dir = os.path.abspath(custom_dir)
    else:
        base_dir = ""
        try:
            roots = folder_paths.get_folder_paths("loras")
            if roots and os.path.isdir(roots[0]):
                base_dir = os.path.abspath(roots[0])
        except Exception:
            pass
        if not base_dir:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "models", "loras"))
        if profile_key == "krea2":
            base_dir = os.path.join(base_dir, "krea2")

    normalized_subfolder = normalize_lora_subfolder(subfolder)
    save_dir = os.path.abspath(os.path.join(base_dir, normalized_subfolder.replace("/", os.sep)))
    if os.path.commonpath([os.path.normcase(save_dir), os.path.normcase(base_dir)]) != os.path.normcase(base_dir):
        raise ValueError("LoRA download folder is outside the configured root")
    os.makedirs(save_dir, exist_ok=True)
    return save_dir


def _request_headers(api_key: str | None = None, json_content: bool = True) -> dict:
    headers = {"User-Agent": USER_AGENT}
    if json_content:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _read_json_url(url: str, api_key: str | None = None, timeout: int = 30) -> dict | None:
    req = urllib.request.Request(url, headers=_request_headers(api_key), method="GET")
    try:
        with open_civitai_preview_url(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[Anima Tools] Civitai API error {e.code}: {e.reason} at {url}")
        return None
    except urllib.error.URLError as e:
        print(f"[Anima Tools] Civitai connection error: {e.reason} at {url}")
        return None
    except Exception as e:
        print(f"[Anima Tools] Civitai unexpected error: {e}")
        return None


def _post_json_url(url: str, body: dict, api_key: str | None = None, timeout: int = 30) -> dict | None:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_request_headers(api_key), method="POST")
    try:
        with open_civitai_preview_url(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        print(f"[Anima Tools] Civitai search error {e.code}: {e.reason} {detail}")
        return None
    except urllib.error.URLError as e:
        print(f"[Anima Tools] Civitai search connection error: {e.reason}")
        return None
    except Exception as e:
        print(f"[Anima Tools] Civitai search unexpected error: {e}")
        return None


def _official_sort_value(sort: str) -> str:
    mapping = {
        "Relevancy": "models_v9",
        "Highest Rated": "models_v9:metrics.thumbsUpCount:desc",
        "Most Downloaded": "models_v9:metrics.downloadCount:desc",
        "Most Liked": "models_v9:metrics.favoriteCount:desc",
        "Most Discussed": "models_v9:metrics.commentCount:desc",
        "Most Collected": "models_v9:metrics.collectedCount:desc",
        "Most Buzz": "models_v9:metrics.tippedAmountCount:desc",
        "Newest": "models_v9:createdAt:desc",
    }
    clean_sort = str(sort or "").strip()
    if clean_sort.startswith("models_v9"):
        return clean_sort
    return mapping.get(clean_sort, "models_v9")


def _meili_sort_for_civitai_sort(sort: str) -> tuple[str, list[str]]:
    official_sort = _official_sort_value(sort)
    parts = official_sort.split(":")
    index_uid = parts[0] or "models_v9"
    sort_rules = [":".join(parts[1:])] if len(parts) > 1 else []
    return index_uid, sort_rules


def _public_api_sort_for_civitai_sort(sort: str) -> str:
    mapping = {
        "models_v9": "Highest Rated",
        "models_v9:metrics.thumbsUpCount:desc": "Highest Rated",
        "models_v9:metrics.downloadCount:desc": "Most Downloaded",
        "models_v9:metrics.favoriteCount:desc": "Most Liked",
        "models_v9:metrics.commentCount:desc": "Most Discussed",
        "models_v9:metrics.collectedCount:desc": "Most Collected",
        "models_v9:metrics.tippedAmountCount:desc": "Most Buzz",
        "models_v9:createdAt:desc": "Newest",
    }
    official_sort = _official_sort_value(sort)
    return mapping.get(official_sort, str(sort or "Highest Rated"))


def _quote_meili_value(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


_OBVIOUS_STYLE_NAME_RE = re.compile(
    r"""
    (?:
        \bstyle\s*[-_/ ]*\s*lora\b
        |\bartist(?:ic)?\s+style\b
        |\bart\s+style\b
        |\bstyle\s+(?:pack|collection|mix|model)\b
        |(?:^|[\s|:/\-\[(])style(?:$|[\s|:/\-\])])
        |画风|畫風|风格|風格|スタイル|스타일
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_obvious_style_named_character_hit(hit: dict) -> bool:
    """Rejects entries explicitly named as styles from the strict Character tab."""
    if not isinstance(hit, dict):
        return False
    return bool(_OBVIOUS_STYLE_NAME_RE.search(str(hit.get("name") or "")))


def resolve_lora_base_model(value: str = "Anima") -> str:
    """Returns the exact Civitai base-model label for a supported selector tab."""
    profile_key = normalize_lora_profile_key(value)
    return SUPPORTED_LORA_BASE_MODELS[profile_key]


def _filter_civitai_items_by_base_model(result: dict | None, base_model: str) -> dict | None:
    """Keeps only versions for the selected base model in public API results."""
    if not isinstance(result, dict):
        return result
    target = str(base_model or "").strip().lower()
    filtered_items = []
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        versions = [
            version
            for version in item.get("modelVersions") or []
            if isinstance(version, dict)
            and str(version.get("baseModel") or "").strip().lower() == target
        ]
        if not versions:
            continue
        filtered_item = dict(item)
        filtered_item["modelVersions"] = versions
        filtered_items.append(filtered_item)
    filtered_result = dict(result)
    filtered_result["items"] = filtered_items
    metadata = dict(filtered_result.get("metadata") or {})
    metadata["baseModel"] = base_model
    filtered_result["metadata"] = metadata
    return filtered_result


def _compact_public_search_result(result: dict | None, api_base: str = "") -> dict | None:
    """Removes detail-only fields from public API results used by the model grid."""
    if not isinstance(result, dict):
        return result

    source_metadata = _civitai_api_source_metadata(api_base) if api_base else {"source": "public-api"}
    compact_items = []
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        compact_versions = []
        for version in item.get("modelVersions") or []:
            if not isinstance(version, dict):
                continue
            compact_files = []
            for file_info in version.get("files") or []:
                if not isinstance(file_info, dict):
                    continue
                compact_files.append({
                    "id": file_info.get("id"),
                    "name": file_info.get("name") or "",
                    "type": file_info.get("type") or "",
                    "downloadUrl": file_info.get("downloadUrl") or version.get("downloadUrl") or "",
                    "metadata": file_info.get("metadata") or {},
                    "primary": file_info.get("primary", False),
                })
            compact_versions.append({
                "id": version.get("id"),
                "name": version.get("name") or "",
                "baseModel": version.get("baseModel") or "",
                "trainedWords": version.get("trainedWords") or [],
                "downloadUrl": version.get("downloadUrl") or "",
                "files": compact_files,
                "images": (version.get("images") or [])[:1],
                "stats": version.get("stats") or {},
            })
        compact_items.append({
            "id": item.get("id"),
            "name": item.get("name") or "Unnamed Model",
            "type": item.get("type") or "LORA",
            "creator": item.get("creator") or {},
            "stats": item.get("stats") or {},
            "modelVersions": compact_versions,
            "_search_source": "public-api",
            "_search_host": source_metadata.get("sourceHost", ""),
        })

    compact_result = {
        "items": compact_items,
        "metadata": dict(result.get("metadata") or {}),
    }
    compact_result["metadata"].update(source_metadata)
    return compact_result


def _convert_meili_image(image: dict, width: int = 450) -> dict:
    image = image or {}
    # The search index already provides the canonical image.civitai.com URL.
    # Keep that route so newly uploaded images do not depend on a derivative
    # object that may not have been generated in image-b2 yet.
    url = get_civitai_preview_image_url(str(image.get("url") or ""), width=width)
    return {
        "id": image.get("id"),
        "url": url,
        "thumbnailUrl": url,
        "type": "image",
        "name": image.get("name") or "",
        "width": image.get("width"),
        "height": image.get("height"),
        "nsfwLevel": image.get("nsfwLevel"),
    }


def _images_for_version(hit: dict, version_id: int | str | None = None) -> list[dict]:
    images = hit.get("images") if isinstance(hit.get("images"), list) else []
    filtered = []
    for image in images:
        if not isinstance(image, dict):
            continue
        if version_id and str(image.get("modelVersionId") or "") != str(version_id):
            continue
        if str(image.get("type") or "").lower() == "video":
            continue
        filtered.append(_convert_meili_image(image))
    if not filtered:
        for image in images:
            if isinstance(image, dict) and str(image.get("type") or "").lower() != "video":
                filtered.append(_convert_meili_image(image))
    return filtered[:1]


def _convert_meili_version(hit: dict, version: dict, base_model: str) -> dict:
    version = version or {}
    version_id = version.get("id")
    model_name = hit.get("name") or "Civitai LoRA"
    version_name = version.get("name") or ""
    filename = _safe_lora_filename(f"{model_name} - {version_name}".strip(" -"), version_id)
    download_url = f"https://civitai.com/api/download/models/{version_id}" if version_id else ""
    return {
        "id": version_id,
        "name": version_name or base_model,
        "baseModel": version.get("baseModel") or base_model,
        "trainedWords": version.get("trainedWords") or hit.get("triggerWords") or [],
        "images": _images_for_version(hit, version_id),
        "downloadUrl": download_url,
        "files": [{
            "id": version_id,
            "name": filename,
            "downloadUrl": download_url,
            "type": "Model",
            "metadata": {"format": "SafeTensor"},
        }],
        "stats": version.get("metrics") or {},
        "metrics": version.get("metrics") or {},
    }


def _convert_meili_hit(hit: dict, base_model: str) -> dict | None:
    versions = []
    target = str(base_model or "").strip().lower()
    primary_version = hit.get("version") if isinstance(hit.get("version"), dict) else {}
    if primary_version and str(primary_version.get("baseModel") or "").strip().lower() == target:
        versions.append(primary_version)
    for version in hit.get("versions") or []:
        if not isinstance(version, dict):
            continue
        if str(version.get("baseModel") or "").strip().lower() != target:
            continue
        if primary_version and str(version.get("id")) == str(primary_version.get("id")):
            continue
        versions.append(version)
    if not versions:
        return None
    model_versions = [_convert_meili_version(hit, version, base_model) for version in versions[:8]]
    if not model_versions[0].get("images"):
        model_versions[0]["images"] = _images_for_version(hit)

    user = hit.get("user") if isinstance(hit.get("user"), dict) else {}
    metrics = hit.get("metrics") if isinstance(hit.get("metrics"), dict) else {}
    tag_names = [
        str(tag.get("name") or "").strip()
        for tag in hit.get("tags") or []
        if isinstance(tag, dict) and str(tag.get("name") or "").strip()
    ]
    return {
        "id": hit.get("id"),
        "name": hit.get("name") or "Unnamed Model",
        "type": hit.get("type") or "LORA",
        "description": hit.get("description") or hit.get("descriptionHtml") or hit.get("descriptionPlaintext") or "",
        "creator": {
            "username": user.get("username") or "Unknown",
            "image": user.get("image"),
        },
        "stats": {
            "downloadCount": metrics.get("downloadCount", 0),
            "favoriteCount": metrics.get("favoriteCount", metrics.get("collectedCount", 0)),
            "thumbsUpCount": metrics.get("thumbsUpCount", 0),
            "commentCount": metrics.get("commentCount", 0),
        },
        "modelVersions": model_versions,
        "_search_source": "meili",
        "_category": (hit.get("category") or {}).get("name") if isinstance(hit.get("category"), dict) else "",
        "_tags": tag_names,
    }


def _search_civitai_loras_meili(
    query: str,
    tag: str,
    category: str,
    sort: str,
    cursor: str,
    limit: int,
    base_model: str,
) -> dict | None:
    try:
        offset = max(0, int(cursor or "0"))
    except ValueError:
        offset = 0

    filters = [
        f"version.baseModel = {_quote_meili_value(base_model)}",
        "type = 'LORA'",
        "fileFormats = 'SafeTensor'",
        "availability != 'Private'",
    ]
    clean_category = str(category or "").strip()
    clean_tag = str(tag or "").strip()
    if clean_category:
        filters.append(f"category.name = {_quote_meili_value(clean_category)}")
    if clean_tag:
        filters.append(f"tags.name = {_quote_meili_value(clean_tag)}")

    index_uid, sort_rules = _meili_sort_for_civitai_sort(sort)
    query_payload = {
        "indexUid": index_uid,
        "q": str(query or "").strip(),
        "filter": filters,
        "limit": max(1, min(limit, 100)),
        "offset": offset,
        "attributesToRetrieve": [
            "id", "name", "type",
            "metrics.downloadCount", "metrics.favoriteCount",
            "metrics.thumbsUpCount", "metrics.commentCount",
            "user.username", "user.image", "category.name", "tags.name",
            "version.id", "version.name", "version.baseModel",
            "version.trainedWords", "version.metrics", "triggerWords",
            "images.id", "images.url", "images.modelVersionId",
            "images.type", "images.width", "images.height", "images.nsfwLevel",
        ],
    }
    if sort_rules:
        query_payload["sort"] = sort_rules

    body = {
        "queries": [query_payload]
    }
    result = _post_json_url(
        f"{CIVITAI_SEARCH_HOST}/multi-search",
        body,
        api_key=CIVITAI_SEARCH_CLIENT_KEY,
        timeout=20,
    )
    if not result:
        return None
    first = (result.get("results") or [{}])[0]
    hits = first.get("hits") or []
    next_offset = offset + len(hits)
    total = first.get("estimatedTotalHits") or 0
    next_cursor = str(next_offset) if len(hits) >= limit and next_offset < total else ""
    expected_category = clean_category.lower()
    category_rejected_count = 0
    semantic_rejected_count = 0
    accepted_hits = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_category = (
            str((hit.get("category") or {}).get("name") or "").strip().lower()
            if isinstance(hit.get("category"), dict)
            else ""
        )
        if expected_category and hit_category != expected_category:
            category_rejected_count += 1
            continue
        if expected_category == "character" and _is_obvious_style_named_character_hit(hit):
            semantic_rejected_count += 1
            continue
        accepted_hits.append(hit)
    converted_items = [
        _convert_meili_hit(hit, base_model)
        for hit in accepted_hits
    ]
    return {
        "items": [item for item in converted_items if item],
        "metadata": {
            "nextCursor": next_cursor,
            "totalItems": total,
            "source": "meili",
            "sourceHost": CIVITAI_SEARCH_HOST.split("://", 1)[-1].split("/", 1)[0].lower(),
            "sourceBaseUrl": CIVITAI_SEARCH_HOST.rstrip("/"),
            "sourceRole": "shared-search-index",
            "baseModel": base_model,
            "category": clean_category,
            "categoryRejectedCount": category_rejected_count,
            "semanticRejectedCount": semantic_rejected_count,
        }
    }


def _search_civitai_loras_uncached(
    query: str = "",
    tag: str = "",
    category: str = "",
    sort: str = "Highest Rated",
    cursor: str = "",
    limit: int = 40,
    base_model: str = "Anima",
) -> dict | None:
    """Searches Civitai for LoRA models matching a supported base-model tab."""
    resolved_base_model = resolve_lora_base_model(base_model)
    config = load_config()
    api_key = config.get("civitai_api_key", "").strip() or None

    clean_query = str(query or "").strip()
    clean_tag = str(tag or "").strip()
    clean_category = str(category or "").strip()
    clean_cursor = str(cursor or "").strip()

    # Civitai's public /api/v1/models endpoint does not support the `category`
    # parameter. Use the search index that exposes category.name instead of
    # accepting an unfiltered public response for every sidebar category.
    if clean_category:
        category_result = _search_civitai_loras_meili(
            clean_query,
            clean_tag,
            clean_category,
            sort,
            clean_cursor,
            limit,
            resolved_base_model,
        )
        if isinstance(category_result, dict):
            return category_result
        return None

    params = {
        "limit": str(max(1, min(limit, 100))),
        "types": "LORA",
        "sortBy": _public_api_sort_for_civitai_sort(sort),
        "nsfw": "true",
        "baseModels": resolved_base_model,
    }
    
    if clean_query:
        params["query"] = clean_query
    if clean_tag:
        params["tag"] = clean_tag
    if clean_cursor:
        params["cursor"] = clean_cursor
        
    encoded = urllib.parse.urlencode(params)
    for api_base in (CIVITAI_API_BASE, CIVITAI_API_FALLBACK_BASE):
        url = f"{api_base}/models?{encoded}"
        result = _read_json_url(url, api_key=api_key, timeout=12)
        filtered_result = _filter_civitai_items_by_base_model(result, resolved_base_model)
        if isinstance(filtered_result, dict) and filtered_result.get("items"):
            return _compact_public_search_result(filtered_result, api_base)

    return _search_civitai_loras_meili(
        query,
        tag,
        category,
        sort,
        cursor,
        limit,
        resolved_base_model,
    )


def _refresh_civitai_search_cache(cache_key: str, search_args: dict) -> None:
    try:
        result = _search_civitai_loras_uncached(**search_args)
        if isinstance(result, dict):
            _save_civitai_cached_response(cache_key, result)
    finally:
        with _CIVITAI_RESPONSE_CACHE_LOCK:
            _CIVITAI_REFRESHING.discard(cache_key)


def search_civitai_loras(
    query: str = "",
    tag: str = "",
    category: str = "",
    sort: str = "Highest Rated",
    cursor: str = "",
    limit: int = 40,
    base_model: str = "Anima",
    force_refresh: bool = False,
    cache_only: bool = False,
) -> dict | None:
    """Searches Civitai with a persistent stale-while-refresh response cache."""
    resolved_base_model = resolve_lora_base_model(base_model)
    search_args = {
        "query": str(query or "").strip(),
        "tag": str(tag or "").strip(),
        "category": str(category or "").strip(),
        "sort": str(sort or "Highest Rated").strip(),
        "cursor": str(cursor or "").strip(),
        "limit": max(1, min(int(limit or 40), 100)),
        "base_model": resolved_base_model,
    }
    cache_key = _civitai_cache_key("search", search_args)
    cached, timestamp = _load_civitai_cached_response(cache_key)
    age = max(0, time.time() - timestamp) if timestamp else float("inf")

    if cache_only:
        if cached:
            return _mark_civitai_cache_result(cached, "cache-only", age)
        return None

    if not force_refresh and cached and age < _CIVITAI_SEARCH_CACHE_TTL:
        return _mark_civitai_cache_result(cached, "fresh", age)

    if not force_refresh and cached and age < _CIVITAI_SEARCH_STALE_TTL:
        with _CIVITAI_RESPONSE_CACHE_LOCK:
            should_refresh = cache_key not in _CIVITAI_REFRESHING
            if should_refresh:
                _CIVITAI_REFRESHING.add(cache_key)
        if should_refresh:
            threading.Thread(
                target=_refresh_civitai_search_cache,
                args=(cache_key, search_args),
                daemon=True,
            ).start()
        return _mark_civitai_cache_result(cached, "stale-refreshing", age)

    result = _search_civitai_loras_uncached(**search_args)
    if isinstance(result, dict):
        _save_civitai_cached_response(cache_key, result)
        return _mark_civitai_cache_result(result, "network", 0)
    if cached:
        return _mark_civitai_cache_result(cached, "stale-offline", age)
    return result


def fetch_civitai_model(
    model_id: int | str,
    force_refresh: bool = False,
    cache_only: bool = False,
) -> dict | None:
    """Fetches full model metadata by id with a persistent response cache."""
    clean_model_id = str(model_id or "").strip()
    cache_key = _civitai_cache_key("model", {"id": clean_model_id})
    cached, timestamp = _load_civitai_cached_response(cache_key)
    age = max(0, time.time() - timestamp) if timestamp else float("inf")
    if cache_only:
        return cached
    if not force_refresh and cached and age < _CIVITAI_MODEL_CACHE_TTL:
        return cached

    config = load_config()
    api_key = config.get("civitai_api_key", "").strip() or None

    for api_base in (CIVITAI_API_BASE, CIVITAI_API_FALLBACK_BASE):
        url = f"{api_base}/models/{clean_model_id}"
        result = _read_json_url(url, api_key=api_key, timeout=12)
        if _is_valid_civitai_model_detail(result):
            marked_result = _mark_civitai_model_source(result, api_base)
            _save_civitai_cached_response(cache_key, marked_result)
            return marked_result
    return cached


def download_preview_image(image_url: str, save_path: str) -> bool:
    """Downloads preview image from Civitai."""
    try:
        image_url = get_civitai_preview_image_url(image_url, width=512)
        # Append width=512 for optimization if not already present
        if "civitai-media-cache" not in image_url and "width=" not in image_url:
            separator = "&" if "?" in image_url else "?"
            image_url = f"{image_url}{separator}width=512"
            
        req = urllib.request.Request(image_url, headers=_request_headers(json_content=False))
        with open_civitai_preview_url(req, timeout=30) as resp:
            image_data = resp.read()
            
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(image_data)
        return True
    except Exception as e:
        print(f"[Anima Tools] Failed to download preview image: {e}")
        return False


def _civitai_download_candidates(download_url: str) -> list[str]:
    """Returns red-C-first download URLs while preserving path and query."""
    parsed = urllib.parse.urlparse(str(download_url or ""))
    host = parsed.netloc.lower()
    if parsed.scheme.lower() != "https" or host not in ("civitai.red", "civitai.com", "www.civitai.com"):
        return [str(download_url or "")]

    candidates = []
    for candidate_host in ("civitai.red", "civitai.com"):
        candidate = urllib.parse.urlunparse(parsed._replace(netloc=candidate_host))
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _with_civitai_api_token(url: str, api_key: str | None) -> str:
    if not api_key:
        return url
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "token" not in query:
        query["token"] = [api_key]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def _download_source_error_message(source_host: str, error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        message = f"HTTP Error {error.code}: {error.reason}"
        if error.code in (401, 403):
            message += ". This model may require a Civitai API Key"
    else:
        message = str(getattr(error, "reason", error))
    return f"{source_host or 'unknown source'}: {message}"


def _download_thread(task_id: str, download_url: str, save_path: str, api_key: str | None = None, metadata: dict = None):
    """Worker thread function to download from red C, then blue C on source failure."""
    temp_path = f"{save_path}.download"
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    total_size = 0
    downloaded = 0
    successful_host = ""
    source_errors = []

    try:
        for candidate_url in _civitai_download_candidates(download_url):
            req_url = _with_civitai_api_token(candidate_url, api_key)
            source_host = urllib.parse.urlparse(candidate_url).netloc.lower()
            with _DOWNLOAD_JOBS_LOCK:
                job = _DOWNLOAD_JOBS[task_id]
                job["status"] = "downloading"
                job["progress"] = 0
                job["total"] = 0
                job["source_host"] = source_host
                attempted_hosts = job.setdefault("attempted_hosts", [])
                if source_host and source_host not in attempted_hosts:
                    attempted_hosts.append(source_host)

            req = urllib.request.Request(req_url, headers=_request_headers(api_key, json_content=False))
            try:
                with urllib.request.urlopen(req, timeout=60) as resp, open(temp_path, "wb") as f:
                    try:
                        total_size = int(resp.headers.get("Content-Length") or 0)
                    except (TypeError, ValueError):
                        total_size = 0
                    downloaded = 0
                    with _DOWNLOAD_JOBS_LOCK:
                        _DOWNLOAD_JOBS[task_id]["total"] = total_size

                    while True:
                        chunk = resp.read(1024 * 1024)  # 1MB chunks
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        with _DOWNLOAD_JOBS_LOCK:
                            _DOWNLOAD_JOBS[task_id]["progress"] = downloaded

                if total_size > 0 and downloaded != total_size:
                    raise urllib.error.URLError(
                        f"Incomplete download response ({downloaded}/{total_size} bytes)"
                    )
                if downloaded <= 0:
                    raise urllib.error.URLError("Empty download response")
                successful_host = source_host
                break
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                http.client.IncompleteRead,
                ssl.SSLError,
            ) as e:
                source_errors.append(_download_source_error_message(source_host, e))
                print(f"[Anima Tools] Download source failed for {task_id}: {source_errors[-1]}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

        if not successful_host:
            detail = "; ".join(source_errors) or "No valid Civitai download source"
            raise RuntimeError(f"All Civitai download sources failed ({detail})")

        os.replace(temp_path, save_path)
        
        # Save companion metadata JSON
        if metadata:
            meta_path = os.path.splitext(save_path)[0] + ".json"
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[Anima Tools] Failed to save metadata json: {e}")
                
            # Download companion preview image
            try:
                version_info = metadata.get("version", {})
                images = version_info.get("images", [])
                if not images and isinstance(metadata.get("model"), dict):
                    images = metadata.get("model", {}).get("modelVersions", [{}])[0].get("images", [])
                
                if images:
                    preview_url = images[0].get("url")
                    if preview_url:
                        # Detect extension
                        preview_ext = ".png"
                        if ".jpg" in preview_url.lower() or ".jpeg" in preview_url.lower():
                            preview_ext = ".jpg"
                        elif ".webp" in preview_url.lower():
                            preview_ext = ".webp"
                            
                        preview_path = os.path.splitext(save_path)[0] + preview_ext
                        download_preview_image(preview_url, preview_path)
            except Exception as e:
                print(f"[Anima Tools] Failed to download companion preview: {e}")
                
        with _DOWNLOAD_JOBS_LOCK:
            job = _DOWNLOAD_JOBS[task_id]
            job["status"] = "completed"
            job["progress"] = total_size or downloaded
            job["total"] = total_size or downloaded
            job["source_host"] = successful_host
            job["source_role"] = "primary" if successful_host == "civitai.red" else "fallback"

    except Exception as e:
        print(f"[Anima Tools] Download thread failed for {task_id}: {e}")
        with _DOWNLOAD_JOBS_LOCK:
            _DOWNLOAD_JOBS[task_id]["status"] = "failed"
            _DOWNLOAD_JOBS[task_id]["error"] = str(e)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
 
 
def start_download_task(
    version_id: int | str,
    download_url: str,
    filename: str,
    metadata: dict = None,
    subfolder: str = "",
    base_model: str = "Anima",
) -> str:
    """Starts a background thread to download a model version."""
    task_id = str(version_id)
    resolved_base_model = resolve_lora_base_model(base_model)
    save_dir = get_lora_save_dir(subfolder, resolved_base_model)
    filename = str(filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename.lower().endswith(".safetensors"):
        raise ValueError("LoRA filename must end with .safetensors")
    save_path = os.path.join(save_dir, filename)
    
    with _DOWNLOAD_JOBS_LOCK:
        if task_id in _DOWNLOAD_JOBS:
            existing_job = _DOWNLOAD_JOBS[task_id]
            status = existing_job["status"]
            if status in ("pending", "downloading"):
                return task_id
            same_target = (
                os.path.normcase(os.path.abspath(str(existing_job.get("save_path") or "")))
                == os.path.normcase(os.path.abspath(save_path))
            )
            if status == "completed" and same_target and os.path.isfile(save_path):
                return task_id
                
        _DOWNLOAD_JOBS[task_id] = {
            "status": "pending",
            "progress": 0,
            "total": 0,
            "error": "",
            "save_path": save_path,
            "base_model": resolved_base_model,
        }
        
    config = load_config()
    api_key = config.get("civitai_api_key", "").strip() or None
    
    t = threading.Thread(
        target=_download_thread,
        args=(task_id, download_url, save_path, api_key, metadata),
        daemon=True
    )
    t.start()
    return task_id


def get_download_job_status(task_id: str) -> dict | None:
    """Gets current status of a download job."""
    with _DOWNLOAD_JOBS_LOCK:
        return _DOWNLOAD_JOBS.get(task_id)


def get_all_download_jobs() -> dict:
    """Gets all current active/cached download jobs."""
    with _DOWNLOAD_JOBS_LOCK:
        return dict(_DOWNLOAD_JOBS)
