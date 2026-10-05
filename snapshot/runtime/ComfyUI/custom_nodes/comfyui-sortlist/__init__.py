import sys
import os

# Add PyArmor runtime to Python path
_runtime_path = os.path.join(os.path.dirname(__file__), "pyarmor_runtime_000000")
if _runtime_path not in sys.path:
    sys.path.insert(0, _runtime_path)

WEB_DIRECTORY = "."

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

def _safe_merge(module_name: str):
    global NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    try:
        mod = __import__(f"{__name__}.{module_name}", fromlist=["*"])
        cls_map = getattr(mod, "NODE_CLASS_MAPPINGS", None)
        name_map = getattr(mod, "NODE_DISPLAY_NAME_MAPPINGS", None)

        if isinstance(cls_map, dict):
            NODE_CLASS_MAPPINGS.update(cls_map)
        if isinstance(name_map, dict):
            NODE_DISPLAY_NAME_MAPPINGS.update(name_map)

    except Exception as e:
        print(f"[comfyui-sortlist] Skipped '{module_name}' due to import error: {e}")


# --- Utility ---
_safe_merge("nodes.utility.sort_nodes")
_safe_merge("nodes.utility.filter_nodes")
_safe_merge("nodes.utility.simple_loop")
_safe_merge("nodes.utility.get_timestamp")
_safe_merge("nodes.utility.check_encoder")
_safe_merge("nodes.utility.colab_nodes")
_safe_merge("nodes.utility.clear_vram_passthrough")

# --- Video ---
_safe_merge("nodes.video.videos_nodes")
_safe_merge("nodes.video.video_scene_splitter")
_safe_merge("nodes.video.video_audio_concat")
_safe_merge("nodes.video.video_mute")
_safe_merge("nodes.video.video_cut")
_safe_merge("nodes.video.video_sync_concat")
_safe_merge("nodes.video.video_nodes_console_note")

try:
    from .nodes.video.video_frame_guard import VHS_VideoFrameGuard, VHS_VideoPickMinFrames
    NODE_CLASS_MAPPINGS.update({
        "VHS_VideoFrameGuard": VHS_VideoFrameGuard,
        "VHS_VideoPickMinFrames": VHS_VideoPickMinFrames,
    })
    NODE_DISPLAY_NAME_MAPPINGS.update({
        "VHS_VideoFrameGuard": "Video Frame Guard (<=210 frames)",
        "VHS_VideoPickMinFrames": "Pick Video With Min Frames",
    })
except Exception as e:
    print(f"[comfyui-sortlist] Skipped 'video_frame_guard' due to import error: {e}")

try:
    from .nodes.video.vhs_extract_path import VHS_ExtractVideoPath
    NODE_CLASS_MAPPINGS.update({
        "VHS_ExtractVideoPath": VHS_ExtractVideoPath,
    })
    NODE_DISPLAY_NAME_MAPPINGS.update({
        "VHS_ExtractVideoPath": "Extract Video Path from VHS_FILENAMES",
    })
except Exception as e:
    print(f"[comfyui-sortlist] Skipped 'vhs_extract_path' due to import error: {e}")

# --- Audio ---
_safe_merge("nodes.audio.mp3_audio_loader")
_safe_merge("nodes.audio.mp3_embed_image")
_safe_merge("nodes.audio.mp3_extract_image")
_safe_merge("nodes.audio.split_mp3")
_safe_merge("nodes.audio.split_mp3_v2")
_safe_merge("nodes.audio.audio_file_scanner")

# --- Image ---
_safe_merge("nodes.image.draw_mask_on_image")
_safe_merge("nodes.image.image_concatenate_auto")
_safe_merge("nodes.image.load_image_from_path")
_safe_merge("nodes.image.steg_alpha_embed")
_safe_merge("nodes.image.steg_alpha_extract")

try:
    from .nodes.image.steg_rgb_extract import StegRGBExtract
    NODE_CLASS_MAPPINGS.update({"steg_rgb_extract": StegRGBExtract})
    NODE_DISPLAY_NAME_MAPPINGS.update({
        "steg_rgb_extract": "Steganography: Extract String From Colors (RGB)",
    })
except Exception as e:
    print(f"[comfyui-sortlist] Skipped 'steg_rgb_extract' due to import error: {e}")

try:
    from .nodes.image.i2sha import ImageToSHA256
    NODE_CLASS_MAPPINGS.update({"image_to_sha256": ImageToSHA256})
    NODE_DISPLAY_NAME_MAPPINGS.update({"image_to_sha256": "Image to SHA256"})
except Exception as e:
    print(f"[comfyui-sortlist] Skipped 'i2sha' due to import error: {e}")

# --- File ---
_safe_merge("nodes.file.file_list_loader")
_safe_merge("nodes.file.file_list_to_path")
_safe_merge("nodes.file.folder_file_scanner")
_safe_merge("nodes.file.collect_files")
_safe_merge("nodes.file.rename_file")
_safe_merge("nodes.file.mv")
_safe_merge("nodes.file.clear_folder")
_safe_merge("nodes.file.clear_folder_pattern")
_safe_merge("nodes.file.remove_first_line")

# --- Value ---
_safe_merge("nodes.value.value")
_safe_merge("nodes.value.set_values_from_panel")
_safe_merge("nodes.value.set_value_mc")
_safe_merge("nodes.value.set_value_mc_v2v")
_safe_merge("nodes.value.set_value_mc_v2v_v2")
_safe_merge("nodes.value.set_value_mc_i2v")
_safe_merge("nodes.value.set_value_mc_i2v_v2")
_safe_merge("nodes.value.string_concat")


from .nodes.value.set_value_with_path import NODE_CLASS_MAPPINGS as _m, NODE_DISPLAY_NAME_MAPPINGS as _n
NODE_CLASS_MAPPINGS.update(_m)
NODE_DISPLAY_NAME_MAPPINGS.update(_n)

from .nodes.value.set_value_for_dancing import NODE_CLASS_MAPPINGS as _m2, NODE_DISPLAY_NAME_MAPPINGS as _n2
NODE_CLASS_MAPPINGS.update(_m2)
NODE_DISPLAY_NAME_MAPPINGS.update(_n2)

# --- Resolution ---
_safe_merge("nodes.resolution.fix_dimensions")
_safe_merge("nodes.resolution.adaptive_resolution")
_safe_merge("nodes.resolution.resolution_down_step")
_safe_merge("nodes.resolution.max_frames_calc")
_safe_merge("nodes.resolution.max_frames_by_resolution")
_safe_merge("nodes.resolution.wan_frame_window")
