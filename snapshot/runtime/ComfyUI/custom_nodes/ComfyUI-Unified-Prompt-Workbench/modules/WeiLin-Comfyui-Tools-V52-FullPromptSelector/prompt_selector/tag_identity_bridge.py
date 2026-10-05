"""Read-only bridge between legacy WeiLin Tag UUIDs and shared resources."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class TagIdentityBridge:
    """Load audited candidate links without modifying either source database."""

    def __init__(self, candidates_path: str | Path):
        self.path = Path(candidates_path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != "weilin-legacy-tag-link-candidates-v1":
            raise ValueError("候选映射格式不受支持")
        self.summary = dict(payload.get("summary") or {})
        self.links = [dict(link) for link in payload.get("links", [])]
        if any(link.get("status") != "candidate_not_applied" for link in self.links):
            raise ValueError("候选映射状态无效")
        self._tag_index = {}
        self._resource_index = {}
        for link in self.links:
            for row in self._rows(link, "tag_sources"):
                self._tag_index.setdefault(row.get("tag_uuid"), []).append(link)
            for row in self._rows(link, "prompt_targets"):
                self._resource_index.setdefault(row.get("resource_id"), []).append(link)

    @staticmethod
    def _rows(link: Dict[str, Any], key: str) -> Iterable[Dict[str, Any]]:
        return link.get(key) or ()

    def by_tag_uuid(self, tag_uuid: str) -> List[Dict[str, Any]]:
        return list(self._tag_index.get(tag_uuid, ()))

    def by_resource_id(self, resource_id: str) -> List[Dict[str, Any]]:
        return list(self._resource_index.get(resource_id, ()))

    def validate_summary(self) -> Dict[str, Any]:
        """Return deterministic counts and reject duplicate identities."""
        tag_count = sum(len(list(self._rows(link, "tag_sources"))) for link in self.links)
        resource_count = sum(len(list(self._rows(link, "prompt_targets"))) for link in self.links)
        relations = {}
        for link in self.links:
            relations[link.get("relation")] = relations.get(link.get("relation"), 0) + 1
        if any(not key for key in self._tag_index) or any(not key for key in self._resource_index):
            raise ValueError("候选映射缺少稳定身份")
        return {"concepts": len(self.links), "tag_records": tag_count, "shared_records": resource_count, "relations": relations}

    def relation(self, tag_uuid: Optional[str] = None, resource_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if (tag_uuid is None) == (resource_id is None):
            raise ValueError("必须指定一个身份")
        return self.by_tag_uuid(tag_uuid) if tag_uuid is not None else self.by_resource_id(resource_id)

    def lookup(self, *, tag_uuid: Optional[str] = None, resource_id: Optional[str] = None) -> Dict[str, Any]:
        """Return a read-only, JSON-safe identity lookup result."""
        rows = self.relation(tag_uuid=tag_uuid, resource_id=resource_id)
        return {
            "query": {"tag_uuid": tag_uuid, "resource_id": resource_id},
            "matches": rows,
            "count": len(rows),
            "writes_to_sources": False,
            "candidate_only": True,
        }
