"""Read local backup evidence, never create/restore a backup or inspect live data.

The index is selected explicitly or by repo-local Git configuration. Hashing
receipt metadata is not rehashing the payload or rechecking physical disks.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

MAX_FILE = 4 * 1024 * 1024
MAX_METADATA = 16 * 1024 * 1024
EXCLUSIONS = {
    'Large model weights': '大型模型权重',
    'Original previews and generated images': '预览原图与输出图',
    'Training image datasets': '训练图片/训练集',
    'Full Python/CUDA environment': '完整 Python/CUDA 环境',
    'Complete legacy private Git archives': '全部旧私有 Git 档案',
}


def require(condition):
    if not condition:
        raise ValueError('Invalid backup evidence')


def plain_path(value):
    require(isinstance(value, str) and not value.startswith(('\\\\', '//')))
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts)
    require(not any(':' in part for part in path.parts[1:]))
    return path


def unlinked(path):
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400)
    return path.stat()


def relative_path(root, value):
    require(isinstance(value, str) and value and not any(c in value for c in ('\\', ':', '\x00')))
    pure = PurePosixPath(value)
    require(not pure.is_absolute() and pure.as_posix() == value and '..' not in pure.parts)
    return root.joinpath(*pure.parts)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode(raw):
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(value, dict))
    return value


def sha(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value))
    return value


def count(value):
    require(type(value) is int and 0 <= value <= 10**15)
    return value


def timestamp(value):
    require(isinstance(value, str))
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None)
    return parsed.isoformat()


class EvidenceReader:
    def __init__(self, repo):
        self.repo = repo.resolve()
        self.reads = {}
        self.total = 0

    def read(self, path, expected=None):
        require(not path.is_relative_to(self.repo))
        before = unlinked(path)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_FILE)
        if path in self.reads:
            raw = self.reads[path]
        else:
            with path.open('rb') as stream:
                raw = stream.read(MAX_FILE + 1)
            after = path.stat()
            require((before.st_ino, before.st_size, before.st_mtime_ns) ==
                    (after.st_ino, after.st_size, after.st_mtime_ns))
            self.total += len(raw)
            require(len(raw) <= MAX_FILE and self.total <= MAX_METADATA)
            self.reads[path] = raw
        if expected is not None:
            require(hashlib.sha256(raw).hexdigest() == sha(expected))
        return raw

    def stable(self):
        # Detect metadata replacement during the query without reading payloads.
        for path, raw in self.reads.items():
            info = unlinked(path)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == len(raw))
            with path.open('rb') as stream:
                require(stream.read(MAX_FILE + 1) == raw)


def payload_metadata(root, files, repo):
    require(isinstance(files, list) and 0 < len(files) <= 50000)
    seen = set()
    total = 0
    for row in files:
        path = relative_path(root, row['target'])
        key = str(path).casefold()
        require(key not in seen and not path.is_relative_to(repo))
        seen.add(key)
        info = unlinked(path)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == count(row['bytes']))
        sha(row['sha256'])
        total += info.st_size
    return total


def inspect(repo, index_path, head, clean):
    """Fail closed in the backup section; no external exception text is returned."""
    result = {
        'mode': 'rules-only', 'automatic_actions': False,
        'destination_configured_by_this_policy': False,
        'status': 'not_configured', 'recorded_acceptance': False,
        'receipt_chain_verified': False, 'payload_sha256_rechecked': False,
        'physical_disks_rechecked': False, 'live_data_freshness_checked': False,
        'current_checkout_covered': False,
    }
    if index_path is None:
        return result
    try:
        repo = Path(repo).resolve()
        reader = EvidenceReader(repo)
        index = decode(reader.read(plain_path(str(index_path))))
        require(index['schema'] == 1 and index['status'] == 'ACCEPTED_CRITICAL_SCOPE_BACKUP')
        require(plain_path(index['main_git']) == repo)
        root = plain_path(index['backup_root'])
        receipt_path = plain_path(index['final_receipt'])
        require(receipt_path.is_relative_to(root) and receipt_path != root)
        final = decode(reader.read(receipt_path, index['final_receipt_sha256']))
        require(final['schema'] == 1 and final['pass'] is True and
                final['status'] == 'PASS_FOR_USER_APPROVED_CRITICAL_BACKUP_SCOPE')
        require(final['batch_id'] == index['batch_id'] and plain_path(final['backup_root']) == root)
        require(plain_path(final['only_development_authority']) == repo)
        rows = final['evidence']
        require(isinstance(rows, list) and 0 < len(rows) <= 64)
        evidence = {}
        for row in rows:
            relative = row['path']
            require(relative.casefold() not in {key.casefold() for key in evidence})
            raw = reader.read(relative_path(root, relative), row['sha256'])
            require(len(raw) == count(row['bytes']))
            evidence[relative] = raw

        def bound(name):
            return decode(evidence[name])

        source = final['source']
        commit = source['commit']
        require(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit))
        version = source['version']
        require(isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version))
        state_info = final['accepted_current_state']
        state = bound(state_info['receipt'])
        require(state['pass'] is True and state['source_commit'] == commit)
        require(state['plan_sha256'] == hashlib.sha256(evidence[state_info['plan']]).hexdigest())
        require(state['directory'] == state_info['directory'])
        data_root = relative_path(root, state['directory'])
        total = payload_metadata(data_root, state['files'], repo)
        require(len(state['files']) == count(state['count']) == count(state_info['payload_files']))
        require(total == count(state['bytes']) == count(state_info['payload_bytes']))
        databases = [row for row in state['files'] if row['kind'] == 'sqlite']
        require(len(databases) == count(state_info['sqlite_databases']))
        for row in databases:
            require(row['database']['integrity_check'] == 'ok')
            sha(row['database']['logical_sql_sha256'])
        require(bound('SOURCE_CLONE_ACCEPTANCE.json')['pass'] is True)
        require(bound('SOURCE_CLONE_ACCEPTANCE.json')['commit'] == commit)
        require(bound(final['validation']['final_independent_recheck'])['pass'] is True)
        require(bound(final['privacy']['ACL_receipt'])['pass'] is True)
        require(bound(final['production_preservation']['reviewed_guard']['receipt'])['pass'] is True)
        # The raw/failed candidate reports in evidence are intentionally not PASS.
        source_copy = bound('SOURCE_COPY_RECEIPT.json')
        require(source_copy['pass'] is True and source_copy['source_commit'] == commit)
        bundle = next(row for row in source_copy['files'] if row['target'] == source['bundle'])
        require(bundle['sha256'] == sha(source['bundle_sha256']) and bundle['bytes'] == source['bundle_bytes'])
        payload_metadata(root, source_copy['files'], repo)

        cross = final['cross_physical_disk']
        require(cross['main_and_g_sources_backed_up_to_D'] is True)
        disks = cross['drive_to_disk_number']
        require(type(disks['G']) is int and type(disks['D']) is int and disks['G'] != disks['D'])
        companion_info = cross['c_drive_companion']
        companion = bound(companion_info['receipt'])
        require(companion['pass'] is True and companion['original_source_disk'] != companion['companion_disk'])
        require(companion['parent_backup_receipt_sha256'] == hashlib.sha256(evidence[state_info['receipt']]).hexdigest())
        companion_root = plain_path(companion_info['root'])
        require(companion_root == plain_path(companion['companion']))
        reader.read(companion_root / 'COMPANION_RECEIPT.json', companion_info['companion_receipt_sha256'])
        require(payload_metadata(companion_root, companion['files'], repo) == count(companion['bytes']))
        require(len(companion['files']) == count(companion_info['files']) == count(companion['count']))
        excluded = final['excluded']
        require(isinstance(excluded, list) and excluded and all(item in EXCLUSIONS for item in excluded))
        captured = timestamp(state['checked_at'])
        accepted = timestamp(final['created_at'])
        reader.stable()
        result.update({
            'status': 'accepted_receipt', 'recorded_acceptance': True,
            'receipt_chain_verified': True, 'payload_paths_and_sizes_checked': True,
            'receipt_sha256': index['final_receipt_sha256'], 'metadata_files_checked': len(reader.reads),
            'captured_at': captured, 'accepted_at': accepted,
            'source_commit': commit, 'source_version': version,
            'head_matches_backup': head == commit, 'working_tree_changes_included': False,
            'current_checkout_covered': head == commit and clean,
            'payload_files': state['count'], 'sqlite_databases': len(databases),
            'payload_bytes': total, 'excluded': excluded,
        })
    except FileNotFoundError:
        result.update(status='unavailable', reason='backup_index_or_evidence_or_payload_unavailable')
    except Exception:
        result.update(status='invalid', reason='backup_evidence_validation_failed')
    return result


def lines(report):
    state = report['status']
    if state == 'not_configured':
        return ['备份状态：未登记本机回执索引，无法判定；规则不等于备份。']
    if state != 'accepted_receipt':
        return ['备份状态：回执或副本' + ('不可访问' if state == 'unavailable' else '核验失败') + '，不能确认备份有效；不会自动删除。']
    coverage = '覆盖当前干净提交' if report['current_checkout_covered'] else '不覆盖当前完整工作树，需另行备份新增修改'
    local_time = datetime.fromisoformat(report['captured_at']).astimezone().isoformat(timespec='seconds')
    return [
        '备份状态：已有异盘备份验收记录；本次回执链、文件存在和大小核验通过。',
        '备份时间（本机时区）：' + local_time + '；源码 v' + report['source_version'] + ' / ' + report['source_commit'][:12],
        '备份覆盖：' + coverage + '；资料为备份时点，不保证包含后续运行数据。',
        '备份范围：主仓、当期资料库与私密配置；资料 ' + str(report['payload_files']) + ' 文件 / ' + str(report['sqlite_databases']) + ' 个数据库。',
        '未包含：' + '、'.join(EXCLUSIONS[item] for item in report['excluded']) + '。',
        '核验边界：未重算有效载荷哈希、未重新核验物理磁盘/权限、未做启动验收；不自动备份或清理。',
    ]
