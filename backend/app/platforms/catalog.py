"""The supported platforms. Adding a platform = one adapter module + one entry here."""

from __future__ import annotations

from dataclasses import dataclass

from app.platforms.base import PlatformAdapter
from app.platforms.chzzk import ChzzkAdapter
from app.platforms.kick import KickAdapter
from app.platforms.public_sites import BigoAdapter, NimoAdapter, RumbleAdapter, SoopAdapter
from app.platforms.steam import SteamAdapter
from app.platforms.twitch import TwitchAdapter
from app.platforms.youtube import YouTubeAdapter


@dataclass(frozen=True)
class PlatformInfo:
    id: str
    label: str
    adapter: type[PlatformAdapter]
    credential_fields: tuple[str, ...]  # empty = no official API: opt-in public lookup

    @property
    def keyless(self) -> bool:
        return not self.credential_fields


PLATFORMS: dict[str, PlatformInfo] = {
    p.id: p
    for p in (
        PlatformInfo("twitch", "Twitch", TwitchAdapter, ("client_id", "client_secret")),
        PlatformInfo("kick", "Kick", KickAdapter, ("client_id", "client_secret")),
        PlatformInfo("youtube", "YouTube", YouTubeAdapter, ("api_key",)),
        PlatformInfo("chzzk", "CHZZK", ChzzkAdapter, ("client_id", "client_secret")),
        PlatformInfo("soop", "SOOP", SoopAdapter, ()),
        PlatformInfo("steam", "Steam", SteamAdapter, ("api_key",)),
        PlatformInfo("bigo", "Bigo LIVE", BigoAdapter, ()),
        PlatformInfo("nimo", "Nimo TV", NimoAdapter, ()),
        PlatformInfo("rumble", "Rumble", RumbleAdapter, ()),
    )
}


def label(platform: str | None) -> str:
    info = PLATFORMS.get(platform or "")
    return info.label if info else (platform or "")
