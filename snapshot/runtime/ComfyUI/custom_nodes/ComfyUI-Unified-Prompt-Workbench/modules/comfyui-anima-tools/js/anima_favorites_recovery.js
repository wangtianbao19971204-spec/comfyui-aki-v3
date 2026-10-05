// One persistent recovery surface, including pending reads and writes.
let activeRecovery = false;
export async function recoverFavoritesConflict({ partition, draftSection, currentConfig, currentEtag,
    initialStatus = 409, fetchLatest, submit, commit, isActive = () => true }) {
    if (typeof document === "undefined" || activeRecovery || !isActive()) return false;
    activeRecovery = true;
    const overlay = document.createElement("div");
    overlay.dataset.animaFavoritesRecovery = "1";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "收藏保存恢复");
    overlay.style.cssText = "position:fixed;inset:0;z-index:100010;background:#000a;display:flex;align-items:center;justify-content:center;padding:24px";
    const box = document.createElement("div");
    box.style.cssText = "background:#20242b;color:#fff;max-width:760px;width:100%;max-height:85vh;overflow:auto;padding:22px;border-radius:10px;white-space:pre-wrap;font:14px sans-serif";
    const heading = document.createElement("h3"); heading.textContent = "收藏保存恢复";
    const message = document.createElement("div");
    const details = document.createElement("details");
    const summary = document.createElement("summary"); summary.textContent = "展开最新分区与草稿原文";
    const pre = document.createElement("pre"); pre.style.cssText = "max-height:35vh;overflow:auto;white-space:pre-wrap";
    details.append(summary, pre);
    const actions = document.createElement("div"); actions.style.cssText = "display:flex;gap:12px;justify-content:flex-end;margin-top:18px";
    const cancel = document.createElement("button"); cancel.textContent = "取消，保留草稿";
    const action = document.createElement("button");
    actions.append(cancel, action); box.append(heading, message, details, actions); overlay.append(box);
    document.body.append(overlay);
    let cancelled = false, decide, stopWaiting;
    const cancelledPromise = new Promise(resolve => { stopWaiting = () => resolve({ cancelled: true }); });
    const stop = () => { cancelled = true; decide?.(false); stopWaiting(); };
    cancel.onclick = stop;
    const observer = typeof MutationObserver === "function" ? new MutationObserver(() => {
        if (!isActive() || !overlay.isConnected) stop();
    }) : null;
    observer?.observe(document.body, { childList: true, subtree: true });
    const alive = () => !cancelled && isActive();
    const wait = promise => Promise.race([Promise.resolve(promise).then(value => ({ value }), error => ({ error })), cancelledPromise]);
    const pending = text => { message.textContent = text; action.disabled = true; action.textContent = "请稍候"; };
    const choose = (text, label) => {
        if (!alive()) return Promise.resolve(false);
        message.textContent = text; action.textContent = label; action.disabled = false;
        return new Promise(resolve => { decide = resolve; action.onclick = () => {
            if (action.disabled || !alive()) return;
            action.disabled = true; decide = null; resolve(true);
        }; });
    };
    const counts = section => "分组 " + (section?.groups || []).length + " 个，项目 " + (section?.items || []).length + " 条";
    const preserveNewFields = (draft, latest) => (draft || []).map(item => {
        if (!item || typeof item !== "object" || !item.id) return item;
        const matches = (latest || []).filter(saved => saved && saved.id === item.id
            && saved.selectorKey === item.selectorKey
            && saved._base_model_profile === item._base_model_profile);
        // Keep new fields only for an unambiguous identity. The reviewed draft
        // still controls changed values and which records remain in the list.
        return matches.length === 1 ? { ...matches[0], ...item } : item;
    });
    let status = initialStatus, config = currentConfig, etag = currentEtag;
    try {
        while (alive()) {
            if (status === 409) {
                pending("收藏已被其他窗口修改，正在读取最新版本。草稿保持不变。");
                const read = await wait(Promise.resolve().then(fetchLatest));
                if (!alive() || read.cancelled) return false;
                let latest;
                try {
                    if (read.error) throw read.error;
                    if (!read.value?.ok) throw new Error("HTTP " + (read.value?.status || 0));
                    const parsed = await wait(read.value.json());
                    if (!alive() || parsed.cancelled) return false;
                    if (parsed.error) throw parsed.error;
                    latest = parsed.value;
                    etag = read.value.headers.get("ETag");
                    if (!etag || !latest || typeof latest !== "object" || Array.isArray(latest)) throw new Error("最新版本无有效修订");
                } catch (error) {
                    if (!(await choose("读取最新收藏失败（" + error.message + "）。草稿仍保留。", "重新读取"))) return false;
                    continue;
                }
                config = { ...latest, [partition]: { ...latest[partition], ...draftSection,
                    groups: preserveNewFields(draftSection.groups, latest[partition]?.groups),
                    items: preserveNewFields(draftSection.items, latest[partition]?.items) } };
                pre.textContent = JSON.stringify({ 最新分区: latest[partition], 本地草稿: draftSection }, null, 2);
                details.hidden = false;
                const text = "当前分区：" + partition + "\n服务器：" + counts(latest[partition]) + "\n本地草稿：" + counts(draftSection) + "\n\n重新提交会用草稿替换本分区的分组和项目，覆盖该分区的并发修改。其他分区保留最新内容。请查看原文后决定。";
                if (!(await choose(text, "确认重新提交本分区"))) return false;
            } else {
                details.hidden = true;
                if (!(await choose("收藏保存失败，草稿仍保留。可重试本次保存；若上次请求已生效，将进入版本对照。", "重试保存"))) return false;
            }
            if (!alive()) return false;
            pending("正在保存收藏。已发送的请求无法撤回，请等待结果。");
            cancel.disabled = true;
            const result = await wait(Promise.resolve().then(() => submit(config, etag)));
            cancel.disabled = false;
            if (!alive() || result.cancelled) return false;
            if (result.value?.ok) { commit(config, result.value.etag || etag); return true; }
            status = result.value?.status || 0;
        }
        return false;
    } finally {
        observer?.disconnect(); overlay.remove(); activeRecovery = false;
    }
}

