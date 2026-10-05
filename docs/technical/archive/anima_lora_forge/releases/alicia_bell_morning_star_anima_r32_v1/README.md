# Alicia Bell Morning Star Anima LoRA v1

- File: `alicia_bell_morning_star_anima_r32_v1.safetensors`
- Base model: Anima Base v1.0
- Trigger: `alcbm7yo260822`
- Rank / Alpha: 32 / 16
- Selected checkpoint: 150 steps
- Recommended strength: `0.8`
- SHA256: `E62F86968AB6E75EB60C2DA03C4FF8FF22F3C0504722C54F5ECA662354301920`

The trigger carries Morning Star Alicia's face and core identity. For the most
stable canonical outfit, use the concise contract in `prompt_pack.txt`: light
peach-blonde hair with a rose-gold tint, wine-red ribbons, one gold five-point
hair star, an opaque ivory high-neck top, wine-red corset, ivory bell skirt, and
transparent nude pantyhose.

At 0.8 the canonical prompt stays single-person while the sheer ivory pantyhose
can be removed or replaced and the hair star can be removed or changed. Strength
1.0 can introduce ankle boundaries; use 0.8 by default. Strong photorealistic 3D
or watercolor prompts can weaken hair color and facial identity.

The August 22 strengthening audit found that two targeted continuation runs did
not materially outperform v1 under the same precise prompt, so v1 remains the
release. See `prompt_pack.txt` for the tested short prompts and
`evaluation_report.md` for the checkpoint comparison.
