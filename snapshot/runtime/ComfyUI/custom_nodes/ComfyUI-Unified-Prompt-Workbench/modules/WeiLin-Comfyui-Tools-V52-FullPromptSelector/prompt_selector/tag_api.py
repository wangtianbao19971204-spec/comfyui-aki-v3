import asyncio
import json
import os
import re
import threading
import time
import uuid
import logging
from pathlib import Path
from aiohttp import web
from server import PromptServer

from ..app.server.dao import dao
from .tag_library import (TagConflict, TagLibrary, STRING_AREA_PREFIX, STRING_GROUP_UUID,
                          STRING_LOOSE_UUID)
from .tag_import_plan import preview_tag_import
from .tag_batch_jobs import TagBatchJobs, BatchConflict, BatchError, QueueFull, UnknownJob
from . import prompt_selector as prompt_store
from .selector_library import collection_groups
from .tag_identity_bridge import TagIdentityBridge
from . import item_maintenance
from . import item_batch
from . import tag_links

logger = logging.getLogger("weilin.prompt_selector")


def _warm_tag_catalog(delay=0.0):
    """Build the folder tree and the default page before the first Tag panel opens.

    The tree is one 289k-row count pass and the default 基础 Tag view counts the
    comma-free rows; both used to land on the user's first click after a restart.
    """
    def runner():
        try:
            if delay:
                time.sleep(delay)
            started = time.perf_counter()
            library().categories()
            # Every shape option in the 正文形状 dropdown costs a full count pass the
            # first time it is chosen (220 ms / 950 ms / 1057 ms measured); pay it here
            # instead of on the user's click.
            for shape in ("atomic", "group", "string"):
                library().page(shape=shape, offset=0, limit=120)
            # The 标签串 split is the default 基础 Tag view, so warm both sides of it.
            library().page(scope="tags", offset=0, limit=120)
            library().page(scope="strings", offset=0, limit=120)
            logger.info("[Workbench] Tag catalog warmed in %.1f s; the Tag manager opens from cache.",
                        time.perf_counter() - started)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"[Workbench] Tag catalog warm-up skipped: {error}")

    threading.Thread(target=runner, name="uw-tag-catalog-warmup", daemon=True).start()


# Stable, repository-relative evidence location for the audited candidate
# mapping. The test hook only changes the read-only candidate source.
def _default_candidate_path():
    relative = Path('benchmark_reports') / '2026-09-11_shared_collections' / 'evidence' / 'tag_link_candidates.json'
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[-1] / relative


_DEFAULT_CANDIDATE_PATH = _default_candidate_path()
_CANDIDATE_PATH_OVERRIDE = None
_BRIDGE_CACHE = {'path': None, 'bridge': None}


def _candidate_path():
    override = _CANDIDATE_PATH_OVERRIDE
    return Path(override) if override is not None else _DEFAULT_CANDIDATE_PATH


def set_candidate_path_for_tests(path):
    """Test-only override; pass None to restore the default evidence path."""
    global _CANDIDATE_PATH_OVERRIDE
    _CANDIDATE_PATH_OVERRIDE = path
    _BRIDGE_CACHE['path'] = None
    _BRIDGE_CACHE['bridge'] = None


def identity_bridge():
    """Load the read-only candidate bridge, caching by resolved path."""
    path = _candidate_path()
    if _BRIDGE_CACHE['bridge'] is None or _BRIDGE_CACHE['path'] != str(path):
        _BRIDGE_CACHE['bridge'] = TagIdentityBridge(path)
        _BRIDGE_CACHE['path'] = str(path)
    return _BRIDGE_CACHE['bridge']


def library():
    return TagLibrary(dao.tags_db_path)


def catalog():
    data = prompt_store._read_prompt_data_cached()
    return {'collections': collection_groups(data), 'collection_revision': prompt_store._revision(data)}


_LIBRARY_LINKS = {'revision': None, 'value': None}
_LIBRARY_LINK_LOCK = threading.RLock()


def _path_name(text):
    """法典分类名两侧的空格不统一（"基础涩涩 / 各种体位 / 后入/背后位"），比对前先归一。"""
    return re.sub(r'\s*/\s*', ' / ', str(text or '')).strip()


