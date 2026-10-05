"""Instrument the workbench at runtime: polling cost, DOM footprint, and open/close lifecycle.

Measures rather than guesses. Read-only: no node values are written.
"""
from __future__ import annotations

import json
import pathlib
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

HERE = pathlib.Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8188/'

options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1700,1100')
options.add_argument('--disable-gpu')
options.add_argument('--no-first-run')
options.add_argument('--user-data-dir=' + str(HERE / 'perf_profile'))

driver = webdriver.Chrome(options=options)
report = {}
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

    # Baselines before the workbench exists.
    report['baseline'] = driver.execute_script("""
        return {
            domNodes: document.getElementsByTagName('*').length,
            timersCreated: window.__timerCount || null,
            hasWorkbench: Boolean(document.querySelector('#unified-workbench')),
        };
    """)

    # Instrument setInterval/setTimeout and requestAnimationFrame callbacks to count work.
    driver.execute_script("""
        window.__stats = {intervalFires: {}, timeoutFires: 0, rafFires: 0, longTasks: 0};
        window.__openMs = null;
        const realSetInterval = window.setInterval;
        const realSetTimeout = window.setTimeout;
        window.setInterval = function (fn, ms, ...rest) {
            const wrapped = function (...args) {
                const key = String(ms);
                window.__stats.intervalFires[key] = (window.__stats.intervalFires[key] || 0) + 1;
                return fn.apply(this, args);
            };
            return realSetInterval.call(window, wrapped, ms, ...rest);
        };
        window.setTimeout = function (fn, ms, ...rest) {
            if (typeof fn === 'function') {
                const wrapped = function (...args) { window.__stats.timeoutFires++; return fn.apply(this, args); };
                return realSetTimeout.call(window, wrapped, ms, ...rest);
            }
            return realSetTimeout.apply(window, arguments);
        };
        try {
            new PerformanceObserver(list => { window.__stats.longTasks += list.getEntries().length; })
                .observe({entryTypes: ['longtask']});
        } catch (error) { window.__stats.longTaskUnsupported = String(error); }
    """)

    # Time how long opening the workbench takes.
    open_ms = driver.execute_async_script("""
        const done = arguments[arguments.length - 1];
        const t0 = performance.now();
        Promise.resolve(window.unifiedOpenWorkbench({page: 'workspace'}))
            .then(() => {
                // Let the first paint settle before measuring.
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    done(Math.round(performance.now() - t0));
                }));
            })
            .catch(error => done('error: ' + String(error)));
    """)
    time.sleep(4)
    report['open'] = {'openMs': open_ms,
                      'domNodesAfterOpen': driver.execute_script("return document.getElementsByTagName('*').length;")}

    # Sample polling behaviour over 6 seconds while the workbench sits idle.
    before = driver.execute_script("return JSON.parse(JSON.stringify(window.__stats));")
    time.sleep(6)
    after = driver.execute_script("return JSON.parse(JSON.stringify(window.__stats));")
    report['idle6s'] = {
        'intervalFiresByMs': {k: after['intervalFires'].get(k, 0) - before['intervalFires'].get(k, 0)
                              for k in set(after['intervalFires']) | set(before['intervalFires'])},
        'timeoutFires': after['timeoutFires'] - before['timeoutFires'],
        'longTasks': after['longTasks'] - before['longTasks'],
        'longTaskSupported': 'longTaskUnsupported' not in after,
    }

    # Close and sample again: does polling stop and does the DOM shrink?
    driver.execute_script("""
        const wb = document.querySelector('#unified-workbench');
        const close = [...wb.querySelectorAll('button')].find(b => /关闭工作台/.test(b.textContent));
        if (close) close.click();
    """)
    time.sleep(2)
    dom_after_close = driver.execute_script("return document.getElementsByTagName('*').length;")
    before2 = driver.execute_script("return JSON.parse(JSON.stringify(window.__stats));")
    time.sleep(6)
    after2 = driver.execute_script("return JSON.parse(JSON.stringify(window.__stats));")
    report['closed'] = {
        'workbenchPresent': driver.execute_script("return Boolean(document.querySelector('#unified-workbench'));"),
        'domNodes': dom_after_close,
        'intervalFiresByMs': {k: after2['intervalFires'].get(k, 0) - before2['intervalFires'].get(k, 0)
                              for k in set(after2['intervalFires']) | set(before2['intervalFires'])},
        'timeoutFires': after2['timeoutFires'] - before2['timeoutFires'],
        'longTasks': after2['longTasks'] - before2['longTasks'],
    }

    # Reopen to confirm the DOM footprint is stable across cycles (no growth).
    driver.execute_script("window.unifiedOpenWorkbench({page: 'workspace'});")
    time.sleep(4)
    report['reopen'] = {'domNodes': driver.execute_script("return document.getElementsByTagName('*').length;")}

    print(json.dumps(report, ensure_ascii=False, indent=2)[:3000])
finally:
    try:
        driver.quit()
    except Exception:
        pass
(HERE / 'perf_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
