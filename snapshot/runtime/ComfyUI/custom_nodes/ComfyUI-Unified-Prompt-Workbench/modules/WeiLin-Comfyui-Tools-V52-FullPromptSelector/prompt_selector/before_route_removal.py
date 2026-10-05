# -*- coding: utf-8 -*-

import os
import json
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
from . import route_receipts
from . import route_jobs
import atexit
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageOps
from .semantic_projection import read_projection, project_library, merge_selection_edit, decision_for, confirm_classification, selector_subcategories, rebind_unchanged_prompt, binding as semantic_binding
from .import_plan import plan_import
from .prompt_merge import merge_preview, apply_merge, merged_source, known_merged_import
from .selector_library import favorites_view, apply_favorites, apply_collection, update_collection, collection_groups, prompt_collection, COLLECTION_KINDS, CLASS_ROUTES

# Logger导入
import logging
logger = logging.getLogger("weilin.prompt_selector")

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
_REVIEWED_LIBRARY_CACHE = {}
_LIBRARY_PAGE_SIZE = 30
_LIBRARY_PAGE_SIZE_MAX = 100


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
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            if compact:
                json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
            else:
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

def _atomic_save_json(file_path, data, create_backup=True, compact=False, sync_to_disk=True, expected_revision=None, *, server_receipt=None):
    """Validate version and retain server-owned route receipts in the same replace."""
    with _PROMPT_FILE_LOCK:
        is_library = os.path.normcase(os.path.abspath(file_path)) == os.path.normcase(os.path.abspath(DATA_FILE))
        current = {}
        if os.path.exists(file_path) and (expected_revision is not None or is_library):
            try:
                with open(file_path, "r", encoding="utf-8") as current_file:
                    current = json.load(current_file)
            except json.JSONDecodeError:
                # Retain original startup recovery for an already malformed file.
                if expected_revision is not None:
                    raise
            if expected_revision is not None:
                _require_revision({"base_revision": expected_revision}, current)
        if is_library:
            route_receipts.protect_receipts(current, data, server_receipt=server_receipt)
        elif server_receipt is not None:
            raise ValueError("Route receipts belong to the prompt library only")
        return _atomic_save_json_unlocked(file_path, data, create_backup, compact, sync_to_disk)

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
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                separator = data.get("settings", {}).get("separator", ", ")

        if prefix and selected_prompts_string:
            final_prompt = f"{prefix}{separator}{selected_prompts_string}"
        elif prefix:
            final_prompt = prefix
        else:
            final_prompt = selected_prompts_string

        return (final_prompt,)

def _prompt_data_signature():
    stat = os.stat(DATA_FILE)
    return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)


