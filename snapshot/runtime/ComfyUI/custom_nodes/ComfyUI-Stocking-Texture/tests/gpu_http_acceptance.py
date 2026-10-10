"""Exercise actual SAM/depth through an isolated CUDA ComfyUI HTTP instance."""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener


def run(args):
    url = urlsplit(args.url)
    if url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1") or url.port in (None, 8188):
        raise ValueError("Use an explicit isolated localhost port, never production 8188")
    args.out.mkdir(parents=True, exist_ok=False)
    opener = build_opener(ProxyHandler({}))
    def call(method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(args.url.rstrip("/") + path, data=body, method=method,
                          headers={"Content-Type": "application/json"} if body else {})
        with opener.open(request, timeout=120) as response:
            return json.load(response)

    assert not any(call("GET", "/queue").values())
    project = json.loads(args.project.read_text(encoding="utf-8"))
    project["depth_enabled"] = False
    project.pop("depth_asset", None)
    project["look"].update(moire_on=False)
    opened = call("POST", "/stocking_texture/studio", {"project": project, "restore": False})
    base = opened["url"].rstrip("/")
    state = call("GET", base + "/api/doc")
    docbase = base + "/api/doc/" + state["id"]
    rid = state["regions"][0]["id"]
    rows = []
    def click(label, x, y):
        start = time.perf_counter()
        call("POST", docbase + f"/regions/{rid}/segment", {"x": x, "y": y})
        elapsed = time.perf_counter() - start
        state = call("GET", base + "/api/doc")
        info = state["sam"]["inference"]
        assert info["backend"].startswith("cuda"), info
        row = {"label": label, "http_seconds": elapsed, "inference": info}
        rows.append(row)
        with (args.out / "clicks.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)
        return info

    click("first_click", *args.point[0])
    for point in args.point[1:]:
        assert click("cached_click", *point)["embedding_cached"]
    call("POST", docbase + "/segment/select", {"k": 2})
    call("POST", docbase + "/undo", {})
    call("POST", docbase + "/redo", {})
    # SAM must not sit behind slow depth model loading/CPU preprocessing.
    call("PUT", base + "/api/options", {"depth_enabled": True})
    assert click("during_depth", *args.point[0])["embedding_cached"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        options = call("GET", base + "/api/options")
        if options["depth"] != "working":
            break
        time.sleep(.2)
    assert options["depth"] == "ready", options
    assert options["depth_inference"]["backend"].startswith("cuda"), options
    applied = call("POST", base + "/api/apply")
    call("POST", base + "/api/apply/ack", {"ticket": applied["ticket"]})
    reopened = call("POST", "/stocking_texture/studio", {"project": applied["project"], "restore": False})
    restored = call("GET", reopened["url"].rstrip("/") + "/api/doc")
    assert restored["has_depth"]
    restored_project = call("POST", reopened["url"].rstrip("/") + "/api/apply")["project"]
    for key in ("regions", "strokes", "dividers", "asset", "depth_asset", "look"):
        assert restored_project[key] == applied["project"][key], key

    # A real queued texture render occupies ComfyUI's worker, without diffusion
    # weights or generation. Editor inference must then use CPU independently.
    prompt = {"1": {"class_type": "StockingTextureStudio", "inputs": {
        "project_json": json.dumps(json.loads(args.project.read_text(encoding="utf-8")))}}}
    queued = call("POST", "/prompt", {"prompt": prompt})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if call("GET", "/queue")["queue_running"]:
            break
        time.sleep(.02)
    else:
        raise AssertionError("Did not observe the isolated texture prompt running")
    call("POST", docbase + f"/regions/{rid}/segment", {"x": args.point[0][0], "y": args.point[0][1]})
    busy_info = call("GET", base + "/api/doc")["sam"]["inference"]
    assert busy_info["backend"] == "cpu" and busy_info["fallback"] == "comfy_busy", busy_info
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        history = call("GET", "/history/" + queued["prompt_id"])
        if queued["prompt_id"] in history:
            assert history[queued["prompt_id"]]["status"]["status_str"] == "success"
            break
        time.sleep(.2)
    else:
        raise AssertionError("Isolated texture prompt did not finish")
    assert click("gpu_after_queue", *args.point[0])["embedding_cached"]
    receipt = {"pass": True, "sessions": [opened, reopened], "clicks": rows,
               "depth": options["depth_inference"], "busy_fallback": busy_info,
               "candidate_cycle_undo_redo": True,
               "apply_ack_reopen": True, "real_browser_verified": False,
               "devices": call("GET", "/system_stats")["devices"]}
    (args.out / "ACCEPTANCE.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    for session in (opened, reopened):
        call("POST", session["url"].rstrip("/") + "/api/close", {})
    print(json.dumps({"pass": True, "depth": options["depth_inference"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--point", type=int, nargs=2, action="append", required=True)
    run(parser.parse_args())
