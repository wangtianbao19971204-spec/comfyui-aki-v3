# Krea 2 Character category purity fix

Date: 2026-07-30

## Confirmed causes

1. The healthy Krea 2 Character and Style index queries are separate and have no
   overlapping model IDs.
2. The previous network fallback converted `category=character` to
   `tag=character`. Tags are not categories, so this fallback could return style
   models and cache them as Character.
3. Civitai also has a small number of upstream Character entries whose names
   explicitly identify them as style LoRAs.

## Changes

- Categorized searches no longer fall back to the public tag endpoint.
- Frontend rendering accepts only items whose `_category` exactly matches the
  active category.
- Character searches remove entries explicitly named as Style LoRA, Artist
  Style, Art Style, Style Pack/Collection/Mix/Model, 画风, 風格, スタイル, or
  스타일.
- Search results now retain lightweight Civitai tag names for future auditing.
- Frontend and backend cache versions were incremented again, isolating all
  previously contaminated category cache entries.

## Validation

- Four JavaScript test suites passed.
- Python unittest discovery passed all 23 tests.
- Live Krea 2 Character, first 100 upstream hits:
  - 99 accepted Character items.
  - 1 explicit `stylelora` entry rejected.
  - 0 wrong `_category` items.
  - 0 explicit style-name items remained.
- Live Krea 2 Style returned 100 Style items.
- Character and Style overlap: 0.
- The third Character UI page displayed 39 items and no `stylelora` or
  `Artist Style` card.
- ComfyUI restarted with its original arguments and returned HTTP 200.
- Temporary validation nodes were removed.

## Backup

`G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\backups\lora_krea_character_purity_20260730_224045`

See `RESTORE.md` in the backup directory for exact restore commands.