def _prompt_library_index():
    """提示词片段的分类索引：全名 -> {id,name,count}，以及区域 -> 该区域下的分类。"""
    data = prompt_store._read_prompt_data_cached()
    revision = prompt_store._revision(data)
    with _LIBRARY_LINK_LOCK:
        if _LIBRARY_LINKS['value'] is not None and _LIBRARY_LINKS['revision'] == revision:
            return _LIBRARY_LINKS['value']
        by_name, by_area = {}, {}
        for category in data.get('categories', []) or []:
            name = _path_name(category.get('name'))
            record = {'id': category.get('id') or category.get('name'), 'name': category.get('name'),
                      'count': len(category.get('prompts') or [])}
            by_name[name] = record
            by_area.setdefault(name.split(' / ')[0], []).append(record)
        value = {'by_name': by_name, 'by_area': by_area}
        _LIBRARY_LINKS.update({'revision': revision, 'value': value})
        return value


def attach_string_links(payload):
    """给「标签 tags 串」里每一项标出提示词片段里的同名分组，前端据此提供跳转。

    这批串本来就大量与提示词片段同源（逐 token 比对：同名分组里约一半条目两边一模一样），
    所以不是"再造一份"，而是让用户从桶里一键回到它真正的家。
    """
    bucket = next((group for group in payload.get('groups', [])
                   if group.get('p_uuid') == STRING_GROUP_UUID), None)
    if bucket is None:
        return payload
    index = _prompt_library_index()
    for child in bucket.get('groups', []):
        uuid_value = child.get('g_uuid') or ''
        if uuid_value.startswith(STRING_AREA_PREFIX):
            area = _path_name(str(child.get('name') or '').replace('（整区）', ''))
            matches = index['by_area'].get(area) or []
            if matches:
                child['library'] = {'area': area, 'categories': len(matches),
                                    'count': sum(item['count'] for item in matches),
                                    'category_id': matches[0]['id'], 'category_name': matches[0]['name']}
        elif uuid_value and uuid_value != STRING_LOOSE_UUID:
            name = _path_name(child.get('name'))
            hit = index['by_name'].get(name)
            if hit:
                child['library'] = {'area': name.split(' / ')[0], 'categories': 1, 'count': hit['count'],
                                    'category_id': hit['id'], 'category_name': hit['name']}
    return payload


def _batch_catalog():
    groups = catalog()
    with library().connection() as conn:
        subgroups = {row[0] for row in conn.execute('SELECT g_uuid FROM tag_subgroups')}
    # The worker checks the Tag revision inside its owning transaction.
    return None, groups['collection_revision'], subgroups


TAG_BATCH_JOBS = TagBatchJobs(library, prompt_store._PROMPT_FILE_LOCK, _batch_catalog)


def normalize_membership(item, groups):
    known = {group['id'] for group in groups}
    item['collection_ids'] = [identity for identity in item.get('collection_ids', []) if identity in known] or (['default'] if item.get('favorite') else [])
    return item


def item_view(identity):
    result = library().get(identity)
    result.update(catalog())
    normalize_membership(result['item'], result['collections'])
    return result


def _save_tag(payload, expected):
    if not isinstance(payload, dict):
        raise ValueError('Tag 操作格式无效')
    with prompt_store._PROMPT_FILE_LOCK:
        groups = catalog()
        known = {group['id'] for group in groups['collections']}
        rows = payload.get('items', []) if payload.get('operation') == 'batch' else [payload]
        if payload.get('operation') == 'import':
            bundle = payload.get('bundle')
            if not isinstance(bundle, dict) or not isinstance(bundle.get('items'), list):
                raise ValueError('Tag 导入文件格式无效')
            rows = bundle['items']
        if not isinstance(rows, list):
            raise ValueError('Tag 操作必须包含记录列表')
        if any('collection_ids' in row for row in rows if isinstance(row, dict)):
            if payload.get('collection_revision') != groups['collection_revision']:
                raise TagConflict(library().revision())
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('Tag 操作格式无效')
                memberships = row.get('collection_ids', [])
                if not isinstance(memberships, list) or any(not isinstance(identity, str) for identity in memberships):
                    raise ValueError('收藏组必须是 ID 列表')
                if any(identity not in known for identity in memberships):
                    raise ValueError('收藏组已不存在，请重新选择。未保存当前修改。')
        result = library().update(payload, expected)
        result.update(groups)
        return result


def import_preview(payload):
    if not isinstance(payload, dict):
        raise ValueError('Tag 导入预览格式无效')
    with prompt_store._PROMPT_FILE_LOCK:
        groups = catalog()
        if payload.get('collection_revision') != groups['collection_revision']:
            raise TagConflict(library().revision())
        return preview_tag_import(dao.tags_db_path, payload.get('bundle'), payload.get('overwrite') is True,
            groups['collection_revision'], [group['id'] for group in groups['collections']])


