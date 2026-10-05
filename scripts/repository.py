"""Maintain this local Git snapshot without touching the live runtime."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from snapshot import REPO, digest, is_link, scan, verify, walk
import security_guard


def run_git(*args):
    return subprocess.run(['git', '-C', str(REPO), *args], check=True, capture_output=True, text=True, encoding='utf-8').stdout.strip()


def changes(candidate):
    old=json.loads((REPO/'snapshot/manifest.json').read_text(encoding='utf-8'))
    new=json.loads((candidate/'manifest.json').read_text(encoding='utf-8'))
    def hashes(manifest):
        return {f['source']:f.get('sha256',f.get('sql_sha256')) for f in manifest['files']}
    a,b=hashes(old),hashes(new)
    old_meta={f['path']:f['sha256'] for f in old.get('metadata_files',[])}
    new_meta={f['path']:f['sha256'] for f in new.get('metadata_files',[])}
    reviewed = digest(REPO/'snapshot/manifest.json') + ':' + digest(candidate/'manifest.json')
    return {'added':sorted(b.keys()-a.keys()),'removed':sorted(a.keys()-b.keys()),'changed':sorted(k for k in a.keys()&b.keys() if a[k]!=b[k]),'metadata_added':sorted(new_meta.keys()-old_meta.keys()),'metadata_removed':sorted(old_meta.keys()-new_meta.keys()),'metadata_changed':sorted(k for k in old_meta.keys()&new_meta.keys() if old_meta[k]!=new_meta[k]),'old_time':old['created_at'],'new_time':new['created_at'],'same_runtime_root':old['source_root']==new['source_root'], 'review_sha256':hashlib.sha256(reviewed.encode('ascii')).hexdigest()}


def validate_candidate(candidate):
    if is_link(candidate):
        raise ValueError('Candidate must not be a symlink or junction')
    candidate=candidate.resolve()
    if candidate.parent!=REPO.parent or not candidate.name.startswith('comfyui-candidate-'):
        raise ValueError('Candidate must be an immediate maintenance/comfyui-candidate-* sibling')
    if not candidate.is_dir() or candidate.is_symlink():
        raise ValueError('Candidate must be an ordinary directory')
    if not verify(candidate)['pass']:
        raise RuntimeError('Candidate failed verification')
    return candidate


def adopt(candidate, *, purpose=None, reviewed_sha256=None):
    if purpose not in {'accepted-deployment', 'recovery-migration'}:
        raise ValueError('Adopt is only for an accepted deployment or reviewed recovery/migration, not routine reverse sync')
    candidate=validate_candidate(candidate)
    if run_git('status','--porcelain'):
        raise RuntimeError('Commit or separately preserve current changes before adopting another snapshot')
    diff=changes(candidate)
    if reviewed_sha256 != diff['review_sha256']:
        raise ValueError('Review compare output and pass its exact review_sha256; review is stale or missing')
    if not diff['same_runtime_root']:
        raise ValueError('Different runtime root; explicit migration review required')
    if is_link(REPO/'snapshot'):
        raise ValueError('Current snapshot must not be a symlink or junction')
    current=(REPO/'snapshot').resolve()
    if current.parent!=REPO.resolve() or current.name!='snapshot' or current.is_symlink():
        raise ValueError('Unexpected current snapshot')
    if not verify(current)['pass']:
        raise RuntimeError('Current snapshot integrity failed')
    if changes(candidate)['review_sha256'] != reviewed_sha256:
        raise RuntimeError('Manifests changed after adoption review')
    backup=REPO/'local/backups'/datetime.now().strftime('%Y%m%d_%H%M%S')
    if backup.exists():
        raise FileExistsError(backup)
    backup.parent.mkdir(parents=True,exist_ok=True)
    current.rename(backup)
    try:
        candidate.rename(current)
    except OSError:
        backup.rename(current)
        raise
    print(json.dumps({'adopted':str(current),'purpose':purpose,'recoverable_previous':str(backup),'difference':diff,'production_modified':False},ensure_ascii=False))


def check_tracked():
    tracked = set(run_git('ls-files', '-z').split('\0')) - {''}
    disk = {'snapshot/' + file.relative_to(REPO/'snapshot').as_posix() for file in walk(REPO/'snapshot', set())}
    missing = sorted(disk - tracked)
    extra = sorted(path for path in tracked if path.startswith('snapshot/') and path not in disk)
    if missing or extra:
        raise RuntimeError('Tracked snapshot differs from disk: ' + json.dumps({'untracked': missing, 'missing_on_disk': extra}))
    for line in run_git('ls-files', '--stage').splitlines():
        if line.startswith('160000 '):
            raise RuntimeError('Nested Git repository was staged as a submodule')
    for relative in sorted(tracked):
        file = REPO / relative
        if file.stat().st_size > 50 * 1024 * 1024:
            raise RuntimeError('Tracked file exceeds 50 MiB: ' + relative)
        # bundle() has already verified all snapshot hashes and credentials.
        if relative.startswith('snapshot/'):
            continue
        findings = scan(file)
        if findings:
            raise RuntimeError('Tracked credential scan failed: ' + relative + ': ' + ', '.join(findings))
    return {'tracked_files': len(tracked), 'snapshot_files': len(disk)}


def bundle(output):
    output=output.resolve()
    if output.exists() or output.is_relative_to(REPO):
        raise ValueError('Bundle must be a new file outside the checkout')
    if run_git('status','--porcelain'):
        raise RuntimeError('Uncommitted changes would not enter the bundle; commit first')
    if not verify(REPO/'snapshot')['pass']:
        raise RuntimeError('Snapshot failed verification')
    tracked = check_tracked()
    security = security_guard.run(REPO)
    if not security['pass']:
        raise RuntimeError('Public-history credential gate failed: ' + json.dumps(security['findings']))
    if run_git('status','--porcelain'):
        raise RuntimeError('Checkout changed during bundle preflight')
    output.parent.mkdir(parents=True,exist_ok=True)
    run_git('fsck','--full')
    if security_guard.refs(REPO) != security['refs']:
        raise RuntimeError('Git refs changed after security review')
    run_git('bundle','create',str(output),'--all')
    run_git('bundle','verify',str(output))
    if security_guard.refs(REPO) != security['refs']:
        raise RuntimeError('Git refs changed while bundling; quarantine this bundle and retry')
    print(json.dumps({'bundle':str(output),'bytes':output.stat().st_size,'sha256':digest(output),'head':run_git('rev-parse','HEAD'),'remote_contacted':False,'credential_history_gate':True,'scanned_objects':security['scanned_objects'],**tracked}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ['compare','adopt']:
        p=commands.add_parser(name);p.add_argument('--candidate',type=Path,required=True)
        if name == 'adopt':
            p.add_argument('--purpose', choices=['accepted-deployment', 'recovery-migration'], required=True)
            p.add_argument('--review-sha256', required=True)
    p=commands.add_parser('bundle');p.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='compare':
        print(json.dumps(changes(validate_candidate(args.candidate)),ensure_ascii=False,indent=2))
    elif args.command=='adopt':adopt(args.candidate,purpose=args.purpose,reviewed_sha256=args.review_sha256)
    else:bundle(args.out)


if __name__=='__main__':
    main()
