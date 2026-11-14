"""The little of Jellyfin's API that "put on <title>" needs (https://api.jellyfin.org).

The server is asked with an API key (Jellyfin > Dashboard > API keys), which goes in the Authorization header. An API key belongs to
the server, not to a person, so every call that is about what someone watched carries the user id as well.

  GET  /Users                                          the people on the server, to pick whose library is searched
  GET  /Items?searchTerm=…&userId=…                    find a series or a film by its name
  GET  /Shows/NextUp?userId=…[&seriesId=…]             the episode to watch next, of one series or of them all
  GET  /UserItems/Resume?userId=…                      films and episodes that were started and not finished
  GET  /Items/<id>?userId=…                            one item, to play it by its id
  GET  /Items/<id>/Images/Primary                      its poster
  GET  /Shows/<id>/Episodes?userId=…&season=…          an episode by its number, and the first unwatched one
  GET  /Sessions                                       what is signed in; the TV's app is one of these while it is open
  POST /Sessions/<id>/Playing?playCommand=PlayNow      play it there, from a position in ticks (10 000 000 of them to a second)

This module has no Home Assistant imports, so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

TIMEOUT_S = 15
SEARCH_KINDS = "Series,Movie"
# a last resort when the address and the name do not tell: clients that only exist on a TV ("jellyfin" is in every client's name)
TV_CLIENTS = ("webos", "litefin", "moonfin", "lg ")


async def async_find_servers(timeout: float = 1.2) -> list[dict[str, str]]:
    """Jellyfin servers on the network, as they answer the question Jellyfin's own clients broadcast on UDP 7359.

    Returns [{name, url}]. It is only used to fill the address in for the person setting this up; nothing is contacted.
    """
    loop = asyncio.get_running_loop()
    found: dict[str, dict[str, str]] = {}

    class Ask(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            try:
                got = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                return
            url = clean_url(str(got.get("Address") or f"http://{addr[0]}:8096"))
            if url:
                found[url] = {"name": str(got.get("Name") or url), "url": url}

    transport = None
    try:
        transport, _ = await loop.create_datagram_endpoint(Ask, family=socket.AF_INET, allow_broadcast=True)
        transport.sendto(b"who is JellyfinServer?", ("255.255.255.255", 7359))
        await asyncio.sleep(timeout)
    except OSError as err:
        _LOGGER.debug("looking for Jellyfin servers failed: %s", err)
    finally:
        if transport:
            transport.close()
    return sorted(found.values(), key=lambda s: s["name"].lower())


def resume_ticks(item: dict[str, Any] | None) -> int:
    """Where this was left, in Jellyfin's ticks; 0 when it was never started or was watched to the end."""
    data = (item or {}).get("UserData") or {}
    try:
        ticks = int(data.get("PlaybackPositionTicks") or 0)
    except (TypeError, ValueError):
        return 0
    return 0 if ticks <= 0 or data.get("Played") else ticks


def _ip_of(endpoint: Any) -> str:
    """The address out of "192.168.1.10:54321", "[::1]:5", "::ffff:127.0.0.1"."""
    t = str(endpoint or "").strip().lower()
    if t.startswith("["):
        t = t[1:].split("]")[0]
    elif t.count(":") == 1:
        t = t.split(":")[0]
    return t.removeprefix("::ffff:")


class JellyfinError(Exception):
    """The server did not answer, or refused."""


class JellyfinAuthError(JellyfinError):
    """The API key is not (or no longer) accepted."""


