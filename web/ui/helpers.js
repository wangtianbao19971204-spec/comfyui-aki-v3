/** @ts-ignore */
/** @param {import("../../scripts/app.js").app.nodeType} node */
export function getWidget(node, name) {
  return node.widgets?.find((w) => w.name === name);
}

/** @ts-ignore */
/** @param {import("../../scripts/app.js").app.nodeType} node */
export function refresh(node) {
  node.setDirtyCanvas(true, true);
}

/**
 * @template {keyof HTMLElementTagNameMap} K
 * @param {K} tag
 * @param {Record<string,string>=} attrs
 * @returns {HTMLElementTagNameMap[K]}
 */
export function el(tag, attrs) {
  const n = /** @type {HTMLElementTagNameMap[K]} */ (
    document.createElement(tag)
  );
  if (attrs) Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
  return n;
}
