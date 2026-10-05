"""Keep frequently edited nodes and their group switches in the daily area."""
import argparse
import json
from datetime import datetime

import tighten_uap_widgets as layout

REPORT = layout.ROOT / "benchmark_reports/2026-09-07_uap_daily_controls"


def arrange(data, measured=False):
    # The graph is copied by compact(); only UI navigation is changed here.
    import copy
    data = copy.deepcopy(data)
    for branch in data["extra"]["uap_workbench"]["branches"]:
        stages = {stage["id"]: stage for stage in branch["stages"]}
        if "daily" not in stages:
            continue
        daily = stages["daily"]
        first = [g for g in daily["groups"] if not g.startswith(("CORE-02B", "CTRL-00"))]
        nearby = [g for stage in branch["stages"] for g in stage["groups"] if g.startswith(("CORE-02B", "CTRL-00"))]
        for stage in branch["stages"]:
            if stage is not daily:
                stage["groups"] = [g for g in stage["groups"] if g not in nearby]
        daily["groups"] = first + nearby
        daily["label"] = "日常总控"
        stages["model"]["label"] = "模型配置"
        branch["dailyRows"] = [first, nearby]
    layout.SIZES.update({
        "WeiLinPromptUI": (420, 230), "PrimitiveBoolean": (280, 58),
        "ShowText|pysssss": (320, 100), "CLIPTextEncode": (320, 110),
        "CR Prompt Text": (320, 120), "KSampler": (300, 270),
        "SaveImage": (320, 68), "PreviewImage": (300, 240),
        "PromptSelector": (480, 360),
    })
    result = layout.compact(data, resize_nodes=not measured)
    result["extra"]["uap_workbench"].update(viewBranch=result["extra"]["uap_workbench"]["activeBranch"], stage="daily")
    result["extra"]["codex_uap_integration"]["layout"] = "daily_controls_together"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repack-measured", action="store_true")
    args = parser.parse_args()
    data = json.loads(layout.OUTPUT.read_text(encoding="utf8"))
    result = arrange(data, args.repack_measured)
    audit = layout.audit(data, result)
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / f"before_{datetime.now():%Y%m%d_%H%M%S}.json").write_bytes(layout.OUTPUT.read_bytes())
    layout.OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
