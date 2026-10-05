"""Pure candidate planner extracted from PromptSelector import_zip semantics."""
from __future__ import annotations

import copy
import hashlib
from collections import Counter


def _variant_id(category_id, prompt, fingerprint):
    source_id = str(prompt.get("_source_id") or prompt.get("id") or "")
    return f"variant:{category_id}:{source_id}:{prompt.get('_source_fingerprint') or fingerprint(prompt)}"


def plan_import(local_data, compatible_data, selected_category_names, fingerprint, known_merged):
    """Return a mutation plan without modifying either input.

    The callback signatures are fingerprint(prompt) -> str and
    known_merged(local_data, category_id, prompt, fingerprint_callback) -> bool.
    """
    result = copy.deepcopy(local_data)
    incoming = copy.deepcopy(compatible_data)
    selected = set(selected_category_names)
    local_categories = {str(cat.get("id")): cat for cat in result.get("categories", []) if cat.get("id")}
    used_ids = {
        str(prompt.get("id"))
        for category in result.get("categories", [])
        for prompt in category.get("prompts", []) or []
        if prompt.get("id")
    }
    used_ids.update(map(str, result.get("_source_to_canonical", {})))
    used_ids.update(str(pid) for event in result.get("_merge_history", []) for pid in event.get("source_ids", []))
    images, actions = set(), []

    for category_index, category in enumerate(incoming.get("categories", [])):
        category_name = category.get("name")
        if category_name not in selected:
            continue
        category_id = str(category.get("id"))
        prompts = category.get("prompts", []) or []
        kept = []
        for prompt_index, prompt in enumerate(prompts):
            if known_merged(local_data, category_id, prompt, fingerprint):
                actions.append(_action(category_index, prompt_index, category, prompt, "suspected_duplicate", "skip_historical"))
            else:
                kept.append((prompt_index, prompt))
        category["prompts"] = [prompt for _, prompt in kept]

        if category_id not in local_categories:
            if any(str(existing.get("name") or "") == str(category_name or "") for existing in result.get("categories", [])):
                category["_source_name"] = category_name
                suffix = hashlib.sha256(category_id.encode("utf-8")).hexdigest()
                category["name"] = f"{category_name} / pending_review/{suffix}"
            for prompt_index, prompt in kept:
                original_id = str(prompt.get("id") or "")
                disposition, action = "new", "create"
                if original_id in used_ids:
                    base = _variant_id(category_id, prompt, fingerprint)
                    prompt["id"] = base
                    occurrence = 2
                    while str(prompt["id"]) in used_ids:
                        prompt["id"] = f"{base}:occurrence:{occurrence}"
                        occurrence += 1
                    disposition, action = "updated", "create_variant"
                used_ids.add(str(prompt.get("id")))
                if prompt.get("image"):
                    images.add(prompt["image"])
                actions.append(_action(category_index, prompt_index, category, prompt, disposition, action, original_id))
            result.setdefault("categories", []).append(category)
            local_categories[category_id] = category
            continue

        local_category = local_categories[category_id]
        local_prompts = {}
        for existing in local_category.get("prompts", []) or []:
            if existing.get("id"):
                local_prompts.setdefault(str(existing["id"]), []).append(existing)
        for prompt_index, prompt in kept:
            original_id = str(prompt.get("id") or "")
            matches = local_prompts.get(original_id, [])
            exact = next((existing for existing in matches if fingerprint(existing) == prompt.get("_source_fingerprint")), None)
            if exact is not None:
                disposition, action, result_id = "suspected_duplicate", "skip_exact", str(exact.get("id"))
            elif matches:
                prompt["id"] = _variant_id(category_id, prompt, fingerprint)
                result_id = str(prompt.get("id"))
                if result_id in used_ids:
                    actions.append(_action(category_index, prompt_index, category, prompt, "suspected_duplicate", "skip_existing_variant", original_id, result_id))
                    continue
                disposition, action = "updated", "create_variant"
                local_category.setdefault("prompts", []).append(prompt)
                local_prompts.setdefault(result_id, []).append(prompt)
                used_ids.add(result_id)
            else:
                legacy_collision = original_id in used_ids
                if legacy_collision:
                    prompt["id"] = _variant_id(category_id, prompt, fingerprint)
                    if str(prompt["id"]) in used_ids:
                        # The deterministic source variant already exists. Its
                        # current body may have been edited locally: preserve it
                        # without appending a second record with the same ID.
                        actions.append(_action(category_index, prompt_index, category, prompt, "suspected_duplicate", "skip_existing_variant", original_id, str(prompt["id"])))
                        continue
                    disposition, action = "updated", "create_variant"
                else:
                    disposition, action = "new", "create"
                result_id = str(prompt.get("id"))
                local_category.setdefault("prompts", []).append(prompt)
                local_prompts.setdefault(result_id, []).append(prompt)
                used_ids.add(result_id)
            if prompt.get("image"):
                images.add(prompt["image"])
            actions.append(_action(category_index, prompt_index, category, prompt, disposition, action, original_id, result_id))

    actions.sort(key=lambda row: (row["category_index"], row["prompt_index"]))
    counts = Counter(action["disposition"] for action in actions)
    counts["total_records"] = len(actions)
    counts["will_write"] = sum(action["action"] in {"create", "create_variant"} for action in actions)
    counts["will_skip"] = len(actions) - counts["will_write"]
    counts["unsupported"] = sum(bool(action["unsupported_issues"]) for action in actions)
    for key in ("new", "updated", "suspected_duplicate", "unsupported"):
        counts.setdefault(key, 0)
    return {"merged_data": result, "images": images, "actions": actions, "counts": dict(counts)}


def _action(category_index, prompt_index, category, prompt, disposition, action, source_id=None, result_id=None):
    quarantine = prompt.get("_import_quarantine") if isinstance(prompt.get("_import_quarantine"), dict) else {}
    return {
        "category_index": category_index,
        "prompt_index": prompt_index,
        "source": f"categories[{category_index}].prompts[{prompt_index}]",
        "source_category_id": str(category.get("id") or ""),
        "source_id": str(prompt.get("_source_id") or source_id or prompt.get("id") or ""),
        "result_id": str(result_id or prompt.get("id") or ""),
        "disposition": disposition,
        "action": action,
        "unsupported_issues": copy.deepcopy(quarantine.get("issues", [])),
    }
