"""Test doubles: a stateful fake of the Twitch Helix + Kick Public APIs + image CDNs.

It plugs in at the httpx transport layer, so the real adapters, token handling,
retry/rate-limit logic and caching are all exercised. Used ONLY by tests.
"""

from __future__ import annotations

import io
import json
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from PIL import Image, ImageDraw
from rapidfuzz import fuzz

TWITCH_LOGIN_RULE = re.compile(r"^[a-z0-9][a-z0-9_]{3,24}$")
TWITCH_IMG = "https://static-cdn.jtvnw.net/jtv_user_pictures/{}-profile_image-300x300.png"
TWITCH_DEFAULT_IMG = "https://static-cdn.jtvnw.net/user-default-pictures-uv/{}-profile_image-300x300.png"
KICK_IMG = "https://files.kick.com/images/user/{}/profile_image/conversion/{}-fullsize.webp"


# ---------------------------------------------------------------- image helpers
def distinctive_image(seed: int, size: int = 300) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (size, size), tuple(rnd.randint(0, 255) for _ in range(3)))
    d = ImageDraw.Draw(img)
    for _ in range(14):
        x0, y0 = rnd.randint(0, size), rnd.randint(0, size)
        x1, y1 = x0 + rnd.randint(20, 160), y0 + rnd.randint(20, 160)
        color = tuple(rnd.randint(0, 255) for _ in range(3))
        if rnd.random() < 0.5:
            d.ellipse([x0, y0, x1, y1], fill=color)
        else:
            d.rectangle([x0, y0, x1, y1], fill=color)
    for _ in range(6):
        pts = [(rnd.randint(0, size), rnd.randint(0, size)) for _ in range(3)]
        d.polygon(pts, fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return img


def generic_image(color: tuple[int, int, int] = (145, 70, 255)) -> Image.Image:
    img = Image.new("RGB", (300, 300), color)
    ImageDraw.Draw(img).ellipse([100, 100, 200, 200], fill=(255, 255, 255))
    return img


def to_bytes(img: Image.Image, fmt: str = "PNG", quality: int = 90) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=quality)
    else:
        img.save(buf, fmt)
    return buf.getvalue()


def platform_variant(img: Image.Image) -> bytes:
    """What another platform does to the same upload: resize, border, recompress."""
    small = img.resize((150, 150), Image.LANCZOS)
    bordered = Image.new("RGB", (170, 170), (255, 255, 255))
    bordered.paste(small, (10, 10))
    return to_bytes(bordered, "JPEG", quality=70)


# ---------------------------------------------------------------- fake world
@dataclass
class FailureRule:
    predicate: Callable[[httpx.Request], bool]
    status: int | None = None  # HTTP status to return
    exc: type[Exception] | None = None  # exception to raise instead
    times: int = 10**9
    headers: dict[str, str] = field(default_factory=dict)


