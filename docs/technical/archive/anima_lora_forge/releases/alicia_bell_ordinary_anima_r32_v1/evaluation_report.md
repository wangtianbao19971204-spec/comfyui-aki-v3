# Alicia Bell Ordinary Anima LoRA v1 Evaluation

## Decision

Select the 300-step checkpoint at strength 0.8. It was the only checkpoint in
the fixed-seed 100/200/300/400 anchor sweep that consistently produced one
character rather than a front/back reference-sheet layout.

## Training

- Dataset: 200 unique PNG/TXT pairs, all captions begin with `alcbo7yo260822`
- Global visual audit: pass across 10 contact sheets and 29 native spot checks
- BF16, Rank 32, Alpha 16, AdamW, learning rate `2e-5`
- 400 requested steps; checkpoints every 100 steps
- Final average loss: approximately `0.0762`
- Peak steady training VRAM: approximately 9.1 GB
- Completed run: `alicia_bell_ordinary_400_v4`, return code 0

## Checkpoints

- 100: canonical identity formed, but fixed-seed anchor produced two-view layout
- 200: stronger identity, but two-view layout remained at all tested strengths
- 300: single-person anchor at 0.6, 0.8, and 1.0; selected
- 400: returned to two-view anchor overbinding; rejected

## Control Matrix

- Canonical identity and anatomy: pass
- Morning Star leakage: pass; no twin tails, hair star, idol dress, or hosiery lock
- Formal wardrobe: pass
- Modern casual wardrobe: pass with weaker braid/ribbon retention
- Watercolor style: pass
- Stylized 3D: partial; outfit survives but hair can become too dark
- Strengths 0.6/0.8/1.0: all remain single-person; 0.8 is the best balance

## Provenance

Sweep and control manifests, prompts, seeds, images, and contact sheets are in
`runs/alicia_bell_ordinary/split_evaluation/`. The 200-step weight is retained
as a softer fallback, but it has a known reference-layout risk.
