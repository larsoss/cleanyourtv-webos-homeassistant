"""The base of every CleanYourTV entity: one device per TV, updated the moment the TV reports a change."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import CytvConfigEntry
from .client import STANDBY_STATES
from .const import CONF_MAC, DOMAIN


class CytvEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: CytvConfigEntry, key: str) -> None:
        self._entry = entry
        self._data = entry.runtime_data
        self._client = entry.runtime_data.client
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        mac = entry.data.get(CONF_MAC)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))} if mac else set(),
            manufacturer="LG",
            model=self._client.model or "webOS TV with CleanYourTV",
            name=entry.title,
            # the device page's "Visit" opens the remote page for this TV
            configuration_url=f"homeassistant://cleanyourtv-remote?entry={entry.entry_id}",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self.async_write_ha_state))

    @property
    def tv_on(self) -> bool:
        """The TV is on (its screen may be dark): it answers and is not in standby."""
        return self._client.connected and self._client.power_state not in STANDBY_STATES
