"""Platforms without an official API for looking up other users' channels. They read the same
public data the platform's own website loads for anonymous visitors (no key, no login):

  SOOP   GET  https://chapi.sooplive.co.kr/api/{id}/station        JSON (station.user_id, user_nick,
                                                                   display.profile_text, profile_image)
  Bigo   POST https://ta.bigo.tv/official_website/studio/getInternalStudioInfo  siteId={bigo id}
                                                                   {"code":0,"data":{clientBigoId, …}}
  Nimo   GET  https://www.nimo.tv/{alias}                         HTML with G_roomBaseInfo = {...}
  Rumble GET  https://rumble.com/c/{name} (then /user/{name})     HTML <meta og:*> tags

These are undocumented and can change without notice. Each is opt-in on the API keys screen,
lookups are rate-limited, and an unexpected answer is a retryable row error — never a
"not found". None of them has a usable search, so accounts are found by exact name, name
variants and links in bios (like Kick).
"""

from __future__ import annotations

import re
from typing import Any

from app.platforms.base import Profile
from app.platforms.errors import UnexpectedResponseError
from app.platforms.simple import SimpleAdapter, https_url, js_object, meta_tags, public_call


class SoopAdapter(SimpleAdapter):
    platform = "soop"
    variant_budget = 12
    handle_pattern = re.compile(r"^[a-z0-9_]{3,20}$")
    url_hosts = ("sooplive.co.kr", "sooplive.com", "afreecatv.com")
    url_format = "https://ch.sooplive.co.kr/{}"
    NS = "soop"

    async def lookup(self, handle: str) -> Profile | None:
        body = await public_call(
            self.http.get_json(f"api/{handle}/station", endpoint_category="soop.station"), "soop"
        )
        if body is None:
            return None
        if not isinstance(body, dict):
            raise UnexpectedResponseError("SOOP station returned an unexpected response", platform="soop")
        station = body.get("station")
        if not isinstance(station, dict) or not station.get("user_id"):
            return None  # unknown ids come back without a station
        display: dict[str, Any] = station["display"] if isinstance(station.get("display"), dict) else {}
        broad: dict[str, Any] = body["broad"] if isinstance(body.get("broad"), dict) else {}
        uid = str(station["user_id"]).lower()
        return Profile(
            platform=self.platform,
            username=uid,
            user_id=str(station.get("station_no") or uid),
            display_name=station.get("user_nick") or None,
            description="\n".join(
                t
                for t in (display.get("profile_text"), station.get("station_title"))
                if isinstance(t, str) and t
            )
            or None,
            profile_image_url=https_url(body.get("profile_image")),
            profile_url=self.profile_url(uid),
            stream_title=broad.get("broad_title") or None,
            source="soop-public-station",
        )


class BigoAdapter(SimpleAdapter):
    platform = "bigo"
    variant_budget = 8
    handle_pattern = re.compile(r"^[a-z0-9._-]{2,32}$")
    url_hosts = ("bigo.tv",)
    url_format = "https://www.bigo.tv/{}"
    NS = "bigo"

    async def lookup(self, handle: str) -> Profile | None:
        body = await public_call(
            self.http.request_json(
                "POST",
                "official_website/studio/getInternalStudioInfo",
                data={"siteId": handle, "verify": ""},
                endpoint_category="bigo.studio_info",
            ),
            "bigo",
        )
        if not isinstance(body, dict) or "code" not in body:
            raise UnexpectedResponseError("Bigo returned an unexpected response", platform="bigo")
        data = body.get("data")
        if body.get("code") != 0 or not isinstance(data, dict) or not data.get("clientBigoId"):
            return None
        bigo_id = str(data["clientBigoId"]).lower()
        return Profile(
            platform=self.platform,
            username=bigo_id,
            user_id=str(data.get("uid") or data.get("roomId") or bigo_id),
            display_name=data.get("nick_name") or data.get("nickName") or None,
            description=data.get("signature") or None,
            profile_image_url=https_url(data.get("image") or data.get("head_url")),
            profile_url=self.profile_url(bigo_id),
            category=data.get("gameTitle") or None,
            stream_title=data.get("roomTopic") or None,
            source="bigo-public-studio",
        )


class NimoAdapter(SimpleAdapter):
    platform = "nimo"
    variant_budget = 6
    handle_pattern = re.compile(r"^[a-z0-9._-]{2,40}$")
    url_hosts = ("nimo.tv",)
    url_format = "https://www.nimo.tv/{}"
    NS = "nimo"

    async def lookup(self, handle: str) -> Profile | None:
        page = await public_call(self.http.get_text(handle, endpoint_category="nimo.room_page"), "nimo")
        if page is None:
            return None
        info = js_object(page, "G_roomBaseInfo")
        if info is None:
            if "nimo" not in page.lower():
                raise UnexpectedResponseError("Nimo TV returned an unexpected page", platform="nimo")
            return None  # the site answers unknown names with a generic page
        nickname = info.get("nickname") or info.get("anchorName")
        if not nickname:
            return None
        room = str(info.get("roomId") or info.get("id") or "")
        return Profile(
            platform=self.platform,
            username=handle,
            user_id=room or None,
            display_name=str(nickname),
            description=info.get("anchorAnnouncement") or info.get("roomAnnouncement") or None,
            profile_image_url=https_url(
                info.get("anchorAvatarUrl") or info.get("avatarUrl") or info.get("headImg")
            ),
            profile_url=self.profile_url(handle),
            category=info.get("game") or info.get("roomTypeName") or None,
            stream_title=info.get("title") or info.get("roomTheme") or None,
            language=_lang(info.get("lcid")),
            source="nimo-public-page",
        )


class RumbleAdapter(SimpleAdapter):
    platform = "rumble"
    variant_budget = 6
    handle_pattern = re.compile(r"^[a-z0-9_-]{2,40}$")
    url_hosts = ("rumble.com",)
    url_format = "https://rumble.com/c/{}"
    NS = "rumble"

    async def lookup(self, handle: str) -> Profile | None:
        for kind in ("c", "user"):
            page = await public_call(
                self.http.get_text(f"{kind}/{handle}", endpoint_category="rumble.channel_page"), "rumble"
            )
            if page is None:
                continue
            meta = meta_tags(page)
            title = _strip_site(meta.get("og:title") or _title(page))
            if not title:
                raise UnexpectedResponseError("Rumble returned an unexpected page", platform="rumble")
            return Profile(
                platform=self.platform,
                username=handle,
                display_name=title,
                description=meta.get("og:description") or meta.get("description") or None,
                profile_image_url=https_url(meta.get("og:image")),
                profile_url=f"https://rumble.com/{kind}/{handle}",
                source="rumble-public-page",
            )
        return None


def _title(page: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _strip_site(title: str) -> str:
    return re.sub(r"\s*[-|–]\s*Rumble\s*$", "", title or "", flags=re.IGNORECASE).strip()


def _lang(lcid: Any) -> str | None:
    return {1033: "en", 1066: "vi", 1041: "ja", 1046: "pt", 3082: "es", 1057: "id", 1054: "th"}.get(
        int(lcid) if isinstance(lcid, (int, str)) and str(lcid).isdigit() else -1
    )
