# -*- coding: utf-8 -*-

import os
import json
import gc
from array import array
from collections import Counter
from server import PromptServer
from aiohttp import web
import zipfile
import shutil
import io
import gzip
import time
import uuid
import tempfile
import asyncio
import hashlib
import threading
import copy
import atexit
import re as _re_module
import sqlite3
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageOps
from .semantic_projection import read_projection, project_library, merge_selection_edit, decision_for, confirm_classification, selector_subcategories, soft_light_modifier_cue_allowed, rebind_unchanged_prompt, binding as semantic_binding
from .semantic_taxonomy import CLASS_LABELS, FACET_CLASS_MAP, SUBCATEGORY_PARENTS, semantic_themes, subcategory_owner
from .semantic_refinements import REFINEMENT_NODES, REFINEMENT_VERSION, extract_refinements
from .semantic_filter_counts import build_filter_masks, conditional_filter_counts, row_mask
from .import_plan import plan_import
from .prompt_merge import merge_preview, apply_merge, merged_source, known_merged_import
from .selector_library import favorites_view, apply_favorites, apply_collection, update_collection, collection_groups, prompt_collection, COLLECTION_KINDS, CLASS_ROUTES

# Logger导入
import logging
logger = logging.getLogger("weilin.prompt_selector")

# orjson is ~7x faster at both ends of the 110 MB library snapshot and produces the same
# document (no float values in the store, key order preserved); the stdlib stays as the
# fallback so the plugin never depends on it.
try:
    import orjson as _orjson
except Exception:  # noqa: BLE001
    _orjson = None


def _json_dump_bytes(data):
    # Looked up through globals() so partial-source harnesses that drop the optional
    # import block still run on the stdlib path.
    orjson_module = globals().get("_orjson")
    if orjson_module is not None:
        try:
            return orjson_module.dumps(data)
        except Exception:  # noqa: BLE001 - fall back rather than fail a commit
            pass
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _json_load_path(path):
    orjson_module = globals().get("_orjson")
    if orjson_module is not None:
        try:
            with open(path, 'rb') as stream:
                return orjson_module.loads(stream.read())
        except Exception:  # noqa: BLE001 - stdlib reports the real syntax error
            pass
    with open(path, 'r', encoding='utf-8') as stream:
        return json.load(stream)

# 插件目录
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOM_NODE_DIR = os.path.abspath(os.path.join(PLUGIN_DIR, '..'))

# Prompt Selector is fully owned by WeiLin. Code lives in prompt_selector/, while
# persistent user data lives under user_data/prompt_selector/. No Gallery lookup or
# fallback store is used, so upgrading/removing the Gallery cannot affect this data.
PROMPT_STORE_DIR = os.path.join(CUSTOM_NODE_DIR, "user_data", "prompt_selector")
PROMPT_STORE_OWNER = "weilin"
DATA_FILE = os.path.join(PROMPT_STORE_DIR, "data.json")
DEFAULT_DATA_FILE = os.path.join(PROMPT_STORE_DIR, "default.json")
PREVIEW_DIR = os.path.join(PROMPT_STORE_DIR, "preview")
THUMBNAIL_DIR = os.path.join(PROMPT_STORE_DIR, "preview_thumbnails")
os.makedirs(PREVIEW_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
_ROUTE_BRANCH_LAST_BACKUP_AT = 0
_ROUTE_BRANCH_BACKUP_INTERVAL_SEC = 180
_PROMPT_DATA_LOCK = asyncio.Lock()
_PROMPT_FILE_LOCK = threading.RLock()
_THUMBNAIL_BUILD_SEMAPHORE = asyncio.Semaphore(2)
_PROMPT_CACHE_LOCK = threading.RLock()
_PROMPT_DATA_CACHE = None
_PROMPT_DATA_CACHE_SIGNATURE = None
# Derived read model for the shared library. ``entries`` holds one reviewed copy per
# prompt id, ``views`` the two visibility views, ``rows`` the page-ready ordering and
# ``matches`` the cached pagination result of repeated identical page requests. It is
# guarded by the same lock as the parsed document, which is always taken first.
_LIBRARY_STATE = {"version": None, "data": None, "document": None, "indexed": True,
                  "entries": {}, "views": {}, "rows": {}, "ranges": {}, "matches": {}, "index": None,
                  "view_index": {}, "row_index": {}, "filter_masks": {}, "filter_scopes": {}}
_REVIEWED_LIBRARY_CACHE = _LIBRARY_STATE["views"]
_LIBRARY_MATCH_CACHE_LIMIT = 24
_LIBRARY_PAGE_SIZE = 30
_LIBRARY_PAGE_SIZE_MAX = 100
_LIBRARY_TRACE = os.environ.get("UW_LIBRARY_TRACE") == "1"


def _lib_trace(event, **fields):
    if not globals().get("_LIBRARY_TRACE"):
        return
    try:
        with open(os.path.join(PROMPT_STORE_DIR, "read_model_trace.log"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": datetime.now().isoformat(timespec="milliseconds"),
                                     "event": event, **fields}, ensure_ascii=False) + "\n")
    except Exception:
        pass


class RevisionConflict(ValueError):
    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual
        super().__init__("Prompt library changed since editing began; draft was not saved")


def _revision(data):
    return str(data.get("last_modified") or "") if isinstance(data, dict) else ""


def _require_revision(payload, current):
    expected = payload.get("base_revision") if isinstance(payload, dict) else None
    actual = _revision(current)
    if actual == "" and expected is not None and str(expected) == "":
        return
    if not expected or str(expected) != actual:
        raise RevisionConflict(expected, actual)


def _request_revision(request, payload=None):
    """If-Match is authoritative; JSON base_revision remains a compatibility path."""
    value = request.headers.get("If-Match")
    if value is not None:
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value
    return payload.get("base_revision") if isinstance(payload, dict) else None


def _etag(revision):
    return '"' + str(revision or "") + '"'


def _with_etag(response, revision):
    response.headers["ETag"] = _etag(revision)
    response.headers["Cache-Control"] = "no-store"
    return response


def _success_response(payload):
    response_payload = dict(payload)
    revision = response_payload.get("revision")
    if revision is None:
        raise RuntimeError("successful write result missing committed revision")
    return _with_etag(web.json_response(response_payload), revision)

logger.info(f"PromptSelector storage owner: {PROMPT_STORE_OWNER}")
logger.info(f"PromptSelector data: {DATA_FILE}")
logger.info(f"PromptSelector previews: {PREVIEW_DIR}")

# === 数据安全工具函数 ===

def _validate_data(data):
    """
    验证数据结构的完整性

    Args:
        data: 待验证的数据字典

    Raises:
        ValueError: 数据结构不完整时抛出异常
    """
    if not isinstance(data, dict):
        raise ValueError("数据必须是字典类型")

    if "version" not in data:
        raise ValueError("缺少 version 字段")

    if "categories" not in data:
        raise ValueError("缺少 categories 字段")

    if not isinstance(data["categories"], list):
        raise ValueError("categories 必须是列表类型")

    if "settings" not in data:
        raise ValueError("缺少 settings 字段")

    return True

def _create_backup(file_path, max_backups=3):
    """
    创建文件备份，保留最近 N 个版本

    Args:
        file_path: 要备份的文件路径
        max_backups: 最多保留的备份数量
    """
    if not os.path.exists(file_path):
        return

    try:
        # 生成备份文件名（带时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{file_path}.backup_{timestamp}"

        # 创建备份
        shutil.copy2(file_path, backup_file)
        logger.info(f"✓ 已创建备份: {os.path.basename(backup_file)}")

        # 清理旧备份（保留最新的 max_backups 个）
        backup_dir = os.path.dirname(file_path)
        backup_pattern = f"{os.path.basename(file_path)}.backup_"

        backups = []
        for filename in os.listdir(backup_dir):
            if filename.startswith(backup_pattern):
                full_path = os.path.join(backup_dir, filename)
                backups.append((os.path.getmtime(full_path), full_path))

        # 按修改时间排序（最新的在前）
        backups.sort(reverse=True)

        # 删除多余的备份
        for _, old_backup in backups[max_backups:]:
            try:
                os.remove(old_backup)
                logger.info(f"✓ 已清理旧备份: {os.path.basename(old_backup)}")
            except Exception as e:
                logger.warning(f"⚠ 清理备份失败 {os.path.basename(old_backup)}: {e}")

    except Exception as e:
        logger.warning(f"⚠ 创建备份失败: {e}")

def _atomic_save_json_unlocked(file_path, data, create_backup=True, compact=False, sync_to_disk=True):
    """
    原子性保存 JSON 数据到文件

    使用临时文件 + 原子重命名机制，确保数据写入的原子性：
    1. 先写入到临时文件
    2. 强制刷新到磁盘（fsync）
    3. 原子重命名覆盖目标文件
    4. 异常时自动清理临时文件

    Args:
        file_path: 目标文件路径
        data: 要保存的数据（字典）
        create_backup: 是否创建备份
        compact: 是否以紧凑 JSON 写入，减少大文件写盘体积
        sync_to_disk: 是否强制 fsync 落盘。批量归类走轻量接口时可关闭，
                      避免 Windows 上偶发的长时间磁盘阻塞。

    Raises:
        ValueError: 数据验证失败
        IOError: 文件写入失败
    """
    # 1. 验证数据结构
    _validate_data(data)

    # 2. 创建备份
    if create_backup:
        _create_backup(file_path)

    # 3. 写入临时文件
    temp_fd = None
    temp_path = None

    try:
        # 在同一目录下创建临时文件（确保在同一文件系统上，os.replace 才能原子操作）
        temp_fd, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(file_path),
            prefix='.tmp_',
            suffix='.json'
        )

        # 使用文件描述符写入数据
        if compact:
            # One encode plus one write: streaming json.dump costs ~1.8 s on the 110 MB
            # library snapshot because of its many small writes.
            payload = _json_dump_bytes(data)
            with os.fdopen(temp_fd, 'wb') as f:
                f.write(payload)
                f.flush()
                if sync_to_disk:
                    os.fsync(f.fileno())
        else:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                if sync_to_disk:
                    os.fsync(f.fileno())  # 强制刷新到磁盘

        temp_fd = None  # 文件已关闭，避免重复关闭

        # 4. 原子重命名（覆盖旧文件）
        # os.replace 在 Windows 和 Unix 上都是原子操作
        os.replace(temp_path, file_path)

        logger.info(f"✓ 数据已安全保存: {os.path.basename(file_path)}")

    except Exception as e:
        logger.error(f"✗ 保存数据失败: {e}")
        # 清理临时文件
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except:
                pass

        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
        raise

def _atomic_save_json(file_path, data, create_backup=True, compact=False, sync_to_disk=True, expected_revision=None):
    """Validate the expected revision, then replace the file atomically."""
    with _PROMPT_FILE_LOCK:
        is_library = os.path.normcase(os.path.abspath(file_path)) == os.path.normcase(os.path.abspath(DATA_FILE))
        current = {}
        if expected_revision is not None and os.path.exists(file_path):
            if is_library:
                # The read model already tracks the file identity, so the revision
                # check reuses it instead of parsing another 217 MB of JSON.
                current = _read_prompt_data_cached()
            else:
                try:
                    with open(file_path, "r", encoding="utf-8") as current_file:
                        current = json.load(current_file)
                except json.JSONDecodeError:
                    # Retain original startup recovery for an already malformed file.
                    raise
            _require_revision({"base_revision": expected_revision}, current)
        result = _atomic_save_json_unlocked(file_path, data, create_backup, compact, sync_to_disk)
    # A write invalidated every derived view; rebuild them off the request path so the
    # next 资料库 / Tag / 节点 read is served warm instead of paying the projection pass.
    warm = globals().get("_request_library_warm")
    if is_library and warm is not None and os.environ.get("UW_SKIP_LIBRARY_WARMUP") != "1":
        warm(delay=0.05)
    return result

