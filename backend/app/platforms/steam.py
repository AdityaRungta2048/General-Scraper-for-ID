"""Steam (SteamTV broadcasts belong to Steam community profiles) — official Steam Web API.

  GET https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key=…&vanityurl=…
      {"response": {"success": 1, "steamid": "7656…"}}  (success 42 = no match)
  GET https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key=…&steamids=a,b  (≤100)
      {"response": {"players": [{steamid, personaname, profileurl, avatarfull, loccountrycode}]}}
Lookup keys: a custom-URL name ("gaben") or a 64-bit SteamID. No search, no bio in the API.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.cache.service import CacheService
from app.platforms.base import Profile, chunked, dedupe
from app.platforms.errors import ConfigurationError, UnexpectedResponseError
from app.platforms.http import PlatformHttpClient
from app.platforms.simple import SimpleAdapter

STEAMID = re.compile(r"^7656\d{13}$")


class SteamAdapter(SimpleAdapter):
    platform = "steam"
    variant_budget = 12
    handle_pattern = re.compile(r"^[a-z0-9_-]{2,32}$|^7656\d{13}$")
    url_hosts = ("steamcommunity.com",)
    url_format = "https://steamcommunity.com/id/{}"
    NS = "steam"

    def __init__(
        self,
        http: PlatformHttpClient,
        api_key: str,
        cache: CacheService,
        image_client: httpx.AsyncClient,
        **kw: Any,
    ) -> None:
        super().__init__(http, cache, image_client, **kw)
        self.api_key = api_key

    def profile_url(self, handle: str) -> str:
        return (
            f"https://steamcommunity.com/profiles/{handle}"
            if STEAMID.match(handle)
            else self.url_format.format(handle)
        )

    def _key(self) -> str:
        if not self.api_key:
            raise ConfigurationError(
                "steam API key is not configured (add it on the API keys screen)", platform="steam"
            )
        return self.api_key

    async def find_exact_accounts(self, handles: list[str]) -> dict[str, Profile | None]:
        result: dict[str, Profile | None] = {}
        steamids: dict[str, str] = {}  # handle -> steamid
        for h in dedupe([h.lower() for h in handles]):
            if not self.is_valid_handle(h):
                result[h] = None
                continue
            cached = self.cache.get(f"{self.NS}:account", h)
            if cached is not None:
                result[h] = None if cached.get("_not_found") else Profile.from_dict(cached)
            elif STEAMID.match(h):
                steamids[h] = h
            else:
                body = await self.http.get_json(
                    "ISteamUser/ResolveVanityURL/v1/",
                    params={"key": self._key(), "vanityurl": h},
                    endpoint_category="steam.resolve_vanity",
                )
                resp = _response(body)
                if resp.get("success") == 1 and STEAMID.match(str(resp.get("steamid") or "")):
                    steamids[h] = str(resp["steamid"])
                else:
                    self._remember(h, None)
                    result[h] = None
        players: dict[str, Profile] = {}
        for batch in chunked(dedupe(list(steamids.values())), 100):
            body = await self.http.get_json(
                "ISteamUser/GetPlayerSummaries/v2/",
                params={"key": self._key(), "steamids": ",".join(batch)},
                endpoint_category="steam.player_summaries",
            )
            for p in _response(body).get("players") or []:
                if isinstance(p, dict) and p.get("steamid"):
                    players[str(p["steamid"])] = self._profile(p)
        for h, sid in steamids.items():
            prof = players.get(sid)
            self._remember(h, prof)
            result[h] = prof
        return result

    async def lookup(self, handle: str) -> Profile | None:  # batched above
        return (await self.find_exact_accounts([handle])).get(handle)

    def _remember(self, handle: str, prof: Profile | None) -> None:
        self.cache.set(
            f"{self.NS}:account",
            handle,
            prof.to_dict() if prof else {"_not_found": True},
            self.cache_ttl if prof else self.negative_ttl,
            source="steam",
        )

    def _profile(self, p: dict[str, Any]) -> Profile:
        sid = str(p["steamid"])
        url = str(p.get("profileurl") or "")
        m = re.search(r"steamcommunity\.com/id/([^/]+)", url)
        username = m.group(1).lower() if m else sid
        return Profile(
            platform=self.platform,
            username=username,
            user_id=sid,
            display_name=p.get("personaname") or None,
            profile_image_url=p.get("avatarfull") or None,
            profile_url=url or self.profile_url(sid),
            source="steam-web-api",
        )


def _response(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or not isinstance(body.get("response"), dict):
        raise UnexpectedResponseError("Steam Web API returned an unexpected response", platform="steam")
    return body["response"]
