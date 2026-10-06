"""Read-only audit of Git uniqueness and tracked machine-path exposure.

This tool never writes to the runtime, never contacts a network and never
prints the contents of a matched line. Machine-specific absolute paths are
reported as repository-relative file names and counts only, so a report can be
reviewed without copying file bodies out of the checkout.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = REPO.parents[1]
DEFAULT_EXTERNAL = REPO.parents[2] / 'ComfyUI-local'
SOLE_DEVELOPMENT_GIT = 'maintenance/comfyui'

# These regexes are matched by git grep -E against tracked files. They describe
# a shape, not a value. Nothing here authorises printing the matched text.
EXPOSURE_PATTERNS = (
    (r'G:\\ComfyUI-aki-v3', 'workspace_absolute_path'),
    (r'C:\\Users\\Administrator', 'windows_user_profile'),
)

WALK_SKIP = {'.cache', '.git', '__pycache__', 'node_modules', 'output', 'temp'}

AREA_RULES = (
    ('docs/technical/archive/', 'docs_technical_archive'),
    ('docs/receipts/', 'docs_receipts'),
    ('docs/releases/', 'docs_releases'),
    ('docs/', 'docs_current'),
    ('governance/', 'governance'),
    ('database/', 'database'),
    ('examples/', 'examples'),
    ('scripts/', 'scripts'),
    ('tests/', 'tests'),
    ('snapshot/evidence/', 'snapshot_evidence'),
    ('snapshot/inventory/', 'snapshot_inventory'),
    ('snapshot/library/', 'snapshot_library'),
    ('snapshot/runtime/ComfyUI/custom_nodes/', 'snapshot_custom_nodes'),
    ('snapshot/runtime/qwen21_lab/', 'snapshot_qwen21_lab'),
    ('snapshot/runtime/anima_lora_forge/', 'snapshot_anima_lora_forge'),
    ('snapshot/runtime/character_lora_forge/', 'snapshot_character_lora_forge'),
    ('snapshot/runtime/production_tools/', 'snapshot_production_tools'),
    ('snapshot/runtime/remote_llm_guard/', 'snapshot_remote_llm_guard'),
    ('snapshot/runtime/tools/', 'snapshot_tools'),
    ('snapshot/runtime/', 'snapshot_runtime_root'),
)


def is_reparse_point(path):
    """True for a symlink or a Windows junction, so a walk never crosses out."""
    if os.path.islink(path):
        return True
    checker = getattr(os.path, 'isjunction', None)
    return bool(checker and checker(path))


def scan_git_directories(root, label):
    """Return every .git directory under root without following reparse points."""
    root = Path(root).resolve()
    found = []
    for directory, folders, _ in os.walk(root, followlinks=False):
        base = Path(directory)
        keep = []
        for name in folders:
            path = base / name
            if is_reparse_point(path):
                continue
            if name == '.git':
                found.append({'root': label, 'path': str(path)})
                continue
            if name in WALK_SKIP:
                continue
            keep.append(name)
        folders[:] = keep
    return sorted(found, key=lambda item: item['path'].casefold())


def scan_bare_git_directories(root, label):
    """Return bare *.git repositories, which are archives rather than worktrees."""
    root = Path(root).resolve()
    if not root.is_dir():
        return []
    found = []
    for directory, folders, _ in os.walk(root, followlinks=False):
        base = Path(directory)
        keep = []
        for name in folders:
            path = base / name
            if is_reparse_point(path):
                continue
            if name != '.git' and name.endswith('.git'):
                found.append({'root': label, 'path': str(path)})
                continue
            if name in WALK_SKIP:
                continue
            keep.append(name)
        folders[:] = keep
    return sorted(found, key=lambda item: item['path'].casefold())


def read_retired(repo=REPO):
    path = Path(repo) / 'governance/retired-git.json'
    return json.loads(path.read_text(encoding='utf-8'))


def classify_runtime_repos(runtime, repo=REPO):
    """Compare observed repositories with the retired-Git registry."""
    runtime = Path(runtime).resolve()
    repo = Path(repo).resolve()
    expected = (repo / '.git').resolve()
    retired = read_retired(repo)
    retired_paths = {item['runtime_path'] for item in retired['repositories']}
    observed = scan_git_directories(runtime, 'runtime')
    unexpected = []
    still_present = []
    for item in observed:
        path = Path(item['path'])
        if path.resolve() == expected:
            continue
        unexpected.append(item)
        try:
            relative = path.parent.resolve().relative_to(runtime).as_posix()
        except ValueError:
            continue
        if relative in retired_paths:
            still_present.append({'runtime_path': relative, 'marker': item['path']})
    return {
        'sole_development_git': str(expected),
        'sole_development_git_expected_relative': SOLE_DEVELOPMENT_GIT,
        'observed_git_directories': observed,
        'observed_count': len(observed),
        'unexpected_git_directories': unexpected,
        'retired_markers_registered': retired.get('retired_git_markers'),
        'retired_markers_still_present': still_present,
    }


def classify_external_repos(external):
    external = Path(external).resolve()
    if not external.is_dir():
        return {'root': str(external), 'present': False}
    nested = scan_git_directories(external, 'external')
    bare = scan_bare_git_directories(external, 'external')
    return {
        'root': str(external),
        'present': True,
        'nested_worktree_git_directories': nested,
        'nested_count': len(nested),
        'bare_git_directories': bare,
        'bare_count': len(bare),
        'classification': 'archive_and_validation_only',
        'note': 'Archived history and validation clones are not development sources.',
    }


def run_git(repo, *args):
    result = subprocess.run(
        ['git', '--no-optional-locks', '-C', str(repo), *args],
        capture_output=True,
    )
    return result.returncode, result.stdout


def area_of(relative):
    for prefix, name in AREA_RULES:
        if relative.startswith(prefix):
            return name
    return 'other'


def path_exposure(repo=REPO, patterns=EXPOSURE_PATTERNS):
    """Count tracked files containing machine-specific absolute paths.

    Only file names, line numbers and counts are returned; matched text is
    deliberately discarded before it can reach a report or a console.
    """
    repo = Path(repo).resolve()
    per_pattern = {}
    per_file = Counter()
    per_area = Counter()
    occurrences = 0
    for regex, label in patterns:
        code, stdout = run_git(repo, 'grep', '-n', '-I', '-E', regex, '--', '.')
        if code not in (0, 1):
            raise RuntimeError('git grep failed for pattern ' + label)
        files = Counter()
        lines = 0
        for raw in stdout.splitlines():
            text = raw.decode('utf-8', errors='surrogateescape')
            relative = text.split(':', 1)[0].strip('"')
            files[relative] += 1
            lines += 1
        per_pattern[label] = {
            'occurrences': lines,
            'files': len(files),
            'top_files': files.most_common(10),
        }
        per_file.update(files)
        occurrences += lines
        for relative, count in files.items():
            per_area[area_of(relative)] += count
    return {
        'patterns_checked': [label for _, label in patterns],
        'total_occurrences': occurrences,
        'total_distinct_files': len(per_file),
        'occurrences_by_pattern': per_pattern,
        'occurrences_by_area': dict(sorted(per_area.items())),
        'files': sorted(per_file),
        'contains_credentials': False,
        'matched_text_included': False,
        'note': ('Machine-specific absolute paths are a portability and detail '
                 'exposure, not a credential finding.'),
    }


def audit(runtime=DEFAULT_RUNTIME, external=DEFAULT_EXTERNAL, repo=REPO):
    uniqueness = classify_runtime_repos(runtime, repo)
    external_repos = classify_external_repos(external)
    exposure = path_exposure(repo)
    return {
        'schema': 1,
        'mode': 'READ_ONLY_WORKSPACE_AUDIT',
        'repo': str(Path(repo).resolve()),
        'runtime_root': str(Path(runtime).resolve()),
        'git_uniqueness': {
            **uniqueness,
            'sole_development_git_holds': (
                not uniqueness['unexpected_git_directories']
                and not uniqueness['retired_markers_still_present']
            ),
        },
        'external_repositories': external_repos,
        'tracked_path_exposure': exposure,
        'production_modified': False,
        'network_accessed': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument('--external', type=Path, default=DEFAULT_EXTERNAL)
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    report = audit(args.runtime, args.external, args.repo)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding='utf-8')
    else:
        sys.stdout.write(text)
    return 0 if report['git_uniqueness']['sole_development_git_holds'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
