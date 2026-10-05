function ensureContainer() {
    let container = document.getElementById('weilin-prompt-selector-toast-container');
    if (container) return container;
    container = document.createElement('div');
    container.id = 'weilin-prompt-selector-toast-container';
    container.style.cssText = [
        'position:fixed', 'top:20px', 'left:50%', 'transform:translateX(-50%)',
        'z-index:1000000', 'display:flex', 'flex-direction:column', 'gap:8px',
        'align-items:center', 'pointer-events:none'
    ].join(';');
    (document.body || document.documentElement).appendChild(container);
    return container;
}

class PromptSelectorToastManager {
    showToast(message, type = 'info', duration = 3000) {
        const item = document.createElement('div');
        const palette = {
            success: ['#183d2b', '#7ee2a8'],
            error: ['#4a2026', '#ff9aa7'],
            warning: ['#463718', '#ffd479'],
            info: ['#202d49', '#a8c7ff'],
        };
        const [background, foreground] = palette[type] || palette.info;
        item.textContent = String(message ?? '');
        item.style.cssText = [
            `background:${background}`, `color:${foreground}`, 'border:1px solid currentColor',
            'border-radius:8px', 'padding:9px 14px', 'max-width:620px',
            'box-shadow:0 6px 20px rgba(0,0,0,.35)', 'font-size:13px',
            'pointer-events:auto', 'opacity:0', 'transform:translateY(-6px)',
            'transition:opacity .18s ease, transform .18s ease'
        ].join(';');
        ensureContainer().appendChild(item);
        requestAnimationFrame(() => {
            item.style.opacity = '1';
            item.style.transform = 'translateY(0)';
        });
        const close = () => {
            item.style.opacity = '0';
            item.style.transform = 'translateY(-6px)';
            setTimeout(() => item.remove(), 220);
        };
        item.addEventListener('click', close);
        setTimeout(close, Math.max(800, Number(duration) || 3000));
        return item;
    }
}

export const globalToastManager = new PromptSelectorToastManager();
export const toastManagerProxy = globalToastManager;