def _read_prompt_data_cached():
    global _PROMPT_DATA_CACHE, _PROMPT_DATA_CACHE_SIGNATURE

    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        signature = _prompt_data_signature()
        if _PROMPT_DATA_CACHE is not None and _PROMPT_DATA_CACHE_SIGNATURE == signature:
            return _PROMPT_DATA_CACHE
        # External replacement must not pair bytes from one file with another's signature.
        for _ in range(3):
            signature = _prompt_data_signature()
            with open(DATA_FILE, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if signature == _prompt_data_signature():
                _PROMPT_DATA_CACHE = data
                _PROMPT_DATA_CACHE_SIGNATURE = signature
                return data
        raise RuntimeError("词库正在更新，请重试读取")


def _cache_prompt_data(data):
    global _PROMPT_DATA_CACHE, _PROMPT_DATA_CACHE_SIGNATURE

    # A delayed caller may hold an older commit. Reload disk on the next read.
    with _PROMPT_CACHE_LOCK:
        _PROMPT_DATA_CACHE = None
        _PROMPT_DATA_CACHE_SIGNATURE = None
        _REVIEWED_LIBRARY_CACHE.clear()


def _reviewed_library_data(include_pending=False):
    # Retain only the current normal/review views. File identity and both revisions
    # are checked on every read; a missing/broken/new projection never uses an old view.
    projection_path = os.path.join(PROMPT_STORE_DIR, "semantic_projection.json")
    def version():
        stat = os.stat(projection_path)
        return (os.path.abspath(DATA_FILE), _prompt_data_signature(),
                os.path.abspath(projection_path), stat.st_mtime_ns,
                stat.st_ctime_ns, stat.st_size, stat.st_ino)
    with _PROMPT_FILE_LOCK, _PROMPT_CACHE_LOCK:
        for _ in range(3):
            signature = version()
            if _REVIEWED_LIBRARY_CACHE.get("version") != signature:
                _REVIEWED_LIBRARY_CACHE.clear()
                _REVIEWED_LIBRARY_CACHE["version"] = signature
            key = bool(include_pending)
            if key in _REVIEWED_LIBRARY_CACHE:
                return _REVIEWED_LIBRARY_CACHE[key]
            projection = read_projection(projection_path)
            result = project_library(_read_prompt_data_cached(), projection, include_pending=key)
            if version() == signature:
                _REVIEWED_LIBRARY_CACHE[key] = result
                return result
        _REVIEWED_LIBRARY_CACHE.clear()
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


def _library_index_payload():
    data = _reviewed_library_data()
    categories = []
    for category in data.get("categories", []) or []:
        summary = {
            key: value
            for key, value in category.items()
            if key != "prompts"
        }
        summary["prompt_count"] = len(category.get("prompts", []) or [])
        summary["prompts"] = []
        categories.append(summary)

    return {
        "version": data.get("version", "1.6"),
        "settings": data.get("settings", {}),
        "last_modified": data.get("last_modified"),
        "categories": categories,
        "total_prompts": sum(category["prompt_count"] for category in categories),
        "review_counts": data["_review_counts"],
        "semantic_classes": data.get("_semantic_class_labels", {}),
        "selector_groups": {kind: collection_groups(data) for kind in COLLECTION_KINDS},
        "selector_class_kinds": {key: route[0] for key, route in CLASS_ROUTES.items()},
        "semantic_subcategories": {key: sorted({label for category in data['categories'] for prompt in category['prompts']
            if prompt['_semantic'].get('primary_class') == key for label in prompt['_semantic'].get('subcategories', [])})
            for key in data.get('_semantic_class_labels', {})},
    }


def _prompt_search_rank(prompt, category_name, query):
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
    if any(query in value for value in names + body):
        return 2
    return 3 if query in category_name.casefold() else None


def _library_page_payload(category_id, query, offset, limit, view="", usage="", content_type="", theme="", subcategory="", collection=""):
    data = _reviewed_library_data(True) if view == "review" else _reviewed_library_data()
    categories = data.get("categories", []) or []
    normalized_query = str(query or "").strip().casefold()
    offset = max(0, int(offset or 0))
    limit = min(_LIBRARY_PAGE_SIZE_MAX, max(1, int(limit or _LIBRARY_PAGE_SIZE)))
    view = str(view or "").strip().casefold()
    if view not in {"", "all", "common", "favorites", "recent", "plans", "templates", "categories", "review"}:
        view = ""

    selected_name = ""
    target_categories = categories
    semantic_class = str(category_id).removeprefix("semantic:") if str(category_id).startswith("semantic:") else ""
    source_category = bool(category_id) and not semantic_class
    semantic_class = str(theme or semantic_class)
    theme_classes = {'style_medium', 'quality_detail'} if semantic_class == 'style_quality' else {semantic_class}
    if usage not in ("", "positive", "negative", "mixed", "unknown"):
        raise ValueError("Unknown usage filter")
    if content_type not in ("", "atomic_tag", "fragment", "template", "model_reference"):
        raise ValueError("Unknown content form filter")
    if source_category and view != "review":
        selected = next(
            (
                category
                for category in categories
                if str(category.get("id") or category.get("name") or "") == str(category_id or "")
            ),
            None,
        )
        if selected is None:
            selected = next(
                (category for category in categories if category.get("name") == category_id),
                None,
            )
        if selected is None:
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
            }
        selected_name = str(selected.get("name") or "")
        target_categories = [
            category
            for category in categories
            if str(category.get("name") or "") == selected_name
        ]

    known_groups = {group['id'] for group in collection_groups(data)}
    if collection and collection not in known_groups:
        raise ValueError('收藏组已不存在，请刷新列表')
    matches = []
    source_index = 0
    page_end = offset + limit
    # rows are (score, source_index, source_prompt, category_identity, category_name)
    for category in target_categories:
        category_identity = str(category.get("id") or category.get("name") or "")
        category_name = str(category.get("name") or "")
        for prompt in category.get("prompts", []) or []:
            semantic = prompt["_semantic"]
            if collection:
                memberships = [value for value in prompt_collection(prompt).get('groupIds', []) if value in known_groups] or ['default']
                if collection not in memberships:
                    continue
            if view == "review" and semantic["disposition"] in ("reviewed", "classified"):
                continue
            if semantic_class and not theme_classes.intersection([semantic.get("primary_class"), *semantic.get("alternative_classes", [])]):
                continue
            if subcategory and not any(label == subcategory or label.startswith(subcategory + '/') for label in semantic.get('subcategories', [])):
                continue
            if view == "templates" and prompt["_semantic"]["content_type"] != "template":
                source_index += 1
                continue
            if view == "common" and not normalized_query and not (prompt.get("favorite") is True or bool(prompt.get("last_used"))):
                source_index += 1
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
            score = _prompt_search_rank(prompt, category_name, normalized_query)
            if score is None:
                source_index += 1
                continue
            # Keep the source row here; only the returned page is copied below, so a
            # broad query no longer allocates a dict per match (66k+ per request).
            matches.append((score, source_index, prompt, category_identity, category_name))
            source_index += 1

    if view == "common" and not normalized_query:
        matches.sort(key=lambda row: str(row[2].get("last_used") or ""), reverse=True)
        matches.sort(key=lambda row: not (row[2].get("favorite") is True))
    elif view == "recent":
        matches.sort(key=lambda row: str(row[2].get("last_used") or ""), reverse=True)
    elif normalized_query:
        matches.sort(key=lambda row: (row[0], row[1]))
    total = len(matches)
    page_items = [{**row[2], "_categoryId": row[3], "_categoryName": row[4]}
                  for row in matches[offset:offset + limit]]

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