def _same_file_bytes(left_path, right_path):
    """Compare an imported preview with an existing file without replacing it."""
    left = hashlib.sha256()
    right = hashlib.sha256()
    with open(left_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            left.update(chunk)
    with open(right_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            right.update(chunk)
    return left.digest() == right.digest()

def _import_fingerprint(value):
    """Stable semantic fingerprint used only for idempotent import matching."""
    semantic = {
        str(key): value[key]
        for key in sorted(value)
        if key not in {"_source_fingerprint", "created_at", "updated_at", "usage_count", "last_used"}
        and not (key == "description" and value[key] == "")
        and not (key == "tags" and value[key] == [])
        and not (key == "favorite" and value[key] is False)
        and not (key == "image" and value[key] == "")
    }
    encoded = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def _prepare_import_data(data):
    """Normalize imported records without inventing a source ID."""
    prepared = json.loads(json.dumps(data, ensure_ascii=False))
    if not isinstance(prepared, dict) or not isinstance(prepared.get("categories"), list):
        raise ValueError("导入文件的 categories 必须是列表；原文件及当前资料均未改动。")
    for category_index, category in enumerate(prepared["categories"]):
        if not isinstance(category, dict) or not isinstance(category.get("name"), str):
            raise ValueError(f"导入文件 categories[{category_index}] 的分类名称损坏；请修复后重试，原文件及当前资料均未改动。")
        if not isinstance(category.get("prompts", []), list):
            raise ValueError(f"导入分类 {category['name']} 的 prompts 必须是列表；原文件及当前资料均未改动。")
        for prompt_index, raw in enumerate(category.get("prompts", [])):
            prompt = dict(raw) if isinstance(raw, dict) else {"prompt": raw if isinstance(raw, str) else ""}
            issues = [] if isinstance(raw, dict) else ["记录格式损坏"]
            if not isinstance(prompt.get("id"), str) or not prompt.get("id"):
                issues.append("原 ID 缺失或格式无效")
                prompt.pop("id", None)
            for field, default in (("prompt", ""), ("alias", ""), ("description", ""), ("image", ""), ("tags", [])):
                if field in prompt and not isinstance(prompt[field], type(default)):
                    issues.append(f"{field} 字段格式损坏")
                    prompt[field] = default
            if any(not isinstance(tag, str) for tag in prompt.get("tags", [])):
                issues.append("tags 列表包含非文本值")
                prompt["tags"] = [tag for tag in prompt["tags"] if isinstance(tag, str)]
            for field in ("favorite", "template"):
                if field in prompt and type(prompt[field]) is not bool:
                    issues.append(f"{field} 字段格式损坏")
                    prompt[field] = False
            if "usage_count" in prompt and (type(prompt["usage_count"]) is not int or prompt["usage_count"] < 0):
                issues.append("usage_count 字段格式损坏")
                prompt["usage_count"] = 0
            for field in ("created_at", "updated_at", "last_used"):
                if field in prompt and prompt[field] is not None and not isinstance(prompt[field], str):
                    issues.append(f"{field} 字段格式损坏")
                    prompt[field] = None if field == "last_used" else ""
            if not prompt.get("prompt", "").strip():
                issues.append("正文为空")
                prompt.setdefault("prompt", "")
            image = prompt.get("image", "")
            if image and (Path(image).is_absolute() or Path(image).drive or any(char in image for char in '/\\<>:"|?*\x00') or image in {".", ".."}):
                issues.append("预览图路径无效")
                prompt["image"] = ""
            if issues:
                prompt.setdefault("_import_quarantine", {
                    "source": f"categories[{category_index}].prompts[{prompt_index}]",
                    "issues": issues,
                    "raw": raw,
                })
                if not prompt.get("alias"):
                    prompt["alias"] = f"待核查记录 {prompt_index + 1}"
            category["prompts"][prompt_index] = prompt
        original_category_id = category.get("id")
        if not isinstance(original_category_id, str) or not original_category_id:
            if original_category_id is not None:
                category.setdefault("_source_category_id", original_category_id)
            category_key = hashlib.sha256(json.dumps({key: value for key, value in category.items() if key != "prompts"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            category["id"] = "provisional:category:" + category_key
            category["_source_identity"] = None
        category_scope = str(category.get("id"))
        category["_source_scope"] = "weilin:category:" + category_scope
        source_occurrences = {}
        for prompt in category.get("prompts", []) or []:
            original_prompt_id = prompt.get("id")
            prompt["_source_id"] = original_prompt_id
            occurrence_key = (str(original_prompt_id or ""), _import_fingerprint(prompt))
            occurrence = source_occurrences.get(occurrence_key, 0) + 1
            source_occurrences[occurrence_key] = occurrence
            if occurrence > 1:
                # Repeated records in one archive remain separate, while the
                # same archive imported again keeps the same local identities.
                prompt["_source_occurrence"] = occurrence
            if not original_prompt_id:
                prompt_key = _import_fingerprint(prompt)
                prompt["id"] = "provisional:prompt:" + hashlib.sha256((category_scope + ":" + prompt_key).encode("utf-8")).hexdigest()
                prompt["_source_identity"] = None
            prompt["_source_fingerprint"] = _import_fingerprint(prompt)
    return _ensure_data_compatibility(prepared)

def _should_create_route_branch_backup():
    global _ROUTE_BRANCH_LAST_BACKUP_AT
    now = time.time()
    if now - _ROUTE_BRANCH_LAST_BACKUP_AT < _ROUTE_BRANCH_BACKUP_INTERVAL_SEC:
        return False
    _ROUTE_BRANCH_LAST_BACKUP_AT = now
    return True

class PromptSelector:
    """
    提示词选择器节点，用于管理和选择提示词。
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 这个隐藏字段用于从前端接收最终的提示词字符串
                "selected_prompts": ("STRING", {"default": "", "widget": "hidden"}),
            },
            "optional": {
                "prefix_prompt": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "execute"
    CATEGORY = "WeiLin/Prompt Selector"

    def __init__(self):
        # 确保预览图片目录存在
        if not os.path.exists(PREVIEW_DIR):
            os.makedirs(PREVIEW_DIR)

    def execute(self, **kwargs):
        prefix = kwargs.get("prefix_prompt", "")
        # 从前端获取选择的提示词
        selected_prompts_string = kwargs.get("selected_prompts", "")

        # 从 data.json 加载设置以获取分隔符
        separator = ", "
        if os.path.exists(DATA_FILE):
            # Node execution used to parse the whole 118 MB library just for the separator.
            data = _read_prompt_data_cached()
            separator = data.get("settings", {}).get("separator", ", ")

        if prefix and selected_prompts_string:
            final_prompt = f"{prefix}{separator}{selected_prompts_string}"
        elif prefix:
            final_prompt = prefix
        else:
            final_prompt = selected_prompts_string

        return (final_prompt,)

def _prompt_data_signature():
    try:
        stat = os.stat(DATA_FILE)
    except OSError:
        return ()
    return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)


def _projection_signature():
    try:
        stat = os.stat(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
    except OSError:
        return ()
    return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)


def _library_signature():
    """Identity of everything the reviewed view is derived from."""
    return (_prompt_data_signature(), _projection_signature())


def _read_prompt_data_cached():
    global _PROMPT_DATA_CACHE, _PROMPT_DATA_CACHE_SIGNATURE

    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        signature = _prompt_data_signature()
        if _PROMPT_DATA_CACHE is not None and _PROMPT_DATA_CACHE_SIGNATURE == signature:
            return _PROMPT_DATA_CACHE
        # External replacement must not pair bytes from one file with another's signature.
        for _ in range(3):
            signature = _prompt_data_signature()
            data = _json_load_path(DATA_FILE)
            if signature == _prompt_data_signature():
                _PROMPT_DATA_CACHE = data
                _PROMPT_DATA_CACHE_SIGNATURE = signature
                _lib_trace("parse_data", signature=list(signature))
                return data
        raise RuntimeError("词库正在更新，请重试读取")


def _library_state_reset():
    """Drop every derived read model; the next read rebuilds it from source."""
    state = _LIBRARY_STATE
    state["version"] = None
    state["data"] = None
    state["document"] = None
    state["indexed"] = True
    state["entries"].clear()
    state["views"].clear()
    state["rows"].clear()
    state["ranges"].clear()
    state["matches"].clear()
    state["view_index"].clear()
    state["row_index"].clear()
    state["filter_masks"].clear()
    state["filter_scopes"].clear()
    state["index"] = None


def _library_entry(document, category, prompt):
    """The reviewed view of one prompt; the only place binding + subcategories run."""
    decision = decision_for(document, category, prompt)
    semantic = {**decision, "subcategories": selector_subcategories(decision, prompt)}
    semantic["theme_ids"] = sorted(semantic_themes(semantic))
    semantic["refinements"] = [] if semantic.get("declared_usage", semantic.get("usage")) == "negative" else extract_refinements(prompt.get("prompt", ""), semantic["subcategories"], enable_soft_modifier_cues=soft_light_modifier_cue_allowed(decision, category, prompt, selector_subcategories(decision, prompt)))
    return {**prompt, "_semantic": semantic}


def _library_rebuild_locked():
    """Recompute the per-prompt projection once for the current source revision."""
    data = _read_prompt_data_cached()
    version = (_PROMPT_DATA_CACHE_SIGNATURE, _projection_signature())
    document = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
    _library_state_reset()
    entries = _LIBRARY_STATE["entries"]
    indexed = True
    for category in data.get("categories", []) or []:
        for prompt in category.get("prompts", []) or []:
            identity = prompt.get("id")
            entry = _library_entry(document, category, prompt)
            if isinstance(identity, str) and identity and identity not in entries:
                entries[identity] = entry
            else:
                # Duplicate or missing identity: fall back to computing every row inline.
                indexed = False
    state = _LIBRARY_STATE
    state["version"] = version
    state["data"] = data
    state["document"] = document
    state["indexed"] = indexed
    _lib_trace("rebuild", signature=[list(version[0]), list(version[1])], indexed=indexed, entries=len(entries))
    return state


def _library_state_locked():
    """Return the derived read state, rebuilding it whenever the source moved."""
    state = _LIBRARY_STATE
    if state["data"] is not None and state["version"] == _library_signature():
        return state
    _lib_trace("state_miss", cached=None if state["version"] is None else [list(state["version"][0]), list(state["version"][1])],
               current=[list(_prompt_data_signature()), list(_projection_signature())])
    return _library_rebuild_locked()


def _library_view_locked(state, include_pending):
    """The reviewed view (existing entries only; safe to rebuild from the id cache)."""
    key = bool(include_pending)
    view = state["views"].get(key)
    if view is not None:
        return view
    data = state["data"]
    document = state["document"]
    entries = state["entries"]
    indexed = state["indexed"]
    counts = Counter()
    categories = []
    view_index = {}
    for category in data.get("categories", []) or []:
        items = []
        for prompt in category.get("prompts", []) or []:
            identity = prompt.get("id")
            entry = entries.get(identity) if indexed and isinstance(identity, str) else None
            if entry is None:
                entry = _library_entry(document, category, prompt)
                if indexed and isinstance(identity, str) and identity:
                    entries[identity] = entry
            semantic = entry["_semantic"]
            counts[semantic["disposition"]] += 1
            if include_pending or (
                semantic["disposition"] in ("reviewed", "classified")
                and semantic["manual_search_eligible"]
            ):
                if isinstance(identity, str) and identity:
                    view_index[identity] = (len(categories), len(items))
                items.append(entry)
        categories.append({**category, "prompts": items})
    view = {**data, "categories": categories, "_review_counts": dict(counts),
        "_semantic_class_labels": {**document.get("class_labels", {}), **CLASS_LABELS},
        "_selection_projection": "S4-semantic-projection-v1"}
    state["views"][key] = view
    state["view_index"][key] = view_index
    return view


def _build_library_rows(view):
    """Flat rows plus per-category ranges.

    A row is ``(prompt, category identity, category name, folded name, search names,
    search body)``: the search fields are precomputed once per revision so a query does
    not rebuild the casefolded term lists for all 100k rows on every request.
    """
    rows = []
    ranges = []
    for category in view.get("categories", []) or []:
        start = len(rows)
        identity = str(category.get("id") or category.get("name") or "")
        name = str(category.get("name") or "")
        folded = name.casefold()
        for prompt in category.get("prompts", []) or []:
            names, body = _search_terms(prompt)
            rows.append((prompt, identity, name, folded, names, body))
        ranges.append((identity, name, start, len(rows)))
    return rows, ranges


def _search_terms(prompt):
    """Same term extraction `_prompt_search_rank` performs, but once per prompt."""
    def terms(values):
        result = []
        for value in values:
            if isinstance(value, (list, tuple)):
                result.extend(terms(value))
            elif isinstance(value, str) and value.strip():
                result.append(value.strip().casefold())
        return result
    names = terms([prompt.get("alias"), prompt.get("aliases"), prompt.get("name"),
                   prompt.get("name_zh"), prompt.get("nickname")])
    body = terms([prompt.get("prompt"), prompt.get("description"), prompt.get("tags")])
    return names, body


def _rank_terms(names, body, folded_category, query):
    """Ranking over precomputed terms; identical outcome to `_prompt_search_rank`."""
    if query in names:
        return 0
    for name in names:
        if name.startswith(query):
            return 1
    for value in names:
        if query in value:
            return 2
    for value in body:
        if query in value:
            return 3
    return 4 if query in folded_category else None


def _search_match_reason(rank):
    return ('名称或别名精确匹配', '名称或别名前缀匹配', '名称或别名包含',
            '正文命中', '分类命中')[rank]


def _library_rows_for(state, include_pending, view):
    """Rows of ``view``; only the view this module built is cached for reuse."""
    key = bool(include_pending)
    own_view = state["views"].get(key) is view
    if own_view and state["rows"].get(key) is not None:
        return state["rows"][key], state["ranges"][key]
    rows, ranges = _build_library_rows(view)
    if own_view:
        state["rows"][key] = rows
        state["ranges"][key] = ranges
        state["row_index"][key] = {}
        index = state["row_index"][key]
        for position, row in enumerate(rows):
            identity = row[0].get("id")
            if isinstance(identity, str) and identity:
                index[identity] = position
    return rows, ranges


def _library_entry_in_view(entry, include_pending):
    """The same visibility rule ``_library_view_locked`` applies."""
    semantic = entry.get("_semantic") or {}
    return bool(include_pending or (
        semantic.get("disposition") in ("reviewed", "classified")
        and semantic.get("manual_search_eligible")))


def _patch_derived_caches(state, data, changed_ids):
    """Keep the cached views and row ordering when the changed rows stayed put.

    Only the safe shape is patched: every changed prompt must still exist, keep its
    category, keep its visibility, keep its disposition (so ``_review_counts`` stays
    right) and keep its position. Anything else returns False and the caller falls
    back to a full rebuild, which is always correct.

    ``matches`` is dropped either way — it is a list of row positions filtered by
    usage/theme/collection, so a content edit can change it, and recomputing it costs
    a small fraction of the ordering rebuild.
    """
    changed = {str(identity) for identity in changed_ids if identity}
    if not changed:
        return False
    locations = {}
    for category_position, category in enumerate(data.get("categories", []) or []):
        identity = str(category.get("id") or category.get("name") or "")
        name = str(category.get("name") or "")
        for prompt in category.get("prompts", []) or []:
            prompt_id = prompt.get("id")
            if prompt_id in changed:
                locations[prompt_id] = (category_position, identity, name)
    if len(locations) != len(changed):
        return False
    entries = state["entries"]
    # Fields the view copies from the document: a patch must refresh them or the
    # view would keep serving the previous revision (the ETag feeds save conflicts).
    derived = {"categories", "_review_counts", "_semantic_class_labels", "_selection_projection"}
    for key in (False, True):
        view = state["views"].get(key)
        if view is None:
            continue
        view_index = state["view_index"].get(key)
        rows = state["rows"].get(key)
        row_index = state["row_index"].get(key)
        if view_index is None or rows is None or row_index is None:
            return False
        view_categories = view["categories"]
        for prompt_id, (category_position, identity, name) in locations.items():
            entry = entries.get(prompt_id)
            placement = view_index.get(prompt_id)
            if category_position >= len(view_categories):
                return False
            category = view_categories[category_position]
            if str(category.get("id") or category.get("name") or "") != identity:
                return False
            eligible = entry is not None and _library_entry_in_view(entry, key)
            if placement is None:
                if eligible:
                    return False          # the row has to appear now
                continue
            if not eligible:
                return False              # the row has to leave the view
            if placement[0] != category_position:
                return False              # the row moved between categories
            previous = category["prompts"][placement[1]]
            if (previous.get("_semantic") or {}).get("disposition") != \
                    (entry.get("_semantic") or {}).get("disposition"):
                return False              # _review_counts would go stale
            category["prompts"][placement[1]] = entry
            position = row_index.get(prompt_id)
            if position is None:
                return False
            names, body = _search_terms(entry)
            rows[position] = (entry, identity, name, name.casefold(), names, body)
        for name_of_field, value in data.items():
            if name_of_field not in derived:
                view[name_of_field] = value
        state["views"][key] = view
    state["matches"].clear()
    state["filter_masks"].clear()
    state["filter_scopes"].clear()
    state["index"] = None
    return True


def _cache_prompt_data(data, changed_ids=None):
    """Install a just-committed library document.

    ``changed_ids`` names every prompt the caller rewrote, so the derived projection
    is patched instead of dropped: the next read reuses ~93k bindings and only
    recomputes the touched rows. Anything ambiguous falls back to a full rebuild.
    """
    global _PROMPT_DATA_CACHE, _PROMPT_DATA_CACHE_SIGNATURE

    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        _PROMPT_DATA_CACHE = data
        _PROMPT_DATA_CACHE_SIGNATURE = _prompt_data_signature()
        version = (_PROMPT_DATA_CACHE_SIGNATURE, _projection_signature())
        state = _LIBRARY_STATE
        if changed_ids is None or state["data"] is None or not state["indexed"] \
                or state["version"] is None or state["version"][1] != version[1]:
            _lib_trace("cache_reset", changed=None if changed_ids is None else len(changed_ids),
                       has_data=state["data"] is not None, indexed=state["indexed"],
                       projection_changed=state["version"] is not None and state["version"][1] != version[1])
            _library_state_reset()
            return
        entries = state["entries"]
        document = state["document"]
        wanted = {str(identity) for identity in changed_ids if identity}
        found = set()
        total = 0
        for category in data.get("categories", []) or []:
            for prompt in category.get("prompts", []) or []:
                total += 1
                identity = prompt.get("id")
                if identity in wanted:
                    entries[identity] = _library_entry(document, category, prompt)
                    found.add(identity)
        for identity in wanted - found:
            entries.pop(identity, None)
        if len(entries) != total:
            # A caller under-reported its change set; rebuild rather than serve a stale view.
            _lib_trace("cache_reset", reason="count", entries=len(entries), total=total)
            _library_state_reset()
            return
        state["data"] = data
        state["version"] = version
        # A favourite, a usage stamp, a note or a preview swap keeps its row in place,
        # so the 100k-row ordering can be patched instead of rebuilt (measured 721 ms).
        if _patch_derived_caches(state, data, found):
            _lib_trace("cache_patch", changed=sorted(found), rows="patched",
                       signature=[list(version[0]), list(version[1])])
            return
        state["views"].clear()
        state["rows"].clear()
        state["ranges"].clear()
        state["matches"].clear()
        state["view_index"].clear()
        state["row_index"].clear()
        state["filter_masks"].clear()
        state["filter_scopes"].clear()
        state["index"] = None
        _lib_trace("cache_patch", changed=sorted(found), signature=[list(version[0]), list(version[1])])


def _reviewed_library_data(include_pending=False):
    # Retain only the current normal/review views. File identity and both revisions
    # are checked on every read; a missing/broken/new projection never uses an old view.
    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        for _ in range(3):
            state = _library_state_locked()
            version = state["version"]
            key = bool(include_pending)
            view = state["views"].get(key)
            if view is not None:
                return view
            view = _library_view_locked(state, key)
            if _library_signature() == version:
                return view
            _library_state_reset()
        raise ValueError("资料或分类版本正在变化，请刷新后重试")


@PromptServer.instance.routes.get('/prompt_selector/library/revision')
async def get_library_revision(request):
    data = await asyncio.to_thread(_read_prompt_data_cached)
    return _with_etag(web.json_response({'revision': _revision(data)}), _revision(data))


def _selector_favorites_state():
    data = _read_prompt_data_cached()
    state = data.get('selector_library')
    if not state:
        raise ValueError('Selector library migration has not completed')
    document = read_projection(os.path.join(PROMPT_STORE_DIR, 'semantic_projection.json'))
    view = favorites_view(data, document, state.get('legacy_favorites', {}))
    encoded = json.dumps([_revision(data), view], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    etag = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    return data, document, view, etag


async def get_selector_favorites(request):
    try:
        _, _, view, etag = await asyncio.to_thread(_selector_favorites_state)
        return _with_etag(web.json_response(view), etag)
    except Exception as error:
        return web.json_response({'error': str(error)}, status=503)


def _save_selector_favorites(body, expected):
    with _PROMPT_FILE_LOCK:
        current, document, view, etag = _selector_favorites_state()
        if expected != etag:
            raise RevisionConflict(expected, etag)
        updated = json.loads(json.dumps(current))
        apply_favorites(updated, document, body, view, datetime.now().isoformat())
        for key, value in body.items():
            if key not in updated['selector_library']['kinds']:
                updated['selector_library']['legacy_favorites'][key] = value
        _atomic_save_json(DATA_FILE, updated, compact=True, create_backup=True, expected_revision=_revision(current))
        _cache_prompt_data(updated)
        return _selector_favorites_state()[3]


async def save_selector_favorites(request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Favorites must be an object')
        async with _PROMPT_DATA_LOCK:
            etag = await asyncio.to_thread(_save_selector_favorites, body, _request_revision(request))
        return _with_etag(web.json_response({'success': True, 'etag': etag}), etag)
    except RevisionConflict as error:
        return _with_etag(web.json_response({'error': str(error), 'etag': error.actual}, status=409), error.actual)
    except Exception as error:
        return web.json_response({'error': str(error)}, status=400)


# Existing Anima endpoints delegate to the source owner's atomic transaction.
PromptServer.instance.weilin_selector_favorites = (get_selector_favorites, save_selector_favorites)


def _apply_collection_update(payload):
    with _PROMPT_FILE_LOCK:
        current = _read_prompt_data_cached()
        _require_revision(payload, current)
        updated = json.loads(json.dumps(current))
        changed = update_collection(updated, payload)
        if changed:
            updated['last_modified'] = datetime.now().isoformat()
            _atomic_save_json(DATA_FILE, updated, compact=True, create_backup=_should_create_route_branch_backup(),
                expected_revision=_revision(current))
            _cache_prompt_data(updated)
        return {'success': True, 'changed': changed, 'revision': _revision(updated),
            'groups': collection_groups(updated)}


@PromptServer.instance.routes.get('/prompt_selector/collections/index')
async def get_collection_index(request):
    data = await asyncio.to_thread(_read_prompt_data_cached)
    return _success_response({'groups': collection_groups(data), 'revision': _revision(data)})


@PromptServer.instance.routes.post('/prompt_selector/collections/update')
async def update_selector_collection(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('收藏组操作必须是对象')
        payload['base_revision'] = _request_revision(request, payload)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_collection_update, payload)
        return _success_response(result)
    except RevisionConflict as error:
        return _with_etag(web.json_response({'error': str(error), 'conflict': True, 'current_revision': error.actual}, status=409), error.actual)
    except KeyError as error:
        return web.json_response({'error': str(error)}, status=404)
    except ValueError as error:
        return web.json_response({'error': str(error)}, status=400)


def parse_pool_filters(raw):
    """把 `轴:值;轴:值` 解析成 {轴: [值]}；轴 ∈ theme/sub/detail/facet/count。"""
    result = {}
    for chunk in str(raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        axis, value = chunk.split(":", 1)
        axis = axis.strip()
        if axis == "subcategory":   # 前端池子里的键名，等价于 sub
            axis = "sub"
        value = value.strip()
        if axis not in ("theme", "sub", "detail", "facet", "count") or not value:
            continue
        result.setdefault(axis, [])
        if value not in result[axis]:
            result[axis].append(value)
    return result


def pool_filter_hit(semantic, filters, mode="any"):
    """小主题按大主题分组，细分按父小主题分组；不同组同时满足。"""
    groups = {}
    themes = semantic_themes(semantic)
    for axis, values in (filters or {}).items():
        for value in values:
            if axis == "facet":
                value = FACET_CLASS_MAP.get(value, value)
                group, hit = "theme", value in themes
            elif axis == "theme":
                theme_ids = {"style_medium", "quality_detail"} if value == "style_quality" else {value}
                group, hit = "theme", bool(theme_ids.intersection(themes))
            elif axis == "sub":
                explicit_owner, separator, label = value.partition("::")
                qualified = separator and explicit_owner in CLASS_LABELS
                if qualified:
                    owner, value = explicit_owner, label
                else:
                    owner = SUBCATEGORY_PARENTS.get(value) or SUBCATEGORY_PARENTS.get(value.split("/", 1)[0])
                group = "sub:" + (owner or value)
                hit = any((label == value or label.startswith(value + "/"))
                          and (not qualified or subcategory_owner(semantic, label) == owner)
                          for label in semantic.get("subcategories", []))
            elif axis == "detail":
                node = REFINEMENT_NODES.get(value)
                if node is None:
                    return False
                group = "detail:" + node["parent"]
                hit = value in (semantic.get("refinements") or []) and any(
                    label == node["parent"] or label.startswith(node["parent"] + "/")
                    for label in semantic.get("subcategories", []))
            else:
                group, hit = "sub:person_count", value in (semantic.get("count_markers") or [])
            groups.setdefault(group, []).append(hit)
    for hits in groups.values():
        if not (all(hits) if mode == "all" else any(hits)):
            return False
    return True


def _library_index_payload():
    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        data = _reviewed_library_data()
        state = _LIBRARY_STATE
        payload = state["index"]
        if payload is not None and state["views"].get(False) is data:
            return payload
        categories = []
        for category in data.get("categories", []) or []:
            summary = {key: value for key, value in category.items() if key != "prompts"}
            summary["prompt_count"] = len(category.get("prompts", []) or [])
            summary["prompts"] = []
            categories.append(summary)
        # One pass collects the per-class subcategory vocabulary; the previous shape
        # walked every prompt once per class label.
        subcategories = {key: set() for key in data.get("_semantic_class_labels", {})}
        # 小主题只使用词表声明的归属，数据量变化不会让它换父主题。
        pool_themes = Counter()
        pool_subcategories = {}
        subcategory_owners = {}
        unknown_subcategories = Counter()
        pool_facets = Counter()
        pool_counts = Counter()
        pool_refinements = Counter()
        for category in data.get("categories", []) or []:
            for prompt in category.get("prompts", []) or []:
                semantic = prompt["_semantic"]
                for theme in semantic_themes(semantic):
                    if theme:
                        pool_themes[theme] += 1
                for label in set(semantic.get("subcategories") or []):
                    owner = subcategory_owner(semantic, label)
                    if owner:
                        subcategory_owners.setdefault(label, set()).add(owner)
                        subcategories.setdefault(owner, set()).add(label)
                        pool_subcategories.setdefault(owner, Counter())[label] += 1
                    else:
                        unknown_subcategories[label] += 1
                for facet in set(semantic.get("themes") or []):
                    pool_facets[facet] += 1
                for marker in set(semantic.get("count_markers") or []):
                    pool_counts[marker] += 1
                pool_refinements.update(set(semantic.get("refinements") or []))
        conflicting_subcategories = {}
        subcategory_values = {}
        for label, owners in subcategory_owners.items():
            if len(owners) > 1:
                conflicting_subcategories[label] = {owner: pool_subcategories[owner].pop(label) for owner in sorted(owners)}
                for owner in owners:
                    subcategories[owner].discard(label)
            elif not subcategory_owner({}, label):
                subcategory_values[label] = next(iter(owners)) + "::" + label
        refinements = {}
        for identity, count in pool_refinements.most_common():
            node = REFINEMENT_NODES[identity]
            refinements.setdefault(node["parent"], []).append({
                "id": identity, "label": node["label"], "parent": node["parent"],
                "owner": node["owner"], "count": count,
                "tags": node["tags"],
            })
        payload = {
            "version": data.get("version", "1.6"),
            "settings": data.get("settings", {}),
            "last_modified": data.get("last_modified"),
            "categories": categories,
            "total_prompts": sum(category["prompt_count"] for category in categories),
            "review_counts": data["_review_counts"],
            "semantic_classes": data.get("_semantic_class_labels", {}),
            "selector_groups": {kind: collection_groups(data) for kind in COLLECTION_KINDS},
            "selector_class_kinds": {key: route[0] for key, route in CLASS_ROUTES.items()},
            "semantic_subcategories": {key: sorted(value) for key, value in subcategories.items()},
            "filter_pool": {
                "theme": dict(pool_themes.most_common()),
                "subcategory": {key: dict(value.most_common()) for key, value in pool_subcategories.items()},
                "subcategory_values": subcategory_values,
                "facet": dict(pool_facets.most_common()),
                "count": dict(pool_counts.most_common()),
                "refinements": refinements,
                "refinement_version": REFINEMENT_VERSION,
                "unmapped_subcategories": dict(unknown_subcategories.most_common()),
                "conflicting_subcategories": conflicting_subcategories,
            },
        }
        if state["views"].get(False) is data:
            state["index"] = payload
        return payload


def _prompt_search_rank(prompt, category_name, query):
    """Reference ranking implementation (per-prompt term rebuild).

    The page path uses the precomputed `_rank_terms` fast path; this function stays as the
    semantic reference that `phase4/verify_read_model.py` replays from the previous build.
    """
    if not query:
        return 0
    def terms(values):
        result = []
        for value in values:
            if isinstance(value, (list, tuple)):
                result.extend(terms(value))
            elif isinstance(value, str) and value.strip():
                result.append(value.strip().casefold())
        return result
    names = terms([prompt.get("alias"), prompt.get("aliases"), prompt.get("name"), prompt.get("name_zh"), prompt.get("nickname")])
    if query in names:
        return 0
    if any(name.startswith(query) for name in names):
        return 1
    body = terms([prompt.get("prompt"), prompt.get("description"), prompt.get("tags")])
    if any(query in value for value in names):
        return 2
    if any(query in value for value in body):
        return 3
    return 4 if query in category_name.casefold() else None


def _library_scope_rows(ranges, category_id, source_category, view):
    """Row indices a request may see: one category branch, or every row of the view."""
    if not source_category or view == "review":
        return None, ""
    ranges = ranges or []
    wanted = str(category_id or "")
    selected = next((record for record in ranges if wanted in (record[0], record[1])), None)
    if selected is None:
        return array("i"), ""
    name = selected[1]
    scoped = array("i")
    for record in ranges:
        if record[1] == name:
            scoped.extend(range(record[2], record[3]))
    return scoped, name


def _library_matches(library, rows, scope, view, semantic_class, theme_classes, usage,
                     content_type, subcategory, collection, normalized_query,
                     pool_filters=None, pool_mode="any"):
    """Row indices matching one page request, in delivery order."""
    known_groups = {group['id'] for group in collection_groups(library)}
    if collection and collection not in known_groups:
        raise ValueError('收藏组已不存在，请刷新列表')
    indices = range(len(rows)) if scope is None else scope
    # A query orders rows by (score, row index). Bucketing by score while scanning gives
    # that order without sorting the whole match set.
    ranked = bool(normalized_query) and view != "recent"
    buckets = [array("i") for _ in range(5)] if ranked else None
    matches = []
    for index in indices:
        prompt, _identity, category_name, folded_category, names, body = rows[index]
        semantic = prompt["_semantic"]
        if collection:
            memberships = [value for value in prompt_collection(prompt).get('groupIds', []) if value in known_groups] or ['default']
            if collection not in memberships:
                continue
        if view == "review" and semantic["disposition"] in ("reviewed", "classified"):
            continue
        if semantic_class and not theme_classes.intersection(semantic_themes(semantic)):
            continue
        if subcategory and not any(label == subcategory or label.startswith(subcategory + '/') for label in semantic.get('subcategories', [])):
            continue
        if pool_filters and not pool_filter_hit(semantic, pool_filters, pool_mode):
            continue
        if view == "templates" and semantic["content_type"] != "template":
            continue
        if view == "common" and not normalized_query and not (prompt.get("favorite") is True or bool(prompt.get("last_used"))):
            continue
        if view == "plans" and prompt.get("is_user_plan") is not True:
            continue
        if view == "favorites" and prompt.get("favorite") is not True:
            continue
        if view == "recent" and not prompt.get("last_used"):
            continue
        if usage and semantic.get("declared_usage", semantic.get("usage")) != usage:
            continue
        if content_type and semantic.get("content_type") != content_type:
            continue
        if ranked:
            rank = _rank_terms(names, body, folded_category, normalized_query)
            if rank is None:
                continue
            buckets[rank].append(index)
        else:
            if normalized_query and _rank_terms(names, body, folded_category, normalized_query) is None:
                continue
            matches.append(index)

    if ranked:
        combined = array("i")
        for bucket in buckets:
            combined.extend(bucket)
        return combined
    if view == "common" and not normalized_query:
        matches.sort(key=lambda index: str(rows[index][0].get("last_used") or ""), reverse=True)
        matches.sort(key=lambda index: not (rows[index][0].get("favorite") is True))
    elif view == "recent":
        matches.sort(key=lambda index: str(rows[index][0].get("last_used") or ""), reverse=True)
    return array("i", matches)


def _library_page_payload(category_id, query, offset, limit, view="", usage="", content_type="", theme="",
                          subcategory="", collection="", pool_filters="", pool_mode="any", include_filter_counts=False):
    normalized_query = str(query or "").strip().casefold()
    offset = max(0, int(offset or 0))
    limit = min(_LIBRARY_PAGE_SIZE_MAX, max(1, int(limit or _LIBRARY_PAGE_SIZE)))
    include_pending = view == "review"
    view = str(view or "").strip().casefold()
    if view not in {"", "all", "common", "favorites", "recent", "plans", "templates", "categories", "review"}:
        view = ""
    semantic_class = str(category_id).removeprefix("semantic:") if str(category_id).startswith("semantic:") else ""
    source_category = bool(category_id) and not semantic_class
    semantic_class = str(theme or semantic_class)
    theme_classes = {'style_medium', 'quality_detail'} if semantic_class == 'style_quality' else {semantic_class}
    if usage not in ("", "positive", "negative", "mixed", "unknown"):
        raise ValueError("Unknown usage filter")
    if content_type not in ("", "atomic_tag", "fragment", "template", "model_reference"):
        raise ValueError("Unknown content form filter")
    parsed_pool = parse_pool_filters(pool_filters)
    pool_mode = "all" if str(pool_mode or "").strip().casefold() == "all" else "any"
    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        data = _reviewed_library_data(include_pending)
        state = _LIBRARY_STATE
        reusable = state["views"].get(bool(include_pending)) is data
        rows, ranges = _library_rows_for(state, include_pending, data)
        scope, selected_name = _library_scope_rows(ranges, category_id, source_category, view)
        if source_category and view != "review" and not selected_name:
            return {
                "last_modified": data.get("last_modified"),
                "items": [],
                "total": 0,
                "offset": offset,
                "limit": limit,
                "has_more": False,
                "category_id": category_id,
                "category_name": "",
                "query": "",
                "view": view,
                **({'filter_counts': {'theme': {}, 'subcategory': {}, 'count': {}, 'detail': {}, 'mode': pool_mode}} if include_filter_counts else {}),
            }
        key = (include_pending, selected_name, view, usage, content_type, semantic_class,
               subcategory, collection, normalized_query, repr(sorted(parsed_pool.items())), pool_mode)
        matched = state["matches"].get(key) if reusable else None
        if matched is None:
            matched = _library_matches(data, rows, scope, view, semantic_class, theme_classes,
                                       usage, content_type, subcategory, collection, normalized_query,
                                       parsed_pool, pool_mode)
            if reusable:
                if len(state["matches"]) >= _LIBRARY_MATCH_CACHE_LIMIT:
                    state["matches"].clear()
                state["matches"][key] = matched
        total = len(matched)
        page_end = offset + limit
        page_items = [{**rows[index][0], "_categoryId": rows[index][1], "_categoryName": rows[index][2],
                       **({"match_reason": _search_match_reason(_rank_terms(rows[index][4], rows[index][5],
                                                                        rows[index][3], normalized_query))}
                          if normalized_query else {})}
                      for index in matched[offset:offset + limit]]
        extra = {}
        if include_filter_counts:
            masks = state['filter_masks'].get(bool(include_pending)) if reusable else None
            if masks is None:
                masks = build_filter_masks(rows)
                if reusable:
                    state['filter_masks'][bool(include_pending)] = masks
            scope_key = key[:-2]
            base = state['filter_scopes'].get(scope_key) if reusable else None
            if base is None:
                scoped_matches = matched if not parsed_pool else _library_matches(
                    data, rows, scope, view, semantic_class, theme_classes,
                    usage, content_type, subcategory, collection, normalized_query)
                base = row_mask(scoped_matches, len(rows))
                if reusable:
                    if len(state['filter_scopes']) >= _LIBRARY_MATCH_CACHE_LIMIT:
                        state['filter_scopes'].clear()
                    state['filter_scopes'][scope_key] = base
            extra['filter_counts'] = conditional_filter_counts(masks, base, parsed_pool, pool_mode, _library_index_payload()['filter_pool'])
        return {
            "last_modified": data.get("last_modified"),
            "items": page_items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": page_end < total,
            "category_id": category_id,
            "category_name": selected_name,
            "query": str(query or "").strip(),
            "view": view,
            "review_counts": data["_review_counts"],
            **extra,
        }


def _safe_preview_source(filename):
    safe_name = os.path.basename(str(filename or ""))
    if not safe_name or safe_name != filename:
        return None
    source_path = os.path.abspath(os.path.join(PREVIEW_DIR, safe_name))
    preview_root = os.path.abspath(PREVIEW_DIR) + os.sep
    if not source_path.startswith(preview_root) or not os.path.isfile(source_path):
        return None
    return source_path


def _ensure_preview_thumbnail(filename):
    source_path = _safe_preview_source(filename)
    if source_path is None:
        raise FileNotFoundError(filename)

    digest = hashlib.sha1(filename.encode("utf-8", errors="ignore")).hexdigest()
    thumbnail_path = os.path.join(THUMBNAIL_DIR, f"{digest}.webp")
    if (
        os.path.isfile(thumbnail_path)
        and os.path.getmtime(thumbnail_path) >= os.path.getmtime(source_path)
    ):
        return thumbnail_path

    temp_path = f"{thumbnail_path}.{uuid.uuid4().hex}.tmp"
    try:
        with Image.open(source_path) as image:
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            has_alpha = image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            )
            image = image.convert("RGBA" if has_alpha else "RGB")
            image.thumbnail((480, 360), Image.Resampling.LANCZOS)
            image.save(temp_path, format="WEBP", quality=82, method=4)
        os.replace(temp_path, thumbnail_path)
        return thumbnail_path
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


# --- API 路由 ---

_PACKED_LIBRARY_CACHE = {"revision": None, "packed": None}

# 「标签 tags 串」按法典原分组并入「提示词片段」：分类以资源库分类的形态出现，
# 直接读 tag 字典那一份数据（不复制 27.5 万行，主库保持 118 MB、写入与检索速度不变）。
_STRING_CATEGORY_CACHE = {'revision': None, 'value': None, 'used': 0.0}
_STRING_CATEGORY_IDLE_SECONDS = 600.0
# 2026-09-16：法典串已经"真建成"资源库条目（phase4/materialize_string_categories.py），
# 虚拟的「法典串分类」不再发布，避免两边重复。要回退成虚拟分类把它设成 True 即可。
SHOW_STRING_CATEGORY_SOURCE = False
_STRING_CATEGORY_LOCK = threading.RLock()


def _prompt_store_paths():
    """Lazy import: the tag dictionary lives next to the library, but this module must not
    import the tag API at load time (that would close an import cycle)."""
    from .tag_library import TagLibrary
    try:
        from ..app.server.dao import dao
        path = dao.tags_db_path
    except ImportError:
        # The read-model harness imports this package in isolation; fall back to the
        # plugin's default dictionary path.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'user_data', 'userdatas_zh_CN_tags.db')
    return TagLibrary(path)


def _tag_string_categories():
    """法典串分组，按资源库分类的形状返回（id = ``tagstr:<子夹 uuid>``）。"""
    if not SHOW_STRING_CATEGORY_SOURCE:
        return []
    tags = _prompt_store_paths()
    with tags.connection() as conn:
        conn.row_factory = sqlite3.Row
        revision = tags.text_revision_of(conn)
        with _STRING_CATEGORY_LOCK:
            cached = _STRING_CATEGORY_CACHE.get('value')
            if cached is not None:
                if _STRING_CATEGORY_CACHE.get('revision') == revision \
                        and time.monotonic() - _STRING_CATEGORY_CACHE.get('used', 0.0) < _STRING_CATEGORY_IDLE_SECONDS:
                    _STRING_CATEGORY_CACHE['used'] = time.monotonic()
                    return cached
                _STRING_CATEGORY_CACHE['value'] = None
                from .tag_library import release_string_caches
                release_string_caches()
            layout = tags.string_layout(conn, revision)
            areas = {row['p_uuid']: row['name'] for row in conn.execute('SELECT p_uuid, name FROM tag_groups')}
            value = []
            # 资源库已经有同名分类的：若它条数不少于法典串行数，就说明这批内容在片段里
            # 已经有家了，不再重复列一份；条数更少的保留法典串这一份，并标注差多少。
            existing = {_path_joined(category.get('name')): category.get('prompt_count') or 0
                        for category in _library_index_payload().get('categories', [])}
            merged = 0
            for g_uuid, record in layout['folders'].items():
                if g_uuid not in layout['string_folders']:
                    continue
                area_name = areas.get(record['area_uuid']) or record['area_name']
                name = _path_joined(f"{area_name} / {record['name']}")
                have = existing.get(name)
                if have is not None and have >= record['rows']:
                    merged += 1
                    continue
                entry = {'id': 'tagstr:' + g_uuid, 'name': name, 'prompts': [],
                         'prompt_count': record['rows'], 'created_at': '', 'updated_at': '',
                         'strings': True}
                if have is not None:
                    entry['name'] = f"{name}（法典串补充 {record['rows'] - have} 条）"
                    entry['library_entries'] = have
                value.append(entry)
            value.sort(key=lambda item: item['name'])
            logger.info("[Workbench] 法典串分类 %d 个（另有 %d 个已与资源库同名分类合并）",
                        len(value), merged)
            _STRING_CATEGORY_CACHE['revision'] = revision
            _STRING_CATEGORY_CACHE['value'] = value
            _STRING_CATEGORY_CACHE['used'] = time.monotonic()
            return value


def _path_joined(text):
    return _re_module.sub(r'\s*/\s*', ' / ', str(text or '')).strip()


def _tag_string_page(category_id, query, offset, limit):
    """法典串分类的一页，形状与资源库分页一致（前端无需区分数据来源）。"""
    from .tag_library import STRING_GROUP_UUID  # noqa: F401  (kept for symmetry / future use)
    g_uuid = category_id.split(':', 1)[1]
    tags = _prompt_store_paths()
    result = tags.page(query=query, subgroup=g_uuid, offset=offset, limit=limit, scope='strings')
    name = next((item['name'] for item in _tag_string_categories() if item['id'] == category_id), '法典串')
    items = []
    revision = result.get('revision')
    for row in result['items']:
        text = str(row.get('text') or '')
        parts = [part for part in text.replace('，', ',').split(',') if part.strip()]
        items.append({
            'id': 'tag:' + row['t_uuid'], 'alias': (str(row.get('desc') or '').strip() or text)[:120],
            'prompt': text, 'description': '', 'tags': [], 'strings': True,
            'favorite': bool(row.get('favorite')), 'template': False, 'is_user_plan': False,
            'created_at': row.get('create_time'), 'updated_at': row.get('update_time'),
            # 编辑时带回来的 CAS 版本（tag 字典的 revision）。
            '_revision': revision,
            'match_reason': row.get('match_reason', ''),
            # 自己绑定的预览图（存在 tag 元数据里，缩略图走同一个 /thumbnail 接口）。
            'image': row.get('preview') or '',
            # 这条在别的法典区域里也归到哪些子夹（多区域归属，和 tag 侧一致）。
            'folder_ids': list(row.get('folder_ids') or []),
            '_categoryId': category_id, '_categoryName': name,
            '_semantic': {'primary_class': None, 'alternative_classes': [], 'subcategories': [],
                          'content_type': 'template' if len(parts) > 1 else 'atomic_tag',
                          'usage': 'positive', 'declared_usage': 'positive',
                          'manual_search_eligible': True, 'note': ''},
        })
    return {'last_modified': result.get('revision'), 'items': items, 'total': result['total'],
            'offset': result['offset'], 'limit': result['limit'],
            'has_more': result['offset'] + len(items) < result['total'],
            'category_id': category_id, 'category_name': name, 'query': str(query or ''),
            'view': 'all', 'strings': True}


def _json_library_bytes():
    """Serialise the reviewed library; the compact form is ~116 MB, so keep it off the loop."""
    return _json_dump_bytes(_reviewed_library_data())


def _packed_library_payload():
    """Serialise once per revision and cache the gzip form (~10 MB) for repeat reads."""
    payload = _reviewed_library_data()
    revision = _revision(payload)
    if _PACKED_LIBRARY_CACHE["revision"] == revision and _PACKED_LIBRARY_CACHE["packed"] is not None:
        return revision, _PACKED_LIBRARY_CACHE["packed"]
    raw = _json_dump_bytes(payload)
    packed = gzip.compress(raw, 6)
    del raw
    _PACKED_LIBRARY_CACHE["revision"] = revision
    _PACKED_LIBRARY_CACHE["packed"] = packed
    return revision, packed


@PromptServer.instance.routes.get("/prompt_selector/data")
async def get_data(request):
    if not os.path.exists(DATA_FILE):
        return web.json_response({"error": "Data file not found"}, status=404)
    try:
        revision, packed = await asyncio.to_thread(_packed_library_payload)
        headers = {"ETag": f'"{revision}"', "Cache-Control": "no-store"}
        if "gzip" in str(request.headers.get("Accept-Encoding", "")).lower():
            headers["Content-Encoding"] = "gzip"
            return web.Response(body=packed, content_type="application/json", headers=headers)
        body = await asyncio.to_thread(_json_library_bytes)
        return web.Response(body=body, content_type="application/json", headers=headers)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def _resolve_saved_selection(selections, weights):
    """Rebuild a saved node output in library order without sending the library to a browser."""
    if not isinstance(selections, dict) or not isinstance(weights, dict):
        raise ValueError("Invalid saved selection")
    data = _reviewed_library_data()
    selected = []
    for category in data.get("categories", []):
        name = category.get("name")
        saved = selections.get(name)
        if isinstance(saved, list):
            chosen = set(value for value in saved if isinstance(value, str))
        elif isinstance(saved, dict):
            chosen = set(saved)
        else:
            continue
        category_weights = weights.get(name)
        category_weights = category_weights if isinstance(category_weights, dict) else {}
        for prompt in category.get("prompts", []):
            body = prompt.get("prompt")
            if body not in chosen:
                continue
            weight = category_weights.get(body) or 1
            if isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight != 1:
                selected.append(f"({body}:{weight:.2f}".rstrip("0").rstrip(".") + ")")
            else:
                selected.append(body)
    separator = data.get("settings", {}).get("separator") or ", "
    return {"output": separator.join(selected), "revision": _revision(data)}


@PromptServer.instance.routes.post("/prompt_selector/library/resolve-selection")
async def resolve_saved_selection(request):
    try:
        payload = await request.json()
        result = await asyncio.to_thread(
            _resolve_saved_selection,
            payload.get("selected_prompts"), payload.get("prompt_weights", {}),
        )
        response = web.json_response(result)
        response.headers["Cache-Control"] = "no-store"
        return response
    except (TypeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        return web.json_response({"error": str(error)}, status=500)


@PromptServer.instance.routes.get("/prompt_selector/library/index")
async def get_library_index(request):
    if not os.path.exists(DATA_FILE):
        return web.json_response({"error": "Data file not found"}, status=404)
    try:
        payload = await asyncio.to_thread(_library_index_payload)
        # 法典串分组以附加分类的形式并入「提示词片段」（数据仍单一存放在 tag 字典）。
        try:
            strings = await asyncio.to_thread(_tag_string_categories)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"[Workbench] 法典串分类未并入提示词片段: {error}")
            strings = []
        if strings:
            payload = {**payload, "categories": [*payload.get("categories", []), *strings],
                       "total_prompts": payload.get("total_prompts", 0)
                       + sum(item.get("prompt_count", 0) for item in strings),
                       "string_categories": len(strings),
                       "string_rows": sum(item.get("prompt_count", 0) for item in strings)}
        response = _with_etag(web.json_response(payload), payload.get("last_modified"))
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.get("/prompt_selector/library/prompts")
async def get_library_prompts_page(request):
    if not os.path.exists(DATA_FILE):
        return web.json_response({"error": "Data file not found"}, status=404)
    category_id = request.query.get("category_id", "")
    if category_id.startswith("tagstr:"):
        try:
            payload = await asyncio.to_thread(
                _tag_string_page, category_id, request.query.get("q", ""),
                request.query.get("offset", 0), request.query.get("limit", _LIBRARY_PAGE_SIZE))
            response = _with_etag(web.json_response(payload), payload.get("last_modified"))
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as error:  # noqa: BLE001
            logger.warning(f"[Workbench] 法典串分页失败: {error}")
            return web.json_response({"error": str(error)}, status=500)
    try:
        payload = await asyncio.to_thread(
            _library_page_payload,
            request.query.get("category_id", ""),
            request.query.get("q", ""),
            request.query.get("offset", 0),
            request.query.get("limit", _LIBRARY_PAGE_SIZE),
            request.query.get("view", ""),
            request.query.get("usage", ""),
            request.query.get("content_type", ""),
            request.query.get("theme", ""),
            request.query.get("subcategory", ""),
            request.query.get("collection", ""),
            ";".join(request.query.getall("filter", [])),
            request.query.get("filter_mode", "any"),
            request.query.get("include_filter_counts") == "1",
        )
        response = _with_etag(web.json_response(payload), payload.get("last_modified"))
        response.headers["Cache-Control"] = "no-store"
        return response
    except (TypeError, ValueError) as e:
        return web.json_response({"error": f"Invalid pagination: {e}"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.get("/prompt_selector/library/prompt")
async def get_library_prompt(request):
    """Read one prompt by its stable id for an explicit editor conflict review."""
    prompt_id = str(request.query.get("prompt_id") or "").strip()
    category_id = str(request.query.get("category_id") or "").strip()
    if not prompt_id:
        return web.json_response({"error": "Missing prompt_id"}, status=400)
    if not os.path.exists(DATA_FILE):
        return web.json_response({"error": "Data file not found"}, status=404)
    try:
        data = _ensure_data_compatibility(_json_load_path(DATA_FILE))
        requested_id = prompt_id
        mapped = merged_source(data, prompt_id, category_id)
        if mapped:
            category_id = str(mapped[0]['id'])
            prompt_id = str(mapped[1]['id'])
        for category in data.get("categories", []):
            identity = str(category.get("id") or category.get("name") or "")
            if category_id and identity != category_id:
                continue
            for prompt in category.get("prompts", []) or []:
                if str(prompt.get("id") or "") == prompt_id:
                    if request.query.get("selection") == "1" or request.query.get("include_semantic") == "1":
                        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
                        decision = decision_for(projection, category, prompt)
                        if request.query.get("selection") == "1" and (decision.get("disposition") not in ("reviewed", "classified") or not decision.get("manual_search_eligible")):
                            return web.json_response({"error": "Prompt changed or is not approved for selection"}, status=409)
                        semantic = {**decision, 'subcategories': selector_subcategories(decision, prompt)}
                        semantic['theme_ids'] = sorted(semantic_themes(semantic))
                        semantic['refinements'] = [] if semantic.get('declared_usage', semantic.get('usage')) == 'negative' else extract_refinements(prompt.get('prompt', ''), semantic['subcategories'], enable_soft_modifier_cues=soft_light_modifier_cue_allowed(decision, category, prompt, selector_subcategories(decision, prompt)))
                        prompt = {**prompt, "_semantic": semantic}
                    payload = {
                        "prompt": prompt,
                        "category": _category_summary(category),
                        "revision": _revision(data),
                        "requested_id": requested_id,
                        "redirected": requested_id != prompt_id,
                    }
                    response = _with_etag(web.json_response(payload), payload["revision"])
                    response.headers["Cache-Control"] = "no-store"
                    return response
        response = _with_etag(web.json_response({"error": f"Prompt not found: {prompt_id}", "deleted": True, "revision": _revision(data)}, status=404), _revision(data))
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.get("/prompt_selector/metadata")
async def get_metadata(request):
    """
    获取数据元信息（不返回完整数据，仅用于检查是否有更新）

    返回格式:
    {
        "last_modified": "2025-01-22T10:30:45.123Z",
        "version": "1.6",
        "categories_count": 5,
        "total_prompts": 120
    }
    """
    if not os.path.exists(DATA_FILE):
        # 返回空的元数据而非 404 错误，避免前端同步检查失败
        return web.json_response({
            "last_modified": None,
            "version": "1.6",
            "categories_count": 0,
            "total_prompts": 0
        })
    try:
        index = await asyncio.to_thread(_library_index_payload)

        metadata = {
            "last_modified": index.get("last_modified"),
            "version": index.get("version"),
            "categories_count": len(index.get("categories", [])),
            "total_prompts": index.get("total_prompts", 0),
        }

        return _with_etag(web.json_response(metadata), metadata.get("last_modified"))
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/prompt_selector/data")
async def save_data(request):
    try:
        new_data = await request.json()
        base_revision = _request_revision(request, new_data)
        if isinstance(new_data, dict):
            new_data.pop("base_revision", None)

        # 读取旧数据用于智能时间戳更新
        old_data = None
        if os.path.exists(DATA_FILE):
            try:
                old_data = _json_load_path(DATA_FILE)
            except Exception as e:
                logger.warning(f"读取旧数据失败，将跳过时间戳比较: {e}")

        _require_revision({"base_revision": base_revision}, old_data or {})

        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
        new_data = merge_selection_edit(old_data, projection, new_data)

        # 智能更新时间戳（检测变更并只更新修改的项）
        updated_data = _update_timestamps(new_data, old_data)

        # 使用原子保存机制，确保数据安全
        # 整库保存按紧凑格式写盘：缩进格式会把约 70MB 的库文件放大到约 145MB。
        _atomic_save_json(DATA_FILE, updated_data, create_backup=True, compact=True,
                          expected_revision=base_revision)

        if request.query.get("minimal") == "1":
            return _with_etag(web.json_response({
                "success": True,
                "last_modified": updated_data.get("last_modified"),
                "revision": _revision(updated_data),
                "category_count": len(updated_data.get("categories", [])),
            }), _revision(updated_data))

        # 返回完整的最新数据（包含所有更新后的时间戳）
        return _with_etag(web.json_response({
            "success": True,
            "data": project_library(updated_data, projection),
            "revision": _revision(updated_data),
        }), _revision(updated_data))
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except ValueError as e:
        # 数据验证失败
        logger.error(f"数据验证失败: {e}")
        return web.json_response({"error": f"数据验证失败: {str(e)}"}, status=400)
    except Exception as e:
        logger.error(f"保存数据失败: {e}")
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.get("/prompt_selector/preview/{filename}")
async def get_preview_image(request):
    filename = request.match_info['filename']
    image_path = _safe_preview_source(filename)
    if image_path:
        response = web.FileResponse(image_path)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    return web.Response(status=404)


@PromptServer.instance.routes.get("/prompt_selector/thumbnail/{filename}")
async def get_preview_thumbnail(request):
    filename = request.match_info['filename']
    try:
        async with _THUMBNAIL_BUILD_SEMAPHORE:
            thumbnail_path = await asyncio.to_thread(_ensure_preview_thumbnail, filename)
        response = web.FileResponse(thumbnail_path)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    except FileNotFoundError:
        return web.Response(status=404)
    except Exception as e:
        logger.warning("Preview thumbnail failed for %s: %s", filename, e)
        return web.Response(status=500)

@PromptServer.instance.routes.post("/prompt_selector/upload_image")
async def upload_image(request):
    post = await request.post()
    image_file = post.get("image")
    alias = post.get("alias", "")

    if not image_file or not image_file.file:
        return web.json_response({"error": "No image file uploaded"}, status=400)

    if not os.path.exists(PREVIEW_DIR):
        os.makedirs(PREVIEW_DIR)

    _, file_extension = os.path.splitext(image_file.filename)
    if not file_extension:
        file_extension = '.png'

    # Sanitize the alias to create a valid filename
    sanitized_alias = "".join(c for c in alias if c.isalnum() or c in (' ', '_')).rstrip()
    if not sanitized_alias:
        sanitized_alias = "untitled"

    # Create a unique filename based on alias and timestamp
    timestamp = int(time.time())
    unique_filename = f"{sanitized_alias}_{timestamp}{file_extension}"
    image_path = os.path.join(PREVIEW_DIR, unique_filename)

    # Ensure the filename is unique
    count = 1
    while os.path.exists(image_path):
        unique_filename = f"{sanitized_alias}_{timestamp}_{count}{file_extension}"
        image_path = os.path.join(PREVIEW_DIR, unique_filename)
        count += 1

    try:
        with open(image_path, 'wb') as f:
            shutil.copyfileobj(image_file.file, f)
        
        return web.json_response({"filename": unique_filename})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

def _ensure_data_compatibility(data):
    """确保导入的数据与当前版本兼容，自动添加时间戳字段"""
    if "version" not in data:
        data["version"] = "1.6" # 假设是旧版本

    if "settings" not in data:
        data["settings"] = {
            "language": "zh-CN",
            "separator": ", ",
            "save_selection": True
        }

    # 添加全局 last_modified 时间戳
    if "last_modified" not in data:
        data["last_modified"] = datetime.now().isoformat()

    for category in data.get("categories", []):
        # Legacy selection state belongs to the source record.  Consumers may
        # ignore it, but schema compatibility must not silently delete it.
        # 为分类添加 updated_at 时间戳
        if "updated_at" not in category:
            category["updated_at"] = datetime.now().isoformat()

        for prompt in category.get("prompts", []):
            if "id" not in prompt or not prompt["id"]:
                prompt["id"] = str(uuid.uuid4())
            if "description" not in prompt:
                prompt["description"] = ""
            if "tags" not in prompt:
                prompt["tags"] = []
            if "favorite" not in prompt:
                prompt["favorite"] = False
            if "image" not in prompt:
                prompt["image"] = ""
            if "created_at" not in prompt:
                prompt["created_at"] = datetime.now().isoformat()
            # 为提示词添加 updated_at 时间戳
            if "updated_at" not in prompt:
                prompt["updated_at"] = prompt.get("created_at", datetime.now().isoformat())
            if "usage_count" not in prompt:
                prompt["usage_count"] = 0
            if "last_used" not in prompt:
                prompt["last_used"] = None
    return data

def _update_timestamps(new_data, old_data=None):
    """
    智能更新时间戳：
    1. 比较新旧数据，检测哪些提示词被修改
    2. 为新增的提示词添加 created_at 和 updated_at
    3. 为修改的提示词更新 updated_at
    4. 更新全局 last_modified

    Args:
        new_data: 新的数据（从客户端接收）
        old_data: 旧的数据（从文件读取），如果为 None 则跳过比较

    Returns:
        更新时间戳后的 new_data
    """
    now = datetime.now().isoformat()

    # 更新全局 last_modified
    new_data["last_modified"] = now

    # 如果没有旧数据，直接确保所有字段存在
    if old_data is None:
        return _ensure_data_compatibility(new_data)

    # 创建旧数据的快速查找映射
    old_categories_map = {cat["name"]: cat for cat in old_data.get("categories", [])}

    for new_category in new_data.get("categories", []):
        cat_name = new_category.get("name")
        old_category = old_categories_map.get(cat_name)

        # 如果是新分类
        if not old_category:
            new_category["updated_at"] = now
            # 新分类中的所有提示词也是新的
            for prompt in new_category.get("prompts", []):
                if "created_at" not in prompt:
                    prompt["created_at"] = now
                prompt["updated_at"] = now
            continue

        # 比较分类级别的变更（如分类名称、设置等）
        category_modified = False
        for key in new_category:
            if key in ("prompts", "updated_at"):
                continue
            if new_category.get(key) != old_category.get(key):
                category_modified = True
                break

        # 创建旧提示词的快速查找映射（使用 ID）
        old_prompts_map = {p.get("id"): p for p in old_category.get("prompts", []) if p.get("id")}

        # 检查提示词变更
        for new_prompt in new_category.get("prompts", []):
            prompt_id = new_prompt.get("id")

            # 如果提示词没有 ID，是新提示词
            if not prompt_id:
                new_prompt["id"] = str(uuid.uuid4())
                new_prompt["created_at"] = now
                new_prompt["updated_at"] = now
                category_modified = True
                continue

            old_prompt = old_prompts_map.get(prompt_id)

            # 如果是新提示词（ID 不在旧数据中）
            if not old_prompt:
                if "created_at" not in new_prompt:
                    new_prompt["created_at"] = now
                new_prompt["updated_at"] = now
                category_modified = True
                continue

            # 比较提示词内容是否变更
            prompt_modified = False
            for key in new_prompt:
                if key in ("updated_at", "last_used", "usage_count"):
                    continue
                if new_prompt.get(key) != old_prompt.get(key):
                    prompt_modified = True
                    category_modified = True
                    break

            # 如果提示词被修改，更新 updated_at
            if prompt_modified:
                new_prompt["updated_at"] = now
            else:
                # 保持旧的时间戳
                new_prompt["updated_at"] = old_prompt.get("updated_at", old_prompt.get("created_at", now))

            # 确保 created_at 存在
            if "created_at" not in new_prompt:
                new_prompt["created_at"] = old_prompt.get("created_at", now)

        # 更新分类的 updated_at
        if category_modified:
            new_category["updated_at"] = now
        else:
            new_category["updated_at"] = old_category.get("updated_at", now)

    # 确保所有必需字段存在
    return _ensure_data_compatibility(new_data)

def _import_local_snapshot():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as stream:
            return json.load(stream)
    return {"version": "1.6", "categories": [], "settings": {"language": "zh-CN", "separator": ", ", "save_selection": True}}


def _import_selection(value, compatible):
    names = [cat.get("name") for cat in compatible["categories"]]
    selected = names if value is None else json.loads(value)
    if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected):
        raise ValueError("选中的来源目录必须是文本列表。")
    if any(name not in names for name in selected):
        raise ValueError("选中的来源目录已不在当前资料包中，请重新预览。")
    return sorted(set(selected))


def _import_preflight(local_data, compatible, selected, archive_digest):
    plan = plan_import(local_data, compatible, selected, _import_fingerprint, known_merged_import)
    preview = {
        "contract": "weilin-import-preflight-v1", "base_revision": _revision(local_data),
        "archive_sha256": archive_digest, "selected_categories": selected,
        "counts": dict(plan["counts"], version_conflicts=0), "items": plan["actions"],
    }
    preview["preflight_token"] = hashlib.sha256(json.dumps(preview, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return plan, preview


def _preview_import_archive(zip_file, selected_categories):
    """Worker-thread body for the import preview; never call this on the event loop."""
    archive_bytes = zip_file.file.read()
    with zipfile.ZipFile(io.BytesIO(archive_bytes), 'r') as zf:
        if 'data.json' not in zf.namelist():
            raise ValueError("ZIP file must contain data.json")
        with zf.open('data.json') as stream:
            compatible = _prepare_import_data(json.load(stream))
    selected = _import_selection(selected_categories, compatible)
    with _PROMPT_FILE_LOCK:
        _, preview = _import_preflight(_import_local_snapshot(), compatible, selected, hashlib.sha256(archive_bytes).hexdigest())
    # Retain categories for existing clients; this endpoint never writes.
    preview["categories"] = [cat.get("name") for cat in compatible["categories"]]
    return preview


def _stage_import_previews(archive_bytes, imported_images, staging_dir):
    """Worker-thread body: copy the archive's previews into a staging directory."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes), 'r') as zf:
        names = set(zf.namelist())
        for image_name in imported_images:
            image_path = Path(str(image_name))
            if image_path.is_absolute() or image_path.drive or len(image_path.parts) != 1 or image_path.name in {"", ".", ".."}:
                raise ValueError("Invalid preview path")
            zip_image_path = f'preview/{image_name}'
            if zip_image_path in names:
                target_path = os.path.join(staging_dir, image_name)
                # 只有当文件不存在时才写入，避免覆盖
                if not os.path.exists(target_path):
                    with zf.open(zip_image_path) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)


@PromptServer.instance.routes.post("/prompt_selector/pre_import")
async def pre_import_zip(request):
    post = await request.post()
    zip_file = post.get("zip_file")
    if not zip_file or not zip_file.file:
        return web.json_response({"error": "No file uploaded"}, status=400)
    try:
        preview = await asyncio.to_thread(_preview_import_archive, zip_file, post.get("selected_categories"))
        return _with_etag(web.json_response(preview), preview["base_revision"])
    except (ValueError, zipfile.BadZipFile) as error:
        return web.json_response({"error": str(error), "committed": 0}, status=400)
    except Exception as error:
        return web.json_response({"error": str(error), "committed": 0}, status=500)

def _import_operation(preflight, operation_id, status, *, after_revision=None, error=None, phase=None):
    """Exportable atomic outcome, with no second copy of editable resource bodies."""
    preview = preflight or {}
    count = preview.get("counts", {}).get("will_write")
    committed = status == "committed"
    return {
        "contract": "weilin-import-operation-v1", "operation_id": operation_id,
        "status": status, "atomic": True, "archive_sha256": preview.get("archive_sha256"),
        "preflight_token": preview.get("preflight_token"), "selected_categories": preview.get("selected_categories", []),
        "before_revision": preview.get("base_revision"), "after_revision": after_revision,
        "counts": preview.get("counts", {}), "items": preview.get("items", []),
        "committed": count if committed else 0, "uncommitted": 0 if committed else count,
        "skipped": preview.get("counts", {}).get("will_skip"),
        "failure": {"phase": phase, "message": error} if error else None,
        "recovery": {"mode": "none" if committed else "repreview_original_archive", "partial_batches": False},
        "persistence": "response_export",
    }


@PromptServer.instance.routes.post("/prompt_selector/import")
async def import_zip(request):
    post = await request.post()
    zip_file = post.get("zip_file")
    selected_categories_str = post.get("selected_categories", "[]")
    
    if not zip_file or not zip_file.file:
        return web.json_response({"error": "No file uploaded"}, status=400)

    preflight = None
    operation_id = str(uuid.uuid4())
    phase = "validation"
    staging_dir = None
    created_preview_paths = []
    try:
        # Hold the same transaction lock from the initial read/CAS check through
        # preview preparation and JSON commit.  This prevents import from
        # racing a partial/full writer after the revision was read.
        _PROMPT_FILE_LOCK.acquire()
        selected_categories = json.loads(selected_categories_str)
        
        # 加载本地数据
        if os.path.exists(DATA_FILE):
            local_data = _json_load_path(DATA_FILE)
        else:
            # 如果本地文件不存在，则创建一个空的结构
            local_data = {
                "version": "1.6",
                "categories": [],
                "settings": { "language": "zh-CN", "separator": ", ", "save_selection": True }
            }
        archive_bytes = zip_file.file.read()
        archive_digest = hashlib.sha256(archive_bytes).hexdigest()
        with zipfile.ZipFile(io.BytesIO(archive_bytes), 'r') as zf:
            if 'data.json' not in zf.namelist():
                raise ValueError("ZIP file must contain data.json")
            
            with zf.open('data.json') as f:
                import_data = json.load(f)

            compatible_data = await asyncio.to_thread(_prepare_import_data, import_data)

            selected_categories = _import_selection(selected_categories_str, compatible_data)
            planned, preflight = await asyncio.to_thread(
                _import_preflight, local_data, compatible_data, selected_categories, archive_digest)
            phase = "revision"
            _require_revision({"base_revision": _request_revision(request, post)}, local_data)
            # Legacy callers retain their If-Match contract. The unified editor
            # additionally binds its confirmed preview to these exact bytes.
            if post.get("preflight_token") is not None:
                if post.get("confirmed") != "true" or post.get("preflight_token") != preflight["preflight_token"]:
                    return web.json_response({"error": "导入预览已变化或尚未确认，请重新预览。", "plan_mismatch": True, "committed": 0,
                        "uncommitted": preflight["counts"]["will_write"],
                        "operation": _import_operation(preflight, operation_id, "not_committed", error="导入预览未确认或已变化", phase="confirmation")}, status=409)
            local_data = planned["merged_data"]
            imported_images = planned["images"]

            phase = "preview_stage"
            # 提取并保存相关的图片
            if not os.path.exists(PREVIEW_DIR):
                os.makedirs(PREVIEW_DIR)
            staging_dir = tempfile.mkdtemp(prefix=".import_preview_", dir=os.path.dirname(PREVIEW_DIR))
                
            # Unpacking a large archive is blocking; keep it off the event loop.
            await asyncio.to_thread(_stage_import_previews, archive_bytes, imported_images, staging_dir)

            try:
                # Prepare previews before the CAS commit; rollback also covers
                # a failure while copying a later image.
                for image_name in imported_images:
                    staged_path = os.path.join(staging_dir, image_name)
                    final_path = os.path.join(PREVIEW_DIR, image_name)
                    if not os.path.exists(staged_path):
                        continue
                    if os.path.exists(final_path):
                        if not _same_file_bytes(staged_path, final_path):
                            raise ValueError("Preview already exists with different content")
                        continue
                    publish_path = os.path.join(staging_dir, ".publish_" + uuid.uuid4().hex + ".tmp")
                    try:
                        # Complete the copy away from the user-visible path.
                        # Publication is non-overwriting and therefore cannot
                        # replace a file created by another writer.
                        shutil.copy2(staged_path, publish_path)
                        os.link(publish_path, final_path)
                        stat_result = os.stat(final_path)
                        created_preview_paths.append((final_path, stat_result.st_dev, stat_result.st_ino))
                    finally:
                        if os.path.exists(publish_path):
                            os.remove(publish_path)

                phase = "json_commit"
                # Save JSON only after all preview side effects are prepared.
                local_data["last_modified"] = datetime.now().isoformat()
                _atomic_save_json(DATA_FILE, local_data, create_backup=True, compact=True,
                                  expected_revision=_request_revision(request, post))
            except Exception:
                for created_path, created_dev, created_ino in created_preview_paths:
                    try:
                        current_stat = os.stat(created_path)
                        if current_stat.st_dev == created_dev and current_stat.st_ino == created_ino:
                            os.remove(created_path)
                    except OSError:
                        pass
                raise

        return _success_response({"success": True, "revision": _revision(local_data), "operation": _import_operation(preflight, operation_id, "committed", after_revision=_revision(local_data))})
    except RevisionConflict as e:
        if preflight:
            preflight["counts"]["version_conflicts"] = preflight["counts"]["total_records"]
        operation = _import_operation(preflight, operation_id, "not_committed", error=str(e), phase="revision")
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True, "committed": 0, "operation": operation}, status=409)
    except (ValueError, zipfile.BadZipFile) as e:
        return web.json_response({"error": str(e), "committed": 0, "operation": _import_operation(preflight, operation_id, "not_committed", error=str(e), phase=phase)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e), "committed": 0, "operation": _import_operation(preflight, operation_id, "not_committed", error=str(e), phase=phase)}, status=500)
    finally:
        if staging_dir and os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        _PROMPT_FILE_LOCK.release()

def _export_preview_bytes():
    total = 0
    if os.path.exists(PREVIEW_DIR):
        for root, _, files in os.walk(PREVIEW_DIR):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
    return total


def _build_export_archive(target_path, include_previews=True):
    """Worker-thread body for the export route; never call this on the event loop."""
    with zipfile.ZipFile(target_path, 'w') as zf:
        zf.write(DATA_FILE, arcname='data.json',
                 compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
        # 添加图片
        if include_previews and os.path.exists(PREVIEW_DIR):
            for root, _, files in os.walk(PREVIEW_DIR):
                for name in files:
                    # 预览图本身已被压缩，直接存储可显著缩短导出时间。
                    zf.write(os.path.join(root, name), arcname=os.path.join('preview', name),
                             compress_type=zipfile.ZIP_STORED)


@PromptServer.instance.routes.get("/prompt_selector/export")
async def export_zip(request):
    """Build the archive in a worker thread and stream it, so a large library
    cannot block the event loop or buffer the whole zip in memory."""
    archive_path = None
    prepared = False
    try:
        # Library previews are tens of gigabytes, so the default export is data only.
        # Callers that really need the images must ask for them explicitly.
        include_previews = str(request.query.get('include_previews', '0')).lower() in ('1', 'true', 'yes')
        if include_previews:
            required = _export_preview_bytes() + os.path.getsize(DATA_FILE)
            free = shutil.disk_usage(tempfile.gettempdir()).free
            if required > free * 0.8:
                return web.json_response({
                    "error": (f"导出需要约 {required // (1024 ** 3)} GB 临时空间，"
                              f"当前可用 {free // (1024 ** 3)} GB。请先清理磁盘，"
                              f"或使用 include_previews=0 仅导出资料数据。"),
                    "required_bytes": required, "free_bytes": free,
                    "data_only_supported": True,
                }, status=507)
        handle, archive_path = tempfile.mkstemp(suffix='.zip', prefix='prompt_library_export_')
        os.close(handle)
        await asyncio.to_thread(_build_export_archive, archive_path, include_previews)
        response = web.StreamResponse(status=200, headers={
            'Content-Type': 'application/zip',
            'Content-Length': str(os.path.getsize(archive_path)),
            'Content-Disposition': 'attachment; filename="prompt_library.zip"',
            'Cache-Control': 'no-store',
        })
        await response.prepare(request)
        prepared = True
        with open(archive_path, 'rb') as stream:
            while True:
                chunk = await asyncio.to_thread(stream.read, 262144)
                if not chunk:
                    break
                await response.write(chunk)
        await response.write_eof()
        return response
    except Exception as e:
        if prepared:
            raise
        return web.json_response({"error": str(e)}, status=500)
    finally:
        if archive_path and os.path.exists(archive_path):
            try:
                os.remove(archive_path)
            except OSError:
                pass

# --- 新增的管理功能API ---

def _rename_category_branch(payload):
    """Rename one category and every descendant that lives under it.

    The node editor used to rename locally and then post the whole library back,
    which exceeds the server's request limit at the current library size.  This
    keeps the edit to one locked, revision-checked, compact atomic write.
    """
    old_name = str(payload.get("old_name") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    old_key, new_key = old_name.lstrip("/"), new_name.lstrip("/")
    if not old_key or not new_key:
        raise ValueError("Missing category names")
    if any(part == "" for part in new_key.split("/")):
        raise ValueError("分类名不能包含空的路径段")
    prefix, new_prefix = old_key + "/", new_key + "/"
    if new_key != old_key and new_key.startswith(prefix):
        raise ValueError("不能把分类移动到它自己的子分类下")
    with _PROMPT_FILE_LOCK:
        file_data = _json_load_path(DATA_FILE)
        _require_revision(payload, file_data)
        categories = file_data.get("categories", [])
        normalized = [str(category.get("name") or "").lstrip("/") for category in categories]
        if old_key not in normalized:
            raise KeyError("Category not found")
        for name in normalized:
            if name == old_key or name.startswith(prefix):
                continue
            if name == new_key or name.startswith(new_prefix):
                raise ValueError("Category name already exists")
        now = datetime.now().isoformat()
        renamed = []
        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
        for category, name in zip(categories, normalized):
            if name != old_key and not name.startswith(prefix):
                continue
            previous_category = copy.deepcopy(category)
            rest = name[len(old_key):]
            current = str(category.get("name") or "")
            category["name"] = current[: len(current) - len(name)] + new_key + rest
            category["updated_at"] = now
            for old_prompt, prompt in zip(previous_category.get("prompts", []), category.get("prompts", [])):
                rebind_unchanged_prompt(projection, previous_category, old_prompt, category, prompt)
            renamed.append(new_key + rest)
        file_data["last_modified"] = now
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, compact=True,
                          expected_revision=payload.get("base_revision"))
        _cache_prompt_data(file_data)
        return {"success": True, "renamed": renamed, "count": len(renamed),
                "revision": _revision(file_data)}


@PromptServer.instance.routes.post("/prompt_selector/category/rename")
async def rename_category(request):
    """重命名分类及其子分类；一次加锁、一次原子紧凑保存。"""
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_rename_category_branch, data)
        return _success_response(result)
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except KeyError as e:
        message = str(e.args[0]) if e.args else "Category not found"
        return web.json_response({"error": message}, status=404)
    except (ValueError, TypeError) as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/prompt_selector/category/delete")
async def delete_category(request):
    """删除分类及其子分类"""
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        category_name_to_delete = data.get("name")

        if not category_name_to_delete:
            return web.json_response({"error": "Missing category name"}, status=400)

        if not os.path.exists(DATA_FILE):
            return web.json_response({"success": True})

        file_data = _json_load_path(DATA_FILE)
        _require_revision(data, file_data)
        _require_revision(data, file_data)

        prefix_to_delete = category_name_to_delete + '/'
        categories_to_keep = []
        removed_prompt_ids = []
        for cat in file_data.get("categories", []):
            original_cat_name = cat.get("name", "")
            # Sanitize the name by removing any leading slashes before comparison
            sanitized_cat_name = original_cat_name.lstrip('/')
            
            keep = sanitized_cat_name != category_name_to_delete and not sanitized_cat_name.startswith(prefix_to_delete)
            if keep:
                categories_to_keep.append(cat)
            else:
                removed_prompt_ids.extend(prompt.get("id") for prompt in cat.get("prompts", []) or [])


        file_data["categories"] = categories_to_keep

        if "categories" not in file_data:
            file_data["categories"] = []

        file_data["last_modified"] = datetime.now().isoformat()

        # 使用原子保存机制
        # Compact on every library write: the indented form doubles the 100 MB+ store and
        # the cold parse along with it.
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, compact=True,
                          expected_revision=data.get("base_revision"))
        _cache_prompt_data(file_data, removed_prompt_ids)

        return _success_response({"success": True, "revision": _revision(file_data)})
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/prompt_selector/prompts/batch_delete")
async def batch_delete_prompts(request):
    """批量删除提示词

    v55 修复点：前端词库弹窗可以浏览与节点 selectedCategory 不同的分类，
    因此批量删除不能只信任单个 category 字段。新前端会传入
    prompt_items=[{"id": prompt_id, "source_category": category_name}, ...]。
    """
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        category_name = data.get("category")
        prompt_ids = {str(pid) for pid in data.get("prompt_ids", []) if pid}
        prompt_items = data.get("prompt_items", []) or []

        if not prompt_ids and not prompt_items:
            return web.json_response({"error": "Missing parameters"}, status=400)

        file_data = _json_load_path(DATA_FILE)
        _require_revision(data, file_data)

        categories = file_data.get("categories", [])
        category_map = {category.get("name"): category for category in categories}

        # 新协议：按每个 prompt 的真实源分类删除。若 source_category 缺失，则退化为全局按 ID 查找。
        ids_by_category = {}
        global_ids = set()
        for item in prompt_items:
            if not isinstance(item, dict):
                continue
            prompt_id = item.get("id") or item.get("prompt_id")
            if not prompt_id:
                continue
            prompt_id = str(prompt_id)
            source_category = item.get("source_category") or item.get("category")
            if source_category:
                ids_by_category.setdefault(source_category, set()).add(prompt_id)
            else:
                global_ids.add(prompt_id)

        # 旧协议兼容：只有 category + prompt_ids 时，仍按单分类删除。
        if not ids_by_category and not global_ids:
            if not category_name or not prompt_ids:
                return web.json_response({"error": "Missing parameters"}, status=400)
            if category_name not in category_map:
                return web.json_response({"error": "Category not found"}, status=404)
            ids_by_category[category_name] = set(prompt_ids)

        requested_items = [(str(item.get("id") or item.get("prompt_id") or ""), item.get("source_category") or item.get("category"))
                           for item in prompt_items if isinstance(item, dict)] if prompt_items else [(str(pid), category_name) for pid in data.get("prompt_ids", [])]
        if len({pid for pid, _ in requested_items}) != len(requested_items):
            return web.json_response({"error": "Duplicate prompt IDs"}, status=400)
        if len(requested_items) != len(prompt_items or data.get("prompt_ids", [])) or any(not pid for pid, _ in requested_items):
            return web.json_response({"error": "Invalid prompt items"}, status=400)
        requested_ids = {pid for pid, _ in requested_items}
        locations = {pid: [] for pid in requested_ids}
        for category in categories:
            for prompt in category.get("prompts", []):
                pid = str(prompt.get("id"))
                if pid in locations:
                    locations[pid].append((category, prompt))
        for pid, source in requested_items:
            matches = locations[pid]
            if len(matches) != 1 or (source and matches[0][0].get("name") != source):
                return web.json_response({"error": "Prompt identity or source changed; refresh before deleting"}, status=409)

        deleted_count = 0
        touched_categories = []
        deleted_prompt_ids = []
        now = datetime.now().isoformat()

        for category in categories:
            cat_name = category.get("name")
            ids_for_this_category = set(global_ids)
            ids_for_this_category.update(ids_by_category.get(cat_name, set()))
            if not ids_for_this_category:
                continue

            before_count = len(category.get("prompts", []))
            category["prompts"] = [
                prompt for prompt in category.get("prompts", [])
                if str(prompt.get("id")) not in ids_for_this_category
            ]
            removed = before_count - len(category.get("prompts", []))
            if removed > 0:
                deleted_count += removed
                category["updated_at"] = now
                touched_categories.append(cat_name)
                deleted_prompt_ids.extend(ids_for_this_category)

        if deleted_count <= 0:
            return web.json_response({
                "error": "No matching prompts found for batch_delete; source category and prompt IDs may be stale",
                "deleted_count": 0
            }, status=404)

        file_data["last_modified"] = now

        # 使用原子保存机制
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, compact=True,
                          expected_revision=data.get("base_revision"))
        _cache_prompt_data(file_data, deleted_prompt_ids)

        return _success_response({
            "success": True,
            "deleted_count": deleted_count,
            "touched_categories": touched_categories,
            "revision": _revision(file_data)
        })
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

