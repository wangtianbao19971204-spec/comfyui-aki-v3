"""Isolated CPU acceptance using the actual installed control checkpoint; no sampling."""
import argparse, hashlib, importlib.util, json, os, pathlib, sys, types

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--comfy-root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1]/'snapshot/runtime/ComfyUI')
parser.add_argument('--controlnet-directory', type=pathlib.Path, required=True)
parser.add_argument('--checkpoint', default='anima-lllite-any-test-like-v2.safetensors')
parser.add_argument('--out', type=pathlib.Path, required=True)
args = parser.parse_args()
if args.out.exists(): parser.error('Use a new receipt path; existing evidence is never overwritten.')
source = args.comfy_root.resolve()
sys.path.insert(0,str(source))
import comfy.cli_args
comfy.cli_args.args.cpu=True
import torch
torch.set_num_threads(2)
import folder_paths
folder_paths.add_model_folder_path('controlnet', str(args.controlnet_directory.resolve()))
import comfy.ldm.anima.lllite as native
from comfy.ldm.anima.model import Anima
original_apply=native.AnimaLLLite.apply

def load(name,path,package=False):
    spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)] if package else None)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

package=load('anima_compat_candidate',source/'custom_nodes/ComfyUI-Anima-LoRA-ControlNet-Patch/__init__.py',True)
loader=load('anima_native_loader',source/'custom_nodes/ComfyUI-Anima-LLLite/native_loader.py').AnimaLLLiteModelLoader()
patcher=loader.load(args.checkpoint)[0]
model=patcher.model
host=Anima.__new__(Anima);torch.nn.Module.__init__(host);host.blocks=torch.nn.ModuleList([torch.nn.Identity() for _ in range(40)])
wrapper=types.SimpleNamespace(model=types.SimpleNamespace(diffusion_model=host))
package.controlnet_patch._maybe_install_remap(wrapper,patcher)
mapping=package.anima_arch.get_inverse_mapping(28,40)
assert getattr(model,'_anima_compat_cnet_remap')==mapping
torch.manual_seed(2940)
x=torch.randn(1,4,model.model_dim)
cond=torch.randn(1,4,32)
errors=[]
for i in range(40):
    actual=model.apply(x,cond,i,'self_attn_q_proj',0.8)
    expected=x if i not in mapping else original_apply(model,x,cond,mapping[i],'self_attn_q_proj',0.8)
    if not torch.equal(actual,expected): errors.append(i)
assert not errors,errors
assert model.block_count==28 and len(model.module_names)==28
os.environ['ANIMA_COMPAT_CONTROLNET_REMAP']='0'
try: loader.load(args.checkpoint)
except RuntimeError: disabled_rejected=True
else: raise AssertionError('disabled remap should not allow this workflow')
os.environ.pop('ANIMA_COMPAT_CONTROLNET_REMAP')
for bad in ('../anima-lllite-any-test-like-v2.safetensors',str((args.controlnet_directory/args.checkpoint).resolve()),'file.pt'):
    try: loader.load(bad)
    except ValueError: pass
    else: raise AssertionError('unlisted path accepted')
key_map={'adapter':'diffusion_model.llm_adapter.weight',**{f'lora_unet_blocks_{i}_self_attn_q_proj':f'diffusion_model.blocks.{i}.self_attn.q_proj.weight' for i in range(40)}}
lora28={f'lora_unet_blocks_{i}_self_attn_q_proj.lora_down.weight':None for i in range(28)}
decision=package.lora_patch._decide(lora28,key_map)
assert decision[:3]==('expand',28,40)
mapped,_,_=package.lora_patch._remap_key_map(key_map,decision[3])
assert mapped['lora_unet_blocks_2_self_attn_q_proj']=='diffusion_model.blocks.3.self_attn.q_proj.weight'
assert package.lora_patch._decide({f'lora_unet_blocks_{i}_self_attn_q_proj.lora_down.weight':None for i in range(40)},key_map) is None
assert {parameter.device.type for parameter in model.parameters()} == {'cpu'}
result={'native_actual_checkpoint_loaded':True,'control_blocks':model.block_count,'host_blocks':40,'exact_cpu_routing_cases':40,
        'inherited_blocks':28,'inserted_blocks_passthrough':12,'disabled_patch_rejected':disabled_rejected,
        'unlisted_paths_rejected':3,'lora_28_to_40_mapping_pass':True,'native_40_lora_passthrough':True,
        'tensor_device':'cpu','cuda_initialized_by_import_probe':torch.cuda.is_initialized(),
        'torch_cuda_memory_allocated':torch.cuda.memory_allocated() if torch.cuda.is_initialized() else 0,'sampling_executed':False}
with (args.controlnet_directory/args.checkpoint).open('rb') as file:
    result['checkpoint_sha256'] = hashlib.file_digest(file, 'sha256').hexdigest()
out=args.out
out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
del patcher
