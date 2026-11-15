import {app} from '../../../scripts/app.js';

// 只读自检：不动画布、不进队列、不写 userdata；?uapcheck=1 时自动跑一次。
const IO_NODE_IDS = new Set([-10, -20]);
const AUTO = /[?&]uapcheck=1(?:&|$)/.test(location.search);
let ran = false;

const asList = value => Array.isArray(value) ? value
    : value instanceof Map ? [...value.values()]
    : value && typeof value === 'object' ? Object.values(value) : [];

// 节点 id 在新前端是字符串，旧工作流可能是数字，统一按字符串比对。
const keyOf = value => String(value);
const isIoNode = value => IO_NODE_IDS.has(Number(value));

// link 在旧格式里是数组，新格式里是对象，两套都归一化。
function linkFields(link) {
    if (Array.isArray(link)) return {id: link[0], origin: link[1], target: link[3]};
    return {id: link?.id, origin: link?.origin_id, target: link?.target_id};
}

function linkRows(links) {
    if (links instanceof Map) return [...links.entries()];
    if (Array.isArray(links)) return links.map((link, index) => [index, link]);
    if (links && typeof links === 'object') return Object.entries(links);
    return [];
}

// 1.55 起读 .link 会刷废弃警告，优先走 getInputLink / isInputConnected。
function inputLink(node, index) {
    if (typeof node.getInputLink === 'function') return node.getInputLink(index)?.id ?? null;
    return node.inputs?.[index]?.link ?? null;
}

function outputConnected(node, index) {
    if (typeof node.isOutputConnected === 'function') return node.isOutputConnected(index);
    return node.outputs?.[index]?.link != null;
}

// 子图定义来自根图的注册表，也来自实例节点自带的 subgraph。
function registerSubgraphs(root, nodes) {
    const defs = new Map();
    for (const source of [root?.subgraphs, root?._subgraphs, root?.definitions?.subgraphs, nodes.map(node => node?.subgraph)])
        for (const def of asList(source))
            if (def?.id && !defs.has(def.id)) defs.set(def.id, def);
    return defs;
}

function hasWidget(slot) {
    return slot?.widget != null || slot?.widgetId != null;
}

function reportSlot(result, label, node, kind, index, name, reason) {
    result.subgraphIo.push({graph: label, nodeId: node.id, type: node.type, slot: kind, index, name, reason});
}

// 子图实例：输入槽要么接线要么有 widget，输出槽必须对得上定义的 outputs。
// 子图实例的 getInputLink 返回的是内部连线（id 属于子图，不在根图 links 里），
// 所以这里只信 isInputConnected，不拿根图 links 去比对。
function inputConnected(node, index) {
    if (typeof node.isInputConnected === 'function') return node.isInputConnected(index);
    return node.inputs?.[index]?.link != null;
}

function checkSubgraphInstance(label, node, def, result) {
    for (const [index, slot] of (node.inputs || []).entries())
        if (!inputConnected(node, index) && !hasWidget(slot))
            reportSlot(result, label, node, 'input', index, slot?.name, 'unconnected');
    const defined = def.outputs || [];
    for (const [index, slot] of (node.outputs || []).entries()) {
        const target = defined[index];
        if (!target) reportSlot(result, label, node, 'output', index, slot?.name, 'missing-definition');
        else if (outputConnected(node, index) && target.name !== slot?.name)
            reportSlot(result, label, node, 'output', index, slot?.name, 'name-mismatch');
    }
}

function inspect(root) {
    const result = {ok: true, nodeCount: 0, dupNodeIds: [], dupLinkIds: [],
        missingLinkEnds: [], danglingInputs: [], subgraphIo: []};
    if (!root) return result;
    const rootNodes = asList(root.nodes ?? root._nodes);
    const defs = registerSubgraphs(root, rootNodes);
    const scopes = [{label: 'root', graph: root}, ...[...defs].map(([id, def]) => ({label: 'subgraph:' + id, graph: def}))];
    const linkOwners = new Map();

    for (const {label, graph} of scopes) {
        const nodes = asList(graph.nodes ?? graph._nodes);
        result.nodeCount += nodes.length;

        const byId = new Map();
        for (const node of nodes) {
            byId.set(keyOf(node.id), (byId.get(keyOf(node.id)) || 0) + 1);
            if (Number(node.id) < 0 && !isIoNode(node.id))
                result.dupNodeIds.push({graph: label, id: node.id, count: 0, reason: 'negative'});
        }
        for (const [id, count] of byId)
            if (count > 1) result.dupNodeIds.push({graph: label, id, count, reason: 'duplicate'});

        const links = new Map();
        for (const [key, value] of linkRows(graph.links)) {
            const link = linkFields(value);
            const id = link.id ?? key;
            links.set(keyOf(id), {...link, id});
            const owner = linkOwners.get(keyOf(id)) || new Map();
            owner.set(label, (owner.get(label) || 0) + 1);
            linkOwners.set(keyOf(id), owner);
        }

        for (const link of links.values()) {
            const missing = [];
            if (!byId.has(keyOf(link.origin)) && !isIoNode(link.origin)) missing.push('origin');
            if (!byId.has(keyOf(link.target)) && !isIoNode(link.target)) missing.push('target');
            if (missing.length) result.missingLinkEnds.push({graph: label, linkId: link.id,
                origin: link.origin, target: link.target, missing: missing.join('+')});
        }

        for (const node of nodes) {
            const def = defs.get(node.type);
            if (!def) {
                // 子图实例走 checkSubgraphInstance：它的 .link 是内部连线 id，不能用根图 links 判空。
                for (const [slot, port] of (node.inputs || []).entries()) {
                    const link = inputLink(node, slot);
                    if (link == null || links.has(keyOf(link))) continue;
                    result.danglingInputs.push({graph: label, nodeId: node.id, slot, name: port?.name, link});
                }
            }
            if (def) checkSubgraphInstance(label, node, def, result);
        }
    }

    for (const [id, owner] of linkOwners) {
        const total = [...owner.values()].reduce((sum, count) => sum + count, 0);
        if (total > 1) result.dupLinkIds.push({id, graphs: Object.fromEntries(owner)});
    }

    result.ok = !result.dupNodeIds.length && !result.dupLinkIds.length && !result.missingLinkEnds.length
        && !result.danglingInputs.length && !result.subgraphIo.length;
    return result;
}

function selfCheck() {
    return inspect(app?.graph ?? app?.rootGraph);
}

// 等图配置完成再跑；没图也给一次空图结果，避免静默。
function runOnce() {
    if (ran) return;
    ran = true;
    console.log('[UAP selfcheck]', JSON.stringify(selfCheck()));
}

app.registerExtension({
    name: 'UAP.SelfCheck',
    setup() {
        window.__uapSelfCheck = selfCheck;
        if (AUTO) setTimeout(runOnce, 8000);
    },
    afterConfigureGraph() {
        if (AUTO && !ran) setTimeout(runOnce, 500);
    },
});
