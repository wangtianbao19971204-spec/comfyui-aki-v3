const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { pathToFileURL } = require("node:url");
const { test } = require("node:test");

const web = path.resolve(__dirname, "../web");
const modelSource = fs.readFileSync(path.join(web, "editor_model.js"), "utf8");
const modulePromise = import(`data:text/javascript;base64,${Buffer.from(modelSource).toString("base64")}`);
const fixture = () => ({ schema: 1, width: 120, height: 160,
  regions: [{ id: "left", name: "左腿", polygons: [[[10, 10], [90, 10], [70, 130]]],
    strokes: [[[20, 35], [80, 40]]] }], dividers: [[[45, 20], [45, 90]]] });

test("empty guides bind the image size; malformed data and size drift are rejected", async () => {
  const { parseGuides, emptyGuides } = await modulePromise;
  assert.deepEqual(parseGuides("", 120, 160), emptyGuides(120, 160));
  assert.deepEqual(parseGuides(JSON.stringify(emptyGuides()), 120, 160), emptyGuides(120, 160));
  assert.throws(() => parseGuides("broken", 120, 160), /JSON/);
  assert.throws(() => parseGuides(JSON.stringify(fixture()), 240, 320), /不会自动缩放/);
  const missingSize = fixture(); missingSize.width = 0; missingSize.height = 0;
  assert.throws(() => parseGuides(JSON.stringify(missingSize), 120, 160), /缺少参考图像尺寸/);
});

test("saved schema preserves region identity, disjoint polygons, strokes and dividers", async () => {
  const { EditorModel, parseGuides } = await modulePromise;
  const original = fixture();
  const editor = new EditorModel(original);
  editor.addPolygon([[12, 140], [50, 140], [35, 150]]);
  editor.renameRegion("左腿丝袜");
  assert.equal(original.regions[0].polygons.length, 1);
  assert.equal(editor.document.regions[0].id, "left");
  const saved = parseGuides(editor.serialize(), 120, 160);
  assert.equal(saved.regions[0].polygons.length, 2);
  assert.equal(saved.regions[0].name, "左腿丝袜");
  assert.deepEqual(saved.regions[0].strokes, original.regions[0].strokes);
  assert.deepEqual(saved.dividers, original.dividers);
  assert.deepEqual(new EditorModel(saved).document, editor.document);
});

test("undo and redo restore geometry and names; a new edit ends the redo branch", async () => {
  const { EditorModel } = await modulePromise;
  const editor = new EditorModel(fixture());
  const before = editor.serialize();
  editor.renameRegion("左腿新名");
  editor.clearRegion("strokes");
  assert.equal(editor.document.regions[0].strokes.length, 0);
  assert.equal(editor.undo(), true);
  assert.equal(editor.document.regions[0].strokes.length, 1);
  assert.equal(editor.undo(), true);
  assert.equal(editor.serialize(), before);
  assert.equal(editor.undo(), false);
  assert.equal(editor.redo(), true);
  editor.addDivider([[2, 2], [20, 20]]);
  assert.equal(editor.redo(), false);
  assert.equal(editor.document.regions[0].name, "左腿新名");
});

test("region deletion and undo keep remaining regions ordered and editable", async () => {
  const { EditorModel } = await modulePromise;
  const editor = new EditorModel(fixture());
  const id = editor.addRegion("右腿");
  editor.addStroke([[90, 80], [105, 90]]);
  assert.deepEqual(editor.document.regions.map((r) => r.name), ["左腿", "右腿"]);
  editor.deleteRegion();
  assert.equal(editor.selectedId, "left");
  editor.undo();
  assert.equal(editor.document.regions[1].id, id);
  assert.equal(editor.document.regions[1].strokes.length, 1);
  editor.select(id);
  assert.equal(editor.region.name, "右腿");
});

