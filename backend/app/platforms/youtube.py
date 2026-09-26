"""YouTube Data API v3 adapter (official API, API key).

  GET /channels?forHandle=@h          one handle per call (1 quota unit) — existence + profile
  GET /channels?id=UC…,UC…            up to 50 ids per call (1 unit)
  GET /search?type=channel&q=…        candidate discovery only (100 units — used sparingly)

Default quota is 10,000 units/day per Google Cloud project, so handle probing is capped
(``variant_budget``) and search only runs when exact lookups found nothing plausible.
Lookup keys are a lowercase handle ("mrbeast") or "channel:<UC id>" (ids are case-sensitive).
"""

from __future__ import annotations

import re
import shlex
from typing import Any
from urllib.parse import urlparse

import httpx

from app.cache.service import CacheService
from app.platforms.base import PlatformAdapter, Profile, chunked, dedupe
from app.platforms.errors import UnexpectedResponseError
from app.platforms.http import PlatformHttpClient, download_image

HANDLE_RE = re.compile(r"^[a-z0-9._-]{3,30}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
PARTS = "snippet,brandingSettings,topicDetails"


class YouTubeAdapter(PlatformAdapter):
    platform = "youtube"
    supports_search = True
    expensive_search = True
    variant_budget = 12
    url_hosts = ("youtube.com",)
    url_format = "https://www.youtube.com/@{}"
    NS = "youtube"

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
        self.allowed_image_hosts = allowed_image_hosts or {"yt3.ggpht.com", "yt3.googleusercontent.com"}
        self.image_max_bytes = image_max_bytes

    # ----- handles --------------------------------------------------------------------
    @classmethod
    def normalize_handle(cls, raw: Any) -> str | None:
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        if "/" in text or "youtube.com" in text.lower():
            parsed = urlparse(text if "://" in text else "https://" + text.lstrip("/"))
            host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
            if host != "youtube.com":
                return None
            parts = [p for p in parsed.path.split("/") if p]
            if not parts:
                return None
            if (parts[0] == "channel" and len(parts) > 1) or (parts[0] in {"c", "user"} and len(parts) > 1):
                text = parts[1]
            else:
                text = parts[0]
        if CHANNEL_ID_RE.match(text):
            return "channel:" + text
        text = text.lstrip("@").strip().lower()
        return text if HANDLE_RE.match(text) else None

    @classmethod
    def is_valid_handle(cls, handle: str) -> bool:
        if handle.startswith("channel:"):
            return bool(CHANNEL_ID_RE.match(handle[8:]))
        return bool(HANDLE_RE.match(handle))

    def to_handle(self, variant: str) -> str | None:
        v = variant.strip().lower().lstrip("@").replace(" ", "")
        return v if HANDLE_RE.match(v) else None

    def handle_from_link(self, identity: str, url: str) -> str | None:
        # identities are lowercased; channel ids are case-sensitive, so re-read the original URL
        return self.normalize_handle(url) if "youtube.com" in url else self.to_handle(identity)

    def profile_url(self, handle: str) -> str:
        if handle.startswith("channel:"):
            return f"https://www.youtube.com/channel/{handle[8:]}"
        return self.url_format.format(handle)

    # ----- lookups --------------------------------------------------------------------
    async def find_exact_accounts(self, handles: list[str]) -> dict[str, Profile | None]:
        result: dict[str, Profile | None] = {}
        to_fetch: list[str] = []
        for h in dedupe([h if h.startswith("channel:") else h.lower() for h in handles]):
            if not self.is_valid_handle(h):
                result[h] = None
                continue
            cached = self.cache.get(f"{self.NS}:channel", h)
            if cached is None:
                to_fetch.append(h)
            elif cached.get("_not_found"):
                result[h] = None
            else:
                result[h] = Profile.from_dict(cached)

        fetched: dict[str, Profile] = {}
        ids = [h for h in to_fetch if h.startswith("channel:")]
        for batch in chunked(ids, 50):
            body = await self.http.get_json(
                "channels",
                params={"part": PARTS, "id": ",".join(h[8:] for h in batch), "maxResults": 50},
                endpoint_category="youtube.channels",
            )
            for item in _items(body, "channels"):
                fetched["channel:" + str(item.get("id"))] = self._profile(item)
        for h in to_fetch:
            if h.startswith("channel:"):
                continue
            body = await self.http.get_json(
                "channels",
                params={"part": PARTS, "forHandle": "@" + h},
                endpoint_category="youtube.channels_by_handle",
            )
            items = _items(body, "channels")
            if items:
                fetched[h] = self._profile(items[0])

        for h in to_fetch:
            prof = fetched.get(h)
            result[h] = prof
            if prof is None:
                self.cache.set(
                    f"{self.NS}:channel", h, {"_not_found": True}, self.negative_ttl, source="youtube"
                )
            else:
                self.cache.set(f"{self.NS}:channel", h, prof.to_dict(), self.cache_ttl, source="youtube")
        return result

    def _profile(self, item: dict[str, Any]) -> Profile:
        snippet = item.get("snippet") or {}
        channel_id = str(item.get("id") or "")
        handle = str(snippet.get("customUrl") or "").lstrip("@").lower()
        username = handle if HANDLE_RE.match(handle) else "channel:" + channel_id
        thumbs = snippet.get("thumbnails") or {}
        image = next(
            (thumbs[k]["url"] for k in ("high", "medium", "default") if isinstance(thumbs.get(k), dict)), None
        )
        topics = (item.get("topicDetails") or {}).get("topicCategories") or []
        category = str(topics[-1]).rsplit("/", 1)[-1].replace("_", " ") if topics else None
        keywords = ((item.get("brandingSettings") or {}).get("channel") or {}).get("keywords") or ""
        try:
            tags = shlex.split(keywords)
        except ValueError:
            tags = keywords.split()
        return Profile(
            platform=self.platform,
            username=username,
            user_id=channel_id or None,
            display_name=snippet.get("title") or None,
            description=snippet.get("description") or None,
            profile_image_url=image,
            profile_url=self.profile_url(username),
            category=category,
            tags=tags[:20],
            language=snippet.get("defaultLanguage") or None,
            created_at=snippet.get("publishedAt") or None,
            source="youtube-data-v3",
        )

    async def search_accounts(self, query: str, limit: int = 10) -> list[str]:
        q = query.strip()
        if not q:
            return []
        key = f"{q.lower()}|{limit}"
        cached = self.cache.get(f"{self.NS}:search", key)
        if cached is not None:
            return list(cached)
        body = await self.http.get_json(
            "search",
            params={"part": "snippet", "type": "channel", "q": q, "maxResults": max(1, min(limit, 25))},
            endpoint_category="youtube.search",
        )
        found = dedupe(
            [
                "channel:"
                + str((i.get("snippet") or {}).get("channelId") or (i.get("id") or {}).get("channelId"))
                for i in _items(body, "search")
            ]
        )
        found = [h for h in found if self.is_valid_handle(h)][:limit]
        self.cache.set(f"{self.NS}:search", key, found, self.cache_ttl, source="youtube")
        return found

    async def get_image(self, url: str) -> bytes | None:
        return await download_image(
            self.image_client, url, allowed_hosts=self.allowed_image_hosts, max_bytes=self.image_max_bytes
        )


def _items(body: Any, endpoint: str) -> list[dict[str, Any]]:
    """YouTube omits ``items`` entirely when nothing matched."""
    if body is None or not isinstance(body, dict) or ("kind" not in body and "items" not in body):
        raise UnexpectedResponseError(
            f"YouTube {endpoint} returned an unexpected response shape", platform="youtube"
        )
    items = body.get("items") or []
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