def _get_or_create_category(categories, category_name, now):
    for category in categories:
        if category.get("name") == category_name:
            return category
    category = {
        "id": str(uuid.uuid4()),
        "name": category_name,
        "updated_at": now,
        "prompts": [],
    }
    categories.append(category)
    return category

def _category_summary(category):
    return {
        "id": category.get("id") or category.get("name"),
        "name": category.get("name") or "未分类",
        "updated_at": category.get("updated_at"),
        "prompt_count": len(category.get("prompts", []) or []),
        "prompts": [],
    }


def _find_category_by_identity(categories, identity):
    identity = str(identity or "")
    for category in categories:
        if str(category.get("id") or category.get("name") or "") == identity:
            return category
    for category in categories:
        if str(category.get("name") or "") == identity:
            return category
    return None


def _apply_create_category(category_name, expected_revision):
    file_data = _json_load_path(DATA_FILE)
    _require_revision({"base_revision": expected_revision}, file_data)
    file_data = _ensure_data_compatibility(file_data)
    categories = file_data.get("categories", [])
    now = datetime.now().isoformat()
    existing = next(
        (category for category in categories if category.get("name") == category_name),
        None,
    )
    if existing is not None:
        return {"success": True, "created": False, "category": _category_summary(existing),
                "revision": _revision(file_data)}

    category = _get_or_create_category(categories, category_name, now)
    file_data["last_modified"] = now
    _atomic_save_json(
        DATA_FILE,
        file_data,
        create_backup=_should_create_route_branch_backup(),
        compact=True,
        sync_to_disk=False,
        expected_revision=expected_revision,
    )
    _cache_prompt_data(file_data, [])
    return {"success": True, "created": True, "category": _category_summary(category), "revision": _revision(file_data)}


