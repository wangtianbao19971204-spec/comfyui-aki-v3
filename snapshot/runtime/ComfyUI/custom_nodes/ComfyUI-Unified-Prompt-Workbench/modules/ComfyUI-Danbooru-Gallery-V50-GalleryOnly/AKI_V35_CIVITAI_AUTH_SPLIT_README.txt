AKI V35 - Civitai 认证分离修复

问题：v34 合并保存 collection Cookie 与 multi-search Authorization 后，collection.getAllUser 可能把 search-new 的 Authorization 一起带到 civitai.red tRPC，导致 401。

修复：
1. civitai.red 的 collection.* / image.getInfinite 只使用 Cookie / x-client 等站内头，不再发送 Authorization / X-Meili-API-Key。
2. search-new.civitai.com/multi-search 只使用 Authorization / X-Meili-API-Key 等搜索授权，不再发送 Cookie。
3. 保留 v34 的合并保存机制。
