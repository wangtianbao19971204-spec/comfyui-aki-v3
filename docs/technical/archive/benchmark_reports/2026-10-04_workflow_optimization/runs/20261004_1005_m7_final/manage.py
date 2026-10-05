import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent
PLAN = OUT.parent.parent
ROOT = PLAN.parent.parent
sys.path.insert(0, str(PLAN / 'runs/20261004_0905_m6_dependencies'))
from guard import live, read, write, sha

NAMES = ['UAP统一生产工作台_v2.json', '生产套件_01_Anima原版_LoRA生产_v2.json', '生产套件_02_Anima2.9B_动漫生产_v2.json', '生产套件_03_Krea2_一体化生产_v2.json']
TARGETS = [ROOT / 'production_tools/templates' / n for n in NAMES]
TARGETS += [ROOT / 'production_tools/插件处置表.md']


def current_guard(expected):
    current = live()
    assert {p: sha(Path(p)) for p in expected} == expected
    assert not current['queue']['queue_running'] and not current['queue']['queue_pending']
    return current


def prune(before):
    after = copy.deepcopy(before)
    titles = {g['title'] for g in before['groups'] if g['title'].startswith('SW-00B ')}
    allowed = {'AnimaCharacterTagSelector', 'AnimaClothingTagSelector', 'AnimaPoseTagSelector', 'AnimaPoseTagSelectorPlus', 'AnimaBackgroundTagSelectorPlus', 'AnimaPromptComposer', 'ShowText|pysssss'}
    removed = set()
    for group in before['groups']:
        if group['title'] not in titles:
            continue
        x, y, w, h = group['bounding']
        for node in before['nodes']:
            if node['type'] in allowed and x <= node['pos'][0] < x+w and y <= node['pos'][1] < y+h:
                assert node.get('mode') == 2
                removed.add(node['id'])
    links = [e for e in before['links'] if e[1] in removed or e[3] in removed]
    assert all(e[1] in removed and e[3] in removed for e in links), 'Obsolete helper unexpectedly connects to retained production nodes'
    after['nodes'] = [n for n in after['nodes'] if n['id'] not in removed]
    after['links'] = [e for e in after['links'] if e not in links]
    after['groups'] = [g for g in after['groups'] if g['title'] not in titles]
    controllers = []
    for node in after['nodes']:
        if 'Fast Groups' in node['type']:
            prop = node.get('properties', {})
            sort = prop.get('customSortAlphabet', '')
            clean = ','.join(v for v in sort.split(',') if v not in titles)
            if sort != clean:
                prop['customSortAlphabet'] = clean
                controllers.append(node['id'])
    for branch in after['extra'].get('uap_workbench', {}).get('branches', []):
        branch['nodeIds'] = [i for i in branch['nodeIds'] if i not in removed]
        for stage in branch.get('stages', []):
            stage['groups'] = [t for t in stage['groups'] if t not in titles]
    suite = after['extra'].get('production_suite', {})
    if 'safe_mute_groups' in suite:
        suite['safe_mute_groups'] = [t for t in suite['safe_mute_groups'] if t not in titles]
    # Compare all retained node payloads, including nested graphs and model/prompt settings.
    prior = {n['id']: n for n in before['nodes']}
    for node in after['nodes']:
        expected = copy.deepcopy(prior[node['id']])
        if node['id'] in controllers:
            expected['properties']['customSortAlphabet'] = node['properties']['customSortAlphabet']
        assert node == expected
    assert after.get('definitions') == before.get('definitions')
    assert after['links'] == [e for e in before['links'] if e not in links]
    for key in before:
        if key not in ['nodes', 'links', 'groups', 'extra']:
            assert before[key] == after[key]
    return after, dict(removed_nodes=sorted(removed), removed_links=[e[0] for e in links], removed_groups=sorted(titles), controllers=controllers, retained_node_payloads_equal=True, nested_graphs_equal=True, retained_links_equal=True)


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'start':
        state = read(PLAN / 'STATE.json')
        assert state['current_phase'] == 'M7' and state['active_run'] is None
        assert not list((ROOT / 'benchmark_reports').rglob('run.lock'))
        assert not list((ROOT / '_codex_artifacts').rglob('run.lock'))
        base = read(PLAN / 'CURRENT_BASELINE.json')
        current = current_guard(base['files'])
        lock = dict(owner_thread=state['owner_thread'], scope='M7 four SW-00B template corrections, final regression and daily maintenance transition', target_files=[str(p) for p in TARGETS], started_at=current['at'], active_run=str(OUT))
        with (PLAN / 'run.lock').open('x', encoding='utf8') as f:
            json.dump(lock, f, ensure_ascii=False, indent=2)
        (OUT / 'before').mkdir()
        for name in ['PLAN.json', 'STATE.json', 'CONTINUATION.txt', 'CURRENT_BASELINE.json', 'ACCEPTED_BASELINE.json']:
            shutil.copy2(PLAN / name, OUT / 'before' / name)
        for path in TARGETS:
            shutil.copy2(path, OUT / 'before' / path.name)
        write(OUT / 'baseline.json', dict(files=base['files'], live=current, target_files=[str(p) for p in TARGETS]))
        state.update(status='in_progress', active_run=str(OUT), next_action='Stage and validate four SW-00B template prunes, then fresh browser acceptance and cumulative M7 closeout.')
        write(PLAN / 'STATE.json', state)
    elif action == 'stage':
        (OUT / 'candidate').mkdir(exist_ok=True)
        reports = []
        m6 = read(PLAN / 'runs/20261004_0905_m6_dependencies/template_parity.json')
        for name in NAMES:
            before = read(OUT / 'before' / name)
            candidate, report = prune(before)
            assert len(report['removed_nodes']) == (16 if name.startswith('UAP') else 6 if '03_' in name else 5)
            expected = next(x for x in m6 if Path(x['template']).name == name)
            assert report['removed_nodes'] == sorted(n['id'] for n in expected['template_only_nodes'])
            assert prune(candidate)[0] == candidate
            write(OUT / 'candidate' / name, candidate)
            reports.append(dict(file=name, before=sha(OUT / 'before' / name), after=sha(OUT / 'candidate' / name), **report))
        text = (OUT / 'before/插件处置表.md').read_text('utf8')
        old = '收尾待办：4 份主套件模板仍保留正式工作流已移除的 SW-00B 辅助节点；重新导入模板会带回旧入口。M7 先核对并同步这一结构差异，保留每份文件各自的正文、模型与参数；不直接用用户工作流整份覆盖模板。'
        new = 'M7 已同步 4 份主模板的 SW-00B 清理：移除 32 个未接入生产链的旧辅助节点及内部连线、分组和导航引用。保留各模板自己的正文、模型、参数与其余节点/连线；不把模板与用户图的其他差异强行统一。验收与精确回滚见 `../benchmark_reports/2026-10-04_workflow_optimization/runs/20261004_1005_m7_final/`。'
        assert text.count(old) == 1
        (OUT / 'candidate/插件处置表.md').write_text(text.replace(old, new), encoding='utf8')
        write(OUT / 'pruning_validation.json', dict(status='OFFLINE_PASS', files=reports, removed_node_count=sum(len(x['removed_nodes']) for x in reports), production_graph_files_written=0))
    elif action == 'publish':
        assert read(PLAN / 'run.lock')['active_run'] == str(OUT)
        locks = list((ROOT / 'benchmark_reports').rglob('run.lock')) + list((ROOT / '_codex_artifacts').rglob('run.lock'))
        assert locks == [PLAN / 'run.lock'], locks
        assert not (OUT / 'release.json').exists()
        base = read(OUT / 'baseline.json')
        current = current_guard(base['files'])
        assert current['owners'] == base['live']['owners']
        assert read(OUT / 'browser_candidate_acceptance.json')['passed']
        cleanup = read(OUT / 'browser_cleanup.json')
        assert cleanup['passed'] and cleanup['remaining_agent_tabs'] == []
        for row in read(OUT / 'pruning_validation.json')['files']:
            assert sha(OUT / 'candidate' / row['file']) == row['after']
        before = {str(p): base['files'][str(p)] for p in TARGETS}
        after = {str(p): sha(OUT / 'candidate' / p.name) for p in TARGETS}
        assert all(sha(OUT / 'before' / p.name) == before[str(p)] for p in TARGETS)
        write(OUT / 'rollback_preflight.json', dict(before=before, after=after, restart_required=False))
        for path in TARGETS:
            shutil.copyfile(OUT / 'candidate' / path.name, path)
        assert all(sha(Path(p)) == h for p, h in after.items())
        write(OUT / 'release.json', dict(at=datetime.now().astimezone().isoformat(), before=before, after=after, status='published_awaiting_final_guard'))
    elif action == 'rollback':
        release = read(OUT / 'release.json')
        assert all(sha(Path(p)) == h for p, h in release['after'].items())
        assert all(sha(OUT / 'before' / Path(p).name) == h for p, h in release['before'].items())
        for path in release['before']:
            shutil.copyfile(OUT / 'before' / Path(path).name, path)
        write(OUT / 'rollback.json', dict(at=datetime.now().astimezone().isoformat(), restored=release['before']))
    elif action == 'verify':
        base = read(OUT / 'baseline.json')
        release = read(OUT / 'release.json') if (OUT / 'release.json').exists() else dict(after={})
        expected = {**base['files'], **release['after']}
        current = current_guard(expected)
        assert current['owners'] == base['live']['owners']
        write(OUT / 'final_guard.json', dict(at=current['at'], files=len(expected), changed=release['after'], unchanged=len(expected)-len(release['after']), drift=[], live=current))
    print({'action': action, 'status': 'pass'})
