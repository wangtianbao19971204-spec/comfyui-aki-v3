import { app } from "../../scripts/app.js";

const API = {
  data: "/promptselector_direct_manager/data",
  save: "/promptselector_direct_manager/save",
  backup: "/promptselector_direct_manager/backup",
  page: "/promptselector_direct_manager/page",
};

const MANAGER_NODES = new Set(["PromptSelector_Local_Manager", "PromptSelector_Local_ManagerLauncher"]);
const USE_NODES = new Set(["PromptSelector_Local_Use"]);

let state = {
  loaded: false,
  categories: [],
  rows: [],
  currentCategory: "",
  search: "",
  duplicatesOnly: false,
  dirty: false,
};

function q(sel, root = document) { return root.querySelector(sel); }
function qa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }
function esc(s) {
  return String(s ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]));
}
function normPrompt(s) { return String(s ?? "").trim().toLowerCase().replace(/[\s_-]+/g, " "); }
function setStatus(msg, cls = "") {
  const el = q("#psnm-status");
  if (!el) return;
  el.textContent = msg;
  el.className = cls;
}
function markDirty(v = true) {
  state.dirty = v;
  const el = q("#psnm-dirty");
  if (el) el.textContent = v ? "未保存" : "已保存";
  if (el) el.className = v ? "dirty" : "clean";
}
function counts() {
  const c = new Map();
  for (const row of state.rows) c.set(row.category, (c.get(row.category) || 0) + 1);
  return c;
}
function duplicateKeys() {
  const seen = new Map();
  for (const r of state.rows) {
    const k = normPrompt(r.prompt);
    if (!k) continue;
    if (!seen.has(k)) seen.set(k, []);
    seen.get(k).push(r);
  }
  const dup = new Set();
  for (const [k, arr] of seen) if (arr.length > 1) dup.add(k);
  return dup;
}
function filteredRows() {
  const s = state.search.trim().toLowerCase();
  const dup = duplicateKeys();
  return state.rows.filter((r) => {
    if (state.currentCategory && r.category !== state.currentCategory && !s) return false;
    if (s && !(String(r.display).toLowerCase().includes(s) || String(r.prompt).toLowerCase().includes(s) || String(r.category).toLowerCase().includes(s))) return false;
    if (state.duplicatesOnly && !dup.has(normPrompt(r.prompt))) return false;
    return true;
  });
}
function rowIndex(row) { return state.rows.indexOf(row); }
function moveRowWithinCategory(row, delta) {
  const same = state.rows.filter(r => r.category === row.category);
  const local = same.indexOf(row);
  if (local < 0) return;
  const target = local + delta;
  if (target < 0 || target >= same.length) return;
  const other = same[target];
  const i = rowIndex(row), j = rowIndex(other);
  [state.rows[i], state.rows[j]] = [state.rows[j], state.rows[i]];
  markDirty(); render();
}
function sortCurrentCategory(mode) {
  const cat = state.currentCategory;
  if (!cat) return;
  const selected = state.rows.filter(r => r.category === cat);
  const other = state.rows.filter(r => r.category !== cat);
  const cmpText = (a,b,fn) => fn(a).localeCompare(fn(b), "zh-Hans-CN", {sensitivity:"base"});
  if (mode === "显示名升序") selected.sort((a,b)=>cmpText(a,b,x=>x.display));
  else if (mode === "显示名降序") selected.sort((a,b)=>cmpText(b,a,x=>x.display));
  else if (mode === "Prompt升序") selected.sort((a,b)=>cmpText(a,b,x=>x.prompt));
  else if (mode === "Prompt降序") selected.sort((a,b)=>cmpText(b,a,x=>x.prompt));
  else if (mode === "短词优先") selected.sort((a,b)=>String(a.prompt).length-String(b.prompt).length || cmpText(a,b,x=>x.prompt));
  else if (mode === "长词优先") selected.sort((a,b)=>String(b.prompt).length-String(a.prompt).length || cmpText(a,b,x=>x.prompt));
  else if (mode === "中文显示名优先") selected.sort((a,b)=>(/[\u4e00-\u9fff]/.test(b.display)?1:0)-(/[\u4e00-\u9fff]/.test(a.display)?1:0) || cmpText(a,b,x=>x.display));
  else if (mode === "英文显示名优先") selected.sort((a,b)=>(/[\u4e00-\u9fff]/.test(a.display)?1:0)-(/[\u4e00-\u9fff]/.test(b.display)?1:0) || cmpText(a,b,x=>x.display));
  state.rows = [];
  for (const c of state.categories) state.rows.push(...(c === cat ? selected : other.filter(r=>r.category===c)));
  markDirty(); render();
}
function renderCategories() {
  const wrap = q("#psnm-cats");
  if (!wrap) return;
  const c = counts();
  wrap.innerHTML = state.categories.map(cat => `<button class="cat ${cat===state.currentCategory?'active':''}" data-cat="${esc(cat)}"><span>${esc(cat)}</span><b>${c.get(cat)||0}</b></button>`).join("");
  qa("button.cat", wrap).forEach(btn => btn.onclick = () => { state.currentCategory = btn.dataset.cat; state.search = ""; q("#psnm-search").value=""; render(); });
}
function renderTable() {
  const body = q("#psnm-tbody");
  const info = q("#psnm-info");
  if (!body) return;
  const rows = filteredRows();
  const dup = duplicateKeys();
  if (info) info.textContent = `显示 ${rows.length} / 总 ${state.rows.length}` + (state.currentCategory && !state.search ? ` · ${state.currentCategory}` : state.search ? ` · 搜索：${state.search}` : "");
  body.innerHTML = rows.slice(0, 1200).map((r, i) => {
    const isDup = dup.has(normPrompt(r.prompt));
    const idx = rowIndex(r);
    return `<tr data-idx="${idx}" class="${isDup ? 'dup' : ''}">
      <td class="num">${i+1}</td>
      <td><input class="display" value="${esc(r.display)}" /></td>
      <td><input class="prompt" value="${esc(r.prompt)}" /></td>
      <td><select class="category">${state.categories.map(c => `<option ${c===r.category?'selected':''}>${esc(c)}</option>`).join("")}</select></td>
      <td class="actions"><button class="up" title="上移">↑</button><button class="down" title="下移">↓</button><button class="del" title="删除">删除</button></td>
    </tr>`;
  }).join("");
  qa("tr", body).forEach(tr => {
    const idx = Number(tr.dataset.idx);
    const row = state.rows[idx];
    q("input.display", tr).oninput = (e) => { row.display = e.target.value; markDirty(); };
    q("input.prompt", tr).oninput = (e) => { row.prompt = e.target.value; markDirty(); tr.classList.toggle('dup', duplicateKeys().has(normPrompt(row.prompt))); };
    q("select.category", tr).onchange = (e) => { row.category = e.target.value; markDirty(); render(); };
    q("button.up", tr).onclick = () => moveRowWithinCategory(row, -1);
    q("button.down", tr).onclick = () => moveRowWithinCategory(row, 1);
    q("button.del", tr).onclick = () => { if (confirm(`删除：${row.display || row.prompt} ?`)) { state.rows.splice(idx, 1); markDirty(); render(); } };
  });
}
function render() { renderCategories(); renderTable(); }
async function loadData() {
  setStatus("正在读取数据...");
  const r = await fetch(API.data);
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "读取失败");
  state.categories = j.categories || j.category_order || [];
  state.rows = (j.rows || []).map(x => ({category:x.category, display:x.display, prompt:x.prompt}));
  state.currentCategory = state.categories[0] || "";
  state.loaded = true;
  markDirty(false);
  setStatus(`已读取：${j.total || state.rows.length} 条；保存后需要重启 ComfyUI 才会刷新下拉。`, "ok");
  render();
}
async function saveData() {
  if (!state.loaded) return;
  if (!confirm("保存会写回当前 NSFWPromptSelector_LocalMerged.py，并自动生成 .bak。继续？")) return;
  setStatus("正在写回 PY...");
  const r = await fetch(API.save, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({categories: state.categories, rows: state.rows})});
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "保存失败");
  markDirty(false);
  setStatus(`${j.message} 备份：${j.backup_path || ''}` + (j.blocked_count ? `；过滤 ${j.blocked_count} 条` : ""), "ok");
}
async function backup() {
  const r = await fetch(API.backup, {method:"POST"});
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || "备份失败");
  setStatus(`已备份：${j.backup_path}`, "ok");
}
function addRow() {
  const cat = state.currentCategory || state.categories[0] || "额外标签";
  if (!state.categories.includes(cat)) state.categories.push(cat);
  state.rows.push({category: cat, display: "新标签", prompt: "new_prompt"});
  markDirty(); render();
}
function addCategory() {
  const name = prompt("新分类名称：");
  if (!name) return;
  if (!state.categories.includes(name)) state.categories.push(name);
  state.currentCategory = name;
  markDirty(); render();
}
function exportJson() {
  const data = {categories: state.categories, rows: state.rows};
  const blob = new Blob([JSON.stringify(data, null, 2)], {type:"application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "promptselector_direct_export.json"; a.click();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
}
function importJson(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const j = JSON.parse(reader.result);
      if (!Array.isArray(j.rows)) throw new Error("JSON 里没有 rows");
      state.categories = Array.isArray(j.categories) ? j.categories : Array.from(new Set(j.rows.map(r=>r.category).filter(Boolean)));
      state.rows = j.rows.map(x => ({category:x.category || state.categories[0] || "额外标签", display:x.display || x.prompt || "", prompt:x.prompt || x.display || ""}));
      state.currentCategory = state.categories[0] || "";
      markDirty(); render(); setStatus("已导入 JSON，未保存。", "ok");
    } catch(e) { setStatus("导入失败：" + e.message, "err"); }
  };
  reader.readAsText(file, "utf-8");
}
function buildPanel() {
  if (q("#psnm-root")) return;
  const root = document.createElement("div");
  root.id = "psnm-root";
  root.innerHTML = `<div id="psnm-overlay"></div>
  <div id="psnm-panel">
    <div class="head"><div><b>PromptSelector 标签管理面板</b><span id="psnm-dirty" class="clean">未读取</span></div><div class="head-actions"><button id="psnm-openpage" title="用独立页面打开">独立页面</button><button id="psnm-close">×</button></div></div>
    <div class="toolbar">
      <input id="psnm-search" placeholder="搜索显示名 / prompt / 分类，不需要执行队列" />
      <button id="psnm-load">刷新读取</button><button id="psnm-save" class="primary">保存写回PY</button><button id="psnm-backup">备份PY</button>
      <button id="psnm-add">新增标签</button><button id="psnm-addcat">新增分类</button>
      <select id="psnm-sort"><option>显示名升序</option><option>显示名降序</option><option>Prompt升序</option><option>Prompt降序</option><option>短词优先</option><option>长词优先</option><option>中文显示名优先</option><option>英文显示名优先</option></select><button id="psnm-applysort">排序当前分类</button>
      <label class="chk"><input type="checkbox" id="psnm-dups" /> 只看重复Prompt</label>
      <button id="psnm-export">导出JSON</button><label class="filebtn">导入JSON<input id="psnm-import" type="file" accept="application/json" /></label>
    </div>
    <div id="psnm-status"></div>
    <div class="main"><div id="psnm-cats"></div><div class="tablewrap"><div id="psnm-info"></div><table><thead><tr><th>#</th><th>显示名</th><th>Prompt</th><th>分类</th><th>操作</th></tr></thead><tbody id="psnm-tbody"></tbody></table></div></div>
    <div class="foot">黄色行 = prompt 精确重复。编辑后点“保存写回PY”，再重启 ComfyUI 刷新使用节点下拉。</div>
  </div>`;
  document.body.appendChild(root);
  const style = document.createElement("style");
  style.textContent = `#psnm-root{display:none}#psnm-root.open{display:block}#psnm-overlay{position:fixed;inset:0;background:#0008;z-index:10000}#psnm-panel{position:fixed;inset:4vh 4vw;z-index:10001;background:#1f2227;color:#ddd;border:1px solid #555;border-radius:12px;display:flex;flex-direction:column;box-shadow:0 10px 50px #000;overflow:hidden;font:14px/1.4 Arial,'Microsoft YaHei',sans-serif}.head{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;background:#2b3038;border-bottom:1px solid #555}.head b{font-size:18px;margin-right:12px}.head button{background:#343a44;color:#eee;border:1px solid #555;border-radius:6px;cursor:pointer;padding:6px 10px}.head #psnm-close{font-size:22px;background:transparent;border:0;padding:0 4px}.head-actions{display:flex;gap:8px;align-items:center}.dirty{color:#ffcc66}.clean{color:#88cc88}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 12px;background:#242830;border-bottom:1px solid #444}.toolbar input#psnm-search{min-width:280px;flex:1;padding:8px;background:#11151b;color:#eee;border:1px solid #555;border-radius:6px}.toolbar button,.toolbar select,.filebtn{padding:7px 9px;border-radius:6px;border:1px solid #555;background:#333943;color:#eee;cursor:pointer}.toolbar button.primary{background:#235a88}.filebtn input{display:none}.chk{white-space:nowrap}#psnm-status{min-height:20px;padding:6px 12px;border-bottom:1px solid #444;color:#bbb}#psnm-status.ok{color:#8fdb8f}#psnm-status.err{color:#ff8f8f}.main{display:flex;min-height:0;flex:1}#psnm-cats{width:210px;overflow:auto;border-right:1px solid #444;padding:8px;background:#191c21}.cat{width:100%;display:flex;justify-content:space-between;margin:3px 0;padding:7px 8px;background:#2b3038;color:#ddd;border:1px solid #444;border-radius:6px;text-align:left;cursor:pointer}.cat.active{background:#36506d;border-color:#6a9ac9}.cat b{color:#aaa}.tablewrap{flex:1;overflow:auto;padding:8px}#psnm-info{padding:4px 4px 8px;color:#aaa}table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border-bottom:1px solid #3a3f47;padding:5px}th{position:sticky;top:0;background:#252a31;z-index:1}td.num{width:42px;color:#aaa;text-align:right}td input,td select{width:100%;box-sizing:border-box;background:#11151b;color:#eee;border:1px solid #4a505a;border-radius:5px;padding:6px}td.actions{width:150px;white-space:nowrap}td.actions button{margin-right:4px;padding:5px 7px;background:#303640;color:#eee;border:1px solid #555;border-radius:5px;cursor:pointer}tr.dup td{background:#4b3d19}.foot{padding:7px 12px;border-top:1px solid #444;color:#aaa;background:#242830}`;
  document.head.appendChild(style);
  q("#psnm-close").onclick = () => root.classList.remove("open");
  q("#psnm-openpage").onclick = () => window.open(API.page, "_blank");
  q("#psnm-load").onclick = () => loadData().catch(e => setStatus("读取失败：" + e.message, "err"));
  q("#psnm-save").onclick = () => saveData().catch(e => setStatus("保存失败：" + e.message, "err"));
  q("#psnm-backup").onclick = () => backup().catch(e => setStatus("备份失败：" + e.message, "err"));
  q("#psnm-add").onclick = addRow;
  q("#psnm-addcat").onclick = addCategory;
  q("#psnm-search").oninput = e => { state.search = e.target.value; render(); };
  q("#psnm-dups").onchange = e => { state.duplicatesOnly = e.target.checked; render(); };
  q("#psnm-applysort").onclick = () => sortCurrentCategory(q("#psnm-sort").value);
  q("#psnm-export").onclick = exportJson;
  q("#psnm-import").onchange = e => { if (e.target.files?.[0]) importJson(e.target.files[0]); };
}
function openPanel() {
  buildPanel();
  q("#psnm-root").classList.add("open");
  if (!state.loaded) loadData().catch(e => setStatus("读取失败：" + e.message, "err"));
}
function openPage() { window.open(API.page, "_blank"); }
function addManagerButtonToNode(node) {
  try {
    if (!node || node.__promptSelectorManagerPatched) return;
    const cls = String(node.comfyClass || node.type || "");
    if (!MANAGER_NODES.has(cls)) return;
    node.__promptSelectorManagerPatched = true;
    node.addWidget("button", "打开管理面板", "", () => openPanel());
    node.addWidget("button", "独立页面打开", "", () => openPage());
    node.addWidget("button", "刷新管理数据", "", () => { state.loaded = false; openPanel(); });
    node.color = node.color || "#223348";
    node.bgcolor = node.bgcolor || "#1b2430";
    node.size = node.size || [320, 160];
    if (node.setSize) node.setSize([Math.max(node.size[0], 320), Math.max(node.size[1], 150)]);
  } catch (e) { console.warn("PromptSelector manager node button patch failed", e); }
}
function addUseNodeMenu(nodeType) {
  const origMenu = nodeType.prototype.getExtraMenuOptions;
  nodeType.prototype.getExtraMenuOptions = function(_, options) {
    if (origMenu) origMenu.apply(this, arguments);
    options.unshift({content: "打开 PromptSelector 标签管理面板", callback: () => openPanel()});
    options.unshift({content: "用独立页面管理 PromptSelector", callback: () => openPage()});
  };
}
function patchPromptSelectorPlaceholders(node) {
  try {
    if (!node || !node.widgets) return;
    const cls = String(node.comfyClass || node.type || "");
    if (!USE_NODES.has(cls)) return;
    for (const w of node.widgets) {
      if (!w || !w.name || !String(w.name).startsWith("选择_")) continue;
      const cat = String(w.name).replace(/^选择_/, "");
      const label = `【${cat}】未选择`;
      if (w.inputEl && w.inputEl.placeholder !== undefined) w.inputEl.placeholder = label;
      if (w.element && w.element.querySelectorAll) for (const input of w.element.querySelectorAll("input, textarea")) input.placeholder = label;
    }
  } catch (e) { console.warn("PromptSelector placeholder patch failed", e); }
}

app.registerExtension({
  name: "PromptSelector.NodeButtonManager",
  async setup() {
    console.log("[PromptSelector] Node-button manager extension loaded");
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const name = nodeData?.name || nodeData?.class_type || "";
    const origCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const r = origCreated ? origCreated.apply(this, args) : undefined;
      setTimeout(() => addManagerButtonToNode(this), 50);
      setTimeout(() => patchPromptSelectorPlaceholders(this), 100);
      setTimeout(() => patchPromptSelectorPlaceholders(this), 800);
      return r;
    };
    if (MANAGER_NODES.has(name)) {
      const origDblClick = nodeType.prototype.onDblClick;
      nodeType.prototype.onDblClick = function (...args) {
        openPanel();
        return origDblClick ? origDblClick.apply(this, args) : undefined;
      };
      const origMenu = nodeType.prototype.getExtraMenuOptions;
      nodeType.prototype.getExtraMenuOptions = function(_, options) {
        if (origMenu) origMenu.apply(this, arguments);
        options.unshift({content: "打开管理面板", callback: () => openPanel()});
        options.unshift({content: "独立页面打开", callback: () => openPage()});
      };
    }
    if (USE_NODES.has(name)) addUseNodeMenu(nodeType);
  },
});
