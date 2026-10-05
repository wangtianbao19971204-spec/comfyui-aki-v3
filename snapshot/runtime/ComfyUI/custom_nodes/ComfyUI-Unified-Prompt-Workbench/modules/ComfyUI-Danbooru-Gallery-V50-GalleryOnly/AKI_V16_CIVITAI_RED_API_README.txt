AKI V16 - Civitai.red API experimental update

Changes:
1. Civitai source now uses https://civitai.red as the primary API host.
2. https://civitai.com is kept as fallback only when civitai.red HTTP/JSON request fails.
3. Civitai image proxy host whitelist now includes civitai.red / civitai.green / civitai.delivery / civitai.com domains.
4. Search parser supports:
   - nsfw:true / nsfw:false / nsfw:any
   - sfw / nsfw shorthand
   - sort:Newest / sort:Most_Reactions / sort:Most_Comments
   - period:Day / period:Week / period:Month / period:Year / period:AllTime
   - model:123, version:123, post:123, user:name
5. nsfw:true/false is both sent to the API and applied as a local fallback filter on the returned page.
6. Added backend route:
   /danbooru_gallery/diagnose_civitai?tags=nsfw:true
   This tests civitai.red and civitai.com Images API paths.

Notes:
- This is still an API-mode experiment, not HTML scraping.
- Civitai public API behavior can differ between civitai.com and civitai.red.
- If empty search and prompt local search work but nsfw filters do not, use /diagnose_civitai to inspect API behavior.
