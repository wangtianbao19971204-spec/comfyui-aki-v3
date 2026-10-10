import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { EditorModel, parseGuides, nearestLine } from "./editor_model.js";

const COLORS = ["#70c5ff", "#ff91bf", "#bba0ff", "#80e0b1", "#ffd17c", "#efacff"];
const WIDGET_LABELS = {
  guides_json: ["引导数据 JSON", "由引导编辑器保存；也可连接引导编辑节点的 STRING 输出。已有坐标与参考尺寸绑定。"],
  style: ["纹理样式", "细线、针织、斜单线、加濑风或试验油光。"],
  density: ["织纹密度 (%)", "密度越高纹理越细；过密区域会自动减弱以抑制摩尔纹。"],
  strength: ["纹理强度 (%)", "手动调节会关闭自动强度；亮点由各亮点参数单独控制。"],
  dark_adapt: ["暗部织纹适配", "增强细线、针织和斜单线在暗色布料上的可见度，保留抗摩尔纹；关闭可对照原版。纯黑仍保持黑色。"],
  auto_strength: ["自动纹理强度", "根据部位颜色调整强度，减少浅色丝袜上的过强纹理。"],
  tilt: ["斜线角度 (°)", "只影响斜单线样式，左右方向由部位名称与位置决定。"],
  sparkle_bright: ["按亮部加亮点 (%)", "根据图像的明亮区域分布亮点，不需要深度模型。"],
  sparkle_even: ["均匀亮点 (%)", "在纹理区域内均匀分布亮点，0 表示关闭。"],
  sparkle_depth: ["按深度加亮点 (%)", "非零时必须接入与原图等大的灰度深度 IMAGE。"],
  color_exclude: ["颜色排除", "排除偏离部位主体颜色的像素；透肤或肤色丝袜可尝试关闭。"],
  auto_walls: ["深度自动隔开", "根据深度图寻找前后重叠边界；开启时必须接入 depth。手画隔开线始终生效。"],
  depth_mode: ["深度方向", "与输入深度图的近处亮暗方向一致。"],
  seed: ["亮点种子", "固定种子可复现亮点与颗粒；与生成模型的采样种子无关。"],
};
const TOOL_HINTS = {
  polygon: "圈选：依次点击各顶点，双击或 Enter 完成。可以为同一部位圈多块；Esc 撤销未完成的圈选。",
  stroke: "走向：按住左键画线，线的方向决定横向织纹。每个独立部位至少画一条走向线。",
  divider: "隔开：按住左键画线，隔开前后重叠的同一部位。隔开线对经过的所有部位生效。",
  delete: "删除线：点击当前部位的走向线或任意隔开线。删除后可撤销。",
  pan: "移动：按住拖动画布。滚轮滚动；Ctrl / ⌘ + 滚轮缩放。",
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(text, action, className) {
  const node = element("button", className, text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function style() {
  if (document.getElementById("stocking-texture-editor-style")) return;
  const link = document.createElement("link");
  link.id = "stocking-texture-editor-style";
  link.rel = "stylesheet";
  link.href = new URL("./stocking_texture.css", import.meta.url).href;
  document.head.appendChild(link);
}

function viewURL(file) {
  if (!file?.filename || !["input", "output", "temp"].includes(file.type || "temp")) {
    throw new Error("节点尚未返回可读取的预览图像。");
  }
  const query = new URLSearchParams({
    filename: file.filename,
    subfolder: file.subfolder || "",
    type: file.type || "temp",
    rand: String(Date.now()),
  });
  return api.apiURL(`/view?${query}`);
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("预览图像读取失败。请重新运行引导节点，再打开编辑器。"));
    img.src = viewURL(file);
  });
}