test("deleting a line only touches the selected stroke or global divider", async () => {
  const { EditorModel, nearestLine } = await modulePromise;
  const editor = new EditorModel(fixture());
  const stroke = nearestLine(editor.document, "left", [22, 35], 3);
  assert.equal(stroke.kind, "stroke");
  editor.removeLine(stroke);
  assert.equal(editor.region.strokes.length, 0);
  assert.equal(editor.document.dividers.length, 1);
  editor.undo();
  const divider = nearestLine(editor.document, "left", [45, 70], 2);
  assert.equal(divider.kind, "divider");
  editor.removeLine(divider);
  assert.equal(editor.region.strokes.length, 1);
  assert.equal(editor.document.dividers.length, 0);
  assert.equal(nearestLine(editor.document, "left", [118, 158], 1), null);
});

test("invalid edits do not mutate data or history; editor instances are isolated", async () => {
  const { EditorModel, validateGuides } = await modulePromise;
  const a = new EditorModel(fixture()), b = new EditorModel(fixture());
  const before = a.serialize();
  assert.throws(() => a.addStroke([[0, 0], [120, 1]]), /范围之外/);
  assert.throws(() => a.addPolygon([[1, 1], [2, 2]]), /3 个点/);
  assert.throws(() => a.renameRegion(" "), /不能为空/);
  assert.equal(a.serialize(), before);
  assert.equal(a.undoStack.length, 0);
  a.addStroke([[1, 1], [10, 10]]);
  assert.equal(b.serialize(), before);
  const duplicate = fixture(); duplicate.regions.push({ ...duplicate.regions[0] });
  assert.throws(() => validateGuides(duplicate), /不同的非空 id/);
});

test("editor honors backend size limits and preserves imported coordinate precision", async () => {
  const { EditorModel, validateGuides, parseGuides } = await modulePromise;
  const data = fixture(); data.regions[0].strokes[0][0] = [20.123456, 35.765432];
  assert.deepEqual(JSON.parse(new EditorModel(data).serialize()).regions[0].strokes[0][0], [20.123456, 35.765432]);
  const tooMany = fixture();
  tooMany.regions = Array.from({ length: 33 }, (_, index) => ({ id: String(index), name: "部位", polygons: [], strokes: [] }));
  assert.throws(() => validateGuides(tooMany), /32 个部位/);
  const tooManyPoints = fixture();
  tooManyPoints.dividers = [Array.from({ length: 50001 }, () => [1, 1])];
  assert.throws(() => validateGuides(tooManyPoints), /50000/);
  assert.throws(() => parseGuides(" ".repeat(4 * 1024 * 1024 + 1), 120, 160), /4 MiB/);
});

async function extensionHarness() {
  const model = await modulePromise;
  let extension;
  const app = { registerExtension: (value) => { extension = value; } };
  const context = vm.createContext({ app, api: { apiURL: (url) => `/comfy${url}` },
    ...model, URL, URLSearchParams, console });
  const source = fs.readFileSync(path.join(web, "stocking_texture.js"), "utf8")
    .replace(/^import .*;\r?\n/gm, "")
    .replaceAll("import.meta.url", JSON.stringify(pathToFileURL(path.join(web, "stocking_texture.js")).href));
  vm.runInContext(`${source}\nglobalThis.testExports = { writeGuides, viewURL };`, context);
  return { extension, context };
}

test("node extension chains callbacks, caches preview metadata and cleans up on removal", async () => {
  const { extension } = await extensionHarness();
  let originalCreated = 0, originalExecuted = 0, originalRemoved = 0, closed = 0, invalidated = 0;
  class Node {
    constructor() { this.widgets = []; }
    addWidget(type, name, value, callback, options) {
      const widget = { type, name, value, callback, options }; this.widgets.push(widget); return widget;
    }
    onNodeCreated() { originalCreated++; return "created"; }
    onExecuted() { originalExecuted++; return "executed"; }
    onRemoved() { originalRemoved++; return "removed"; }
  }
  await extension.beforeRegisterNodeDef(Node, { name: "StockingTextureGuides" });
  const a = new Node(), b = new Node();
  assert.equal(a.onNodeCreated(), "created"); b.onNodeCreated();
  assert.equal(originalCreated, 2);
  assert.equal(a.widgets[0].name, "编辑丝袜引导");
  assert.equal(a.widgets[0].options.serialize, false);
  const image = { filename: "image.png", type: "temp", subfolder: "" };
  const mask = { filename: "mask.png", type: "temp", subfolder: "" };
  assert.equal(a.onExecuted({ images: [image], stocking: [{ width: 120, height: 160, has_mask: false, mask }] }), "executed");
  assert.equal(originalExecuted, 1);
  assert.equal(a._stockingTexture.preview.image, image);
  assert.equal(a._stockingTexture.preview.hasMask, false);
  assert.equal(b._stockingTexture.preview, null);
  a._stockingTexture.panel = { invalidate() { invalidated++; }, close() { closed++; } };
  a.onExecuted({ images: [image], stocking: [{ width: 120, height: 160, has_mask: true, mask }] });
  assert.equal(a._stockingTexture.preview.hasMask, true);
  assert.equal(invalidated, 1);
  assert.equal(a.onRemoved(), "removed");
  assert.equal(closed, 1); assert.equal(originalRemoved, 1); assert.equal(a._stockingTexture, null);
});

