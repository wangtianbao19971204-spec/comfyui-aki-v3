"""Export every locally stored commit to a fresh, self-contained public mirror.

Source worktrees, indexes, refs and configuration are read-only. No network is
used. Credential findings fail closed: this module does not guess redactions.
Blocked payloads are omitted, never renamed to evade the publication gate.
Their paths, object IDs, sizes and SHA-256 become plain-text reference metadata.
"""
from __future__ import annotations

import argparse
import collections
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import subprocess

import history_migration as hm
import security_guard as sg

REFERENCE_FILE = b'.comfyui-history-references.json'
VERIFIER_CONTRACT = 2
SIGNATURE_HEADERS = {b'gpgsig', b'gpgsig-sha256', b'mergetag'}
EXTERNAL_RULES = {
    'external_runtime_asset_payload', 'external_library_preview_payload',
    'unsupported_archive_suffix', 'private_runtime_directory',
    'model_weight_payload', 'database_binary_or_journal',
    'private_credential_file', 'known_private_plugin_config_or_cache',
    'oversize_git_blob', 'unsupported_archive_requires_review',
    'invalid_gzip_payload', 'invalid_zip_payload', 'empty_archive_payload',
    'truncated_gzip_payload', 'nested_archive_requires_review',
    'compressed_expansion_limit', 'archive_expansion_limit',
    'zip_nested_archive_requires_review', 'zip_truncated_gzip_payload',
    'invalid_or_unsupported_zip_payload',
}


def git(repo, *args, data=None, check=True):
    result = subprocess.run(
        ['git', '-c', f'safe.directory={Path(repo).resolve().as_posix()}',
         '-c', 'core.fsmonitor=false', '-c', f'core.hooksPath={os.devnull}', '-C', str(repo), *args],
        input=data, capture_output=True, env=git_environment(repo))
    if check and result.returncode:
        raise RuntimeError(f'Git {args[0]} failed ({result.returncode}); output withheld')
    return result


def git_environment(repo):
    """Ignore inherited Git redirection/config; never modify persistent config."""
    clean = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    clean.update({'GIT_OPTIONAL_LOCKS': '0', 'GIT_NO_REPLACE_OBJECTS': '1',
                  'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                  'GIT_CONFIG_COUNT': '3',
                  'GIT_CONFIG_KEY_0': 'safe.directory',
                  'GIT_CONFIG_VALUE_0': Path(repo).resolve().as_posix(),
                  'GIT_CONFIG_KEY_1': 'core.fsmonitor', 'GIT_CONFIG_VALUE_1': 'false',
                  'GIT_CONFIG_KEY_2': 'core.hooksPath', 'GIT_CONFIG_VALUE_2': os.devnull})
    return clean


def lines(repo, *args, data=None):
    return git(repo, *args, data=data).stdout.decode('utf-8', 'surrogateescape').splitlines()


@contextmanager
def scoped_git_environment(repo):
    """Only this process and its children trust this one source checkout."""
    previous = {key: value for key, value in os.environ.items() if key.upper().startswith('GIT_')}
    additions = {key: value for key, value in git_environment(repo).items() if key.upper().startswith('GIT_')}
    try:
        for key in previous:
            del os.environ[key]
        os.environ.update(additions)
        yield
    finally:
        for key in list(os.environ):
            if key.upper().startswith('GIT_'):
                del os.environ[key]
        os.environ.update(previous)


def aggregate_history(public_git, report, receipt_path):
    previous = hm.ENV
    try:
        hm.ENV = git_environment(public_git)
        return hm.aggregate_history(public_git, report, receipt_path)
    finally:
        hm.ENV = previous


