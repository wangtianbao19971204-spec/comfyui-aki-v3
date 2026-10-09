"""Local aiohttp adapter for the pinned editor, scoped to independent ComfyUI nodes."""
import asyncio
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import quote, urlsplit

from aiohttp import web
import cv2
import numpy as np

from . import studio_models as models
from . import studio_store as store
from .studio import Studio, check_image
from .studio_assets import page, static_asset
from .vendor import export, i18n, look

PREFIX = "/stocking_texture/studio"
NO_STORE = {"Cache-Control": "no-store"}


def json_response(data, status=200):
    return web.Response(text=store.dumps(data), status=status, content_type="application/json", headers=NO_STORE)


def png(image, info=None):
    ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise ValueError("无法编码预览图")
    headers = dict(NO_STORE)
    if info is not None:
        headers["X-Look"] = json.dumps(info)
    return web.Response(body=encoded.tobytes(), content_type="image/png", headers=headers)


async def body_json(request):
    data = bytearray()
    async for chunk in request.content.iter_chunked(64 * 1024):
        data.extend(chunk)
        if len(data) > store.MAX_PROJECT_BYTES:
            raise ValueError("请求数据超过 24 MiB")
    data = json.loads(data or b"{}")
    if not isinstance(data, dict):
        raise ValueError("请求须为 JSON 对象")
    return data


def same_origin(request):
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        raise web.HTTPForbidden(text="编辑请求必须来自当前 ComfyUI 页面")


class EditorSession:
    def __init__(self, studio, loop):
        self.studio, self.loop = studio, loop
        self.queues = set()
        self.downloads = {}
        self.pending_apply = None
        self.operation = asyncio.Lock()
        self.studio.on_event = self.publish

    def publish(self, event):
        for q in tuple(self.queues):
            self.loop.call_soon_threadsafe(self._put, q, event)

    @staticmethod
    def _put(queue, event):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)

    def close(self):
        self.publish(None)
        self.studio.close()


