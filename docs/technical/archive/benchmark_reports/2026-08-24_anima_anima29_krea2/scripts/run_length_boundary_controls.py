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

PROGRESSIVE_SUFFIXES = [
    " Soft mist fills the distance.",
    " Reflections remain calm and geometrically aligned.",
    " Fine rain is visible against the dark steel.",
    " Fabrics stay matte with crisp seams.",
]

ALTERNATE_SUFFIX = (
    " Sharp focus, realistic rain, distinct faces, readable objects, controlled "
    "highlights, fine fabric texture, coherent anatomy, deep perspective. Natural "
    "colors. Balanced lighting."
)


def main() -> int:
    config = load_json(CONFIG_PATH)
    long_case = next(case for case in config["cases"] if case["id"] == "length_long")
    tokenizer = PreTrainedTokenizerFast(tokenizer_file=str(TOKENIZER_FILE))
    full_tokens = tokenizer.encode(long_case["prompt"], add_special_tokens=False)
    base = tokenizer.decode(
        full_tokens[:448],
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )

    variants: list[tuple[str, str]] = []
    progressive = base
    for suffix in PROGRESSIVE_SUFFIXES:
        progressive += suffix
        token_count = len(tokenizer.encode(progressive, add_special_tokens=False))
        variants.append((f"complete_{token_count:04d}", progressive))
    alternate = base + ALTERNATE_SUFFIX
    alternate_count = len(tokenizer.encode(alternate, add_special_tokens=False))
    variants.append((f"alternate_{alternate_count:04d}", alternate))

    completed = successful_job_keys()
    client = ComfyClient(config["server"], timeout=900)
    client.wait_idle()
    client.unload_models()
    try:
        for index, (variant_name, prompt_text) in enumerate(variants, start=1):
            actual_tokens = len(tokenizer.encode(prompt_text, add_special_tokens=False))
            case = dict(long_case)
            case["id"] = f"length_boundary_control_{variant_name}"
            case["phase"] = "length_boundary_control"
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
                print(f"[{index}/{len(variants)}] SKIP {key}", flush=True)
                continue
            print(
                f"[{index}/{len(variants)}] RUN {variant_name} tokens={actual_tokens}",
                flush=True,
            )
            record = run_one(client, config, "anima_38b", case, None, "common")
            record["qwen35_token_count"] = actual_tokens
            record["boundary_control"] = variant_name
            append_result(record)
            print(
                json.dumps(
                    {
                        "success": record.get("success"),
                        "variant": variant_name,
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
