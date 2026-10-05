# Alicia Bell Gold Image Selection Strategy Review - 2026-08-18

This is a pre-production review draft. It supersedes the earlier 3-round / 120-image plan.

## User-Approved Scale

Final campaign size:

- 20 production rounds.
- Each round generates 200 independent candidates.
- Each round is split exactly half and half:
  - 100 ordinary Alicia candidates.
  - 100 Morning Star performance-form candidates.
- Each round selects exactly 50 provisional gold candidates:
  - 25 ordinary Alicia.
  - 25 Morning Star.
- After 20 rounds:
  - 4000 total generated candidates.
  - 1000 provisional selected candidates.
  - Final elite selection: 1000 -> 200 final gold images.

This is a high-redundancy screening plan. The goal is not to preserve every pretty image; the goal is to produce a clean, balanced, LoRA-useful 200-image set with strong identity, stable two-form contrast, and broad coverage.

## Starting Anchors

- Ordinary Alicia direction: use the ordinary full-body outfit/hair direction from `runs/20260818_ordinary_vs_morning_star_contrast_base/candidates/ordinary_contrast_001_fullbody.png`, but update its eye rule from the later bust anchor.
- Ordinary eye anchor: `runs/20260818_eye_color_pupil_contrast_base/candidates/ordinary_eye_contrast_001_bust.png`.
- Morning Star full-body direction: `runs/20260818_ordinary_vs_morning_star_contrast_base/candidates/morning_star_sheer_003_fullbody.png`.
- Morning Star eye anchor: `runs/20260818_eye_color_pupil_soften_base/candidates/morning_star_eye_soft_001_bust.png`.

The two forms must be very different at first glance, but share the same adult face, warm sincere expression, fair warm skin, petite adult build, warm hair family, and red/coral/gold memory point.

## Historical Local Pattern

The completed Rosasha project used:

- Prior approved base gold: 40 images.
- Round 2 outfit/role: 160 candidates -> 40 selected.
- Round 3 style/scene: 160 candidates -> 40 selected.
- Final set: 120 PNG/TXT pairs.
- Validation: trigger-first captions, complete PNG/TXT pairing, exact duplicate count 0, near-duplicate dHash <= 6 count 0.

For Alicia, the user requested a larger custom plan:

- 20 rounds x 200 candidates = 4000 candidates.
- 20 rounds x 50 provisional selected = 1000 provisional selected.
- Final elite set = 200 images.

## Preflight Gate Before 20-Round Scaling

Before generating the 4000-candidate campaign, confirm a 16-image base pilot:

- Ordinary full body, front and three-quarter, with honey-hazel round pupils.
- Ordinary bust, front and three-quarter, with natural round pupils.
- Morning Star full body, front and three-quarter, with sheer stockings and compact idol silhouette.
- Morning Star bust, front and three-quarter, with soft champagne-peach virtual eyes and gentle star catchlight.
- One profile/rear-ish view per form to prove hair construction.
- One hand/leg/shoe detail stress image per form.

Do not scale until these four base anchors pass:

- ordinary_alicia_front_fullbody
- ordinary_alicia_bust_eye_anchor
- morning_star_front_fullbody
- morning_star_bust_virtual_eye_anchor

## Round Structure

Every production round uses the same numeric contract:

- 200 candidates total.
- 100 ordinary Alicia candidates.
- 100 Morning Star candidates.
- 25 ordinary selected.
- 25 Morning Star selected.
- 50 provisional selected per round.
- 8-12 backups per round, split as evenly as possible.

Every round must produce:

- Candidate manifest.
- Contact sheets for all 200 candidates.
- Machine score table.
- Codex manual audit table.
- Selected 50 list.
- Backup list.
- Reject summary.
- Coverage table.

## 20-Round Coverage Matrix

The 20 rounds are grouped by purpose, but the 100/100 and 25/25 ordinary/Morning Star split is mandatory in every round.

| Round | Focus | Ordinary 100 | Morning Star 100 | Select |
|---|---|---:|---:|---:|
| R01 | Core identity front/full-body/bust | 100 | 100 | 25 + 25 |
| R02 | View coverage: 3/4, profile, rear 3/4, rear | 100 | 100 | 25 + 25 |
| R03 | Expression and face stability | 100 | 100 | 25 + 25 |
| R04 | Hair, eye, ribbon, hands, shoes/stockings details | 100 | 100 | 25 + 25 |
| R05 | Ordinary daily clothing / Morning Star canonical costume keyword coverage | 100 | 100 | 25 + 25 |
| R06 | Accessory ablation and simplified variants | 100 | 100 | 25 + 25 |
| R07 | High-magic city daily / virtual broadcast stage | 100 | 100 | 25 + 25 |
| R08 | Travel, walking, seated, relaxed poses | 100 | 100 | 25 + 25 |
| R09 | Formal, seasonal, weather, outerwear | 100 | 100 | 25 + 25 |
| R10 | Magical-network support/healer and streamer contexts | 100 | 100 | 25 + 25 |
| R11 | Clean anime reference style stress | 100 | 100 | 25 + 25 |
| R12 | Cinematic anime lighting stress | 100 | 100 | 25 + 25 |
| R13 | Gouache storybook stress | 100 | 100 | 25 + 25 |
| R14 | Watercolor and ink stress | 100 | 100 | 25 + 25 |
| R15 | RPG concept art stress | 100 | 100 | 25 + 25 |
| R16 | Graphic novel / limited-palette ink stress | 100 | 100 | 25 + 25 |
| R17 | Stylized 3D anime render stress | 100 | 100 | 25 + 25 |
| R18 | Pastel/vintage print stress | 100 | 100 | 25 + 25 |
| R19 | Repair round for weak coverage and hard rejects | 100 | 100 | 25 + 25 |
| R20 | Final challenge round: mixed scenes, rare views, edge cases | 100 | 100 | 25 + 25 |

