from __future__ import annotations

import json
import sys
from pathlib import Path

from transformers import PreTrainedTokenizerFast


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from run_benchmark import (  # noqa: E402
    CONFIG_PATH,
    ComfyClient,
    append_result,
    job_key,
    load_json,
    run_one,
    successful_job_keys,
)


TOKENIZER_FILE = Path(
    r"G:\ComfyUI-aki-v3\ComfyUI\custom_nodes\comfyui-anima-3-8B"
) / "qwen35_tokenizer" / "tokenizer.json"
TARGETS = [384, 448, 480, 496, 504, 512, 520, 544]


def main() -> int:
    config = load_json(CONFIG_PATH)
    long_case = next(case for case in config["cases"] if case["id"] == "length_long")
    tokenizer = PreTrainedTokenizerFast(tokenizer_file=str(TOKENIZER_FILE))
    full_tokens = tokenizer.encode(long_case["prompt"], add_special_tokens=False)
    completed = successful_job_keys()
    client = ComfyClient(config["server"], timeout=900)
    client.wait_idle()
    client.unload_models()
    try:
        for index, target in enumerate(TARGETS, start=1):
            prompt_text = tokenizer.decode(
                full_tokens[:target],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            actual_tokens = len(
                tokenizer.encode(prompt_text, add_special_tokens=False)
            )
            case = dict(long_case)
            case["id"] = f"length_boundary_qwen35_{actual_tokens:04d}"
            case["phase"] = "length_boundary"
            case["prompt"] = prompt_text
            key = job_key(
                case["phase"],
                case["id"],
                "anima_38b",
                int(case["seed"]),
                int(config["models"]["anima_38b"]["steps"]),
                "common",
            )
            if key in completed:
                print(f"[{index}/{len(TARGETS)}] SKIP {key}", flush=True)
                continue
            print(
                f"[{index}/{len(TARGETS)}] RUN target={target} actual={actual_tokens}",
                flush=True,
            )
            record = run_one(
                client,
                config,
                "anima_38b",
                case,
                None,
                "common",
            )
            record["qwen35_token_count"] = actual_tokens
            record["boundary_target"] = target
            append_result(record)
            print(
                json.dumps(
                    {
                        "success": record.get("success"),
                        "qwen35_tokens": actual_tokens,
                        "image": (record.get("output_paths") or [None])[0],
                        "metrics": (record.get("image_metrics") or [None])[0],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        client.unload_models()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