def _json_library_bytes():
    """Serialise the reviewed library; the compact form is ~116 MB, so keep it off the loop."""
    return json.dumps(_reviewed_library_data(), ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _packed_library_payload():
    """Serialise once per revision and cache the gzip form (~10 MB) for repeat reads."""
    payload = _reviewed_library_data()
    revision = _revision(payload)
    if _PACKED_LIBRARY_CACHE["revision"] == revision and _PACKED_LIBRARY_CACHE["packed"] is not None:
        return revision, _PACKED_LIBRARY_CACHE["packed"]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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


@PromptServer.instance.routes.get("/prompt_selector/library/index")
async def get_library_index(request):
    if not os.path.exists(DATA_FILE):
        return web.json_response({"error": "Data file not found"}, status=404)
    try:
        payload = await asyncio.to_thread(_library_index_payload)
        response = _with_etag(web.json_response(payload), payload.get("last_modified"))
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.get("/prompt_selector/library/prompts")
async def get_library_prompts_page(request):
    if not os.path.exists(DATA_FILE):
        return web.json_response({"error": "Data file not found"}, status=404)
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
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = _ensure_data_compatibility(json.load(file))
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
                        prompt = {**prompt, "_semantic": {**decision, 'subcategories': selector_subcategories(decision, prompt)}}
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
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
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
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                local_data = json.load(f)
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
                _atomic_save_json(DATA_FILE, local_data, create_backup=True, expected_revision=_request_revision(request, post))
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
        with open(DATA_FILE, "r", encoding="utf-8") as stream:
            file_data = json.load(stream)
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

        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
        _require_revision(data, file_data)
        _require_revision(data, file_data)

        prefix_to_delete = category_name_to_delete + '/'
        categories_to_keep = []
        for cat in file_data.get("categories", []):
            original_cat_name = cat.get("name", "")
            # Sanitize the name by removing any leading slashes before comparison
            sanitized_cat_name = original_cat_name.lstrip('/')
            
            keep = sanitized_cat_name != category_name_to_delete and not sanitized_cat_name.startswith(prefix_to_delete)
            if keep:
                categories_to_keep.append(cat)


        file_data["categories"] = categories_to_keep

        if "categories" not in file_data:
            file_data["categories"] = []

        file_data["last_modified"] = datetime.now().isoformat()

        # 使用原子保存机制
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, expected_revision=data.get("base_revision"))

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

        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
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

        if deleted_count <= 0:
            return web.json_response({
                "error": "No matching prompts found for batch_delete; source category and prompt IDs may be stale",
                "deleted_count": 0
            }, status=404)

        file_data["last_modified"] = now

        # 使用原子保存机制
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, expected_revision=data.get("base_revision"))

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

