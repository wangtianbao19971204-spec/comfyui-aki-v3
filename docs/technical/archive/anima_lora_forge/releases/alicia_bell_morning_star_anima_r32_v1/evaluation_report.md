# Alicia Bell Morning Star Anima LoRA v1 Evaluation

## Decision

Select the 150-step refinement checkpoint at strength 0.8. It is the latest
fixed-seed checkpoint that retains a single-person anchor. The 175-step result
already switches to a front/back reference layout. Step 125 is retained as a
slightly softer fallback.

## Dataset

- Dataset: Morning Star v5, 200 unique PNG/TXT pairs
- Trigger: every caption begins with `alcbm7yo260822`
- Selection balance: 20 rounds, 10 images per round
- Cumulative targeted image replacements: 23
- Deterministic audit: pass, no missing pairs, warnings, or exact duplicates
- Global visual audit: pass across indexes 1-200, hard rejects 0, caption fixes 0
- Hosiery contract: plain continuous very sheer ivory pantyhose, with no welt,
  top band, over-knee structure, opaque white sock area, or pattern

## Training

- BF16, Rank 32, Alpha 16, AdamW, learning rate `2e-5`
- Windows data-loader workers: 0
- 50-step smoke: complete, final average loss approximately `0.0673`
- 400-step calibration: complete, final average loss approximately `0.0686`
- 175-step refinement: complete, final average loss approximately `0.0725`
- Steady training VRAM: approximately 9.5 GB
- Selected run: `alicia_bell_morning_star_refine_175_v1`

## Checkpoints

- 100: single-person and editable, but identity is comparatively soft
- 125: single-person, all tested property controls pass; retained as fallback
- 150: stronger face/eye/canonical anchor, still single-person; selected
- 175: front/back two-view layout appears; rejected
- 200/300/400: two-view or reference-sheet layout persists; rejected

## Control Matrix

- Canonical identity and anatomy at 0.8: pass
- Hosiery absent: pass; bare legs and bare feet are produced
- Hosiery replaced: pass; opaque charcoal tights are produced
- Hair star absent: pass
- Hair star replaced with pearl clip: pass
- Ordinary-form leakage: pass; no teal cardigan, brown ankle boots, or ordinary
  loose hairstyle in the Morning Star anchor
- Strength 0.6: single-person but softer identity
- Strength 0.8: best balance; selected
- Strength 1.0: single-person but can introduce ankle hosiery boundaries
- Watercolor and stylized 3D: partial; clothing/hosiery survive, but hair color
  and face can drift toward the base model

## Provenance

Sweep and control manifests, prompts, seeds, images, and contact sheets are in
`runs/alicia_bell_morning_star/split_evaluation/`. The release audit records 840
BF16 tensors, Rank 32, Alpha 16, 200 training images, and the selected SHA256.

## 2026-08-22 Strengthening Audit

- Built a separate 72-image correction set from approved v5 sources: 40 full
  hosiery/skirt anchors, 12 additional hosiery views, 12 five-point-star identity
  anchors, and 8 scene anchors.
- Confirmed true continuation through `--network_weights`; the released v1 was
  loaded as the initial Rank-32 network rather than restarting from Anima Base.
- Rejected the first 100-step continuation because compressed `wine` tags were
  interpreted as the drink and shifted corsets toward gold/black.
- Rebuilt captions with explicit `wine-red` and `peach rose-gold` terms and ran a
  conservative `2e-6` continuation through 80 steps.
- Fixed-seed comparison of v1 and the earliest 20-step checkpoint showed no
  material net improvement under the same precise prompt. The continuation is
  retained as an experiment and is not released.
- Revalidated v1 on 12 fixed seeds with the new strict prompt: 12/12 single-person
  identity, 12/12 opaque high-neck ivory top, 12/12 ivory bell skirt with wine-red
  hem, 12/12 gold hair star present, and 0 major anatomy failures.
- Pantyhose coverage remains seed-sensitive: the strict prompt avoids stocking
  bands and opaque white tights, but apparent transparency ranges from visible
  nude nylon to nearly bare. Keep strength at 0.8 and use the tested hosiery phrase.

Artifacts are stored in `_codex_artifacts/morning_star_v1_precise_stability_20260822`
and the two checkpoint-screen directories beside it.

## 2026-08-22 Extended Bow-Tie Audit

- Stopped the first expanded run after four images exposed a prompt omission:
  neither the quick nor strict prompt explicitly requested the canonical neck bow.
- The original 200-image training metadata contains 31 `plain collar knot`, 13
  `plain ivory high collar with a wine-red fabric bow`, and several related bow
  variants. The 72-image correction captions did not explicitly name this trait,
  although it is visibly present in most front-facing source images.
- A six-image phrase A/B found `small wine-red bow tie at throat` more legible than
  `plain wine-red collar knot`; both tested seeds produced a recognizable bow.
- Ran 32 additional fixed-seed images: v1, first-continuation step 25, conservative
  step 20, and conservative step 80, across strict, concise canonical, bright-stage,
  and weak-hosiery prompts. The explicit bow phrase produced a bow in 32/32 images.
- All candidates remained very close to v1. The continuation checkpoints did not
  improve bow size, canonical skirt structure, or hosiery consistency enough to
  justify replacing the release.
- Weight audit confirms real continuation training: each candidate changes 560 of
  840 tensors relative to v1. Relative L2 deltas are 0.000717351 at step 25,
  0.000245821 at conservative step 20, and 0.000631472 at conservative step 80.

The expanded contact sheets and manifest are stored in
`_codex_artifacts/morning_star_extended_eval_bowfix_20260822`.

## 2026-08-22 Implicit Bow Feasibility Test

- Built a 44-image high-confidence subset in which every reference visibly contains
  the canonical throat bow; rear and ambiguous references were excluded.
- Tested three true v1 continuation strategies: explicit bow labels for 40 steps at
  `3e-6`, bow bundled into the trigger for 40 steps at `3e-6`, and an 80-step bundle
  stress test at `1e-5`.
- Evaluated strict full-body, concise full-body, and upper-body portrait prompts with
  every bow-related prompt word deliberately omitted.
- Explicit-label candidates produced 0/18 throat bows, conservative bundle candidates
  produced 0/12, and stress candidates produced 0/18.
- All pilots changed 560/840 tensors. The stress run reached a relative L2 delta of
  `0.002843551` versus v1, but changed hair ribbons, corset details, star scale, skirt
  construction, and face rendering before learning an implicit throat bow.
- Decision: retain v1 and keep `(small wine-red bow tie at throat:1.2)` in the tested
  prompt. Further continuation is not justified for this trait.

Full evidence is stored in
`_codex_artifacts/morning_star_bow_pilot_eval_20260822/feasibility_report.md`.
