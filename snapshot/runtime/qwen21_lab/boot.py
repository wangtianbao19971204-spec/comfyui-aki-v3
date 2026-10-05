import os
import runpy
import sys
from pathlib import Path

lab = Path(__file__).resolve().parent
sys.path.insert(0, str(lab / 'site_packages'))
sys.path.insert(0, str(lab / 'ComfyUI'))
os.chdir(lab / 'ComfyUI')
sys.argv = [str(lab / 'ComfyUI/main.py'), '--listen', '127.0.0.1', '--port', '8189',
    '--disable-auto-launch', '--disable-all-custom-nodes', '--whitelist-custom-nodes', 'ComfyUI-GGUF', '--disable-api-nodes',
    '--extra-model-paths-config', str(lab / 'extra_model_paths.yaml'),
    '--input-directory', str(lab / 'input'), '--output-directory', str(lab / 'output'),
    '--user-directory', str(lab / 'user'), '--database-url', 'sqlite:///' + (lab / 'user/lab.db').as_posix(),
    '--disable-pinned-memory', '--reserve-vram', '4', '--cuda-malloc', '--preview-method', 'none',
    '--bf16-unet', '--bf16-text-enc', '--bf16-vae', *sys.argv[1:]]
runpy.run_path(str(lab / 'ComfyUI/main.py'), run_name='__main__')