class Reader:
    def __init__(self, repo):
        self.proc = subprocess.Popen(
            ['git', '-c', f'safe.directory={Path(repo).resolve().as_posix()}',
             '-c', 'core.fsmonitor=false', '-c', f'core.hooksPath={os.devnull}', '-C', str(repo), 'cat-file', '--batch'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=git_environment(repo))

    def read(self, oid):
        self.proc.stdin.write(oid.encode('ascii') + b'\n')
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3 or header[0].decode('ascii') != oid:
            raise RuntimeError('Missing or malformed Git object')
        payload = self.proc.stdout.read(int(header[2]))
        if len(payload) != int(header[2]) or self.proc.stdout.read(1) != b'\n':
            raise RuntimeError('Truncated Git object')
        return header[1].decode('ascii'), payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.proc.wait()


def metadata(repo):
    return {parts[0]: {'type': parts[1], 'size': int(parts[2])}
            for parts in (line.split() for line in lines(
                repo, 'cat-file', '--batch-all-objects',
                '--batch-check=%(objectname) %(objecttype) %(objectsize)'))}


def refs(repo):
    result = []
    for line in lines(repo, 'for-each-ref', '--format=%(refname)%09%(objectname)%09%(objecttype)%09%(*objectname)%09%(symref)'):
        name, oid, kind, peeled, symbolic = line.split('\t')
        result.append({'ref': name, 'oid': oid, 'type': kind,
                       'peeled': peeled or None, 'symbolic': symbolic or None})
    return result


def entries(payload):
    return [(prefix.split(b' ', 1)[1][:-1], oid, mode)
            for prefix, oid, mode in hm.tree_entries(payload)]


def encode_tree(items):
    ordered = sorted(items, key=lambda item: item[0] + (b'/' if item[2] == b'40000' else b''))
    if len({name for name, _, _ in ordered}) != len(ordered):
        raise ValueError('Duplicate tree entry')
    return b''.join(mode + b' ' + name + b'\0' + bytes.fromhex(oid)
                    for name, oid, mode in ordered)


def commit_parts(payload):
    head, message = payload.split(b'\n\n', 1)
    records = hm.header_records(head)
    tree = next(record[5:].decode('ascii') for record in records if record.startswith(b'tree '))
    parents = [record[7:].decode('ascii') for record in records if record.startswith(b'parent ')]
    return records, message, tree, parents


def ordered_commits(raw, shallow, allow_shallow):
    parents = {oid: commit_parts(payload)[3] for oid, payload in raw.items()}
    missing = []
    children = collections.defaultdict(list)
    indegree = {}
    for oid, items in parents.items():
        indegree[oid] = sum(parent in raw for parent in items)
        for position, parent in enumerate(items):
            if parent not in raw:
                if not allow_shallow or oid not in shallow:
                    raise ValueError('Missing parent is not an approved shallow boundary')
                missing.append({'commit': oid, 'missing_parent': parent, 'parent_position': position})
            else:
                children[parent].append(oid)
    pending = [oid for oid, count in indegree.items() if count == 0]
    heapq.heapify(pending)
    ordered = []
    while pending:
        oid = heapq.heappop(pending)
        ordered.append(oid)
        for child in children[oid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(pending, child)
    if len(ordered) != len(raw):
        raise ValueError('Commit graph is cyclic or incomplete')
    return ordered, parents, missing


def reference_payload(records):
    value = {'schema': 1, 'purpose': 'Public history reference; not a runnable restored revision',
             'original_payloads': 'Retained only in the separate private original Git archive',
             'entries': sorted(records, key=lambda item: (item['path'], item['object']))}
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _scan_partition(task):
    repo, selected = task
    with scoped_git_environment(repo):
        return sg.scan_objects(repo, selected)


def scan_selected(repo, selected, workers=1):
    """Parallelize independent objects, retaining serial cross-part validation.

    Each object keeps every historical path alias. Chunk manifests/part files
    use the original unsplit scanner so no inter-file credential edge is lost.
    """
    needs_edges = any(path.endswith('.part') or path == 'snapshot/manifest.json'
                      for item in selected for path in item['paths'])
    workers = min(max(1, workers), 8)
    if workers == 1 or needs_edges or len(selected) < workers:
        return _scan_partition((repo, selected))
    groups = [[] for _ in range(workers)]
    sizes = [0] * workers
    for item in sorted(selected, key=lambda item: item['bytes'], reverse=True):
        number = min(range(workers), key=sizes.__getitem__)
        groups[number].append(item)
        sizes[number] += item['bytes']
    result = {'findings': [], 'reviewed_fixtures': [], 'compressed_objects': [],
              'sensitive_named_objects': [], 'scanned_bytes': 0, 'cross_part_boundaries': 0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(_scan_partition, [(str(repo), group) for group in groups]):
            for key in result:
                if isinstance(result[key], list):
                    result[key].extend(part[key])
                else:
                    result[key] += part[key]
    result['findings'].sort(key=lambda item: (item['path'], item['object'], item['rule']))
    return result


def audit_public(repo, workers=1):
    with scoped_git_environment(repo):
        before = sg.refs(repo)
        selected, gitlinks = sg.inventory(repo, False)
    result = scan_selected(repo, selected, workers)
    result['findings'].extend(gitlinks)
    with scoped_git_environment(repo):
        if before != sg.refs(repo):
            result['findings'].append({'path': '<git refs>', 'object': '', 'rule': 'refs_changed_during_scan'})
    result.update({'schema': 1, 'mode': 'all-history', 'pass': not result['findings'],
                   'scanned_objects': len(selected), 'scanned_blobs': sum(item['type'] == 'blob' for item in selected),
                   'refs': before, 'offline': True, 'content_only': False,
                   'requested_parallel_workers': workers,
                   'limits': ['Heuristic credential detection is not proof of absence.',
                              'Unreachable objects are outside --all-history; original private Git must not be published.']})
    return result


class SourceGraph:
    def __init__(self, repo):
        self.repo = Path(repo).resolve()
        self.metadata = metadata(repo)
        self.refs = refs(repo)
        self.raw_commits = {}
        self.raw_trees = {}
        self.raw_tags = {}
        with Reader(repo) as reader:
            for oid, item in self.metadata.items():
                if item['type'] not in {'commit', 'tree', 'tag'}:
                    continue
                kind, data = reader.read(oid)
                {'commit': self.raw_commits, 'tree': self.raw_trees, 'tag': self.raw_tags}[kind][oid] = data
        self.shallow = set()
        shallow_file = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'shallow').stdout.decode().strip())
        if shallow_file.exists():
            self.shallow = set(shallow_file.read_text(encoding='ascii').splitlines())
        self.paths = collections.defaultdict(set)
        self.root_trees = {commit_parts(value)[2] for value in self.raw_commits.values()}
        visited = set()

        def tree(oid, prefix=''):
            if (oid, prefix) in visited:
                return
            visited.add((oid, prefix))
            for name, child, mode in entries(self.raw_trees[oid]):
                path = prefix + name.decode('utf-8', 'surrogateescape')
                if mode == b'40000':
                    tree(child, path + '/')
                elif mode != b'160000':
                    self.paths[child].add(path)

        def extra(oid):
            kind = self.metadata[oid]['type']
            if kind == 'tag':
                target = self.raw_tags[oid].split(b'\n', 1)[0][7:].decode('ascii')
                extra(target)
            elif kind == 'tree':
                self.root_trees.add(oid)
            elif kind == 'blob':
                self.paths[oid].add('<direct-object-ref>')

        for oid in self.raw_tags:
            extra(oid)
        for item in self.refs:
            extra(item['oid'])
        for oid in self.root_trees:
            tree(oid)

    def scan(self, workers=1):
        selected = [{'object': oid, 'type': 'blob', 'bytes': self.metadata[oid]['size'], 'paths': sorted(paths)}
                    for oid, paths in self.paths.items()]
        selected.extend({'object': oid, 'type': kind, 'bytes': len(data), 'paths': ['<metadata>']}
                        for kind, raw in [('commit', self.raw_commits), ('tag', self.raw_tags)]
                        for oid, data in raw.items())
        result = scan_selected(self.repo, selected, workers)
        result.update({'schema': 1, 'mode': 'all-stored-commit-graphs',
                       'pass': not result['findings'], 'scanned_objects': len(selected),
                       'scanned_blobs': len(self.paths), 'offline': True, 'content_only': False})
        return result


def build(source, destination, report_path, scan_path, *, allow_shallow=False, externalization_plan=None, scan_workers=1):
    source = Path(source).resolve()
    destination = hm.validate_new_path(destination)
    report_path = hm.validate_new_path(report_path)
    scan_path = hm.validate_new_path(scan_path)
    if destination.is_relative_to(source):
        raise ValueError('Mirror must be outside the source repository')
    if git(source, 'rev-parse', '--show-object-format').stdout.strip() != b'sha1':
        raise ValueError('Only SHA-1 repositories are supported')
    graph = SourceGraph(source)
    order, parents, missing = ordered_commits(graph.raw_commits, graph.shallow, allow_shallow)
    scan = graph.scan(scan_workers)
    hm.save_new(scan_path, scan)
    reviewed = (externalization_plan or {}).get('objects', {})
    finding_rules = collections.defaultdict(set)
    for item in scan['findings']:
        finding_rules[item['object']].add(item['rule'])
    for oid, specification in reviewed.items():
        if oid not in graph.paths or graph.metadata[oid]['type'] != 'blob':
            raise ValueError('Reviewed externalization is not a historical blob')
        if specification['reason'] not in {'credential_bearing_history_payload', 'unreviewed_credential_shaped_history_payload'}:
            raise ValueError('Unknown reviewed externalization reason')
        if set(specification['paths']) != graph.paths[oid] or set(specification['finding_rules']) != finding_rules[oid]:
            raise ValueError('Reviewed externalization paths or rules changed')
        if not re.fullmatch('[0-9a-f]{64}', specification['sha256']):
            raise ValueError('Invalid reviewed payload SHA-256')
    external = collections.defaultdict(set)
    for item in scan['findings']:
        if graph.metadata[item['object']]['type'] != 'blob':
            raise ValueError('Credential or unsupported security finding requires exact independent review')
        if item['rule'] not in EXTERNAL_RULES and item['object'] not in reviewed:
            raise ValueError('Credential or unsupported security finding requires exact independent review')
        external[item['object']].add(item['rule'])
    for oid, specification in reviewed.items():
        external[oid].add(specification['reason'])
    destination.mkdir(parents=True)
    git(destination, 'init', '--bare', '--template=')
    blob_records = {}
    object_map = {}
    with Reader(source) as reader:
        for oid in sorted(graph.paths):
            _, payload = reader.read(oid)
            if oid in external:
                digest = hashlib.sha256(payload).hexdigest()
                if oid in reviewed and digest != reviewed[oid]['sha256']:
                    raise ValueError('Reviewed externalization payload changed')
                blob_records[oid] = {'object': oid, 'bytes': len(payload),
                                     'sha256': digest,
                                     'reasons': sorted(external[oid])}
            else:
                object_map[oid] = hm.put_object(destination, 'blob', payload)
                if object_map[oid] != oid:
                    raise RuntimeError('Unchanged blob ID mismatch')
    tree_cache = {}

    def rewrite_tree(oid):
        if oid in tree_cache:
            return tree_cache[oid]
        result = []
        references = []
        for name, child, mode in entries(graph.raw_trees[oid]):
            path = name.decode('utf-8', 'surrogateescape')
            if mode == b'40000':
                new_child, child_refs = rewrite_tree(child)
                result.append((name, new_child, mode))
                references.extend(dict(item, path=path + '/' + item['path']) for item in child_refs)
            elif mode == b'160000':
                references.append({'path': path, 'object': child, 'git_mode': '160000',
                                   'reasons': ['nested_gitlink'],
                                   'restore': 'Obtain the dependency at this original commit separately; no dependency files are invented.'})
            elif child in external:
                references.append(dict(blob_records[child], path=path, git_mode=mode.decode('ascii')))
            else:
                result.append((name, object_map[child], mode))
        new_oid = hm.put_object(destination, 'tree', encode_tree(result))
        tree_cache[oid] = (new_oid, references)
        return new_oid, references

    root_map = {}
    reference_roots = {}
    for oid in sorted(graph.root_trees):
        public_tree, records = rewrite_tree(oid)
        if records:
            if any(name == REFERENCE_FILE for name, _, _ in entries(graph.raw_trees[oid])):
                raise ValueError('Reserved historical reference metadata path already exists')
            reference_blob = hm.put_object(destination, 'blob', reference_payload(records))
            payload = git(destination, 'cat-file', 'tree', public_tree).stdout
            public_tree = hm.put_object(destination, 'tree', encode_tree(entries(payload) + [(REFERENCE_FILE, reference_blob, b'100644')]))
            reference_roots[oid] = {'public_tree': public_tree, 'reference_blob': reference_blob,
                                    'externalized_entries': records}
        root_map[oid] = public_tree
    object_map.update(root_map)
    commit_map = {}
    signatures = []
    for oid in order:
        old_records, message, old_tree, old_parents = commit_parts(graph.raw_commits[oid])
        rewritten = []
        for record in old_records:
            if record.startswith(b'tree '):
                rewritten.append(b'tree ' + root_map[old_tree].encode('ascii'))
            elif record.startswith(b'parent '):
                parent = record[7:].decode('ascii')
                if parent in commit_map:
                    rewritten.append(b'parent ' + commit_map[parent].encode('ascii'))
            else:
                rewritten.append(record)
        if rewritten != old_records:
            removed = [record.split(b' ', 1)[0].decode() for record in rewritten
                       if record.split(b' ', 1)[0] in SIGNATURE_HEADERS]
            rewritten = [record for record in rewritten if record.split(b' ', 1)[0] not in SIGNATURE_HEADERS]
            if removed:
                signatures.append({'old_commit': oid, 'removed_headers': removed})
        commit_map[oid] = hm.put_object(destination, 'commit', b'\n'.join(rewritten) + b'\n\n' + message)
    if len(set(commit_map.values())) != len(commit_map):
        raise RuntimeError('Rewriting collapsed distinct commits; manual review required')
    object_map.update(commit_map)
    tag_signatures = []

    def rewrite_tag(oid):
        if oid in object_map:
            return object_map[oid]
        payload = graph.raw_tags[oid]
        first, rest = payload.split(b'\n', 1)
        target = first[7:].decode('ascii')
        if target in graph.raw_tags:
            new_target = rewrite_tag(target)
        elif target in external:
            new_target = hm.put_object(destination, 'blob', reference_payload([dict(blob_records[target], path='<direct-object-ref>')]))
        else:
            new_target = object_map[target]
        rewritten = b'object ' + new_target.encode('ascii') + b'\n' + rest
        if target != new_target:
            rewritten, removed = re.subn(rb'\n-----BEGIN (PGP SIGNATURE|SSH SIGNATURE|SIGNED MESSAGE)-----.*', b'\n', rewritten, flags=re.S)
            if removed:
                tag_signatures.append({'old_tag': oid, 'signature_blocks_removed': removed})
        object_map[oid] = hm.put_object(destination, 'tag', rewritten)
        return object_map[oid]

    for oid in graph.raw_tags:
        rewrite_tag(oid)
    source_reachable = set(lines(source, 'rev-list', '--all'))
    source_reflog = set(lines(source, 'rev-list', '--all', '--reflog'))
    tips = set(commit_map) - {item for group in parents.values() for item in group if item in commit_map}
    recovered = tips - source_reachable
    ref_map = []
    commands = []
    for item in graph.refs:
        if item['oid'] not in object_map:
            raise ValueError('Direct externalized object ref needs explicit handling')
        new_oid = object_map[item['oid']]
        ref_map.append(dict(item, public_oid=new_oid))
        if not item['symbolic']:
            commands.append(f"create {item['ref']} {new_oid}")
    for oid in sorted(recovered):
        commands.append(f'create refs/archive-recovered/{oid} {commit_map[oid]}')
    # Retain locally stored annotated tags even when no ref currently names them.
    for oid in sorted(graph.raw_tags):
        commands.append(f'create refs/archive-tags/{oid} {object_map[oid]}')
    git(destination, 'update-ref', '--stdin', data=('\n'.join(commands) + '\n').encode('utf-8'))
    for item in graph.refs:
        if item['symbolic']:
            git(destination, 'symbolic-ref', item['ref'], item['symbolic'])
    symbolic = git(source, 'symbolic-ref', '-q', 'HEAD', check=False)
    if symbolic.returncode == 0:
        git(destination, 'symbolic-ref', 'HEAD', symbolic.stdout.decode().strip())
    else:
        old_head = git(source, 'rev-parse', 'HEAD').stdout.decode().strip()
        git(destination, 'update-ref', 'HEAD', commit_map[old_head])
    if set(lines(destination, 'rev-list', '--all')) != set(commit_map.values()):
        raise RuntimeError('Public commit coverage mismatch')
    if set(blob_records) & set(metadata(destination)):
        raise RuntimeError('Externalized payload survives in public object storage')
    git(destination, 'fsck', '--full', '--strict')
    if refs(source) != graph.refs:
        raise RuntimeError('Source refs changed during export')
    report = {'schema': 1, 'component': source.name,
              'source_original_commit_count': len(commit_map),
              'source_ref_reachable_commits': len(source_reachable),
              'source_reflog_only_commits': len(source_reflog - source_reachable),
              'source_fully_unreachable_commits': len(set(commit_map) - source_reflog - source_reachable),
              'public_commit_count': len(commit_map), 'commit_map': commit_map,
              'unchanged_commit_ids': sum(old == new for old, new in commit_map.items()),
              'rewritten_commit_ids': sum(old != new for old, new in commit_map.items()),
              'refs': ref_map, 'recovered_tips': {old: commit_map[old] for old in sorted(recovered)},
              'all_graph_tips': {old: commit_map[old] for old in sorted(tips)},
              'tag_map': {old: object_map[old] for old in sorted(graph.raw_tags)},
              'externalized_blobs': blob_records, 'reference_roots': reference_roots,
              'missing_shallow_parents': missing, 'shallow_boundary_commits': sorted(graph.shallow),
              'stripped_invalid_signatures': signatures, 'stripped_tag_signatures': tag_signatures,
              'redactions': [], 'fsck_strict_passed': True,
              'all_commit_metadata_and_messages_preserved': True,
              'parent_order_preserved_except_documented_missing_shallow_parents': True,
              'limitations': ['Only locally stored history is available; no remote was fetched.',
                             'Removed payload bytes and original signatures remain only in the private original Git archive.',
                             'Credential detection is heuristic; exact findings require independent review.']}
    hm.save_new(report_path, report)
    return report


def verify(source, destination, report, aggregate_receipt=None):
    """Independently compare every commit and every changed tree recursively."""
    mapping = report['commit_map']
    missing = {(item['commit'], item['missing_parent'], item['parent_position'])
               for item in report['missing_shallow_parents']}
    external = report['externalized_blobs']
    original_objects = metadata(source)
    source_tags = {oid for oid, item in original_objects.items() if item['type'] == 'tag'}
    if source_tags != set(report['tag_map']):
        raise RuntimeError('Locally stored annotated tag coverage is not exact')
    checked = {}
    checked_roots = set()
    source_parents = {}
    shallow = set(report['shallow_boundary_commits'])
    shallow_file = Path(git(source, 'rev-parse', '--path-format=absolute', '--git-path', 'shallow').stdout.decode().strip())
    actual_shallow = set(shallow_file.read_text(encoding='ascii').splitlines()) if shallow_file.exists() else set()
    if shallow != actual_shallow:
        raise RuntimeError('Source shallow boundary metadata changed')
    for commit, parent, position in missing:
        if commit not in shallow or parent in mapping:
            raise RuntimeError('Declared missing edge is not a genuine shallow boundary')
    with Reader(source) as old_reader, Reader(destination) as new_reader:
        for oid, record in external.items():
            kind, payload = old_reader.read(oid)
            if kind != 'blob' or len(payload) != record['bytes'] or hashlib.sha256(payload).hexdigest() != record['sha256']:
                raise RuntimeError('Externalized original payload size or SHA-256 mismatch')
        old_cache = {}
        new_cache = {}

        def tree_data(oid, old):
            cache = old_cache if old else new_cache
            if oid not in cache:
                kind, data = (old_reader if old else new_reader).read(oid)
                if kind != 'tree':
                    raise RuntimeError('Expected tree')
                cache[oid] = entries(data)
            return cache[oid]

        def compare_tree(old, new, root=False, prefix=''):
            cache_key = (old, new, root, prefix)
            if cache_key in checked:
                return checked[cache_key]
            left = tree_data(old, True)
            right = {name: (oid, mode) for name, oid, mode in tree_data(new, False)}
            records = []
            for name, oid, mode in left:
                path = name.decode('utf-8', 'surrogateescape')
                if mode == b'160000':
                    if name in right:
                        raise RuntimeError('Gitlink still materialized')
                    records.append({'path': path, 'object': oid, 'git_mode': '160000',
                                    'reasons': ['nested_gitlink'],
                                    'restore': 'Obtain the dependency at this original commit separately; no dependency files are invented.'})
                elif oid in external:
                    if name in right:
                        raise RuntimeError('External payload still materialized')
                    records.append(dict(external[oid], path=path, git_mode=mode.decode('ascii')))
                else:
                    actual_oid, actual_mode = right.pop(name)
                    if mode != actual_mode:
                        raise RuntimeError('Unexpected mode change')
                    if mode == b'40000':
                        child_records = compare_tree(oid, actual_oid, prefix=prefix + path + '/')
                        records.extend(dict(item, path=path + '/' + item['path']) for item in child_records)
                    elif actual_oid != oid:
                        raise RuntimeError('Unexpected public blob change')
                    elif sg.blocked_path(prefix + path) or original_objects[oid]['size'] > sg.MAX_BLOB:
                        raise RuntimeError('Forbidden historical payload was retained')
            if root and records:
                actual_oid, actual_mode = right.pop(REFERENCE_FILE)
                kind, payload = new_reader.read(actual_oid)
                if kind != 'blob' or actual_mode != b'100644' or payload != reference_payload(records):
                    raise RuntimeError('Reference metadata does not describe exact exclusions')
            if right:
                raise RuntimeError('Unexpected tree addition')
            checked[cache_key] = records
            return records

        def compare_target(old_target, new_target):
            old_kind = original_objects[old_target]['type']
            new_kind, new_payload = new_reader.read(new_target)
            if old_kind != new_kind:
                raise RuntimeError('Referenced object type changed')
            if old_kind == 'commit':
                if new_target != mapping[old_target]:
                    raise RuntimeError('Referenced commit target mismatch')
            elif old_kind == 'tag':
                if new_target != report['tag_map'][old_target]:
                    raise RuntimeError('Referenced nested tag target mismatch')
            elif old_kind == 'tree':
                compare_tree(old_target, new_target, root=True)
            elif old_kind == 'blob':
                if old_target in external:
                    expected = reference_payload([dict(external[old_target], path='<direct-object-ref>')])
                    if new_payload != expected:
                        raise RuntimeError('Direct blob reference metadata differs from declared original')
                elif new_target != old_target or original_objects[old_target]['size'] > sg.MAX_BLOB:
                    raise RuntimeError('Direct blob reference changed or exceeds payload limit')
            else:
                raise RuntimeError('Unsupported referenced object type')

        for old, new in mapping.items():
            _, original = old_reader.read(old)
            _, public = new_reader.read(new)
            old_records, old_message, old_tree, old_parents = commit_parts(original)
            source_parents[old] = old_parents
            new_records, new_message, new_tree, new_parents = commit_parts(public)
            for item_commit, item_parent, position in missing:
                if item_commit == old and (position >= len(old_parents) or old_parents[position] != item_parent):
                    raise RuntimeError('Declared shallow edge is absent from original commit')
            expected_parents = [mapping[parent] for position, parent in enumerate(old_parents)
                                if (old, parent, position) not in missing]
            if new_parents != expected_parents or old_message != new_message:
                raise RuntimeError('Commit message or parent order changed')
            ignored = {b'tree', b'parent'} | (SIGNATURE_HEADERS if old != new else set())
            if old != new and any(record.split(b' ', 1)[0] in SIGNATURE_HEADERS for record in new_records):
                raise RuntimeError('Rewritten commit retains an invalid signature header')
            old_meta = [record for record in old_records if record.split(b' ', 1)[0] not in ignored]
            new_meta = [record for record in new_records if record.split(b' ', 1)[0] not in ignored]
            if old_meta != new_meta:
                raise RuntimeError('Commit author, committer, timestamp, encoding or extra metadata changed')
            if (old_tree, new_tree) not in checked_roots:
                compare_tree(old_tree, new_tree, root=True)
                checked_roots.add((old_tree, new_tree))
        for old, new in report['tag_map'].items():
            old_kind, original = old_reader.read(old)
            new_kind, public = new_reader.read(new)
            if old_kind != 'tag' or new_kind != 'tag':
                raise RuntimeError('Tag kind changed')
            old_first, old_rest = original.split(b'\n', 1)
            new_first, new_rest = public.split(b'\n', 1)
            target = old_first[7:].decode('ascii')
            new_target = new_first[7:].decode('ascii')
            compare_target(target, new_target)
            if target != new_target:
                old_rest = re.sub(rb'\n-----BEGIN (PGP SIGNATURE|SSH SIGNATURE|SIGNED MESSAGE)-----.*', b'\n', old_rest, flags=re.S)
            if new_rest != old_rest:
                raise RuntimeError('Tag name, tagger, timestamp or unsigned message changed')
        for item in report['refs']:
            compare_target(item['oid'], item['public_oid'])
    actual_refs = {item['ref']: item for item in refs(destination)}
    expected_source_refs = [{key: value for key, value in item.items() if key != 'public_oid'} for item in report['refs']]
    if refs(source) != expected_source_refs:
        raise RuntimeError('Source refs differ from the documented migration baseline')
    expected_refs = {}
    for item in report['refs']:
        expected_refs[item['ref']] = {'oid': item['public_oid'], 'symbolic': item['symbolic']}
        if actual_refs[item['ref']]['oid'] != item['public_oid'] or actual_refs[item['ref']]['type'] != item['type']:
            raise RuntimeError('Ref target differs from declared mapping')
    graph_tips = set(mapping) - {parent for group in source_parents.values() for parent in group if parent in mapping}
    if report['all_graph_tips'] != {old: mapping[old] for old in graph_tips}:
        raise RuntimeError('Declared all-graph tips differ from source graph')
    source_reachable = set(lines(source, 'rev-list', '--all'))
    if report['recovered_tips'] != {old: mapping[old] for old in graph_tips - source_reachable}:
        raise RuntimeError('Recovered tip coverage differs from source graph')
    for old, new in report['recovered_tips'].items():
        expected_refs['refs/archive-recovered/' + old] = {'oid': new, 'symbolic': None}
    for old, new in report['tag_map'].items():
        expected_refs['refs/archive-tags/' + old] = {'oid': new, 'symbolic': None}
    if aggregate_receipt:
        expected_refs[aggregate_receipt['archive_ref']] = {'oid': aggregate_receipt['archive_commit'], 'symbolic': None}
    if set(actual_refs) != set(expected_refs):
        raise RuntimeError('Unexpected or missing public refs')
    for name, item in expected_refs.items():
        if actual_refs[name]['oid'] != item['oid'] or actual_refs[name]['symbolic'] != item['symbolic']:
            raise RuntimeError('Public ref target or symbolic destination changed')
    old_symbolic = git(source, 'symbolic-ref', '-q', 'HEAD', check=False)
    new_symbolic = git(destination, 'symbolic-ref', '-q', 'HEAD', check=False)
    if old_symbolic.returncode == 0:
        if new_symbolic.returncode != 0 or old_symbolic.stdout != new_symbolic.stdout:
            raise RuntimeError('Symbolic HEAD changed')
    else:
        old_head = git(source, 'rev-parse', 'HEAD').stdout.decode().strip()
        new_head = git(destination, 'rev-parse', 'HEAD').stdout.decode().strip()
        if new_symbolic.returncode == 0 or new_head != mapping[old_head]:
            raise RuntimeError('Detached HEAD changed')
    expected_commits = set(mapping.values())
    if aggregate_receipt:
        added = {item['commit'] for item in aggregate_receipt['created_commits']}
        archive = aggregate_receipt['archive_commit']
        if set(lines(destination, 'rev-list', archive)) != expected_commits | added:
            raise RuntimeError('Aggregation receipt does not cover exactly the mapped history')
        expected_commits |= added
    if set(lines(destination, 'rev-list', '--all')) != expected_commits:
        raise RuntimeError('Mapped commit coverage is not exact')
    public_meta = metadata(destination)
    if set(external) & set(public_meta):
        raise RuntimeError('Original externalized payload is stored publicly')
    source_commits = {oid for oid, item in metadata(source).items() if item['type'] == 'commit'}
    if source_commits != set(mapping):
        raise RuntimeError('Locally stored source commit set changed or was omitted')
    git(destination, 'fsck', '--full', '--strict')
    return {'schema': 1, 'verifier_contract': VERIFIER_CONTRACT,
            'commits_verified': len(mapping), 'refs_verified': len(report['refs']),
            'public_ref_set_verified': len(actual_refs),
            'source_tag_set_and_symbolic_ref_targets_exact': True,
            'annotated_tags_verified': len(report['tag_map']),
            'tree_pairs_verified': len(checked),
            'changed_tree_pairs_verified': sum(old != new for old, new, _, _ in checked),
            'root_tree_pairs_verified': len(checked_roots),
            'messages_metadata_and_available_parent_order_preserved': True,
            'only_declared_payload_or_gitlink_exclusions': True,
            'missing_shallow_edges_verified': len(missing),
            'externalized_payloads_absent_from_object_storage': True,
            'all_locally_stored_commits_covered': True, 'public_commit_coverage_exact': True,
            'fsck_strict_passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build_parser = sub.add_parser('build')
    for name in ['source', 'dest', 'report', 'scan-report']:
        build_parser.add_argument('--' + name, type=Path, required=True)
    build_parser.add_argument('--allow-shallow-boundary', action='store_true')
    build_parser.add_argument('--externalization-plan', type=Path)
    build_parser.add_argument('--scan-workers', type=int, default=1)
    verify_parser = sub.add_parser('verify')
    for name in ['source', 'dest', 'report', 'out']:
        verify_parser.add_argument('--' + name, type=Path, required=True)
    verify_parser.add_argument('--aggregate-receipt', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'build':
            result = build(args.source, args.dest, args.report, args.scan_report,
                           allow_shallow=args.allow_shallow_boundary,
                           externalization_plan=json.loads(args.externalization_plan.read_text(encoding='utf-8')) if args.externalization_plan else None,
                           scan_workers=args.scan_workers)
            print(json.dumps({key: result[key] for key in ['component', 'public_commit_count',
                'unchanged_commit_ids', 'rewritten_commit_ids', 'fsck_strict_passed']}))
        else:
            result = verify(args.source, args.dest, json.loads(args.report.read_text(encoding='utf-8')),
                            json.loads(args.aggregate_receipt.read_text(encoding='utf-8')) if args.aggregate_receipt else None)
            hm.save_new(args.out, result)
            print(json.dumps(result))
        return 0
    except Exception as exc:
        # An object or malformed filename can carry secrets; don't echo it.
        print(json.dumps({'pass': False, 'error': type(exc).__name__, 'failed_closed': True}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
