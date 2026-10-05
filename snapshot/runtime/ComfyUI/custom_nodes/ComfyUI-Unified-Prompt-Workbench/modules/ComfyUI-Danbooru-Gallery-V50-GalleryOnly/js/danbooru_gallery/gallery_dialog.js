let dialogSequence = 0;

export function galleryDialogFocusables(dialog) {
    return [...dialog.querySelectorAll('button,input,select,textarea,a[href],summary,[tabindex],[contenteditable="true"]')].filter(item => {
        if (item.disabled || item.tabIndex < 0 || !item.getClientRects().length || item.closest('[hidden],[inert]')) return false;
        if (item.matches('input[type="radio"]') && item.name) {
            const checked = [...dialog.querySelectorAll('input[type="radio"]')].find(other => other.name === item.name && other.checked);
            if (checked && checked !== item) return false;
        }
        for (let parent = item; parent; parent = parent.parentElement) {
            const style = getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            if (parent.tagName === 'DETAILS' && !parent.open && !parent.querySelector('summary')?.contains(item)) return false;
            if (parent === dialog) break;
        }
        return true;
    });
}

export function mountGalleryDialog(dialog, { initialFocus, onClose, dialogs } = {}) {
    const previousFocus = document.activeElement;
    let closed = false;
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.tabIndex = -1;
    const heading = dialog.querySelector('h2');
    if (heading) {
        heading.id ||= `gallery-dialog-${++dialogSequence}-title`;
        dialog.setAttribute('aria-labelledby', heading.id);
    }
    dialog.unifiedFocus = () => {
        if (closed || !dialog.isConnected) return;
        const items = galleryDialogFocusables(dialog);
        (items.includes(initialFocus) ? initialFocus : items[0] || dialog).focus({ preventScroll: true });
    };
    dialog.unifiedClose = () => {
        if (closed) return;
        closed = true;
        const restore = dialog.contains(document.activeElement) || document.activeElement === document.body;
        dialogs?.delete(dialog);
        dialog.remove();
        onClose?.();
        if (restore && previousFocus?.isConnected && document.activeElement === document.body) previousFocus.focus({ preventScroll: true });
    };
    dialog.addEventListener('keydown', event => {
        if (event.defaultPrevented) return;
        if (event.isComposing || event.keyCode === 229) { event.stopPropagation(); return; }
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            dialog.unifiedClose();
        } else if (event.key === 'Tab') {
            const items = galleryDialogFocusables(dialog);
            if (!items.length || document.activeElement === dialog || document.activeElement === (event.shiftKey ? items[0] : items.at(-1))) {
                event.preventDefault();
                (event.shiftKey ? items.at(-1) : items[0])?.focus();
            }
            event.stopPropagation();
        }
    });
    for (const type of ['copy', 'cut', 'paste']) dialog.addEventListener(type, event => event.stopPropagation());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.unifiedClose(); });
    dialogs?.add(dialog);
    dialog.unifiedFocus();
}