class FakePlatforms:
    def __init__(self) -> None:
        self.twitch: dict[str, dict[str, Any]] = {}
        self.kick: dict[str, dict[str, Any]] = {}
        self.youtube: dict[str, dict[str, Any]] = {}  # channel id -> channel resource
        self.youtube_keys: set[str] | None = {"test-yt-key"}  # None = any key except "wrong" (demo)
        # the six newer platforms: platform -> handle -> record
        self.extra: dict[str, dict[str, dict[str, Any]]] = {
            p: {} for p in ("chzzk", "steam", "soop", "bigo", "nimo", "rumble")
        }
        self.keys_checked = True  # False = accept any chzzk/steam key except "wrong" (demo)
        self.images: dict[str, bytes] = {}
        self.brave: dict[str, list[str]] = {}
        self.failures: list[FailureRule] = []
        self.calls: Counter[str] = Counter()
        self.requests: list[httpx.Request] = []
        self._next_id = 1000

    # ---- world building -------------------------------------------------------
    def add_twitch(
        self,
        login: str,
        display_name: str | None = None,
        *,
        description: str = "",
        image: bytes | None = None,
        default_avatar: bool = False,
        game: str = "",
        title: str = "",
        tags: list[str] | None = None,
        language: str = "",
    ) -> str:
        self._next_id += 1
        uid = str(self._next_id)
        url = (TWITCH_DEFAULT_IMG if default_avatar or image is None else TWITCH_IMG).format(uid)
        if image is not None and not default_avatar:
            self.images[url] = image
        self.twitch[login.lower()] = {
            "id": uid,
            "login": login.lower(),
            "display_name": display_name or login,
            "type": "",
            "broadcaster_type": "",
            "description": description,
            "profile_image_url": url,
            "offline_image_url": "",
            "view_count": 0,
            "created_at": "2020-01-01T00:00:00Z",
            "_channel": {
                "broadcaster_id": uid,
                "broadcaster_login": login.lower(),
                "broadcaster_name": display_name or login,
                "broadcaster_language": language,
                "game_id": "1",
                "game_name": game,
                "title": title,
                "delay": 0,
                "tags": tags or [],
                "content_classification_labels": [],
                "is_branded_content": False,
            },
        }
        return uid

    def add_kick(
        self,
        slug: str,
        name: str | None = None,
        *,
        description: str = "",
        image: bytes | None = None,
        category: str = "",
        title: str = "",
        tags: list[str] | None = None,
        language: str = "",
    ) -> str:
        self._next_id += 1
        uid = str(self._next_id)
        url = KICK_IMG.format(uid, uid) if image is not None else ""
        if image is not None:
            self.images[url] = image
        self.kick[slug.lower()] = {
            "broadcaster_user_id": int(uid),
            "slug": slug.lower(),
            "channel_description": description,
            "banner_picture": "",
            "stream_title": title,
            "category": {"id": 1, "name": category, "thumbnail": ""} if category else None,
            "stream": {
                "is_live": False,
                "is_mature": False,
                "language": language,
                "custom_tags": tags or [],
                "start_time": "0001-01-01T00:00:00Z",
                "thumbnail": "",
                "viewer_count": 0,
            },
            "_user": {"user_id": int(uid), "name": name or slug, "profile_picture": url},
        }
        return uid

    def add_youtube(
        self,
        handle: str,
        title: str | None = None,
        *,
        description: str = "",
        image: bytes | None = None,
        topic: str = "",
        keywords: str = "",
        language: str = "",
        channel_id: str | None = None,
    ) -> str:
        self._next_id += 1
        cid = channel_id or f"UC{self._next_id:022d}"
        url = f"https://yt3.ggpht.com/{cid}=s800" if image is not None else ""
        if image is not None:
            self.images[url] = image
        self.youtube[cid] = {
            "kind": "youtube#channel",
            "id": cid,
            "snippet": {
                "title": title or handle,
                "description": description,
                "customUrl": "@" + handle.lower(),
                "publishedAt": "2019-01-01T00:00:00Z",
                "thumbnails": {"high": {"url": url}} if url else {},
                **({"defaultLanguage": language} if language else {}),
            },
            "brandingSettings": {"channel": {"keywords": keywords}},
            "topicDetails": {
                "topicCategories": [f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}"]
                if topic
                else []
            },
        }
        return cid

    def add_extra(
        self,
        platform: str,
        handle: str,
        name: str | None = None,
        *,
        bio: str = "",
        image: bytes | None = None,
    ) -> str:
        """An account on CHZZK / Steam / SOOP / Bigo / Nimo / Rumble. Returns its id."""
        self._next_id += 1
        uid = (
            f"{self._next_id:032x}"
            if platform == "chzzk"
            else str(76561190000000000 + self._next_id)
            if platform == "steam"
            else str(self._next_id)
        )
        host = {
            "chzzk": "https://nng-phinf.pstatic.net/{}.png",
            "steam": "https://avatars.steamstatic.com/{}_full.jpg",
            "soop": "https://stimg.sooplive.co.kr/LOGO/{}.jpg",
            "bigo": "https://esx.bigo.sg/{}.jpg",
            "nimo": "https://img.nimo.tv/{}.png",
            "rumble": "https://sp.rmbl.ws/{}.jpg",
        }[platform]
        url = host.format(uid) if image is not None else ""
        if image is not None:
            self.images[url] = image
        key = uid if platform == "chzzk" else handle.lower()
        self.extra[platform][key] = {
            "id": uid,
            "handle": handle.lower(),
            "name": name or handle,
            "bio": bio,
            "image": url,
        }
        return uid

    def fail(
        self,
        predicate: Callable[[httpx.Request], bool],
        *,
        status: int | None = None,
        exc: type[Exception] | None = None,
        times: int = 10**9,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.failures.append(FailureRule(predicate, status, exc, times, headers or {}))

    # ---- transport ---------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = urlparse(str(request.url))
        key = f"{url.hostname}{url.path}"
        self.calls[key] += 1
        for rule in self.failures:
            if rule.times > 0 and rule.predicate(request):
                rule.times -= 1
                if rule.exc is not None:
                    raise rule.exc("simulated", request=request)  # type: ignore[call-arg]
                return httpx.Response(rule.status or 500, headers=rule.headers, json={"error": "simulated"})
        q = parse_qs(url.query)
        host = url.hostname or ""
        if host in ("id.twitch.tv", "id.kick.com") and url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": f"tok-{host}", "expires_in": 3600, "token_type": "bearer"}
            )
        if host == "api.twitch.tv":
            return self._twitch(url.path, q, request)
        if host == "api.kick.com":
            return self._kick(url.path, q, request)
        if host == "www.googleapis.com" and url.path.startswith("/youtube/v3/"):
            return self._youtube(url.path.removeprefix("/youtube/v3"), q, request)
        if host in {
            "openapi.chzzk.naver.com",
            "api.chzzk.naver.com",
            "api.steampowered.com",
            "chapi.sooplive.co.kr",
            "ta.bigo.tv",
            "www.nimo.tv",
            "rumble.com",
        }:
            return self._extra_platform(host, url.path, q, request)
        if host == "api.search.brave.com":
            query = q.get("q", [""])[0]
            return httpx.Response(
                200, json={"web": {"results": [{"url": u} for u in self.brave.get(query, [])]}}
            )
        if str(request.url) in self.images:
            return httpx.Response(
                200, headers={"Content-Type": "image/png"}, content=self.images[str(request.url)]
            )
        return httpx.Response(404, json={"error": "not found"})

    def _auth_ok(self, request: httpx.Request) -> bool:
        return request.headers.get("Authorization", "").startswith("Bearer tok-")

    def _twitch(self, path: str, q: dict[str, list[str]], request: httpx.Request) -> httpx.Response:
        if not self._auth_ok(request) or not request.headers.get("Client-Id"):
            return httpx.Response(401, json={"error": "Unauthorized"})
        if path == "/helix/users":
            logins = [x.lower() for x in q.get("login", [])]
            if len(logins) + len(q.get("id", [])) > 100:
                return httpx.Response(400, json={"error": "too many"})
            # Real Helix behaviour: ONE invalid login rejects the whole request.
            if any(not TWITCH_LOGIN_RULE.match(x) for x in logins):
                return httpx.Response(
                    400,
                    json={"error": "Bad Request", "message": "Invalid login names, emails or IDs in request"},
                )
            data = [
                {k: v for k, v in self.twitch[x].items() if not k.startswith("_")}
                for x in logins
                if x in self.twitch
            ]
            return httpx.Response(200, json={"data": data})
        if path == "/helix/channels":
            ids = set(q.get("broadcaster_id", []))
            return httpx.Response(
                200, json={"data": [u["_channel"] for u in self.twitch.values() if u["id"] in ids]}
            )
        if path == "/helix/search/channels":
            query = q.get("query", [""])[0].lower()
            first = int(q.get("first", ["20"])[0])
            hits = []
            for u in self.twitch.values():
                score = max(fuzz.ratio(query, u["login"]), fuzz.ratio(query, u["display_name"].lower()))
                if query in u["login"] or score >= 70:
                    hits.append((score, u))
            hits.sort(key=lambda t: -t[0])
            data = [
                {
                    "broadcaster_login": u["login"],
                    "display_name": u["display_name"],
                    "id": u["id"],
                    "game_name": u["_channel"]["game_name"],
                    "is_live": False,
                    "tags": [],
                    "title": "",
                    "broadcaster_language": u["_channel"]["broadcaster_language"],
                    "thumbnail_url": "",
                }
                for _, u in hits[:first]
            ]
            return httpx.Response(200, json={"data": data, "pagination": {}})
        return httpx.Response(404, json={"error": "Not Found"})

    def _kick(self, path: str, q: dict[str, list[str]], request: httpx.Request) -> httpx.Response:
        if not self._auth_ok(request):
            return httpx.Response(401, json={"message": "Unauthorized"})
        if path == "/public/v1/channels":
            slugs = [s.lower() for s in q.get("slug", [])]
            if len(slugs) > 50 or any(len(s) > 25 for s in slugs):
                return httpx.Response(400, json={"message": "invalid slug param"})
            data = [
                {k: v for k, v in self.kick[s].items() if not k.startswith("_")}
                for s in slugs
                if s in self.kick
            ]
            return httpx.Response(200, json={"data": data, "message": "OK"})
        if path == "/public/v1/users":
            ids = {int(i) for i in q.get("id", [])}
            data = [c["_user"] for c in self.kick.values() if c["_user"]["user_id"] in ids]
            return httpx.Response(200, json={"data": data, "message": "OK"})
        return httpx.Response(404, json={"message": "Not Found"})

    def _youtube(self, path: str, q: dict[str, list[str]], request: httpx.Request) -> httpx.Response:
        key = request.headers.get("X-goog-api-key") or ""
        if (key not in self.youtube_keys) if self.youtube_keys is not None else key in ("", "wrong"):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": "API key not valid. Please pass a valid API key.",
                        "errors": [{"reason": "badRequest"}],
                        "details": [{"reason": "API_KEY_INVALID"}],
                    }
                },
            )
        if path == "/channels":
            if "forHandle" in q:
                handle = q["forHandle"][0].lstrip("@").lower()
                items = [c for c in self.youtube.values() if c["snippet"]["customUrl"] == "@" + handle]
            else:
                ids = q.get("id", [""])[0].split(",")
                items = [self.youtube[i] for i in ids if i in self.youtube]
            body: dict[str, Any] = {
                "kind": "youtube#channelListResponse",
                "pageInfo": {"totalResults": len(items)},
            }
            if items:  # like the real API: no "items" key at all when nothing matched
                body["items"] = items
            return httpx.Response(200, json=body)
        if path == "/search":
            query = q.get("q", [""])[0].lower()
            hits = []
            for c in self.youtube.values():
                name = c["snippet"]["customUrl"].lstrip("@")
                score = max(fuzz.ratio(query, name), fuzz.ratio(query, c["snippet"]["title"].lower()))
                if query in name or score >= 70:
                    hits.append((score, c))
            hits.sort(key=lambda t: -t[0])
            return httpx.Response(
                200,
                json={
                    "kind": "youtube#searchListResponse",
                    "items": [
                        {
                            "id": {"kind": "youtube#channel", "channelId": c["id"]},
                            "snippet": {"channelId": c["id"]},
                        }
                        for _, c in hits[: int(q.get("maxResults", ["5"])[0])]
                    ],
                },
            )
        return httpx.Response(404, json={"error": {"code": 404}})

    def _extra_platform(
        self, host: str, path: str, q: dict[str, list[str]], request: httpx.Request
    ) -> httpx.Response:
        ok = lambda given, want: given == want if self.keys_checked else given not in ("", "wrong", None)  # noqa: E731
        if host == "openapi.chzzk.naver.com" and path == "/open/v1/channels":
            if not (
                ok(request.headers.get("Client-Id"), "test-chzzk-id")
                and ok(request.headers.get("Client-Secret"), "test-chzzk-secret")
            ):
                return httpx.Response(401, json={"code": 401, "message": "INVALID_CLIENT"})
            data = [
                {
                    "channelId": c["id"],
                    "channelName": c["name"],
                    "channelImageUrl": c["image"],
                    "followerCount": 1,
                    "verifiedMark": False,
                }
                for cid in q.get("channelIds", [])
                if (c := self.extra["chzzk"].get(cid))
            ]
            return httpx.Response(200, json={"code": 200, "message": None, "content": {"data": data}})
        if host == "api.chzzk.naver.com":
            chz = self.extra["chzzk"]
            if path.startswith("/service/v1/channels/"):
                c = chz.get(path.rsplit("/", 1)[-1])
                content = (
                    {"channelId": c["id"], "channelName": c["name"], "channelDescription": c["bio"]}
                    if c
                    else {"channelId": None}
                )
                return httpx.Response(200, json={"code": 200, "message": None, "content": content})
            if path == "/service/v1/search/channels":
                kw = q.get("keyword", [""])[0].lower()
                hits = [
                    c
                    for c in chz.values()
                    if kw in c["name"].lower() or fuzz.ratio(kw, c["name"].lower()) >= 70
                ]
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "content": {
                            "size": len(hits),
                            "data": [
                                {"channel": {"channelId": c["id"], "channelName": c["name"]}} for c in hits
                            ],
                        },
                    },
                )
        if host == "api.steampowered.com":
            if not ok(q.get("key", [""])[0], "test-steam-key"):
                return httpx.Response(403, text="<html><body>Forbidden</body></html>")
            st = self.extra["steam"]
            if path == "/ISteamUser/ResolveVanityURL/v1/":
                c = st.get(q.get("vanityurl", [""])[0].lower())
                resp = {"steamid": c["id"], "success": 1} if c else {"success": 42, "message": "No match"}
                return httpx.Response(200, json={"response": resp})
            if path == "/ISteamUser/GetPlayerSummaries/v2/":
                ids = set(q.get("steamids", [""])[0].split(","))
                players = [
                    {
                        "steamid": c["id"],
                        "personaname": c["name"],
                        "avatarfull": c["image"],
                        "profileurl": f"https://steamcommunity.com/id/{c['handle']}/",
                    }
                    for c in st.values()
                    if c["id"] in ids
                ]
                return httpx.Response(200, json={"response": {"players": players}})
        if host == "chapi.sooplive.co.kr":
            c = self.extra["soop"].get(path.split("/")[2] if path.count("/") >= 3 else "")
            if not c:
                return httpx.Response(200, json={"code": 9000, "message": "no station"})
            return httpx.Response(
                200,
                json={
                    "profile_image": c["image"].replace("https:", ""),
                    "station": {
                        "user_id": c["handle"],
                        "user_nick": c["name"],
                        "station_no": int(c["id"]),
                        "station_title": "",
                        "display": {"profile_text": c["bio"]},
                    },
                    "broad": None,
                },
            )
        if host == "ta.bigo.tv":
            form = parse_qs(request.content.decode())
            c = self.extra["bigo"].get(form.get("siteId", [""])[0].lower())
            if not c:
                return httpx.Response(200, json={"code": 1, "msg": "fail", "data": None})
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "roomId": c["id"],
                        "clientBigoId": c["handle"],
                        "nick_name": c["name"],
                        "gameTitle": "",
                        "roomTopic": "",
                        "signature": c["bio"],
                        "image": c["image"],
                        "hls_src": "",
                    },
                },
            )
        if host == "www.nimo.tv":
            c = self.extra["nimo"].get(path.strip("/").lower())
            if not c:
                return httpx.Response(404, text="<html>Nimo TV</html>")
            info = {
                "roomId": int(c["id"]),
                "nickname": c["name"],
                "title": "live",
                "game": "",
                "anchorAnnouncement": c["bio"],
                "anchorAvatarUrl": c["image"],
                "lcid": 1033,
            }
            return httpx.Response(
                200, text=f"<html><script>var G_roomBaseInfo = {json.dumps(info)};</script></html>"
            )
        if host == "rumble.com":
            parts = path.strip("/").split("/")
            c = self.extra["rumble"].get(parts[-1].lower()) if len(parts) == 2 and parts[0] == "c" else None
            if not c:
                return httpx.Response(404, text="<html>404</html>")
            return httpx.Response(
                200,
                text=(
                    f'<html><head><meta property="og:title" content="{c["name"]} - Rumble">'
                    f'<meta property="og:description" content="{c["bio"]}">'
                    f'<meta property="og:image" content="{c["image"]}"></head></html>'
                ),
            )
        return httpx.Response(404, json={"error": "not found"})

    def api_calls(self, prefix: str) -> int:
        return sum(v for k, v in self.calls.items() if k.startswith(prefix))


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
