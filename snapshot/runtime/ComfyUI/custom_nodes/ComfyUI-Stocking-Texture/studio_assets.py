"""Small browser adaptations over the byte-preserved upstream UI."""
from pathlib import Path
import re

ROOT = Path(__file__).parent / "vendor/static"
FILES = {"app.js": "text/javascript", "look.js": "text/javascript", "i18n.js": "text/javascript",
         "style.css": "text/css", "i18n/en.json": "application/json"}


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError("固定版编辑器的接入点已变化，请重新验收前端适配")
    return text.replace(before, after, 1)


def page(base, lang="zh"):
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    english = lang == "en"
    if english:
        html = html.replace('lang="zh-CN"', 'lang="en"', 1)
    html = re.sub(r'<link rel="icon"[^>]*>\s*', "", html)
    apply, close = ("Apply to node", "Close") if english else ("应用到节点", "关闭")
    depth, dark = ("Built-in depth", "Dark adaptation") if english else ("内置深度", "暗部适配")
    note = "Edits are autosaved as a draft. Apply to save them in the workflow." if english else "编辑会自动保存为草稿；应用后写入工作流。"
    bridge = f'''<div id="stocking-bridge">
      <button id="stocking-apply" class="btn primary">{apply}</button>
      <label><input id="stocking-depth" type="checkbox"> {depth}</label>
      <label><input id="stocking-dark" type="checkbox"> {dark}</label>
      <span id="stocking-note">{note}</span><div class="spacer"></div>
      <button id="stocking-close" class="btn">{close}</button>
    </div>'''
    css = '''<style>
      body { grid-template-rows:40px 44px 1fr 28px;
        grid-template-areas:"bridge bridge" "bar bar" "side stage" "status status"; }
      #stocking-bridge { grid-area:bridge; display:flex; align-items:center; gap:12px;
        padding:4px 10px; border-bottom:1px solid var(--line); }
      #stocking-bridge label { display:flex; gap:4px; align-items:center; white-space:nowrap; }
      #stocking-note { color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      #stocking-bridge button { white-space:nowrap; }
      #exported-files a { color:var(--text); }
      @media (max-width:900px) { #stocking-note { display:none; } }
    </style>'''
    html = html.replace("</head>", css + "</head>")
    html = html.replace('<header class="bar">', bridge + '<header class="bar">', 1)
    html = html.replace("/static/", base + "/static/")
    html = html.replace('id="btn-reveal" class="btn small">在文件夹中显示',
                        'id="btn-reveal" class="btn small">' + ('Download again' if english else '再次下载'))
    return html


def static_asset(name, base):
    if name not in FILES:
        raise ValueError("未知的编辑器资源")
    text = (ROOT / name).read_text(encoding="utf-8")
    if name == "app.js":
        start = text.index("async function openDialog() {")
        end = text.index("\nasync function openUpload(file)", start)
        text = text[:start] + '''async function openDialog() {
  // Browser file selection stays on the computer running this ComfyUI page.
  $('#file-input').click();
}
''' + text[end:]
        # The original file input already calls openUpload and checks unsaved work.
        text = replace_once(text,
            "const to = await request('POST', `/api/doc/${id}/export/ask`, { kind });",
            "const to = { path: '' };")
        text = replace_once(text, "    showExported(res);", """    showExported(res);
    const download = document.createElement('a');
    download.href = res.url; download.download = res.file;
    document.body.append(download); download.click(); download.remove();""")
        text = replace_once(text, "const file = document.createElement('span');", "const file = document.createElement('a');\n  file.href = res.url; file.download = res.file;")
        text = replace_once(text,
            "if (S.doc) request('POST', `/api/doc/${S.doc.id}/export/reveal`).catch((e) => flash(e.message, true));",
            "if (S.doc) request('POST', `/api/doc/${S.doc.id}/export/reveal`).then(r => { const a = document.createElement('a'); a.href = r.url; a.download = ''; a.click(); }).catch((e) => flash(e.message, true));")
        text = replace_once(text, "else if (ev.type === 'depth') lookUI.onEvent(ev);",
                            "else if (ev.type === 'depth') { lookUI.onEvent(ev); loadOptions().catch(() => {}); }")
        text += BRIDGE_JS
    if name in ("app.js", "look.js"):
        text = text.replace("/api/", base + "/api/")
    return text, FILES[name]


BRIDGE_JS = r'''
// The full editor owns its draft; only this action changes the ComfyUI widget.
const bridgeBase = location.pathname.replace(/\/$/, '');
const englishBridge = document.documentElement.lang.startsWith('en');
const note = $('#stocking-note');
let pendingApply = null;
window.addEventListener('message', event => {
  if (event.origin !== location.origin || event.source !== window.parent ||
      event.data?.type !== 'stocking-studio-applied' ||
      event.data.session !== bridgeBase.split('/').pop() ||
      !pendingApply || event.data.ticket !== pendingApply.ticket) return;
  const pending = pendingApply; pendingApply = null; clearTimeout(pending.timer);
  if (event.data.ok) pending.resolve();
  else pending.reject(new Error(event.data.detail || 'Apply rejected'));
});
async function loadOptions() {
  const options = await request('GET', '/api/options');
  $('#stocking-depth').checked = options.depth_enabled;
  $('#stocking-dark').checked = options.dark_adapt;
  const device = options.depth_inference?.device || options.models.device;
  $('#stocking-depth').title = `Depth Anything V2 Small · ${device}`;
}
for (const [id, key] of [['stocking-depth', 'depth_enabled'], ['stocking-dark', 'dark_adapt']]) {
  $(`#${id}`).addEventListener('change', async e => {
    try {
      await queue(() => request('PUT', '/api/options', { [key]: e.target.checked }));
      refresh(0); lookUI.onEvent({ type: 'depth' });
    } catch (error) { flash(error.message, true); await loadOptions(); }
  });
}
$('#stocking-apply').addEventListener('click', async () => {
  if (!S.doc) { flash(englishBridge ? 'Open an image first.' : '请先导入或连接图片。', true); return; }
  const b = $('#stocking-apply'); b.disabled = true;
  try {
    await queue(async () => {
      const params = lookUI.params();
      if (params) await request('PUT', `/api/doc/${S.doc.id}/look`, params);
    });
    const data = await request('POST', '/api/apply');
    await new Promise((resolve, reject) => {
      pendingApply = { ticket: data.ticket, resolve, reject,
        timer: setTimeout(() => { pendingApply = null; reject(new Error(englishBridge ? 'No confirmation from the node. Please apply again.' : '节点未确认，请重新应用。')); }, 15000) };
      window.parent.postMessage({ type: 'stocking-studio-apply', session: bridgeBase.split('/').pop(),
        project: data.project, ticket: data.ticket }, location.origin);
    });
    note.textContent = englishBridge ? 'Applied. Run the node to produce the result.' : '已应用。运行节点即可输出成品。';
    flash(note.textContent);
  } catch (error) { flash(error.message, true); }
  finally { b.disabled = false; }
});
$('#stocking-close').addEventListener('click', () => {
  window.parent.postMessage({ type: 'stocking-studio-close', session: bridgeBase.split('/').pop() }, location.origin);
});
loadOptions().catch(error => flash(error.message, true));
'''