def _apply_upsert_prompt(payload):
    file_data = _json_load_path(DATA_FILE)
    _require_revision(payload, file_data)
    file_data = _ensure_data_compatibility(file_data)
    categories = file_data.get("categories", [])
    now = datetime.now().isoformat()

    new_category_name = str(payload.get("new_category_name") or "").strip()
    target_identity = payload.get("target_category_id")
    if new_category_name:
        target_category = _get_or_create_category(categories, new_category_name, now)
    else:
        target_category = _find_category_by_identity(categories, target_identity)
    if target_category is None:
        target_category = _get_or_create_category(categories, "默认/其他", now)

    raw_prompt = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    prompt_id = str(raw_prompt.get("id") or "").strip()
    mode = str(payload.get("mode") or "create")
    if mode not in {"create", "edit"}:
        raise ValueError("Invalid prompt save mode")
    existing_prompt = None
    source_category = None
    source_index = None

    if prompt_id:
        if prompt_id in file_data.get('_source_to_canonical', {}):
            raise ValueError('旧资料已合并，请通过原 ID 定位后编辑当前资料')
        for category in categories:
            prompts = category.get("prompts", []) or []
            for index, prompt in enumerate(prompts):
                if str(prompt.get("id") or "") == prompt_id:
                    existing_prompt = prompt
                    source_category = category
                    source_index = index
                    break
            if existing_prompt is not None:
                break

    draft_id = str(payload.get("draft_id") or "").strip()
    if mode == "create" and draft_id:
        for category in categories:
            for prompt in category.get("prompts", []) or []:
                if prompt.get("_draft_id") == draft_id:
                    return {"success": True, "created": False, "prompt": prompt,
                            "category": _category_summary(category), "revision": _revision(file_data)}
    if mode == "create" and existing_prompt is not None:
        # An unrelated create must retain the existing identity.
        prompt_id = str(uuid.uuid4())
        existing_prompt = None
        source_category = None

    if mode == "edit" and existing_prompt is None:
        raise KeyError(f"Prompt not found: {prompt_id}")
    if mode == "create" and existing_prompt is None and any(prompt_id in event.get('source_ids', []) for event in file_data.get('_merge_history', [])):
        raise ValueError('该历史身份已被合并或删除；请另存为新身份')

    if mode == "edit" and existing_prompt is not None and source_category is not target_category:
        source_category["prompts"].remove(existing_prompt)

    prompt = dict(existing_prompt or {})
    prompt["id"] = prompt_id or str(uuid.uuid4())
    prompt["alias"] = str(raw_prompt.get("alias") or "")
    prompt["prompt"] = str(raw_prompt.get("prompt") or "")
    prompt["description"] = str(raw_prompt.get("description") or "")
    prompt["image"] = str(raw_prompt.get("image") or "")
    tags = raw_prompt.get("tags", []) or []
    prompt["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    prompt["favorite"] = bool(raw_prompt.get("favorite", False))
    prompt["template"] = bool(raw_prompt.get("template", prompt.get("template", False)))
    if "is_user_plan" in raw_prompt:
        if type(raw_prompt["is_user_plan"]) is not bool:
            raise ValueError("方案标记必须为明确的是或否")
        prompt["is_user_plan"] = raw_prompt["is_user_plan"]
    prompt["usage_count"] = int(raw_prompt.get("usage_count", prompt.get("usage_count", 0)) or 0)
    prompt["last_used"] = raw_prompt.get("last_used", prompt.get("last_used"))
    prompt["created_at"] = raw_prompt.get("created_at") or prompt.get("created_at") or now
    prompt["updated_at"] = now
    if mode == "create" and draft_id:
        prompt["_draft_id"] = draft_id

    reserved_prompt_fields = {
        "id", "alias", "prompt", "description", "image", "tags", "favorite",
        "template", "is_user_plan", "usage_count", "last_used", "created_at", "updated_at",
        "_categoryId", "_categoryName",
    }
    for key, value in raw_prompt.items():
        if key not in reserved_prompt_fields and not str(key).startswith("_"):
            prompt[key] = value

    sections = prompt.get('plan_sections')
    if sections is not None:
        if not isinstance(sections, dict) or set(sections) != {'positive', 'negative'} or any(not isinstance(value, str) for value in sections.values()):
            raise ValueError('方案必须包含有效的正向和负向文本字段')
        if not any(value.strip() for value in sections.values()):
            raise ValueError('方案至少需要一个方向的正文')
        expected_text = '\n\n'.join(label + '\n' + sections[key] for key, label in [('positive', '[正向]'), ('negative', '[负向]')] if sections[key].strip())
        if prompt['prompt'] != expected_text:
            raise ValueError('方案正文与分段不一致，请在同一编辑器中修改分段后保存')
        expected_usage = 'mixed' if all(value.strip() for value in sections.values()) else 'negative' if sections['negative'].strip() else 'positive'
        if payload.get('classification') is not None and payload['classification'].get('usage') != expected_usage:
            raise ValueError('方案用途必须与正负向分段一致')

    if payload.get("classification") is not None:
        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
        prompt["_classification"] = confirm_classification(
            projection, target_category, prompt, payload["classification"],
            previous_category=source_category if mode == "edit" else None,
            previous_prompt=existing_prompt if mode == "edit" else None,
        )
        prompt["template"] = prompt["_classification"]["content_type"] == "template"
        prompt["_classification"]["binding"] = semantic_binding(target_category, prompt)

    if mode == "edit" and source_category is not target_category and payload.get("classification") is None:
        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
        rebind_unchanged_prompt(projection, source_category, existing_prompt, target_category, prompt)

    if "selector_group_ids" in payload:
        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
        apply_collection(file_data, prompt, decision_for(projection, target_category, prompt), payload["selector_group_ids"], payload.get('selector_metadata'))

    if raw_prompt.get("is_user_plan") is True:
        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))
        if decision_for(projection, target_category, prompt).get("manual_search_eligible") is not True:
            raise ValueError("请先确认资料主题后再保存为方案")

    if mode == "edit" and source_category is target_category:
        target_category["prompts"][source_index] = prompt
    else:
        target_category.setdefault("prompts", []).append(prompt)
    target_category["updated_at"] = now
    if source_category is not None and source_category is not target_category:
        source_category["updated_at"] = now
    file_data["last_modified"] = now
    _atomic_save_json(
        DATA_FILE,
        file_data,
        create_backup=_should_create_route_branch_backup(),
        compact=True,
        sync_to_disk=False,
        expected_revision=payload.get("base_revision"),
    )
    _cache_prompt_data(file_data, [prompt["id"]])
    outcome = {
        "success": True,
        "prompt": prompt,
        "category": _category_summary(target_category),
        "revision": _revision(file_data),
    }
    # A body edit is mirrored to the Tag row for the same concept (see shared_sync).
    previous_text = str((existing_prompt or {}).get("prompt") or "")
    if mode == "edit" and previous_text and previous_text != str(prompt.get("prompt") or ""):
        try:
            from . import shared_sync
            synced = shared_sync.mirror_from_library(prompt["id"], previous_text, prompt.get("prompt"))
            if synced is not None:
                outcome["mirrored"] = synced
        except Exception as error:  # noqa: BLE001 - the library write is already committed
            logger.warning("资源库正文同步到 Tag 库失败: %s", error)
    return outcome


