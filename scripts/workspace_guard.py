"""Read-only production preservation checks for workspace organization."""
import argparse
import json
from pathlib import Path

from snapshot import REPO, digest, health, now, safe_path


def file_state(path):
    return {"exists": path.is_file(), "sha256": digest(path) if path.is_file() else None}


def capture(runtime, output, snapshot=REPO / "snapshot"):
    runtime = runtime.resolve()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    paths = {row["source"] for row in manifest["files"]}
    private = snapshot / "inventory/excluded_private_configs.json"
    if private.exists():
        paths.update(row["path"] for row in json.loads(private.read_text(encoding="utf-8")))
    paths.add("ComfyUI/custom_nodes/TB_Multi_API_Caption_ConfigPage_V17_ProviderAdapters/models_cache.json")
    for entry in manifest["files"]:
        if entry["kind"] == "sqlite_sql":
            paths.add(entry["source"] + "-wal")
    before = health()
    states = {relative: file_state(safe_path(runtime, relative)) for relative in sorted(paths)}
    if before != health():
        raise RuntimeError("Service state changed during guard capture")
    report = {"schema": 1, "created_at": now(), "runtime": str(runtime),
              "snapshot_manifest_sha256": digest(snapshot / "manifest.json"),
              "health": before, "files": states, "production_modified": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return {"baseline": str(output), "protected_paths": len(states), "health": before}


def verify(baseline, output=None, approved_changes=None):
    baseline = baseline.resolve()
    report = json.loads(baseline.read_text(encoding="utf-8"))
    runtime = Path(report["runtime"])
    allowed = {}
    if approved_changes:
        spec = json.loads(approved_changes.read_text(encoding="utf-8"))
        for entry in spec["files"]:
            relative = entry["source"]
            if relative in allowed or relative not in report["files"]:
                raise ValueError("Approval must bind a unique already-protected source")
            if report["files"][relative]["sha256"] != entry["before_sha256"]:
                raise ValueError("Approval before hash does not match baseline")
            allowed[relative] = {"exists": True, "sha256": entry["after_sha256"]}
    drift = [relative for relative, old in report["files"].items()
             if file_state(safe_path(runtime, relative)) != allowed.get(relative, old)]
    current = health()
    result = {"schema": 1, "checked_at": now(), "baseline_sha256": digest(baseline),
              "pass": not drift and current == report["health"], "drift": drift,
              "protected_paths": len(report["files"]), "health": current,
              "service_identity_unchanged": current == report["health"], "check_is_read_only": True,
              "approved_changed_files": sorted(allowed), "unplanned_drift_count": len(drift)}
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cap = commands.add_parser("capture")
    cap.add_argument("--runtime", type=Path, required=True)
    cap.add_argument("--out", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--baseline", type=Path, required=True)
    check.add_argument("--out", type=Path)
    check.add_argument("--approved-changes", type=Path)
    args = parser.parse_args()
    result = capture(args.runtime, args.out) if args.command == "capture" else verify(args.baseline, args.out, args.approved_changes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
