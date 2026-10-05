const storageKey = 'uw-ui-theme';
const themes = {light: '☼ 白天', dark: '☾ 夜间', anime: '✦ 多色'};
let installed = false;

export function getUiTheme() {
    const value = document.documentElement.dataset.uwTheme;
    return Object.hasOwn(themes, value) ? value : 'dark';
}

function applyTheme(value) {
    const theme = Object.hasOwn(themes, value) ? value : 'dark';
    const changed=document.documentElement.dataset.uwTheme!==theme;
    document.documentElement.dataset.uwTheme = theme;
    for (const picker of document.querySelectorAll('[data-uw-theme-toggle]')) {
        picker.value = theme;
        picker.title = '晴空手帖 · ' + themes[theme] + (theme === 'anime' ? ' · 明暗跟随工作流' : ' · 同一套插画与布局');
    }
    if(changed)window.dispatchEvent(new CustomEvent('uw-theme-change',{detail:{theme}}));
}

export function setUiTheme(value) {
    if (!Object.hasOwn(themes, value)) return;
    applyTheme(value);
    try { localStorage.setItem(storageKey, value); } catch { /* Session switching still works when storage is unavailable. */ }
}

export function installUiTheme() {
    if (installed) return;
    installed = true;
    let saved;
    try { saved = localStorage.getItem(storageKey); } catch { /* Use the default in restricted storage contexts. */ }
    applyTheme(saved);
    if (!document.getElementById('uw-studio-style')) {
        const style = document.createElement('link');
        style.id = 'uw-studio-style'; style.rel = 'stylesheet';
        style.href = '/extensions/ComfyUI-Unified-Prompt-Workbench/studio.css?v=20261005-stickers';
        document.head.append(style);
    }
    window.addEventListener('storage', event => {
        if (event.key === storageKey || event.key === null) applyTheme(event.newValue);
    });
}

export function mountThemeToggle(parent) {
    installUiTheme();
    const picker = document.createElement('select');
    picker.className = 'uw-theme-toggle';
    picker.dataset.uwThemeToggle = '';
    picker.setAttribute('aria-label', '界面主题');
    for (const [value, label] of Object.entries(themes)) {
        const option = document.createElement('option');
        option.value = value; option.textContent = label; picker.append(option);
    }
    picker.onchange = () => setUiTheme(picker.value);
    parent.append(picker);
    applyTheme(getUiTheme());
    return picker;
}
