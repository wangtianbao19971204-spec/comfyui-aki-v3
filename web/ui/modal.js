/**
 * @typedef {Object} ModalAction
 * @property {string} label
 * @property {(() => void | Promise<void>)=} onClick
 * @property {true=} default
 */

/**
 * @typedef {Object} CreateModalOptions
 * @property {string=} title
 * @property {number=} width
 * @property {HTMLElement | string=} body
 * @property {ModalAction[]=} actions
 */

/**
 * @typedef {Object} ModalHandles
 * @property {HTMLDivElement} overlay
 * @property {HTMLDivElement} modal
 * @property {HTMLDivElement} header
 * @property {HTMLDivElement} body
 * @property {HTMLDivElement} footer
 * @property {HTMLButtonElement} close
 * @property {() => void} cleanup
 */

let stylesInjected = false;

function injectStylesOnce() {
  if (stylesInjected) return;
  stylesInjected = true;

  const css = `
  .olm-modal__overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    display: flex; align-items: center; justify-content: center;
    z-index: 9999;
  }
  .olm-modal {
    background: var(--comfy-input-bg, #222);
    color: var(--input-text, #eee);
    border: 1px solid var(--border-color, #444);
    box-shadow: 0 10px 30px rgba(0,0,0,.4);
    border-radius: 8px;
    min-width: 320px; max-width: 720px; width: var(--olm-modal-w, 560px);
    max-height: 80vh; display: flex; flex-direction: column;
    overflow: hidden;
  }
  .olm-modal__header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 12px; border-bottom: 1px solid var(--border-color, #444);
    background: var(--comfy-menu-bg, #1a1a1a);
    font-weight: 600;
  }
  .olm-modal__title { margin: 0; font-size: 14px; }
  .olm-modal__close {
    border: none; background: transparent; color: inherit; cursor: pointer;
    font-size: 18px; line-height: 1; padding: 4px 6px;
  }
  .olm-modal__body {
    padding: 12px; overflow: auto; flex: 1;
  }
  .olm-modal__footer {
    display: flex; gap: 8px; justify-content: flex-end;
    padding: 10px 12px; border-top: 1px solid var(--border-color, #444);
    background: var(--comfy-menu-bg, #1a1a1a);
  }
  .olm-btn {
    border: 1px solid var(--border-color, #444);
    background: var(--comfy-input-bg, #2a2a2a);
    color: var(--input-text, #eee);
    padding: 6px 10px; border-radius: 6px; cursor: pointer; font-size: 12px;
  }
  .olm-btn:hover { filter: brightness(1.1); }
  .olm-badge {
    display:inline-block; padding:2px 6px; border-radius:999px; font-size:11px;
    background: var(--comfy-input-bg, #2a2a2a); border:1px solid var(--border-color,#444);
    margin-left: 6px;
  }
  .olm-pre {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px; background: var(--comfy-input-bg, #2a2a2a);
    padding: 10px; border-radius: 6px; border:1px solid var(--border-color, #444);
    white-space: pre-wrap; word-break: break-word;
  }
  .olm-row { display:flex; align-items:center; justify-content:space-between; gap:10px; }
  `;
  const style = document.createElement("style");
  style.id = "olm-modal-styles";
  style.textContent = css;

  (document.head ?? document.documentElement).appendChild(style);
}

/**
 * @param {CreateModalOptions=} opts
 * @returns {ModalHandles}
 */
function createModal(opts = {}) {
  injectStylesOnce();

  const {
    title = "Dialog",
    width = 560,
    body,
    actions = /** @type {ModalAction[]} */ ([]),
  } = opts;

  const overlay = /** @type {HTMLDivElement} */ (document.createElement("div"));
  overlay.className = "olm-modal__overlay";
  overlay.style.setProperty("--olm-modal-w", `${width}px`);

  const modal = /** @type {HTMLDivElement} */ (document.createElement("div"));
  modal.className = "olm-modal";
  overlay.appendChild(modal);

  const header = /** @type {HTMLDivElement} */ (document.createElement("div"));
  header.className = "olm-modal__header";

  const titleEl = document.createElement("div");
  titleEl.className = "olm-modal__title";
  titleEl.textContent = title;

  const close = /** @type {HTMLButtonElement} */ (
    document.createElement("button")
  );
  close.className = "olm-modal__close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";

  header.appendChild(titleEl);
  header.appendChild(close);

  const main = /** @type {HTMLDivElement} */ (document.createElement("div"));
  main.className = "olm-modal__body";

  if (body instanceof HTMLElement) {
    main.appendChild(body);
  } else if (typeof body === "string") {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = body;
    main.appendChild(wrapper);
  }

  const footer = /** @type {HTMLDivElement} */ (document.createElement("div"));
  footer.className = "olm-modal__footer";

  for (const a of actions) {
    const btn = /** @type {HTMLButtonElement} */ (
      document.createElement("button")
    );
    btn.className = "olm-btn";
    btn.textContent = a.label;
    btn.onclick = () => {
      a.onClick?.();
    };
    footer.appendChild(btn);
  }

  modal.appendChild(header);
  modal.appendChild(main);
  modal.appendChild(footer);

  function cleanup() {
    if (overlay.parentNode) {
      document.removeEventListener("keydown", onKey);
      overlay.remove();
    }
  }

  /** @param {KeyboardEvent} e */
  function onKey(e) {
    if (e.key === "Escape") {
      cleanup();
    }

    if (e.key === "Enter") {
      const def = actions.find((a) => a.default);
      def?.onClick?.();
    }
  }

  close.onclick = cleanup;
  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay) cleanup();
  });
  document.addEventListener("keydown", onKey);

  (document.body ?? document.documentElement).appendChild(overlay);
  close.focus();

  return { overlay, modal, header, body: main, footer, close, cleanup };
}

/**
 * @param {string} title
 * @param {unknown} obj
 * @param {{ width?: number }=} opts
 */
function showJSONModal(title, obj, { width = 700 } = {}) {
  const pre = document.createElement("pre");
  pre.className = "olm-pre";
  pre.textContent =
    typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);

  const { cleanup } = createModal({
    title,
    width,
    body: pre,
    actions: /** @type {ModalAction[]} */ ([
      {
        label: "Copy",
        onClick: async () => navigator.clipboard.writeText(pre.textContent),
      },
      { label: "Close", onClick: () => cleanup(), default: true },
    ]),
  });
}

/**
 * @param {string} title
 * @param {string} text
 * @param {{ width?: number }=} opts
 */
function showTextModal(title, text, { width = 600 } = {}) {
  const pre = document.createElement("pre");
  pre.className = "olm-pre";
  pre.textContent = text;
  const { cleanup } = createModal({
    title,
    width,
    body: pre,
    actions: /** @type {ModalAction[]} */ ([
      {
        label: "Copy",
        onClick: async () => navigator.clipboard.writeText(text),
      },
      { label: "Close", onClick: () => cleanup(), default: true },
    ]),
  });
}

export { createModal, showJSONModal, showTextModal };
