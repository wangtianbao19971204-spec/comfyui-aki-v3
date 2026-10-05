from common import *
import os, ast, traceback
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
sys.path.insert(0,str(ROOT/'ComfyUI'))
module_root=PROD.parent/'comfyui-lora-manager'
package=types.ModuleType('one_shot_lora_probe');package.__path__=[str(module_root)];sys.modules[package.__name__]=package
tree=ast.parse((module_root/'__init__.py').read_text(encoding='utf-8'))
imports=tree.body[0].body
loaded=[]
for node in imports:
    if not isinstance(node,ast.ImportFrom):continue
    name='one_shot_lora_probe.'+node.module
    try:
        module=importlib.import_module(name)
        for obj in node.names:assert hasattr(module,obj.name),(name,obj.name)
        loaded.append(name);print('IMPORTED',name,flush=True)
    except Exception as error:
        save(HERE/'workbench_import_probe.json',{'passed':False,'loaded':loaded,'failed_module':name,'error':repr(error),'traceback':traceback.format_exc()})
        traceback.print_exc();raise
save(HERE/'workbench_import_probe.json',{'passed':True,'loaded':loaded})
