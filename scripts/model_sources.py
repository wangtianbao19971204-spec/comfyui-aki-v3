"""Validate and render the offline model-source catalogue without reading weights.

Only ``render`` writes a file: the fixed docs/MODEL_SOURCES.md in the chosen
repository. No request, download, service, runtime, or model-file operation is
performed. Local hashes are catalogue assertions; declared upstream hashes are
kept separate and are never promoted to verified local hashes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
from urllib.parse import unquote, urlsplit
import uuid


REPO = Path(__file__).resolve().parents[1]
CATALOGUE = 'snapshot/inventory/model_sources.json'
INVENTORY = 'snapshot/inventory/models.json'
WORKFLOW = 'ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json'
WORKFLOW_SOURCE = 'snapshot/runtime/' + WORKFLOW
DOCUMENT = 'docs/MODEL_SOURCES.md'
STATUSES = ('version_metadata', 'upstream_mapping', 'local_derivative', 'unresolved')
TOP_KEYS = {'schema', 'captured_at', 'inventory_sha256', 'workflow_sha256',
            'notes', 'assets', 'missing_workflow_references', 'summary'}
ASSET_KEYS = {'path', 'bytes', 'kind', 'captured_in_inventory', 'observed_present',
              'local_sha256', 'source_status', 'family', 'sources', 'companions',
              'workflows', 'derivation', 'notes'}
SOURCE_KEYS = {'page_url', 'download_url', 'provider', 'model_id', 'version_id',
               'file_id', 'filename', 'declared_sha256', 'revision', 'evidence',
               'availability'}
SUMMARY_KEYS = {'asset_count', 'inventory_asset_count', 'observed_present_count',
                'observed_missing_count', 'workflow_asset_count',
                'missing_workflow_reference_count', 'source_status_counts'}
DERIVATION_KEYS = {'kind', 'parent_path', 'recipe_reference',
                   'original_weight_required', 'reproducibility'}
HASH = re.compile(r'[0-9a-fA-F]{64}')
DEVICE = re.compile(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', re.I)
LOCAL_SUFFIXES = {'localhost', 'local', 'internal', 'lan', 'home', 'test',
                  'invalid', 'onion'}
AUTH_SEGMENTS = {'token', 'tokens', 'session', 'sessions', 'auth', 'login',
                 'logout', 'oauth', 'callback', 'authorize', 'api-key'}
MAX_JSON_BYTES = 16 * 1024 * 1024


class CatalogueError(ValueError):
    """A fixed error code; never echo untrusted URLs or private metadata."""


def string(value, *, nullable=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise CatalogueError('invalid_string')
    return value


def relative_path(value):
    string(value)
    if (value.startswith(('/', '\\')) or '\\' in value or ':' in value or
            any(c in value for c in '<>"|?*')):
        raise CatalogueError('invalid_relative_path')
    parts = value.split('/')
    if any(not part or part in {'.', '..'} or part.rstrip(' .') != part or
           DEVICE.fullmatch(part) or part.casefold() == '.git' for part in parts):
        raise CatalogueError('invalid_relative_path')
    # Preserve legitimate captured Unicode filenames, including fullwidth
    # parentheses. Reject only normalization that disguises a path delimiter,
    # traversal component, reserved device, or Git directory.
    normalized = [unicodedata.normalize('NFKC', part) for part in parts]
    if any(part in {'.', '..'} or part.rstrip(' .') != part or
           any(c in part for c in '/\\:<>"|?*') or DEVICE.fullmatch(part) or
           part.casefold() == '.git' for part in normalized):
        raise CatalogueError('invalid_relative_path')
    return value


def path_list(value):
    if not isinstance(value, list):
        raise CatalogueError('invalid_path_list')
    result = [relative_path(item) for item in value]
    if len({item.casefold() for item in result}) != len(result):
        raise CatalogueError('duplicate_relative_path')
    return result


def notes(value):
    if not isinstance(value, list):
        raise CatalogueError('invalid_notes')
    for item in value:
        string(item)


def hash_value(value, *, nullable=False):
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise CatalogueError('invalid_sha256')
    return value.lower()


def public_url(value, *, download=False):
    string(value)
    if len(value) > 8192 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        raise CatalogueError('invalid_public_url')
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise CatalogueError('invalid_public_url') from None
    if (parsed.scheme != 'https' or not host or parsed.username is not None or
            parsed.password is not None or port is not None or parsed.fragment or
            '%' in parsed.netloc or host.endswith('.') or '.' not in host or
            not re.fullmatch(r'[A-Za-z0-9.-]+', host)):
        raise CatalogueError('invalid_public_url')
    host = host.casefold()
    if any(not label or label.startswith('-') or label.endswith('-') for label in host.split('.')):
        raise CatalogueError('invalid_public_url')
    if host.split('.')[-1] in LOCAL_SUFFIXES or host in {'localhost.localdomain', 'metadata.google.internal'}:
        raise CatalogueError('local_url_forbidden')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Numeric host aliases may still be interpreted as local IPv4 by clients.
        if re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*', host):
            raise CatalogueError('local_url_forbidden')
    else:
        raise CatalogueError('ip_literal_url_forbidden')
    decoded_path = unquote(parsed.path)
    if (re.search(r'[\s\\\x00-\x1f\x7f]', decoded_path) or parsed.path.startswith('//') or
            any(part in {'.', '..'} for part in decoded_path.split('/'))):
        raise CatalogueError('invalid_public_url')
    if any(part.casefold() in AUTH_SEGMENTS for part in decoded_path.split('/')):
        raise CatalogueError('authentication_url_forbidden')
    if parsed.query:
        version_page = (not download and host in {'civitai.com', 'www.civitai.com',
                                                  'civitai.red', 'www.civitai.red'} and
                        re.fullmatch(r'/models/[0-9]+(?:/[^/?#]+)?/?', parsed.path) and
                        re.fullmatch(r'modelVersionId=[0-9]+', parsed.query))
        if not version_page:
            raise CatalogueError('url_query_forbidden')
    # Empty query/fragment markers are aliases too, rather than canonical links.
    if ('?' in value and not parsed.query) or ('#' in value and not parsed.fragment):
        raise CatalogueError('invalid_public_url')
    return value


def identifier(value):
    if value is None:
        return
    if type(value) is int and value >= 0:
        return
    string(value)


def derivation(value):
    if value is None:
        return
    if (not isinstance(value, dict) or not DERIVATION_KEYS <= set(value) or
            set(value) - DERIVATION_KEYS - {'notes'} or
            value.get('kind') not in {'local_training', 'local_conversion'} or
            type(value.get('original_weight_required')) is not bool):
        raise CatalogueError('invalid_derivation')
    for field in ('parent_path', 'recipe_reference'):
        if value[field] is not None:
            relative_path(value[field])
    string(value['reproducibility'])
    if 'notes' in value:
        notes(value['notes'])


def no_links(path):
    path = Path(path).absolute()
    for candidate in [*reversed(path.parents), path]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CatalogueError('linked_or_reparse_path')
    if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
        raise CatalogueError('not_single_regular_file')
    return path


def unique_json(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise CatalogueError('duplicate_json_key')
        data[key] = value
    return data


def read_json(path):
    path = no_links(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise CatalogueError('json_size_limit')
    try:
        return json.loads(raw, object_pairs_hook=unique_json), hashlib.sha256(raw).hexdigest()
    except (UnicodeError, json.JSONDecodeError):
        raise CatalogueError('invalid_json') from None


def digest(path):
    path = no_links(path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def compute_summary(catalogue):
    assets = catalogue['assets']
    return {'asset_count': len(assets),
            'inventory_asset_count': sum(item['captured_in_inventory'] for item in assets),
            'observed_present_count': sum(item['observed_present'] for item in assets),
            'observed_missing_count': sum(not item['observed_present'] for item in assets),
            'workflow_asset_count': sum(WORKFLOW in item['workflows'] for item in assets),
            'missing_workflow_reference_count': len(catalogue['missing_workflow_references']),
            'source_status_counts': {status: sum(item['source_status'] == status for item in assets)
                                     for status in STATUSES}}


def validate_catalogue(catalogue, inventory, inventory_sha256, workflow_sha256):
    if (not isinstance(catalogue, dict) or set(catalogue) != TOP_KEYS or
            type(catalogue['schema']) is not int or catalogue['schema'] != 1):
        raise CatalogueError('invalid_catalogue_schema')
    string(catalogue['captured_at'])
    try:
        captured = datetime.fromisoformat(catalogue['captured_at'].replace('Z', '+00:00'))
        if captured.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise CatalogueError('invalid_capture_time') from None
    if hash_value(catalogue['inventory_sha256']) != hash_value(inventory_sha256):
        raise CatalogueError('inventory_sha256_mismatch')
    if hash_value(catalogue['workflow_sha256']) != hash_value(workflow_sha256):
        raise CatalogueError('workflow_sha256_mismatch')
    notes(catalogue['notes'])
    if not isinstance(inventory, dict) or not isinstance(inventory.get('files'), list):
        raise CatalogueError('invalid_inventory')
    original = {}
    for item in inventory['files']:
        if not isinstance(item, dict):
            raise CatalogueError('invalid_inventory_entry')
        key = relative_path(item.get('path')).casefold()
        if key in original or type(item.get('bytes')) is not int or item['bytes'] < 0:
            raise CatalogueError('duplicate_or_invalid_inventory_entry')
        original[key] = item
    assets = catalogue['assets']
    if not isinstance(assets, list) or len(assets) > 10000:
        raise CatalogueError('invalid_asset_collection')
    seen = set()
    captured_paths = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != ASSET_KEYS:
            raise CatalogueError('invalid_asset_schema')
        path = relative_path(asset['path']); key = path.casefold()
        if key in seen:
            raise CatalogueError('duplicate_asset_path')
        seen.add(key)
        if type(asset['bytes']) is not int or asset['bytes'] < 0:
            raise CatalogueError('invalid_asset_bytes')
        string(asset['kind']); string(asset['family'], nullable=True)
        if type(asset['captured_in_inventory']) is not bool or type(asset['observed_present']) is not bool:
            raise CatalogueError('invalid_presence_flag')
        if asset['captured_in_inventory'] != (key in original):
            raise CatalogueError('inventory_membership_mismatch')
        if key in original:
            if asset['path'] != original[key]['path'] or asset['bytes'] != original[key]['bytes']:
                raise CatalogueError('inventory_path_or_bytes_mismatch')
            captured_paths.add(key)
        hash_value(asset['local_sha256'], nullable=True)
        if asset['local_sha256'] is not None and not asset['observed_present']:
            raise CatalogueError('missing_asset_has_local_sha256')
        if asset['source_status'] not in STATUSES:
            raise CatalogueError('invalid_source_status')
        if not isinstance(asset['sources'], list):
            raise CatalogueError('invalid_source_collection')
        if (not asset['sources'] and asset['source_status'] not in {'unresolved', 'local_derivative'}):
            raise CatalogueError('resolved_asset_requires_source')
        if asset['source_status'] == 'local_derivative' and not asset['derivation']:
            raise CatalogueError('local_derivative_requires_derivation')
        derivation(asset['derivation'])
        for source in asset['sources']:
            if not isinstance(source, dict) or set(source) != SOURCE_KEYS:
                raise CatalogueError('invalid_source_schema')
            public_url(source['page_url'])
            if source['download_url'] is not None:
                public_url(source['download_url'], download=True)
            string(source['provider']); string(source['availability'])
            for field in ('model_id', 'version_id', 'file_id'):
                identifier(source[field])
            if source['filename'] is not None:
                relative_path(source['filename'])
            hash_value(source['declared_sha256'], nullable=True)
            string(source['revision'], nullable=True)
            if not isinstance(source['evidence'], list):
                raise CatalogueError('invalid_evidence_collection')
            for evidence in source['evidence']:
                if not isinstance(evidence, dict) or set(evidence) != {'kind', 'reference'}:
                    raise CatalogueError('invalid_evidence_schema')
                string(evidence['kind']); relative_path(evidence['reference'])
        path_list(asset['companions']); path_list(asset['workflows']); notes(asset['notes'])
    if captured_paths != set(original):
        raise CatalogueError('inventory_coverage_mismatch')
    missing = catalogue['missing_workflow_references']
    if not isinstance(missing, list):
        raise CatalogueError('invalid_missing_reference_collection')
    missing_seen = set()
    for item in missing:
        if not isinstance(item, dict) or set(item) != {'reference', 'workflows', 'notes'}:
            raise CatalogueError('invalid_missing_reference_schema')
        reference = string(item['reference'])
        if '://' in reference:
            public_url(reference, download=True)
        else:
            relative_path(reference.replace('\\', '/'))
        path_list(item['workflows']); notes(item['notes'])
        identity = (reference.casefold(), tuple(sorted(path.casefold() for path in item['workflows'])))
        if identity in missing_seen:
            raise CatalogueError('duplicate_missing_reference')
        missing_seen.add(identity)
    summary = compute_summary(catalogue)
    supplied = catalogue['summary']
    if (not isinstance(supplied, dict) or set(supplied) != SUMMARY_KEYS or
            any(type(supplied[k]) is not int for k in SUMMARY_KEYS - {'source_status_counts'}) or
            not isinstance(supplied['source_status_counts'], dict) or
            set(supplied['source_status_counts']) != set(STATUSES) or
            any(type(v) is not int for v in supplied['source_status_counts'].values()) or
            supplied != summary):
        raise CatalogueError('summary_mismatch')
    return summary


def checked_catalogue(repo=REPO):
    repo = Path(repo).absolute()
    catalogue, catalogue_sha256 = read_json(repo / CATALOGUE)
    inventory, inventory_sha256 = read_json(repo / INVENTORY)
    workflow_sha256 = digest(repo / WORKFLOW_SOURCE)
    summary = validate_catalogue(catalogue, inventory, inventory_sha256, workflow_sha256)
    return catalogue, summary, catalogue_sha256


def check_catalogue(repo=REPO):
    catalogue, summary, _ = checked_catalogue(repo)
    return catalogue, summary


def cell(value):
    """Escape catalogue prose as Markdown text, never interpret it as markup."""
    return (str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('\\', '&#92;').replace('|', '&#124;').replace('`', '&#96;')
            .replace('[', '&#91;').replace(']', '&#93;').replace('*', '&#42;')
            .replace('_', '&#95;').replace('\r', ' ').replace('\n', ' '))


def link(label, url):
    # Angle brackets protect valid upstream paths containing parentheses.
    target = url.replace('<', '%3C').replace('>', '%3E')
    return f'[{cell(label)}](<{target}>)'


def grouping(asset):
    if WORKFLOW in asset['workflows']:
        return '正式 v2 所需'
    if asset['kind'].casefold() == 'lora' or '/loras/' in asset['path'].casefold():
        return 'LoRA'
    if asset['kind'] in {'diffusion_model', 'text_encoder', 'vae', 'vision_encoder', 'llm'}:
        return '底模与配套'
    return '其他模型与插件权重'


def source_cell(asset):
    entries = []
    for source in asset['sources']:
        text = link(source['provider'] + ' 来源页', source['page_url'])
        if source['download_url']:
            text += ' · ' + link('父模型文件' if asset['source_status'] == 'local_derivative' else '文件链接', source['download_url'])
        ids = [f'{label}={cell(source[key])}' for key, label in
               [('model_id', 'model'), ('version_id', 'version'), ('file_id', 'file'), ('revision', 'revision')]
               if source[key] is not None]
        if source['filename'] is not None:
            ids.append('filename=' + cell(source['filename']))
        if ids:
            text += '<br>' + ', '.join(ids)
        text += '<br>可用性记录：' + cell(source['availability'])
        entries.append(text)
    return '<br><br>'.join(entries) if entries else '无已核实来源；见说明' if asset['source_status'] == 'unresolved' else '本地衍生；无最终文件公开来源'


def render_markdown(catalogue):
    summary = catalogue['summary']
    lines = ['# 模型来源与补齐指引', '',
             '这是离线来源目录，来源定位不等于下载验证、文件可用性保证或许可授权。工具不联网、不下载、不读取模型内容，也不修改运行区。', '',
             '正式 v2 只按当前工作流引用列出所需资产，不会自动启用分支、替换缺失资源或更改 LoRA/种子/参数。目录 JSON 保留完整网址、版本 ID、证据、摘要和备注。', '',
             '“本机 SHA-256”仅表示采集者记录的实际文件内容摘要；空值表示未作本机内容核验。“上游声明 SHA-256”来自来源元数据，二者独立，不能相互代替。本地衍生文件的父模型链接不能用作最终文件直接下载。', '',
             f'采集时间：{cell(catalogue["captured_at"])}。资产 {summary["asset_count"]} 项，其中原捕获清单 {summary["inventory_asset_count"]} 项；本机观察存在 {summary["observed_present_count"]} 项、已不存在 {summary["observed_missing_count"]} 项；正式 v2 引用 {summary["workflow_asset_count"]} 项。', '',
             '[完整机器目录](../snapshot/inventory/model_sources.json) · [原模型清单](../snapshot/inventory/models.json) · [模型与兼容说明](MODELS.md)', '',
             f'原清单 SHA-256：`{catalogue["inventory_sha256"]}`。', '',
             f'正式 v2 SHA-256：`{catalogue["workflow_sha256"]}`。', '']
    lines.extend('- ' + cell(note) for note in catalogue['notes'])
    if catalogue['notes']:
        lines.append('')
    labels = {'version_metadata': '版本元数据定位', 'upstream_mapping': '上游实现对应',
              'local_derivative': '本地衍生', 'unresolved': '来源待核实'}
    kinds = {'diffusion_model': '生成底模', 'lora': 'LoRA', 'text_encoder': '文本编码器',
             'vae': 'VAE', 'detector': '检测器', 'segmentation': '分割模型',
             'upscale': '超分模型', 'vision_encoder': '视觉编码器', 'llm': '语言模型',
             'plugin_weight': '插件权重', 'tagger': '标签模型', 'other': '其他'}
    for group in ('正式 v2 所需', '底模与配套', 'LoRA', '其他模型与插件权重'):
        assets = [item for item in catalogue['assets'] if grouping(item) == group]
        lines.extend([f'## {group}（{len(assets)} 项）', '',
                      '| 放置路径（相对运行根） | 字节 / 本机状态 | 类型 / 家族 | 来源状态与版本 | 摘要 | 配套与维护说明 |',
                      '|---|---|---|---|---|---|'])
        for asset in sorted(assets, key=lambda item: item['path'].casefold()):
            hashes = ['本机：' + (cell(asset['local_sha256']) if asset['local_sha256'] else '未核验')]
            hashes.extend('上游声明：' + cell(source['declared_sha256']) for source in asset['sources'] if source['declared_sha256'])
            hints = []
            if asset['companions']:
                hints.append('配套：' + '；'.join(cell(p) for p in asset['companions']))
            if asset['family']:
                hints.append('按家族与对应编码器/VAE核对兼容性；同家族不保证LoRA效果。')
            if asset['derivation']:
                recipe = asset['derivation']
                hints.append('衍生方式：' + ('本地训练' if recipe['kind'] == 'local_training' else '本地转换'))
                hints.append('父权重：' + cell(recipe['parent_path'] or '未登记'))
                hints.append('配方说明：' + cell(recipe['recipe_reference'] or '未登记'))
                if recipe['original_weight_required']:
                    hints.append('须另行保留权重原件；来源链接不能恢复最终文件。')
                hints.append('重建条件：' + ('依赖权重备份' if recipe['reproducibility'] == 'weights_backup_required' else cell(recipe['reproducibility'])))
                hints.extend(cell(note) for note in recipe.get('notes', []))
            hints.extend(cell(note) for note in asset['notes'])
            if asset['workflows']:
                hints.append('工作流：' + '；'.join(cell(p) for p in asset['workflows']))
            lines.append('| ' + ' | '.join([
                cell(asset['path']), f'{asset["bytes"]:,}<br>' + ('观察存在' if asset['observed_present'] else '已不存在；保留捕获记录'),
                cell(kinds.get(asset['kind'], asset['kind'])) + '<br>' + cell(asset['family'] or '家族未确认'),
                labels[asset['source_status']] + '<br>' + source_cell(asset),
                '<br>'.join(hashes), '<br>'.join(hints) or '见机器目录']) + ' |')
        lines.append('')
    lines.extend(['## 缺失工作流引用', '',
                  '下表独立保留未匹配到现有资产的引用；链接或名称只是原引用，不提供自动替代关系。先核对原工作流和模型家族，再人工处理。', '',
                  '| 原引用 | 工作流 | 核对说明 |', '|---|---|---|'])
    for item in catalogue['missing_workflow_references']:
        reference = item['reference']
        displayed = link(reference, reference) if '://' in reference else cell(reference)
        lines.append('| ' + ' | '.join([displayed, '<br>'.join(cell(p) for p in item['workflows']),
                                        '<br>'.join(cell(n) for n in item['notes']) or '尚未匹配；不自动替换']) + ' |')
    if not catalogue['missing_workflow_references']:
        lines.append('| 无 | — | 当前目录没有登记缺失引用；不表示所有资产已通过加载或推理验收。 |')
    lines.extend(['', '更新时先核对原清单和正式 v2 的字节摘要，保留已不存在的捕获条目。修改清单后先运行 `scripts/model_sources.py render`，再运行 `scripts/model_sources.py check` 核对易读表与清单同步；清单来源变更需要重新审查，渲染不改变模型或工作流。', ''])
    return '\n'.join(lines)


def check_document(repo, catalogue):
    target = no_links(Path(repo).absolute() / DOCUMENT)
    if not target.exists():
        raise CatalogueError('rendered_document_missing')
    expected = render_markdown(catalogue).encode('utf8')
    with target.open('rb') as stream:
        observed = stream.read(MAX_JSON_BYTES + 1)
    if observed != expected:
        raise CatalogueError('rendered_document_mismatch')
    return hashlib.sha256(observed).hexdigest()


def render_receipt(repo=REPO):
    repo = Path(repo).absolute()
    catalogue, summary, catalogue_sha256 = checked_catalogue(repo)
    target = no_links(repo / DOCUMENT)
    if not target.parent.is_dir():
        raise CatalogueError('document_directory_missing')
    temporary = target.with_name('.MODEL_SOURCES.md.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(render_markdown(catalogue))
        no_links(target)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return summary, catalogue_sha256, check_document(repo, catalogue)


def render(repo=REPO):
    summary, _, _ = render_receipt(repo)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'render'])
    parser.add_argument('--repo', type=Path, default=REPO)
    args = parser.parse_args(argv)
    try:
        if args.command == 'render':
            summary, catalogue_sha256, document_sha256 = render_receipt(args.repo)
        else:
            catalogue, summary, catalogue_sha256 = checked_catalogue(args.repo)
            document_sha256 = check_document(args.repo, catalogue)
        print(json.dumps({'pass': True, 'command': args.command, 'summary': summary,
                          'catalogue_sha256': catalogue_sha256,
                          'document': DOCUMENT, 'document_sha256': document_sha256}, ensure_ascii=False))
        return 0
    except CatalogueError as error:
        print(json.dumps({'pass': False, 'error': str(error)}))
    except OSError:
        print(json.dumps({'pass': False, 'error': 'filesystem_error'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())
