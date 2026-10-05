const modelPages = new Set(['/loras', '/checkpoints', '/embeddings', '/loras/recipes', '/statistics']);

export function openModelSettings(section = 'general') {
    window.modalManager.showModal('settingsModal');
    const search = document.getElementById('settingsSearchClear');
    search?.click();
    const target = ['general', 'interface', 'library'].includes(section) ? section : 'general';
    document.querySelector(`.settings-nav-item[data-section="${target}"]`)?.click();
}

export function installWorkbenchPanel() {
    if (new URLSearchParams(location.search).get('uw_embed') !== '1' || window.parent === window) return;
    let owner;
    try { owner = window.parent.document.getElementById('unified-workbench'); } catch { return; }
    if (!owner || window.frameElement?.dataset.uw !== 'model-frame') return;
    const root = document.documentElement;
    root.classList.add('uw-model-panel');
    const style = document.createElement('link');
    style.rel = 'stylesheet';
    style.href = '/loras_static/css/workbench.css?v=20260928-variants';
    document.head.append(style);
    const sync = () => {
        root.dataset.density = owner.dataset.density;
        const theme = window.parent.getComputedStyle(owner);
        root.dataset.uwTheme = window.parent.document.documentElement.dataset.uwTheme || 'dark';
        root.dataset.theme = theme.getPropertyValue('--uw-scheme').trim() === 'light' ? 'light' : 'dark';
        document.body.dataset.theme = root.dataset.theme;
        for (const name of ['bg', 'panel', 'raised', 'input', 'sidebar', 'text', 'muted', 'border', 'border-strong', 'accent', 'accent-bg', 'accent-text', 'accent-strong', 'on-accent', 'danger', 'shadow', 'card-shadow', 'scheme', 'anime-header']) {
            const key = '--uw-' + name;
            root.style.setProperty(key, theme.getPropertyValue(key));
        }
    };
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(owner, { attributes: true, attributeFilter: ['data-density', 'style'] });
    observer.observe(window.parent.document.documentElement, { attributes: true, attributeFilter: ['data-uw-theme', 'class'] });
    const themeStyle = window.parent.document.getElementById('uw-studio-style');
    themeStyle?.addEventListener('load', sync);
    window.addEventListener('pagehide', () => { observer.disconnect(); themeStyle?.removeEventListener('load', sync); }, { once: true });
    document.addEventListener('click', event => {
        const link = event.target.closest('a[href]');
        if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target === '_blank' || link.hasAttribute('download')) return;
        const url = new URL(link.href, location.href);
        if (url.origin !== location.origin || !modelPages.has(url.pathname) || url.search || url.hash) return;
        event.preventDefault();
        window.parent.unifiedWorkbenchOpenProvider(url.pathname.slice(1));
    });
}
