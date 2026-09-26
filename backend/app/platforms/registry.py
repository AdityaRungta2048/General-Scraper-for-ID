"""Builds the adapters from settings + the user's saved credentials. Tests inject transports."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app import credentials
from app.cache.service import CacheService
from app.config import Settings
from app.platforms.base import PlatformAdapter
from app.platforms.chzzk import ChzzkAdapter
from app.platforms.http import ClientCredentialsToken, PlatformHttpClient, RetryPolicy, StaticKeyToken
from app.platforms.kick import KickAdapter
from app.platforms.public_sites import BigoAdapter, NimoAdapter, RumbleAdapter, SoopAdapter
from app.platforms.search_engine import BraveSearchEngine, DisabledSearchEngine, SearchEngineProvider
from app.platforms.steam import SteamAdapter
from app.platforms.twitch import TwitchAdapter
from app.platforms.youtube import YouTubeAdapter

USER_AGENT = "Mozilla/5.0 (compatible; StreamerIdentityMatcher/2.0)"


@dataclass
class PlatformBundle:
    adapters: dict[str, PlatformAdapter]
    search_engine: SearchEngineProvider
    clients: list[httpx.AsyncClient]

    def adapter(self, platform: str) -> PlatformAdapter:
        if platform not in self.adapters:
            raise ValueError(f"unknown platform {platform!r}")
        return self.adapters[platform]

    @property
    def twitch(self) -> TwitchAdapter:
        return self.adapters["twitch"]  # type: ignore[return-value]

    @property
    def kick(self) -> KickAdapter:
        return self.adapters["kick"]  # type: ignore[return-value]

    @property
    def youtube(self) -> YouTubeAdapter:
        return self.adapters["youtube"]  # type: ignore[return-value]

    async def aclose(self) -> None:
        for c in self.clients:
            await c.aclose()


def search_engine_configured(settings: Settings) -> bool:
    return settings.search_engine_fallback and credentials.is_configured(settings, "brave")


def build_platforms(
    settings: Settings,
    cache: CacheService,
    transport: httpx.AsyncBaseTransport | None = None,
) -> PlatformBundle:
    timeout = httpx.Timeout(settings.http_timeout)
    common = {"timeout": timeout, "headers": {"User-Agent": USER_AGENT}, "follow_redirects": False}
    if transport is not None:
        common["transport"] = transport
    api_client = httpx.AsyncClient(**common)  # type: ignore[arg-type]
    image_client = httpx.AsyncClient(**{**common, "follow_redirects": True})  # type: ignore[arg-type]
    retry = RetryPolicy(settings.retry_count, settings.retry_base_delay, settings.retry_max_delay)
    image_hosts = {h.strip().lower() for h in settings.image_allowed_hosts.split(",") if h.strip()}
    adapter_kw = {
        "cache_ttl": settings.cache_ttl,
        "negative_ttl": settings.negative_cache_ttl,
        "allowed_image_hosts": image_hosts,
        "image_max_bytes": settings.image_max_bytes,
    }

    def http(platform: str, base_url: str, token: object, rpm: int, **kw: object) -> PlatformHttpClient:
        return PlatformHttpClient(
            platform=platform,
            base_url=base_url,
            client=api_client,
            token=token,  # type: ignore[arg-type]
            concurrency=settings.api_concurrency,
            requests_per_minute=rpm,
            burst=settings.request_burst,
            retry=retry,
            **kw,  # type: ignore[arg-type]
        )

    tw = credentials.get(settings, "twitch")
    twitch_token = ClientCredentialsToken(
        platform="twitch",
        token_url=settings.twitch_token_url,
        client_id=tw["client_id"],
        client_secret=tw["client_secret"],
        client=api_client,
    )
    twitch = TwitchAdapter(
        http(
            "twitch",
            settings.twitch_api_base,
            twitch_token,
            settings.twitch_requests_per_minute,
            auth_headers=lambda t: {"Authorization": f"Bearer {t}", "Client-Id": tw["client_id"]},
        ),
        cache,
        image_client,
        **adapter_kw,  # type: ignore[arg-type]
    )
    kc = credentials.get(settings, "kick")
    kick_token = ClientCredentialsToken(
        platform="kick",
        token_url=settings.kick_token_url,
        client_id=kc["client_id"],
        client_secret=kc["client_secret"],
        client=api_client,
    )
    kick = KickAdapter(
        http("kick", settings.kick_api_base, kick_token, settings.kick_requests_per_minute),
        cache,
        image_client,
        **adapter_kw,  # type: ignore[arg-type]
        public_enrichment=settings.kick_public_profile_enrichment,
        public_site_base=settings.kick_public_site_base,
        public_client=api_client if settings.kick_public_profile_enrichment else None,
    )
    yt_key = credentials.get(settings, "youtube")["api_key"]
    youtube = YouTubeAdapter(
        http(
            "youtube",
            settings.youtube_api_base,
            StaticKeyToken("youtube", yt_key),
            settings.youtube_requests_per_minute,
            auth_headers=lambda k: {"X-goog-api-key": k},
        ),
        cache,
        image_client,
        **adapter_kw,  # type: ignore[arg-type]
    )
    ch = credentials.get(settings, "chzzk")
    chzzk = ChzzkAdapter(
        http(
            "chzzk",
            settings.chzzk_api_base,
            StaticKeyToken("chzzk", ch["client_id"] and ch["client_secret"]),
            settings.chzzk_requests_per_minute,
            auth_headers=lambda _t: {"Client-Id": ch["client_id"], "Client-Secret": ch["client_secret"]},
        ),
        http("chzzk", settings.chzzk_public_base, None, settings.chzzk_requests_per_minute),
        cache,
        image_client,
        **adapter_kw,  # type: ignore[arg-type]
    )
    steam = SteamAdapter(
        http("steam", settings.steam_api_base, None, settings.steam_requests_per_minute),
        credentials.get(settings, "steam")["api_key"],
        cache,
        image_client,
        **adapter_kw,  # type: ignore[arg-type]
    )
    public: dict[str, PlatformAdapter] = {
        cls.platform: cls(
            http(cls.platform, base, None, rpm),
            cache,
            image_client,
            **adapter_kw,  # type: ignore[arg-type]
        )
        for cls, base, rpm in (
            (SoopAdapter, settings.soop_public_base, settings.soop_requests_per_minute),
            (BigoAdapter, settings.bigo_public_base, settings.bigo_requests_per_minute),
            (NimoAdapter, settings.nimo_public_base, settings.nimo_requests_per_minute),
            (RumbleAdapter, settings.rumble_public_base, settings.rumble_requests_per_minute),
        )
    }

    search: SearchEngineProvider = DisabledSearchEngine()
    if search_engine_configured(settings):
        brave_key = credentials.get(settings, "brave")["api_key"]
        search = BraveSearchEngine(
            PlatformHttpClient(
                platform="brave",
                base_url=settings.brave_search_url,
                client=api_client,
                token=StaticKeyToken("brave", brave_key),
                auth_headers=lambda k: {"X-Subscription-Token": k},
                concurrency=1,
                requests_per_minute=settings.search_requests_per_minute,
                burst=settings.request_burst,
                retry=retry,
            ),
            cache,
            settings.cache_ttl,
        )
    return PlatformBundle(
        adapters={
            "twitch": twitch,
            "kick": kick,
            "youtube": youtube,
            "chzzk": chzzk,
            "steam": steam,
            **public,
        },
        search_engine=search,
        clients=[api_client, image_client],
    )
