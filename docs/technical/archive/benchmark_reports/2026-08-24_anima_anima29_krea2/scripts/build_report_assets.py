from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
RAW = ROOT / "raw"
REPORT = ROOT / "report"
ASSETS = REPORT / "assets"
RESULTS = RAW / "results.jsonl"
SCORES = RAW / "manual_scores.json"

MODEL_ORDER = ["anima_original", "anima_29b", "krea2"]
MODEL_LABELS = {
    "anima_original": "Anima 原版",
    "anima_29b": "Anima 2.9B BF16",
    "krea2": "Krea2 Turbo",
}
MODEL_COLORS = {
    "anima_original": "#2E86AB",
    "anima_29b": "#A23B72",
    "krea2": "#F18F01",
}
MAIN_PHASES = {"smoke", "core", "advanced", "length", "aspect"}

HASHES = {
    "miaomiaoHarem_anima15.safetensors": "EEBCD007A03B6E456841EF976821001FB998284E074040FDB091932DAD21A529",
    "anima29B_v10_bf16.safetensors": "0B3020D1B906155F7EB30667622723E87160632C8C7A5F1C93BDCE685F2A346D",
    "DasiwaKrea2TurboRaw_cutedisasterV2Turbo.safetensors": "2F623E2DFD5E03AF0268939C8EBE462D7C35CE80AF7E7E64C28AE31E5A5BC486",
    "anima_baseV10_txt.safetensors": "CD2A512003E2F9F3CD3C32A9C3573F820BB28C940F73C57B1DDAA983D9223EBA",
    "qwen3-vl-4b-heretic.safetensors": "3FBA9F5A2059C719DA105BCB510B9DF0450BDDDE52D96968C607802C9D86F9CE",
    "krea2RealVae_v10.safetensors": "0DBBE0BAECA04C2B98D2F3809C6F595608939809C88B695BA971368F17C874B8",
    "qwen_image_vae.safetensors": "A70580F0213E67967EE9C95F05BB400E8FB08307E017A924BF3441223E023D1F",
}

MODEL_FILES = {
    "anima_original": [
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\diffusion_models\Anima\miaomiaoHarem_anima15.safetensors"),
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\text_encoders\anima_baseV10_txt.safetensors"),
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\vae\qwen_image_vae.safetensors"),
    ],
    "anima_29b": [
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\diffusion_models\Anima-2.9B\anima29B_v10_bf16.safetensors"),
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\text_encoders\anima_baseV10_txt.safetensors"),
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\vae\qwen_image_vae.safetensors"),
    ],
    "krea2": [
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\diffusion_models\krea2\DasiwaKrea2TurboRaw_cutedisasterV2Turbo.safetensors"),
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\text_encoders\qwen3-vl-4b-heretic.safetensors"),
        Path(r"G:\ComfyUI-aki-v3\ComfyUI\models\vae\krea2RealVae_v10.safetensors"),
    ],
}


def load_records() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in RESULTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "figure.facecolor": "#F7F8FA",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": "#C9CDD3",
            "axes.titleweight": "bold",
            "grid.color": "#DDE1E6",
            "grid.alpha": 0.7,
        }
    )


def main_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    base = [
        record
        for record in records
        if record["phase"] in MAIN_PHASES and record["negative_mode"] == "common"
    ]
    models: dict[str, Any] = {}
    for model in MODEL_ORDER:
        rows = [record for record in base if record["model"] == model]
        models[model] = {
            "task_count": len(rows),
            "success_count": sum(bool(record["success"]) for record in rows),
            "wall_time_s_mean": round(statistics.mean(record["wall_time_s"] for record in rows), 3),
            "wall_time_s_median": round(statistics.median(record["wall_time_s"] for record in rows), 3),
            "peak_vram_mb_mean": round(
                statistics.mean(record["telemetry_summary"]["gpu_memory_mb_max"] for record in rows), 1
            ),
            "peak_vram_mb_max": max(record["telemetry_summary"]["gpu_memory_mb_max"] for record in rows),
            "system_available_mb_min": min(
                record["telemetry_summary"]["system_available_mb_min"] for record in rows
            ),
            "post_unload_vram_mb_mean": round(
                statistics.mean(record["unload_after"]["after"]["gpu_memory_mb"] for record in rows), 1
            ),
            "post_unload_vram_mb_max": max(
                record["unload_after"]["after"]["gpu_memory_mb"] for record in rows
            ),
        }
    return {
        "all_tasks": len(records),
        "all_successes": sum(bool(record["success"]) for record in records),
        "all_failures": sum(not bool(record["success"]) for record in records),
        "main_common_tasks": len(base),
        "models": models,
    }


