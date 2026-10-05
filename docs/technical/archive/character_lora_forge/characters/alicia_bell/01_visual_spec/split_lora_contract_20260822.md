# Alicia Bell Split-LoRA Contract

Status: approved architecture for the 2026-08-22 split release.

The previous mixed-form LoRA remains an experiment only. Ordinary Alicia and
Morning Star must be trained, evaluated, and released as two independent LoRAs.
No training caption may contain the other form's trigger token.

## Ordinary Alicia

- Trigger: `alcbo7yo260822`
- Dataset target: 200 unique image-caption pairs.
- Fixed identity: adult Alicia Bell, warm soft oval face, fair warm skin,
  natural honey-hazel amber eyes with normal round pupils, light-brown to
  champagne everyday hair, and a warm approachable offline presence.
- Canonical outfit language: opaque ivory blouse, short teal cardigan or shawl,
  wine-red A-line skirt, and practical brown low ankle boots.
- Variable and captioned: view, crop, pose, expression, scene, lighting, style,
  hand-held object, outfit variant, and visible legwear.
- Hard rejects: Morning Star trigger or form language, peach-pink low twin
  tails, virtual eyes, star hairpiece, translucent stage shoulder gauze,
  off-shoulder idol bodice, sheer ivory stage pantyhose as an identity cue,
  stage heels, or broadcast magic effects.

## Morning Star

- Trigger: `alcbm7yo260822`
- Dataset target: 200 unique image-caption pairs.
- Fixed identity: adult Alicia Bell's Morning Star virtual singer form, warm
  soft oval face, fair luminous skin, warm champagne virtual eyes, peach-gold
  or rose-gold low twin tails or side bundles, wine ribbons, and one small gold
  five-point hairpiece when the crop includes that area.
- Canonical outfit language: opaque wine and ivory idol outfit, plain
  high-waist wine bodice, compact ivory bell skirt with a restrained wine hem,
  short translucent ivory gauze across the shoulders over opaque clothing,
  and wine-red stage heels when feet are visible.
- Fixed hosiery phrase for leg-visible captions: `very sheer ivory pantyhose
  covering both legs and feet, warm skin tone visible through the fabric`.
- Hosiery hard rejects: bare legs in a leg-visible canonical outfit image,
  opaque white leggings, heavy tights, knee socks, detached stockings, garters,
  stocking-top bands, dense geometric or metallic stripes, asymmetric coverage,
  or broken coverage at the feet.
- Upper-body and face crops must not claim hosiery that is outside the frame.
- Hard rejects: ordinary trigger or offline form language, ordinary loose daily
  hair, natural ordinary pupils when virtual-eye detail is visible, teal daily
  cardigan, practical low boots, or loss of the canonical stage silhouette.

## Training And Evaluation

- Use the verified Anima base model, text encoder, and VAE hashes already pinned
  by the forge profiles.
- Keep trigger token first with `keep_tokens = 1` and do not shuffle captions.
- Train each LoRA independently. GPU-heavy training and ComfyUI evaluation are
  serialized.
- Compare steps 100, 200, 300, and 400 at strengths 0.6, 0.8, and 1.0.
- Select the earliest checkpoint that passes identity, anatomy, outfit control,
  accessory control, and style transfer. Morning Star additionally requires a
  hosiery present/absent/replacement matrix.
- Do not recommend loading both split LoRAs at full strength together. They are
  alternate character forms, not additive style modules.