## Per-Round 200 -> 50 Selection

Each round follows this order:

1. Deterministic precheck: all files readable, single image, no missing outputs.
2. Hard reject pass before scoring.
3. Generate contact sheets covering all 200 candidates.
4. LLM/VLM score every non-rejected candidate using the weighted rubric.
5. Build two separate machine shortlists:
   - ordinary Alicia shortlist: top 35-45 from the 100 ordinary candidates.
   - Morning Star shortlist: top 35-45 from the 100 Morning Star candidates.
6. Codex visual audit:
   - inspect all contact sheets, not only machine top picks;
   - open borderline/high-score/disagreement images full size;
   - reject pretty but off-identity images;
   - rescue lower machine-score images only if they fill important coverage safely.
7. Select exactly 25 ordinary and exactly 25 Morning Star.
8. Record 8-12 backups, split as evenly as possible.
9. Write captions only for selected 50 and backups if promoted.
10. Send review materials:
   - selected contact sheet;
   - ordinary 25 list and Morning Star 25 list;
   - top rejects with reasons;
   - per-round coverage table.

## Mandatory Per-Round Monitoring Gate

The 20 production rounds must not run as an unattended 4000-image dump. Every
200-candidate round is a stop gate before the next round starts.

Gate command after scoring a round:

```powershell
python character_lora_forge/characters/alicia_bell/tools/round_gate_20x200.py --round R01 --source-run <round-run-id>
```

Gate contract:

- Select exactly 25 ordinary Alicia images and 25 Morning Star images for the provisional pool.
- Write `gate_report.json`, `gate_report.md`, selected-image copies, score JSON sidecars, captions if present, and selected/reject contact sheets.
- Status `pass` is required before continuing to the next round.
- Status `pause_for_repair` blocks continuation.

Pause conditions:

- Ordinary Alicia acceptable picks below 25.
- Morning Star acceptable picks below 25.
- Hard reject rate over 25% in either form.
- VLM/scoring error rate over 15% in either form.
- Identity low-score rate over 20% in either form.
- Adult/proportion low-score rate over 20% in either form.
- Manual visual review finds a recurring design drift even if numeric scores pass.

Repair actions before continuing:

- Tighten positive prompt language for the weak form.
- Add focused negative terms for the observed failure.
- Reduce background/scene complexity if LoRA cleanliness is declining.
- Rerun the weak round or add a repair subset before starting the next production round.
- Update the campaign manifest or batch prompt note so the same issue is not repeated.

Recurring visual watch points:

- Ordinary Alicia drifting into Morning Star: off-shoulder idol bodice, sheer stockings, high heels, virtual/star pupils, peach-gold low twin-tail / side-bundle hair.
- Morning Star collapsing back into ordinary Alicia: ordinary blouse/cardigan, low boots, ordinary round amber pupils, loose daily hair, weak idol silhouette.
- Morning Star eyes becoming harsh crimson, predatory, multi-ring, hypnotic, or too aggressive.
- Hair becoming wind-exploded, glassy, scattered, or too broad across the canvas.
- Background becoming too busy for LoRA training.
- Skin becoming muddy, overly dark, or face-shadowed.
- Costume becoming design-by-piling-up rather than concise idol design.

## Round-Level Acceptance Targets

Each 50-image provisional set should ideally include:

- At least 14 full-body images.
- At least 10 bust/portrait images.
- At least 6 non-front views.
- At least 4 eye-readable images across both forms.
- At least 4 hand-readable images.
- At least 4 feet/shoes/stocking-readable images when full body is part of the round.
- No near-duplicate cluster larger than 2.
- No single pose/background/outfit variant occupying more than 20% of that round's selection unless the round focus explicitly requires it.

## 1000 Provisional Pool Audit

After 20 rounds, the 1000 provisional images are not final gold yet.

Pool-level audit steps:

