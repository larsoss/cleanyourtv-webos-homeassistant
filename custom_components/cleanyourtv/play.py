"""Putting a title on the TV: from a name or an id to playing it, wherever the ask comes from.

The remote's play action, the "carry on watching" select and the remote card all land here. The steps are always the same: find the
item on the Jellyfin server, make sure the TV is on, make sure a Jellyfin client on it is signed in to the server, and tell the
server to play it there (from where it was left).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import CONF_JF_APP, CONF_JF_KEY, CONF_JF_URL, CONF_JF_USER, DEFAULT_JF_APP, DOMAIN, JF_CLIENTS, PLAY_WAIT_S
from .jellyfin import Jellyfin, JellyfinAuthError, JellyfinError, resume_ticks

if TYPE_CHECKING:
    from . import CytvConfigEntry

_LOGGER = logging.getLogger(__name__)

ON_WAIT_S = 45  # how long a TV that was off may take to answer after Wake-on-LAN


def jellyfin_of(hass: HomeAssistant, entry: CytvConfigEntry) -> Jellyfin | None:
    """The Jellyfin server of this TV, or None when it was not set up in the options."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    o = entry.options
    if not (o.get(CONF_JF_URL) and o.get(CONF_JF_KEY)):
        return None
    return Jellyfin(async_get_clientsession(hass), o[CONF_JF_URL], o[CONF_JF_KEY], o.get(CONF_JF_USER, ""))


async def async_play(
    hass: HomeAssistant,
    entry: CytvConfigEntry,
    *,
    title: str = "",
    item_id: str = "",
    season: int | None = None,
    episode: int | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Play a title (by name, or an item by its id) on the TV. Returns the item that was played."""
    jf = jellyfin_of(hass, entry)
    if jf is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_jellyfin")
    try:
        item = await _find(jf, title, item_id, season, episode)
        ticks = resume_ticks(item) if resume else 0
        await _turn_on(hass, entry)
        session = await _session(hass, entry, jf)
        await jf.async_play(session["Id"], item["Id"], ticks)
    except JellyfinAuthError as err:
        raise HomeAssistantError(str(err)) from err
    except JellyfinError as err:
        raise HomeAssistantError(str(err)) from err
    return item


async def _find(jf: Jellyfin, title: str, item_id: str, season: int | None, episode: int | None) -> dict[str, Any]:
    """The film, or the episode of the series: the one asked for by id, or by name and then the episode to watch next."""
    if item_id:
        item = await jf.async_item(item_id)
        if not item:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_found", translation_placeholders={"title": item_id}
            )
        return item
    found = await jf.async_search(title)
    if not found:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_found", translation_placeholders={"title": title})
    item = found[0]
    if item.get("Type") != "Series":
        return item
    name = str(item.get("Name") or title)
    got = (
        await jf.async_episode(item["Id"], season, episode)
        if season is not None or episode is not None
        else await jf.async_next_up(item["Id"])
    )
    if not got:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_episode", translation_placeholders={"title": name})
    return got


async def _turn_on(hass: HomeAssistant, entry: CytvConfigEntry) -> None:
    """A TV that does not answer is woken first: picking something to watch should not need the remote as well."""
    from .media_player import turn_on

    client = entry.runtime_data.client
    if client.connected:
        return
    await turn_on(hass, entry)
    end = hass.loop.time() + ON_WAIT_S
    while hass.loop.time() < end:
        await asyncio.sleep(2)
        if client.connected:
            return
    raise HomeAssistantError(f"the TV did not answer within {ON_WAIT_S} seconds of being woken")


def _app(entry: CytvConfigEntry, app: str) -> str:
    """The Jellyfin client to open: the chosen one, or another one that is on the TV when the chosen one is not installed."""
    ids = {a["id"] for a in entry.runtime_data.apps if a.get("id")}
    if not ids or app in ids:  # an empty list means the TV has not been read yet: just use what was chosen
        return app
    other = next((i for i in JF_CLIENTS if i in ids), "")
    if not other:
        return app
    _LOGGER.info("%s is not installed on the TV, opening %s (%s) instead", app, JF_CLIENTS[other], other)
    return other


async def _session(hass: HomeAssistant, entry: CytvConfigEntry, jf: Jellyfin) -> dict[str, Any]:
    """The Jellyfin client on the TV, opened first when it is not in front: a session takes a moment to sign in."""
    from homeassistant.const import CONF_HOST

    client = entry.runtime_data.client
    app = _app(entry, entry.options.get(CONF_JF_APP) or DEFAULT_JF_APP)
    model, host = client.model or "", entry.data.get(CONF_HOST, "")
    session = jf.tv_session(await jf.async_sessions(), model, host)
    if session:
        return session
    await client.async_action("launch", id=app)
    end = hass.loop.time() + PLAY_WAIT_S
    while hass.loop.time() < end:
        await asyncio.sleep(2)
        session = jf.tv_session(await jf.async_sessions(), model, host)
        if session:
            return session
    raise HomeAssistantError(
        f"{app} was opened on the TV but did not sign in to the Jellyfin server within {PLAY_WAIT_S} seconds; "
        "the app has to be signed in to the same server, and has to be a client the server can play on"
    )
