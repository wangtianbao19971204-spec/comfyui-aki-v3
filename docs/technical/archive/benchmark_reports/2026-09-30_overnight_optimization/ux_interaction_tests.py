"""Five real-browser interaction tests against the workbench, looking for unreasonable behaviour.

Each test drives the live UI the way a user would and records timings, state changes, and
feedback. Writes go only to an isolated clone target; the user's own nodes are never written.
"""
from __future__ import annotations

import json
import pathlib
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

HERE = pathlib.Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8188/'
CLONE_ID = 990007

options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1700,1100')
options.add_argument('--disable-gpu')
options.add_argument('--no-first-run')
options.add_argument('--user-data-dir=' + str(HERE / 'ux_profile'))

driver = webdriver.Chrome(options=options)
report = {'tests': []}


def record(test, observations, friction=None):
    entry = {'test': test, 'observations': observations, 'friction': friction or []}
    report['tests'].append(entry)
    print(f'--- {test}')
    for obs in observations:
        print(f'    {obs}')
    for item in entry['friction']:
        print(f'    [FRICTION] {item}')
    print()


def timed(fn):
    start = time.time()
    value = fn()
    return value, round((time.time() - start) * 1000)


try:
    driver.get(URL)
    for _ in range(120):
        if driver.execute_script('return Boolean(window.app && window.app.graph && window.unifiedDailyControls);'):
            break
        time.sleep(1)
    driver.execute_async_script("""
        const done = arguments[arguments.length - 1];
        fetch('/api/userdata/workflows%2F' + encodeURIComponent('UAP统一生产工作台_v2.json'))
            .then(r => r.json())
            .then(async graph => { await app.loadGraphData(graph, true, false, 'uap'); done(true); })
            .catch(error => done(String(error)));
    """)
    time.sleep(2)
    driver.execute_script("""
        for (const extension of app.extensions || []) {
            if (extension.afterConfigureGraph) extension.afterConfigureGraph({workflow: app.graph, options: {}});
        }
    """)
    time.sleep(2)

    # Isolated write target + guard for the user's node.
    driver.execute_script("""
        const orig = app.graph._nodes.find(n => n.type === 'WeiLinPromptUI' && n.mode === 0);
        const ow = orig.widgets.find(w => w.name === 'positive');
        window.__orig = {node: orig, w: ow, v: String(ow.value ?? '')};
        const clone = new (orig.constructor)('WeiLinPromptUI');
        clone.id = arguments[0]; clone.title = '[UX 目标]'; clone.mode = 0;
        app.graph.add(clone); clone.graph = app.graph;
        clone.widgets.find(w => w.name === 'positive').value = 'UX-BASE';
        const state = app.graph.extra.uap_workbench;
        const branch = state.branches.find(b => b.id === state.activeBranch);
        window.__branchNodeIds = [...branch.nodeIds];
        branch.nodeIds.push(clone.id);
        window.__clone = clone;
    """, CLONE_ID)

    # ---------- Test 1: first open, what a user sees and can do ----------
    opened, open_ms = timed(lambda: driver.execute_script("window.unifiedOpenWorkbench({page: 'workspace'});"))
    time.sleep(5)
    state = driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const vis = n => n.offsetParent !== null;
        const tabs = [...wb.querySelectorAll('[data-uw^="page-"]')].map(b => ({t: b.textContent.trim(), pressed: b.getAttribute('aria-pressed')}));
        const tasks = [...wb.querySelectorAll('[data-uw^="task-"]')].map(b => ({t: b.textContent.trim(), pressed: b.getAttribute('aria-pressed'), disabled: b.disabled}));
        const banners = [...wb.querySelectorAll('.uw-component-notice')].filter(vis).map(n => n.textContent.trim());
        const runButtons = [...wb.querySelectorAll('button')].filter(b => vis(b) && /^开始/.test(b.textContent.trim()))
            .map(b => ({t: b.textContent.trim(), disabled: b.disabled}));
        return {tabs, tasks, banners, runButtons,
                heading: (wb.querySelector('h2') || {}).textContent || null,
                focusInWorkbench: wb.contains(document.activeElement)};
    """)
    friction = []
    if not state['focusInWorkbench']:
        friction.append('打开后焦点不在工作台内（键盘用户需要额外 Tab 才能进入）')
    if state['banners']:
        friction.append(f"启动时出现组件告警横幅：{state['banners']}")
    disabled_tasks = [t['t'] for t in state['tasks'] if t['disabled']]
    if disabled_tasks:
        friction.append(f'任务按钮初始禁用但未见原因：{disabled_tasks}')
    record('1. 首次打开工作台', [
        f'打开耗时 {open_ms} ms',
        f'标题：{state["heading"]}',
        f'页面标签：{[t["t"] for t in state["tabs"]]}',
        f'任务标签（是否按下/禁用）：{[(t["t"], t["pressed"], t["disabled"]) for t in state["tasks"]]}',
        f'可见运行按钮：{[(b["t"], b["disabled"]) for b in state["runButtons"]]}',
        f'焦点是否落在工作台内：{state["focusInWorkbench"]}',
        f'组件告警横幅：{state["banners"] or "无"}',
    ], friction)

    # ---------- Test 2: search feedback ----------
    driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const tab = [...wb.querySelectorAll('button')].find(b => b.dataset && b.dataset.uw === 'page-library');
        if (tab) tab.click();
    """)
    time.sleep(4)
    search_timing = driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const input = wb.querySelector('input[aria-label="搜索当前资料库与筛选范围"]') || wb.querySelector('input[aria-label="跨来源搜索资料、Tag 和模型"]');
        if (!input) return {why: 'no search input'};
        const t0 = performance.now();
        input.value = 'cup';
        input.dispatchEvent(new Event('input', {bubbles: true}));
        // Observe whether any "searching" feedback appears within the debounce window.
        const seen = [];
        const deadline = performance.now() + 1200;
        return new Promise(resolve => {
            const poll = () => {
                const statuses = [...wb.querySelectorAll('[role="status"]')].map(n => n.textContent.trim()).filter(Boolean);
                const busy = /搜索|加载|查询/.test(statuses.join(' '));
                if (busy) seen.push(statuses.slice(-1)[0]);
                if (performance.now() > deadline) return resolve({feedbackShown: seen.length > 0, samples: seen.slice(0, 3),
                                                                 statusesAtEnd: statuses.slice(-3), elapsed: Math.round(performance.now() - t0)});
                setTimeout(poll, 50);
            };
            poll();
        });
    """)
    time.sleep(4)
    rows = driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        return {cards: [...wb.querySelectorAll('button')].filter(b => b.offsetParent && /加入待用列表/.test(b.textContent)).length};
    """)
    friction = []
    if isinstance(search_timing, dict) and not search_timing.get('feedbackShown'):
        friction.append('搜索期间没有任何"正在搜索"反馈，用户无法区分"还在搜"和"没结果"')
    record('2. 资料库搜索反馈', [
        f'搜索防抖窗口内的反馈：{json.dumps(search_timing, ensure_ascii=False)}',
        f'搜索后结果数：{rows}',
    ], friction)

    # ---------- Test 3: insertion options while nothing is selected ----------
    driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const cards = [...wb.querySelectorAll('button')].filter(b => b.offsetParent && /加入待用列表/.test(b.textContent));
        cards.slice(0, 2).forEach(b => b.click());
    """)
    time.sleep(2)
    driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const btn = [...wb.querySelectorAll('button')].find(b => /待用列表/.test(b.textContent));
        if (btn) btn.click();
    """)
    time.sleep(2.5)
    initial = driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const vis = n => n.offsetParent !== null;
        return {
            applyButtons: [...wb.querySelectorAll('button')].filter(b => vis(b) && /^应用到目标$/.test(b.textContent.trim())).length,
            hint: [...wb.querySelectorAll('p')].map(n => n.textContent.trim()).filter(t => /目标|方向/.test(t)).slice(-2),
            weights: [...wb.querySelectorAll('input[aria-label="本次权重"]')].filter(vis).length,
            preview: (() => { const p = wb.querySelector('.uw-pending-preview'); return p ? p.textContent.length : null; })(),
        };
    """)
    friction = []
    if initial['applyButtons'] == 0:
        friction.append('待用列表里看不到"应用到目标"按钮，只能靠底部下拉选目标；没有说明指向那个下拉')
    record('3. 待用列表（未选目标时）', [
        f'"应用到目标"按钮数：{initial["applyButtons"]}',
        f'权重输入数：{initial["weights"]}',
        f'预览长度：{initial["preview"]}',
        f'提示文案：{initial["hint"]}',
    ], friction)

    # ---------- Test 4: theme switching feedback in both modes ----------
    theme_rows = []
    for mode in ('full', 'half'):
        if mode == 'half':
            driver.execute_script("""
                const wb = document.querySelector('#unified-workbench');
                const close = [...wb.querySelectorAll('button')].find(b => /关闭工作台/.test(b.textContent));
                if (close) close.click();
                if (window.unifiedDailyControls) window.unifiedDailyControls.show(true);
            """)
            time.sleep(3)
        for theme in ('☼ 白天', '☾ 夜间', '✦ 多色'):
            started = time.time()
            picked = driver.execute_script("""
                const root = document.querySelector('#unified-workbench') || document.querySelector('#uap-daily-desk');
                const select = root && root.querySelector('select[aria-label="界面主题"]');
                if (!select) return {ok: false, why: 'no theme select'};
                const option = [...select.options].find(o => o.textContent.trim() === arguments[0]);
                if (!option) return {ok: false, why: 'no option'};
                select.value = option.value;
                select.dispatchEvent(new Event('change', {bubbles: true}));
                if (select.onchange) select.onchange();
                return {ok: true, value: select.value};
            """, theme)
            time.sleep(1.5)
            applied = driver.execute_script("""
                const desk = document.querySelector('#uap-daily-desk');
                const wb = document.querySelector('#unified-workbench');
                const target = (wb && wb.offsetParent) ? wb : desk;
                if (!target) return null;
                const s = getComputedStyle(target);
                return {bg: s.backgroundColor, color: s.color};
            """)
            theme_rows.append({'mode': mode, 'theme': theme, 'picked': picked, 'applied': applied,
                               'ms': round((time.time() - started) * 1000)})
    friction = []
    for row in theme_rows:
        if row['picked'] and row['picked'].get('ok') and row['applied'] and row['applied'].get('color') is None:
            friction.append(f"主题 {row['mode']}/{row['theme']} 切换后取不到配色")
    record('4. 三主题 × 半屏/完整', [json.dumps(r, ensure_ascii=False) for r in theme_rows], friction)

    # ---------- Test 5: empty / error states ----------
    driver.get(URL)
    time.sleep(4)
    for _ in range(90):
        if driver.execute_script('return Boolean(window.app && window.unifiedDailyControls);'):
            break
        time.sleep(1)
    empty = driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        if (!wb) return {why: 'workbench not reopened'};
        const btn = [...wb.querySelectorAll('button')].find(b => /待用列表/.test(b.textContent));
        if (btn) btn.click();
        return {ok: true};
    """)
    time.sleep(4)
    empty_state = driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const vis = n => n.offsetParent !== null;
        const texts = [...wb.querySelectorAll('p')].filter(vis).map(n => n.textContent.trim()).filter(Boolean);
        return {
            counter: (() => { const b = [...wb.querySelectorAll('button')].find(b => /待用列表/.test(b.textContent)); return b ? b.textContent.trim() : null; })(),
            guidance: texts.filter(t => /待用|加入|资料|Tag/.test(t)).slice(0, 3),
            anyEmptyWarning: texts.some(t => /空/.test(t)),
        };
    """)
    friction = []
    if not empty_state['guidance']:
        friction.append('待用列表为空时没有给出"从哪里加入"的指引')
    record('5. 空状态（新会话重开）', [
        f'计数器：{empty_state["counter"]}',
        f'指引文案：{empty_state["guidance"]}',
        f'是否出现"空"提示：{empty_state["anyEmptyWarning"]}',
    ], friction)

    report['user_node_untouched'] = driver.execute_script("return String(window.__orig?.w?.value ?? '') === window.__orig?.v;")

finally:
    try:
        driver.execute_script("""
            if (window.__orig) window.__orig.w.value = window.__orig.v;
            if (window.__clone) { try { app.graph.remove(window.__clone); } catch (e) {} }
        """)
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass

report['all_friction'] = [f for t in report['tests'] for f in t['friction']]
(HERE / 'ux_interaction_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('=== 汇总：全部摩擦点 ===')
for item in report['all_friction']:
    print(' *', item)
print()
print('用户节点未被触碰:', report.get('user_node_untouched'))
