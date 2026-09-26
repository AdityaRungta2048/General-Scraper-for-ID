"""CHZZK (Naver) adapter.

Official Open API (Client ID + Secret, https://chzzk.gitbook.io/chzzk):
  GET https://openapi.chzzk.naver.com/open/v1/channels?channelIds=…   up to 20 ids
      headers Client-Id / Client-Secret; {"code":200,"content":{"data":[{channelId, channelName,
      channelImageUrl, followerCount, verifiedMark}]}}
The official API has no search and no channel description, so two public, keyless endpoints
of chzzk.naver.com are used as well (best effort, like Kick's optional enrichment):
  GET https://api.chzzk.naver.com/service/v1/search/channels?keyword=…   discovery
  GET https://api.chzzk.naver.com/service/v1/channels/{id}                description (bio links)
CHZZK accounts are identified by a 32-hex channel id; channel names are not unique handles.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.cache.service import CacheService
from app.logging_setup import get_logger
from app.platforms.base import Profile, chunked, dedupe
from app.platforms.errors import PlatformError, TemporaryPlatformError, UnexpectedResponseError
from app.platforms.http import PlatformHttpClient
from app.platforms.simple import SimpleAdapter, public_call

log = get_logger("chzzk")


class ChzzkAdapter(SimpleAdapter):
    platform = "chzzk"
    supports_search = True
    handle_pattern = re.compile(r"^[0-9a-f]{32}$")
    url_hosts = ("chzzk.naver.com",)
    url_format = "https://chzzk.naver.com/{}"
    NS = "chzzk"

    def __init__(
        self,
        http: PlatformHttpClient,
        public_http: PlatformHttpClient,
        cache: CacheService,
        image_client: httpx.AsyncClient,
        **kw: Any,
    ) -> None:
        super().__init__(http, cache, image_client, **kw)
        self.public_http = public_http

    async def find_exact_accounts(self, handles: list[str]) -> dict[str, Profile | None]:
        result: dict[str, Profile | None] = {}
        to_fetch: list[str] = []
        for h in dedupe([h.lower() for h in handles]):
            if not self.is_valid_handle(h):
                result[h] = None
                continue
            cached = self.cache.get(f"{self.NS}:account", h)
            if cached is None:
                to_fetch.append(h)
            else:
                result[h] = None if cached.get("_not_found") else Profile.from_dict(cached)
        fetched: dict[str, Profile] = {}
        for batch in chunked(to_fetch, 20):
            body = await self.http.get_json(
                "open/v1/channels",
                params=[("channelIds", c) for c in batch],
                endpoint_category="chzzk.channels",
            )
            for item in _content(body, "channels").get("data") or []:
                if isinstance(item, dict) and item.get("channelId"):
                    found = self._profile(item)
                    fetched[found.username] = found
        for found in fetched.values():
            await self._describe(found)
        for h in to_fetch:
            prof = fetched.get(h)
            result[h] = prof
            self.cache.set(
                f"{self.NS}:account",
                h,
                prof.to_dict() if prof else {"_not_found": True},
                self.cache_ttl if prof else self.negative_ttl,
                source="chzzk",
            )
        return result

    async def lookup(self, handle: str) -> Profile | None:  # batched above
        return (await self.find_exact_accounts([handle])).get(handle)

    def _profile(self, item: dict[str, Any]) -> Profile:
        cid = str(item["channelId"]).lower()
        return Profile(
            platform=self.platform,
            username=cid,
            user_id=cid,
            display_name=item.get("channelName") or None,
            description=item.get("channelDescription") or None,
            profile_image_url=item.get("channelImageUrl") or None,
            profile_url=self.profile_url(cid),
            source="chzzk-open-api",
        )

    async def _describe(self, prof: Profile) -> None:
        """Public channel page data: the description holds the creator's other links."""
        if prof.description:
            return
        try:
            body = await public_call(
                self.public_http.get_json(
                    f"service/v1/channels/{prof.username}", endpoint_category="chzzk.public"
                ),
                "chzzk",
            )
            prof.description = _content(body, "channel").get("channelDescription") or None
        except TemporaryPlatformError:
            raise
        except PlatformError as exc:
            log.info("chzzk_description_unavailable", channel=prof.username, reason=type(exc).__name__)

    async def search_accounts(self, query: str, limit: int = 10) -> list[str]:
        q = query.strip()
        if not q:
            return []
        key = f"{q.lower()}|{limit}"
        cached = self.cache.get(f"{self.NS}:search", key)
        if cached is not None:
            return list(cached)
        body = await public_call(
            self.public_http.get_json(
                "service/v1/search/channels",
                params={"keyword": q, "offset": 0, "size": max(1, min(limit, 50))},
                endpoint_category="chzzk.search",
            ),
            "chzzk",
        )
        ids = dedupe(
            [
                str((d.get("channel") or {}).get("channelId") or "").lower()
                for d in _content(body, "search").get("data") or []
                if isinstance(d, dict)
            ]
        )
        ids = [i for i in ids if self.is_valid_handle(i)][:limit]
        self.cache.set(f"{self.NS}:search", key, ids, self.cache_ttl, source="chzzk")
        return ids


def _content(body: Any, endpoint: str) -> dict[str, Any]:
    """CHZZK wraps responses as {"code": 200, "message": null, "content": {...}}."""
    if not isinstance(body, dict) or body.get("code") not in (200, None) or "content" not in body:
        raise UnexpectedResponseError(f"CHZZK {endpoint} returned an unexpected response", platform="chzzk")
    content = body.get("content")
    return content if isinstance(content, dict) else {}
