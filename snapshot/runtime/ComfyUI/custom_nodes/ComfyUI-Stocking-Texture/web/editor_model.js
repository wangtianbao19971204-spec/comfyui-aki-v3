const copy = (value) => JSON.parse(JSON.stringify(value));

export function emptyGuides(width = 0, height = 0) {
  return { schema: 1, width, height, regions: [], dividers: [] };
}

function points(value, minimum, width, height, label) {
  if (!Array.isArray(value) || value.length < minimum) {
    throw new Error(`${label}至少需要 ${minimum} 个点。`);
  }
  return value.map((point) => {
    if (!Array.isArray(point) || point.length !== 2 ||
        !point.every((n) => typeof n === "number" && Number.isFinite(n)) ||
        point[0] < 0 || point[0] > width - 1 || point[1] < 0 || point[1] > height - 1) {
      throw new Error(`${label}含有图像范围之外的坐标。`);
    }
    return [...point];
  });
}

export function validateGuides(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || value.schema !== 1) {
    throw new Error("丝袜引导数据格式不正确，仅支持 schema 1。");
  }
  const { width, height } = value;
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 0 || height < 0 ||
      ((width === 0) !== (height === 0))) {
    throw new Error("引导数据必须保留有效的参考图像宽高。");
  }
  if (!Array.isArray(value.regions) || !Array.isArray(value.dividers)) {
    throw new Error("引导数据缺少 regions 或 dividers。");
  }
  if (value.regions.length > 32) throw new Error("最多支持 32 个部位。");
  if (width === 0 && (value.regions.length || value.dividers.length)) {
    throw new Error("已有引导数据缺少参考图像尺寸，无法安全应用。");
  }
  const ids = new Set();
  let pointCount = 0;
  const line = (p, minimum, label) => {
    const result = points(p, minimum, width, height, label);
    pointCount += result.length;
    if (pointCount > 50000) throw new Error("引导点数量超过 50000，请简化走向或圈选。");
    return result;
  };
  const regions = value.regions.map((region) => {
    if (!region || typeof region.id !== "string" || !region.id.trim() || region.id.length > 128 || ids.has(region.id)) {
      throw new Error("每个部位必须具有不同的非空 id。");
    }
    if (typeof region.name !== "string" || !region.name.trim() || region.name.trim().length > 80) {
      throw new Error("部位名称不能为空，且不能超过 80 字。");
    }
    if (!Array.isArray(region.polygons) || !Array.isArray(region.strokes)) {
      throw new Error("部位数据缺少 polygons 或 strokes。");
    }
    ids.add(region.id);
    return {
      id: region.id,
      name: region.name.trim(),
      polygons: region.polygons.map((p) => line(p, 3, "圈选")),
      strokes: region.strokes.map((p) => line(p, 2, "走向线")),
    };
  });
  return { schema: 1, width, height, regions,
    dividers: value.dividers.map((p) => line(p, 2, "隔开线")) };
}

export function parseGuides(raw, width, height) {
  if (typeof raw === "string" && new TextEncoder().encode(raw).length > 4 * 1024 * 1024) {
    throw new Error("引导 JSON 超过 4 MiB，请简化数据。");
  }
  let value;
  try {
    value = raw && String(raw).trim() ? JSON.parse(raw) : emptyGuides();
  } catch {
    throw new Error("guides_json 不是有效的 JSON，请先修正该输入。");
  }
  const parsed = validateGuides(value);
  if (parsed.width === 0 && parsed.height === 0) {
    parsed.width = width;
    parsed.height = height;
  } else if (parsed.width !== width || parsed.height !== height) {
    throw new Error(`引导参考图为 ${parsed.width}×${parsed.height}，当前图为 ${width}×${height}。请使用原尺寸图片，或在 guides_json 中新建空引导；不会自动缩放已有坐标。`);
  }
  return validateGuides(parsed);
}

export class EditorModel {
  constructor(value) {
    this.document = validateGuides(value);
    this.selectedId = this.document.regions[0]?.id ?? null;
    this.undoStack = [];
    this.redoStack = [];
  }

  get region() {
    return this.document.regions.find((r) => r.id === this.selectedId) ?? null;
  }

  select(id) {
    if (!this.document.regions.some((r) => r.id === id)) return false;
    this.selectedId = id;
    return true;
  }

  reconcileSelection() {
    if (!this.region) this.selectedId = this.document.regions[0]?.id ?? null;
  }

  edit(change) {
    const draft = copy(this.document);
    change(draft);
    const next = validateGuides(draft);
    if (JSON.stringify(next) === JSON.stringify(this.document)) return false;
    this.undoStack.push(copy(this.document));
    if (this.undoStack.length > 100) this.undoStack.shift();
    this.redoStack = [];
    this.document = next;
    this.reconcileSelection();
    return true;
  }

  addRegion(name) {
    let number = 1;
    while (this.document.regions.some((r) => r.id === `region_${number}`)) number++;
    const id = `region_${number}`;
    this.edit((d) => d.regions.push({ id, name: name || `部位 ${number}`, polygons: [], strokes: [] }));
    this.selectedId = id;
    return id;
  }

  renameRegion(name) {
    const id = this.selectedId;
    if (!this.region) return false;
    return this.edit((d) => { d.regions.find((r) => r.id === id).name = name; });
  }

  deleteRegion() {
    const id = this.selectedId;
    if (!this.region) return false;
    return this.edit((d) => { d.regions = d.regions.filter((r) => r.id !== id); });
  }

  addPolygon(p) {
    return this.addToRegion("polygons", p);
  }

  addStroke(p) {
    return this.addToRegion("strokes", p);
  }

  addToRegion(key, p) {
    const id = this.selectedId;
    if (!this.region) throw new Error("请先新增或选择一个部位。");
    return this.edit((d) => d.regions.find((r) => r.id === id)[key].push(copy(p)));
  }

  addDivider(p) {
    return this.edit((d) => d.dividers.push(copy(p)));
  }

  clearRegion(key) {
    const id = this.selectedId;
    if (!this.region) return false;
    return this.edit((d) => { d.regions.find((r) => r.id === id)[key] = []; });
  }

  removeLine(target) {
    if (!target) return false;
    return this.edit((d) => {
      const lines = target.kind === "divider" ? d.dividers :
        d.regions.find((r) => r.id === target.regionId)?.strokes;
      if (lines) lines.splice(target.index, 1);
    });
  }

  undo() {
    if (!this.undoStack.length) return false;
    this.redoStack.push(copy(this.document));
    this.document = this.undoStack.pop();
    this.reconcileSelection();
    return true;
  }

  redo() {
    if (!this.redoStack.length) return false;
    this.undoStack.push(copy(this.document));
    this.document = this.redoStack.pop();
    this.reconcileSelection();
    return true;
  }

  serialize() {
    return JSON.stringify(this.document);
  }
}

function segmentDistance(point, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const denominator = dx * dx + dy * dy;
  const t = denominator ? Math.max(0, Math.min(1,
    ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / denominator)) : 0;
  return Math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy);
}

export function nearestLine(document, regionId, point, tolerance) {
  let nearest = null, best = tolerance;
  const visit = (lines, kind, id = null) => lines.forEach((line, index) => {
    for (let i = 1; i < line.length; i++) {
      const distance = segmentDistance(point, line[i - 1], line[i]);
      if (distance <= best) {
        best = distance;
        nearest = { kind, regionId: id, index };
      }
    }
  });
  visit(document.regions.find((r) => r.id === regionId)?.strokes ?? [], "stroke", regionId);
  visit(document.dividers, "divider");
  return nearest;
}
