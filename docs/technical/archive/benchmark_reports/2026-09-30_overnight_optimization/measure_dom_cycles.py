"""Does the DOM footprint grow without bound across open/close cycles?

If the count plateaus, detached nodes are simply awaiting GC. If it climbs linearly, there
is a real leak worth fixing.
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
samples = []
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
    time.sleep(3)

    node_count = lambda: driver.execute_script("return document.getElementsByTagName('*').length;")
    samples.append({'phase': 'baseline', 'nodes': node_count()})

    for cycle in range(1, 6):
        driver.execute_script("window.unifiedOpenWorkbench({page: 'workspace'});")
        time.sleep(3)
        opened = node_count()
        driver.execute_script("""
            const wb = document.querySelector('#unified-workbench');
            const close = wb && [...wb.querySelectorAll('button')].find(b => /关闭工作台/.test(b.textContent));
            if (close) close.click();
        """)
        time.sleep(2.5)
        closed = node_count()
        present = driver.execute_script("return Boolean(document.querySelector('#unified-workbench'));")
        samples.append({'phase': f'cycle{cycle}', 'opened': opened, 'closed': closed, 'workbenchPresent': present})
        print(f'cycle {cycle}: opened={opened} closed={closed} present={present}')

finally:
    try:
        driver.quit()
    except Exception:
        pass

(HERE / 'dom_cycle_results.json').write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')
print()
print('baseline:', samples[0]['nodes'])
closed_series = [s['closed'] for s in samples[1:]]
print('closed-node series:', closed_series)
if len(closed_series) >= 2:
    growth = closed_series[-1] - closed_series[0]
    print(f'growth across {len(closed_series)} close cycles: {growth:+d} nodes')
    print('verdict:', 'PLATEAUS (GC-able detachment)' if growth < 500 else 'GROWS (likely leak)')