1. Merge all selected 50s into a unified 1000-candidate pool.
2. Re-score all 1000 with the same rubric to normalize across rounds.
3. Generate shuffled contact sheets so round order does not bias selection.
4. Run exact hash duplicate check.
5. Run perceptual duplicate check, using dHash distance <= 6 as the strict review threshold.
6. Build coverage tables:
   - ordinary vs Morning Star;
   - full body / knee-up / bust / close face;
   - front / 3/4 / profile / rear 3/4 / rear;
   - pose families;
   - ordinary clothing variants;
   - Morning Star costume and performance variants;
   - accessories present/ablated;
   - scenes/backgrounds;
   - style domains;
   - eye-visible and hand/foot-visible counts.
7. Identify overrepresented clusters and weak coverage before final 200 selection.

## Final 1000 -> 200 Elite Selection

Final target:

- 200 PNG images.
- 200 same-stem TXT captions.
- Captions start with `alcbl7yo260817`.
- All captions describe visible traits only.
- Final ordinary/Morning Star split target: 100 ordinary + 100 Morning Star.

Recommended final 200 structure:

- 60 identity anchors:
  - 30 ordinary.
  - 30 Morning Star.
  - Emphasis on clean face, full-body, views, eyes, hair, and silhouette.
- 70 clothing / role / accessory images:
  - 35 ordinary.
  - 35 Morning Star.
  - Daily, travel, formal, seasonal, accessory ablation, support/healer, streamer, performance.
- 50 style / scene images:
  - 25 ordinary.
  - 25 Morning Star.
  - Balanced across the eight style domains without letting any style dominate.
- 20 reserve elite / repair picks:
  - 10 ordinary.
  - 10 Morning Star.
  - Fill weak coverage discovered in the 1000-pool audit.

Final 200 selection method:

1. First pass: remove all unresolved hard rejects from the 1000 pool.
2. Second pass: remove exact duplicates and near-duplicates with weak information value.
3. Third pass: select the strongest identity anchors first.
4. Fourth pass: fill clothing, role, scene, style, view, and pose quotas.
5. Fifth pass: check ordinary/Morning Star exactly 100/100.
6. Sixth pass: shuffled Codex visual review of the proposed 200.
7. Seventh pass: caption verification and final audit.

## Hard Rejects Before Score

Reject immediately:

- Underage, schoolgirl, child-coded, or ambiguous age presentation.
- Extra person, split panel, model sheet, readable text, logo, signature, or watermark.
- Face no longer recognizably Alicia.
- Ordinary Alicia borrowing Morning Star traits: virtual pupil marks, off-shoulder idol bodice, rose/peach low twin tails, sheer stockings, high heels, stage effects.
- Morning Star losing avatar traits: no idol silhouette, no soft virtual eye distinction, no peach/rose low twin-tail / side-bundle hair, no high-heeled stage shoes in full body.
- Morning Star eye becoming harsh crimson, blood-red, target-like, multi-ring, hypnotic, demonic, predatory, or aggressive.
- Transparent main bodice, transparent skirt, see-through chest coverage, nudity, lingerie, fetish framing, or sexualized off-shoulder.
- Physical lute, guitar, band instrument, handheld microphone, or microphone stand dominating the design.
- Green sleeve cuffs, teal arm sleeves, shoulder-covering green capelet, heavy green upper-body fabric on Morning Star.
- Messy exploded hair, wind-lifted hair, floating hair trails, scattered/frayed hair tips.
- Overly dark skin, muddy shadows, dark concert stage, busy market background, dense UI, dominant magic circle.
- Malformed hands, feet, limbs, face, shoes, or critical crop.
- Exact duplicate or near duplicate with no new training value.

## Weighted Score

Only score candidates that pass hard gates.

- Identity likeness: 30 points. Same adult Alicia face, warm expression, skin, hair family, memory point.
- Adult body/proportions: 20 points. Petite 160 cm adult human proportions, not child-coded, not distorted.
- Technical/anatomy quality: 15 points. Hands, feet, limbs, face, focus, clean render.
- Prompt/form correctness: 15 points. Correct ordinary vs Morning Star form, eye type, hair style, clothing, shoes, background.
- Training information value: 10 points. Adds useful view, pose, outfit, scene, style, or accessory coverage.
- Style identity preservation: 5 points. Style does not redesign the character.
- Aesthetic finish: 5 points. Polished but not overriding identity.

Suggested accept threshold:

- Provisional per-round accept normally at 82+.
- Borderline review at 78-81 only if it fills rare coverage.
- Reject below 78 unless explicitly retained as a repair reference.
- Identity must be at least 24/30 and body/proportions at least 16/20.
- For the final 200, prefer 88+ except for rare coverage slots.

## Final Handoff Audit

Do not call the 200-image set final until all of these pass:

- Exactly 200 PNG images.
- Exactly 200 TXT captions.
- Same-stem PNG/TXT pairing.
- Trigger token first in every caption.
- All files readable.
- Exact duplicate hash count 0.
- Near-duplicate dHash <= 6 manually reviewed, with target 0 retained weak duplicates.
- No unresolved hard-reject images.
- Declared coverage counts for forms, views, framings, outfits, accessories, poses, scenes, and styles.
- Completed Codex visual audit record.
- Reproducible manifest with prompts, references, scores, selected/rejected decisions, hashes, and caption paths.
