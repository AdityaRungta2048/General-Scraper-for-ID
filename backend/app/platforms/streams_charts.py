"""Streams Charts API (official, keyed, optional): finds channels that were renamed.

The platform APIs only know an account's *current* name, so an ID in a sheet that was renamed
looks like "no such account". Streams Charts keeps channels under their earlier names:

  GET /api/v2/channels/{name}?platform=twitch|kick   1 credit per 2xx; a 404 is free

returns the channel's ``channel_id``. The current account is then read from the official
platform API by that id, and only counts as the same channel when the id confirms it (Twitch
user ids; for Kick the id must agree with the picture or name Streams Charts reports).
An unconfirmed rename is never written to the sheet on its own (see resolver.contradictions).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.cache.service import CacheService
from app.logging_setup import get_logger
from app.platforms.base import PlatformAdapter, Profile
from app.platforms.errors import UnexpectedResponseError
from app.platforms.http import PlatformHttpClient

log = get_logger("streams_charts")

SUPPORTED = ("twitch", "kick")


class StreamsChartsRenames:
    def __init__(self, http: PlatformHttpClient, cache: CacheService, time: str = "") -> None:
        self.http = http
        self.cache = cache
        self.time = time

    async def channel(self, platform: str, name: str) -> dict[str, Any] | None:
        """Streams Charts' record for a channel name (current or earlier), None if unknown."""
        cached = self.cache.get("streamscharts", f"{platform}|{name}")
        if cached is not None:
            return cached or None
        params = {"platform": platform, **({"time": self.time} if self.time else {})}
        body = await self.http.get_json(
            f"channels/{name}", params=params, endpoint_category="streamscharts.channels"
        )
        if body is None:
            record: dict[str, Any] = {}  # 404: Streams Charts has never seen this name
        elif isinstance(body, dict) and isinstance(body.get("data"), dict):
            record = body["data"]
        else:
            raise UnexpectedResponseError(
                "Streams Charts /channels returned an unexpected response shape", platform="streamscharts"
            )
        self.cache.set("streamscharts", f"{platform}|{name}", record, 86400, source="streamscharts")
        return record or None

    async def renamed_account(self, adapter: PlatformAdapter, old_name: str) -> Profile | None:
        """The current account of a channel that used to be called ``old_name``, or None.

        Call it only for a name the platform API does not know any more."""
        if adapter.platform not in SUPPORTED or not old_name:
            return None
        record = await self.channel(adapter.platform, old_name)
        if record is None:
            return None
        sc_id = str(record.get("channel_id") or "").strip()
        sc_name = str(record.get("channel_name") or "").strip().lower()
        prof: Profile | None = None
        by_id = False
        if sc_id:
            prof = (await adapter.find_by_ids([sc_id])).get(sc_id)
            by_id = prof is not None
        if prof is None and sc_name and sc_name != old_name:
            prof = await adapter.find_exact_account(sc_name)
        if prof is None or prof.username == old_name:
            log.info("streamscharts_no_current_account", platform=adapter.platform, name=old_name)
            return None
        confirmed = by_id and (adapter.platform == "twitch" or _agrees(record, prof))
        log.info(
            "streamscharts_rename",
            platform=adapter.platform,
            old=old_name,
            new=prof.username,
            confirmed=confirmed,
        )
        return replace(prof, former_names=[old_name], rename_confirmed=confirmed)


def _agrees(record: dict[str, Any], prof: Profile) -> bool:
    """Does the account found by id look like the channel Streams Charts described?"""
    avatar = str(record.get("avatar_url") or "").split("?")[0]
    if avatar and prof.profile_image_url and avatar == prof.profile_image_url.split("?")[0]:
        return True
    names = {str(record.get(k) or "").strip().lower() for k in ("channel_name", "channel_display_name")}
    names.discard("")
    return bool(names & {prof.username, (prof.display_name or "").lower()})
