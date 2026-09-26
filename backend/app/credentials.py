"""API credentials each user enters on the setup screen (their own keys, not the author's).

Stored in ``DATA_DIR/credentials.json`` (the API and the worker share DATA_DIR), with the
matching environment variables as a fallback for server deployments. Secret values are
never returned to the browser and never logged.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app.config import Settings
from app.platforms.catalog import PLATFORMS

# credential id -> required fields ("brave" = optional search-engine fallback).
# Platforms without an official API have no fields: they are simply switched on (KEYLESS).
FIELDS: dict[str, tuple[str, ...]] = {
    **{p: info.credential_fields for p, info in PLATFORMS.items()},
    "brave": ("api_key",),
}
KEYLESS = {p for p, info in PLATFORMS.items() if info.keyless}
_ENV_ATTR = {("brave", "api_key"): "brave_search_api_key"}


def _path(settings: Settings) -> Any:
    return settings.data_dir / "credentials.json"


def _stored(settings: Settings) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _env(settings: Settings, cred: str, field: str) -> str:
    value = getattr(settings, _ENV_ATTR.get((cred, field), f"{cred}_{field}"), "")
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value or "")


def get(settings: Settings, cred: str) -> dict[str, str]:
    """Effective values: saved on the setup screen, else from the environment."""
    saved = _stored(settings).get(cred) or {}
    return {f: str(saved.get(f) or "") or _env(settings, cred, f) for f in FIELDS[cred]}


def _enabled_by_env(settings: Settings, cred: str) -> bool:
    return cred in {p.strip() for p in settings.public_lookup_platforms.split(",")}


def is_configured(settings: Settings, cred: str) -> bool:
    if cred in KEYLESS:
        return (_stored(settings).get(cred) or {}).get("enabled") == "1" or _enabled_by_env(settings, cred)
    return all(get(settings, cred).values())


def source(settings: Settings, cred: str) -> str | None:
    if cred in KEYLESS:
        if (_stored(settings).get(cred) or {}).get("enabled") == "1":
            return "setup"
        return "environment" if _enabled_by_env(settings, cred) else None
    if all((_stored(settings).get(cred) or {}).get(f) for f in FIELDS[cred]):
        return "setup"
    return "environment" if all(_env(settings, cred, f) for f in FIELDS[cred]) else None


def save(settings: Settings, cred: str, values: dict[str, str]) -> None:
    data = _stored(settings)
    data[cred] = {"enabled": "1"} if cred in KEYLESS else {f: values[f].strip() for f in FIELDS[cred]}
    _write(settings, data)


def clear(settings: Settings, cred: str) -> None:
    data = _stored(settings)
    if data.pop(cred, None) is not None:
        _write(settings, data)


def _write(settings: Settings, data: dict[str, Any]) -> None:
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".credentials", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