def _split_category_path(name):
    return [
        part.strip()
        for part in str(name or "").replace("／", "/").split("/")
        if part.strip()
    ]

def _join_category_path(parts):
    return "/".join([
        str(part or "").strip()
        for part in parts
        if str(part or "").strip()
    ])

def _category_matches_route_prefix(category_name, route_prefix, include_children):
    category_parts = _split_category_path(category_name)
    prefix_parts = _split_category_path(route_prefix)
    if not prefix_parts:
        return False
    if include_children:
        return category_parts[:len(prefix_parts)] == prefix_parts
    return category_parts == prefix_parts

def _build_anima_target_path(target_root, target_sub_path):
    target_parts = _split_category_path(target_root)
    sub_parts = _split_category_path(target_sub_path)
    if (
        target_parts
        and len(sub_parts) >= len(target_parts)
        and sub_parts[:len(target_parts)] == target_parts
    ):
        return _join_category_path(sub_parts)
    return _join_category_path([*target_parts, *sub_parts])

def _build_route_target_category_name(source_name, route_prefix, target_base, include_children):
    source_parts = _split_category_path(source_name)
    prefix_parts = _split_category_path(route_prefix)
    target_parts = _split_category_path(target_base)
    if not include_children:
        return _join_category_path(target_parts)
    return _join_category_path([*target_parts, *source_parts[len(prefix_parts):]])

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
    with open(DATA_FILE, 'r', encoding='utf-8') as file:
        file_data = json.load(file)
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
    _cache_prompt_data(file_data)
    return {"success": True, "created": True, "category": _category_summary(category), "revision": _revision(file_data)}


def _apply_upsert_prompt(payload):
    with open(DATA_FILE, 'r', encoding='utf-8') as file:
        file_data = json.load(file)
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
    _cache_prompt_data(file_data)
    return {
        "success": True,
        "prompt": prompt,
        "category": _category_summary(target_category),
        "revision": _revision(file_data),
    }


def _apply_delete_prompt(prompt_id, expected_revision):
    with open(DATA_FILE, 'r', encoding='utf-8') as file:
        file_data = json.load(file)
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
    _cache_prompt_data(file_data)
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
    with open(DATA_FILE, encoding='utf-8') as stream:
        data = json.load(stream)
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
            _atomic_save_json(DATA_FILE, data, create_backup=_should_create_route_branch_backup(),
                             expected_revision=payload.get('base_revision'))
            _cache_prompt_data(data)
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
    with open(DATA_FILE, encoding='utf-8') as stream:
        data = json.load(stream)
    _require_revision(payload, data)
    projection = read_projection(os.path.join(PROMPT_STORE_DIR, 'semantic_projection.json'))
    if payload.get('commit') is not True:
        return merge_preview(data, projection, payload.get('prompt_ids'), payload.get('canonical_id'))
    merged, preview = apply_merge(data, projection, payload, datetime.now().isoformat())
    _atomic_save_json(DATA_FILE, merged, create_backup=True, expected_revision=payload.get('base_revision'))
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
        with open(DATA_FILE, 'r', encoding='utf-8') as file:
            current = json.load(file)
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