def import_operation(plan, operation_id, status, revision=None, error=None):
    plan = plan or {}
    counts = plan.get('counts', {})
    committed = status == 'committed'
    return {'contract': 'weilin-tag-import-operation-v1', 'operation_id': operation_id,
        'status': status, 'atomic': True, 'committed': counts.get('will_write') if committed else 0,
        'uncommitted': 0 if committed else counts.get('will_write'), 'skipped': counts.get('will_skip'),
        'before_revision': plan.get('base_revision'), 'after_revision': revision,
        'collection_revision': plan.get('collection_revision'), 'canonical_bundle_hash': plan.get('canonical_bundle_hash'),
        'preflight_token': plan.get('preflight_token'), 'counts': counts,
        'items': plan.get('items', []), 'category_counts': plan.get('category_counts', {}),
        'failure': str(error) if error else None, 'persistence': 'response_export',
        'recovery': {'mode': 'none' if committed else 'repreview_original_bundle', 'partial_batches': False}}


def save_tag(payload, expected):
    if not isinstance(payload, dict) or payload.get('operation') != 'import' or 'preflight_token' not in payload:
        return _save_tag(payload, expected)
    plan = None
    operation_id = str(uuid.uuid4())
    try:
        # Hold the collection owner lock across preflight and the existing Tag
        # transaction. Any Tag change between the snapshot and BEGIN IMMEDIATE
        # is rejected by update's original revision check.
        with prompt_store._PROMPT_FILE_LOCK:
            plan = import_preview(payload)
            if not plan.get('committable', True) or payload.get('confirmed') is not True or payload.get('preflight_token') != plan['preflight_token'] or str(expected or '').strip('"') != plan['base_revision']:
                raise TagConflict(plan['base_revision'])
            result = _save_tag(payload, expected)
            result['operation'] = import_operation(plan, operation_id, 'committed', result['revision'])
            return result
    except Exception as error:
        error.operation = import_operation(plan, operation_id, 'not_committed', error=error)
        raise


def export_tags(ids=None):
    with prompt_store._PROMPT_FILE_LOCK:
        result = library().export_bundle(ids)
        groups = catalog()
        for item in result['items']:
            normalize_membership(item, groups['collections'])
        return {**result, **groups}


def response(result, status=200):
    headers = {'Cache-Control': 'no-store'}
    if result.get('revision'):
        headers['ETag'] = '"' + result['revision'] + '"'
    return web.json_response(result, status=status, headers=headers)


def operation_error(error):
    return {'committed': 0, 'operation': error.operation} if hasattr(error, 'operation') else {}


async def run(callback):
    try:
        return response(await asyncio.to_thread(callback))
    except TagConflict as error:
        return response({'error': str(error), 'conflict': True, 'revision': error.revision, **operation_error(error)}, 409)
    except BatchConflict as error:
        return response({'error': str(error), 'conflict': True, 'revision': error.revision}, 409)
    except QueueFull as error:
        return response({'error': str(error), 'retryable': True}, 429)
    except UnknownJob as error:
        return response({'error': str(error), 'unknown': True}, 404)
    except BatchError as error:
        return response({'error': str(error)}, 400)
    except KeyError as error:
        return response({'error': str(error), **operation_error(error)}, 404)
    except (ValueError, TypeError) as error:
        return response({'error': str(error), **operation_error(error)}, 400)
    except Exception as error:
        if hasattr(error, 'operation'):
            return response({'error': str(error), **operation_error(error)}, 500)
        raise


@PromptServer.instance.routes.post('/prompt_selector/tags/batch/start')
async def tag_batch_start(request):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON'}, 400)
    return await run(lambda: TAG_BATCH_JOBS.start(payload))


@PromptServer.instance.routes.get('/prompt_selector/tags/batch/status')
async def tag_batch_status(request):
    return await run(lambda: TAG_BATCH_JOBS.status(request.query.get('token', '')))


@PromptServer.instance.routes.post('/prompt_selector/tags/batch/cancel')
async def tag_batch_cancel(request):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON'}, 400)
    return await run(lambda: TAG_BATCH_JOBS.cancel(payload.get('token', '') if isinstance(payload, dict) else None))


@PromptServer.instance.routes.get('/prompt_selector/tags/batch/export')
async def tag_batch_export(request):
    return await run(lambda: TAG_BATCH_JOBS.export(request.query.get('token', ''), request.query.get('kind') == 'failed'))


@PromptServer.instance.routes.get('/prompt_selector/tags/index')
async def tag_index(request):
    return await run(lambda: attach_string_links({**library().categories(), **catalog()}))