def speed_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for model in MODEL_ORDER:
        rows = [record for record in records if record["phase"] == "speed" and record["model"] == model]
        by_steps: dict[str, Any] = {}
        for steps in sorted({record["steps"] for record in rows}):
            values = [record["wall_time_s"] for record in rows if record["steps"] == steps]
            by_steps[str(steps)] = {
                "samples_s": values,
                "median_s": round(statistics.median(values), 3),
                "min_s": round(min(values), 3),
                "max_s": round(max(values), 3),
            }
        result[model] = by_steps
    return result


def score_stats() -> dict[str, Any]:
    payload = json.loads(SCORES.read_text(encoding="utf-8"))
    weights = {
        "prompt_adherence": 0.5,
        "visual_quality": 0.3,
        "structure_artifacts": 0.2,
    }
    result: dict[str, Any] = {"weights": weights, "models": {}}
    for model in MODEL_ORDER:
        dimensions: dict[str, list[float]] = defaultdict(list)
        weighted: list[float] = []
        category_weighted: dict[str, list[float]] = defaultdict(list)
        for case in payload["cases"].values():
            row = case[model]
            for dimension in weights:
                dimensions[dimension].append(float(row[dimension]))
            value = sum(float(row[dimension]) * weight for dimension, weight in weights.items())
            weighted.append(value)
            category_weighted[case["category"]].append(value)
        result["models"][model] = {
            "case_count": len(weighted),
            "prompt_adherence_mean": round(statistics.mean(dimensions["prompt_adherence"]), 3),
            "visual_quality_mean": round(statistics.mean(dimensions["visual_quality"]), 3),
            "structure_artifacts_mean": round(statistics.mean(dimensions["structure_artifacts"]), 3),
            "weighted_mean": round(statistics.mean(weighted), 3),
            "category_weighted_mean": {
                category: round(statistics.mean(values), 3)
                for category, values in sorted(category_weighted.items())
            },
        }
    return result


def model_inventory() -> dict[str, Any]:
    models: dict[str, Any] = {}
    for model, paths in MODEL_FILES.items():
        files = []
        for path in paths:
            files.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                    "size_gib": round(path.stat().st_size / 1024**3, 3),
                    "sha256": HASHES[path.name],
                }
            )
        models[model] = {
            "files": files,
            "total_size_bytes": sum(row["size_bytes"] for row in files),
            "total_size_gib": round(sum(row["size_bytes"] for row in files) / 1024**3, 3),
        }
    models["anima_original"]["source"] = {
        "model": "MiaoMiao Harem",
        "version": "Anima_1.5",
        "civitai_model_id": 934764,
        "civitai_version_id": 3153747,
        "url": "https://civitai.com/models/934764?modelVersionId=3153747",
    }
    models["anima_29b"]["source"] = {
        "model": "Anima 2.9B",
        "version": "preview v1 BF16",
        "civitai_model_id": 2855007,
        "civitai_version_id": 3224434,
        "civitai_file_id": 3106672,
        "url": "https://civitai.red/models/2855007/anima-29b?modelVersionId=3224434",
        "official_url": "https://huggingface.co/Gazingstars123/Anima-2.9B",
    }
    models["krea2"]["source"] = {
        "model": "DaSiWa Krea2 | Turbo | Raw",
        "version": "CuteDisaster v2 Turbo UC",
        "civitai_model_id": 2760803,
        "civitai_version_id": 3151280,
        "url": "https://civitai.com/models/2760803?modelVersionId=3151280",
        "official_base_url": "https://huggingface.co/krea/Krea-2-Turbo",
    }
    return {
        "machine": {
            "gpu": "NVIDIA GeForce RTX 5090 D",
            "gpu_memory_mb": 32607,
            "driver": "610.88",
            "cpu": "AMD Ryzen 7 9800X3D 8-Core Processor",
            "cpu_cores_threads": "8/16",
            "system_ram_mb": 32662368 / 1024,
            "os": "Windows 11 Pro 10.0.26200 build 26200",
            "python": "3.13.11",
            "pytorch": "2.9.1+cu130",
            "cuda": "13.0",
            "cudnn": 91200,
            "bf16_supported": True,
            "comfyui_commit": "cc0fc21fea7a6a82f568362b15b7fbd713b419c1",
            "anima29_support": "ComfyUI native dynamic block detection; no custom node",
        },
        "models": models,
        "identity_note": "Anima 2.9B reuses the original Anima Qwen3 0.6B text encoder and Qwen Image VAE.",
    }