def _apply_route_patch_groups(groups, start_time, expected_revision):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        file_data = json.load(f)
    _require_revision({"base_revision": expected_revision}, file_data)

    file_data = _ensure_data_compatibility(file_data)
    categories = file_data.get("categories", [])
    now = datetime.now().isoformat()
    moved_count = 0
    appended_count = 0
    missing_ids = []
    touched_sources = set()
    touched_targets = set()
    group_results = []

    for group in groups:
        target_name = group["target_name"]
        target_ids = set(group["prompt_ids"])
        target_category = _get_or_create_category(categories, target_name, now)
        target_category.setdefault("prompts", [])
        found_prompts = {}

        for category in categories:
            prompts = category.get("prompts", []) or []
            next_prompts = []
            changed = False
            is_target_category = category is target_category
            for prompt in prompts:
                prompt_id = str(prompt.get("id") or "").strip()
                if prompt_id and prompt_id in target_ids:
                    found_prompts.setdefault(prompt_id, prompt)
                    if is_target_category:
                        next_prompts.append(prompt)
                    else:
                        changed = True
                        moved_count += 1
                        touched_sources.add(category.get("name", ""))
                    continue
                next_prompts.append(prompt)
            if changed:
                category["prompts"] = next_prompts
                category["updated_at"] = now

        existing_target_ids = {
            str(prompt.get("id") or "").strip()
            for prompt in target_category.get("prompts", []) or []
            if str(prompt.get("id") or "").strip()
        }
        group_appended = 0
        for prompt_id in group["prompt_ids"]:
            prompt = found_prompts.get(prompt_id)
            if not prompt:
                missing_ids.append(prompt_id)
                continue
            if prompt_id in existing_target_ids:
                continue
            prompt["updated_at"] = now
            target_category["prompts"].append(prompt)
            existing_target_ids.add(prompt_id)
            appended_count += 1
            group_appended += 1

        if group_appended or target_ids.intersection(existing_target_ids):
            target_category["updated_at"] = now
            touched_targets.add(target_name)

        group_results.append({
            "target_name": target_name,
            "requested_count": len(group["prompt_ids"]),
            "found_count": len(found_prompts),
            "appended_count": group_appended,
        })

    if moved_count or appended_count:
        file_data["last_modified"] = now
        _atomic_save_json(
            DATA_FILE,
            file_data,
            create_backup=_should_create_route_branch_backup(),
            compact=True,
            sync_to_disk=False,
            expected_revision=expected_revision,
        )
        _cache_prompt_data(file_data)

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info(
        "route_patch moved %s prompts, appended %s prompts to %s target(s) in %sms",
        moved_count,
        appended_count,
        len(touched_targets),
        elapsed_ms,
    )
    return {
        "success": True,
        "moved_count": moved_count,
        "appended_count": appended_count,
        "missing_count": len(missing_ids),
        "missing_ids": missing_ids[:50],
        "source_categories": sorted(touched_sources),
        "target_categories": sorted(touched_targets),
        "groups": group_results,
        "elapsed_ms": elapsed_ms,
        "revision": _revision(file_data),
    }

def _route_planner_helpers():
    return {
        "match": _category_matches_route_prefix,
        "build_target": _build_anima_target_path,
        "build_category_name": _build_route_target_category_name,
        "get_or_create": _get_or_create_category,
        "normalize": lambda name: _join_category_path(_split_category_path(name)),
        "now": lambda: datetime.now().isoformat(),
    }


_ROUTE_JOBS = None


def _route_job_preview(payload):
    with _PROMPT_FILE_LOCK:
        current = _route_job_load()
        result = route_receipts.plan_route(copy.deepcopy(current), payload, _route_planner_helpers())
        receipt = result["receipt"]
        counts = {}
        for action in receipt["actions"]:
            identity = action["source_category_id"]
            counts[identity] = counts.get(identity, 0) + 1
        return {"revision": _revision(current), "counts": receipt["counts"],
                "target_base": receipt["scope"]["target_base"],
                "source_categories": [dict(item, prompt_count=counts.get(item["id"], 0)) for item in receipt["sources"]]}


