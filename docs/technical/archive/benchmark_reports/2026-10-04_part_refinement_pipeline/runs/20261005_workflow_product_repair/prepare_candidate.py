"""Prepare editable candidate sources and inspect local safetensors headers only."""
import re
import shutil
import struct

from freeze import ROOT, RUN, WEB, NAV, read, save

EDIT_FILES = [ROOT / "production_tools/merge_unified_workflow.py"]
EDIT_FILES += [WEB / name for name in ("runtime_controls.js", "resource_actions.js", "task_activity.js", "workspace.js", "workbench.css", "studio.css")]
EDIT_FILES += [NAV / name for name in ("uap_daily_controls.js", "uap_workbench.js")]


def prepare():
    for path in EDIT_FILES:
        destination = RUN / "candidate" / path.relative_to(ROOT)
        assert not destination.exists(), destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RUN / "before" / path.relative_to(ROOT), destination)
    info = read(RUN / "object_info.json")
    records = []
    for cls, field, folders in (("UNETLoader", "unet_name", ("diffusion_models", "unet")),
                               ("CLIPLoader", "clip_name", ("text_encoders", "clip")),
                               ("VAELoader", "vae_name", ("vae",))):
        for name in info[cls]["input"]["required"][field][0]:
            if not name.endswith(".safetensors"):
                continue
            paths = [ROOT / "ComfyUI/models" / folder / name for folder in folders]
            path = next((path for path in paths if path.is_file()), None)
            assert path, name
            with path.open("rb") as stream:
                length = struct.unpack("<Q", stream.read(8))[0]
                assert 0 < length < 64 * 1024 * 1024
                import json
                header = json.loads(stream.read(length))
            keys = [key for key in header if key != "__metadata__"]
            blocks = sorted({int(match.group(1)) for key in keys for match in [re.search(r"(?:^|\.)blocks\.(\d+)\.", key)] if match})
            examples = keys[:5] + [key for key in keys if any(part in key for part in ("pos_embed", "patch_embed", "in_proj", "img_in", "embed_tokens", "conv_in", "encoder.conv1"))][:8]
            records.append({"class": cls, "name": name, "path": str(path), "key_count": len(keys),
                            "blocks": len(blocks), "max_block": max(blocks, default=-1),
                            "examples": {key: header[key].get("shape") for key in examples}})
    save(RUN / "model_headers.json", records)
    for item in records:
        print(item["class"], item["name"], "blocks=", item["blocks"], "keys=", item["key_count"], item["examples"])


if __name__ == "__main__":
    prepare()