function writeGuides(node, value) {
  const widget = node.widgets?.find((w) => w.name === "guides_json");
  if (!widget) throw new Error("找不到 guides_json 输入，无法保存引导。");
  widget.value = value;
  const input = widget.element ?? widget.inputEl;
  if (input) input.value = value;
  widget.callback?.call(widget, value);
  node.graph?.change();
  node.setDirtyCanvas?.(true, true);
}

function path(ctx, points, close = false) {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(...points[0]);
  for (let i = 1; i < points.length; i++) ctx.lineTo(...points[i]);
  if (close) ctx.closePath();
}

class GuidesPanel {
  constructor(node) {
    this.node = node;
    this.preview = node._stockingTexture.preview;
    this.closed = false;
    this.stale = false;
    this.tool = "stroke";
    this.zoom = 1;
    this.draft = null;
    this.hover = null;
    this.drag = null;
    this.dialog = element("dialog", "stocking-editor");
    this.dialog.setAttribute("aria-label", "丝袜引导编辑器");
    this.shell = element("div", "stocking-shell");
    this.dialog.append(this.shell);
    this.dialog.addEventListener("close", () => this.cleanup());
    this.dialog.addEventListener("cancel", (event) => {
      if (this.draft) { event.preventDefault(); this.discardDraft(); }
    });
    this.dialog.addEventListener("keydown", (event) => this.keydown(event));
    for (const type of ["pointerdown", "pointerup", "click", "dblclick"]) {
      this.dialog.addEventListener(type, (event) => event.stopPropagation());
    }
    document.body.appendChild(this.dialog);
    this.dialog.showModal();
    this.ready = this.open();
  }

  async open() {
    const loading = element("div", "stocking-loading");
    const message = element("p", "", "正在读取图像…");
    loading.append(element("h2", "", "丝袜引导编辑器"), message,
      button("关闭", () => this.close()));
    this.shell.append(loading);
    try {
      if (this.node.inputs?.some((input) => input.name === "guides_json" && input.link != null)) {
        throw new Error("guides_json 当前连接了其他节点。请先断开该连接，再在此节点编辑；连接输入时将使用上游数据。");
      }
      if (!this.preview) {
        throw new Error("首次接图后，请先运行一次 StockingTextureGuides 节点，再点击“编辑丝袜引导”。已保存的引导保留在 guides_json 中。");
      }
      this.image = await loadImage(this.preview.image);
      if (this.closed) return;
      if (this.stale) throw new Error("节点预览已更新，请关闭后重新打开编辑器。");
      const { width, height } = this.preview;
      if (this.image.naturalWidth !== width || this.image.naturalHeight !== height) {
        throw new Error("预览尺寸与节点回执不同，请重新运行此节点后再编辑。");
      }
      const widget = this.node.widgets?.find((w) => w.name === "guides_json");
      const data = parseGuides(widget?.value, width, height);
      if (!data.regions.length) {
        data.regions.push({ id: "left", name: "左腿", polygons: [], strokes: [] });
      }
      this.model = new EditorModel(data);
      this.width = width;
      this.height = height;
      if (this.preview.hasMask && this.preview.mask) {
        const mask = await loadImage(this.preview.mask);
        if (this.closed) return;
        if (this.stale) throw new Error("节点预览已更新，请关闭后重新打开编辑器。");
        if (mask.naturalWidth !== width || mask.naturalHeight !== height) {
          throw new Error("外接蒙版尺寸与图像不同，请修正输入后重新运行。");
        }
        this.maskOverlay = this.makeMaskOverlay(mask);
      }
      if (this.closed) return;
      loading.remove();
      this.build();
      this.update();
      this.resizeObserver = new ResizeObserver(() => {
        if (this.fitMode) this.fit();
      });
      this.resizeObserver.observe(this.canvasArea);
      requestAnimationFrame(() => {
        if (this.closed) return;
        this.fit();
        this.canvas.focus();
      });
    } catch (error) {
      if (!this.closed) message.textContent = error.message;
    }
  }

