export function capturePromptTarget(node, widget, getGraph) {
    const graph = getGraph();
    const graphId = graph?.id;
    const branch = graph?.extra?.uap_workbench?.activeBranch;
    const mode = node?.mode ?? 0;
    return () => {
        if (!graph || getGraph() !== graph || graph.id !== graphId ||
            graph.getNodeById(node?.id) !== node || node.graph !== graph ||
            !node.widgets?.includes(widget) || (node.mode ?? 0) !== mode ||
            graph.extra?.uap_workbench?.activeBranch !== branch) {
            throw new Error("目标工作流、分支或节点状态已变化，请关闭并从当前节点重新打开选择器。");
        }
    };
}

function canonicalVariantValue(value, isRoot = false) {
    if (Array.isArray(value)) return value.map(item => canonicalVariantValue(item));
    if (value && typeof value === "object") {
        return Object.fromEntries(Object.entries(value)
            .filter(([key]) => !isRoot || key !== "selectorKey")
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([key, val]) => [key, canonicalVariantValue(val)]));
    }
    return value;
}

export function getPromptItemBaseKey(item) {
    if (!item || typeof item !== "object") return "";
    if (item.isCustom) return `custom:${String(item.id || item.name || "")}`;
    const origin = item.shared ? "shared" : "local";
    // The shared endpoint uses a lightweight index id
    // `weilin:index:<kind>:<stable>` and a full-record id
    // `weilin:<kind>:<stable>`. Treat them as the same source identity so a
    // lazy index-to-full upgrade does not invalidate selection/favorites.
    const rawId = String(item.id || item.name || "");
    const normalizedId = rawId.replace(/^weilin:index:([^:]+):/, "weilin:$1:");
    return `${origin}:${normalizedId}`;
}

export function getPromptItemKey(item) {
    if (!item || typeof item !== "object") return "";
    return item.selectorKey ? String(item.selectorKey) : getPromptItemBaseKey(item);
}

export function getPromptItemVariantKey(item) {
    const base = getPromptItemBaseKey(item);
    const canonical = canonicalVariantValue(item, true);
    return `${base}:variant:${encodeURIComponent(JSON.stringify(canonical))}`;
}

export function assignPromptSelectorKeys(items) {
    const list = Array.isArray(items) ? items : [];
    const counts = new Map();
    list.forEach(item => {
        const key = getPromptItemBaseKey(item);
        if (key) counts.set(key, (counts.get(key) || 0) + 1);
    });
    list.forEach(item => {
        const base = getPromptItemBaseKey(item);
        if (base && counts.get(base) > 1 && !item.selectorKey) {
            item.selectorKey = getPromptItemVariantKey(item);
        }
    });
    return list;
}

export function getPromptFavoriteSourceKey(item, items) {
    if (!item?.shared) return getPromptItemKey(item);
    if (String(item.id || "").startsWith("weilin:index:")) return "";
    const base = getPromptItemBaseKey(item);
    if (!/^shared:weilin:(?:character|clothing|pose|background|artist|style_quality):/.test(base)) return "";
    const matches = (Array.isArray(items) ? items : []).filter(candidate => candidate?.shared && getPromptItemBaseKey(candidate) === base);
    // A source can arrive twice through paging and lookup. Different payloads
    // remain ambiguous even when their IDs match.
    const variants = new Set(matches.map(getPromptItemVariantKey));
    return variants.size === 1 && variants.has(getPromptItemVariantKey(item)) ? base : "";
}

export function resolvePromptFavorites(items, favoriteItems) {
    const records = Array.isArray(favoriteItems) ? favoriteItems : [];
    const available = Array.isArray(items) ? items : [];
    const map = new Map();
    const unresolved = [];
    records.forEach(record => {
        if (record?.isCustom) return;
        let key = record.selectorKey ? String(record.selectorKey) : "";
        if (key) {
            let matches = available.filter(item => getPromptItemKey(item) === key);
            if (key.startsWith("shared:weilin:") && !key.includes(":variant:")) {
                matches = available.filter(item => item?.shared && getPromptItemBaseKey(item) === key && getPromptFavoriteSourceKey(item, available) === key);
            }
            const selectionKeys = new Set(matches.map(getPromptItemKey));
            const selectionKey = selectionKeys.values().next().value;
            if (selectionKeys.size !== 1 || map.has(selectionKey)) unresolved.push({ ...record });
            else map.set(selectionKey, { ...record, selectorKey: key });
            return;
        }
        const matches = available.filter(item => String(item.name || "") === String(record.name || ""));
        if (matches.length !== 1) { unresolved.push({ ...record }); return; }
        key = getPromptItemKey(matches[0]);
        const sourceKey = getPromptFavoriteSourceKey(matches[0], available);
        if (!sourceKey || map.has(key)) unresolved.push({ ...record });
        else map.set(key, { ...record, selectorKey: sourceKey });
    });
    return { map, set: new Set(map.keys()), unresolved };
}

