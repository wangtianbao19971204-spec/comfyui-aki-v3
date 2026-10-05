import { promptSelectorTranslations } from '../translations/prompt_selector_translations.js';

class PromptSelectorLanguageManager {
    constructor() {
        this.storageKey = 'weilin_prompt_selector_language';
        this.currentLanguage = 'zh';
        try {
            const saved = localStorage.getItem(this.storageKey) || localStorage.getItem('comfyui_global_language');
            if (saved === 'en' || saved === 'zh') this.currentLanguage = saved;
        } catch (_) {}
    }

    getLanguage() { return this.currentLanguage; }

    setLanguage(language, silent = false) {
        const normalized = String(language).toLowerCase().startsWith('en') ? 'en' : 'zh';
        const changed = normalized !== this.currentLanguage;
        this.currentLanguage = normalized;
        try { localStorage.setItem(this.storageKey, normalized); } catch (_) {}
        if (changed && !silent) {
            document.dispatchEvent(new CustomEvent('languageChanged', { detail: { language: normalized } }));
        }
        return changed;
    }

    t(key) {
        const actual = String(key || '').replace(/^prompt_selector\./, '');
        const table = promptSelectorTranslations[this.currentLanguage] || promptSelectorTranslations.zh || {};
        return actual.split('.').reduce((value, part) => value && value[part], table) || key;
    }
}

export const globalMultiLanguageManager = new PromptSelectorLanguageManager();