  makeMaskOverlay(image) {
    const overlay = document.createElement("canvas");
    overlay.width = this.width;
    overlay.height = this.height;
    const ctx = overlay.getContext("2d");
    ctx.drawImage(image, 0, 0);
    const data = ctx.getImageData(0, 0, this.width, this.height);
    for (let i = 0; i < data.data.length; i += 4) {
      const amount = data.data[i];
      data.data[i] = 255;
      data.data[i + 1] = 198;
      data.data[i + 2] = 71;
      data.data[i + 3] = Math.round(amount * 0.22);
    }
    ctx.putImageData(data, 0, 0);
    return overlay;
  }

  build() {
    const heading = element("header", "stocking-heading");
    heading.append(element("h2", "", "丝袜引导编辑器"),
      element("p", "", `${this.width} × ${this.height} · 先圈选部位，再画织纹走向。保存后运行节点应用到图像。`));
    const body = element("div", "stocking-body");
    this.sidebar = element("aside", "stocking-sidebar");
    this.regionList = element("div", "stocking-region-list");
    this.regionList.setAttribute("aria-label", "部位列表");
    const regionActions = element("div", "stocking-row");
    this.deleteRegionButton = button("删除部位", () => this.perform(() => this.model.deleteRegion()));
    regionActions.append(button("新增部位", () => this.perform(() => this.model.addRegion())), this.deleteRegionButton);
    const nameLabel = element("label", "stocking-name", "部位名称");
    this.nameInput = element("input");
    this.nameInput.type = "text";
    this.nameInput.maxLength = 80;
    this.nameInput.setAttribute("aria-label", "部位名称");
    this.nameInput.addEventListener("change", () => this.perform(() => this.model.renameRegion(this.nameInput.value)));
    nameLabel.append(this.nameInput);
    this.regionInfo = element("p", "stocking-description");
    this.warning = element("p", "stocking-description stocking-warning");
    const clearActions = element("div", "stocking-row");
    this.clearPolygons = button("清空圈选", () => this.perform(() => this.model.clearRegion("polygons")));
    this.clearStrokes = button("清空走向", () => this.perform(() => this.model.clearRegion("strokes")));
    clearActions.append(this.clearPolygons, this.clearStrokes);
    const maskLabel = element("label", "stocking-mask-toggle");
    this.showMask = element("input");
    this.showMask.type = "checkbox";
    this.showMask.checked = true;
    this.showMask.disabled = !this.maskOverlay;
    this.showMask.addEventListener("change", () => this.render());
    maskLabel.append(this.showMask, document.createTextNode("显示外接蒙版（黄色）"));
    this.sidebar.append(element("h3", "", "部位"), this.regionList, regionActions, nameLabel,
      this.regionInfo, clearActions, maskLabel, this.warning,
      element("p", "stocking-description", "无圈选时使用外接蒙版。圈选可包含多块；部位按列表顺序处理，重叠处归后面的部位。名称中的“左 / 右”影响斜线纹理方向。"));
    const main = element("main", "stocking-main");
    const toolbar = element("div", "stocking-toolbar");
    this.toolButtons = new Map();
    for (const [tool, label] of [["polygon", "圈选"], ["stroke", "走向"], ["divider", "隔开"], ["delete", "删除线"], ["pan", "移动"]]) {
      const item = button(label, () => {
        this.discardDraft();
        this.tool = tool;
        this.update();
      });
      item.title = TOOL_HINTS[tool];
      this.toolButtons.set(tool, item);
      toolbar.append(item);
    }
    toolbar.append(element("span", "stocking-divider"));
    this.undoButton = button("撤销", () => this.perform(() => this.model.undo()));
    this.redoButton = button("重做", () => this.perform(() => this.model.redo()));
    toolbar.append(this.undoButton, this.redoButton, element("span", "stocking-divider"),
      button("适应", () => this.fit()), button("−", () => this.setZoom(this.zoom / 1.25)));
    this.zoomLabel = element("span", "stocking-zoom");
    toolbar.append(this.zoomLabel, button("+", () => this.setZoom(this.zoom * 1.25)),
      button("100%", () => this.setZoom(1)));
    this.canvasArea = element("div", "stocking-canvas-area");
    const wrap = element("div", "stocking-canvas-wrap");
    this.canvas = element("canvas", "stocking-canvas");
    this.canvas.width = this.width;
    this.canvas.height = this.height;
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute("aria-label", "圈选部位并绘制走向的图像画布");
    this.ctx = this.canvas.getContext("2d");
    wrap.append(this.canvas);
    this.canvasArea.append(wrap);
    this.hint = element("p", "stocking-hint");
    main.append(toolbar, this.canvasArea, this.hint);
    body.append(this.sidebar, main);
    const footer = element("footer", "stocking-footer");
    this.status = element("p", "stocking-status", "编辑内容在点击保存前不会写入节点。");
    this.status.setAttribute("role", "status");
    this.saveButton = button("保存引导", () => this.save(), "stocking-save");
    footer.append(this.status, button("取消", () => this.close()), this.saveButton);
    this.shell.append(heading, body, footer);
    this.canvas.addEventListener("pointerdown", (event) => this.pointerDown(event));
    this.canvas.addEventListener("pointermove", (event) => this.pointerMove(event));
    this.canvas.addEventListener("pointerup", (event) => this.pointerUp(event));
    this.canvas.addEventListener("pointercancel", () => this.discardDraft());
    this.canvas.addEventListener("click", (event) => this.click(event));
    this.canvas.addEventListener("dblclick", (event) => {
      if (this.tool === "polygon") { event.preventDefault(); this.finishPolygon(); }
    });
    this.canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    this.canvasArea.addEventListener("wheel", (event) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      this.setZoom(this.zoom * (event.deltaY < 0 ? 1.15 : 1 / 1.15), event.clientX, event.clientY);
    }, { passive: false });
  }

  perform(action) {
    if (this.stale) return;
    this.discardDraft();
    try {
      const changed = action();
      this.update();
      if (changed) this.status.textContent = "引导已修改，点击“保存引导”写入节点。";
    } catch (error) {
      this.status.textContent = error.message;
      this.update();
    }
  }

  update() {
    if (!this.model || this.closed) return;
    this.regionList.replaceChildren();
    const regions = this.model.document.regions;
    regions.forEach((region, index) => {
      const item = button("", () => {
        this.discardDraft(); this.model.select(region.id); this.update();
      });
      item.setAttribute("aria-pressed", String(region.id === this.model.selectedId));
      const dot = element("span", "stocking-dot");
      dot.style.backgroundColor = COLORS[index % COLORS.length];
      item.append(dot, element("span", "", region.name));
      this.regionList.append(item);
    });
    const selected = this.model.region;
    this.nameInput.value = selected?.name ?? "";
    this.nameInput.disabled = !selected || this.stale;
    this.deleteRegionButton.disabled = !selected || this.stale;
    this.clearPolygons.disabled = !selected?.polygons.length || this.stale;
    this.clearStrokes.disabled = !selected?.strokes.length || this.stale;
    this.regionInfo.textContent = selected ?
      `${selected.polygons.length ? `${selected.polygons.length} 块圈选` : "使用外接蒙版"} · ${selected.strokes.length} 条走向线` : "请新增一个部位。";
    const unpartitioned = regions.filter((r) => !r.polygons.length).length;
    this.warning.textContent = unpartitioned > 1 ?
      "多个部位都未圈选，将使用同一外接蒙版；重叠处归后面的部位。请用圈选分开左右腿。" :
      (!this.preview.hasMask && unpartitioned ? "当前没有外接蒙版，请圈选纹理部位。" : "");
    this.undoButton.disabled = !this.model.undoStack.length || this.stale;
    this.redoButton.disabled = !this.model.redoStack.length || this.stale;
    this.saveButton.disabled = this.stale;
    for (const [tool, item] of this.toolButtons) item.setAttribute("aria-pressed", String(tool === this.tool));
    this.canvas.dataset.tool = this.tool;
    this.hint.textContent = TOOL_HINTS[this.tool];
    this.render();
  }

  point(event) {
    const box = this.canvas.getBoundingClientRect();
    return [Math.max(0, Math.min(this.width - 1, (event.clientX - box.left) * this.width / box.width)),
      Math.max(0, Math.min(this.height - 1, (event.clientY - box.top) * this.height / box.height))]
      .map((n) => Math.round(n * 100) / 100);
  }

  pointerDown(event) {
    if (this.stale || event.button !== 0) return;
    this.canvas.focus();
    if (this.tool === "pan") {
      this.drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY,
        left: this.canvasArea.scrollLeft, top: this.canvasArea.scrollTop };
      this.canvas.setPointerCapture(event.pointerId);
    } else if (this.tool === "stroke" || this.tool === "divider") {
      if (this.tool === "stroke" && !this.model.region) {
        this.status.textContent = "请先新增或选择一个部位。"; return;
      }
      this.draft = { kind: this.tool, points: [this.point(event)], pointer: event.pointerId };
      this.canvas.setPointerCapture(event.pointerId);
    }
  }

  pointerMove(event) {
    if (this.drag) {
      this.canvasArea.scrollLeft = this.drag.left - event.clientX + this.drag.x;
      this.canvasArea.scrollTop = this.drag.top - event.clientY + this.drag.y;
      return;
    }
    this.hover = this.point(event);
    if (this.draft && this.draft.kind !== "polygon" && this.draft.pointer === event.pointerId) {
      const last = this.draft.points.at(-1);
      if (Math.hypot(this.hover[0] - last[0], this.hover[1] - last[1]) >= Math.max(.6, 1 / this.zoom)) {
        this.draft.points.push(this.hover);
      }
    }
    this.render();
  }

  pointerUp(event) {
    if (this.canvas.hasPointerCapture(event.pointerId)) this.canvas.releasePointerCapture(event.pointerId);
    if (this.drag) { this.drag = null; return; }
    if (!this.draft || this.draft.kind === "polygon" || this.draft.pointer !== event.pointerId) return;
    const draft = this.draft;
    const end = this.point(event);
    const last = draft.points.at(-1);
    if (Math.hypot(end[0] - last[0], end[1] - last[1]) > .25) draft.points.push(end);
    this.draft = null;
    if (draft.points.length < 2) {
      this.status.textContent = "请按住鼠标拖动，画出一条线。"; this.render(); return;
    }
    this.perform(() => draft.kind === "stroke" ? this.model.addStroke(draft.points) : this.model.addDivider(draft.points));
  }

  click(event) {
    if (this.stale) return;
    if (this.tool === "polygon") {
      if (!this.model.region) { this.status.textContent = "请先新增或选择一个部位。"; return; }
      if (event.detail > 1) return;
      if (!this.draft) this.draft = { kind: "polygon", points: [] };
      this.draft.points.push(this.point(event));
      this.render();
    } else if (this.tool === "delete") {
      const target = nearestLine(this.model.document, this.model.selectedId, this.point(event), 10 / this.zoom);
      if (target) this.perform(() => this.model.removeLine(target));
      else this.status.textContent = "附近没有当前部位的走向线或隔开线。";
    }
  }

  finishPolygon() {
    if (this.draft?.kind !== "polygon") return;
    if (this.draft.points.length < 3) {
      this.status.textContent = "圈选至少需要 3 个顶点。继续点击，或按 Esc 取消。"; return;
    }
    const points = this.draft.points;
    this.draft = null;
    this.perform(() => this.model.addPolygon(points));
  }

  discardDraft() {
    if (this.draft || this.drag) {
      const pointer = this.draft?.pointer ?? this.drag?.pointer;
      if (pointer !== undefined && this.canvas?.hasPointerCapture(pointer)) this.canvas.releasePointerCapture(pointer);
      this.draft = null;
      this.drag = null;
      this.render();
    }
  }

  keydown(event) {
    event.stopPropagation();
    const textInput = ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName);
    if (textInput || !this.model) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      this.perform(() => event.shiftKey ? this.model.redo() : this.model.undo());
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
      event.preventDefault(); this.perform(() => this.model.redo());
    } else if (event.key === "Enter" && this.draft?.kind === "polygon") {
      event.preventDefault(); this.finishPolygon();
    } else if (event.key === "Escape" && this.draft) {
      event.preventDefault(); this.discardDraft();
    }
  }

  fit() {
    if (!this.canvasArea || this.closed) return;
    const width = this.canvasArea.clientWidth - 42;
    const height = this.canvasArea.clientHeight - 42;
    if (width <= 0 || height <= 0) return;
    this.setZoom(Math.min(width / this.width, height / this.height, 1));
    this.fitMode = true;
  }

  setZoom(value, clientX, clientY) {
    if (!this.canvas || this.closed) return;
    const area = this.canvasArea.getBoundingClientRect();
    const before = this.canvas.getBoundingClientRect();
    const x = clientX ?? area.left + area.width / 2;
    const y = clientY ?? area.top + area.height / 2;
    const imageX = (x - before.left) / this.zoom;
    const imageY = (y - before.top) / this.zoom;
    this.zoom = Math.max(.03, Math.min(4, value));
    this.fitMode = false;
    this.canvas.style.width = `${this.width * this.zoom}px`;
    this.canvas.style.height = `${this.height * this.zoom}px`;
    this.zoomLabel.textContent = `${Math.round(this.zoom * 100)}%`;
    const after = this.canvas.getBoundingClientRect();
    this.canvasArea.scrollLeft += after.left + imageX * this.zoom - x;
    this.canvasArea.scrollTop += after.top + imageY * this.zoom - y;
    this.render();
  }

  render() {
    if (!this.ctx || this.closed) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.drawImage(this.image, 0, 0);
    if (this.showMask.checked && this.maskOverlay) ctx.drawImage(this.maskOverlay, 0, 0);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    const lineWidth = 2 / this.zoom;
    this.model.document.regions.forEach((region, index) => {
      const color = COLORS[index % COLORS.length];
      const selected = region.id === this.model.selectedId;
      for (const polygon of region.polygons) {
        path(ctx, polygon, true);
        ctx.fillStyle = color;
        ctx.globalAlpha = selected ? .22 : .12;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = color;
        ctx.lineWidth = selected ? lineWidth : lineWidth * .65;
        ctx.setLineDash(selected ? [] : [5 / this.zoom, 4 / this.zoom]);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      for (const stroke of region.strokes) {
        path(ctx, stroke);
        ctx.strokeStyle = "#10151e"; ctx.lineWidth = lineWidth + 2 / this.zoom; ctx.stroke();
        ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.stroke();
      }
    });
    for (const divider of this.model.document.dividers) {
      path(ctx, divider);
      ctx.strokeStyle = "#111"; ctx.lineWidth = lineWidth + 2 / this.zoom; ctx.stroke();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = lineWidth; ctx.setLineDash([6 / this.zoom, 4 / this.zoom]); ctx.stroke();
      ctx.setLineDash([]);
    }
    if (this.draft) {
      const points = [...this.draft.points];
      if (this.draft.kind === "polygon" && this.hover) points.push(this.hover);
      path(ctx, points);
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = lineWidth;
      ctx.setLineDash(this.draft.kind === "polygon" ? [5 / this.zoom, 4 / this.zoom] : []);
      ctx.stroke(); ctx.setLineDash([]);
      if (this.draft.kind === "polygon") {
        for (const point of this.draft.points) {
          ctx.beginPath(); ctx.arc(...point, 3 / this.zoom, 0, Math.PI * 2);
          ctx.fillStyle = "#fff"; ctx.fill();
        }
      }
    }
  }

  invalidate() {
    this.stale = true;
    this.discardDraft();
    this.update();
    if (this.status) this.status.textContent = "节点预览已更新，当前编辑内容未保存。请取消后重新打开，核对新图再编辑。";
  }

  save() {
    if (this.stale) return;
    if (this.draft) { this.status.textContent = "请先完成当前圈选，或按 Esc 取消它。"; return; }
    const preview = this.node._stockingTexture?.preview;
    if (preview !== this.preview || preview.width !== this.width || preview.height !== this.height) {
      this.invalidate(); return;
    }
    if (this.node.inputs?.some((input) => input.name === "guides_json" && input.link != null)) {
      this.status.textContent = "guides_json 已连接上游数据，请断开连接后再保存。"; return;
    }
    try {
      writeGuides(this.node, this.model.serialize());
      this.close();
    } catch (error) {
      this.status.textContent = error.message;
    }
  }

  close() {
    if (this.closed) return;
    if (this.dialog.open) this.dialog.close();
    this.cleanup();
  }

  cleanup() {
    if (this.closed) return;
    this.closed = true;
    this.resizeObserver?.disconnect();
    this.dialog.remove();
    this.maskOverlay = null;
    this.image = null;
    if (this.node._stockingTexture?.panel === this) this.node._stockingTexture.panel = null;
  }
}

