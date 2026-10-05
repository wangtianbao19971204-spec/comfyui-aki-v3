import json
import os
import time
from aiohttp import web
from server import PromptServer

DATA_FILE = os.path.join(os.path.dirname(__file__), "latest_danbooru_browser_import_v05.json")
LATEST = {}
ROUTE = "/danbooru_browser_import_v05"
VERSION = "0.6"


def _load_latest(force=False):
    global LATEST
    if LATEST and not force:
        return LATEST
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                LATEST = json.load(f)
        except Exception as e:
            LATEST = {"_error": f"failed to read latest import: {e}"}
    return LATEST


def _save_latest(data):
    global LATEST
    LATEST = data or {}
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(LATEST, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def _mtime_token():
    try:
        return str(os.path.getmtime(DATA_FILE))
    except Exception:
        return "no-file"


def _cors_json(data, status=200):
    resp = web.json_response(data, status=status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Requested-With"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


@PromptServer.instance.routes.get(ROUTE)
async def danbooru_browser_import_get_v05(request):
    return _cors_json({
        "ok": True,
        "plugin": "ComfyUI-Danbooru-Browser-Import",
        "version": VERSION,
        "route": ROUTE,
        "method": "GET",
        "latest": _load_latest(force=True),
        "mtime": _mtime_token(),
    })


@PromptServer.instance.routes.post(ROUTE)
async def danbooru_browser_import_post_v05(request):
    try:
        data = await request.json()
    except Exception:
        text = await request.text()
        data = {"raw_text": text}
    if not isinstance(data, dict):
        data = {"raw_payload": data}
    data["_received_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data["_route"] = ROUTE
    data["_plugin_version"] = VERSION
    _save_latest(data)
    return _cors_json({
        "ok": True,
        "plugin": "ComfyUI-Danbooru-Browser-Import",
        "version": VERSION,
        "route": ROUTE,
        "method": "POST",
        "received_keys": sorted(list(data.keys())),
        "post_id": data.get("post_id", ""),
        "merged_tags_preview": str(data.get("merged_tags", ""))[:240],
        "mtime": _mtime_token(),
    })


@PromptServer.instance.routes.options(ROUTE)
async def danbooru_browser_import_options_v05(request):
    return _cors_json({"ok": True, "plugin": "ComfyUI-Danbooru-Browser-Import", "version": VERSION, "route": ROUTE, "method": "OPTIONS"})


@PromptServer.instance.routes.get("/danbooru_browser_import_v05_status")
async def danbooru_browser_import_status_v05(request):
    return _cors_json({
        "ok": True,
        "plugin": "ComfyUI-Danbooru-Browser-Import",
        "version": VERSION,
        "route": ROUTE,
        "data_file": DATA_FILE,
        "exists": os.path.exists(DATA_FILE),
        "mtime": _mtime_token(),
    })


class DanbooruBrowserImportV05:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"refresh_token": ("INT", {"default": 0, "min": 0, "max": 999999999})}}

    @classmethod
    def IS_CHANGED(cls, refresh_token=0):
        # Important: the data is updated by an external browser POST, not by graph inputs.
        # This token tells ComfyUI to re-run the node when the received JSON file changes.
        return f"{refresh_token}:{_mtime_token()}"

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "merged_tags",
        "artist_tags",
        "character_tags",
        "copyright_tags",
        "general_tags",
        "meta_tags",
        "source_url",
        "image_url",
        "post_id",
        "raw_json",
    )
    FUNCTION = "read_latest"
    CATEGORY = "Danbooru/Browser Import"

    def read_latest(self, refresh_token=0):
        d = _load_latest(force=True) or {}
        def s(key):
            val = d.get(key, "")
            if isinstance(val, list):
                return ", ".join([str(x) for x in val if str(x).strip()])
            if isinstance(val, dict):
                return json.dumps(val, ensure_ascii=False)
            return str(val or "")
        raw = json.dumps(d, ensure_ascii=False, indent=2) if d else "No Danbooru browser import received yet. Open a Danbooru post page and click Send Tags to ComfyUI v0.5."
        return (
            s("merged_tags"),
            s("artist_tags"),
            s("character_tags"),
            s("copyright_tags"),
            s("general_tags"),
            s("meta_tags"),
            s("source_url"),
            s("image_url"),
            s("post_id"),
            raw,
        )


NODE_CLASS_MAPPINGS = {"DanbooruBrowserImportV05": DanbooruBrowserImportV05}
NODE_DISPLAY_NAME_MAPPINGS = {"DanbooruBrowserImportV05": "Danbooru Browser Import v0.6 · Tags/URL"}