@PromptServer.instance.routes.get('/prompt_selector/tags/page')
async def tag_page(request):
    q = request.query
    def page():
        groups = catalog()
        collection = q.get('collection', '')
        known = [group['id'] for group in groups['collections']]
        if collection and collection not in known:
            raise ValueError('收藏组已不存在，请刷新列表')
        result = library().page(q.get('q', ''), q.get('subgroup', ''), q.get('group', ''), q.get('offset', 0),
                                q.get('limit', 100), q.get('favorite') == 'true', collection, known,
                                q.get('shape', ''), q.get('scope', ''), theme=q.get('theme', ''))
        for item in result['items']:
            normalize_membership(item, groups['collections'])
        return {**result, **groups}
    return await run(page)


@PromptServer.instance.routes.get('/prompt_selector/tags/complete')
async def tag_complete(request):
    def search():
        result = library().page(request.query.get('search', ''), offset=request.query.get('offset', 0), limit=request.query.get('limit', 20))
        return {'success':True, 'words':[{'tag_name':item['text'], 'resource_id':item['resource_id'],
            'category':-1, 'post_count':0, 'shared':True} for item in result['items']]}
    return await run(search)


@PromptServer.instance.routes.get('/prompt_selector/tags/item')
async def tag_item(request):
    return await run(lambda: item_view(request.query.get('id')))


@PromptServer.instance.routes.get('/prompt_selector/tags/export')
async def tag_export(request):
    ids = request.query.get('ids')
    result = await run(lambda: export_tags(ids.split(',') if ids else None))
    if result.status == 200:
        result.headers['Content-Disposition'] = 'attachment; filename="shared-tags.json"'
    return result


@PromptServer.instance.routes.post('/prompt_selector/tags/pre_import')
async def tag_pre_import(request):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON', 'committed': 0}, 400)
    return await run(lambda: import_preview(payload))


@PromptServer.instance.routes.post('/prompt_selector/tags/update')
async def tag_update(request):
    expected = request.headers.get('If-Match')
    if not expected:
        return response({'error': '请先读取当前 Tag 库版本'}, 428)
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON'}, 400)
    return await run(lambda: save_tag(payload, expected))


@PromptServer.instance.routes.get('/prompt_selector/tags/identity')
async def tag_identity(request):
    q = request.query
    tag_uuid = q.get('tag_uuid') or None
    resource_id = q.get('resource_id') or None
    if (tag_uuid is None) == (resource_id is None):
        return response({'error': '必须且仅指定 tag_uuid 或 resource_id 其中一个身份'}, 400)

    def lookup():
        # This endpoint reads the audited candidate file only; neither source
        # database is loaded or mutated.
        return identity_bridge().lookup(tag_uuid=tag_uuid, resource_id=resource_id)

    return await run(lookup)


def _item_revision(request, payload=None):
    value = request.headers.get('If-Match')
    if value is None and isinstance(payload, dict):
        value = payload.get('base_revision') or payload.get('revision')
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[1:-1] if len(value) >= 2 and value.startswith('"') and value.endswith('"') else value


def _item_response(result):
    headers = {'Cache-Control': 'no-store'}
    if isinstance(result, dict) and result.get('revision') is not None:
        headers['ETag'] = '"' + str(result['revision']) + '"'
    return web.json_response(result, headers=headers)


@PromptServer.instance.routes.get('/prompt_selector/item')
async def item_metadata_get(request):
    resource_id = request.query.get('resource_id')
    if not isinstance(resource_id, str) or not resource_id.strip():
        return response({'error': '缺少 resource_id'}, 400)
    try:
        return _item_response(await asyncio.to_thread(item_maintenance.read_item, resource_id))
    except KeyError as error:
        return response({'error': str(error)}, 404)
    except (ValueError, TypeError) as error:
        return response({'error': str(error)}, 400)


# Scheduled from the end of the module: the worker calls library(), which only exists
# once every definition above has executed. Triggering it earlier lost the race and the
# warm-up silently never ran ("name 'library' is not defined" in the boot log).
try:
    if os.environ.get("UW_SKIP_LIBRARY_WARMUP") != "1":
        _warm_tag_catalog()
except Exception as error:  # noqa: BLE001
    logger.warning(f"[Workbench] Tag catalog warm-up could not be scheduled: {error}")


