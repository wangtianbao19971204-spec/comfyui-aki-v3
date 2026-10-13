"""Keep the Krea2 control and pose chain enabled when its branch is activated.

Reproduction (local/reproduce_branch_activation.py): activateBranch (uap_workbench.js L124-129)
writes b.modes[id] ?? 0 for the target branch, so k2's table decides what survives a branch
switch. The table said 2 (muted) for the Depth control chain and the pose studio, so after
switching to Krea2 the exporter dropped Krea2ControlApply and the sampler silently fell back to
the raw model (input_02 of DazzleSwitch 1187) - no error, just no control.

This enables exactly the control/pose chain in k2's table and leaves every other node's recorded
mode alone, so optional tools (captioning, gallery, comparers) stay off and t2i-to-control
switching keeps working through the model switch.
"""
import argparse
import json
import pathlib

TARGETS = ('ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json',
           'production_tools/templates/UAP统一生产工作台_v2.json')
BRANCH = 'k2'
ENABLE = {
    130163: 'K2 subgraph instance (line-art, erase, pose depth, encoder)',
    1161: 'Krea2ControlApply',
    1160: 'Krea2ControlLoRALoader',
    1172: 'VNCCS_PoseStudio',
    1149: 'VNCCS pose reference loader',
}
# previews and the temporary line-art save stay off: they only add visual noise
KEEP_MUTED = (1163, 1150, 1228, 1182)


def align(path: pathlib.Path, write: bool) -> dict:
    graph = json.loads(path.read_text(encoding='utf8'))
    nodes = {node['id']: node for node in graph['nodes']}
    branch = next(item for item in graph['extra']['uap_workbench']['branches'] if item['id'] == BRANCH)
    modes = branch.setdefault('modes', {})
    changes = []
    for node_id, why in ENABLE.items():
        node = nodes.get(node_id)
        if node is None:
            continue
        before = modes.get(str(node_id))
        if before != 0:
            changes.append({'node': node_id, 'type': node['type'], 'table_before': before,
                            'table_after': 0, 'why': why})
            modes[str(node_id)] = 0
        # keep the saved node mode consistent so a save without a branch switch cannot drift back
        if node.get('mode', 0) != 0:
            changes.append({'node': node_id, 'field': 'node.mode',
                            'before': node.get('mode', 0), 'after': 0})
            node['mode'] = 0
    report = {'path': path.name, 'branch': BRANCH, 'enabled': sorted(ENABLE),
              'kept_muted': list(KEEP_MUTED), 'changes': changes, 'written': write}
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
