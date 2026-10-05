"""Shared exact LoRA identity resolution for node and UI trigger-word readers."""
import os


class AmbiguousLoraTriggerWordError(ValueError):
    def __init__(self, choices):
        self.choices = choices
        super().__init__("LoRA name is ambiguous; choose an exact resource path")


def normalize(value):
    return str(value or "").replace("\\", "/").strip().rstrip("/").casefold()


def stem(value):
    for extension in (".safetensors", ".ckpt", ".pt", ".bin", ".pth"):
        if value.endswith(extension):
            return value[:-len(extension)]
    return value


def resolve_lora_record(name, rows):
    requested = normalize(name)
    if not requested:
        return None
    path_like = "/" in requested or ":" in requested
    matches = []
    for item in rows:
        filename = normalize(item.get("file_name"))
        folder = normalize(item.get("folder"))
        path = normalize(item.get("file_path"))
        relative = "/".join(part for part in (folder, filename) if part)
        relative_with_extension = "/".join(part for part in (folder, path.rsplit("/", 1)[-1]) if part)
        identities = {path, relative, relative_with_extension} - {""}
        candidates = identities if path_like else {filename.rsplit("/", 1)[-1], path.rsplit("/", 1)[-1]}
        if requested in candidates or (stem(requested) == requested and requested in {stem(value) for value in candidates}):
            matches.append(item)
    # A folder-relative name can also be ambiguous across multiple model roots.
    if len(matches) > 1:
        raise AmbiguousLoraTriggerWordError(sorted({normalize(item.get("file_path")) for item in matches}))
    return matches[0] if matches else None


def resolve_lora_syntax_identity(name, rows, syntax_format="full"):
    """Return an unambiguous loadable name without relying on a display label."""
    if syntax_format not in {"full", "legacy"}:
        raise ValueError("Unknown LoRA syntax format")
    item = resolve_lora_record(name, rows)
    if item is None or not os.path.isfile(item.get("file_path", "")):
        raise FileNotFoundError("LoRA resource is missing; refresh the model list")
    path = item["file_path"].replace("\\", "/")
    filename = path.rsplit("/", 1)[-1]
    for extension in (".safetensors", ".ckpt", ".pt", ".bin", ".pth"):
        if filename.casefold().endswith(extension):
            filename = filename[:-len(extension)]
            break
    folder = str(item.get("folder") or "").replace("\\", "/").strip("/")
    relative = "/".join(part for part in (folder, filename) if part)
    syntax_name = filename if syntax_format == "legacy" else relative
    if not syntax_name or any(character in syntax_name for character in ":<>\r\n"):
        raise ValueError("LoRA path cannot be represented by the loader syntax")
    # Also reject a relative path shared by two separately configured roots.
    resolved = resolve_lora_record(syntax_name, rows)
    if resolved is None or normalize(resolved.get("file_path")) != normalize(path):
        raise ValueError("LoRA identity changed; refresh the model list")
    return {"name": syntax_name, "relative_name": relative, "file_path": path,
            "syntax_format": syntax_format}


async def read_trigger_words(item):
    if item is None:
        return []
    civitai = item.get("civitai")
    if not isinstance(civitai, dict) or "trainedWords" not in civitai:
        from .metadata_manager import MetadataManager
        from .models import LoraMetadata
        metadata, should_skip = await MetadataManager.load_metadata(item["file_path"], LoraMetadata)
        civitai = metadata.civitai if metadata is not None and not should_skip else {}
    words = civitai.get("trainedWords", []) if isinstance(civitai, dict) else []
    return list(words) if isinstance(words, list) else []
