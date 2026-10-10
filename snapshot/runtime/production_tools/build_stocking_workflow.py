"""Create the independent repair workflow; never rebuild any existing production graph."""
import argparse
import json
from pathlib import Path


def build():
    edit, output = '01 原图与纹理修复', '03 成品与透明图层'
    studio = dict(id=1, type='StockingTextureStudio', title='丝袜纹理修复 · 打开完整编辑器',
                  pos=[80, 160], size=[420, 470], flags={}, order=0, mode=0,
                  inputs=[dict(name='image', type='IMAGE', shape=7, link=None),
                          dict(name='depth', type='IMAGE', shape=7, link=None),
                          dict(name='project_json', type='STRING', widget={'name': 'project_json'}, link=None)],
                  outputs=[dict(name=name, type=kind, links=links) for name, kind, links in
                           [('成品', 'IMAGE', [1]), ('仅丝袜透明图层', 'IMAGE', [2]),
                            ('图层透明度', 'MASK', None), ('问题标记', 'IMAGE', None), ('处理说明', 'STRING', None)]],
                  properties={'Node name for S&R': 'StockingTextureStudio', 'uap_layout_group': edit},
                  widgets_values=['{}'])
    saves = [dict(id=i, type='SaveImage', title=title, pos=[x, 160], size=[360, 470], flags={},
                  order=i-1, mode=0, inputs=[dict(name='images', type='IMAGE', link=i-1)], outputs=[],
                  properties={'Node name for S&R': 'SaveImage', 'uap_layout_group': output},
                  widgets_values=[prefix]) for i, x, title, prefix in
                 [(2, 630, '修复成品', 'StockingRepair/finished'),
                  (3, 1060, '仅丝袜透明图层', 'StockingRepair/stockings')]]
    note = dict(id=4, type='Note', pos=[80, 690], size=[420, 230], flags={}, order=3, mode=0,
                inputs=[], outputs=[], properties={'uap_layout_group': edit},
                widgets_values=['1. 打开完整编辑器，直接导入 PNG / JPG / PSD。\n'
                                '2. 双腿分别修边，检查袜口、脚部与遮挡；各画走向。\n'
                                '3. 在纹理页选择样式；摩尔纹需先完成深度计算。\n'
                                '4. 点击“应用到节点”，关闭编辑器后运行。\n'
                                '5. 成品和透明丝袜图层分别保存到 StockingRepair。\n'
                                '摩尔纹默认关闭；油光为试验效果，先用低强度预览。\n'
                                'PSD 在编辑器内导出。继续放大时切换到 2× / 4× 并载入成品。\n'
                                '此工作流独立运行，不包含生成、精修或放大步骤。'])
    branch = dict(id='stocking', label='丝袜纹理修复', group=edit, nodeIds=[1, 2, 3, 4],
                  modes={str(i): 0 for i in range(1, 5)}, stages=[
                      dict(id='daily', label='导入与修复', groups=[edit]),
                      dict(id='compare', label='成品与图层', groups=[output])])
    return dict(revision=0, last_node_id=4, last_link_id=2, nodes=[studio, *saves, note],
                links=[[1, 1, 0, 2, 0, 'IMAGE'], [2, 1, 1, 3, 0, 'IMAGE']],
                groups=[dict(title=edit, bounding=[40, 90, 500, 880], color='#56747e', font_size=24, flags={}),
                        dict(title=output, bounding=[590, 90, 870, 580], color='#647e56', font_size=24, flags={})],
                config={}, extra={'uap_workbench': dict(version=1, activeBranch='stocking',
                     viewBranch='stocking', stage='daily', compactWidgets=False, branches=[branch]),
                     'ds': {'scale': .8, 'offset': [0, 0]}}, version=.4)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as file:
        json.dump(build(), file, ensure_ascii=False, indent=2)
        file.write('\n')
