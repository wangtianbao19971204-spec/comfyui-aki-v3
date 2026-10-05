export function browserTarget(search = window.location.search) {
  const params = new URLSearchParams(search);
  return { key: params.get('lm_target'), token: params.get('lm_token'), label: params.get('lm_label') };
}

export function filterBrowserTargets(nodes, target = browserTarget()) {
  if (!target.key) return nodes;
  return Object.fromEntries(Object.entries(nodes).filter(([key, node]) =>
    (node.unique_id || key) === target.key &&
    !!target.token && node.capabilities?.target_token === target.token));
}

function showTargetLabel() {
  const target = browserTarget();
  if (!target.key || document.getElementById('lm-workflow-target')) return;
  const badge = document.createElement('div');
  badge.id = 'lm-workflow-target';
  badge.setAttribute('role', 'status');
  badge.textContent = `写入目标：${target.label || target.key} · 发送只写入此栏`;
  badge.style.cssText = 'position:fixed;bottom:12px;left:50%;transform:translateX(-50%);z-index:9000;max-width:85vw;padding:8px 14px;border:1px solid #5c8597;border-radius:6px;background:#172a35;color:#d9f1fa;font:13px system-ui;pointer-events:none';
  document.body.appendChild(badge);
  // Keep the selected workflow slot when switching between LoRAs and recipes.
  for (const link of document.querySelectorAll('a[href]')) {
    const url = new URL(link.href, window.location.origin);
    if (url.origin !== window.location.origin || !['/loras', '/loras/recipes'].includes(url.pathname)) continue;
    for (const [key, value] of new URLSearchParams(window.location.search)) {
      if (['lm_target', 'lm_token', 'lm_label', 'lm_folder'].includes(key)) url.searchParams.set(key, value);
    }
    link.href = url.href;
  }
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', showTargetLabel, { once: true });
else showTargetLabel();