test("save writes the actual widget and triggers change without a second document store", async () => {
  const { context } = await extensionHarness();
  let callbackValue, graphChanges = 0, canvasChanges = 0;
  const input = { value: "old" };
  const widget = { name: "guides_json", value: "old", inputEl: input,
    callback(value) { callbackValue = value; } };
  const node = { widgets: [widget], graph: { change() { graphChanges++; } },
    setDirtyCanvas() { canvasChanges++; } };
  context.testExports.writeGuides(node, "new JSON");
  assert.equal(widget.value, "new JSON"); assert.equal(input.value, "new JSON");
  assert.equal(callbackValue, "new JSON"); assert.equal(graphChanges, 1); assert.equal(canvasChanges, 1);
  assert.throws(() => context.testExports.writeGuides({ widgets: [] }, "x"), /找不到/);
});

test("view routes encode names and render labels preserve input field identity", async () => {
  const { extension, context } = await extensionHarness();
  const url = context.testExports.viewURL({ filename: "丝袜 & test.png", subfolder: "QA 子目录", type: "temp" });
  const query = new URL(url, "http://localhost").searchParams;
  assert.equal(query.get("filename"), "丝袜 & test.png");
  assert.equal(query.get("subfolder"), "QA 子目录");
  assert.equal(query.has("preview"), false);
  assert.throws(() => context.testExports.viewURL({ filename: "x", type: "remote" }), /可读取/);
  class Render { onNodeCreated() { this.widgets = [{ name: "density", value: 100 }]; return "ok"; } }
  const data = { name: "StockingTextureRender", input: { required: { density: ["FLOAT", { default: 100 }] } } };
  await extension.beforeRegisterNodeDef(Render, data);
  const node = new Render(); assert.equal(node.onNodeCreated(), "ok");
  assert.equal(node.widgets[0].name, "density"); assert.equal(node.widgets[0].label, "织纹密度 (%)");
  assert.equal(data.input.required.density[1].default, 100);
  assert.match(data.input.required.density[1].tooltip, /摩尔纹/);
});

test("manual strength disables auto like upstream while loading values preserves it", async () => {
  const { extension } = await extensionHarness();
  let calls = 0;
  class Render {
    onNodeCreated() {
      this.widgets = [{ name: "strength", value: 100, callback(value) { calls++; return value; } },
        { name: "auto_strength", value: true }, { name: "dark_adapt", value: true }];
    }
  }
  const data = { name: "StockingTextureRender", input: { optional: { dark_adapt: ["BOOLEAN", { default: true }] } } };
  await extension.beforeRegisterNodeDef(Render, data);
  const node = new Render(); node.onNodeCreated();
  assert.equal(node.widgets[1].value, true);
  node.widgets[0].value = 60; // workflow deserialization is not a slider gesture
  assert.equal(node.widgets[1].value, true);
  assert.equal(node.widgets[0].callback(160), 160);
  assert.equal(node.widgets[1].value, false);
  assert.equal(calls, 1);
  assert.equal(node.widgets[2].label, "暗部织纹适配");
  assert.match(data.input.optional.dark_adapt[1].tooltip, /抗摩尔纹/);
});
