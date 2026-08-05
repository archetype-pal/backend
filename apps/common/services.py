"""Feature-flag helpers backed by `AppSettings`.

`AppSettings.value` is a plain `TextField` (some rows hold JSON that callers
decode themselves), so a boolean flag is stored as the literal string
`"true"` / `"false"`. Reading that string directly at call sites (`.value ==
"true"`) is error-prone — a stray `"True"`, `"1"`, or typo silently reads as
falsy — so callers should go through `is_feature_enabled` instead of touching
`AppSettings` directly, per the service-layer convention in CONTRIBUTING.md.
"""

from __future__ import annotations

from apps.common.models import AppSettings

_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def is_feature_enabled(key: str, default: bool = False) -> bool:
    """Return whether the feature flag stored at `key` is enabled.

    Falls back to `default` when the key is missing, inactive, or holds a
    value that doesn't parse as a recognizable boolean — a flag lookup should
    never raise and break the caller's request.
    """
    try:
        setting = AppSettings.objects.get(key=key, is_active=True)
    except AppSettings.DoesNotExist:
        return default

    normalized = setting.value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def set_feature_enabled(key: str, enabled: bool, *, description: str | None = None) -> AppSettings:
    """Create or update the flag at `key`, storing it as `"true"` / `"false"`.

    `is_active` is reset to `True` on write so re-enabling a previously
    deactivated flag via this helper doesn't require a separate step.
    """
    defaults: dict[str, object] = {"value": "true" if enabled else "false", "is_active": True}
    if description is not None:
        defaults["description"] = description

    setting, _ = AppSettings.objects.update_or_create(key=key, defaults=defaults)
    return setting
