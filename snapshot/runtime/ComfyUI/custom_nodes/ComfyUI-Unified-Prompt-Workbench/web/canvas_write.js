// 画布状态的唯一写入口：只写 node.mode，不再回写 branches[].modes 快照。
const SAVED_MODES = [0, 2, 4];

export function setNodeMode(app, node, mode) {
    if (!node || node.mode === mode) return false;
    const graph = node.graph || app.graph;
    graph.beforeChange?.();
    try { node.mode = mode; }
    finally { graph.afterChange?.(); graph.setDirtyCanvas?.(true, true); }
    return true;
}

// 期望模式：节点属性优先，其次旧工作流的快照，最后按启用处理。
export function readDefaultMode(branch, node) {
    const fixed = node?.properties?.uap_default_mode;
    if (SAVED_MODES.includes(fixed)) return fixed;
    const snapshot = branch?.modes?.[node.id];
    return SAVED_MODES.includes(snapshot) ? snapshot : 0;
}

export function applyBranchModes(app, branchId) {
    const graph = app.graph, config = graph?.extra?.uap_workbench;
    if (!config?.branches?.length) return 0;
    let changed = 0;
    graph.beforeChange?.();
    try {
        for (const branch of config.branches) {
            const current = branch.id === branchId;
            for (const id of branch.nodeIds || []) {
                const node = graph.getNodeById(id);
                if (!node) continue;
                const snapshot = branch.modes?.[node.id];
                // 旧快照只在节点缺默认值时补一次，运行期不再写回
                if (node.properties?.uap_default_mode == null && (snapshot === 0 || snapshot === 2)) (node.properties ||= {}).uap_default_mode = snapshot;
                if (setNodeMode(app, node, current ? readDefaultMode(branch, node) : 2)) changed += 1;
            }
        }
    } finally { graph.afterChange?.(); graph.setDirtyCanvas?.(true, true); }
    return changed;
}