export function getSharedFavoritePromptId(record) {
    // Stored resource IDs are authoritative; a display name is never enough to rebind.
    for (const value of [record?.id, record?.selectorKey]) {
        const text = String(value || "");
        if (value === record?.selectorKey && text.includes(":variant:")) continue;
        const match = text.match(/^(?:shared:)?weilin:(?:index:)?(?:character|clothing|pose|background|style_quality):(.+)$/);
        if (match) return match[1];
    }
    return "";
}

export function appendUnresolvedPromptFavorites(parent, records) {
    const document = parent.ownerDocument;
    const previousDetails = [...parent.querySelectorAll(":scope > .anima-unresolved-favorites")];
    const previous = previousDetails[0];
    const signature = JSON.stringify(records || []);
    if (previousDetails.length === 1 && previous._unresolvedFavoritesSignature === signature) return;
    const expanded = previous?.open;
    const hadFocus = previousDetails.some(details => details.contains(document.activeElement));
    const overlay = parent.closest('[id^="anima-"][id$="selector-overlay"]');
    const overlayStyle = hadFocus && overlay ? document.defaultView.getComputedStyle(overlay) : null;
    const restoreFocus = hadFocus && parent.isConnected && !parent.closest("[hidden], [inert]")
        && !overlay?.inert && overlayStyle?.display !== "none" && overlayStyle?.visibility !== "hidden";
    previousDetails.forEach(details => details.remove());
    if (!records?.length) {
        if (restoreFocus) overlay?.querySelector('input[type="search"]')?.focus();
        return;
    }
    const details = document.createElement("details");
    details.className = "anima-unresolved-favorites";
    details.open = Boolean(expanded);
    details._unresolvedFavoritesSignature = signature;
    details.style.cssText = "margin-top:4px;font-size:11px;color:#fbbf24;max-width:520px;";
    const summary = document.createElement("summary");
    summary.textContent = `旧收藏待确认 ${records.length} 条（保留原记录）`;
    details.appendChild(summary);
    const list = document.createElement("div");
    list.style.cssText = "max-height:180px;overflow:auto;overflow-wrap:anywhere;";
    for (const record of records) {
        const row = document.createElement("div");
        row.style.cssText = "padding:5px 0;border-top:1px solid #52525b;";
        const name = document.createElement("div");
        name.textContent = String(record?.nickname || record?.name || "未命名旧收藏");
        const identity = document.createElement("div");
        identity.textContent = `原名称：${record?.name || "未命名"}；原 ID：${record?.selectorKey || record?.id || "未记录"}`;
        row.append(name, identity);
        const promptId = getSharedFavoritePromptId(record);
        const status = document.createElement("span");
        if (promptId) {
            const locate = document.createElement("button");
            locate.type = "button";
            locate.textContent = "查看当前资料";
            locate.onclick = async event => {
                event.stopPropagation();
                if (locate.disabled) return;
                locate.disabled = true;
                const overlay = parent.closest('[id^="anima-"][id$="selector-overlay"]');
                const display = overlay?.style.display;
                const wasInert = overlay?.inert;
                const restore = () => {
                    if (overlay?.isConnected) {
                        overlay.style.display = display;
                        overlay.inert = wasInert;
                        locate.focus();
                    }
                };
                try {
                    const open = document.defaultView?.tbOpenSharedPresetManager;
                    if (typeof open !== "function") throw new Error("资料库尚未就绪，请稍后重试。");
                    if (overlay) { overlay.style.display = "none"; overlay.inert = true; }
                    const opened = await open({promptId, view:"categories", onClose:restore});
                    status.textContent = opened === false ? "未能定位，原收藏仍保留。" : "已打开当前资料；原收藏仍保留。";
                } catch (error) { restore(); status.textContent = error.message || String(error); }
                finally { locate.disabled = false; }
            };
            row.appendChild(locate);
        } else {
            status.textContent = "没有可唯一定位的共享 ID，请按原名称核对后重新收藏。";
        }
        row.appendChild(status);
        list.appendChild(row);
    }
    details.appendChild(list);
    parent.appendChild(details);
    if (restoreFocus) summary.focus();
}
