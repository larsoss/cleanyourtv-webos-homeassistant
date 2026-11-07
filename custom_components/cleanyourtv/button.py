"""Buttons for the power calls of the TV: screen off and on, standby, restart and shut down."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CytvConfigEntry
from .client import CytvError
from .entity import CytvEntity

# (key, power action, device class, enabled by default): a shut-down TV comes back only with its own remote, so that one starts off
BUTTONS = (
    ("screen_off", "off", None, True),
    ("screen_on", "on", None, True),
    ("standby", "standby", None, True),
    ("restart", "reboot", ButtonDeviceClass.RESTART, True),
    ("shut_down", "shutdown", None, False),
)


async def async_setup_entry(hass: HomeAssistant, entry: CytvConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add(CytvPowerButton(entry, *b) for b in BUTTONS)


class CytvPowerButton(CytvEntity, ButtonEntity):
    def __init__(self, entry: CytvConfigEntry, key: str, action: str, device_class, enabled: bool) -> None:
        super().__init__(entry, key)
        self._action = action
        self._attr_translation_key = key
        self._attr_device_class = device_class
        self._attr_entity_registry_enabled_default = enabled

    @property
    def available(self) -> bool:
        return self._client.connected

    async def async_press(self) -> None:
        try:
            await self._client.async_power(self._action)
        except CytvError as err:
            raise HomeAssistantError(str(err)) from err
