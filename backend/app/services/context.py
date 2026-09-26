"""Wires adapters + matching engine together for one processing run."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.cache.service import CacheService
from app.config import Settings
from app.credentials import KEYLESS
from app.logging_setup import get_logger
from app.matching.candidates import CandidateGenerator
from app.matching.config import ScoringConfig
from app.matching.image import ProfileImageMatcher
from app.matching.text import SentenceTransformerEmbedder, TextEmbedder
from app.matching.verifier import IdentityVerifier
from app.platforms.http import ClientCredentialsToken, PlatformHttpClient, RetryPolicy, StaticKeyToken
from app.platforms.registry import PlatformBundle, build_platforms
from app.services.resolver import IdentityResolver
from app.services.stores import DbImageFeatureStore, ProfileStore

log = get_logger("context")


# Test hook: integration tests route all platform HTTP through a fake transport.
_default_transport: httpx.AsyncBaseTransport | None = None


def set_default_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _default_transport
    _default_transport = transport


@dataclass
class MatchingContext:
    resolver: IdentityResolver
    platforms: PlatformBundle
    cache: CacheService

    async def aclose(self) -> None:
        await self.platforms.aclose()


def build_context(
    settings: Settings,
    session_factory: sessionmaker[Session],
    transport: httpx.AsyncBaseTransport | None = None,
) -> MatchingContext:
    cache = CacheService(session_factory)
    platforms = build_platforms(settings, cache, transport=transport or _default_transport)
    config = ScoringConfig.from_settings(settings)
    profile_store = ProfileStore(session_factory)
    embedder: TextEmbedder | None = None
    if settings.bio_embeddings_enabled:
        try:
            embedder = SentenceTransformerEmbedder(settings.bio_embedding_model)
        except Exception as exc:
            log.warning("bio_embeddings_unavailable", error=type(exc).__name__)
    verifier = IdentityVerifier(
        config,
        image_matcher=ProfileImageMatcher(
            config, DbImageFeatureStore(session_factory, settings.image_cache_ttl)
        ),
        social_frequency=profile_store.social_frequency,
        text_embedder=embedder,
        image_max_candidates=settings.image_max_candidates,
    )
    generator = CandidateGenerator(
        settings.max_candidates, settings.search_results_per_query, platforms.search_engine
    )
    resolver = IdentityResolver(
        platforms.adapters,
        generator,
        verifier,
        cache,
        profile_store,
        settings.resolution_cache_ttl,
    )
    return MatchingContext(resolver=resolver, platforms=platforms, cache=cache)


async def check_credentials(settings: Settings, cred: str, values: dict[str, str]) -> None:
    """Make one cheap authenticated call so a wrong key is reported on the setup screen,
    not halfway through a job. Raises AuthenticationError / PlatformError."""
    retry = RetryPolicy(retries=1, base_delay=0.5)
    kw = {"timeout": httpx.Timeout(settings.http_timeout)}
    if _default_transport is not None:
        kw["transport"] = _default_transport  # type: ignore[assignment]
    async with httpx.AsyncClient(**kw) as client:  # type: ignore[arg-type]
        if cred in ("twitch", "kick"):
            await ClientCredentialsToken(
                platform=cred,
                token_url=settings.twitch_token_url if cred == "twitch" else settings.kick_token_url,
                client_id=values["client_id"],
                client_secret=values["client_secret"],
                client=client,
            ).get()
            return
        if cred == "youtube":
            http = PlatformHttpClient(
                platform="youtube",
                base_url=settings.youtube_api_base,
                client=client,
                token=StaticKeyToken("youtube", values["api_key"]),
                auth_headers=lambda k: {"X-goog-api-key": k},
                retry=retry,
            )
            # 1 quota unit: the "Google for Developers" channel
            await http.get_json("channels", params={"part": "id", "id": "UC_x5XG1OV2P6uZZ5FSM9Ttw"})
            return
        if cred == "chzzk":
            http = PlatformHttpClient(
                platform="chzzk",
                base_url=settings.chzzk_api_base,
                client=client,
                token=StaticKeyToken("chzzk", values["client_id"]),
                auth_headers=lambda _t: {
                    "Client-Id": values["client_id"],
                    "Client-Secret": values["client_secret"],
                },
                retry=retry,
            )
            await http.get_json("open/v1/channels", params={"channelIds": "0" * 32})
            return
        if cred == "steam":
            http = PlatformHttpClient(
                platform="steam", base_url=settings.steam_api_base, client=client, token=None, retry=retry
            )
            await http.get_json(
                "ISteamUser/GetPlayerSummaries/v2/",
                params={"key": values["api_key"], "steamids": "76561197960287930"},
            )
            return
        if cred in KEYLESS:
            return  # nothing to check: public pages, no key
        if cred == "brave":
            http = PlatformHttpClient(
                platform="brave",
                base_url=settings.brave_search_url,
                client=client,
                token=StaticKeyToken("brave", values["api_key"]),
                auth_headers=lambda k: {"X-Subscription-Token": k},
                retry=retry,
            )
            await http.get_json("", params={"q": "twitch", "count": 1})
            return
    raise ValueError(f"unknown credential {cred!r}")
