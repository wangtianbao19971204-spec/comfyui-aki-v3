from __future__ import annotations

import argparse
import json
from pathlib import Path

from anima_lora_forge.core import (
    build_training_command,
    execute_run,
    list_runs,
    load_profile,
    preflight,
    prepare_run,
    sd_trainer_dashboard_status,
    submit_sd_trainer_job,
)


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="可复用的 Anima 角色 LoRA 训练项目"
    )
    parser.add_argument(
        "--profile",
        default="profiles/rosasha.json",
        help="角色训练配置 JSON",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="检查数据集、模型、GPU 和训练器")
    doctor.add_argument("--verify-model-hash", action="store_true")
    prepare = commands.add_parser("prepare", help="生成训练配置和可审计运行目录")
    prepare.add_argument("--run-id")
    command = commands.add_parser("command", help="显示训练命令，不执行")
    command.add_argument("--run-id")
    train = commands.add_parser("train", help="执行已经准备并解锁的训练")
    train.add_argument("--run-id", required=True)
    submit = commands.add_parser(
        "submit",
        help="通过 SD-Trainer 提交已准备并解锁的训练",
    )
    submit.add_argument("--run-id", required=True)
    commands.add_parser("dashboard", help="检查可视化控制台和监控入口")
    commands.add_parser("status", help="列出训练运行和权重")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profile = load_profile(args.profile)
    if args.command == "doctor":
        report = preflight(profile, verify_model_hash=args.verify_model_hash)
        print_json(report)
        return 0 if report["ok"] else 2
    if args.command == "prepare":
        print_json(prepare_run(profile, run_id=args.run_id))
        return 0
    if args.command == "command":
        manifest = prepare_run(profile, run_id=args.run_id)
        print("& " + " ".join(f"'{part}'" for part in manifest["command"]))
        return 0
    if args.command == "train":
        return execute_run(profile, args.run_id)
    if args.command == "submit":
        print_json(submit_sd_trainer_job(profile, args.run_id))
        return 0
    if args.command == "dashboard":
        print_json(sd_trainer_dashboard_status(profile))
        return 0
    if args.command == "status":
        print_json({"runs": list_runs(profile)})
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print_json({"ok": False, "error": str(exc)})
        raise SystemExit(2)
