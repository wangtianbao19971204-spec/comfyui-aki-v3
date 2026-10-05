const PAGE_SIZE = 80;

function addStyles() {
    if (document.getElementById('ps-paged-library-style')) return;
    const style = document.createElement('style');
    style.id = 'ps-paged-library-style';
    style.textContent = `
        .ps-paged-library{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;padding:18px;background:#090d18b8;color:#eef0fa;font:14px/1.45 system-ui,sans-serif}
        .ps-paged-panel{width:min(1060px,100%);max-height:calc(100vh - 36px);display:flex;flex-direction:column;min-width:0;background:#202530;border:1px solid #4b5366;border-radius:14px;box-shadow:0 22px 70px #0009;overflow:hidden}
        .ps-paged-header,.ps-paged-toolbar,.ps-paged-footer{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #3d4558;flex-wrap:wrap}
        .ps-paged-header h2{font-size:17px;margin:0;flex:1}.ps-paged-footer{border-top:1px solid #3d4558;border-bottom:0}
        .ps-paged-toolbar input,.ps-paged-toolbar select{box-sizing:border-box;min-height:36px;background:#161c27;color:#f4f5ff;border:1px solid #59637a;border-radius:8px;padding:6px 10px}
        .ps-paged-toolbar input{flex:2;min-width:180px}.ps-paged-toolbar select{flex:1;min-width:180px;max-width:360px}
        .ps-paged-library button{min-height:34px;background:#30394c;color:#f1f3ff;border:1px solid #56617a;border-radius:8px;padding:5px 11px;cursor:pointer}
        .ps-paged-library button:hover{background:#3b4760}.ps-paged-library button:disabled{opacity:.55;cursor:default}
        .ps-paged-library button:focus-visible,.ps-paged-library input:focus-visible,.ps-paged-library select:focus-visible,.ps-paged-row:focus-visible{outline:2px solid #a99bff;outline-offset:2px}
        .ps-paged-library .ps-paged-primary{background:#6752bb;border-color:#a99bff}.ps-paged-library .ps-paged-primary:hover{background:#7560cc}
        .ps-paged-list{overflow:auto;min-height:180px;flex:1;padding:8px 12px}.ps-paged-row{display:flex;align-items:flex-start;gap:10px;margin:5px 0;padding:10px;border:1px solid #414a60;border-radius:9px;background:#252c3a}
        .ps-paged-row input{margin-top:5px;accent-color:#937fff}.ps-paged-text{min-width:0;flex:1}.ps-paged-text strong{display:block;overflow-wrap:anywhere}
        .ps-paged-text small{color:#abb4ca}.ps-paged-excerpt{white-space:pre-wrap;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:#cbd2e2;margin-top:3px}
        .ps-paged-status{margin:0;min-height:20px;color:#c4cce0;flex:1}.ps-paged-count{white-space:nowrap}.ps-paged-review{padding:10px 16px;border-top:1px solid #3d4558;background:#181e29}
        .ps-paged-review[hidden]{display:none}.ps-paged-review pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:120px;overflow:auto;margin:6px 0 0}
        .ps-paged-editor{position:fixed;inset:0;z-index:2147483100;display:grid;place-items:center;padding:16px;background:#080d18c9;color:#eef0fa;font:14px/1.45 system-ui,sans-serif}
        .ps-paged-editor-panel{width:min(760px,100%);max-height:calc(100vh - 32px);overflow:auto;background:#202530;border:1px solid #69718b;border-radius:14px;padding:18px;box-shadow:0 24px 70px #000a}
        .ps-paged-editor-panel h3{margin:0 0 10px}.ps-paged-editor-panel label{display:block;margin:12px 0 4px;color:#cbd2e2}
        .ps-paged-editor-panel input,.ps-paged-editor-panel textarea{box-sizing:border-box;width:100%;background:#151b27;color:#f4f5ff;border:1px solid #67718a;border-radius:8px;padding:9px;font:inherit}
        .ps-paged-editor-panel textarea{min-height:160px;resize:vertical}.ps-paged-editor-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:14px}
        @media(max-width:700px){.ps-paged-library{padding:6px}.ps-paged-panel{max-height:calc(100vh - 12px)}.ps-paged-toolbar input,.ps-paged-toolbar select{max-width:none;width:100%;flex:auto}}
        @media(max-width:520px){.ps-paged-footer .ps-paged-status{flex:1 0 100%}}
    `;
    document.head.append(style);
}

