from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'benchmark_reports/2026-09-07_plugin_fusion'
FILES = [
    'ComfyUI/custom_nodes/comfyui-lora-manager/web/comfyui/lora_loader.js',
    'ComfyUI/custom_nodes/comfyui-lora-manager/web/comfyui/workflow_registry.js',
    'ComfyUI/custom_nodes/comfyui-lora-manager/web/comfyui/utils.js',
    'ComfyUI/custom_nodes/comfyui-lora-manager/web/comfyui/loras_widget.js',
    'ComfyUI/custom_nodes/comfyui-lora-manager/static/js/utils/uiHelpers.js',
    'ComfyUI/custom_nodes/WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/zz_tb_shared_preset_global_entry.js',
    'ComfyUI/custom_nodes/WeiLin-Comfyui-Tools-V52-FullPromptSelector/dist/javascript/zz_tb_shared_preset_manager.js',
    'ComfyUI/custom_nodes/WeiLin-Comfyui-Tools-V52-FullPromptSelector/js_node/weilin_prompt_ui_node.js',
    'ComfyUI/custom_nodes/comfyui-anima-tools/js/anima_selector_random.js',
    'ComfyUI/custom_nodes/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js',
]

if __name__ == '__main__':
    for relative in FILES:
        source = ROOT / relative
        target = REPORT / 'before' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
    data = ROOT / 'ComfyUI/custom_nodes/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/prompt_selector'
    manifest = {str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in data.rglob('*.json')}
    target = REPORT / 'shared_data_before.json'
    if not target.exists():
        target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Backed up {len(FILES)} code files; {len(manifest)} shared data files')