def _apply_delete_prompt(prompt_id, expected_revision):
    file_data = _json_load_path(DATA_FILE)
    _require_revision({"base_revision": expected_revision}, file_data)
    file_data = _ensure_data_compatibility(file_data)
    categories = file_data.get("categories", [])
    now = datetime.now().isoformat()

    deleted = None
    source_category = None
    for category in categories:
        prompts = category.get("prompts", []) or []
        for index, prompt in enumerate(prompts):
            if str(prompt.get("id") or "") == prompt_id:
                deleted = prompts.pop(index)
                source_category = category
                break
        if deleted is not None:
            break

    if deleted is None:
        raise KeyError(f"Prompt not found: {prompt_id}")

    source_category["updated_at"] = now
    file_data["last_modified"] = now
    _atomic_save_json(
        DATA_FILE,
        file_data,
        create_backup=_should_create_route_branch_backup(),
        compact=True,
        sync_to_disk=False,
        expected_revision=expected_revision,
    )
    _cache_prompt_data(file_data, [prompt_id])
    return {
        "success": True,
        "deleted_id": prompt_id,
        "category": _category_summary(source_category),
        "revision": _revision(file_data),
    }


@PromptServer.instance.routes.post("/prompt_selector/categories/create")
async def create_prompt_category(request):
    try:
        payload = await request.json()
        payload["base_revision"] = _request_revision(request, payload)
        category_name = str(payload.get("name") or "").strip()
        if not category_name:
            return web.json_response({"error": "Missing category name"}, status=400)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_create_category, category_name, payload.get("base_revision"))
        return _success_response(result)
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def _apply_plan_flag(payload):
    data = _json_load_path(DATA_FILE)
    _require_revision(payload, data)
    value = payload.get('is_user_plan')
    if type(value) is not bool:
        raise ValueError('方案标记必须为明确的是或否')
    for category in data.get('categories', []):
        for prompt in category.get('prompts', []):
            if prompt.get('id') != payload.get('prompt_id'):
                continue
            if value:
                projection = read_projection(os.path.join(PROMPT_STORE_DIR, 'semantic_projection.json'))
                semantic = decision_for(projection, category, prompt)
                if semantic.get('manual_search_eligible') is not True:
                    raise ValueError('请先编辑并确认资料主题，再保存为方案')
            prompt['is_user_plan'] = value
            prompt['updated_at'] = datetime.now().isoformat()
            data['last_modified'] = prompt['updated_at']
            _atomic_save_json(DATA_FILE, data, create_backup=_should_create_route_branch_backup(), compact=True,
                             expected_revision=payload.get('base_revision'))
            _cache_prompt_data(data, [prompt['id']])
            return {'success': True, 'prompt_id': prompt['id'], 'is_user_plan': value,
                    'revision': _revision(data)}
    raise KeyError('资料已不存在，请刷新列表')


