# ComfyUI-Danbooru-Browser-Import v0.6

This version keeps the v0.5 browser endpoint:

- POST `/danbooru_browser_import_v05`
- GET `/danbooru_browser_import_v05_status`

Fixes:

- Adds `IS_CHANGED` based on the received JSON file mtime, so the ComfyUI node refreshes after the browser sends new tags.
- Keeps the node type `DanbooruBrowserImportV05`, so existing workflows do not break.

Install: replace the old `ComfyUI-Danbooru-Browser-Import` folder in `custom_nodes`, then fully restart ComfyUI.
