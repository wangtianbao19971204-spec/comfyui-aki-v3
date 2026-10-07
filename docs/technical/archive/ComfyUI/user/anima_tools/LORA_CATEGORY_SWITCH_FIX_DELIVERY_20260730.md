# LoRA selector category switch fix

Date: 2026-07-30

## Root cause

The selector correctly changed its active sidebar button and request URL, but it sent
the selected value as `category=` to Civitai's public `/api/v1/models` endpoint.
That endpoint ignores `category`, so Action, Clothing, Character, and the other
sidebar entries all returned and cached the same unfiltered page.

## Changes

- Categorized requests now use the category-aware Civitai search index.
- The direct public-API race remains enabled for the unfiltered All page, but is
  skipped for categorized requests.
- If the category-aware index is unavailable, the backend uses the supported
  public `tag=` parameter as a labeled fallback instead of returning the All page.
- Frontend and backend cache versions were incremented so incorrect old category
  pages are ignored automatically.
- Local manifest matching is scoped by Anima/Krea 2 profile.
- Loaded LoRAs and the Already Added state are scoped by the active profile.

## Verification

- All JavaScript tests passed:
  - `anima_lora_manifest_matching.test.mjs`
  - `anima_lora_node_widgets.test.mjs`
  - `anima_selector_ui.test.mjs`
  - `anima_shared_prompt_data.test.mjs`
- Python unittest discovery: 22 tests passed.
- Live backend:
  - Anima / Action returned category `action`.
  - Anima / Clothing returned category `clothing` with a different model ID set.
  - Krea 2 / Style returned category `style`.
- Live selector:
  - Action changed to 11 action models.
  - Clothing changed to clothing models.
  - Krea 2 / Clothing changed to Krea 2 clothing models.
  - Downloaded changed between 125 Anima LoRAs and 39 Krea 2 LoRAs, with their
    respective folder lists.
- ComfyUI was restarted with its original arguments and returned HTTP 200.
- Temporary validation nodes were removed from the test workflow.

## Backup and restore

Backup:

`G:\ComfyUI-aki-v3\ComfyUI\user\anima_tools\backups\lora_category_switch_20260730_212253`

See `RESTORE.md` in the backup directory for exact restore commands.
