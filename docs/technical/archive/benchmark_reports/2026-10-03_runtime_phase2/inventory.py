import json
from manage import ROOT,OUT,get,save,sha

def inspect(info):
 profiles=json.loads((ROOT/'production_tools/profiles.json').read_text('utf8'))
 allowed=set(profiles['production'])
 frontend={'MarkdownNote','Note','Reroute','PrimitiveNode','Fast Groups Muter (rgthree)','Fast Groups Bypasser (rgthree)','Label (rgthree)'}
 fields={'UNETLoader':'unet_name','VAELoader':'vae_name','CLIPLoader':'clip_name','CheckpointLoaderSimple':'ckpt_name','UpscaleModelLoader':'model_name','UnetLoaderGGUF':'unet_name','AnimaLLLiteApply_sdscripts':'lllite_name'}
 rows=[]
 for p in (ROOT/'ComfyUI/user/default/workflows').glob('*.json'):
  d=json.loads(p.read_text('utf8'));graphs=[('root',d)]+[(g['id'],g) for g in d.get('definitions',{}).get('subgraphs',[])]
  if not d.get('nodes'):continue
  subids={g['id'] for g in d.get('definitions',{}).get('subgraphs',[])}
  types={n['type'] for _,g in graphs for n in g.get('nodes',[])}
  owners={info[t]['python_module'].split('.')[1] for t in types if t in info and info[t].get('python_module','').startswith('custom_nodes.')}
  missing=[]
  for gid,g in graphs:
   for n in g.get('nodes',[]):
    if n['type'] not in fields:continue
    key=fields[n['type']];choices=info.get(n['type'],{}).get('input',{}).get('required',{}).get(key,[None])[0]
    value=(n.get('widgets_values') or [None])[0]
    if isinstance(choices,list) and value not in choices:missing.append({'graph':gid,'node':n['id'],'type':n['type'],'model':value,'mode':n.get('mode',0)})
  rows.append({'file':p.name,'sha256':sha(p),'required_plugins':sorted(owners),'profile_missing':sorted(owners-allowed),'unregistered':sorted(types-set(info)-subids-frontend),'missing_models':missing})
 opened=[]
 for row in json.loads((OUT/'open_workflow_types.json').read_text('utf8')):
  types=row['snapshot']['result']['value']['types'];owners={info[t]['python_module'].split('.')[1] for t in types if t in info and info[t].get('python_module','').startswith('custom_nodes.')}
  opened.append({'name':row['name'],'profile_missing':sorted(owners-allowed)})
 assert not any(r['profile_missing'] for r in rows+opened)
 return {'workflow_count':len(rows),'profile_plugins':len(allowed),'active_backend_modules':len({i['python_module'].split('.')[1] for i in info.values() if i.get('python_module','').startswith('custom_nodes.')}),'rows':rows,'opened':opened}

if __name__=='__main__':
 result=inspect(get('/object_info'));save('dependency_inventory.json',result)
 lines=['# 现有工作流状态','','2026-10-03 本轮核对：下表根据当前服务的节点注册与模型下拉清单生成；包含嵌套子图。节点和模型存在不等同于所有分支已实跑通过。','','日常生产白名单为 24 个插件，覆盖已保存主生产工作流及本轮浏览器中 3 个已打开工作流的已注册后端依赖。原完整启动方式保留；本轮不卸载插件。','','| 工作流 | 当前检查结果 |','|---|---|']
 for row in result['rows']:
  issues=[]
  if row['unregistered']:issues.append('缺少后端节点：'+', '.join(row['unregistered']))
  if row['missing_models']:issues.append('有 '+str(len(row['missing_models']))+' 处模型引用不在当前可选清单，保留为历史参考 / 待迁移')
  if row['file']=='UAP统一生产工作台_v1.json':issues.append('不能作为无条件可用的完整回退')
  if not issues:issues.append('所查后端节点与加载器模型可用；完整可选分支未逐一重新生图')
  if '2.9B' in row['file'] or row['file'].startswith('UAP'):issues.append('2.9B 不支持当前原版 28 层 LLLite 权重')
  lines.append('| '+row['file']+' | '+'；'.join(issues)+' |')
 lines+=['','缺失模型可能位于禁用或旁路分支；表中数量不代表当前生成必然失败。未替换任何旧模型引用，也未自动启用控制分支。','','明细与运行验收：`benchmark_reports/2026-10-03_runtime_phase2/`。本轮第二阶段用于运行配置和连续出图效率，24 张提示词画质对照属于后续第三阶段。']
 (OUT/'staged/工作流状态表.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
 print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False));print('missing_model_references',sum(len(r['missing_models']) for r in result['rows']))
