# 艾莉西亚·贝尔 200 张黄金图包计划

## Source Interpretation

- Treat `00_source/艾莉西亚lv1西征.xlsx` as character data only.
- Use `02_master_refs/alicia_bell_primary_market_fullbody.png` as the only master identity image for now, but reinterpret its stage/travel details through the high-magic network idol setting.
- For Morning Star production, use `02_master_refs/morning_star_base_fullbody_translucent_shawl.png`, `02_master_refs/morning_star_base_closeup_translucent_shawl.png`, `02_master_refs/morning_star_default_idol_outfit_approved_001.png`, and `02_master_refs/morning_star_default_idol_outfit_approved_002.png` as the approved default outfit base images. They override later simplified single-side-ponytail red-dress variants.
- The duplicate large image is kept in source but not counted as a second identity reference.
- Small embedded icons are ability or sheet decoration references, not identity anchors.
- The main sheet says age 23; all gold prompts and captions use adult 23-year-old coding.

## Trigger

`alcbl7yo260817`

## Current Reset

- First define two clean base forms before any 120-image production.
- Previous magical stage pilots are direction references only; their mixed backgrounds are not suitable LoRA base anchors.
- Base images must use plain or near-plain backgrounds, brighter fair warm skin, and simple readable skirt silhouettes.
- 2026-08-17 idol reference pass: studied recent/active idol project official pages and translated the shared design language into Morning Star rules: bold stage silhouette, coordinated headpiece/waist/skirt/legwear/shoe design, controlled hair ends, and no reliance on busy concert backgrounds.
- 2026-08-18 clarity pass: reference Blue Archive-like readable character setup and Idolmaster-like idol proportion. Morning Star should be concise, light, and readable: no design-by-piling-up.

## Two Base Forms

- Ordinary Alicia: offline everyday form, covered ivory blouse or light cardigan, simple wine-red A-line skirt, teal short shawl or small collar cape, brown low ankle boots, minimal gold trim, honey-hazel brown amber eyes with simple normal round pupils, loose light-brown/champagne everyday hair, no stage effects.
- Morning Star: online magical-network singer form. It should be much bolder than ordinary Alicia, but LoRA-clean and concise: controlled peach-gold or rose-gold low twin-tail / side-bundle hair with ribbon-bound, curled, or bluntly gathered ends that hang close to the body; soft champagne-gold to peach-gold virtual eyes with a gentle small star catchlight or subtle tiny star aperture and at most one faint soundwave crescent highlight; larger fabric star ribbon or small metal star hairpiece; `Morning Star default idol outfit` as the normal starting trigger: off-shoulder fitted idol bodice, translucent chest-to-upper-arm gauze shawl, readable compact A-line or bell skirt, no green sleeve cuffs, teal arm sleeves, or shoulder-covering green capelet; short wrist cuffs or small gloves only below the wrist; very sheer ivory stockings with skin tone visible through the fabric and natural coral-gold soundwave embroidery; elegant wine-red high-heeled stage shoes; small integrated voice-core brooch; subtle ear monitor; coral-gold and amber light accents; sparse orange-gold soundwave glyphs.
- Both forms must keep only the important recognition thread: similar soft face, warm amber/gold eye family, warm luminous hair family, adult age coding, fair warm skin, and warm sincere personality. They should look very different at first glance, but like the same person after close analysis.
- Morning Star costume changes are reserved for an explicit `Morning Star alternate idol outfit` branch. Normal pose, scene, view, and style expansion must not mutate the default idol outfit.
- If ordinary Alicia and Morning Star intentionally wear the same clothing in a contrast test, they must still separate at first glance: ordinary Alicia through loose everyday hair, natural round pupils, and grounded offline posture; Morning Star through peach-gold low twin tails, wine-red ribbons, small star hairpiece, soft virtual idol eyes, and brighter online singer presence.

## Base Image Gates

- Background: plain warm off-white, pale gold, or light gray; no market clutter, dark stage, dense UI, or dominant magic circle.
- Skin and exposure: fair warm luminous skin, bright soft studio light, no muddy shadows or dim concert lighting.
- Outfit: simple clean skirt hem, minimal accessories for ordinary Alicia; Morning Star may have stronger idol ornaments but must remain readable and not become cluttered. Ordinary Alicia must not borrow Morning Star's sheer stockings, high heels, off-shoulder idol bodice, rose-gold low twin tails, or virtual pupil marks. Avoid glass-shard ornaments, prismatic color blocks, oversized chest gems, hair spreading across the whole canvas, scattered hair tips, and bulky/flat boots.
- Shoes: Morning Star full-body bases must use elegant high-heeled stage shoes or high-heeled ankle boots; ugly utilitarian boots fail the base gate.
- Back hem: Morning Star may have a short asymmetric capelet and layered idol skirt, but the rear hem and upper cape back must stay compact; large flying trains or banner-like back panels fail the base gate.
- Sleeves/shoulders: Morning Star should use a modest off-shoulder idol top. Green sleeve cuffs, teal arm sleeves, and shoulder-covering green capelets fail the base gate.
- Design clarity: Morning Star should have only a few strong identity points. Too many stars, trims, dangling ornaments, or costume parts fail the base gate even if pretty.
- Hair motion: Morning Star hair should be controlled and close to the body. Wind-lifted sideways hair or floating hair trails fail the base gate.
- Props: no lute, guitar, band instrument, handheld microphone, or microphone stand.
- Composition: one character only, full body with feet visible or clean bust portrait, no model sheet.

