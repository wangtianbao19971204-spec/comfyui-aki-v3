"""Independent, file-only verification of the scoped P4 supplement."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

R = Path(__file__).resolve().parent
def read(name):
    return json.loads((R / name).read_text(encoding='utf-8-sig'))
def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))
def metrics(row):
    return {x['name']: x['value'] for x in row['cdp_metrics']}
def signature(listener):
    return tuple(listener.get(key) for key in ('target', 'source', 'scriptId', 'type', 'useCapture', 'passive', 'once', 'lineNumber', 'columnNumber'))
def component_zero(row):
    return all(row['dom'][key] == 0 for key in ('clothing_cards', 'clothing_descendants', 'clothing_overlays', 'workbench_count', 'workbench_descendants')) and row['dom']['workbench_visible'] is False

samples = read('lifecycle_supplement.json')
cycles = read('lifecycle_cycles.json')
collector = read('lifecycle_collector_snapshot.json')
cleanup = read('lifecycle_cleanup.json')
script_map = read('lifecycle_script_map.json')
services = [read(f'lifecycle_service_{cycle:02d}.json') for cycle in (0, 5, 10)]
run_baseline = read('before_guard.json')
checks = {}
checks['checkpoints_0_5_10'] = [r['cycle'] for r in samples] == [0, 5, 10]
checks['ten_fixed_hoodie_cycles_with_39_cards'] = [r['cycle'] for r in cycles] == list(range(1, 11)) and all(r['query'] == 'hoodie' and r['card_count'] == 39 for r in cycles)
checks['component_dom_zero_at_every_close'] = all(component_zero(r['closed']) for r in cycles)
checks['component_dom_zero_at_three_checkpoints'] = all(component_zero(r) for r in samples)
checks['same_5_second_settle_target'] = all(5000 <= r['settled_ms'] < 5100 for r in samples)
checks['document_element_count_stable'] = len({r['dom']['total_document_elements'] for r in samples}) == 1
checks['visible_focused_checkpoints'] = all(r['visibility'] == 'visible' and r['focused'] for r in samples)
checks['isolated_identity_and_prompt_values_unchanged'] = all(r['identity']['valid'] and r['identity']['prompts_unchanged'] and r['identity']['graph_id'] == 'a2b12b8e-d5c6-5b86-9dc9-26ab3378cbf8' and r['identity']['branch'] == 'a1' and r['identity']['positive'] == 'M9B synthetic 1063' and r['identity']['negative'] == '' for r in samples)
checks['source_map_includes_prompt_target'] = any(url.endswith('/prompt_target.js') for url in script_map['scripts'].values())
listener_sets = [sorted(signature(listener) for listener in row['attributed_global_listeners']) for row in samples]
checks['attributed_global_listener_sets_stable'] = listener_sets[0] == listener_sets[1] == listener_sets[2]
checks['only_expected_module_level_shared_listener_remains'] = all(len(row['attributed_global_listeners']) == 1 and row['attributed_global_listeners'][0]['target'] == 'window' and row['attributed_global_listeners'][0]['type'] == 'anima-tools-shared-prompts-updated' and row['attributed_global_listeners'][0]['source'].endswith('/anima_shared_prompt_data.js') and row['attributed_global_listeners'][0]['lineNumber'] == 22 for row in samples)
checks['listener_sources_match_runtime_script_map'] = all(script_map['scripts'].get(listener['scriptId']) == listener['source'] for row in samples for listener in row['attributed_global_listeners'])
checks['new_source_attributed_timers_zero_at_all_checkpoints'] = all(not row['source_attributed_new_timers']['active'] and row['source_attributed_new_timers']['active_timeouts'] == row['source_attributed_new_timers']['active_intervals'] == 0 for row in samples)
checks['timer_source_scope_has_no_untracked_strings'] = all(row['source_attributed_new_timers']['counts']['untracked_string_callbacks'] == 0 for row in samples)
event_groups = defaultdict(list)
for event in collector['timer_events']:
    event_groups[(event['id'], event['kind'], event['registered_ms'])].append(event)
checks['all_new_tracked_timers_have_one_terminal_event'] = len(event_groups) == 30 and all(Counter(event['event'] for event in group)['created'] == 1 and sum(event['event'] in ('fired', 'cleared') for event in group) == 1 for group in event_groups.values())
counts = collector['timers']['counts']
checks['timer_totals_balance'] = counts['timeout_created'] == 20 and counts['timeout_fired'] == counts['timeout_cleared'] == 10 and counts['interval_created'] == counts['interval_cleared'] == 10
checks['no_same_origin_requests_in_three_settle_windows'] = all(row['settle_requests'] == [] for row in samples)
checks['collector_sample_data_matches_saved_checkpoints'] = all(all(row[key] == stored[key] for key in stored) for row, stored in zip(samples, collector['samples']))
checks['timer_wrapper_cleanup_recorded'] = cleanup['cleaned'] is True and cleanup['timers']['active'] == []
expected_listener = [(row['pid'], row['create_time']) for row in run_baseline['listeners']]
checks['service_listener_identity_matches_run_start'] = all([(row['pid'], row['create_time'])] == expected_listener and row['listener_identity_matches_run_baseline'] for row in services)
checks['service_queue_empty_at_three_samples'] = all(row['queue_running'] == row['queue_pending'] == 0 for row in services)
checks['service_samples_are_cycle_paired'] = [row['cycle'] for row in services] == [0, 5, 10] and all(timestamp(service['rss_sampled_at']) >= timestamp(row['wall_time']) for row, service in zip(samples, services))

rows = []
for row, service in zip(samples, services):
    metric = metrics(row)
    rows.append({
        'cycle': row['cycle'], 'settled_ms': row['settled_ms'], 'browser_sampled_at': row['wall_time'],
        'component_dom': row['dom'], 'attributed_global_listener_count': len(row['attributed_global_listeners']),
        'active_new_attributed_timeout_count': row['source_attributed_new_timers']['active_timeouts'],
        'active_new_attributed_interval_count': row['source_attributed_new_timers']['active_intervals'],
        'cdp_js_heap_used_bytes': metric['JSHeapUsedSize'], 'cdp_js_heap_total_bytes': metric['JSHeapTotalSize'],
        'performance_memory_used_bytes': row['page_js_heap']['used_bytes'],
        'whole_page_cdp_listener_count_unattributed': metric['JSEventListeners'],
        'whole_page_cdp_nodes_unattributed': metric['Nodes'],
        'service_pid': service['pid'], 'service_rss_bytes': service['rss_bytes'], 'service_rss_sampled_at': service['rss_sampled_at'],
        'service_pairing_lag_seconds': (timestamp(service['rss_sampled_at']) - timestamp(row['wall_time'])).total_seconds(),
        'queue_running': service['queue_running'], 'queue_pending': service['queue_pending']
    })
boundaries = [
    'Acceptance is scoped to ten clothing open/hoodie-query/close cycles on the sanitized workflow, with three closed-state checkpoints. It is not whole-application performance certification.',
    'Timer attribution covers registrations after collector installation with matching clothing/shared/workbench source frames only. Pre-existing timers and other modules are not enumerated.',
    'Window/document listener attribution includes the captured prompt_target scriptId. The surviving shared update listener is intentionally module-scoped; detached element retention is not ruled out by a zero live DOM count.',
    'CDP whole-page listeners grow 17126 -> 17329 -> 19008 and CDP Nodes grow 41634 -> 41938 -> 48608. The growth is unassigned; these counts are not evidence of stable whole-page resources or a clothing leak/no-leak result.',
    'CDP heap rises between 0 and 5 then slightly falls at 10; no forced GC or retaining-path proof was performed. Service RSS movement and page JS heap are separate measurements. Neither establishes absence of leaks.',
    'Service RSS is paired 7.07/9.43/9.22 seconds after the corresponding browser checkpoint, not sampled atomically at the 5-second boundary. Actual timestamps and queue states are retained.',
    'Dedicated renderer PID/RSS remains unavailable. performance.memory and CDP heap are distinct sources and must not be numerically combined.',
    'The previously accepted M9b 60-second idle receipt is separate evidence; this supplement only certifies its own three five-second settle windows.',
    'Global final source/formal-data/service gates and overall M9 completion remain the main executor responsibility; this report does not edit STATE or assert whole-plan completion.'
]
files = ['lifecycle_supplement.json', 'lifecycle_cycles.json', 'lifecycle_collector_snapshot.json', 'lifecycle_script_map.json', 'lifecycle_cleanup.json', 'lifecycle_service_00.json', 'lifecycle_service_05.json', 'lifecycle_service_10.json', 'lifecycle_collector.js']
result = {
    'status': 'accepted_scoped_resource_observation' if all(checks.values()) else 'failed',
    'reviewed_at': datetime.now(timezone.utc).isoformat(), 'reviewer': 'review_validation_plan',
    'method': 'Independent file-only evidence cross-check; no browser or production operation',
    'checks': checks, 'checkpoint_rows': rows, 'listener_script_map': script_map['scripts'],
    'surviving_listener_signatures': [dict(zip(('target','source','scriptId','type','useCapture','passive','once','lineNumber','columnNumber'), sig)) for sig in listener_sets[0]],
    'tracked_timer_totals': counts, 'boundaries': boundaries,
    'evidence_sha256': {name: hashlib.sha256((R / name).read_bytes()).hexdigest() for name in files}
}
(R / 'lifecycle_acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
lines = [
    'M9c P4 补充资源观察：独立验收',
    '状态：' + result['status'],
    '范围：脱敏工作流中服装入口10次打开、hoodie查询、关闭；每次39卡；未进行生产编辑或浏览器操作。',
    f'检查：{sum(checks.values())}/{len(checks)} 通过。',
    '0/5/10：服装overlay、卡片、组件后代及工作台DOM均为0；document元素数均20223；提示词与graph/a1身份保持。',
    '来源归因window/document监听器均只剩1个正常模块级shared更新处理器；过滤映射包含prompt_target.js。',
    '本轮新增来源timer：20个timeout=10触发+10取消；10个interval全部取消；三个检查点活跃均0。清理回执cleaned=true。',
    '',
    'cycle | settle_ms | CDP JS heap used bytes | performance.memory used bytes | service RSS bytes | RSS pairing lag s',
]
for row in rows:
    lines.append(f"{row['cycle']} | {row['settled_ms']:.1f} | {row['cdp_js_heap_used_bytes']} | {row['performance_memory_used_bytes']} | {row['service_rss_bytes']} | {row['service_pairing_lag_seconds']:.3f}")
lines += [
    '',
    'CDP heap：176.0 → 200.7 → 199.4 MB；服务RSS：1996.1 → 1996.2 → 1584.1 MB（十进制MB）。服务PID24420/create_time与本轮基线一致，三次queue均0/0。',
    '全页CDP listeners 17126 → 17329 → 19008、Nodes 41634 → 41938 → 48608增长，未归因，不能包装为全页稳定或无泄漏。',
    '三个浏览器采样实际等待5004.0/5001.4/5007.0ms。RSS经工具配对分别晚7.070/9.435/9.222秒，非同一瞬间或精确5秒采样。',
    '仅接受本轮对应组件DOM、已归因全局监听器及安装后新增timer的关闭状态；不保证所有detached对象已回收，不宣称无内存泄漏。',
    '未强制GC，renderer RSS不可可靠映射；两种JS堆指标分开保留。旧M9b的60秒空闲证据独立引用，本补充仅含三个5秒稳定窗口。',
    '本报告不代替最终源码/正式资料守卫、STATE收尾或整体计划完成判定。',
]
if not all(checks.values()):
    lines += ['失败项：' + ', '.join(key for key, passed in checks.items() if not passed)]
(R / 'lifecycle_acceptance.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'status': result['status'], 'passed': sum(checks.values()), 'checks': len(checks), 'failed': [key for key, value in checks.items() if not value]}, ensure_ascii=False))
if not all(checks.values()):
    raise SystemExit(1)
