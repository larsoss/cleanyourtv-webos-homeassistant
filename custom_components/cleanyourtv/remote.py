"""The remote control: every key of the TV remote, and the actions for text, apps, channels, power and the pointer.

remote.send_command takes key names (UP, ENTER, HOME, VOLUMEUP, RED, 1, ...) and a few words of its own:
  text:<text>   types into the text field open on the TV      enter / delete / click
  launch:<id>   opens an app (com.webos.app.hdmi1, netflix)  live:<number>  Live TV on that channel
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

import voluptuous as vol
from homeassistant.components.remote import ATTR_DELAY_SECS, ATTR_NUM_REPEATS, DEFAULT_DELAY_SECS, RemoteEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CytvConfigEntry, refresh_lists
from .client import KEYS, POWER_ACTIONS, CytvError
from .const import DOMAIN
from .entity import CytvEntity
from .media_player import turn_on


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([CytvTVEntity(entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "send_text", {vol.Required("text"): cv.string, vol.Optional("enter", default=False): cv.boolean}, "async_send_text"
    )
    platform.async_register_entity_service("launch_app", {vol.Required("app_id"): vol.Match(r"^[\w.\-]+$")}, "async_launch_app")
    platform.async_register_entity_service(
        "live_channel", {vol.Required("channel"): vol.All(vol.Coerce(int), vol.Range(1, 99999))}, "async_live_channel"
    )
    platform.async_register_entity_service("tv_power", {vol.Required("action"): vol.In(POWER_ACTIONS)}, "async_tv_power")
    platform.async_register_entity_service(
        "pointer",
        {
            vol.Optional("dx", default=0): vol.All(vol.Coerce(int), vol.Range(-500, 500)),
            vol.Optional("dy", default=0): vol.All(vol.Coerce(int), vol.Range(-500, 500)),
            vol.Optional("click", default=False): cv.boolean,
            vol.Optional("scroll", default=0): vol.All(vol.Coerce(int), vol.Range(-50, 50)),
        },
        "async_pointer",
    )
    platform.async_register_entity_service("refresh_lists", None, "async_refresh_lists")


class CytvTVEntity(CytvEntity, RemoteEntity):
    _attr_translation_key = "remote"
    _unrecorded_attributes = frozenset({"keys", "apps", "inputs"})

    def __init__(self, entry: CytvConfigEntry) -> None:
        super().__init__(entry, "remote")

    @property
    def is_on(self) -> bool:
        return self.tv_on

    async def _do(self, coro) -> None:
        try:
            await coro
        except CytvError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await turn_on(self)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._do(self._client.async_power("standby"))

    def _command(self, cmd: str):
        c = str(cmd).strip()
        word, _, arg = c.partition(":")
        w = word.strip().lower()
        if arg and w == "text":
            return self._client.async_text(arg)
        if arg and w == "launch":
            return self._client.async_launch(arg.strip())
        if arg and w == "live":
            if not arg.strip().isdigit():
                raise ServiceValidationError(f"not a channel number: {arg}")
            return self._client.async_live(int(arg))
        if not arg and w == "enter":
            return self._client.async_enter()
        if not arg and w == "delete":
            return self._client.async_delete(1)
        if not arg and w == "click":
            return self._client.async_click()
        if c.upper() in KEYS:
            return self._client.async_key(c.upper())
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_command", translation_placeholders={"command": c})

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        repeats = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        cmds = list(command)
        for c in cmds:  # every word is checked before the first one is sent
            self._command(c).close()
        first = True
        for _ in range(repeats):
            for c in cmds:
                if not first and delay:
                    await asyncio.sleep(delay)
                first = False
                await self._do(self._command(c))

    async def async_send_text(self, text: str, enter: bool = False) -> None:
        await self._do(self._client.async_text(text))
        if enter:
            await self._do(self._client.async_enter())

    async def async_launch_app(self, app_id: str) -> None:
        await self._do(self._client.async_launch(app_id))

    async def async_live_channel(self, channel: int) -> None:
        await self._do(self._client.async_live(channel))

    async def async_tv_power(self, action: str) -> None:
        await self._do(self._client.async_power(action))

    async def async_pointer(self, dx: int = 0, dy: int = 0, click: bool = False, scroll: int = 0) -> None:
        if dx or dy:
            await self._do(self._client.async_move(dx, dy))
        if click:
            await self._do(self._client.async_click())
        if scroll:
            await self._do(self._client.async_scroll(scroll))

    async def async_refresh_lists(self) -> None:
        refresh_lists(self.hass, self._entry)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "keys": KEYS,
            "apps": {a["title"]: a["id"] for a in self._data.apps},
            "inputs": {i.get("title") or i["appId"]: i["appId"] for i in self._data.inputs},
            "channels": len(self._data.channels),
        }
