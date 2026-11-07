"""The remote card (custom:cleanyourtv-remote): the Phone remote's own page, in a card, talking to the TV through this integration.

The card loads by itself: the integration serves frontend/ and adds the card's script to every dashboard (no resource to add by hand).
The page inside the card asks Home Assistant over its WebSocket API:
  cleanyourtv/card    {entity_id}                -> {entry_id, secret, model, mac}: which TV, and the key for its pictures
  cleanyourtv/action  {entry_id, action: {t,..}} -> {ok, error}: a key, text, the pointer, an app, a channel, a power call
  cleanyourtv/list    {entry_id, kind}           -> the apps, the inputs or the Live TV channels, as the Phone remote's page reads them
Pictures (channel logos, app icons) are <img> tags, which cannot carry Home Assistant's token: they are served at
/api/cleanyourtv/<entry_id>/... with the entry's own secret in ?t=, which only a signed-in user gets from cleanyourtv/card.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .client import CytvError
from .const import DOMAIN

STATIC_URL = "/cleanyourtv_static"
FRONTEND = Path(__file__).parent / "frontend"
CONF_CARD_SECRET = "card_secret"
# what the card may ask the TV to do (the add-on's actions); anything else is refused here
ACTIONS = ("key", "text", "del", "enter", "move", "click", "scroll", "launch", "live", "liveSetup", "tvpower", "volume", "mute")


async def async_setup_frontend(hass: HomeAssistant, version: str) -> None:
    """Once per Home Assistant start: the card's files, its script on every dashboard, the WebSocket commands and the picture view."""
    if hass.data.get(f"{DOMAIN}_frontend"):
        return
    hass.data[f"{DOMAIN}_frontend"] = True
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(FRONTEND), False)])
    add_extra_js_url(hass, f"{STATIC_URL}/cleanyourtv-remote.js?v={version}")
    websocket_api.async_register_command(hass, ws_card)
    websocket_api.async_register_command(hass, ws_action)
    websocket_api.async_register_command(hass, ws_list)
    hass.http.register_view(CytvPictureView())


def card_secret(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """The entry's own secret for the card's pictures, made once."""
    s = entry.data.get(CONF_CARD_SECRET)
    if not s:
        s = secrets.token_hex(16)
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_CARD_SECRET: s})
    return s


def _entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    e = hass.config_entries.async_get_entry(entry_id)
    if e is None or e.domain != DOMAIN or not hasattr(e, "runtime_data"):
        return None
    return e


@websocket_api.websocket_command({vol.Required("type"): "cleanyourtv/card", vol.Required("entity_id"): str})
@callback
def ws_card(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    ent = er.async_get(hass).async_get(msg["entity_id"])
    entry = _entry(hass, ent.config_entry_id) if ent and ent.config_entry_id else None
    if entry is None:
        connection.send_error(msg["id"], "not_found", "not a CleanYourTV entity")
        return
    client = entry.runtime_data.client
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "secret": card_secret(hass, entry),
            "model": client.model or entry.title,
            "mac": client.mac or entry.data.get("mac", ""),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "cleanyourtv/action", vol.Required("entry_id"): str, vol.Required("action"): dict})
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass, msg["entry_id"])
    action = dict(msg["action"])
    t = action.pop("t", None)
    action.pop("n", None)
    if entry is None or t not in ACTIONS:
        connection.send_result(msg["id"], {"ok": False, "error": "not allowed"})
        return
    try:
        await entry.runtime_data.client.async_action(t, **action)
    except CytvError as err:
        connection.send_result(msg["id"], {"ok": False, "error": str(err)})
        return
    connection.send_result(msg["id"], {"ok": True, "error": ""})


@websocket_api.websocket_command(
    {vol.Required("type"): "cleanyourtv/list", vol.Required("entry_id"): str, vol.Required("kind"): vol.In(["apps", "inputs", "live"])}
)
@websocket_api.async_response
async def ws_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "unknown TV")
        return
    client = entry.runtime_data.client
    try:
        if msg["kind"] == "apps":
            out: dict[str, Any] = {"apps": await client.async_apps()}
        elif msg["kind"] == "inputs":
            out = {"inputs": await client.async_inputs()}
        else:
            out = {"channels": await client.async_channels()}
    except CytvError as err:
        connection.send_result(msg["id"], {"error": str(err)})
        return
    connection.send_result(msg["id"], out)


class CytvPictureView(HomeAssistantView):
    """Channel logos and app icons for the card: /api/cleanyourtv/<entry_id>/api/logo/<n> and .../icon/<app id>, with ?t=<secret>."""

    url = "/api/cleanyourtv/{entry_id}/{kind:api/logo|icon}/{item}"
    name = "api:cleanyourtv:picture"
    requires_auth = False  # an <img> cannot send the token: the entry's secret in ?t= stands in for it

    async def get(self, request: web.Request, entry_id: str, kind: str, item: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        entry = _entry(hass, entry_id)
        given = request.query.get("t", "")
        secret = entry.data.get(CONF_CARD_SECRET, "") if entry else ""
        if not entry or not secret or not hmac.compare_digest(given.encode(), secret.encode()):
            return web.Response(status=401)
        if kind == "icon":
            if not all(c.isalnum() or c in "._-" for c in item):
                return web.Response(status=404)
            path = f"/api/icon/{item}"
        else:
            if not item.isdigit():
                return web.Response(status=404)
            path = f"/api/logo/{int(item)}"
        body, ctype = await entry.runtime_data.client.async_picture(path)
        if body is None:
            return web.Response(status=404)
        return web.Response(body=body, content_type=(ctype or "image/png").split(";")[0], headers={"Cache-Control": "max-age=3600"})
