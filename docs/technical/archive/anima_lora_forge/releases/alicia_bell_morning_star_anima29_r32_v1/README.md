# Alicia Bell Morning Star Anima 2.9B LoRA v1

- File: `alicia_bell_morning_star_anima29_r32_v1.safetensors`
- Base model: Anima 2.9B v1.0 BF16, 40 transformer blocks
- Base SHA256: `0B3020D1B906155F7EB30667622723E87160632C8C7A5F1C93BDCE685F2A346D`
- Trigger: `alcbm7yo260822`
- Rank / Alpha: 32 / 16
- Selected checkpoint: 300 steps
- Recommended strength: `0.8`
- LoRA SHA256: `AEF260A4F99B06C612F17101442BE2E80D2B749C33BE6EACC731545F922AECA1`

This release was trained only on Alicia Bell's Morning Star form. It contains
400 LoRA modules covering Anima 2.9B blocks 0-39. It is separate from the older
28-block Anima Base release.

Use the tested canonical prompt in `prompt_pack.txt`. The LoRA improves the
Morning Star face, low twin tails, wine-red ribbons, single gold hair star,
shoulder gauze, corset, bell skirt, and hosiery construction when those traits
are named explicitly.

Important limitation: the trigger token by itself does not recall the complete
Morning Star identity, even at strengths 1.0-1.5. Strength 1.5 begins to distort
clothing. Keep the LoRA at 0.8 and use the concise identity contract.

Step 300 was selected over step 400 because it was the earliest checkpoint that
kept the gold hair star across both canonical seeds at strength 0.8. Step 400
started to sharpen the corset/skirt boundary excessively and lost the star on
the second canonical seed.