@PromptServer.instance.routes.post('/prompt_selector/items/batch')
async def item_metadata_batch(request):
    """One atomic, revision-bound metadata change set for many shared resources."""
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON'}, 400)
    if not isinstance(payload, dict):
        return response({'error': '批量维护需要对象'}, 400)
    revision = _item_revision(request, payload)
    if revision is None:
        return response({'error': '请先读取当前共享库版本'}, 428)
    payload = dict(payload)
    payload['base_revision'] = revision
    try:
        return _item_response(await asyncio.to_thread(item_batch.apply_batch, payload))
    except prompt_store.RevisionConflict as error:
        return response({'error': str(error), 'conflict': True,
                         'expected_revision': error.expected, 'current_revision': error.actual}, 409)
    except KeyError as error:
        return response({'error': str(error)}, 404)
    except (ValueError, TypeError) as error:
        return response({'error': str(error)}, 400)


@PromptServer.instance.routes.post('/prompt_selector/item')
async def item_metadata_post(request):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON'}, 400)
    if not isinstance(payload, dict):
        return response({'error': '维护操作必须是对象'}, 400)
    resource_id = payload.get('resource_id')
    if not isinstance(resource_id, str) or not resource_id.strip():
        return response({'error': '缺少 resource_id'}, 400)
    revision = _item_revision(request, payload)
    if revision is None:
        return response({'error': '请先读取当前资源版本'}, 428)
    payload = dict(payload)
    payload['base_revision'] = revision
    try:
        return _item_response(await asyncio.to_thread(item_maintenance.write_item, resource_id, payload))
    except (prompt_store.RevisionConflict, TagConflict) as error:
        body = {'error': str(error), 'conflict': True}
        if hasattr(error, 'expected'):
            body['expected_revision'] = error.expected
        if hasattr(error, 'actual'):
            body['current_revision'] = error.actual
        if hasattr(error, 'revision'):
            body['revision'] = error.revision
        return response(body, 409)
    except KeyError as error:
        return response({'error': str(error)}, 404)
    except (ValueError, TypeError) as error:
        return response({'error': str(error)}, 400)


@PromptServer.instance.routes.get('/prompt_selector/tags/links')
async def tag_links_get(request):
    """Applied links for one stable identity, plus the audited candidate matches."""
    tag_uuid = request.query.get('tag_uuid') or None
    resource_id = request.query.get('resource_id') or None
    if (tag_uuid is None) == (resource_id is None):
        return response({'error': '必须且仅指定 tag_uuid 或 resource_id 其中一个身份'}, 400)
    try:
        applied = await asyncio.to_thread(tag_links.lookup, tag_uuid=tag_uuid, resource_id=resource_id)
    except tag_links.LinkError as error:
        return response({'error': str(error)}, 400)
    try:
        candidates = identity_bridge().lookup(tag_uuid=tag_uuid, resource_id=resource_id)
    except Exception as error:  # candidate file is optional for the link view
        candidates = {'matches': [], 'count': 0, 'error': str(error)}
    return _item_response({**applied, 'candidates': candidates.get('matches') or [],
                           'candidate_count': candidates.get('count') or 0})


@PromptServer.instance.routes.post('/prompt_selector/tags/links')
async def tag_links_post(request):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return response({'error': '请求需要有效 JSON'}, 400)
    if not isinstance(payload, dict):
        return response({'error': '关联操作需要对象'}, 400)
    action = payload.get('action')
    expected = request.headers.get('If-Match')
    if expected is None:
        expected = payload.get('base_revision', payload.get('revision'))
    if expected is None:
        return response({'error': '请先读取当前链接关系版本'}, 428)
    try:
        if action == 'link':
            result = await asyncio.to_thread(
                tag_links.link, tag_uuid=payload.get('tag_uuid'), resource_id=payload.get('resource_id'),
                relation=payload.get('relation') or 'manual', source=payload.get('source') or 'manual',
                note=payload.get('note') or '', expected=expected)
        elif action == 'unlink':
            result = await asyncio.to_thread(
                tag_links.unlink, link_id=payload.get('link_id'), tag_uuid=payload.get('tag_uuid'),
                resource_id=payload.get('resource_id'), expected=expected)
        else:
            return response({'error': '未知的关联操作'}, 400)
        return _item_response(result)
    except tag_links.LinkConflict as error:
        return response({'error': str(error), 'conflict': True,
                         'expected_revision': error.expected, 'current_revision': error.actual}, 409)
    except tag_links.LinkError as error:
        return response({'error': str(error)}, 400)
    except KeyError as error:
        return response({'error': str(error)}, 404)
    except (ValueError, TypeError) as error:
        return response({'error': str(error)}, 400)