def clean_url(url: str) -> str:
    """http://host:8096 from what someone typed (a trailing slash or /web/index.html is dropped)."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    p = urlsplit(u)
    path = p.path
    for tail in ("/web/index.html", "/web", "/index.html"):
        path = path.removesuffix(tail)
    return urlunsplit((p.scheme, p.netloc, path.rstrip("/"), "", ""))


class Jellyfin:
    """One Jellyfin server, asked with an API key."""

    def __init__(self, session: aiohttp.ClientSession, url: str, key: str, user_id: str = "") -> None:
        self._session = session
        self.url = clean_url(url)
        self._key = key
        self.user_id = user_id

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f'MediaBrowser Token="{self._key}"', "Accept": "application/json"}

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._call("GET", path, params)

    async def _call(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        q = "&".join(f"{k}={quote(str(v))}" for k, v in (params or {}).items() if v not in (None, ""))
        url = f"{self.url}{path}" + (("?" if "?" not in path else "&") + q if q else "")
        try:
            async with asyncio.timeout(TIMEOUT_S):
                async with self._session.request(method, url, headers=self._headers) as resp:
                    if resp.status in (401, 403):
                        raise JellyfinAuthError("Jellyfin does not accept the API key")
                    if resp.status >= 400:
                        raise JellyfinError(f"Jellyfin answered {resp.status}")
                    if resp.status == 204:
                        return {}
                    text = await resp.text()
                    if not text.strip():
                        return {}
                    return await resp.json(content_type=None)
        except JellyfinError:
            raise
        except (TimeoutError, aiohttp.ClientError, OSError, ValueError) as err:
            raise JellyfinError(f"Jellyfin did not answer: {err}") from err

    async def async_users(self) -> list[dict[str, str]]:
        """Everyone on the server: [{id, name}]."""
        out = await self._get("/Users")
        return [{"id": u["Id"], "name": u.get("Name") or u["Id"]} for u in out or [] if u.get("Id")]

    async def async_search(self, title: str, limit: int = 8) -> list[dict[str, Any]]:
        """Series and films whose name holds the words, the closest first."""
        out = await self._get(
            "/Items",
            searchTerm=title,
            userId=self.user_id,
            includeItemTypes=SEARCH_KINDS,
            recursive="true",
            limit=limit,
            fields="ProviderIds,UserData",
        )
        items = [i for i in (out or {}).get("Items") or [] if i.get("Id")]
        want = title.strip().lower()
        # an exact name first, then one that starts with what was asked, then the server's own order
        items.sort(key=lambda i: (str(i.get("Name", "")).lower() != want, not str(i.get("Name", "")).lower().startswith(want)))
        return items

    async def async_continue(self, limit: int = 24) -> dict[str, list[dict[str, Any]]]:
        """What there is to carry on with: {"series": [episodes], "movies": [films]}.

        Series come from Next Up, which is the episode to watch next of every series, newest first. Films come from Resume, the
        ones that were started and not finished; an episode in Resume is already in Next Up, so only films are taken from it.
        """
        series, resume = await asyncio.gather(
            self._get("/Shows/NextUp", userId=self.user_id, limit=limit, fields="UserData"),
            self._get("/UserItems/Resume", userId=self.user_id, limit=limit, includeItemTypes="Movie", fields="UserData"),
            return_exceptions=True,
        )
        out: dict[str, list[dict[str, Any]]] = {"series": [], "movies": []}
        for key, got in (("series", series), ("movies", resume)):
            if isinstance(got, BaseException):
                if isinstance(got, JellyfinAuthError):
                    raise got
                _LOGGER.debug("Jellyfin did not answer for %s: %s", key, got)
                continue
            out[key] = [i for i in (got or {}).get("Items") or [] if i.get("Id")]
        return out

    async def async_item(self, item_id: str) -> dict[str, Any] | None:
        """One item by its id, with where it was left."""
        out = await self._get(f"/Items/{quote(item_id)}", userId=self.user_id, fields="UserData")
        return out if isinstance(out, dict) and out.get("Id") else None

    async def async_poster(self, item_id: str, height: int = 450) -> tuple[bytes | None, str]:
        """The poster of an item, as bytes; images need no key, but going through the server keeps it out of the browser."""
        url = f"{self.url}/Items/{quote(item_id)}/Images/Primary?maxHeight={int(height)}&quality=90"
        try:
            async with asyncio.timeout(TIMEOUT_S):
                async with self._session.get(url, headers=self._headers) as resp:
                    if resp.status != 200:
                        return None, ""
                    return await resp.read(), resp.headers.get("Content-Type", "image/jpeg")
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            _LOGGER.debug("no poster for %s: %s", item_id, err)
            return None, ""

    async def async_next_up(self, series_id: str) -> dict[str, Any] | None:
        """The episode to watch next of a series (where you stopped, or the first one)."""
        out = await self._get("/Shows/NextUp", userId=self.user_id, seriesId=series_id, limit=1, fields="UserData")
        items = (out or {}).get("Items") or []
        if items:
            return items[0]
        out = await self._get(f"/Shows/{series_id}/Episodes", userId=self.user_id, limit=1, startIndex=0, fields="UserData")
        items = (out or {}).get("Items") or []
        return items[0] if items else None

    async def async_episode(self, series_id: str, season: int | None, episode: int | None) -> dict[str, Any] | None:
        """One episode by its numbers; without an episode number the first of that season."""
        out = await self._get(f"/Shows/{series_id}/Episodes", userId=self.user_id, season=season, fields="UserData")
        items = (out or {}).get("Items") or []
        if episode is None:
            return items[0] if items else None
        for i in items:
            if i.get("IndexNumber") == episode:
                return i
        return None

    async def async_sessions(self) -> list[dict[str, Any]]:
        """What is signed in now."""
        out = await self._get("/Sessions")
        return list(out or [])

    def tv_session(self, sessions: list[dict[str, Any]], device: str = "", host: str = "") -> dict[str, Any] | None:
        """The session of the Jellyfin app on the TV, and not of a phone that happens to be signed in.

        Jellyfin says where a session connects from, so the TV's own address is the surest sign; then the TV's name in the device,
        then a client that only runs on a TV. A session that does not take commands is never one of these.
        """
        able = [s for s in sessions if s.get("SupportsRemoteControl") and s.get("Id")]
        ip = (host or "").strip().lower()
        if ip:
            for s in able:
                if _ip_of(s.get("RemoteEndPoint")) == ip:
                    return s
        name = (device or "").strip().lower()
        if name:
            for s in able:
                if name in str(s.get("DeviceName", "")).lower():
                    return s
        for s in able:
            text = (str(s.get("Client", "")) + " " + str(s.get("DeviceName", "")) + " ").lower()
            if any(w in text for w in TV_CLIENTS):
                return s
        return None

    async def async_play(self, session_id: str, item_id: str, ticks: int = 0) -> None:
        """Play it on that session, from the start or from a position in ticks."""
        params: dict[str, Any] = {"playCommand": "PlayNow", "itemIds": item_id}
        if ticks > 0:
            params["startPositionTicks"] = ticks
        await self._call("POST", f"/Sessions/{session_id}/Playing", params)
