"""Serve actual browser-import modules/handlers for isolated page acceptance.

This fixture never imports ComfyUI, touches its queue, or uses production data.
Run with an explicit fresh external-root and an unused loopback port.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

from aiohttp import web


def build_app(external_root):
    runtime = Path(__file__).resolve().parents[1]
    web_root = runtime / "ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web"
    source = runtime / "ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/danbooru_browser_import.py"
    external_root = external_root.resolve()
    if external_root == runtime or external_root.is_relative_to(runtime):
        raise ValueError("Fixture state must stay outside the source checkout")
    external_root.mkdir(parents=True, exist_ok=False)
    os.environ["COMFYUI_EXTERNAL_ROOT"] = str(external_root)
    sockets = set()
    routes = web.RouteTableDef()

    class FixtureServer:
        def __init__(self):
            self.routes = routes

        def send_sync(self, event, data, sid=None):
            async def deliver():
                for socket in tuple(sockets):
                    if not socket.closed:
                        await socket.send_json({"type": event, "data": data})
            asyncio.get_running_loop().create_task(deliver())

    sys.modules["server"] = types.SimpleNamespace(
        PromptServer=types.SimpleNamespace(instance=FixtureServer()))
    spec = importlib.util.spec_from_file_location("isolated_browser_bridge", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Legacy fixture I/O also stays in the fresh external directory.
    module.DATA_FILE = str(external_root / "legacy-latest.json")
    app = web.Application(client_max_size=256 * 1024)
    app.add_routes(routes)

    async def fixture(request):
        return web.FileResponse(runtime / "production_tools/browser_bridge_fixture.html")

    async def api_stub(request):
        return web.Response(text="export const api = new EventTarget();\n", content_type="application/javascript")

    async def ws(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        sockets.add(socket)
        try:
            async for _ in socket:
                pass
        finally:
            sockets.discard(socket)
        return socket

    app.router.add_get("/fixture", fixture)
    app.router.add_get("/scripts/api.js", api_stub)
    app.router.add_get("/fixture-ws", ws)
    app.router.add_static("/web/", web_root)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port == 8188:
        parser.error("Use an unused non-production port between 1024 and 65535")
    app = build_app(args.external_root)
    print(json.dumps({"fixture": True, "production_imported": False,
                      "url": f"http://127.0.0.1:{args.port}/fixture"}), flush=True)
    web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