@PromptServer.instance.routes.post('/prompt_selector/prompts/plan')
async def set_prompt_plan(request):
    try:
        payload = await request.json()
        payload['base_revision'] = _request_revision(request, payload)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_plan_flag, payload)
        return _success_response(result)
    except RevisionConflict as error:
        return web.json_response({'error': str(error), 'conflict': True}, status=409)
    except KeyError as error:
        return web.json_response({'error': str(error)}, status=404)
    except ValueError as error:
        return web.json_response({'error': str(error)}, status=400)
    except Exception as error:
        logger.error("保存方案标记失败: %s", error)
        return web.json_response({'error': str(error)}, status=500)


@PromptServer.instance.routes.post("/prompt_selector/prompts/upsert")
async def upsert_prompt(request):
    try:
        payload = await request.json()
        payload["base_revision"] = _request_revision(request, payload)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_upsert_prompt, payload)
        return _success_response(result)
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except KeyError as e:
        return web.json_response({"error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def _apply_merge_request(payload):
    data = _json_load_path(DATA_FILE)
    _require_revision(payload, data)
    projection = read_projection(os.path.join(PROMPT_STORE_DIR, 'semantic_projection.json'))
    if payload.get('commit') is not True:
        return merge_preview(data, projection, payload.get('prompt_ids'), payload.get('canonical_id'))
    merged, preview = apply_merge(data, projection, payload, datetime.now().isoformat())
    _atomic_save_json(DATA_FILE, merged, create_backup=True, compact=True,
                      expected_revision=payload.get('base_revision'))
    _cache_prompt_data(merged)
    return {'success': True, 'canonical_id': preview['canonical_id'],
        'mapped_ids': [x for x in preview['prompt_ids'] if x != preview['canonical_id']],
        'revision': _revision(merged)}


@PromptServer.instance.routes.post('/prompt_selector/prompts/merge')
async def merge_prompts(request):
    try:
        payload = await request.json()
        payload['base_revision'] = _request_revision(request, payload)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_merge_request, payload)
        return _success_response(result)
    except RevisionConflict as error:
        return web.json_response({'error': str(error), 'conflict': True}, status=409)
    except ValueError as error:
        return web.json_response({'error': str(error)}, status=400)
    except Exception as error:
        return web.json_response({'error': str(error)}, status=500)


@PromptServer.instance.routes.post("/prompt_selector/prompts/delete")
async def delete_prompt(request):
    try:
        payload = await request.json()
        payload["base_revision"] = _request_revision(request, payload)
        prompt_id = str(payload.get("prompt_id") or "").strip()
        if not prompt_id:
            return web.json_response({"error": "Missing prompt id"}, status=400)
        current = _json_load_path(DATA_FILE)
        _require_revision(payload, current)
        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_delete_prompt, prompt_id, payload.get("base_revision"))
        return _success_response(result)
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except KeyError as e:
        return web.json_response({"error": str(e)}, status=404)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
