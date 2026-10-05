AKI v0.9 - Gelbooru v0.2 UI rollback + minimal output fix

- Gelbooru search/preview/display code is rolled back to the v0.2 baseline, which was the version where preview display worked.
- Output fix is minimal: selection_data is still written to the widget, plus mirrored to /danbooru_gallery/selection_state as a backend fallback.
- No Danbooru browser-bridge mode is included.
- Danbooru remains native API only; if Cloudflare challenges Python requests, the node cannot force real browser cookies/TLS state.
- Credentials are cleared from settings.json. Re-enter Danbooru/Gelbooru API credentials in node settings.
