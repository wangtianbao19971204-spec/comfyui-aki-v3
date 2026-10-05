# Alicia Bell Morning Star Anima 2.9B LoRA v1 Evaluation

## Decision

Select the 300-step checkpoint at strength 0.8.

It is the earliest checkpoint that retains the single gold five-point hair star
on both fixed canonical seeds while improving the Morning Star face, low twin
tails, shoulder gauze, corset, bell skirt, and hosiery construction. Step 200 is
still inconsistent on the hair star. Step 400 sharpens the outfit more strongly
but loses the star on the second seed and shows an over-defined corset/skirt
boundary at strength 1.0.

## Dataset

- Morning Star v5 only; ordinary Alicia was not included
- 200 unique PNG/TXT pairs
- 200/200 captions begin with `alcbm7yo260822`
- No missing pairs, empty files, unreadable images, or exact image duplicates
- Source dataset was preserved; prepared runs used hard-linked staging trees

## Training

- Base: `anima29B_v10_bf16.safetensors`, 40 blocks
- BF16, Rank 32, Alpha 16, AdamW, learning rate `2e-5`
- Batch 1, resolution buckets 512-1536, bucket step 64
- Cached latents and text-encoder outputs
- DiT-only training, gradient checkpointing, Windows data-loader workers 0
- 75-step smoke: return code 0, final average loss about 0.0709
- 400-step calibration: return code 0, 9 minutes 16 seconds, final average loss about 0.0745
- Steady training VRAM: about 15.6 GiB

The bundled trainer originally hard-coded 28 blocks. It was changed to infer
transformer depth from safetensors keys. Both the old 28-block base and the new
40-block model were validated. Training logs reported 40 blocks, 400 LoRA
modules, and zero missing or unexpected base-model keys.

## Weight Audit

All 100/200/300/400 checkpoints contain 1200 BF16 tensors and 400 LoRA modules
covering blocks 0-39 contiguously. Every tensor is finite. The LoRA up-weight RMS
increases smoothly from 0.000241 at step 100 to 0.000488 at step 400.

The selected step 300 checkpoint:

- Size: 131,241,592 bytes
- SHA256: `AEF260A4F99B06C612F17101442BE2E80D2B749C33BE6EACC731545F922AECA1`
- Base SHA256: `0B3020D1B906155F7EB30667622723E87160632C8C7A5F1C93BDCE685F2A346D`

## Inference Matrix

ComfyUI generated 34 core images and 6 supplemental high-strength images at
768x1152, 28 Euler steps, CFG 3.5, SGM Uniform, flow shift 3.0. All 40 jobs
completed successfully.

- Canonical strength 0.6/0.8/1.0: pass; 0.8 is the best balance
- Second canonical seed at 0.8: step 300 passes; step 400 loses the hair star
- Casual outfit replacement: pass at every checkpoint
- Watercolor style transfer: pass at every checkpoint
- Explicit hair-star removal: pass at every checkpoint
- Trigger-only recall at 0.8: fail at every checkpoint
- Trigger-only recall at 1.0/1.2/1.5 for steps 300/400: fail
- Strength 1.5: rejected; step 400 begins to distort clothing

The trigger limitation is a caption-allocation issue rather than an inference
strength issue: detailed captions distributed identity learning across explicit
appearance tags. The release remains useful with the tested concise identity
contract, but it should not be advertised as trigger-only.

## GPU Cleanup

Models were unloaded between checkpoint groups and after the final evaluation.
The final `/free` call reduced measured GPU memory use from about 13.5 GiB to
about 6.5 GiB, leaving about 25.6 GiB free.

## Evidence

Full prompts, histories, images, results, and contact sheets:

`benchmark_reports/2026-08-24_anima29_morning_star_training_eval/`
