import { app } from "../../../scripts/app.js";

let readyGraph;
let scheduled;
const pendingGroups = new Set();

function members(group) {
    return app.graph._nodes.filter(n => n.properties?.uap_layout_group === group.title);
}

function move(group, x, y) {
    const dx = x - group._pos[0], dy = y - group._pos[1];
    for (const node of members(group)) {
        node.pos[0] += dx;
        node.pos[1] += dy;
    }
    group._pos[0] = x;
    group._pos[1] = y;
}

function packChangedGroup(group) {
    const columns = new Map();
    for (const node of members(group)) {
        const x = Math.round(node.pos[0]);
        if (!columns.has(x)) columns.set(x, []);
        columns.get(x).push(node);
    }
    let bottom = group._pos[1];
    for (const nodes of columns.values()) {
        nodes.sort((a, b) => a.pos[1] - b.pos[1]);
        let y = group._pos[1] + 58;
        for (const node of nodes) {
            node.pos[1] = y;
            y += node.size[1] + 54;
            bottom = Math.max(bottom, node.pos[1] + node.size[1]);
        }
    }
    group._size[1] = bottom - group._pos[1] + 16;
}

function reflow() {
    scheduled = undefined;
    const c = app.graph.extra?.uap_workbench;
    if (!c?.compactWidgets || readyGraph !== app.graph) return;
    const groups = new Map(app.graph._groups.map(g => [g.title, g]));
    for (const title of pendingGroups) {
        if (groups.has(title)) packChangedGroup(groups.get(title));
    }
    pendingGroups.clear();
    // Native image previews can grow after configuration without emitting a
    // compact-widget event. Account for their current bounds before moving rows.
    for (const group of groups.values()) {
        for (const node of members(group)) {
            group._size[0] = Math.max(group._size[0], node.pos[0] + node.size[0] - group._pos[0] + 16);
            group._size[1] = Math.max(group._size[1], node.pos[1] + node.size[1] - group._pos[1] + 16);
        }
    }
    let cursorY = 0;
    for (const branch of c.branches) {
        const stages = new Map(branch.stages.map(s => [s.id, s.groups.map(t => groups.get(t))]));
        if (stages.has('daily')) {
            let y = cursorY;
            const rows = branch.dailyRows?.map(row => row.map(title => groups.get(title))) || [stages.get('daily')];
            for (const row of rows) {
                let x = 0;
                for (const group of row) {
                    move(group, x, y);
                    x += group._size[0] + 32;
                }
                y += Math.max(...row.map(g => g._size[1])) + 48;
            }
            y += 48;
            for (const row of [['input', 'prompt', 'model'], ['control', 'refine', 'compare']]) {
                let x = 0, rowBottom = y;
                for (const stage of row) {
                    const items = stages.get(stage) || [];
                    let sy = y;
                    for (const group of items) {
                        move(group, x, sy);
                        sy += group._size[1] + 48;
                    }
                    rowBottom = Math.max(rowBottom, sy);
                    x += Math.max(0, ...items.map(g => g._size[0])) + 96;
                }
                y = rowBottom + 48;
            }
        } else {
            let x = 0;
            for (const stage of branch.stages) {
                for (const group of stages.get(stage.id)) {
                    move(group, x, cursorY);
                    x += group._size[0] + 48;
                }
            }
        }
        const items = [...stages.values()].flat();
        const left = Math.min(...items.map(g => g._pos[0])) - 28;
        const top = Math.min(...items.map(g => g._pos[1])) - 58;
        const right = Math.max(...items.map(g => g._pos[0] + g._size[0])) + 28;
        const bottom = Math.max(...items.map(g => g._pos[1] + g._size[1])) + 28;
        const wrapper = groups.get(branch.group);
        wrapper._pos[0] = left; wrapper._pos[1] = top;
        wrapper._size[0] = right - left; wrapper._size[1] = bottom - top;
        cursorY = bottom + 200;
    }
    app.graph.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: 'UAP.CompactWidgetLayout',
    setup() {
        window.addEventListener('uap:compact-node-resized', ({ detail }) => {
            const node = detail.node;
            if (readyGraph !== app.graph || node.graph !== app.graph || !app.graph.extra?.uap_workbench?.compactWidgets) return;
            if (!node.properties?.uap_layout_group) return;
            pendingGroups.add(node.properties.uap_layout_group);
            if (!scheduled) scheduled = requestAnimationFrame(reflow);
        });
    },
    beforeConfigureGraph() { readyGraph = undefined; pendingGroups.clear(); },
    afterConfigureGraph() { readyGraph = app.graph; },
});