## Current Morning Star Candidate

- `runs/20260817_morning_star_refined_base/candidates/refined_001_morning_star_fullbody.png` is downgraded to needs-revision after user review because the hair ends still read too scattered, the idol transformation is too conservative, and the shoes are not strong enough.
- `runs/20260817_morning_star_idol_heels_base/candidates/idol_heels_001_morning_star_fullbody.png` has the better overall image but too much unnecessary flying rear cloth.
- `runs/20260817_morning_star_idol_heels_base/candidates/idol_heels_002_morning_star_fullbody_preferred.png` has the better shoes and is retained as the shoe reference.
- `runs/20260818_morning_star_combined_heels_base/candidates/combined_001_morning_star_fullbody.png` is the current preferred Morning Star full-body direction: 001-like overall image, 002-like elegant high-heeled stage shoes, compact back hem, and no large rear banner panel.
- User follow-up: combined_001 overall shape is acceptable, but the green sleeve/capelet should be removed for a modest off-shoulder design, the body should feel lighter, and the hair should stop lifting or floating sideways. This led to the lighter off-shoulder pass below.
- `runs/20260818_morning_star_offshoulder_light_base/candidates/offshoulder_003_preferred_morning_star_fullbody.png` is the current preferred Morning Star full-body direction: green sleeve/capelet removed, modest off-shoulder upper body, lighter cleaner idol costume, controlled low twin-tail / side-bundle hair close to the body, and elegant high-heeled shoes.
- User follow-up: perform Codex aesthetic optimization without changing the established setting. This led to a polish pass focused on line rhythm, refined bodice/skirt construction, smaller integrated brooch, cleaner leg details, and stronger full-body silhouette.
- `runs/20260818_morning_star_aesthetic_polish_base/candidates/aesthetic_002_preferred_morning_star_fullbody.png` is the current preferred Morning Star full-body direction: same setting and identity, better shoulder-neck line, more intentional high-waist bodice, cleaner pleated skirt, reduced ornament noise, controlled low twin-tail / side-bundle hair, and elegant stage heels.
- User follow-up: lock this direction, but add the liked translucent forearm/front-chest chiffon feeling, make stockings sheer with more natural gold soundwave lines, and allow stronger online-avatar differentiation from ordinary Alicia through distinct Morning Star hair and even golden-amber virtual pupil highlights.
- Transparency rule: only decorative chiffon overlay and stockings may be sheer. The main bodice, chest coverage, and skirt stay opaque and modest.
- Avatar difference rule: ordinary Alicia keeps loose light-brown/champagne hair and normal amber eyes; Morning Star should use more virtual peach/rose-gold low twin-tail / side-bundle hair and may use golden-amber star-ring or soundwave pupil highlights.
- `runs/20260818_morning_star_sheer_avatar_diff_base/candidates/sheer_diff_002_preferred_morning_star_fullbody.png` is the current preferred Morning Star full-body direction: locked aesthetic design, narrower translucent front-chest chiffon overlay, sheer ivory stockings, more natural coral-gold stocking line, and stronger online-avatar hair difference.
- 2026-08-18 strong contrast pass: make Morning Star 002 stockings even more transparent, lock visible virtual pupil and hair differences as online-only avatar traits, then generate a new ordinary/casual form that is immediately different from Morning Star while preserving the same face, adult proportions, warm skin, and warm sincere identity thread.
- `runs/20260818_ordinary_vs_morning_star_contrast_base/candidates/ordinary_contrast_001_fullbody.png` is downgraded to needs-eye-revision after user review because the eye color still reads too similar to Morning Star. The outfit and hair direction remain useful, but the ordinary eye anchor should become honey-hazel brown amber with a simple round pupil.
- `runs/20260818_ordinary_vs_morning_star_contrast_base/candidates/morning_star_sheer_003_fullbody.png` is the current Morning Star sheer refinement for user review: it preserves the accepted 002 design while making the ivory stockings more transparent. Full-body scale still limits pupil-shape readability, so a later bust anchor should lock the virtual star/soundwave pupil clearly.
- 2026-08-18 eye contrast pass: ordinary eyes must be honey-hazel brown amber with simple normal round pupils. Morning Star eyes should be softer champagne-gold to peach-gold with a gentle small star catchlight or subtle tiny star aperture and at most one faint soundwave crescent highlight. Use bust/close-up anchors to prove this because full-body images do not show pupil shape reliably.
- `runs/20260818_eye_color_pupil_contrast_base/candidates/ordinary_eye_contrast_001_bust.png` is the current ordinary eye anchor for user review: natural honey-hazel brown amber irises with simple normal round pupils.
- `runs/20260818_eye_color_pupil_contrast_base/candidates/morning_star_eye_contrast_001_bust.png` is downgraded to too-intense after user review because the multi-ring citrine/rose eye reads妖异/侵略性.
- `runs/20260818_eye_color_pupil_soften_base/candidates/morning_star_eye_soft_001_bust.png` is the current Morning Star eye anchor for user review: softer champagne-peach virtual eyes, gentle star catchlight, less multi-ring pressure, and a kinder idol-songstress expression.
- 2026-08-18 anchor correction: user clarified that the Morning Star base images are the full-body translucent-shawl design and matching close-up. From this point, Morning Star candidates must preserve the approved low twin-tail / side-bundle hair, star hairpiece, small flat star voice-core clasp, translucent chest-to-upper-arm gauze shawl, wine-red and ivory high-waist idol costume, very sheer ivory stockings, and wine-red high heels.