app.registerExtension({
  name: "local.StockingTextureGuides",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (["StockingTextureGuides", "StockingTextureRender"].includes(nodeData.name)) {
      for (const [name, [label, tooltip]] of Object.entries(WIDGET_LABELS)) {
        const spec = nodeData.input?.required?.[name] ?? nodeData.input?.optional?.[name];
        if (spec) spec[1] = { ...spec[1], tooltip, label };
      }
    }
    if (nodeData.name === "StockingTextureRender") {
      const created = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const result = created?.apply(this, arguments);
        for (const widget of this.widgets ?? []) {
          const labels = WIDGET_LABELS[widget.name];
          if (labels) { widget.label = labels[0]; widget.tooltip = labels[1]; }
        }
        const strength = this.widgets?.find((w) => w.name === "strength");
        if (strength) {
          const callback = strength.callback;
          const node = this;
          strength.callback = function () {
            const auto = node.widgets?.find((w) => w.name === "auto_strength");
            if (auto) auto.value = false;
            const value = callback?.apply(this, arguments);
            node.setDirtyCanvas?.(true, true);
            return value;
          };
        }
        return result;
      };
      return;
    }
    if (nodeData.name !== "StockingTextureGuides") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      this._stockingTexture = { preview: null, panel: null };
      this.serialize_widgets = true;
      const editButton = this.addWidget("button", "编辑丝袜引导", null, () => {
        style();
        if (this._stockingTexture.panel) {
          this._stockingTexture.panel.dialog.focus(); return;
        }
        this._stockingTexture.panel = new GuidesPanel(this);
      }, { serialize: false });
      editButton.options = { ...editButton.options, serialize: false };
      return result;
    };
    const executed = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      const result = executed?.apply(this, arguments);
      this._stockingTexture ??= { preview: null, panel: null };
      const info = message?.stocking?.[0];
      const image = message?.images?.[0];
      this._stockingTexture.preview = image && info ? {
        image, width: info.width, height: info.height, hasMask: info.has_mask === true, mask: info.mask || null,
      } : null;
      this._stockingTexture.panel?.invalidate();
      return result;
    };
    const removed = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      this._stockingTexture?.panel?.close();
      this._stockingTexture = null;
      return removed?.apply(this, arguments);
    };
  },
});
