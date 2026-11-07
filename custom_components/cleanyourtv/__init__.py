"""CleanYourTV: a rooted LG webOS TV with CleanYourTV in Home Assistant, both ways (the TV pushes what it does)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .client import CytvAuthError, CytvError, CytvTV
from .const import CONF_MAC, CONF_TOKEN, DOMAIN, LISTS_REFRESH_S

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.MEDIA_PLAYER, Platform.REMOTE, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SIGNAL_LISTS = f"{DOMAIN}_lists_{{}}"


@dataclass
class CytvData:
    """What the entities of one TV share."""

    client: CytvTV
    apps: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    lists_task: asyncio.Task | None = None


type CytvConfigEntry = ConfigEntry[CytvData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The remote card's files and its WebSocket commands, once."""
    from .frontend import async_setup_frontend

    await async_setup_frontend(hass, str((await async_get_integration(hass, DOMAIN)).version))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry) -> bool:
    client = CytvTV(async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_TOKEN])
    data = CytvData(client)
    entry.runtime_data = data

    client.start()
    # A TV in standby (or off) does not answer: the entities still come up (off; Turn on sends Wake-on-LAN). Only a TV that answers and
    # refuses the token stops the set-up, so the user can pair again.
    await client.wait_first(5)
    if client.auth_failed:
        await client.stop()
        raise ConfigEntryAuthFailed("the TV no longer accepts Home Assistant: pair it again")

    @callback
    def _on_change() -> None:
        if client.auth_failed:
            entry.async_start_reauth(hass)
            return
        # the MAC address is kept, so Wake-on-LAN works after a restart of Home Assistant while the TV is off
        if client.connected and client.mac and client.mac != entry.data.get(CONF_MAC):
            hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_MAC: client.mac})
        if client.connected and (data.lists_task is None or data.lists_task.done()):
            data.lists_task = entry.async_create_background_task(hass, _refresh_lists(hass, entry), "cleanyourtv lists")

    entry.async_on_unload(client.add_listener(_on_change))
    entry.async_on_unload(client.stop)  # type: ignore[arg-type]
    options = dict(entry.options)

    async def _options_changed(hass: HomeAssistant, entry: CytvConfigEntry) -> None:
        # also called when the MAC address is stored: only a change of the options reloads
        if dict(entry.options) != options:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_options_changed))
    if client.connected:
        _on_change()

    from .frontend import card_secret

    card_secret(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def refresh_lists(hass: HomeAssistant, entry: CytvConfigEntry) -> None:
    """Read the lists again now (the refresh_lists action)."""
    data = entry.runtime_data
    if data.lists_task is not None and not data.lists_task.done():
        data.lists_task.cancel()
    if data.client.connected:
        data.lists_task = entry.async_create_background_task(hass, _refresh_lists(hass, entry), "cleanyourtv lists")


async def _refresh_lists(hass: HomeAssistant, entry: CytvConfigEntry) -> None:
    """Read the apps, inputs and Live TV channels now, and again every ten minutes while connected."""
    data = entry.runtime_data
    while data.client.connected:
        for name, fn in (("apps", data.client.async_apps), ("inputs", data.client.async_inputs), ("channels", data.client.async_channels)):
            try:
                setattr(data, name, await fn())
            except CytvAuthError:
                return
            except CytvError as err:
                _LOGGER.debug("reading %s failed: %s", name, err)
        async_dispatcher_send(hass, SIGNAL_LISTS.format(entry.entry_id))
        await asyncio.sleep(LISTS_REFRESH_S)


async def async_unload_entry(hass: HomeAssistant, entry: CytvConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    task = entry.runtime_data.lists_task
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: CytvConfigEntry) -> None:
    """The integration is deleted: the TV forgets this Home Assistant too (if it can be reached)."""
    client = CytvTV(async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_TOKEN])
    await client.async_unpair()
