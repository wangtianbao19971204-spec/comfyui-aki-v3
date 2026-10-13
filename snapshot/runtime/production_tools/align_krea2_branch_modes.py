"""Align the Krea2 branch's mode table with the state the branch actually works in.

The workbench applies branches[].modes when a branch is activated (uap_workbench.js activateBranch,
L124-129), and snapshots node.mode back into the previous branch's table only when leaving. That
leaves two sources of truth. For the Krea2 branch they had drifted: the file has the control chain
active (mode 0) while the table still says 2 (muted), so activating the branch from another one
muted Krea2ControlApply and the pose studio. With Krea2ControlApply muted, DazzleSwitch 1187 runs
in "priority" mode, silently falls back to input_02 (the raw model) and the Depth control vanishes
without any error.

This writes the file's current modes into the branch table so the two agree, and does not touch
any node's own mode.
"""
import argparse
import json
import pathlib

TARGETS = ('ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json',
           'production_tools/templates/UAP统一生产工作台_v2.json')
BRANCH = 'k2'


def align(path: pathlib.Path, write: bool) -> dict:
    graph = json.loads(path.read_text(encoding='utf8'))
    nodes = {node['id']: node for node in graph['nodes']}
    branch = next(item for item in graph['extra']['uap_workbench']['branches'] if item['id'] == BRANCH)
    modes = branch.setdefault('modes', {})
    changes = []
    for value in branch['nodeIds']:
        node = nodes.get(value if isinstance(value, int) else int(value))
        if node is None:
            continue
        current = node.get('mode', 0)
        recorded = modes.get(str(value))
        if recorded != current:
            changes.append({'node': value, 'type': node['type'],
                            'title': (node.get('title') or '')[:30],
                            'table_before': recorded, 'file': current})
            modes[str(value)] = current
    report = {'path': str(path.name), 'branch': BRANCH, 'aligned': len(changes),
              'changes': changes, 'written': write}
    if write:
        path.write_text(json.dumps(graph, ensure_ascii=False) + '\n', encoding='utf8', newline='')
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=pathlib.Path,
                        default=pathlib.Path(r'G:/ComfyUI-aki-v3/maintenance/comfyui/snapshot/runtime'))
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    for relative in TARGETS:
        print(json.dumps(align(args.repo / relative, args.write), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