@PromptServer.instance.routes.post("/prompt_selector/prompts/update_order")
async def update_prompt_order(request):
    """更新提示词排序"""
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        category_name = data.get("category")
        ordered_ids = data.get("ordered_ids", [])
        
        if not category_name or not ordered_ids:
            return web.json_response({"error": "Missing parameters"}, status=400)
            
        file_data = _json_load_path(DATA_FILE)
        _require_revision(data, file_data)
            
        # 查找分类并重新排序
        for category in file_data["categories"]:
            if category["name"] == category_name:
                prompts = category["prompts"]
                if not isinstance(ordered_ids, list) or any(not isinstance(pid, str) for pid in ordered_ids):
                    return web.json_response({"error": "Invalid prompt IDs"}, status=400)
                # A merged-away source id still resolves to its current canonical slot, so a page
                # loaded before the merge can still reorder without dropping or duplicating records.
                source_map = file_data.get("_source_to_canonical") or {}
                resolved_ids = []
                for pid in ordered_ids:
                    record = source_map.get(pid)
                    canonical = record.get("canonical_id") if isinstance(record, dict) else None
                    resolved_ids.append(str(canonical) if canonical else pid)
                prompt_map = {p.get("id"): p for p in prompts}
                if len(prompt_map) != len(prompts) or len(set(resolved_ids)) != len(resolved_ids):
                    return web.json_response({"error": "Duplicate prompt IDs; refresh the library"}, status=400)
                if any(pid not in prompt_map for pid in resolved_ids):
                    return web.json_response({"error": "Prompt IDs no longer belong to this category"}, status=409)
                requested = set(resolved_ids)
                ordered = iter(prompt_map[pid] for pid in resolved_ids)
                category["prompts"] = [next(ordered) if p.get("id") in requested else p for p in prompts]

                # 更新分类和全局时间戳（排序操作）
                now = datetime.now().isoformat()
                category["updated_at"] = now
                file_data["last_modified"] = now
                break
        else:
            return web.json_response({"error": "Category not found"}, status=404)

        # 使用原子保存机制
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, compact=True,
                          expected_revision=data.get("base_revision"))
        _cache_prompt_data(file_data, [])

        return _success_response({"success": True, "revision": _revision(file_data)})
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/prompt_selector/prompts/toggle_favorite")
async def toggle_favorite(request):
    """切换提示词收藏状态"""
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        category_name = data.get("category")
        category_id = data.get("category_id")
        prompt_id = data.get("prompt_id")
        if "favorite" in data and type(data["favorite"]) is not bool:
            return web.json_response({"error": "收藏状态必须为是或否"}, status=400)
        if not (category_id or category_name) or not prompt_id:
            return web.json_response({"error": "Missing parameters"}, status=400)
            
        # The 217 MB document is already in memory; copy the touched row instead of
        # parsing the file again, and keep the shared document untouched until commit.
        with _PROMPT_FILE_LOCK:
            current = _read_prompt_data_cached()
            _require_revision(data, current)
            categories = current.get("categories", [])
            file_data = None
            for index, category in enumerate(categories):
                if (category.get("id") == category_id if category_id else category.get("name") == category_name):
                    prompts = list(category.get("prompts", []))
                    for position, prompt in enumerate(prompts):
                        if prompt.get("id") != prompt_id:
                            continue
                        # 更新提示词、分类和全局时间戳
                        now = datetime.now().isoformat()
                        prompts[position] = {**prompt, "updated_at": now,
                            "favorite": data.get("favorite", not prompt.get("favorite", False))}
                        rebuilt = list(categories)
                        rebuilt[index] = {**category, "prompts": prompts, "updated_at": now}
                        file_data = {**current, "categories": rebuilt, "last_modified": now}
                        break
                    break

            if file_data is None:
                return web.json_response({"error": "资料已移动或不存在，请刷新后重试"}, status=404)

            # 使用原子保存机制
            _atomic_save_json(DATA_FILE, file_data, create_backup=True, compact=True,
                              expected_revision=data.get("base_revision"))
            _cache_prompt_data(file_data, [prompt_id])

        return _success_response({"success": True, "revision": _revision(file_data)})
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.post("/prompt_selector/prompts/mark_used")
async def mark_prompt_used(request):
    """Record the actual library insertion for the common/recent view."""
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        prompt_id = str(data.get("prompt_id") or "").strip()
        category_id = str(data.get("category_id") or data.get("category") or "").strip()
        if not prompt_id:
            return web.json_response({"error": "Missing prompt_id"}, status=400)
        # Same copy-on-write rule as the favourite toggle: reuse the in-memory document.
        with _PROMPT_FILE_LOCK:
            current = _read_prompt_data_cached()
            _require_revision(data, current)
            categories = current.get("categories", [])
            file_data = None
            for index, category in enumerate(categories):
                category_identity = str(category.get("id") or category.get("name") or "")
                if category_id and category_identity != category_id and str(category.get("name") or "") != category_id:
                    continue
                prompts = list(category.get("prompts", []) or [])
                for position, prompt in enumerate(prompts):
                    if str(prompt.get("id") or "") != prompt_id:
                        continue
                    now = datetime.now().isoformat()
                    prompts[position] = {**prompt, "last_used": now,
                        "usage_count": int(prompt.get("usage_count") or 0) + 1}
                    rebuilt = list(categories)
                    rebuilt[index] = {**category, "prompts": prompts, "updated_at": now}
                    file_data = {**current, "categories": rebuilt, "last_modified": now}
                    break
                if file_data is not None:
                    break

            if file_data is None:
                return web.json_response({"error": "Prompt not found"}, status=404)

            _atomic_save_json(DATA_FILE, file_data, create_backup=True, compact=True,
                              expected_revision=data.get("base_revision"))
            _cache_prompt_data(file_data, [prompt_id])
        return _success_response({"success": True, "prompt_id": prompt_id, "last_used": now, "revision": _revision(file_data)})
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# 确保在启动时 data.json 文件存在，如果不存在则创建一个空的结构
def initialize_data_file():
    # V52+: Prompt Selector has one canonical store owned by WeiLin. Legacy Gallery
    # folders are deliberately not scanned or modified. Copy data.json and preview/
    # into user_data/prompt_selector manually when migrating an existing install.
    # === 原有逻辑：创建默认数据 ===
    if not os.path.exists(DATA_FILE):
        if os.path.exists(DEFAULT_DATA_FILE):
            # 如果 default.json 存在，直接复制作为初始词库
            try:
                logger.error("📦 检测到默认词库文件，正在初始化...")
                shutil.copy2(DEFAULT_DATA_FILE, DATA_FILE)
                logger.error(f"✅ 默认词库已从 {DEFAULT_DATA_FILE} 初始化到 {DATA_FILE}")
            except Exception as e:
                logger.error(f"❌ 复制默认词库失败: {str(e)}")
                # 如果复制失败，创建一个基本的空结构
                fallback_data = {
                    "version": "1.6",
                    "last_modified": datetime.now().isoformat(),
                    "categories": [],
                    "settings": {
                        "language": "zh-CN",
                        "separator": ", ",
                        "save_selection": True
                    }
                }
                _atomic_save_json(DATA_FILE, fallback_data, create_backup=False)
                logger.info("📝 已创建空词库结构作为备用方案")
        else:
            # 如果 default.json 也不存在，创建一个基本的空结构
            fallback_data = {
                "version": "1.6",
                "last_modified": datetime.now().isoformat(),
                "categories": [],
                "settings": {
                    "language": "zh-CN",
                    "separator": ", ",
                    "save_selection": True
                }
            }
            _atomic_save_json(DATA_FILE, fallback_data, create_backup=False)
            logger.error("⚠️ 默认词库文件不存在，已创建空词库结构")

    # === 新增：升级现有数据文件，添加时间戳字段 ===
    # 如果 data.json 已存在，检查并添加缺失的时间戳字段
    if os.path.exists(DATA_FILE):
        try:
            existing_data = _read_prompt_data_cached()

            # 检查是否缺少 last_modified 字段
            needs_upgrade = "last_modified" not in existing_data

            # 检查分类和提示词是否缺少时间戳
            for category in existing_data.get("categories", []):
                if "updated_at" not in category:
                    needs_upgrade = True
                    break
                for prompt in category.get("prompts", []):
                    if "updated_at" not in prompt:
                        needs_upgrade = True
                        break
                if needs_upgrade:
                    break

            # 如果需要升级，使用 _ensure_data_compatibility 添加时间戳
            if needs_upgrade:
                logger.info("📝 检测到数据文件缺少时间戳字段，正在升级...")
                # Compatibility upgrades mutate their input; keep the read cache intact until commit.
                upgraded_data = _ensure_data_compatibility(copy.deepcopy(existing_data))
                _atomic_save_json(DATA_FILE, upgraded_data, create_backup=True, compact=True)
                logger.info("✅ 数据文件已升级，添加了时间戳字段")

        except Exception as e:
            logger.error(f"⚠️ 升级数据文件失败: {e}")
            # 不影响启动，继续运行

