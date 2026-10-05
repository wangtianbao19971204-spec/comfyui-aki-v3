const sourceNames = {danbooru:'Danbooru',gelbooru:'Gelbooru',civitai:'Civitai.red',yandere:'Yande.re'};

export function galleryErrorGuidance(error, source) {
    const name = sourceNames[source] || '当前来源';
    const code = error?.code || error?.reasonCode || '';
    const status = Number(error?.httpStatus);
    if (code === 'local_favorites_unavailable') return {message:`${name} 暂不支持收藏视图。可以继续浏览或搜索，或切换到支持收藏的来源。`,action:'browse'};
    if (code.startsWith('auth_') || status === 401) return {message:`${name} 的登录信息未配置或已失效。请检查该来源的账号设置，保存后再重试。`,action:'settings'};
    if (status === 403) return {message:`${name} 拒绝了这次访问。请检查账号权限及来源设置；也可以切换来源继续浏览。`,action:'settings'};
    if (status === 429 || code === 'rate_limited') {
        const seconds = Number(error?.retryAfterSeconds);
        const wait = Number.isFinite(seconds) && seconds > 0 ? `请等待 ${Math.ceil(seconds)} 秒后重试。` : '请稍后重试。';
        return {message:`${name} 暂时限制了请求频率。${wait}`,action:'retry'};
    }
    if (code === 'unsupported' || code.endsWith('_unavailable') || code === 'not_supported') return {message:`${name} 暂不提供这项功能。可以返回浏览，或切换其他来源。`,action:'browse'};
    if (status >= 500 || code === 'network_error' || code === 'timeout' || code === 'upstream_timeout') return {message:`${name} 暂时没有响应。请稍后重试；已有选择仍然保留。`,action:'retry'};
    return {message:`暂时无法读取 ${name} 的内容。可以重试或切换来源；原始错误保留在下方详情中。`,action:'retry'};
}
