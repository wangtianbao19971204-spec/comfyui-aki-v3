/**
 * Anima Tools - 共享图片加载优化工具
 * 将受支持的远程预览图转到本地持久缓存，并保留会话内加载标记
 */

// 全局已加载图片 URL 缓存（跨弹窗共享，浏览器会话内有效）
if (!window._animaLoadedImageUrls) {
    window._animaLoadedImageUrls = new Set();
}

const PERSISTENT_IMAGE_HOSTS = new Set([
    "blobs.animadex.net",
    "cdn.jsdelivr.net",
    "cdn.statically.io",
    "fastly.jsdelivr.net",
    "raw.githubusercontent.com",
]);

export function getPersistentImageUrl(url) {
    if (!url || typeof url !== "string") return url;
    try {
        const parsed = new URL(url, window.location.href);
        if (parsed.protocol !== "https:" || !PERSISTENT_IMAGE_HOSTS.has(parsed.hostname.toLowerCase())) {
            return url;
        }
        return `/anima-tools/image-cache?url=${encodeURIComponent(parsed.href)}`;
    } catch {
        return url;
    }
}

/**
 * 标记 URL 已成功加载
 */
export function markImageLoaded(url) {
    if (url && !url.startsWith("data:")) {
        window._animaLoadedImageUrls.add(url);
        // 控制缓存大小，防止内存泄漏
        if (window._animaLoadedImageUrls.size > 2000) {
            const first = window._animaLoadedImageUrls.values().next().value;
            window._animaLoadedImageUrls.delete(first);
        }
    }
}

/**
 * 检查 URL 是否已加载过
 */
export function isImageLoaded(url) {
    return url && window._animaLoadedImageUrls.has(url);
}

/**
 * 清空会话内图片已加载标记；不会影响浏览器磁盘缓存或任何用户配置
 */
export function clearImageLoadedCache() {
    if (window._animaLoadedImageUrls?.clear) {
        window._animaLoadedImageUrls.clear();
    }
}
