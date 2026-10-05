# Alicia Bell / Morning Star Form-Outfit Separation Matrix

Date: 2026-08-18

Purpose: keep the dual-form LoRA trainable while allowing controlled outfit
coverage. Outfit is a captioned condition, not the only identity separator.

## Core Principle

Every candidate must answer three independent questions:

- who is she: `ordinary Alicia Bell form` or `Morning Star form`;
- what outfit branch is visible: ordinary default, ordinary variant,
  `Morning Star default idol outfit`, or `Morning Star alternate idol outfit`;
- whether the image teaches a useful LoRA feature without collapsing the two
  forms into one visual identity.

If the form can only be identified because of the clothing, the candidate is
weak. If the form remains clear even when clothing overlaps, the candidate is
useful.

## Branch Matrix

| Branch | Caption Trigger | Hair | Eyes | Outfit Policy | Selection Gate |
| --- | --- | --- | --- | --- | --- |
| Ordinary default | `ordinary Alicia Bell form` | loose champagne light-brown everyday hair, compact shoulder-length / soft daily styling | honey-hazel brown amber, normal round pupils | covered ivory blouse/cardigan, wine-red A-line skirt, brown low ankle boots | must read offline and grounded; reject idol bodice, sheer stockings, high heels, virtual pupils |
| Ordinary outfit variant | `ordinary Alicia Bell form`, visible clothing terms | same ordinary hair lock | same ordinary eye lock | daily or travel clothing may vary, but stays covered, practical, non-stage | reject if it borrows Morning Star's virtual idol language |
| Morning Star default | `Morning Star form`, `Morning Star default idol outfit` | peach-gold / rose-gold low twin tails or side-bundles, wine-red twin ribbons | soft champagne-peach virtual idol eyes, tiny star catchlight only | approved wine-red and ivory bare-shoulder idol dress, translucent ivory gauze shoulder shawl, small flat star clasp, very sheer ivory stockings, wine-red high heels | this is the fixed main trigger branch; reject accidental costume mutation |
| Morning Star alternate outfit | `Morning Star form`, `Morning Star alternate idol outfit` | same Morning Star hair lock | same Morning Star eye lock | idol outfit may change silhouette/color details only when explicitly tagged | must remain recognizably Morning Star even without the default dress |
| Same clothing contrast test | `same clothing contrast test` plus form trigger | ordinary keeps loose daily hair; Morning Star keeps low twin tails / side-bundles | ordinary keeps natural round pupils; Morning Star keeps soft virtual eyes and tiny star catchlight | both forms may intentionally share clothing for stress testing only | accept only if first-glance form separation still works |

## Morning Star Default Outfit Lock

Use `Morning Star default idol outfit` as the normal Morning Star production
starting phrase. These cues are fixed unless the branch is explicitly
`Morning Star alternate idol outfit`:

- wine-red and ivory bare-shoulder idol dress;
- ivory upper dress;
- wine-red high-waist corset panel;
- compact ivory bell skirt with restrained wine-red underskirt accents;
- short translucent ivory gauze shoulder shawl crossing front chest and upper
  arms;
- small flat gold star voice-core clasp;
- very sheer ivory stage stockings with faint natural gold soundwave
  embroidery;
- wine-red high heels.

Default Morning Star prompt expansion may vary only pose, view, expression,
framing, lighting, and background.

## Form Identity Locks

Ordinary Alicia must keep:

- natural honey-hazel round pupils;
- loose everyday champagne light-brown hair;
- covered, grounded daily presence;
- no virtual markings, no star pupil, no sheer stage stockings, no high heels.

Morning Star must keep:

- peach-gold / rose-gold low twin tails or side-bundles;
- wine-red twin ribbons;
- small gold star hairpiece when visible;
- soft champagne-peach virtual idol eyes with a tiny star catchlight;
- online virtual singer presence;
- sparse orange-gold soundwave / projection language.

## Outfit Variant Rules

Allowed later:

- small controlled branch for `Morning Star alternate idol outfit`;
- ordinary daily/travel clothing variants;
- same-clothing contrast tests as deliberate diagnostics.

Not allowed:

- default Morning Star images drifting into uncaptioned outfit variants;
- ordinary Alicia accidentally inheriting Morning Star hair, eyes, stockings,
  high heels, or stage bodice;
- Morning Star becoming ordinary Alicia with only a costume swap;
- using a single low side ponytail, pure red simple dress, missing gauze
  shawl, opaque stockings, boots, microphones, physical instruments, dense UI,
  large chest gems, long trains, or target-ring pupils as active candidates.

## Round Placement

- R02: Morning Star default idol outfit only, used to prove the corrected base
  is stable across view, pose, and simple scene changes.
- R05: mostly Morning Star default idol outfit coverage, plus a small explicitly
  tagged `Morning Star alternate idol outfit` branch.
- R06: same-clothing contrast tests and core-cue stability checks.
- Final 200 selection: include enough default outfit images to make the default
  trigger reliable; include alternate outfit and same-clothing tests only if
  they preserve form identity and add real training value.