function el(tag, className, label = '') {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = label;
    return element;
}

export async function openPagedPromptLibrary({node, request, manageModal, currentGraph, onApplied = () => {}}) {
    if (document.querySelector('.ps-library-modal,.ps-paged-library')) return;
    addStyles();
    const overlay = el('div', 'ps-paged-library');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', 'WeiLin 提示词词库');
    const panel = el('div', 'ps-paged-panel');
    const header = el('header', 'ps-paged-header');
    const title = el('h2', '', 'WeiLin 提示词词库');
    const manage = el('button', '', '分类与新增');
    const closeButton = el('button', '', '关闭');
    closeButton.setAttribute('aria-label', '关闭词库');
    header.append(title, manage, closeButton);
    const toolbar = el('div', 'ps-paged-toolbar');
    const search = el('input');
    search.type = 'search'; search.placeholder = '搜索名称、正文或标签'; search.setAttribute('aria-label', '搜索词库');
    const category = el('select'); category.setAttribute('aria-label', '词库分类');
    category.append(new Option('全部分类', ''));
    const selectVisible = el('button', '', '全选已显示');
    const clearSelection = el('button', '', '清除选择');
    toolbar.append(search, category, selectVisible, clearSelection);
    const list = el('div', 'ps-paged-list');
    list.setAttribute('role', 'list');
    const review = el('div', 'ps-paged-review'); review.hidden = true;
    const reviewTitle = el('strong', '', '将载入当前节点的完整提示词');
    const reviewBefore = el('pre'), reviewAfter = el('pre');
    review.append(reviewTitle, reviewBefore, reviewAfter);
    const footer = el('footer', 'ps-paged-footer');
    const status = el('p', 'ps-paged-status', '读取分类中…'); status.setAttribute('role', 'status');
    const count = el('span', 'ps-paged-count', '已显示 0 / 0 条');
    const more = el('button', '', '显示更多'); more.hidden = true;
    const retry = el('button', '', '重试读取'); retry.hidden = true;
    const apply = el('button', 'ps-paged-primary', '预览载入');
    const undo = el('button', '', '撤销本次载入'); undo.disabled = true;
    footer.append(status, count, more, retry, apply, undo);
    panel.append(header, toolbar, list, review, footer); overlay.append(panel);
    document.body.append(overlay);

    let disposed = false, serial = 0, timer = null, controller = null, revision = null, retryFromStart = false, retryIndex = false, retryPreferred = '';
    let shown = [], total = 0, selected = new Map(), selectionRevision = null, currentKey = '', pendingReview = null, lastWrite = null, indexData = null;
    const setStatus = message => { status.textContent = message; };
    const readError = (error, fallback) => /^(Failed to fetch|NetworkError|fetch failed)$/i.test(error?.message || '')
        ? '词库读取失败，请检查服务连接后重试。' : (error?.message || fallback);
    const showReadError = message => {retry.hidden = false; setStatus(message);};
    const clearReview = () => { pendingReview = null; review.hidden = true; apply.textContent = '预览载入'; };
    const release = manageModal(overlay, {initialFocus:search, onClose:() => close()});
    function close() {
        if (disposed) return;
        disposed = true; serial++; clearTimeout(timer); controller?.abort();
        overlay.remove(); release();
    }
    closeButton.onclick = close;
    overlay.addEventListener('click', event => {if (event.target === overlay) close();});
    async function json(path, signal) {
        const response = await request(path, {signal});
        if (!response.ok) throw new Error(`词库读取失败（HTTP ${response.status}）`);
        return response.json();
    }
    function refreshSelection() {
        clearReview();
        selectVisible.textContent = `全选已显示（${shown.length}）`;
        clearSelection.textContent = `清除选择（${selected.size}）`;
    }
    function renderRows(items) {
        const fragment = document.createDocumentFragment();
        for (const item of items) {
            const source = String(item._categoryId || item._categoryName || '');
            const key = JSON.stringify([source, String(item.id)]);
            const row = el('div', 'ps-paged-row'); row.tabIndex = 0; row.setAttribute('role', 'listitem');
            row.dataset.promptId = String(item.id); row.dataset.sourceCategory = String(item._categoryName || '');
            const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(key);
            checkbox.setAttribute('aria-label', `选择 ${String(item.alias || item.id)}`);
            const body = el('div', 'ps-paged-text');
            body.append(el('strong', '', String(item.alias || '未命名提示词')),
                el('small', '', String(item._categoryName || '未分类')),
                el('div', 'ps-paged-excerpt', String(item.prompt || '')));
            const favorite = el('button', '', item.favorite ? '取消收藏' : '收藏');
            favorite.setAttribute('aria-label', `${item.favorite ? '取消收藏' : '收藏'} ${String(item.alias || item.id)}`);
            const edit = el('button', '', '编辑'); edit.setAttribute('aria-label', `编辑 ${String(item.alias || item.id)}`);
            checkbox.onchange = () => {if (checkbox.checked) {selected.set(key, item); selectionRevision=revision;} else selected.delete(key); refreshSelection();};
            row.onkeydown = event => {
                if (event.target !== row || event.isComposing) return;
                const rows = [...list.querySelectorAll('.ps-paged-row')], index = rows.indexOf(row);
                if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); checkbox.click();}
                else if (event.key === 'ArrowDown') {event.preventDefault(); rows[Math.min(rows.length - 1, index + 1)]?.focus();}
                else if (event.key === 'ArrowUp') {event.preventDefault(); rows[Math.max(0, index - 1)]?.focus();}
                else if (event.key === 'Home') {event.preventDefault(); rows[0]?.focus();}
                else if (event.key === 'End') {event.preventDefault(); rows.at(-1)?.focus();}
            };
            favorite.onclick = () => void toggleFavorite(item, favorite);
            edit.onclick = () => void openEditor(item, edit);
            row.append(checkbox, body, favorite, edit); fragment.append(row);
        }
        list.append(fragment);
    }
    async function loadPage(reset = false) {
        if (disposed) return;
        const key = JSON.stringify([category.value, search.value.trim()]);
        if (reset && currentKey === key && shown.length) {list.inert = false; return;}
        if (reset) {currentKey = key; shown = []; total = 0; revision = null; list.replaceChildren(); refreshSelection();}
        const requestSerial = ++serial;
        controller?.abort(); controller = new AbortController();
        more.disabled = true; retry.hidden = true; retryFromStart = false; setStatus('读取提示词中…');
        try {
            const params = new URLSearchParams({limit:String(PAGE_SIZE), offset:String(shown.length)});
            if (category.value) params.set('category_id', category.value);
            if (search.value.trim()) params.set('q', search.value.trim());
            const page = await json(`/prompt_selector/library/prompts?${params}`, controller.signal);
            if (disposed || requestSerial !== serial) return;
            if (!Array.isArray(page.items) || page.offset !== shown.length) throw new Error('分页结果已变化，请重新搜索。');
            if (revision && revision !== page.last_modified) throw new Error('词库在浏览时更新，请重新搜索。');
            const selectionExpired = selected.size && selectionRevision && selectionRevision !== page.last_modified;
            if (selectionExpired) {selected.clear(); selectionRevision=null;}
            revision = page.last_modified; total = page.total;
            const existing = new Set(shown.map(item => JSON.stringify([item._categoryId || item._categoryName, item.id])));
            for (const item of page.items) {
                const itemKey = JSON.stringify([item._categoryId || item._categoryName, item.id]);
                if (existing.has(itemKey)) throw new Error('分页出现重复条目，请重新搜索。');
                existing.add(itemKey);
            }
            shown.push(...page.items); renderRows(page.items); refreshSelection();
            list.inert = false;
            count.textContent = `已显示 ${shown.length} / ${total} 条`;
            more.hidden = shown.length >= total; more.disabled = false;
            more.textContent = `显示更多（${Math.min(PAGE_SIZE, total - shown.length)} 条）`;
            setStatus(selectionExpired ? '词库已更新，旧选择已清除。' :
                total ? '勾选跨搜索保留；全选只作用于已显示条目。' : '没有匹配的提示词。');
        } catch (error) {
            if (disposed || requestSerial !== serial || error?.name === 'AbortError') return;
            retryFromStart = /分页结果已变化|词库在浏览时更新|分页出现重复条目/.test(error?.message || '');
            more.disabled = false; list.inert = false; showReadError(readError(error, '词库读取失败，请重试。'));
        }
    }
    async function refreshIndex(preferred = '') {
        retryPreferred = preferred;
        retryIndex = true;
        const index = await json('/prompt_selector/library/index');
        if (disposed) return;
        retryIndex = false;
        indexData = index;
        category.replaceChildren(new Option('全部分类', ''));
        for (const entry of index.categories || []) {
            if (!entry?.name || String(entry.id || '').startsWith('tagstr:')) continue;
            category.append(new Option(`${entry.name}（${entry.prompt_count || 0}）`, String(entry.id || entry.name)));
        }
        const chosen = index.categories?.find(entry => entry.name === preferred || String(entry.id) === preferred);
        if (chosen) category.value = String(chosen.id || chosen.name);
        currentKey = '';
        await loadPage(true);
    }
    function currentCategory() {
        return indexData?.categories?.find(entry => String(entry.id || entry.name) === category.value);
    }
    async function openCategoryManager() {
        if (!indexData || !revision) {setStatus('词库尚未就绪，请先重试读取。'); return;}
        const selectedCategory = currentCategory();
        const manager = el('div','ps-paged-editor'); manager.setAttribute('role','dialog');
        manager.setAttribute('aria-label','管理词库分类与新增词条');
        const form = el('div','ps-paged-editor-panel');
        form.append(el('h3','','分类与新增词条'), el('p','',selectedCategory ? `当前分类：${selectedCategory.name}` : '请选择具体分类后可改名、删除或新增词条。'));
        const categoryLabel=el('label','','分类名称'), categoryName=el('input','ps-paged-category-name');
        categoryName.value=selectedCategory?.name || ''; categoryLabel.append(categoryName);
        const categoryActions=el('div','ps-paged-editor-actions');
        const create=el('button','','新建分类'), rename=el('button','','重命名当前分类'), remove=el('button','','删除当前分类');
        rename.disabled=!selectedCategory; remove.disabled=!selectedCategory;
        categoryActions.append(create,rename,remove);
        const confirmBox=el('div',''); confirmBox.hidden=true;
        const branch=selectedCategory && (indexData?.categories||[]).filter(entry=>entry.name===selectedCategory.name||entry.name.startsWith(selectedCategory.name+'/'));
        const branchCount=(branch||[]).reduce((sum,entry)=>sum+Number(entry.prompt_count||0),0);
        const confirmLabel=el('label','',`删除将移除当前分类及子分类的 ${branchCount} 条词。输入完整分类名确认：`);
        const confirmName=el('input','ps-paged-confirm-name'); confirmLabel.append(confirmName); confirmBox.append(confirmLabel);
        const promptAliasLabel=el('label','','新增词条名称'), promptAlias=el('input','ps-paged-new-alias'); promptAliasLabel.append(promptAlias);
        const promptBodyLabel=el('label','','新增词条正文'), promptBody=el('textarea','ps-paged-new-body'); promptBodyLabel.append(promptBody);
        const promptDescriptionLabel=el('label','','新增词条说明'), promptDescription=el('textarea'); promptDescription.style.minHeight='76px'; promptDescriptionLabel.append(promptDescription);
        const note=el('p','ps-paged-status','每次只提交一条或一个分类；保存前会校验词库版本。'); note.setAttribute('role','status');
        const footerActions=el('div','ps-paged-editor-actions');
        const cancel=el('button','','关闭'), addPrompt=el('button','ps-paged-primary','新增词条'); addPrompt.disabled=!selectedCategory;
        footerActions.append(cancel,addPrompt);
        form.append(categoryLabel,categoryActions,confirmBox,promptAliasLabel,promptBodyLabel,promptDescriptionLabel,note,footerActions);
        manager.append(form); document.body.append(manager);
        const releaseManager=manageModal(manager,{initialFocus:categoryName,onClose:()=>closeManager()});
        let closed=false, busy=false, draftId=crypto.randomUUID();
        function closeManager(force=false){if(closed||(busy&&!force))return;closed=true;manager.remove();releaseManager();}
        cancel.onclick=()=>closeManager();
        manager.addEventListener('click',event=>{if(event.target===manager)closeManager();});
        async function submit(path,payload,preferred) {
            if(busy)return;
            busy=true; for(const button of [create,rename,remove,addPrompt])button.disabled=true;
            note.textContent='保存中…';
            try{
                const response=await request(path,{method:'POST',headers:{'Content-Type':'application/json','If-Match':revision},
                    body:JSON.stringify({...payload,base_revision:revision})});
                const result=await response.json();
                if(!response.ok||result.error)throw new Error(response.status===409?'词库已更新，草稿仍在；请重新打开对照后保存。':result.error||'保存失败。');
                selected.clear(); selectionRevision=null;
                closeManager(true);
                try {await refreshIndex(preferred); setStatus(retry.hidden ? '分类或词条已保存。' : '分类或词条已保存，但列表刷新失败；请重试读取。');}
                catch(error){showReadError(`已保存，但列表刷新失败：${error?.message || '请重试读取。'}`);}
                return true;
            }catch(error){note.textContent=error?.message||'保存失败，草稿仍在。';return false;}
            finally{busy=false;create.disabled=false;rename.disabled=!selectedCategory;remove.disabled=!selectedCategory;addPrompt.disabled=!selectedCategory;}
        }
        create.onclick=()=>{
            const name=categoryName.value.trim();
            if(!name){note.textContent='请输入新分类的完整路径。';return;}
            void submit('/prompt_selector/categories/create',{name},name);
        };
        rename.onclick=()=>{
            const name=categoryName.value.trim();
            if(!selectedCategory||!name||name===selectedCategory.name){note.textContent='请输入不同的分类名称。';return;}
            void submit('/prompt_selector/category/rename',{old_name:selectedCategory.name,new_name:name},name);
        };
        remove.onclick=()=>{
            if(!selectedCategory)return;
            if(confirmBox.hidden){confirmBox.hidden=false;confirmName.focus();return;}
            if(confirmName.value!==selectedCategory.name){note.textContent='分类名不一致，未删除任何内容。';return;}
            void submit('/prompt_selector/category/delete',{name:selectedCategory.name},'');
        };
        addPrompt.onclick=()=>{
            if(!selectedCategory||!promptAlias.value.trim()||!promptBody.value.trim()){note.textContent='请先选择分类并填写名称与正文。';return;}
            void submit('/prompt_selector/prompts/upsert',{mode:'create',target_category_id:selectedCategory.id,draft_id:draftId,
                prompt:{alias:promptAlias.value.trim(),prompt:promptBody.value.trim(),description:promptDescription.value.trim()}},selectedCategory.id);
        };
    }
    async function toggleFavorite(item, button) {
        if (!revision) return;
        button.disabled = true;
        try {
            const response = await request('/prompt_selector/prompts/toggle_favorite', {
                method:'POST',headers:{'Content-Type':'application/json','If-Match':revision},
                body:JSON.stringify({category_id:item._categoryId,prompt_id:item.id,favorite:!item.favorite,base_revision:revision})
            });
            const result = await response.json();
            if (!response.ok || result.error) throw new Error(response.status === 409 ? '词库已更新，请刷新后重新收藏。' : result.error || '收藏失败。');
            selected.clear(); selectionRevision=null;
            currentKey=''; await loadPage(true);
            setStatus(retry.hidden ? '收藏状态已保存。' : '收藏已保存，但列表刷新失败；请重试读取。');
        } catch (error) {setStatus(error?.message || '收藏失败，请重试。');}
        finally {button.disabled = false;}
    }
    async function openEditor(item, button) {
        if (document.querySelector('.ps-paged-editor')) return;
        button.disabled = true;
        const openedFrom = currentKey, openedRevision = revision;
        setStatus('读取原条目中…');
        try {
            const params = new URLSearchParams({prompt_id:String(item.id),category_id:String(item._categoryId)});
            const loaded = await json(`/prompt_selector/library/prompt?${params}`);
            if (disposed) return;
            if (currentKey !== openedFrom || revision !== openedRevision) {setStatus('列表已变化，请重新打开条目。'); return;}
            const source = loaded.category, original = loaded.prompt;
            if (!source || !original || String(original.id) !== String(item.id) || String(source.id) !== String(item._categoryId))
                throw new Error('原条目身份已变化，请刷新后重试。');
            const editor = el('div', 'ps-paged-editor'); editor.setAttribute('role','dialog');
            editor.setAttribute('aria-label',`编辑 ${String(original.alias || item.id)}`);
            const form = el('div','ps-paged-editor-panel');
            form.append(el('h3','',`编辑：${String(original.alias || item.id)}`),
                el('div','',`来源：${String(source.name || item._categoryName)} · ID：${String(original.id)}`));
            const aliasLabel=el('label','','名称'), alias=el('input'); alias.value=String(original.alias||'');
            const bodyLabel=el('label','','提示词正文'), body=el('textarea'); body.value=String(original.prompt||'');
            const descriptionLabel=el('label','','说明'), description=el('textarea'); description.value=String(original.description||''); description.style.minHeight='76px';
            aliasLabel.append(alias); bodyLabel.append(body); descriptionLabel.append(description);
            const note=el('p','ps-paged-status','仅保存这条资料的名称、正文和说明；其他字段保持原值。'); note.setAttribute('role','status');
            const actions=el('div','ps-paged-editor-actions');
            const cancel=el('button','','取消'), save=el('button','ps-paged-primary','保存这条');
            actions.append(cancel,save); form.append(aliasLabel,bodyLabel,descriptionLabel,note,actions); editor.append(form); document.body.append(editor);
            const releaseEditor=manageModal(editor,{initialFocus:alias,returnFocus:button,onClose:()=>closeEditor()});
            let closed=false;
            function closeEditor(){if(closed)return;closed=true;editor.remove();releaseEditor();}
            cancel.onclick=closeEditor;
            editor.addEventListener('click',event=>{if(event.target===editor)closeEditor();});
            save.onclick=async()=>{
                if(!alias.value.trim()||!body.value.trim()){note.textContent='名称与正文不能为空。';return;}
                save.disabled=true; note.textContent='保存中…';
                try{
                    const response=await request('/prompt_selector/prompts/upsert',{
                        method:'POST',headers:{'Content-Type':'application/json','If-Match':loaded.revision},
                        body:JSON.stringify({mode:'edit',target_category_id:source.id,base_revision:loaded.revision,
                            prompt:{...original,alias:alias.value.trim(),prompt:body.value.trim(),description:description.value.trim()}})
                    });
                    const result=await response.json();
                    if(!response.ok||result.error)throw new Error(response.status===409?'词库已更新，草稿仍在；请复制草稿并重新打开比较。':result.error||'保存失败。');
                    closeEditor(); selected.clear(); selectionRevision=null; currentKey='';
                    await loadPage(true);
                    setStatus(retry.hidden ? '已保存这条资料；来源分类与其他字段保持不变。' : '这条资料已保存，但列表刷新失败；请重试读取。');
                }catch(error){note.textContent=error?.message||'保存失败，草稿仍在。';}
                finally{save.disabled=false;}
            };
            setStatus('原条目编辑器已打开。');
        } catch (error) {setStatus(readError(error, '读取原条目失败。'));}
        finally {button.disabled = false;}
    }
    manage.onclick = () => void openCategoryManager();
    more.onclick = () => void loadPage();
    retry.onclick = async () => {
        try {
            if (retryIndex || !indexData) await refreshIndex(retryPreferred);
            else {
                if (retryFromStart) currentKey = '';
                await loadPage(retryFromStart || shown.length === 0);
            }
            if (!disposed && retry.hidden && overlay.isConnected) search.focus();
        } catch (error) {showReadError(readError(error, '无法读取词库分类。'));}
    };
    selectVisible.onclick = () => {for (const item of shown) selected.set(JSON.stringify([item._categoryId || item._categoryName, item.id]), item); selectionRevision=revision; for (const box of list.querySelectorAll('input[type=checkbox]')) box.checked = true; refreshSelection();};
    clearSelection.onclick = () => {selected.clear(); selectionRevision=null; for (const box of list.querySelectorAll('input[type=checkbox]')) box.checked = false; refreshSelection();};
    let composing = false;
    search.addEventListener('compositionstart', () => {composing = true; clearTimeout(timer);});
    search.addEventListener('compositionend', () => {composing = false; schedule();});
    search.addEventListener('input', event => {if (!composing && !event.isComposing) schedule();});
    search.addEventListener('keydown', event => {if (event.key === 'Escape' && search.value && !event.isComposing) {event.preventDefault(); event.stopPropagation(); search.value = ''; schedule();}});
    category.onchange = () => {serial++; controller?.abort(); list.inert = true; void loadPage(true);};
    function schedule() {clearTimeout(timer); serial++; controller?.abort(); list.inert = true; setStatus('搜索中…'); timer = setTimeout(() => void loadPage(true), 250);}
    function target() {
        const graph = currentGraph();
        const widget = node.widgets?.find(item => item.name === 'selected_prompts');
        if (!graph || graph.getNodeById?.(node.id) !== node || node.graph !== graph || !widget) throw new Error('目标节点已变化，请重新打开词库。');
        return widget;
    }
    apply.onclick = async () => {
        if (!selected.size) {setStatus('请先选择至少一条已显示的提示词。'); return;}
        const after = [...selected.values()].map(item => String(item.prompt || '')).filter(Boolean).join(', ');
        if (!after.trim()) {setStatus('所选提示词正文为空。'); return;}
        try {
            const widget = target(), before = String(widget.value || '');
            if (before === after) {clearReview(); setStatus('目标正文已是所选内容，无需重复载入。'); return;}
            if (!pendingReview || pendingReview.before !== before || pendingReview.after !== after || pendingReview.revision !== revision) {
                pendingReview = {before, after, revision};
                reviewBefore.textContent = `原文：\n${before || '（空）'}`;
                reviewAfter.textContent = `载入后：\n${after}`;
                review.hidden = false; apply.textContent = '确认载入';
                setStatus('请核对完整正文，再确认载入。'); return;
            }
            apply.disabled = true;
            const confirmed = pendingReview;
            const latest = await json('/prompt_selector/library/revision');
            if (disposed) return;
            if (pendingReview !== confirmed) {setStatus('选择或预览已变化，请重新确认当前预览。'); return;}
            if (latest.revision !== confirmed.revision) {clearReview(); setStatus('词库已更新，请刷新并重新核对。'); return;}
            if (String(target().value || '') !== confirmed.before) {clearReview(); setStatus('目标正文已变化，请重新预览。'); return;}
            const graph = currentGraph();
            const savedSelection = node.properties?.selectedPrompts;
            const savedWeights = node.properties?.promptWeights;
            node.loadPrompt({prompt:confirmed.after});
            if (String(target().value || '') !== confirmed.after) throw new Error('载入未完成，请回到节点核对。');
            node.properties.selectedPrompts = '{}';
            node.properties.promptWeights = '{}';
            lastWrite = {graph,before:confirmed.before,after:confirmed.after,savedSelection,savedWeights};
            undo.disabled = false; clearReview();
            try {onApplied(); setStatus('已载入当前节点；可撤销本次载入。');}
            catch {setStatus('已载入当前节点，可撤销；界面状态提示更新失败。');}
        } catch (error) {setStatus(error?.message || '载入失败。');}
        finally {apply.disabled = false;}
    };
    undo.onclick = () => {
        try {
            if (!lastWrite || currentGraph() !== lastWrite.graph || String(target().value || '') !== lastWrite.after) throw new Error('目标已变化，不能撤销旧操作。');
            node.loadPrompt({prompt:lastWrite.before});
            if (lastWrite.savedSelection === undefined) delete node.properties.selectedPrompts;
            else node.properties.selectedPrompts = lastWrite.savedSelection;
            if (lastWrite.savedWeights === undefined) delete node.properties.promptWeights;
            else node.properties.promptWeights = lastWrite.savedWeights;
            lastWrite = null; undo.disabled = true;
            try {onApplied(); setStatus('已撤销本次载入。');}
            catch {setStatus('已撤销本次载入；界面状态提示更新失败。');}
        } catch (error) {undo.disabled = true; setStatus(error.message);}
    };
    try {await refreshIndex(node.selectedCategory);}
    catch (error) {if (!disposed) showReadError(readError(error, '无法读取词库分类。'));}
}
