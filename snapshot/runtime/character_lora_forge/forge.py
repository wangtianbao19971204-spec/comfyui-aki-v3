from __future__ import annotations

import argparse
import json
from pathlib import Path

from character_forge.comfy import ComfyClient
from character_forge.config import load_config
from character_forge.pipeline import (
    create_plan,
    create_campaign_plan,
    create_repair_plan,
    create_subset_plan,
    doctor,
    generate,
    promote,
    record_manual_audit,
    score,
)
from character_forge.workflow import capture_template


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="ComfyUI 角色一致性黄金数据集炼制流水线"
    )
    root.add_argument(
        "--config",
        default="characters/rosasha/character.json",
        help="角色配置 JSON",
    )
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="检查 ComfyUI、节点和 LLM 配置")

    plan = commands.add_parser("plan", help="生成批量任务矩阵")
    plan.add_argument("--run-id")

    repair_plan = commands.add_parser(
        "repair-plan",
        help="根据上一轮 LLM 拒绝原因建立修复重绘计划",
    )
    repair_plan.add_argument("--source-run", required=True)
    repair_plan.add_argument("--run-id")

    subset_plan = commands.add_parser(
        "subset-plan",
        help="只为指定批次建立任务计划",
    )
    subset_plan.add_argument("--batches", nargs="+", required=True)
    subset_plan.add_argument("--run-id")
    subset_plan.add_argument("--variant")
    subset_plan.add_argument("--seed-offset", type=int, default=0)
    subset_plan.add_argument("--reference-delta", type=float, default=0)

    campaign_plan = commands.add_parser(
        "campaign-plan",
        help="合并多轮候选并进行跨轮统一筛选",
    )
    campaign_plan.add_argument("--source-runs", nargs="+", required=True)
    campaign_plan.add_argument("--run-id")

    capture = commands.add_parser(
        "capture-template",
        help="从 ComfyUI 历史记录捕获当前 API 工作流",
    )
    capture.add_argument("--prompt-id", default="latest")
    capture.add_argument("--output-node", default="13")
    capture.add_argument("--output")

    generation = commands.add_parser("generate", help="批量生成候选图")
    generation.add_argument("--run-id")
    generation.add_argument("--limit", type=int)

    scoring = commands.add_parser("score", help="技术检查 + LLM 一致性筛选")
    scoring.add_argument("--run-id", required=True)
    scoring.add_argument("--limit", type=int)
    scoring.add_argument("--no-llm", action="store_true")
    scoring.add_argument("--auto-promote", action="store_true")

    full = commands.add_parser("run", help="生成并筛选")
    full.add_argument("--run-id")
    full.add_argument("--limit", type=int)
    full.add_argument("--no-llm", action="store_true")
    full.add_argument("--auto-promote", action="store_true")

    promotion = commands.add_parser(
        "promote",
        help="把 machine_gold 复制到训练集目录",
    )
    promotion.add_argument("--run-id", required=True)

    audit = commands.add_parser(
        "audit",
        help="记录 Codex 人工视觉抽检结果，批准后才允许归档",
    )
    audit.add_argument("--run-id", required=True)
    audit.add_argument(
        "--status",
        choices=("approved", "rejected", "needs_revision"),
        required=True,
    )
    audit.add_argument("--notes", required=True)
    audit.add_argument("--sample", nargs="*", default=[])
    audit.add_argument("--exclude", nargs="*", default=[])
    return root


def main() -> int:
    args = parser().parse_args()
    config = load_config(args.config)

    if args.command == "doctor":
        result = doctor(config)
        print_json(result)
        return 0 if result["ok"] else 2

    if args.command == "plan":
        run_id, destination, jobs = create_plan(config, args.run_id)
        print_json(
            {
                "run_id": run_id,
                "run_dir": str(destination),
                "job_count": len(jobs),
            }
        )
        return 0

    if args.command == "repair-plan":
        run_id, destination, jobs = create_repair_plan(
            config,
            source_run_id=args.source_run,
            run_id=args.run_id,
        )
        print_json(
            {
                "run_id": run_id,
                "run_dir": str(destination),
                "source_run_id": args.source_run,
                "job_count": len(jobs),
            }
        )
        return 0

    if args.command == "subset-plan":
        run_id, destination, jobs = create_subset_plan(
            config,
            batch_ids=args.batches,
            run_id=args.run_id,
            variant=args.variant,
            seed_offset=args.seed_offset,
            reference_delta=args.reference_delta,
        )
        print_json(
            {
                "run_id": run_id,
                "run_dir": str(destination),
                "batches": args.batches,
                "job_count": len(jobs),
            }
        )
        return 0

    if args.command == "campaign-plan":
        run_id, destination, jobs = create_campaign_plan(
            config,
            source_run_ids=args.source_runs,
            run_id=args.run_id,
        )
        print_json(
            {
                "run_id": run_id,
                "run_dir": str(destination),
                "source_runs": args.source_runs,
                "job_count": len(jobs),
            }
        )
        return 0

    if args.command == "capture-template":
        client = ComfyClient(
            config["comfyui"]["base_url"],
            config["comfyui"].get("root"),
        )
        history = client.history(max_items=20)
        prompt_id = args.prompt_id
        if prompt_id == "latest":
            if not history:
                raise RuntimeError("ComfyUI 历史记录为空")
            prompt_id = next(iter(history))
        record = history.get(prompt_id)
        if record is None:
            record = client.history(prompt_id=prompt_id).get(prompt_id)
        if record is None:
            raise RuntimeError(f"找不到 ComfyUI 历史记录 {prompt_id}")
        record = dict(record)
        record["prompt_id"] = prompt_id
        output = Path(
            args.output or config["comfyui"]["workflow_template"]
        ).resolve()
        result = capture_template(record, args.output_node, output)
        print_json(
            {
                "output": str(output),
                "nodes": len(result["graph"]),
                "prompt_id": prompt_id,
            }
        )
        return 0

    if args.command == "generate":
        print_json(
            generate(
                config,
                run_id=args.run_id,
                limit=args.limit,
            )
        )
        return 0

    if args.command == "score":
        print_json(
            score(
                config,
                run_id=args.run_id,
                use_llm=not args.no_llm,
                limit=args.limit,
                auto_promote=args.auto_promote,
            )
        )
        return 0

    if args.command == "run":
        generated = generate(
            config,
            run_id=args.run_id,
            limit=args.limit,
        )
        scored = score(
            config,
            run_id=generated["run_id"],
            use_llm=not args.no_llm,
            limit=args.limit,
            auto_promote=args.auto_promote,
        )
        print_json({"generation": generated, "selection": scored})
        return 0

    if args.command == "promote":
        print_json({"promoted": promote(config, run_id=args.run_id)})
        return 0

    if args.command == "audit":
        print_json(
            record_manual_audit(
                config,
                run_id=args.run_id,
                status=args.status,
                notes=args.notes,
                sampled_job_ids=args.sample,
                excluded_job_ids=args.exclude,
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