# 在插件加载时调用初始化
initialize_data_file()


def _warm_library_caches(include_packed=True):
    """Precompute the reviewed library views so the first user request is not the cold one.

    The gzip snapshot is only consumed by the node's whole-library fetch, so the
    after-write warm-up skips it: compressing 172 MB costs seconds and no panel read
    waits on it.
    """
    _tune_library_gc()
    _reviewed_library_data()
    _library_index_payload()
    _library_page_payload("", "", 0, _LIBRARY_PAGE_SIZE)
    if include_packed:
        _packed_library_payload()


def _tune_library_gc():
    """The derived library keeps ~10^5 live dicts alive.

    With the default thresholds a generation-2 collection walks that whole heap and
    shows up as a 0.3-0.9 s stall on an otherwise 20 ms read.  Collecting the young
    generations more coarsely keeps cycles reclaimable without those pauses.
    """
    if os.environ.get("UW_SKIP_GC_TUNING") == "1":
        return
    gc.set_threshold(20000, 100, 100)
    logger.info("[Workbench] Library GC thresholds raised for the large heap.")


_WARM_SCHEDULER = {"thread": None, "again": False, "lock": threading.Lock()}


def _warm_worker(delay, include_packed):
    """One warm-up worker; loops once more when edits landed while it was running."""
    try:
        if delay:
            time.sleep(delay)
        while True:
            started = time.perf_counter()
            _warm_library_caches(include_packed=include_packed)
            logger.info("[Workbench] Library caches warmed in %.1f s; the next open is served from cache.",
                        time.perf_counter() - started)
            with _WARM_SCHEDULER["lock"]:
                if not _WARM_SCHEDULER["again"]:
                    _WARM_SCHEDULER["thread"] = None
                    return
                _WARM_SCHEDULER["again"] = False
    except Exception as error:  # noqa: BLE001
        with _WARM_SCHEDULER["lock"]:
            _WARM_SCHEDULER["thread"] = None
        logger.warning(f"[Workbench] Library warm-up skipped: {error}")


def _request_library_warm(delay=0.0, include_packed=False):
    """Coalesced warm-up request: at most one worker, one extra pass if edits kept coming.

    ``_atomic_save_json`` calls this after every library write. Without it the panel's
    first read after an edit paid the whole projection rebuild (measured 798 ms for the
    first page, 166 ms for the index, against 15 ms once warm).
    """
    with _WARM_SCHEDULER["lock"]:
        thread = _WARM_SCHEDULER["thread"]
        if thread is not None and thread.is_alive():
            _WARM_SCHEDULER["again"] = True
            return
        _WARM_SCHEDULER["again"] = False
        thread = threading.Thread(target=_warm_worker, args=(delay, include_packed),
                                  name="uw-library-warmup", daemon=True)
        _WARM_SCHEDULER["thread"] = thread
        thread.start()


def _schedule_library_warmup(delay=0.0):
    """Warm the read model as soon as the plugin loads.

    The warm-up holds the read locks for the projection pass (~2-3 s on the current
    100k-prompt library). Running it during ComfyUI's own start-up, before the HTTP port
    opens, keeps that window off the user's path; the previous 8 s delay pushed it into
    the first seconds of serving instead.
    """
    _request_library_warm(delay=delay, include_packed=True)


try:
    if os.environ.get("UW_SKIP_LIBRARY_WARMUP") != "1":
        _schedule_library_warmup()
except Exception as error:  # noqa: BLE001
    logger.warning(f"[Workbench] Library warm-up could not be scheduled: {error}")
