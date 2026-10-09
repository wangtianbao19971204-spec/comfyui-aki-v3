import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

async function request(path, options = {}) {
  const response = await api.fetchApi(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `编辑器请求失败（${response.status}）`);
  return data;
}

function notify(message) {
  app.extensionManager?.toast?.add({ severity: "warn", summary: "丝袜纹理", detail: message, life: 6000 });
}

async function projectHash(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
}

function hideProject(node) {
  const widget = node.widgets?.find(w => w.name === "project_json");
  if (!widget) return;
  widget.computeSize = () => [0, -4];
  widget.hidden = true;
  if (widget.element) widget.element.style.display = "none";
}

function writeProject(node, value) {
  const widget = node.widgets?.find(w => w.name === "project_json");
  if (!widget) throw new Error("找不到编辑数据，请重新加载工作流。");
  widget.value = value;
  if (widget.element) widget.element.value = value;
  widget.callback?.(value);
  node.setDirtyCanvas?.(true, true);
  app.graph?.change?.();
}

async function openStudio(node) {
  const state = node._stockingStudio;
  if (state.panel) { state.panel.focus(); return; }
  if (state.opening) return;
  const widget = node.widgets?.find(w => w.name === "project_json");
  if (node.inputs?.some(i => i.name === "project_json" && i.link != null)) {
    notify("编辑数据由上游连接提供，请先解除该连接再编辑。"); return;
  }
  let expected = widget?.value || "{}";
  let project;
  try { project = JSON.parse(expected); }
  catch { notify("编辑数据损坏，请恢复工作流或重新导入。"); return; }
  node.properties ??= {};
  node.properties.stockingStudioDraft ??= crypto.randomUUID().replaceAll("-", "");
  state.opening = true;
  let session;
  let expectedHash;
  try {
    expectedHash = await projectHash(expected);
    if (state.preview && state.previewFor === expectedHash) project = state.preview;
    if (node.inputs?.some(i => i.name === "image" && i.link != null) &&
        !(state.preview && state.previewFor === expectedHash)) {
      notify("请先运行一次节点，加载当前连接的原图后再编辑。"); return;
    }
    session = await request("/stocking_texture/studio", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, draft_id: node.properties.stockingStudioDraft, restore: true }),
    });
  } catch (error) { notify(error.message); return; }
  finally { state.opening = false; }
  if (node._stockingStudio !== state || !node.graph) {
    request(`/stocking_texture/studio/${session.session}/api/close`, { method: "POST" }).catch(() => {});
    return;
  }
  const dialog = document.createElement("dialog");
  dialog.style.cssText = "width:98vw;max-width:1900px;height:95vh;max-height:95vh;padding:0;border:1px solid #555;background:#2c2c2c;overflow:hidden;color:#ddd";
  const frame = document.createElement("iframe");
  frame.src = session.url;
  frame.title = "丝袜纹理完整编辑器";
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-downloads allow-modals allow-forms");
  frame.style.cssText = "border:0;width:100%;height:100%;display:block";
  dialog.append(frame);
  document.body.append(dialog);
  state.panel = dialog;
  let imageHash = project.image_sha256;
  const imageLink = node.inputs?.find(i => i.name === "image")?.link ?? null;
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    window.removeEventListener("message", receive);
    dialog.remove();
    if (state.panel === dialog) state.panel = null;
    state.close = null;
    request(`/stocking_texture/studio/${session.session}/api/close`, { method: "POST" }).catch(error => notify(error.message));
  };
  const receive = async event => {
    if (event.origin !== location.origin || event.source !== frame.contentWindow || event.data?.session !== session.session) return;
    if (event.data.type === "stocking-studio-close") { close(); return; }
    if (event.data.type !== "stocking-studio-apply") return;
    const reply = (ok, detail) => frame.contentWindow.postMessage({
      type: "stocking-studio-applied", session: session.session, ticket: event.data.ticket, ok, detail,
    }, location.origin);
    if (node._stockingStudio !== state || !node.graph || (widget.value || "{}") !== expected ||
        (node.inputs?.find(i => i.name === "image")?.link ?? null) !== imageLink ||
        node.inputs?.some(i => i.name === "project_json" && i.link != null) ||
        (imageHash && state.previewFor === expectedHash && state.preview?.image_sha256 && state.preview.image_sha256 !== imageHash)) {
      const message = "节点或输入图已改变。草稿已保留，请关闭并重新打开编辑器。";
      notify(message); reply(false, message); return;
    }
    if (node.inputs?.some(i => i.name === "image" && i.link != null) && event.data.project?.image_sha256 !== imageHash) {
      const message = "导入图与连接的原图不同。请断开 image 连线后重新打开，或导入相同原图的 PSD。";
      notify(message); reply(false, message); return;
    }
    try {
      const text = JSON.stringify(event.data.project);
      writeProject(node, text);
      expected = text;
      expectedHash = await projectHash(text);
      state.preview = event.data.project;
      state.previewFor = expectedHash;
      imageHash = event.data.project.image_sha256;
      await request(`/stocking_texture/studio/${session.session}/api/apply/ack`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket: event.data.ticket }),
      });
      reply(true);
    } catch (error) {
      notify(error.message); reply(false, error.message);
    }
  };
  state.close = close;
  window.addEventListener("message", receive);
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  dialog.showModal();
  if (session.restored) notify("已恢复上次尚未应用的编辑草稿。");
}

app.registerExtension({
  name: "local.StockingTextureStudio",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "StockingTextureStudio") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const value = created?.apply(this, arguments);
      this._stockingStudio = { panel: null, preview: null, previewFor: null, close: null, opening: false };
      this.serialize_widgets = true;
      this.addWidget("button", "打开完整编辑器", null, () => openStudio(this), { serialize: false });
      hideProject(this);
      return value;
    };
    const configured = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      this._stockingStudio?.close?.();
      if (this._stockingStudio) {
        this._stockingStudio.preview = null;
        this._stockingStudio.previewFor = null;
      }
      const result = configured?.apply(this, arguments);
      hideProject(this);
      return result;
    };
    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = executed?.apply(this, arguments);
      if (this._stockingStudio) {
        this._stockingStudio.preview = message?.stocking_studio?.[0]?.project || null;
        this._stockingStudio.previewFor = message?.stocking_studio?.[0]?.source_hash || null;
      }
      hideProject(this);
      return result;
    };
    const cloned = nodeType.prototype.onClone;
    nodeType.prototype.onClone = function () {
      const result = cloned?.apply(this, arguments);
      this.properties ??= {};
      this.properties.stockingStudioDraft = crypto.randomUUID().replaceAll("-", "");
      return result;
    };
    const removed = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      this._stockingStudio?.close?.();
      this._stockingStudio = null;
      return removed?.apply(this, arguments);
    };
  },
});
