# Anima LoRA Presets

This page lists the first batch of importable Anima LoRA preset TOML files.
They are intended as practical starting points for product integrations, not as
fixed best settings for every dataset.

## Standard LoRA

- [Character LoRA (Automagic)](../config/presets/anima-lora-character-automagic.toml)  
  For single characters, outfits, props, and general character LoRA training.

- [Style LoRA (Automagic)](../config/presets/anima-lora-style-automagic.toml)  
  For art style, coloring, lighting, composition, and texture training.

Standard LoRA presets use `Automagic` to reduce the need for beginners to tune
learning rate and scheduler settings manually.

## Fast LoRA

- [Fast Character LoRA](../config/presets/anima-fast-lora-character.toml)  
  For faster character LoRA training with the Anima Fast plugin runtime.

- [Fast Style LoRA](../config/presets/anima-fast-lora-style.toml)  
  For faster style LoRA training with the Anima Fast plugin runtime.

Fast LoRA currently uses `AdamW8bit` because the Anima Fast plugin runtime does
not support `Automagic`.

## Notes

- These presets intentionally do not include LoKr, T-LoRA, or full finetune
  presets. Those modes are more sensitive to VRAM, dependency versions, speed,
  and parameter combinations, and should be tested separately as advanced
  presets.
- Before exposing presets to end users, test them on 100-300 representative
  images from the target dataset category and verify generated previews.
