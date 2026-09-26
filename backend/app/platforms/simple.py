"""Shared base for adapters that look accounts up one handle at a time (with caching), and
helpers for the platforms that have no public lookup API (public pages / public JSON).

Public-page adapters never try to get around bot protection: a block (401/403) or an
unexpected page shape becomes a retryable row error, never "not found" or "no match".
"""

from __future__ import annotations

import html
import json
import re
from abc import abstractmethod
from typing import Any

import httpx

from app.cache.service import CacheService
from app.logging_setup import get_logger
from app.platforms.base import PlatformAdapter, Profile, dedupe
from app.platforms.errors import AuthenticationError, UnexpectedResponseError
from app.platforms.http import PlatformHttpClient, download_image

log = get_logger("simple_adapter")


class SimpleAdapter(PlatformAdapter):
    NS = ""

    def __init__(
        self,
        http: PlatformHttpClient,
        cache: CacheService,
        image_client: httpx.AsyncClient,
        *,
        cache_ttl: int = 86400,
        negative_ttl: int = 21600,
        allowed_image_hosts: set[str] | None = None,
        image_max_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.http = http
        self.cache = cache
        self.image_client = image_client
        self.cache_ttl = cache_ttl
        self.negative_ttl = negative_ttl
        self.allowed_image_hosts = allowed_image_hosts or set()
        self.image_max_bytes = image_max_bytes

    @classmethod
    def normalize_handle(cls, raw: Any) -> str | None:
        """Cell value / URL / @handle -> lookup key (URLs parsed like links found in bios)."""
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        if "/" in text or any(h in text.lower() for h in cls.url_hosts):
            from app.matching.social import normalize_social_url  # local: avoids an import cycle

            ident = normalize_social_url(text)
            if ident is None or ident.kind != cls.platform:
                return None
            text = ident.identity
        text = text.lstrip("@").strip().lower()
        return text if cls.is_valid_handle(text) else None

    async def find_exact_accounts(self, handles: list[str]) -> dict[str, Profile | None]:
        result: dict[str, Profile | None] = {}
        for h in dedupe([h.lower() for h in handles]):
            if not self.is_valid_handle(h):
                result[h] = None
                continue
            cached = self.cache.get(f"{self.NS}:account", h)
            if cached is not None:
                result[h] = None if cached.get("_not_found") else Profile.from_dict(cached)
                continue
            prof = await self.lookup(h)
            result[h] = prof
            self.cache.set(
                f"{self.NS}:account",
                h,
                prof.to_dict() if prof else {"_not_found": True},
                self.cache_ttl if prof else self.negative_ttl,
                source=self.platform,
            )
        return result

    @abstractmethod
    async def lookup(self, handle: str) -> Profile | None:
        """One account by handle; None = the platform says it doesn't exist."""

    async def get_image(self, url: str) -> bytes | None:
        return await download_image(
            self.image_client, url, allowed_hosts=self.allowed_image_hosts, max_bytes=self.image_max_bytes
        )


async def public_call(coro: Any, platform: str) -> Any:
    """A 401/403 from a public (keyless) endpoint means "blocked right now", not a bad API key:
    report it as a retryable row error instead of failing the whole job."""
    try:
        return await coro
    except AuthenticationError as exc:
        raise UnexpectedResponseError(
            f"{platform} refused the public lookup (HTTP {exc.status_code}); try again later",
            platform=platform,
        ) from exc


_META = re.compile(
    r"<meta\s+[^>]*?(?:property|name)\s*=\s*[\"'](?P<k>[^\"']+)[\"'][^>]*?content\s*=\s*[\"'](?P<v>[^\"']*)[\"']"
    r"|<meta\s+[^>]*?content\s*=\s*[\"'](?P<v2>[^\"']*)[\"'][^>]*?(?:property|name)\s*=\s*[\"'](?P<k2>[^\"']+)[\"']",
    re.IGNORECASE,
)


def meta_tags(page: str) -> dict[str, str]:
    """<meta property/name=... content=...> values (first occurrence wins), HTML-unescaped."""
    out: dict[str, str] = {}
    for m in _META.finditer(page):
        key = (m.group("k") or m.group("k2") or "").lower()
        value = m.group("v") if m.group("k") else m.group("v2")
        if key and key not in out:
            out[key] = html.unescape(value or "").strip()
    return out


def js_object(page: str, name: str) -> dict[str, Any] | None:
    """Parse ``var NAME = {...};`` / ``NAME = {...}`` embedded in a page (balanced braces)."""
    m = re.search(rf"\b{re.escape(name)}\s*=\s*\{{", page)
    if not m:
        return None
    start = m.end() - 1
    depth, i, in_str, esc = 0, start, "", False
    while i < len(page):
        ch = page[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = ""
        elif ch in "\"'":
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(page[start : i + 1])
                except ValueError:
                    return None
                return value if isinstance(value, dict) else None
        i += 1
    return None


def https_url(url: Any) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    return url if url.startswith("https://") else None
