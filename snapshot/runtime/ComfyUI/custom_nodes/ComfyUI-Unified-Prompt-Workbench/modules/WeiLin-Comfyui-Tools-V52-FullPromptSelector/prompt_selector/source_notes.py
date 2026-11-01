"""Read-only original-site annotations, separate from every personal note field."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from .prompt_merge import merged_source

SOURCE_HOSTS = frozenset({"novelai.quicktagcloud.com", "novelai-tag.pages.dev", "prompt-vault-gallery.pages.dev"})
BOOK_NAMES = {
    "suozhang": "所长常规法典", "suozhang_nai5": "所长 NAI5 常规法典",
    "suozhang_r18": "所长成人法典", "suozhang_nai5_r18": "所长 NAI5 成人法典",
    "raven_composition": "渡鸦构图鉴", "enter_codex": "站长的小仓库",
    "artist_nai45_personal": "NAI4.5 画师词典", "artist_nai5_personal": "NAI5 画师词典",
    "nai45_community_pack": "NAI4.5 社区图包", "nai5_community_pack": "NAI5 社区图包",
    "jiegou_yuandian": "解构原典", "mengshen_r18": "梦神法典",
    "qianteng": "千藤的衣柜", "kisegaeningyou": "更衣人偶", "composition_style": "构图风格",
}


def public_source_url(value):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value) or "\\" in value:
        return ""
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.hostname not in SOURCE_HOSTS or url.username or url.password or url.port not in (None, 443):
            return ""
    except ValueError:
        return ""
    return value


def project_source_notes(metadata):
    """Latest appended revision per exact source identity; blank notes remove old ones.

    A primary pointer is a fallback only when that identity has no history. This
    avoids an older primary pointer reviving an explicitly cleared annotation.
    Raw source entries, when present, are authoritative even when note is absent.
    """
    if not isinstance(metadata, dict):
        return []
    prefix = "_" if "_external_sources" in metadata or "_external_source" in metadata else ""
    history = metadata.get(prefix + "external_sources")
    history = history if isinstance(history, list) else []
    latest = {}

    def identity(source):
        if not isinstance(source, dict):
            return None
        values = (source.get("dataset"), source.get("entry_id"))
        return values if all(isinstance(v, str) and v for v in values) else None

    for source in history:
        key = identity(source)
        if key is not None:
            latest[key] = source
    primary = metadata.get(prefix + "external_source")
    key = identity(primary)
    if key is not None and key not in latest:
        latest[key] = primary
    result = []
    for (dataset, entry_id), source in latest.items():
        raw = source.get("raw_entry")
        note = raw.get("note", "") if isinstance(raw, dict) else source.get("note", "")
        if not isinstance(note, str) or not note.strip():
            continue
        title = source.get("dataset_title") or source.get("book_title") or BOOK_NAMES.get(dataset, "原站说明")
        if not isinstance(title, str) or title in (dataset, entry_id):
            title = BOOK_NAMES.get(dataset, "原站说明")
        entry_title = source.get("title") or (raw.get("title") if isinstance(raw, dict) else "") or ""
        if not isinstance(entry_title, str) or entry_title in (dataset, entry_id):
            entry_title = ""
        result.append({"title": title, "entry_title": entry_title, "note": note,
                       "url": public_source_url(source.get("url"))})
    return result


def read_source_notes(resource_id, prompt_loader, tags_path):
    """Read the native effective resource, or a raw Tag UUID, without writes."""
    if not isinstance(resource_id, str) or not resource_id.strip():
        raise ValueError("缺少资料身份")
    resource_id = resource_id.strip()
    if resource_id.startswith("tag:"):
        tag_id = resource_id[4:]
        if not tag_id:
            raise ValueError("Tag 身份无效")
        uri = Path(tags_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT m.data FROM tag_tags t LEFT JOIN workbench_tag_meta m ON m.tag_uuid=t.t_uuid WHERE t.t_uuid=?", (tag_id,)).fetchone()
            if row is None:
                raise KeyError("Tag 已不存在")
            metadata = json.loads(row[0] or "{}")
            revision = conn.execute("SELECT value FROM workbench_tag_revision WHERE id=1").fetchone()
            return {"source_notes": project_source_notes(metadata),
                    "revision": "tags-v1:" + str(revision[0]) if revision else ""}
    document = prompt_loader()
    resolved = merged_source(document, resource_id)
    if resolved is None:
        resolved = next(((category, prompt) for category in document.get("categories", [])
                         for prompt in category.get("prompts", []) if str(prompt.get("id") or "") == resource_id), None)
    if resolved is None:
        raise KeyError("资料已不存在")
    return {"source_notes": project_source_notes(resolved[1]), "revision": str(document.get("last_modified") or "")}
