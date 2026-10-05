/** Lightweight logger owned by WeiLin Prompt Selector. */
const levelRank = { debug: 10, info: 20, warn: 30, error: 40 };

function configuredLevel() {
    try {
        const value = (localStorage.getItem('weilin_prompt_selector_log_level') || 'warn').toLowerCase();
        return levelRank[value] ?? levelRank.warn;
    } catch (_) {
        return levelRank.warn;
    }
}

export function createLogger(component) {
    const emit = (level, args) => {
        if (levelRank[level] < configuredLevel()) return;
        const fn = level === 'debug' ? 'debug' : level;
        (console[fn] || console.log)(`[WeiLin:${component}]`, ...args);
    };
    return {
        debug: (...args) => emit('debug', args),
        info: (...args) => emit('info', args),
        warn: (...args) => emit('warn', args),
        error: (...args) => emit('error', args),
    };
}