def plot_resources(stats: dict[str, Any]) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.6), constrained_layout=True)
    x = np.arange(len(MODEL_ORDER))
    colors = [MODEL_COLORS[model] for model in MODEL_ORDER]
    labels = [MODEL_LABELS[model] for model in MODEL_ORDER]
    values = [stats["models"][model]["wall_time_s_mean"] for model in MODEL_ORDER]
    axes[0].bar(x, values, color=colors, width=0.64)
    axes[0].set_title("主测试平均等待时间")
    axes[0].set_ylabel("秒")
    axes[0].set_xticks(x, labels, rotation=12)
    values = [stats["models"][model]["peak_vram_mb_mean"] / 1024 for model in MODEL_ORDER]
    axes[1].bar(x, values, color=colors, width=0.64)
    axes[1].axhline(32607 / 1024, color="#C0392B", linestyle="--", linewidth=1.3, label="显卡总量")
    axes[1].set_title("平均峰值显存")
    axes[1].set_ylabel("GiB")
    axes[1].set_xticks(x, labels, rotation=12)
    axes[1].legend(frameon=False)
    values = [stats["models"][model]["system_available_mb_min"] / 1024 for model in MODEL_ORDER]
    axes[2].bar(x, values, color=colors, width=0.64)
    axes[2].set_title("运行中最低可用系统内存")
    axes[2].set_ylabel("GiB，越高越安全")
    axes[2].set_xticks(x, labels, rotation=12)
    for axis in axes:
        axis.grid(axis="y")
        for patch in axis.patches:
            axis.text(
                patch.get_x() + patch.get_width() / 2,
                patch.get_height(),
                f"{patch.get_height():.1f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
    fig.suptitle("本机冷启动 + 每任务完整卸载的资源表现", fontsize=15, fontweight="bold")
    fig.savefig(ASSETS / "resources.png", dpi=170)
    plt.close(fig)


def plot_scores(stats: dict[str, Any]) -> None:
    dimensions = [
        ("prompt_adherence_mean", "提示服从"),
        ("visual_quality_mean", "视觉质量"),
        ("structure_artifacts_mean", "结构/伪影"),
        ("weighted_mean", "加权总分"),
    ]
    x = np.arange(len(dimensions))
    width = 0.24
    fig, axis = plt.subplots(figsize=(10.5, 5.2), constrained_layout=True)
    for index, model in enumerate(MODEL_ORDER):
        values = [stats["models"][model][key] for key, _ in dimensions]
        bars = axis.bar(
            x + (index - 1) * width,
            values,
            width,
            label=MODEL_LABELS[model],
            color=MODEL_COLORS[model],
        )
        axis.bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
    axis.set_xticks(x, [label for _, label in dimensions])
    axis.set_ylim(0, 5.25)
    axis.set_ylabel("0–5 分")
    axis.set_title("23 个主场景人工逐图评分")
    axis.grid(axis="y")
    axis.legend(frameon=False, ncol=3, loc="lower center")
    fig.savefig(ASSETS / "manual_scores.png", dpi=170)
    plt.close(fig)


def plot_speed(stats: dict[str, Any]) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.4), constrained_layout=True)
    for axis, model in zip(axes, MODEL_ORDER, strict=True):
        points = sorted((int(steps), row) for steps, row in stats[model].items())
        xs = [steps for steps, _ in points]
        ys = [row["median_s"] for _, row in points]
        lower = [row["median_s"] - row["min_s"] for _, row in points]
        upper = [row["max_s"] - row["median_s"] for _, row in points]
        axis.errorbar(
            xs,
            ys,
            yerr=[lower, upper],
            color=MODEL_COLORS[model],
            marker="o",
            linewidth=2.2,
            capsize=5,
        )
        axis.set_title(MODEL_LABELS[model])
        axis.set_xlabel("步数")
        axis.set_ylabel("秒")
        axis.set_xticks(xs)
        axis.grid()
        for x_value, y_value in zip(xs, ys, strict=True):
            axis.annotate(f"{y_value:.2f}s", (x_value, y_value), xytext=(0, 8), textcoords="offset points", ha="center")
    fig.suptitle("三轮冷启动步数曲线（误差棒为最小–最大）", fontsize=15, fontweight="bold")
    fig.savefig(ASSETS / "speed_curves.png", dpi=170)
    plt.close(fig)