class StudioServer:
    def __init__(self, server, assets, model_paths):
        self.server, self.assets, self.model_paths = server, Path(assets), model_paths
        self.sessions = {}
        self.creation = asyncio.Lock()

    def preferences(self, request):
        root = self.server.user_manager.get_request_user_filepath(request, "stocking_texture/preferences.json")
        if root is None:
            raise web.HTTPForbidden(text="用户资料目录无效")
        return store.Preferences(Path(root).parent)

    def get(self, sid):
        item = self.sessions.get(sid)
        if item is None or item.studio.closed:
            raise web.HTTPGone(text="编辑器已关闭，请从节点重新打开；草稿会自动恢复")
        item.studio.last_access = time.monotonic()
        return item

    async def create(self, request):
        # Reserve capacity across the worker-thread construction await.
        async with self.creation:
            return await self._create(request)

    async def _create(self, request):
        try:
            same_origin(request)
            data = await body_json(request)
            now = time.monotonic()
            for key, entry in list(self.sessions.items()):
                if now - entry.studio.last_access > 1800 and not entry.operation.locked():
                    await asyncio.to_thread(entry.close)
                    self.sessions.pop(key, None)
            if len(self.sessions) >= 4:
                raise ValueError("最多同时打开 4 个完整编辑器，请先关闭一个")
            preferences = self.preferences(request)
            draft_id = data.get("draft_id") or uuid.uuid4().hex
            studio = await asyncio.to_thread(Studio, self.assets, preferences, self.model_paths,
                                             data.get("project", {}), draft_id=draft_id)
            try:
                restored = await asyncio.to_thread(studio.restore_draft) if data.get("restore", True) else False
            except (ValueError, KeyError, OSError):
                studio.draft_id = None  # Preserve the unreadable draft for recovery.
                studio.close()
                raise ValueError("自动保存草稿无法读取，请保留草稿文件后重试")
            sid = uuid.uuid4().hex
            self.sessions[sid] = EditorSession(studio, asyncio.get_running_loop())
            studio.start_depth()
            return json_response({"session": sid, "draft_id": draft_id, "url": f"{PREFIX}/{sid}/",
                                  "restored": restored})
        except (ValueError, KeyError, TypeError) as exc:
            return json_response({"detail": str(exc)}, 400)

    async def events(self, request, entry):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", **NO_STORE})
        await response.prepare(request)
        queue = asyncio.Queue(maxsize=64)
        entry.queues.add(queue)
        try:
            await response.write(b": connected\n\n")
            while not entry.studio.closed:
                try:
                    event = await asyncio.wait_for(queue.get(), 20)
                except asyncio.TimeoutError:
                    entry.studio.last_access = time.monotonic()
                    await response.write(b": heartbeat\n\n")
                    continue
                if event is None:
                    break
                await response.write(("data: " + store.dumps(event) + "\n\n").encode("utf-8"))
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            entry.queues.discard(queue)
        return response

    async def handle(self, request):
        try:
            if request.method not in ("GET", "HEAD"):
                same_origin(request)
            sid = request.match_info["sid"]
            entry = self.get(sid)
            # iframe/image/EventSource requests cannot carry ComfyUI's custom user
            # header. The unguessable session URL is a capability bound at create.
            if "comfy-user" in request.headers and self.preferences(request).path != entry.studio.preferences.path:
                raise web.HTTPForbidden(text="该编辑器属于另一个 ComfyUI 用户")
            path = request.match_info.get("tail", "")
            base = f"{PREFIX}/{sid}"
            lang = entry.studio.preferences.read().get("lang", "zh")
            if path == "" and request.method == "GET":
                return web.Response(text=page(base, lang), content_type="text/html", headers=NO_STORE)
            if path.startswith("static/") and request.method == "GET":
                name = path[len("static/"):]
                content, mime = static_asset(name, base)
                return web.Response(text=content, content_type=mime, headers=NO_STORE)
            if path == "api/events" and request.method == "GET":
                return await self.events(request, entry)
            if path == "api/close" and request.method == "POST":
                async with entry.operation:
                    await asyncio.to_thread(entry.close)
                self.sessions.pop(sid, None)
                return json_response({"ok": True})
            if path.startswith("api/download/") and request.method == "GET":
                key = path.split("/")[-1]
                if key not in entry.downloads:
                    raise web.HTTPNotFound()
                file = entry.downloads[key]
                response = web.FileResponse(file)
                response.headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(file.name)
                return response
            if path == "api/open/upload" and request.method == "POST":
                reader = await request.multipart()
                part = await reader.next()
                if part is None or part.name != "file" or not part.filename:
                    raise ValueError("请上传图片或 PSD 文件")
                data = bytearray()
                while chunk := await part.read_chunk():
                    data.extend(chunk)
                    if len(data) > 128 * 1024 * 1024:
                        raise ValueError("导入文件超过 128 MiB")
                async with entry.operation:
                    return json_response(await asyncio.to_thread(entry.studio.open_bytes, bytes(data), part.filename))
            data = await body_json(request) if request.method not in ("GET", "HEAD") else {}
            token = i18n.language.set("en" if lang == "en" else "zh")
            try:
                async with entry.operation:
                    result = await asyncio.to_thread(self.action, entry, request.method, path, data,
                                                     dict(request.query), base)
            finally:
                i18n.language.reset(token)
            return result if isinstance(result, web.StreamResponse) else json_response(result)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            return json_response({"detail": str(exc)}, 400)
        except OSError as exc:
            return json_response({"detail": "读取或保存失败：" + str(exc)}, 500)

    def action(self, entry, method, path, body, query, base):
        studio = entry.studio
        if path == "api/ping" and method == "GET":
            return {"app": "stocking-texture", "version": "comfy-studio-6c0c620-1"}
        if path == "api/doc" and method == "GET":
            return studio.state()
        if path == "api/lang":
            if method == "POST":
                if body.get("lang") not in ("zh", "en"):
                    raise ValueError("不支持的界面语言")
                studio.preferences.update(lang=body["lang"])
            elif method != "GET":
                raise web.HTTPMethodNotAllowed(method, ["GET", "POST"])
            lang = studio.preferences.read().get("lang", "zh")
            return {"lang": lang, "chosen": lang, "system": "zh"}
        if path == "api/look/presets":
            if method == "GET":
                result = studio.preferences.presets()
            elif method == "PUT":
                result = studio.preferences.save_preset(body.get("name"), body.get("params"))
            elif method == "DELETE":
                result = studio.preferences.delete_preset(body.get("name"))
            else:
                raise web.HTTPMethodNotAllowed(method, ["GET", "PUT", "DELETE"])
            return {"presets": result}
        if path == "api/options":
            if method == "PUT":
                for key in ("dark_adapt", "depth_enabled"):
                    if key in body and type(body[key]) is not bool:
                        raise ValueError("开关值必须为布尔值")
                studio.dark_adapt = body.get("dark_adapt", studio.dark_adapt)
                changed = "depth_enabled" in body and body["depth_enabled"] != studio.depth_enabled
                studio.depth_enabled = body.get("depth_enabled", studio.depth_enabled)
                if changed and studio.doc is not None:
                    studio.depth_revision += 1
                    studio.doc.disparity = None
                    studio.depth_status, studio.depth_error = "idle", None
                    studio.start_depth()
                studio.save_draft()
                studio.publish({"type": "depth"})
            elif method != "GET":
                raise web.HTTPMethodNotAllowed(method, ["GET", "PUT"])
            return {"dark_adapt": studio.dark_adapt, "depth_enabled": studio.depth_enabled,
                    "models": models.available(studio.model_paths), "depth": studio.depth_status,
                    "depth_error": studio.depth_error}
        if path == "api/apply" and method == "POST":
            if studio.doc is None:
                raise ValueError("请先导入或连接图片")
            project = studio.project_data()
            ticket = uuid.uuid4().hex
            entry.pending_apply = (ticket, store.project_digest(project))
            studio.save_draft()
            return {"project": project, "ticket": ticket}
        if path == "api/apply/ack" and method == "POST":
            if entry.pending_apply is None or body.get("ticket") != entry.pending_apply[0]:
                raise ValueError("应用请求已过期，请重新应用")
            studio.base_hash = entry.pending_apply[1]
            entry.pending_apply = None
            studio.save_draft()
            return {"ok": True}

        match = re.fullmatch(r"api/doc/([0-9a-f]+)/(.+)", path)
        if match is None:
            raise web.HTTPNotFound()
        doc = studio.doc
        if doc is None or doc.id != match[1]:
            raise ValueError("这个文件已关闭，请重新打开编辑器")
        action = match[2]
        if method == "GET":
            return self.read_document(entry, action, query, base)
        result = self.edit_document(entry, method, action, body, base)
        studio.save_draft()
        return result

    def read_document(self, entry, action, query, base):
        s, d = entry.studio, entry.studio.doc
        if action == "art":
            return web.Response(body=d.art_png(), content_type="image/png", headers=NO_STORE)
        if action == "coverage":
            return web.Response(body=d.coverage_png(), content_type="image/png", headers=NO_STORE)
        if action == "coverage/stats":
            _, _, stats, version = d.coverage()
            return {"coverage_v": version, "regions": stats}
        if action == "segment/outlines":
            return d.segment_outlines()
        if action == "look":
            return s.look_info(query)
        r = re.fullmatch(r"regions/(\d+)/(mask|courses|neighbours)", action)
        if r:
            rid = int(r[1])
            if r[2] == "mask":
                return web.Response(body=d.mask_png(rid), content_type="image/png", headers=NO_STORE)
            return d.courses(rid) if r[2] == "courses" else d.neighbours(rid)
        if action in ("render/crop", "render/fit", "render/check"):
            w, h = int(query.get("w", d.w)), int(query.get("h", d.h))
            crop = action == "render/crop" or (action == "render/check" and "x0" in query)
            if crop:
                w, h = min(max(w, 1), 1024, d.w), min(max(h, 1), 1024, d.h)
                x, y = int(np.clip(int(query.get("x0", 0)), 0, d.w - w)), int(np.clip(int(query.get("y0", 0)), 0, d.h - h))
            else:
                w, h = int(np.clip(w, 16, d.w)), int(np.clip(h, 16, d.h))
            t0 = time.perf_counter()
            if action == "render/check":
                image = check_image(d, s.scene(), s.params(query),
                                    rect=(x, y, x + w, y + h) if crop else None,
                                    size=None if crop else (w, h))
                return png(image)
            image, info = s.render(query, (x, y, x + w, y + h) if crop else None)
            if not crop:
                image = cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA)
            extra = {"ms": round(1000 * (time.perf_counter() - t0)), "sparkles_ready": info["sparkles_ready"]}
            if crop:
                extra.update(x0=x, y0=y, w=image.shape[1], h=image.shape[0])
            return png(image, extra)
        raise web.HTTPNotFound()

    def edit_document(self, entry, method, action, body, base):
        s, d = entry.studio, entry.studio.doc
        created = {}
        if action == "look" and method == "PUT":
            d.set_look(look.clean_params(body))
            return s.look_info()
        if action == "coverage/exclude" and method == "PUT":
            if type(body.get("on")) is not bool:
                raise ValueError("颜色排除开关无效")
            d.set_color_exclude(body["on"])
        elif action == "regions" and method == "POST":
            if len(d.regions) >= 32:
                raise ValueError("最多 32 个部位")
            created["created"] = d.add_region(self.clean_name(body.get("name")))
        elif action == "strokes" and method == "POST":
            pts = store.points(body.get("pts"), d.w, d.h)
            if len(d.strokes) >= 1000:
                raise ValueError("走向线过多，请简化后重试")
            created["created"] = d.add_stroke(pts.ravel().tolist(), body.get("hint"))
        elif re.fullmatch(r"strokes/\d+", action) and method == "DELETE":
            d.delete_stroke(int(action.split("/")[1]))
        elif action == "dividers" and method == "POST":
            pts = store.points(body.get("pts"), d.w, d.h)
            created["created"] = d.add_divider(pts.ravel().tolist())
        elif action == "walls/remove" and method == "POST":
            xy = store.points([body.get("x"), body.get("y")], d.w, d.h, 1)[0]
            created["removed"] = d.remove_wall_at(*xy, max(1., min(float(body.get("tol", 8)), 60.)))
        elif action == "undo" and method == "POST":
            d.undo()
        elif action == "redo" and method == "POST":
            d.redo()
        elif action == "segment/cycle" and method == "POST":
            d.cycle_segment(int(body.get("step", 1)))
        elif action == "segment/select" and method == "POST":
            d.select_segment(int(body["k"]))
        elif action == "export" and method == "POST":
            return self.export_document(entry, body, base)
        elif action == "export/reveal" and method == "POST":
            if not entry.downloads:
                raise ValueError("请先导出文件")
            return {"url": base + "/api/download/" + next(reversed(entry.downloads))}
        else:
            region = re.fullmatch(r"regions/(\d+)(?:/(paint|clear|segment|split|merge|mirror))?", action)
            if not region:
                raise web.HTTPNotFound()
            rid, op = int(region[1]), region[2]
            d.region(rid)
            if op is None and method == "DELETE":
                d.delete_region(rid)
            elif op is None and method == "PATCH":
                d.rename_region(rid, self.clean_name(body.get("name")))
            elif method != "POST":
                raise web.HTTPMethodNotAllowed(method, ["POST"])
            elif op == "paint":
                pts = store.points(body.get("pts"), d.w, d.h, 1)
                radius = float(body.get("radius", 0))
                if not np.isfinite(radius) or not 0 < radius <= max(d.w, d.h):
                    raise ValueError("笔刷半径无效")
                d.paint(rid, pts.ravel().tolist(), radius, bool(body.get("erase", False)))
            elif op == "clear":
                d.clear_region(rid)
            elif op == "segment":
                s.segment(rid, float(body["x"]), float(body["y"]), bool(body.get("subtract", False)))
            elif op == "split":
                if len(d.regions) >= 32:
                    raise ValueError("最多 32 个部位")
                line = store.points(body["pts"], d.w, d.h).tolist() if body.get("pts") else None
                snap = float(body.get("snap", 0))
                if not np.isfinite(snap) or not 0 <= snap <= max(d.w, d.h):
                    raise ValueError("吸附半径无效")
                created["split"] = list(d.split_region(rid, line, snap))
            elif op == "merge":
                d.merge_region(rid, int(body["into"]))
            elif op == "mirror":
                made, replaced, rms = d.mirror_strokes(rid, int(body["into"]))
                created["mirrored"] = {"made": made, "replaced": replaced, "fit": round(rms, 1)}
            else:
                raise web.HTTPNotFound()
        return dict(s.state(), **created)

    @staticmethod
    def clean_name(name):
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 40 or not name.isprintable():
            raise ValueError("部位名称需为 1–40 个可显示字符")
        return name

    def export_document(self, entry, body, base):
        s, d = entry.studio, entry.studio.doc
        kind = body.get("kind", "png")
        if kind not in export.KINDS:
            raise ValueError("不支持的导出格式")
        key = uuid.uuid4().hex
        folder = s.preferences.path.parent / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", export.base_name(d.name))[:80]
        target = folder / f"{key}-{name}-{export.NAMES[kind]}"
        params = s.params(body.get("params"))
        if kind != "guides":
            s.wait_ready()
            d.set_look(params)
        result = export.export(d, s, params, str(target), kind)
        if kind == "guides":
            d.mark_guides_saved()
        entry.downloads[key] = target
        return {"kind": kind, "file": target.name, "folder": "浏览器下载", "seconds": result["seconds"],
                "notes": [], "url": base + "/api/download/" + key}

    async def shutdown(self, app):
        for entry in self.sessions.values():
            await asyncio.to_thread(entry.close)
        self.sessions.clear()


def register_routes(server):
    import folder_paths
    manager = StudioServer(server, Path(folder_paths.get_input_directory()) / "stocking_studio/assets", models.paths())
    server.routes.post(PREFIX)(manager.create)
    server.routes.get(PREFIX + "/{sid}/")(manager.handle)
    server.routes.route("*", PREFIX + "/{sid}/{tail:.*}")(manager.handle)
    server.app.on_shutdown.append(manager.shutdown)
    return manager
