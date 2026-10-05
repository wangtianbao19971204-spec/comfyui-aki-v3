from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional


FEATURE_API_PATH = "/danbooru_gallery/features"


class FeatureFlagConfigurationError(ValueError):
    """Raised when a rollout configuration is unsafe or internally inconsistent."""


@dataclass(frozen=True)
class V53FeatureFlags:
    # Stable V53 rollout gates. Experimental and legacy shadow paths remain
    # closed until they have their own implementation and delivery evidence.
    v2_routes_enabled: bool = True
    gallery_new_ui_enabled: bool = True
    provider_danbooru_v2: bool = True
    provider_gelbooru_v2: bool = True
    provider_yandere_v2: bool = True
    provider_civitai_v2: bool = True
    legacy_posts_via_v2_danbooru: bool = False
    legacy_posts_via_v2_gelbooru: bool = False
    legacy_posts_via_v2_yandere: bool = False
    legacy_posts_via_v2_civitai: bool = False
    gelbooru_approx_rank_enabled: bool = False
    yandere_html_popular_experimental: bool = False
    civitai_experimental_web: bool = False

    def validate(self) -> "V53FeatureFlags":
        if self.gallery_new_ui_enabled and not self.v2_routes_enabled:
            raise FeatureFlagConfigurationError(
                "gallery_new_ui_enabled requires v2_routes_enabled"
            )
        provider_flags = (
            self.provider_danbooru_v2,
            self.provider_gelbooru_v2,
            self.provider_yandere_v2,
            self.provider_civitai_v2,
        )
        if any(provider_flags) and not self.v2_routes_enabled:
            raise FeatureFlagConfigurationError(
                "provider_*_v2 flags require v2_routes_enabled"
            )
        if self.gelbooru_approx_rank_enabled and not self.provider_gelbooru_v2:
            raise FeatureFlagConfigurationError(
                "gelbooru_approx_rank_enabled requires provider_gelbooru_v2"
            )
        if self.yandere_html_popular_experimental and not self.provider_yandere_v2:
            raise FeatureFlagConfigurationError(
                "yandere_html_popular_experimental requires provider_yandere_v2"
            )
        if self.civitai_experimental_web and not self.provider_civitai_v2:
            raise FeatureFlagConfigurationError(
                "civitai_experimental_web requires provider_civitai_v2"
            )
        legacy_flags = (
            self.legacy_posts_via_v2_danbooru,
            self.legacy_posts_via_v2_gelbooru,
            self.legacy_posts_via_v2_yandere,
            self.legacy_posts_via_v2_civitai,
        )
        if any(legacy_flags):
            raise FeatureFlagConfigurationError(
                "legacy_posts_via_v2_* shadow routing is not implemented in V53"
            )
        return self

    def provider_enabled(self, source: Any) -> bool:
        name = getattr(source, "value", source)
        key = "provider_%s_v2" % str(name or "").strip().lower()
        return bool(getattr(self, key, False))

    def to_dict(self) -> Mapping[str, bool]:
        return asdict(self)


_FLAG_NAMES = tuple(V53FeatureFlags.__dataclass_fields__)


def _merge_flags(base: V53FeatureFlags, values: Optional[Mapping[str, Any]]) -> V53FeatureFlags:
    if values is None:
        return base
    if not isinstance(values, Mapping):
        raise FeatureFlagConfigurationError("feature_flags must be an object")
    unknown = sorted(str(key) for key in values if key not in _FLAG_NAMES)
    if unknown:
        raise FeatureFlagConfigurationError(
            "unknown feature flag(s): %s" % ", ".join(unknown)
        )
    merged: MutableMapping[str, bool] = dict(base.to_dict())
    for key, value in values.items():
        if not isinstance(value, bool):
            raise FeatureFlagConfigurationError("%s must be boolean" % key)
        merged[str(key)] = value
    return V53FeatureFlags(**merged).validate()


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise FeatureFlagConfigurationError("feature flag config does not exist") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FeatureFlagConfigurationError("feature flag config is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise FeatureFlagConfigurationError("feature flag config must be an object")
    return payload


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def load_v53_feature_flags(
    *,
    plugin_root: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> V53FeatureFlags:
    """Load safe defaults, optional user config, then an isolated delivery config.

    The test-config override is deliberately ignored unless the runner sets the
    explicit delivery-test guard, and its path must remain under tests/.runtime.
    This prevents a production process from being redirected to arbitrary JSON.
    """

    env = os.environ if environ is None else environ
    root = (plugin_root or Path(__file__).resolve().parents[3]).resolve()
    flags = V53FeatureFlags()

    production_path = root / "config.json"
    if production_path.is_file():
        production = _load_json_object(production_path)
        configured = production.get("feature_flags")
        if configured is None:
            configured = production.get("gallery_v53_feature_flags")
        flags = _merge_flags(flags, configured)

    test_config = str(env.get("DANBOORU_GALLERY_TEST_CONFIG", "") or "").strip()
    delivery_guard = _is_true(env.get("DANBOORU_GALLERY_DELIVERY_TEST", ""))
    if test_config and delivery_guard:
        test_path = Path(test_config)
        if not test_path.is_absolute():
            raise FeatureFlagConfigurationError("delivery test config path must be absolute")
        resolved = test_path.resolve()
        runtime_root = (root / "tests" / ".runtime").resolve()
        try:
            resolved.relative_to(runtime_root)
        except ValueError as exc:
            raise FeatureFlagConfigurationError(
                "delivery test config must stay under tests/.runtime"
            ) from exc
        payload = _load_json_object(resolved)
        if payload.get("schemaVersion") != 1:
            raise FeatureFlagConfigurationError("unsupported delivery test config schema")
        flags = _merge_flags(flags, payload.get("featureFlags"))

    return flags.validate()


__all__ = [
    "FEATURE_API_PATH",
    "FeatureFlagConfigurationError",
    "V53FeatureFlags",
    "load_v53_feature_flags",
]