def plot_boundary(records: list[dict[str, Any]]) -> None:
    rows = sorted(
        (record for record in records if record["phase"] == "length_boundary"),
        key=lambda record: record["qwen35_token_count"],
    )
    xs = [record["qwen35_token_count"] for record in rows]
    lap = [record["image_metrics"][0]["laplacian_variance"] for record in rows]
    color = [record["image_metrics"][0]["colorfulness"] for record in rows]
    fig, axis = plt.subplots(figsize=(9.5, 5), constrained_layout=True)
    axis.plot(xs, lap, color=MODEL_COLORS["anima_38b"], marker="o", linewidth=2.2, label="Laplacian 清晰度")
    axis.set_xlabel("Qwen3.5 token 数")
    axis.set_ylabel("Laplacian 方差")
    axis.grid()
    controls = sorted(
        (record for record in records if record["phase"] == "length_boundary_control"),
        key=lambda record: record["qwen35_token_count"],
    )
    control_x = [record["qwen35_token_count"] for record in controls]
    control_lap = [record["image_metrics"][0]["laplacian_variance"] for record in controls]
    axis.scatter(
        control_x,
        control_lap,
        color="#1B9E77",
        marker="D",
        s=52,
        zorder=5,
        label="完整句/换尾句控制",
    )
    axis.axvspan(454, 463, color="#F4D03F", alpha=0.24, label="收窄后的崩坏边界")
    second = axis.twinx()
    second.plot(xs, color, color="#2E8B57", marker="s", linewidth=2.0, label="色彩度")
    second.set_ylabel("色彩度")
    handles1, labels1 = axis.get_legend_handles_labels()
    handles2, labels2 = second.get_legend_handles_labels()
    axis.legend(handles1 + handles2, labels1 + labels2, frameon=False, loc="upper right")
    axis.set_title("Anima 3.8B 长提示边界：454 正常，463 起花图")
    fig.savefig(ASSETS / "context_boundary.png", dpi=170)
    plt.close(fig)


def main() -> int:
    configure_plotting()
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = load_records()
    main_summary = main_stats(records)
    speed_summary = speed_stats(records)
    score_summary = score_stats()
    inventory = model_inventory()
    write_json(RAW / "summary_stats.json", main_summary)
    write_json(RAW / "speed_stats.json", speed_summary)
    write_json(RAW / "score_summary.json", score_summary)
    write_json(RAW / "model_inventory.json", inventory)
    plot_resources(main_summary)
    plot_scores(score_summary)
    plot_speed(speed_summary)
    print(f"Wrote summaries to {RAW}")
    print(f"Wrote report assets to {ASSETS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