## Final Dataset Shape

- 200 PNG/TXT pairs after the base forms and 20-round campaign are approved.
- Trigger token first in every caption.
- 20 production rounds, each 200 candidates:
  - 100 ordinary Alicia candidates;
  - 100 Morning Star performance-form candidates, mostly default idol outfit with only explicitly tagged alternate outfit tests in designated rounds;
  - select 25 ordinary + 25 Morning Star per round.
- Campaign pool:
  - 4000 generated candidates;
  - 1000 provisional selected images;
  - final 1000 -> 200 elite selection.
- Final 200 target split:
  - 100 ordinary Alicia;
  - 100 Morning Star.
- Recommended final structure:
  - 60 identity anchors;
  - 70 clothing, role, and accessory images;
  - 50 style and scene stress-test images;
  - 20 reserve elite / repair picks for weak coverage.
- Fully clothed, opaque clothing in every accepted image.
- No model sheets, text, watermark, duplicate people, school context, or NSFW framing.
- Physical instruments are deprecated. A lute or guitar should not be a required identity item and should normally be rejected unless deliberately used as a rare old-setting cameo.

## Production Rounds

1. Base pilot: 16 candidates to confirm ordinary full body, ordinary bust, Morning Star full body, Morning Star bust, profile/rear-ish hair construction, hand readability, and shoe/stocking readability.
2. R01-R20 production campaign: each round generates 200 independent candidates, split 100 ordinary / 100 Morning Star.
3. Per-round monitoring gate: score all 200, hard-reject first, run `tools/round_gate_20x200.py`, inspect selected and reject contact sheets, and stop the campaign if the gate reports `pause_for_repair`.
4. Per-round shortlist: select 25 ordinary + 25 Morning Star only after the gate passes, retain 8-12 backups, and write the round report.
5. Provisional pool: merge 20 x 50 selected images into a 1000-image pool.
6. Pool audit: normalize scores, shuffle contact sheets, exact duplicate scan, dHash near-duplicate review, coverage tables across scenes, clothing, form, view, framing, pose, accessories, and styles.
7. Final elite selection: choose 200 from the 1000 pool, target exactly 100 ordinary + 100 Morning Star.
8. Final audit: shuffled visual review, duplicate scan, caption check, coverage declaration, and `audit_dataset.py`.

## Per-Round Monitoring Gate

- The 20 rounds must not run unattended as one 4000-image dump.
- After every 200-candidate round, the campaign pauses for a gate report.
- The gate requires 25 acceptable ordinary Alicia images and 25 acceptable Morning Star images.
- The gate pauses for repair if either form has fewer than 25 acceptable images, more than 25% hard rejects, more than 15% VLM failures, more than 20% low-identity failures, or more than 20% adult/proportion failures.
- Repair means modifying the next prompt batch, tightening negative prompts, lowering background complexity, or rerunning the weak round before continuing.
- The main watch points are ordinary/Morning Star collapse, wrong pupil color or shape, harsh Morning Star eyes, scattered hair ends, muddy skin, cluttered background, ugly shoes, opaque stockings, and accessory pile-up.

## Primary Acceptance Gates

- Same adult human woman with warm amber/gold/coral eye family and warm blond/peach hair family; ordinary uses honey-hazel round pupils and loose light-brown/champagne daily hair, while Morning Star uses softer champagne-peach virtual eyes with a gentle star catchlight and peach/rose-gold low twin-tail / side-bundle hair.
- Petite adult proportions, not child-coded.
- Wine-red, ivory, teal-blue, brown leather, and warm orange-gold palette remains readable.
- Magical network singer elements appear correctly when requested: floating soundwave glyphs, projection panels, crystal voice interface, subtle ear monitor, star ornaments, virtual stage light, and a visibly more idol-like avatar form.
- Physical instruments do not dominate the character identity.
- Outfit variation is captioned and must not replace the identity.
- Style diversity is reduced or removed if it changes face, hair, age, or outfit identity.