@PromptServer.instance.routes.post("/prompt_selector/categories/route_preview")
async def route_job_preview(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        payload["base_revision"] = _request_revision(request, payload)
        return _success_response(await asyncio.to_thread(_route_job_preview, payload))
    except route_receipts.RevisionConflict as error:
        return web.json_response({"error": str(error), "conflict": True}, status=409)
    except (route_receipts.RouteError, ValueError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)


def _route_job_load():
    with open(DATA_FILE, "r", encoding="utf-8") as stream:
        return json.load(stream)


def _route_job_save(data, *, expected_revision, server_receipt):
    _atomic_save_json(DATA_FILE, data, create_backup=_should_create_route_branch_backup(),
                      compact=True, sync_to_disk=False, expected_revision=expected_revision,
                      server_receipt=server_receipt)
    try:
        _cache_prompt_data(data)
    except Exception:
        logger.exception("Route committed; prompt cache refresh failed")


def _get_route_jobs():
    global _ROUTE_JOBS
    # Called on the HTTP event loop, with no await between check and assignment.
    if _ROUTE_JOBS is None:
        _ROUTE_JOBS = route_jobs.RouteJobs(_PROMPT_FILE_LOCK, _route_job_load, _route_job_save,
                                          _route_planner_helpers(), lambda: datetime.now().isoformat())
        atexit.register(_ROUTE_JOBS.close)
    return _ROUTE_JOBS


async def _route_job_response(request, action):
    try:
        owner = _get_route_jobs()
        if action == "start":
            payload = await request.json()
            if not isinstance(payload, dict):
                raise route_receipts.RouteError("request must be an object")
            payload["base_revision"] = _request_revision(request, payload)
            result = owner.start(payload)
        elif action == "cancel":
            result = owner.cancel(request.match_info["operation_id"])
        else:
            result = await asyncio.to_thread(getattr(owner, action), request.match_info["operation_id"])
        return web.json_response(result, status=202 if action == "start" else 200)
    except route_jobs.UnknownJob:
        return web.json_response({"error": "结果尚无法核验，请保留原编号，不要重复提交。", "unknown": True}, status=404)
    except route_jobs.QueueFull:
        return web.json_response({"error": "归类队列已满，本次未加入队列。", "queued": False}, status=503)
    except route_receipts.OperationConflict as error:
        return web.json_response({"error": str(error), "conflict": True, "unknown": True}, status=409)
    except (route_receipts.RouteError, ValueError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception:
        logger.exception("Route job request failed")
        return web.json_response({"error": "归类请求结果尚无法核验，请保留原编号。", "unknown": True}, status=500)


@PromptServer.instance.routes.post("/prompt_selector/categories/route_jobs/start")
async def route_job_start(request):
    return await _route_job_response(request, "start")


@PromptServer.instance.routes.get("/prompt_selector/categories/route_jobs/{operation_id}")
async def route_job_status(request):
    return await _route_job_response(request, "status")


@PromptServer.instance.routes.post("/prompt_selector/categories/route_jobs/{operation_id}/cancel")
async def route_job_cancel(request):
    return await _route_job_response(request, "cancel")


@PromptServer.instance.routes.get("/prompt_selector/categories/route_jobs/{operation_id}/export")
async def route_job_export(request):
    return await _route_job_response(request, "export")


@PromptServer.instance.routes.post("/prompt_selector/prompts/route_patch")
async def route_prompts_by_id_patch(request):
    """Move prompt ids to target categories without posting the whole library.

    This endpoint is idempotent: if a prompt is already in its target category,
    the request is treated as successful. It avoids relying on the source
    category still containing the prompts after a previous quick classification.
    """
    start_time = time.perf_counter()
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        raw_groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(raw_groups, list):
            return web.json_response({"error": "groups must be a list"}, status=400)

        groups = []
        seen_targets = set()
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue
            target_name = _join_category_path(_split_category_path(raw_group.get("target_name") or ""))
            prompt_ids = []
            seen_ids = set()
            for raw_id in raw_group.get("prompt_ids") or []:
                prompt_id = str(raw_id or "").strip()
                if prompt_id and prompt_id not in seen_ids:
                    seen_ids.add(prompt_id)
                    prompt_ids.append(prompt_id)
            if target_name and prompt_ids:
                groups.append({
                    "target_name": target_name,
                    "prompt_ids": prompt_ids,
                })
                seen_targets.add(target_name)

        if not groups:
            return web.json_response({"success": True, "moved_count": 0, "groups": []})

        async with _PROMPT_DATA_LOCK:
            result = await asyncio.to_thread(_apply_route_patch_groups, groups, start_time, data.get("base_revision"))
        return _success_response(result)
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/prompt_selector/prompts/batch_move")
async def batch_move_prompts(request):
    """批量移动提示词到其他分类

    v55 修复点：不再只使用节点 selectedCategory 作为源分类。
    支持 prompt_items 中携带每个 prompt 的真实 source_category，
    因而父分类聚合视图、收藏夹视图、搜索视图中的批量移动也能正确落库。
    """
    try:
        data = await request.json()
        data["base_revision"] = _request_revision(request, data)
        source_category = data.get("source_category")
        target_category = data.get("target_category")
        prompt_ids = {str(pid) for pid in data.get("prompt_ids", []) if pid}
        prompt_items = data.get("prompt_items", []) or []

        if not target_category or (not prompt_ids and not prompt_items):
            return web.json_response({"error": "Missing parameters"}, status=400)

        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
        _require_revision(data, file_data)

        categories = file_data.get("categories", [])
        category_map = {category.get("name"): category for category in categories}
        target_cat = category_map.get(target_category)

        if not target_cat:
            return web.json_response({"error": "Target category not found"}, status=404)

        # 新协议：按每个 prompt 的真实源分类移动。若 source_category 缺失，则退化为全局按 ID 查找。
        ids_by_category = {}
        global_ids = set()
        for item in prompt_items:
            if not isinstance(item, dict):
                continue
            prompt_id = item.get("id") or item.get("prompt_id")
            if not prompt_id:
                continue
            prompt_id = str(prompt_id)
            item_source = item.get("source_category") or item.get("category")
            if item_source:
                ids_by_category.setdefault(item_source, set()).add(prompt_id)
            else:
                global_ids.add(prompt_id)

        # 旧协议兼容：只有 source_category + prompt_ids 时，仍按单分类移动。
        if not ids_by_category and not global_ids:
            if not source_category or not prompt_ids:
                return web.json_response({"error": "Missing parameters"}, status=400)
            if source_category not in category_map:
                return web.json_response({"error": "Source category not found"}, status=404)
            ids_by_category[source_category] = set(prompt_ids)

        requested_items = [(str(item.get("id") or item.get("prompt_id") or ""), item.get("source_category") or item.get("category"))
                           for item in prompt_items if isinstance(item, dict)] if prompt_items else [(str(pid), source_category) for pid in data.get("prompt_ids", [])]
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
                return web.json_response({"error": "Prompt identity or source changed; refresh before moving"}, status=409)
        projection = read_projection(os.path.join(PROMPT_STORE_DIR, "semantic_projection.json"))

        prompts_to_move = []
        touched_source_categories = []
        now = datetime.now().isoformat()

        # 从真实源分类中移除。若源分类等于目标分类，则该项为 no-op，避免自移动造成顺序变化。
        for category in categories:
            cat_name = category.get("name")
            if cat_name == target_category:
                continue

            ids_for_this_category = set(global_ids)
            ids_for_this_category.update(ids_by_category.get(cat_name, set()))
            if not ids_for_this_category:
                continue

            kept_prompts = []
            moved_from_this_category = []
            for prompt in category.get("prompts", []):
                if str(prompt.get("id")) in ids_for_this_category:
                    old_prompt = copy.deepcopy(prompt)
                    rebind_unchanged_prompt(projection, category, old_prompt, target_cat, prompt)
                    moved_from_this_category.append(prompt)
                else:
                    kept_prompts.append(prompt)

            if moved_from_this_category:
                category["prompts"] = kept_prompts
                category["updated_at"] = now
                touched_source_categories.append(cat_name)
                prompts_to_move.extend(moved_from_this_category)

        moved_count = len(prompts_to_move)
        if moved_count <= 0:
            return web.json_response({
                "error": "No matching prompts found for batch_move; source category and prompt IDs may be stale",
                "moved_count": 0
            }, status=404)

        target_cat.setdefault("prompts", [])
        target_existing_ids = {str(prompt.get("id")) for prompt in target_cat.get("prompts", []) if prompt.get("id")}
        appended_count = 0
        for prompt in prompts_to_move:
            prompt_id = str(prompt.get("id")) if prompt.get("id") else ""
            if prompt_id and prompt_id in target_existing_ids:
                continue
            target_cat["prompts"].append(prompt)
            if prompt_id:
                target_existing_ids.add(prompt_id)
            appended_count += 1

        target_cat["updated_at"] = now
        file_data["last_modified"] = now

        # 使用原子保存机制
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, expected_revision=data.get("base_revision"))

        return _success_response({
            "success": True,
            "moved_count": moved_count,
            "appended_count": appended_count,
            "source_categories": touched_source_categories,
            "target_category": target_category,
            "revision": _revision(file_data)
        })
    except RevisionConflict as e:
        return web.json_response({"error": str(e), "conflict": True, "expected_revision": e.expected, "current_revision": e.actual, "draft_preserved": True}, status=409)
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
            
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
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
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, expected_revision=data.get("base_revision"))

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
            
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
        _require_revision(data, file_data)
            
        found = False
        for category in file_data["categories"]:
            if (category.get("id") == category_id if category_id else category["name"] == category_name):
                for prompt in category["prompts"]:
                    if prompt.get("id") == prompt_id:
                        prompt["favorite"] = data.get("favorite", not prompt.get("favorite", False))
                        found = True

                        # 更新提示词、分类和全局时间戳
                        now = datetime.now().isoformat()
                        prompt["updated_at"] = now
                        category["updated_at"] = now
                        file_data["last_modified"] = now
                        break
                if found:
                    break

        if not found:
            return web.json_response({"error": "资料已移动或不存在，请刷新后重试"}, status=404)

        # 使用原子保存机制
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, expected_revision=data.get("base_revision"))

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
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            file_data = json.load(f)
        _require_revision(data, file_data)
        target = None
        for category in file_data.get("categories", []):
            category_identity = str(category.get("id") or category.get("name") or "")
            if category_id and category_identity != category_id and str(category.get("name") or "") != category_id:
                continue
            for prompt in category.get("prompts", []) or []:
                if str(prompt.get("id") or "") == prompt_id:
                    target = (category, prompt)
                    break
            if target:
                break
        if target is None:
            return web.json_response({"error": "Prompt not found"}, status=404)
        category, prompt = target
        now = datetime.now().isoformat()
        prompt["last_used"] = now
        prompt["usage_count"] = int(prompt.get("usage_count") or 0) + 1
        category["updated_at"] = now
        file_data["last_modified"] = now
        _atomic_save_json(DATA_FILE, file_data, create_backup=True, expected_revision=data.get("base_revision"))
        _cache_prompt_data(file_data)
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
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)

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
                upgraded_data = _ensure_data_compatibility(existing_data)
                _atomic_save_json(DATA_FILE, upgraded_data, create_backup=True)
                logger.info("✅ 数据文件已升级，添加了时间戳字段")

        except Exception as e:
            logger.error(f"⚠️ 升级数据文件失败: {e}")
            # 不影响启动，继续运行

# 在插件加载时调用初始化
initialize_data_file()


def _warm_library_caches():
    """Precompute the reviewed library views so the first user request is not the cold one."""
    _reviewed_library_data()
    _library_index_payload()
    _library_page_payload("", "", 0, _LIBRARY_PAGE_SIZE)
    _packed_library_payload()


def _schedule_library_warmup(delay=8.0):
    def runner():
        try:
            time.sleep(delay)
            _warm_library_caches()
            logger.info("[Workbench] Library caches warmed; first open is served from cache.")
        except Exception as error:  # noqa: BLE001
            logger.warning(f"[Workbench] Library warm-up skipped: {error}")

    threading.Thread(target=runner, name="uw-library-warmup", daemon=True).start()


try:
    if os.environ.get("UW_SKIP_LIBRARY_WARMUP") != "1":
        _schedule_library_warmup()
except Exception as error:  # noqa: BLE001
    logger.warning(f"[Workbench] Library warm-up could not be scheduled: {error}")
